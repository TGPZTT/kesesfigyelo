"""BKK-adatok és időjárás mentése. Folyamatos futás csak külön kapcsolóval."""

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

# Mit kérünk le, és milyen sűrűn.
FORRASOK = {"VehiclePositions": 30, "TripUpdates": 30, "Alerts": 60}
PERIODUSOK = {**FORRASOK, "Menetrend": 86400, "Idojaras": 900}
IDOJARAS_PONTOK = {
    "Belvaros": (47.497413, 19.055158),
    "Rakosmente": (47.478941, 19.256176),
    "Godollo": (47.597505, 19.347599),
}
IDOJARAS_EGYSEGEK = {
    "temperature_2m": "°C", "precipitation": "mm",
    "wind_speed_10m": "km/h", "weather_code": "wmo code",
}
MENETREND_URL = "https://go.bkk.hu/api/static/v1/public-gtfs/budapest_gtfs.zip"
MIN_KOZ = 10
MAX_RT = 50 * 1024 * 1024
MAX_GTFS = 500 * 1024 * 1024
TARTALEK = 2 * 1024 * 1024 * 1024
MAX_VARAKOZAS = 365 * 86400


def utc(ido):
    return datetime.fromtimestamp(ido, UTC).isoformat()


# Letöltés és a szerver által kért várakozás.
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
        return min(
            MAX_VARAKOZAS,
            max(0, math.ceil(datum.timestamp() - (time.time() if now is None else now))),
        )
    except (TypeError, ValueError, OverflowError):
        return None


class BiztonsagosAtiranyitas(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        regi = urlsplit(req.full_url)
        uj = urlsplit(newurl)
        # A kulcsot nem küldjük másik kiszolgálóra, és maradunk HTTPS-en.
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
    # A korábbi hiba URL-je ne kerüljön a kiírt hibába.
    raise uj_hiba


# Csak a kész fájl kerül a helyére.
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
    if tipus == "Idojaras":
        veg = ".json.gz"
    cel = data / mappa / tipus / azonosito[:2] / (azonosito + veg)
    uj = not cel.exists()
    if uj:
        if shutil.disk_usage(data).free < TARTALEK + len(payload):
            raise OSError("keves_tarhely")
        atomikus_iras(
            cel,
            gzip.compress(payload, mtime=0) if tomorit else payload,
            data.parent / ".gyujto-atmeneti",
        )
    else:
        # A meglévő fájlt is ellenőrizzük, hátha megsérült.
        try:
            regi = gzip.decompress(cel.read_bytes()) if tomorit else cel.read_bytes()
        except (OSError, EOFError, zlib.error):
            raise OSError("serult_archivum")
        if hashlib.sha256(regi).hexdigest() != azonosito:
            raise OSError("serult_archivum")
    return {"fajl": cel.relative_to(data).as_posix(), "sha256": azonosito,
            "uj_fajl": uj, "nyers_bajt": len(payload), "mentett_bajt": cel.stat().st_size}


# A mentett válaszok ellenőrzése.
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
        "torolt_menetek": sum(
            m.trip.schedule_relationship == gtfs_realtime_pb2.TripDescriptor.CANCELED
            for m in menetek
        ),
        "jarmu_ido_hianyzik": sum(not j.HasField("timestamp") for j in jarmuvek),
        "regi_jarmupoziciok": sum(k > 90 for k in korok),
        "jovobeli_jarmupoziciok": sum(k < -5 for k in korok),
        "menet_ido_hianyzik": sum(not m.HasField("timestamp") for m in menetek),
        "regi_menetfrissitesek": sum(k > 90 for k in menet_korok),
        "jovobeli_menetfrissitesek": sum(k < -5 for k in menet_korok),
        "ertelmezes": "forrasadat; nem igazolt tenyleges indulas",
    }


def idojaras_parameterek():
    return {
        "latitude": ",".join(str(p[0]) for p in IDOJARAS_PONTOK.values()),
        "longitude": ",".join(str(p[1]) for p in IDOJARAS_PONTOK.values()),
        "current": ",".join(IDOJARAS_EGYSEGEK),
        "temperature_unit": "celsius", "wind_speed_unit": "kmh",
        "precipitation_unit": "mm", "timeformat": "unixtime",
        "timezone": "GMT", "models": "best_match",
    }


