"""Nyers BKK-adatok mentése. Folyamatos futás csak külön kapcsolóval."""

import argparse
import gzip
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import uuid
import zipfile
import zlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

FORRASOK = {"VehiclePositions": 30, "TripUpdates": 30, "Alerts": 60}
MENETREND_URL = "https://go.bkk.hu/api/static/v1/public-gtfs/budapest_gtfs.zip"
MIN_KOZ = 10
MAX_RT = 50 * 1024 * 1024
MAX_GTFS = 500 * 1024 * 1024
TARTALEK = 2 * 1024 * 1024 * 1024
MAX_VARAKOZAS = 365 * 86400


def utc(ido):
    return datetime.fromtimestamp(ido, UTC).isoformat()


class LetoltesHiba(Exception):
    """A teljes URL és a kulcs helyett csak biztonságos hibaadatokat viszünk tovább."""

    def __init__(self, fajta, kod=None, varakozas=None):
        super().__init__(fajta)
        self.fajta = fajta
        self.kod = kod
        self.varakozas = varakozas


def retry_after(ertek, now=None):
    if not ertek:
        return None
    try:
        if str(ertek).strip().isdigit():
            return min(MAX_VARAKOZAS, int(ertek))
        datum = parsedate_to_datetime(ertek)
        if datum.tzinfo is None:
            datum = datum.replace(tzinfo=UTC)
        return min(MAX_VARAKOZAS, max(0, math.ceil(datum.timestamp() - (time.time() if now is None else now))))
    except (TypeError, ValueError, OverflowError):
        return None