def idojaras_adatok(payload, most):
    adatok = json.loads(payload)
    if not isinstance(adatok, list) or len(adatok) != len(IDOJARAS_PONTOK):
        raise ValueError("hianyos_idojaras")
    pontok = []
    for (nev, hely), adat in zip(IDOJARAS_PONTOK.items(), adatok):
        aktualis = adat["current"]
        egysegek = adat["current_units"]
        if not isinstance(aktualis, dict) or not isinstance(egysegek, dict):
            raise TypeError("hibas_idojaras_szerkezet")
        if egysegek.get("time") != "unixtime" or egysegek.get("interval") != "seconds":
            raise ValueError("hibas_idojaras_idoegyseg")
        for mezo, egyseg in IDOJARAS_EGYSEGEK.items():
            ertek = aktualis[mezo]
            if egysegek.get(mezo) != egyseg:
                raise ValueError("hibas_idojaras_mertekegyseg")
            # A hiányzó csapadék nem ugyanaz, mint a nulla.
            if ertek is not None and (type(ertek) not in (int, float) or not math.isfinite(ertek)):
                raise ValueError("hibas_idojaras_ertek")
        if (
            type(aktualis["time"]) is not int
            or type(aktualis["interval"]) is not int
            or aktualis["interval"] <= 0
        ):
            raise ValueError("hibas_idojaras_ido")
        for mezo, kert in zip(("latitude", "longitude"), hely):
            if (
                type(adat[mezo]) not in (int, float)
                or not math.isfinite(adat[mezo])
                or abs(adat[mezo] - kert) > 0.2
            ):
                raise ValueError("eltero_idojarasi_hely")
        kor = most - aktualis["time"]
        pontok.append({
            "terseg": nev, "kert_latitude": hely[0], "kert_longitude": hely[1],
            "adat_ido": aktualis["time"], "adat_kor_mp": kor,
            "regi": kor > 1800, "jovobeli": kor < -5,
            "hianyzo_ertekek": sum(aktualis[m] is None for m in IDOJARAS_EGYSEGEK),
        })
    return {"pontok": pontok, "ertelmezes": "idojarasi modelladat, nem helyi meres"}


def menetrend_ellenorzes(payload):
    with zipfile.ZipFile(BytesIO(payload)) as csomag:
        nevek = set(csomag.namelist())
        kotelezo = {"agency.txt", "routes.txt", "trips.txt", "stops.txt", "stop_times.txt"}
        if not kotelezo <= nevek or not {"calendar.txt", "calendar_dates.txt"} & nevek:
            raise ValueError("hianyos_menetrend")
        if sum(f.file_size for f in csomag.infolist()) > 4 * 1024**3:
            raise ValueError("tul_nagy_kibontott_menetrend")
        if any(
            f.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            for f in csomag.infolist()
        ):
            raise ValueError("nem_tamogatott_zip_tomorites")
        if csomag.testzip() is not None:
            raise ValueError("serult_menetrend")
    return {"gtfs_fajlok": len(nevek)}


def valasz_mentese(data, forras, payload, kezdett, vegzett):
    eredmeny = {"forras": forras, "kezdett_utc": utc(kezdett), "vegzett_utc": utc(vegzett)}
    # Előbb mentünk, utána ellenőrzünk. A hibás válasz is megmarad.
    eredmeny.update(mentes(data, forras, payload, tomorit=forras != "Menetrend"))
    try:
        if forras == "Menetrend":
            eredmeny.update(menetrend_ellenorzes(payload))
        elif forras == "Idojaras":
            eredmeny.update(idojaras_adatok(payload, vegzett))
        else:
            eredmeny.update(feed_adatok(payload, forras, vegzett))
        eredmeny["eredmeny"] = "siker"
    except (
        DecodeError, ValueError, KeyError, TypeError,
        zipfile.BadZipFile, EOFError, RuntimeError, zlib.error,
    ):
        eredmeny["eredmeny"] = "hibas_valasz"
    return eredmeny


# Minden próbáról külön napló készül.
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
    if forras in FORRASOK:
        rekord["ismert_menetrend_sha256"] = menetrend.get("sha256") if ervenyes else None
    try:
        fejlecek = {}
        if forras == "Menetrend":
            url = MENETREND_URL
            for mezo, fejlec in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
                if elozo.get(mezo) and ervenyes:
                    fejlecek[fejlec] = elozo[mezo]
        elif forras == "Idojaras":
            rekord["parameterek"] = idojaras_parameterek()
            url = "https://api.open-meteo.com/v1/forecast?" + urlencode(rekord["parameterek"])
        else:
            url = (
                "https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/"
                + forras + ".pb?" + urlencode({"key": kulcs})
            )
        max_meret = MAX_GTFS if forras == "Menetrend" else MAX_RT
        if forras == "Idojaras":
            max_meret = 1024 * 1024
        payload, status, head = letolt(url, max_meret, fejlecek)
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
    alap = PERIODUSOK[forras]
    rekord["varakozas_mp"] = alap if siker else max(
        min(900, 30 * 2 ** min(hibak, 5)), rekord.get("retry_after_mp") or 0
    )
    if forras == "Idojaras":
        rekord["varakozas_mp"] = max(alap, rekord["varakozas_mp"])
    rekord["kovetkezo_engedelyezett_utc"] = utc(
        (kezdet if siker else time.time()) + rekord["varakozas_mp"]
    )
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


# Óránkénti összesítés a naplókból.
def ures_minoseg(ora):
    forrasok = {}
    for forras, periodus in PERIODUSOK.items():
        if forras == "Menetrend":
            continue
        forrasok[forras] = {
            "probak": 0, "siker": 0, "hibak": 0,
            "regi_feed": 0, "ido_hianyzik": 0,
            "max_jarmu": 0, "max_menetfrissites": 0,
            "max_keresi_res_mp": None, "max_sikeres_res_mp": None,
            "utolso_keres_ota_mp": None, "utolso_siker_ota_mp": None,
            "teljes_orara_tervezett": 3600 // periodus,
        }
        if forras == "Idojaras":
            forrasok[forras] = {k: v for k, v in forrasok[forras].items()
                               if k not in ("regi_feed", "ido_hianyzik", "max_jarmu", "max_menetfrissites")}
            forrasok[forras].update({"regi_pontok": 0, "hianyzo_ertekek": 0})
    return {"ora_utc": ora, "forrasok": forrasok, "reszora_lehet": True}