class BiztonsagosAtiranyitas(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        regi = urlsplit(req.full_url)
        uj = urlsplit(newurl)
        # A kulcsot nem továbbítjuk másik kiszolgálónak, HTTPS-ről sem lépünk vissza.
        if uj.scheme != "https" or (regi.query and uj.netloc.lower() != regi.netloc.lower()):
            raise LetoltesHiba("tiltott_atiranyitas", code)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_megnyitas(url, fejlecek):
    keres = Request(url, headers={"User-Agent": "kesesfigyelo/0.1", **fejlecek})
    return build_opener(BiztonsagosAtiranyitas()).open(keres, timeout=20)


def letolt(url, max_meret, fejlecek=None):
    kezdet = time.monotonic()
    try:
        with http_megnyitas(url, fejlecek or {}) as valasz:
            adat = bytearray()
            olvas = getattr(valasz, "read1", valasz.read)
            while True:
                resz = olvas(min(65536, max_meret + 1 - len(adat)))
                adat.extend(resz)
                if len(adat) > max_meret:
                    raise LetoltesHiba("tul_nagy_valasz")
                if time.monotonic() - kezdet > 120:
                    raise LetoltesHiba("idotullepes")
                if not resz:
                    break
            hossz = valasz.headers.get("Content-Length")
            if hossz is not None and int(hossz) != len(adat):
                raise LetoltesHiba("hianyos_valasz")
            return bytes(adat), valasz.status, dict(valasz.headers)
    except HTTPError as hiba:
        kod = hiba.code
        head = {k.lower(): v for k, v in (hiba.headers or {}).items()}
        hiba.close()
        if kod == 304:
            return b"", 304, head
        uj_hiba = LetoltesHiba("http_hiba", kod, retry_after(head.get("retry-after")))
    except LetoltesHiba:
        raise
    except (OSError, ValueError, HTTPException):
        uj_hiba = LetoltesHiba("halozati_hiba")
    # Már az except blokkon kívül vagyunk: a korábbi kivétel URL-je sem láncolódik tovább.
    raise uj_hiba


def atomikus_iras(cel, adat, atmeneti=None):
    cel.parent.mkdir(parents=True, exist_ok=True)
    atmeneti = atmeneti or cel.parent
    atmeneti.mkdir(parents=True, exist_ok=True)
    if os.stat(atmeneti).st_dev != os.stat(cel.parent).st_dev:
        raise OSError("az_atmeneti_es_adatmappa_nem_azonos_fajlrendszer")
    nev = None
    try:
        with tempfile.NamedTemporaryFile(dir=atmeneti, delete=False, suffix=".tmp") as fajl:
            nev = Path(fajl.name)
            fajl.write(adat)
            fajl.flush()
            os.fsync(fajl.fileno())
        os.replace(nev, cel)
    finally:
        if nev is not None and nev.exists():
            nev.unlink()


def mentes(data, tipus, payload, tomorit=True):
    data.mkdir(parents=True, exist_ok=True)
    azonosito = hashlib.sha256(payload).hexdigest()
    mappa = "nyers" if tomorit else "menetrend"
    veg = ".pb.gz" if tomorit else ".zip"
    cel = data / mappa / tipus / azonosito[:2] / (azonosito + veg)
    uj = not cel.exists()
    if uj:
        if shutil.disk_usage(data).free < TARTALEK + len(payload):
            raise OSError("keves_tarhely")
        atomikus_iras(cel, gzip.compress(payload, mtime=0) if tomorit else payload,
                     data.parent / ".gyujto-atmeneti")
    else:
        # Azonos név alatt sérült fájlt sem fogadunk el és nem írunk felül csendben.
        try:
            regi = gzip.decompress(cel.read_bytes()) if tomorit else cel.read_bytes()
        except (OSError, EOFError, zlib.error):
            raise OSError("serult_archivum")
        if hashlib.sha256(regi).hexdigest() != azonosito:
            raise OSError("serult_archivum")
    return {"fajl": cel.relative_to(data).as_posix(), "sha256": azonosito,
            "uj_fajl": uj, "nyers_bajt": len(payload), "mentett_bajt": cel.stat().st_size}


def feed_adatok(payload, forras, most):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)
    if not feed.IsInitialized() or feed.header.incrementality != 0:
        raise ValueError("nem_teljes_feed")
    if feed.header.gtfs_realtime_version not in ("1.0", "2.0"):
        raise ValueError("ismeretlen_feed_verzio")
    feed_ido = feed.header.timestamp if feed.header.HasField("timestamp") else None
    jarmuvek = [e.vehicle for e in feed.entity if e.HasField("vehicle")]
    menetek = [e.trip_update for e in feed.entity if e.HasField("trip_update")]
    korok = [most - j.timestamp for j in jarmuvek if j.HasField("timestamp")]
    menet_korok = [most - m.timestamp for m in menetek if m.HasField("timestamp")]
    korlat = 600 if forras == "Alerts" else 90
    kor = None if feed_ido is None else most - feed_ido
    return {
        "feed_verzio": feed.header.gtfs_realtime_version,
        "feed_ido": feed_ido,
        "feed_kor_mp": kor,
        "feed_regi": None if kor is None else kor > korlat,
        "feed_jovobeli": None if kor is None else kor < -5,
        "menetrend_verzio": feed.header.feed_version if feed.header.HasField("feed_version") else None,
        "elemek": len(feed.entity), "jarmuvek": len(jarmuvek), "menetfrissitesek": len(menetek),
        "jelzesek": sum(e.HasField("alert") for e in feed.entity),
        "alakzatok": sum(e.HasField("shape") for e in feed.entity),
        "torolt_menetek": sum(m.trip.schedule_relationship == gtfs_realtime_pb2.TripDescriptor.CANCELED for m in menetek),
        "jarmu_ido_hianyzik": sum(not j.HasField("timestamp") for j in jarmuvek),
        "regi_jarmupoziciok": sum(k > 90 for k in korok),
        "jovobeli_jarmupoziciok": sum(k < -5 for k in korok),
        "menet_ido_hianyzik": sum(not m.HasField("timestamp") for m in menetek),
        "regi_menetfrissitesek": sum(k > 90 for k in menet_korok),
        "jovobeli_menetfrissitesek": sum(k < -5 for k in menet_korok),
        "ertelmezes": "forrasadat; nem igazolt tenyleges indulas",
    }