def minoseg(data, ora=None, most=None):
    most = time.time() if most is None else most
    naplok = {}
    elozo_keresek = {}
    elozo_sikerek = {}
    forrasok = {*FORRASOK, "Idojaras"}
    for fajl in sorted((data / "naplo").glob("*/*--*--*.json"), reverse=ora is not None):
        if ora is not None:
            fajl_oraja = fajl.parent.name + "T" + fajl.name[:2]
            forras = fajl.name.split("--")[1]
            if fajl_oraja > ora or forras not in forrasok:
                continue
            if fajl_oraja < ora and forras in elozo_sikerek:
                continue
        rekord = json.loads(fajl.read_text(encoding="utf-8"))
        if rekord.get("teszt") or rekord["forras"] not in forrasok:
            continue
        ora_neve = rekord["kezdett_utc"][:13]
        ido = datetime.fromisoformat(rekord["kezdett_utc"]).timestamp()
        if ido > most or (ora is not None and ora_neve > ora):
            continue
        if ora is not None and ora_neve < ora:
            # Az előző órákból csak az utolsó próba és siker ideje kell.
            forras = rekord["forras"]
            elozo_keresek.setdefault(forras, ido)
            if rekord["eredmeny"] == "siker":
                elozo_sikerek.setdefault(forras, ido)
            if forrasok <= elozo_sikerek.keys():
                break
            continue
        naplok.setdefault(ora_neve, []).append((ido, rekord))
    if not naplok and ora is None:
        return []

    kezdet = datetime.fromisoformat((ora or min(naplok)) + ":00:00+00:00")
    veg = datetime.fromisoformat((ora or utc(most)[:13]) + ":00:00+00:00")
    orak = []
    while kezdet <= veg:
        ora_neve = kezdet.isoformat()[:13]
        osszesites = ures_minoseg(ora_neve)
        for ido, rekord in sorted(naplok.get(ora_neve, []), key=lambda elem: elem[0]):
            forras = rekord["forras"]
            sor = osszesites["forrasok"][forras]
            siker = rekord["eredmeny"] == "siker"
            sor["probak"] += 1
            sor["siker"] += int(siker)
            sor["hibak"] += int(not siker)
            if forras == "Idojaras":
                sor["regi_pontok"] += sum(p["regi"] for p in rekord.get("pontok", []))
                sor["hianyzo_ertekek"] += sum(p["hianyzo_ertekek"] for p in rekord.get("pontok", []))
            else:
                sor["regi_feed"] += int(rekord.get("feed_regi") is True)
                sor["ido_hianyzik"] += int(siker and rekord.get("feed_ido") is None)
                sor["max_jarmu"] = max(sor["max_jarmu"], rekord.get("jarmuvek", 0))
                sor["max_menetfrissites"] = max(sor["max_menetfrissites"], rekord.get("menetfrissitesek", 0))
            if forras in elozo_keresek:
                res = ido - elozo_keresek[forras]
                sor["max_keresi_res_mp"] = max(sor["max_keresi_res_mp"] or 0, res)
            elozo_keresek[forras] = ido
            if siker:
                if forras in elozo_sikerek:
                    res = ido - elozo_sikerek[forras]
                    sor["max_sikeres_res_mp"] = max(sor["max_sikeres_res_mp"] or 0, res)
                elozo_sikerek[forras] = ido

        # Az üres óra és a még tartó szünet is látszódjon.
        ora_vege = min(most, (kezdet + timedelta(hours=1)).timestamp())
        osszesites["ellenorzott_utc"] = utc(ora_vege)
        for forras, sor in osszesites["forrasok"].items():
            if forras in elozo_keresek:
                sor["utolso_keres_ota_mp"] = ora_vege - elozo_keresek[forras]
            if forras in elozo_sikerek:
                sor["utolso_siker_ota_mp"] = ora_vege - elozo_sikerek[forras]
        if ora is None or ora_neve == ora:
            orak.append(osszesites)
        kezdet += timedelta(hours=1)
    return orak


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


# A kérések sorrendje és a köztük tartott szünet.
def futtat(data, kulcs, egyszer=False, forrasok=None):
    if forrasok is None:
        forrasok = list(FORRASOK) if egyszer else list(PERIODUSOK)
    kezdet = time.monotonic()
    esedekes = {s: kezdet + i * MIN_KOZ for i, s in enumerate(forrasok)}
    hibak = {s: 0 for s in forrasok}
    elozok = {s: utolso(data, s) for s in forrasok}
    menetrend = utolso(data, "Menetrend", csak_siker=True)
    if not ervenyes_menetrend(data, menetrend):
        menetrend = {}
    globalis_varakozas = kezdet + max(0, keresi_hatar(data) - time.time())
    # Újraindítás után is kivárjuk a korábbi szünetet.
    for s in forrasok:
        elozo = elozok[s]
        hibak[s] = elozo.get("egymas_utani_hibak", 0)
        if elozo.get("kovetkezo_engedelyezett_utc"):
            hatar = datetime.fromisoformat(elozo["kovetkezo_engedelyezett_utc"]).timestamp()
            esedekes[s] = max(esedekes[s], kezdet + max(0, hatar - time.time()))
            if s != "Idojaras" and elozo.get("http_status") in (429, 503):
                globalis_varakozas = max(globalis_varakozas, kezdet + max(0, hatar - time.time()))
        if s != "Idojaras" and elozo.get("kezdett_utc"):
            utolso_ido = datetime.fromisoformat(elozo["kezdett_utc"]).timestamp()
            globalis_varakozas = max(
                globalis_varakozas, kezdet + max(0, utolso_ido + MIN_KOZ - time.time())
            )
    utolso_keres = kezdet - MIN_KOZ
    ora = utc(time.time())[:13]
    minden_sikerult = True
    while esedekes:
        uj_ora = utc(time.time())[:13]
        if uj_ora != ora:
            try:
                minoseg_mentes(data, ora)
            except (OSError, ValueError, KeyError):
                print("Az oras osszesites hibazott; a nyers gyujtes folytatodik.", flush=True)
            ora = uj_ora
        # Az időjárás és a BKK várakozása külön számít.
        indulasi_idok = {
            s: max(
                ido, utolso_keres + MIN_KOZ,
                0 if s == "Idojaras" else globalis_varakozas,
            )
            for s, ido in esedekes.items()
        }
        s = min(indulasi_idok, key=lambda nev: (indulasi_idok[nev], esedekes[nev]))
        most = time.monotonic()
        indulhat = indulasi_idok[s]
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
        if s != "Idojaras" and rekord.get("http_status") in (401, 403):
            raise RuntimeError("hozzaferes_elutasitva; ellenorizd_helyben_a_kulcsot")
        if rekord["eredmeny"] == "helyi_hiba":
            raise RuntimeError("mentesi_hiba; ellenorizd_a_tarhelyet_es_jogosultsagot")
        if s != "Idojaras" and rekord.get("http_status") in (429, 503):
            globalis_varakozas = time.monotonic() + rekord["varakozas_mp"]
        if egyszer:
            del esedekes[s]
        elif hibak[s]:
            esedekes[s] = time.monotonic() + rekord["varakozas_mp"]
        else:
            periodus = PERIODUSOK[s]
            esedekes[s], _ = kovetkezo_utes(tervezett, time.monotonic(), periodus)
            if s == "Idojaras":
                esedekes[s] = max(esedekes[s], utolso_keres + periodus)
    return minden_sikerult


# A parancssori kapcsolók közül egyet lehet választani.
def main(argv=None):
    parser = argparse.ArgumentParser(description="BKK-adatok és időjárás mentése; alapból csak súgó.")
    mod = parser.add_mutually_exclusive_group()
    mod.add_argument("--egyszer", action="store_true", help="Egy véges kör: három élő kérés.")
    mod.add_argument("--menetrend", action="store_true", help="A statikus GTFS egyszeri ellenőrzése.")
    mod.add_argument("--idojaras", action="store_true", help="Egy időjárási kérés, három térségre; kulcs nélkül.")
    mod.add_argument("--folyamatos", action="store_true", help="Önálló gyűjtés; külön jóváhagyás után.")
    mod.add_argument("--ellenorzes", type=Path, help="Mentett BKK- és időjárásminták offline ellenőrzése.")
    mod.add_argument("--minoseg", action="store_true", help="Óránkénti összesítés a helyi naplókból.")
    parser.add_argument("--adatmappa", type=Path)
    parser.add_argument("--kulcsfajl", type=Path, default=Path(__file__).parent / ".env.bkk")
    args = parser.parse_args(argv)
    if not any((
        args.egyszer, args.menetrend, args.idojaras,
        args.folyamatos, args.ellenorzes, args.minoseg,
    )):
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
                mintaforrasok = [*FORRASOK, "Idojaras"]
                for fajl in sorted(args.ellenorzes.rglob("*")):
                    if not fajl.is_file() or not fajl.name.endswith((".pb", ".pb.gz", ".json.gz")):
                        continue
                    forras = fajl.name.split(".")[0].split("-")[0]
                    if forras not in mintaforrasok:
                        for nev in mintaforrasok:
                            if nev in fajl.parts:
                                forras = nev
                                break
                    if forras not in mintaforrasok:
                        continue
                    feldolgozott += 1
                    megnyitas = gzip.open if fajl.name.endswith(".gz") else open
                    with megnyitas(fajl, "rb") as minta:
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
            if args.idojaras:
                siker = futtat(data, "", egyszer=True, forrasok=["Idojaras"])
                return 0 if siker else 1
            kulcs = beolvas_kulcs(args.kulcsfajl)
            siker = futtat(data, kulcs, egyszer=args.egyszer)
            return 0 if siker else 1
    except KeyboardInterrupt:
        print("Leallitva. A mar elmentett adatok megmaradtak.")
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as hiba:
        # Csak a hiba típusát írjuk ki, mert a szövegben kulcs is lehet.
        print("A gyujto leallt: " + type(hiba).__name__ + ". Ellenorizd a naplot es a helyi beallitasokat.")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