def menetrend_ellenorzes(payload):
    with zipfile.ZipFile(BytesIO(payload)) as csomag:
        nevek = set(csomag.namelist())
        kotelezo = {"agency.txt", "routes.txt", "trips.txt", "stops.txt", "stop_times.txt"}
        if not kotelezo <= nevek or not {"calendar.txt", "calendar_dates.txt"} & nevek:
            raise ValueError("hianyos_menetrend")
        if sum(f.file_size for f in csomag.infolist()) > 4 * 1024**3:
            raise ValueError("tul_nagy_kibontott_menetrend")
        if any(f.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) for f in csomag.infolist()):
            raise ValueError("nem_tamogatott_zip_tomorites")
        if csomag.testzip() is not None:
            raise ValueError("serult_menetrend")
    return {"gtfs_fajlok": len(nevek)}


def valasz_mentese(data, forras, payload, kezdett, vegzett):
    eredmeny = {"forras": forras, "kezdett_utc": utc(kezdett), "vegzett_utc": utc(vegzett)}
    # Az eredeti bájtok a feldolgozás előtt megmaradnak, hibás tartalom esetén is.
    eredmeny.update(mentes(data, forras, payload, tomorit=forras != "Menetrend"))
    try:
        if forras == "Menetrend":
            eredmeny.update(menetrend_ellenorzes(payload))
        else:
            eredmeny.update(feed_adatok(payload, forras, vegzett))
        eredmeny["eredmeny"] = "siker"
    except (DecodeError, ValueError, zipfile.BadZipFile, EOFError, RuntimeError, zlib.error):
        eredmeny["eredmeny"] = "hibas_valasz"
    return eredmeny


def naplo(data, bejegyzes):
    ido = datetime.fromisoformat(bejegyzes["kezdett_utc"])
    nev = ido.strftime("%H%M%S%f") + "--" + bejegyzes["forras"] + "--" + uuid.uuid4().hex + ".json"
    cel = data / "naplo" / ido.strftime("%Y-%m-%d") / nev
    adat = (json.dumps(bejegyzes, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
    atomikus_iras(cel, adat, data.parent / ".gyujto-atmeneti")
    return cel


def utolso(data, forras, csak_siker=False):
    fajlok = sorted((data / "naplo").glob("*/*--" + forras + "--*.json"), reverse=True)
    for fajl in fajlok:
        adat = json.loads(fajl.read_text(encoding="utf-8"))
        if not adat.get("teszt") and (not csak_siker or adat["eredmeny"] in ("siker", "nem_valtozott")):
            return adat
    return {}


def ervenyes_menetrend(data, rekord):
    if not rekord.get("fajl") or not rekord.get("sha256"):
        return False
    fajl = (data / rekord["fajl"]).resolve()
    if not fajl.is_relative_to(data.resolve()) or not fajl.is_file():
        return False
    return hashlib.sha256(fajl.read_bytes()).hexdigest() == rekord["sha256"]


def lepes(data, forras, kulcs, hibak=0, elozo=None, menetrend=None):
    kezdet = time.time()
    if elozo is None:
        elozo = utolso(data, forras) if forras == "Menetrend" else {}
    menetrend = elozo if forras == "Menetrend" else (menetrend or {})
    ervenyes = ervenyes_menetrend(data, menetrend) if forras == "Menetrend" else bool(menetrend)
    rekord = {"forras": forras, "kezdett_utc": utc(kezdet)}
    if forras != "Menetrend":
        rekord["ismert_menetrend_sha256"] = menetrend.get("sha256") if ervenyes else None
    try:
        fejlecek = {}
        if forras == "Menetrend":
            url = MENETREND_URL
            for mezo, fejlec in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
                if elozo.get(mezo) and ervenyes:
                    fejlecek[fejlec] = elozo[mezo]
        else:
            url = "https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/" + forras + ".pb?" + urlencode({"key": kulcs})
        payload, status, head = letolt(url, MAX_GTFS if forras == "Menetrend" else MAX_RT, fejlecek)
        rekord["http_status"] = status
        if status == 304 and forras == "Menetrend" and ervenyes:
            rekord.update({k: elozo[k] for k in ("fajl", "sha256", "etag", "last_modified") if k in elozo})
            rekord["eredmeny"] = "nem_valtozott"
        elif status == 200:
            rekord.update(valasz_mentese(data, forras, payload, kezdet, time.time()))
            head = {k.lower(): v for k, v in head.items()}
            if forras == "Menetrend" and rekord["eredmeny"] == "siker":
                rekord["etag"] = head.get("etag")
                rekord["last_modified"] = head.get("last-modified")
        else:
            rekord["eredmeny"] = "hibas_http_status"
    except LetoltesHiba as hiba:
        rekord.update({"eredmeny": hiba.fajta, "http_status": hiba.kod,
                       "retry_after_mp": hiba.varakozas})
    except OSError:
        rekord["eredmeny"] = "helyi_hiba"
    rekord["vegzett_utc"] = utc(time.time())
    siker = rekord["eredmeny"] in ("siker", "nem_valtozott")
    rekord["egymas_utani_hibak"] = 0 if siker else hibak + 1
    alap = 86400 if forras == "Menetrend" else FORRASOK[forras]
    rekord["varakozas_mp"] = alap if siker else max(min(900, 30 * 2 ** min(hibak, 5)), rekord.get("retry_after_mp") or 0)
    rekord["kovetkezo_engedelyezett_utc"] = utc((kezdet if siker else time.time()) + rekord["varakozas_mp"])
    naplo(data, rekord)
    print(forras + ": " + rekord["eredmeny"] + ", " + str(rekord.get("nyers_bajt", 0)) + " bajt", flush=True)
    return rekord


@contextmanager
def egy_peldany(data):
    data.mkdir(parents=True, exist_ok=True)
    with (data / ".gyujto.lock").open("a+b") as zar:
        zar.seek(0, os.SEEK_END)
        if zar.tell() == 0:
            zar.write(b"0")
            zar.flush()
        zar.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(zar.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(zar.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("mar_fut_egy_gyujto")
        yield


def kovetkezo_utes(esedekes, most, periodus):
    ugras = max(1, math.floor((most - esedekes) / periodus) + 1)
    return esedekes + ugras * periodus, ugras - 1


def ures_minoseg(ora):
    forrasok = {}
    for s, periodus in FORRASOK.items():
        forrasok[s] = {"probak": 0, "siker": 0, "hibak": 0, "regi_feed": 0,
                      "ido_hianyzik": 0, "max_jarmu": 0, "max_menetfrissites": 0,
                      "max_res_mp": None, "teljes_orara_tervezett": 3600 // periodus}
    return {"ora_utc": ora, "forrasok": forrasok, "reszora_lehet": True}


def minoseg(data, ora=None):
    orak = {} if ora is None else {ora: ures_minoseg(ora)}
    elozo_idok = {}
    for fajl in sorted((data / "naplo").glob("*/*.json")):
        r = json.loads(fajl.read_text(encoding="utf-8"))
        if r.get("teszt") or r["forras"] not in FORRASOK:
            continue
        kulcs = r["kezdett_utc"][:13]
        ido = datetime.fromisoformat(r["kezdett_utc"]).timestamp()
        elozo_ido = elozo_idok.get(r["forras"])
        elozo_idok[r["forras"]] = ido
        if ora is not None and kulcs != ora:
            continue
        if kulcs not in orak:
            orak[kulcs] = ures_minoseg(kulcs)
        sor = orak[kulcs]["forrasok"][r["forras"]]
        sor["probak"] += 1
        siker = r["eredmeny"] == "siker"
        sor["siker"] += int(siker)
        sor["hibak"] += int(not siker)
        sor["regi_feed"] += int(r.get("feed_regi") is True)
        sor["ido_hianyzik"] += int(siker and r.get("feed_ido") is None)
        sor["max_jarmu"] = max(sor["max_jarmu"], r.get("jarmuvek", 0))
        sor["max_menetfrissites"] = max(sor["max_menetfrissites"], r.get("menetfrissitesek", 0))
        if elozo_ido is not None:
            sor["max_res_mp"] = max(sor["max_res_mp"] or 0, ido - elozo_ido)
    if orak and ora is None:
        kezdet = datetime.fromisoformat(min(orak) + ":00:00+00:00")
        veg = datetime.fromisoformat(max(orak) + ":00:00+00:00")
        while kezdet <= veg:
            kulcs = kezdet.isoformat()[:13]
            orak.setdefault(kulcs, ures_minoseg(kulcs))
            kezdet += timedelta(hours=1)
    return [orak[k] for k in sorted(orak)]


def minoseg_mentes(data, ora):
    adat = (json.dumps(minoseg(data, ora), sort_keys=True) + "\n").encode("utf-8")
    azonosito = hashlib.sha256(adat).hexdigest()
    cel = data / "adatminoseg" / (ora.replace(":", "-") + "--" + azonosito + ".json")
    if not cel.exists():
        atomikus_iras(cel, adat, data.parent / ".gyujto-atmeneti")


def beolvas_kulcs(fajl):
    sor = fajl.read_text(encoding="utf-8-sig").strip()
    if not sor.startswith("BKK_API_KEY="):
        raise ValueError("hibas_kulcsfajl")
    kulcs = sor.removeprefix("BKK_API_KEY=").strip()
    if not kulcs or any(c.isspace() for c in kulcs):
        raise ValueError("hibas_kulcsfajl")
    return kulcs


def keresi_hatar(data):
    hatar = time.time()
    for s in list(FORRASOK) + ["Menetrend"]:
        elozo = utolso(data, s)
        if elozo.get("kezdett_utc"):
            hatar = max(hatar, datetime.fromisoformat(elozo["kezdett_utc"]).timestamp() + MIN_KOZ)
        if elozo.get("http_status") in (429, 503) and elozo.get("kovetkezo_engedelyezett_utc"):
            hatar = max(hatar, datetime.fromisoformat(elozo["kovetkezo_engedelyezett_utc"]).timestamp())
    return hatar


def futtat(data, kulcs, egyszer=False):
    forrasok = list(FORRASOK) if egyszer else list(FORRASOK) + ["Menetrend"]
    kezdet = time.monotonic()
    esedekes = {s: kezdet + i * MIN_KOZ for i, s in enumerate(forrasok)}
    hibak = {s: 0 for s in forrasok}
    elozok = {s: utolso(data, s) for s in forrasok}
    menetrend = utolso(data, "Menetrend", csak_siker=True)
    if not ervenyes_menetrend(data, menetrend):
        menetrend = {}
    globalis_varakozas = kezdet + max(0, keresi_hatar(data) - time.time())
    # Újrainduláskor egy korábbi korlátozás várakozási idejét is betartjuk.
    for s in forrasok:
        elozo = elozok[s]
        hibak[s] = elozo.get("egymas_utani_hibak", 0)
        if elozo.get("kovetkezo_engedelyezett_utc"):
            hatar = datetime.fromisoformat(elozo["kovetkezo_engedelyezett_utc"]).timestamp()
            esedekes[s] = max(esedekes[s], kezdet + max(0, hatar - time.time()))
            if elozo.get("http_status") in (429, 503):
                globalis_varakozas = max(globalis_varakozas, kezdet + max(0, hatar - time.time()))
        if elozo.get("kezdett_utc"):
            utolso_ido = datetime.fromisoformat(elozo["kezdett_utc"]).timestamp()
            globalis_varakozas = max(globalis_varakozas, kezdet + max(0, utolso_ido + MIN_KOZ - time.time()))
    utolso_keres = kezdet - MIN_KOZ
    ora = utc(time.time())[:13]
    minden_sikerult = True
    while esedekes:
        uj_ora = utc(time.time())[:13]
        if uj_ora != ora:
            minoseg_mentes(data, ora)
            ora = uj_ora
        s = min(esedekes, key=esedekes.get)
        most = time.monotonic()
        indulhat = max(esedekes[s], utolso_keres + MIN_KOZ, globalis_varakozas)
        if most < indulhat:
            time.sleep(min(1, indulhat - most))
            continue
        tervezett = esedekes[s]
        utolso_keres = time.monotonic()
        rekord = lepes(data, s, kulcs, hibak[s], elozo=elozok[s], menetrend=menetrend)
        elozok[s] = rekord
        if s == "Menetrend" and rekord["eredmeny"] in ("siker", "nem_valtozott"):
            menetrend = rekord
        minden_sikerult = minden_sikerult and rekord["eredmeny"] in ("siker", "nem_valtozott")
        hibak[s] = rekord["egymas_utani_hibak"]
        if rekord.get("http_status") in (401, 403):
            raise RuntimeError("hozzaferes_elutasitva; ellenorizd_helyben_a_kulcsot")
        if rekord["eredmeny"] == "helyi_hiba":
            raise RuntimeError("mentesi_hiba; ellenorizd_a_tarhelyet_es_jogosultsagot")
        if rekord.get("http_status") in (429, 503):
            globalis_varakozas = time.monotonic() + rekord["varakozas_mp"]
        if egyszer:
            del esedekes[s]
        elif hibak[s]:
            esedekes[s] = time.monotonic() + rekord["varakozas_mp"]
        else:
            periodus = FORRASOK.get(s, 86400)
            esedekes[s], _ = kovetkezo_utes(tervezett, time.monotonic(), periodus)
    return minden_sikerult


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nyers BKK-adatok mentése; alapból csak súgó.")
    mod = parser.add_mutually_exclusive_group()
    mod.add_argument("--egyszer", action="store_true", help="Egy véges kör: három élő kérés.")
    mod.add_argument("--menetrend", action="store_true", help="A statikus GTFS egyszeri ellenőrzése.")
    mod.add_argument("--folyamatos", action="store_true", help="Önálló gyűjtés; külön jóváhagyás után.")
    mod.add_argument("--ellenorzes", type=Path, help="Mentett .pb.gz minták offline ellenőrzése.")
    mod.add_argument("--minoseg", action="store_true", help="Óránkénti összesítés a helyi naplókból.")
    parser.add_argument("--adatmappa", type=Path)
    parser.add_argument("--kulcsfajl", type=Path, default=Path(__file__).parent / ".env.bkk")
    args = parser.parse_args(argv)
    if not any((args.egyszer, args.menetrend, args.folyamatos, args.ellenorzes, args.minoseg)):
        parser.print_help()
        return 0
    data = args.adatmappa or Path(__file__).parent / "data"
    if args.ellenorzes and args.adatmappa is None:
        data = data / "teszt"
    try:
        if args.minoseg:
            print(json.dumps(minoseg(data), indent=2))
            return 0
        with egy_peldany(data):
            if args.ellenorzes:
                siker = True
                feldolgozott = 0
                for fajl in sorted(args.ellenorzes.glob("*.pb.gz")):
                    forras = fajl.name.split("-")[0]
                    if forras not in FORRASOK:
                        continue
                    feldolgozott += 1
                    with gzip.open(fajl, "rb") as minta:
                        payload = minta.read(MAX_RT + 1)
                    if len(payload) > MAX_RT:
                        raise ValueError("tul_nagy_minta")
                    rekord = valasz_mentese(data, forras, payload, time.time(), time.time())
                    rekord["teszt"] = True
                    naplo(data, rekord)
                    siker = siker and rekord["eredmeny"] == "siker"
                    print(fajl.name + ": " + rekord["eredmeny"])
                if feldolgozott == 0:
                    raise ValueError("nincs_ellenorizheto_minta")
                return 0 if siker else 1
            if args.menetrend:
                hatar = keresi_hatar(data)
                while time.time() < hatar:
                    time.sleep(min(1, hatar - time.time()))
                r = lepes(data, "Menetrend", "")
                return 0 if r["eredmeny"] in ("siker", "nem_valtozott") else 1
            kulcs = beolvas_kulcs(args.kulcsfajl)
            siker = futtat(data, kulcs, egyszer=args.egyszer)
            return 0 if siker else 1
    except KeyboardInterrupt:
        print("Leallitva. A mar elmentett adatok megmaradtak.")
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as hiba:
        # A kivétel szövege tartalmazhat URL-t vagy fájlnevet: csak a típusát írjuk ki.
        print("A gyujto leallt: " + type(hiba).__name__ + ". Ellenorizd a naplot es a helyi beallitasokat.")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
