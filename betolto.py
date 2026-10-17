"""Az elmentett válaszok betöltése PostgreSQL-be. Internetes kérés nincs."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import psycopg
from google.protobuf.json_format import MessageToDict
from google.transit import gtfs_realtime_pb2
from psycopg.types.json import Jsonb

from gyujto import IDOJARAS_PONTOK, idojaras_adatok


def kapcsolat(beallitas=Path(".env.db")):
    # A helyi fájlból csak az adatbázis kapcsolatadatait olvassuk.
    nevek = {"PGHOST": "host", "PGPORT": "port", "PGDATABASE": "dbname",
             "PGUSER": "user", "PGPASSWORD": "password"}
    parameterek = {}
    for sor in Path(beallitas).read_text(encoding="utf-8-sig").splitlines():
        if not sor.strip() or sor.lstrip().startswith("#"):
            continue
        nev, ertek = sor.split("=", 1)
        if nev.strip() not in nevek:
            raise ValueError("Ismeretlen adatbázis-beállítás.")
        parameterek[nevek[nev.strip()]] = ertek.strip()
    return psycopg.connect(**parameterek, autocommit=True, connect_timeout=10,
                           options="-c timezone=UTC -c statement_timeout=120000")


def sema(conn):
    # A táblákat az SQL-fájl írja le. Régi sémát nem alakítunk át magától.
    with conn.transaction():
        if conn.execute("SELECT to_regclass('allapot')").fetchone()[0]:
            raise ValueError("Az új sémához külön adatbázis kell; nem írom át a meglévő táblákat.")
        conn.execute(Path(__file__).with_name("adatbazis.sql").read_text(encoding="utf-8"))


def mezo(uzenet, nev):
    # A hiányzó mező ne legyen véletlenül nulla.
    return getattr(uzenet, nev) if uzenet.HasField(nev) else None


def idopont(masodperc):
    # A forrás 1970 óta eltelt másodperceket ad; ebből UTC-időpont lesz.
    return datetime.fromtimestamp(masodperc, UTC) if masodperc is not None else None


def beszur(conn, tabla, sor):
    # A tábla- és oszlopnevek mindig a programból jönnek, az értékek külön mennek.
    conn.execute("INSERT INTO " + tabla + " (" + ", ".join(sor) + ") VALUES ("
                 + ", ".join(["%s"] * len(sor)) + ")", tuple(sor.values()))


def magyar_szoveg(uzenet):
    for szoveg in uzenet.translation:
        if szoveg.language == "hu":
            return szoveg.text
    return uzenet.translation[0].text if uzenet.translation else None


VONALAK = {
    "0460", "0975", "1610", "1695", "3010", "3020",
    "3030", "3046", "4800", "4820", "H8",
}


def potlo_vonalak(vonalak):
    # A pótlásra utaló BKK-előtagot és a menetrendi nevet nézzük.
    eredeti = {}
    for azonosito, nev, tipus in vonalak:
        if (azonosito in VONALAK and nev and tipus is not None
                and tipus != 3 and not 700 <= tipus < 800):
            eredeti.setdefault(nev, []).append(azonosito)
    if "4-6" in eredeti:
        eredeti.setdefault("4", eredeti["4-6"])
        eredeti.setdefault("6", eredeti["4-6"])
    potlok = {}
    for azonosito, nev, tipus in vonalak:
        if tipus != 3 and not (tipus is not None and 700 <= tipus < 800):
            continue
        jelzes = None
        if azonosito.startswith(("VP", "TP", "MP", "HP")) or tipus == 714:
            jelzes = "potlovonal"
        elif nev in eredeti:
            jelzes = "azonos_nev_jelolt"
        if jelzes:
            parok = eredeti.get(nev, [])
            # A névegyezés kapcsolatjelölt. Több találatból nem választunk.
            potlok[azonosito] = (parok[0] if len(parok) == 1 else None, jelzes)
    return potlok


def ido_mp(szoveg):
    """A menetrendben az óra 24-nél nagyobb is lehet."""
    if szoveg is None or not szoveg.strip():
        return None
    reszek = szoveg.strip().split(":")
    if (len(reszek) != 3 or not all(r.isascii() and r.isdigit() for r in reszek)
            or len(reszek[1]) != 2 or len(reszek[2]) != 2):
        raise ValueError("Hibás menetrendi idő: " + szoveg)
    ora, perc, masodperc = map(int, reszek)
    if perc > 59 or masodperc > 59:
        raise ValueError("Hibás menetrendi idő: " + szoveg)
    return ora * 3600 + perc * 60 + masodperc


def menetrendi_ido(nap: date, masodperc: int, idozona="Europe/Budapest"):
    # A GTFS a helyi délből indul ki. Így az óraátállítás sem csúsztatja el.
    delben = datetime(nap.year, nap.month, nap.day, 12, tzinfo=ZoneInfo(idozona))
    napkezdet = delben.astimezone(UTC) - timedelta(hours=12)
    return napkezdet + timedelta(seconds=masodperc)


def _csv_sorok(csomag, nev):
    # A ZIP-ben lévő táblázatot soronként olvassuk, kicsomagolás nélkül.
    with (csomag.open(nev) as fajl,
          io.TextIOWrapper(fajl, encoding="utf-8-sig", newline="") as szoveg):
        yield from csv.DictReader(szoveg)


def _datum(szoveg):
    return datetime.strptime(szoveg, "%Y%m%d").date() if szoveg else None


def _szam(szoveg, tipus=int):
    return tipus(szoveg) if szoveg else None


def _masol(conn, tabla, oszlopok, sorok):
    # A sok menetrendi sort egyben küldjük az adatbázisnak.
    sql = "COPY " + tabla + " (" + ", ".join(oszlopok) + ") FROM STDIN"
    darab = 0
    with conn.cursor() as kurzor, kurzor.copy(sql) as masolas:
        for sor in sorok:
            masolas.write_row(sor)
            darab += 1
    return darab


def _szolgalati_napok(csomag, szolgalatok):
    # Előbb a heti rendet vesszük, utána alkalmazzuk a napi kivételeket.
    napok = {szolgalat: set() for szolgalat in szolgalatok}
    napnevek = ("monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday", "sunday")
    fajlok = csomag.namelist()
    if "calendar.txt" not in fajlok and "calendar_dates.txt" not in fajlok:
        raise ValueError("Hiányzik a menetrend szolgáltatási naptára.")
    if "calendar.txt" in fajlok:
        for sor in _csv_sorok(csomag, "calendar.txt"):
            szolgalat = sor["service_id"]
            if szolgalat not in szolgalatok:
                continue
            nap = _datum(sor["start_date"])
            vege = _datum(sor["end_date"])
            if nap is None or vege is None or nap > vege:
                raise ValueError("Hibás szolgáltatási időszak.")
            if any(sor[nev] not in ("0", "1") for nev in napnevek):
                raise ValueError("Hibás hétköznap a menetrendben.")
            while nap <= vege:
                if sor[napnevek[nap.weekday()]] == "1":
                    napok[szolgalat].add(nap)
                nap += timedelta(days=1)
    # A kivételek hozzáadnak vagy elvesznek egy konkrét napot.
    if "calendar_dates.txt" in fajlok:
        for sor in _csv_sorok(csomag, "calendar_dates.txt"):
            if sor["service_id"] not in szolgalatok:
                continue
            nap = _datum(sor["date"])
            if nap is None:
                raise ValueError("Hiányzó nap a menetrendi kivételek között.")
            szolgalat = sor["service_id"]
            if sor["exception_type"] == "1":
                napok[szolgalat].add(nap)
            elif sor["exception_type"] == "2":
                napok[szolgalat].discard(nap)
            else:
                raise ValueError("Ismeretlen menetrendi kivétel.")
    return {szolgalat: sorted(napok[szolgalat]) for szolgalat in szolgalatok}


def menetrend_betolt(conn, utvonal, sha256):
    """A hívó nyit tranzakciót; hiba esetén az egész betöltést visszavonja."""
    with Path(utvonal).open("rb") as fajl:
        tenyleges = hashlib.file_digest(fajl, "sha256").hexdigest()
    # A SHA256 a fájl ellenőrző összege. Ugyanahhoz a tartalomhoz ugyanaz tartozik.
    if tenyleges != sha256:
        raise ValueError("A menetrendi ZIP ellenőrző összege nem egyezik.")
    conn.execute(
        "INSERT INTO nyers_fajl (forras,sha256,fajl,nyers_bajt) "
        "VALUES ('Menetrend',%s,%s,%s) ON CONFLICT (forras,sha256) DO NOTHING",
        (sha256, str(Path(utvonal).resolve()), Path(utvonal).stat().st_size),
    )
    menetrend_id, kesz = conn.execute(
        "SELECT id, feldolgozva FROM nyers_fajl WHERE forras='Menetrend' AND sha256=%s",
        (sha256,),
    ).fetchone()
    if kesz:
        return {"kihagyva": True, "menetrend_id": menetrend_id}

    with ZipFile(utvonal) as csomag:
        fajlok = csomag.namelist()
        zonak = {sor["agency_timezone"] for sor in _csv_sorok(csomag, "agency.txt")}
        if len(zonak) != 1:
            raise ValueError("A menetrendhez egy közös időzóna szükséges.")
        idozona = zonak.pop()
        ZoneInfo(idozona)
        info = {}
        if "feed_info.txt" in fajlok:
            infosorok = list(_csv_sorok(csomag, "feed_info.txt"))
            if len(infosorok) > 1:
                raise ValueError("A feed_info több menetrendet tartalmaz.")
            if infosorok:
                info = infosorok[0]

        # A vonaljegyzék kicsi. A menetekből csak a kijelölt és pótló vonalak kellenek.
        vonalak = list(_csv_sorok(csomag, "routes.txt"))
        if not any(s["route_id"] in VONALAK for s in vonalak):
            raise ValueError("A kiválasztott vonalak nincsenek a menetrendben.")
        potlok = potlo_vonalak([(s["route_id"], s.get("route_short_name") or s.get("route_long_name"),
                                _szam(s.get("route_type"))) for s in vonalak])
        kivalasztott = VONALAK | potlok.keys()
        menetek = [s for s in _csv_sorok(csomag, "trips.txt")
                   if s["route_id"] in kivalasztott]
        menetazonositok = {s["trip_id"] for s in menetek}
        if len(menetazonositok) != len(menetek):
            raise ValueError("Ismétlődő menetazonosító a menetrendben.")
        if "frequencies.txt" in fajlok:
            for sor in _csv_sorok(csomag, "frequencies.txt"):
                if sor["trip_id"] in menetazonositok:
                    raise ValueError("A követési idővel megadott menetrend betöltése még nincs kész.")

        napok = _szolgalati_napok(csomag, {s["service_id"] for s in menetek})
        conn.execute(
            "UPDATE nyers_fajl SET menetrend_verzio=%s, ervenyes_tol=%s, "
            "ervenyes_ig=%s, idozona=%s WHERE id=%s",
            (info.get("feed_version") or None, _datum(info.get("feed_start_date")),
             _datum(info.get("feed_end_date")), idozona, menetrend_id),
        )
        eredmeny = {"kihagyva": False, "menetrend_id": menetrend_id}
        eredmeny["vonal"] = _masol(
            conn, "vonal", ("menetrend_id", "vonal_id", "nev", "tipus"),
            ((menetrend_id, s["route_id"], s.get("route_short_name") or s.get("route_long_name"),
              _szam(s.get("route_type"))) for s in vonalak),
        )
        # A megállólista kicsi; a teljes listát megtartjuk a zavarokhoz is.
        eredmeny["megallo"] = _masol(
            conn, "megallo", ("menetrend_id", "megallo_id", "nev", "lat", "lon"),
            ((menetrend_id, s["stop_id"], s.get("stop_name") or None,
              _szam(s.get("stop_lat"), float), _szam(s.get("stop_lon"), float))
             for s in _csv_sorok(csomag, "stops.txt")),
        )
        eredmeny["menet"] = _masol(
            conn, "menet", ("menetrend_id", "menet_id", "vonal_id", "szolgalat_id", "irany", "napok"),
            ((menetrend_id, s["trip_id"], s["route_id"], s["service_id"],
              _szam(s.get("direction_id")), napok[s["service_id"]]) for s in menetek),
        )
        eredmeny["megallasi_ido"] = _masol(
            conn, "megallasi_ido",
            ("menetrend_id", "menet_id", "sorrend", "megallo_id", "erkezes_mp", "indulas_mp",
             "erkezes", "indulas", "felszallas", "kiszallas"),
            ((menetrend_id, s["trip_id"], int(s["stop_sequence"]), s["stop_id"],
              ido_mp(s.get("arrival_time")), ido_mp(s.get("departure_time")),
              s.get("arrival_time") or None, s.get("departure_time") or None,
              _szam(s.get("pickup_type")), _szam(s.get("drop_off_type")))
             for s in _csv_sorok(csomag, "stop_times.txt") if s["trip_id"] in menetazonositok),
        )
        conn.execute("UPDATE nyers_fajl SET feldolgozva=true WHERE id=%s", (menetrend_id,))
        eredmeny["hianyzo_vonalak"] = sorted(VONALAK - {s["route_id"] for s in vonalak})
        return eredmeny


def zavar_betolt(conn, nyers_id, sorrend, elem):
    adat = elem.alert
    # A több időszak és érintettség listaként marad együtt a jelzéssel.
    teljes = MessageToDict(adat, preserving_proto_field_name=True, use_integers_for_enums=True)
    beszur(conn, "zavar", {
        "nyers_id": nyers_id, "sorrend": sorrend, "elem_id": elem.id,
        "ok": mezo(adat, "cause"),
        "hatas": mezo(adat, "effect"), "cim": magyar_szoveg(adat.header_text),
        "leiras": magyar_szoveg(adat.description_text),
        "idoszakok": Jsonb(teljes.get("active_period", [])),
        "erintettek": Jsonb(teljes.get("informed_entity", [])),
    })


def megfigyeles_betolt(conn, nyers_id, sorrend, elem, tipus, menetrend_id, vonal, feloldas,
                      potolt=None, potlas_jelzes=None):
    # A két forrás közös menetadatai egy helyre kerülnek.
    adat = getattr(elem, tipus)
    menet = adat.trip
    sor = {
        "nyers_id": nyers_id, "sorrend": sorrend, "elem_id": elem.id, "tipus": tipus,
        "menetrend_id": menetrend_id, "vonal_id": vonal, "feloldas": feloldas,
        "potolt_vonal_id": potolt, "potlas_jelzes": potlas_jelzes,
        "forras_vonal_id": mezo(menet, "route_id"), "menet_id": mezo(menet, "trip_id"),
        "szolgalati_nap": _datum(mezo(menet, "start_date")),
        "kezdes": mezo(menet, "start_time"), "irany": mezo(menet, "direction_id"),
        "menet_allapot": mezo(menet, "schedule_relationship"),
        "keses": mezo(adat, "delay") if tipus == "trip_update" else None,
        "jarmu_id": mezo(adat.vehicle, "id"), "adat_ido": idopont(mezo(adat, "timestamp")),
    }
    if tipus == "vehicle":
        # Csak a járműhelyzethez van koordináta és aktuális megálló.
        sor.update({
            "lat": mezo(adat.position, "latitude"),
            "lon": mezo(adat.position, "longitude"), "megallo_id": mezo(adat, "stop_id"),
            "megallo_sorrend": mezo(adat, "current_stop_sequence"),
            "jarmu_allapot": mezo(adat, "current_status"),
        })
    beszur(conn, "megfigyeles", sor)
    if tipus == "trip_update":
        # Egy menetfrissítés több megállóhoz is adhat becsült időpontot.
        for i, megallo in enumerate(adat.stop_time_update):
            beszur(conn, "megallo_frissites", {
                "nyers_id": nyers_id, "megfigyeles_sorrend": sorrend, "sorrend": i,
                "megallo_id": mezo(megallo, "stop_id"),
                "megallo_sorrend": mezo(megallo, "stop_sequence"),
                "allapot": mezo(megallo, "schedule_relationship"),
                "erkezes": idopont(mezo(megallo.arrival, "time")),
                "indulas": idopont(mezo(megallo.departure, "time")),
                "erkezes_keses": mezo(megallo.arrival, "delay"),
                "indulas_keses": mezo(megallo.departure, "delay"),
                "erkezes_bizonytalansag": mezo(megallo.arrival, "uncertainty"),
                "indulas_bizonytalansag": mezo(megallo.departure, "uncertainty"),
            })


def rt_betolt(conn, nyers_id, payload, forras, jelolt=None):
    # A mentett bináris válaszból kiolvassuk a fejlécet és az elemeket.
    feed = gtfs_realtime_pb2.FeedMessage.FromString(payload)
    if not feed.IsInitialized():
        raise ValueError("Hiányos valós idejű válasz.")
    conn.execute(
        "UPDATE nyers_fajl SET feed_ido=%s, feed_verzio=%s, menetrend_verzio=%s, "
        "novekmenyes=%s, jelolt_menetrend=%s WHERE id=%s",
        (idopont(mezo(feed.header, "timestamp")), feed.header.gtfs_realtime_version,
         mezo(feed.header, "feed_version"), feed.header.incrementality != 0, jelolt, nyers_id),
    )
    if feed.header.incrementality != 0 or feed.header.gtfs_realtime_version not in ("1.0", "2.0"):
        conn.execute("UPDATE nyers_fajl SET feldolgozasi_hiba=%s WHERE id=%s",
                     ("nem_tamogatott_feed", nyers_id))
        return

    menetrend_id = None
    if jelolt:
        # A gyűjtéskor ismert menetrend segít a hiányzó vonal azonosításában.
        par = conn.execute("SELECT id FROM nyers_fajl WHERE forras='Menetrend' "
                           "AND sha256=%s AND feldolgozva", (jelolt,)).fetchone()
        if not par:
            raise ValueError("Előbb töltsd be a hivatkozott menetrendet.")
        menetrend_id = par[0]
    statikus = dict(conn.execute(
        "SELECT menet_id, vonal_id FROM menet WHERE menetrend_id=%s", (menetrend_id,)
    ).fetchall()) if menetrend_id else {}
    vonalak = conn.execute("SELECT vonal_id, nev, tipus FROM vonal WHERE menetrend_id=%s",
                           (menetrend_id,)).fetchall() if menetrend_id else []
    ismert_vonalak = {s[0] for s in vonalak}
    potlok = potlo_vonalak(vonalak)
    tipus = {"VehiclePositions": "vehicle", "TripUpdates": "trip_update", "Alerts": "alert"}[forras]
    kihagyott = 0
    # Egy sor egy mentett válasz egy eleme. Ugyanazt a fájlt nem töltjük be kétszer.
    with conn.pipeline():
        # A sok beszúrást együtt küldjük; nem várunk külön minden sorra.
        for i, elem in enumerate(feed.entity):
            if not elem.HasField(tipus) or elem.is_deleted:
                kihagyott += 1
                continue
            if tipus == "alert":
                zavar_betolt(conn, nyers_id, i, elem)
                continue
            adat = getattr(elem, tipus)
            vonal = mezo(adat.trip, "route_id") or None
            par = statikus.get(adat.trip.trip_id)
            feloldas = "vonal_a_feedben" if vonal else "ismeretlen_vonal"
            if par:
                feloldas = "menetrendi_jelolt" if not vonal or vonal == par else "eltero_vonal"
                vonal = vonal or par
            potolt, jelzes = potlok.get(vonal, (None, None))
            allapot = mezo(adat.trip, "schedule_relationship")
            if not jelzes and vonal and vonal not in VONALAK:
                if vonal.startswith(("VP", "TP", "MP", "HP")):
                    jelzes = "vonaljel_jelolt"
                elif allapot in (gtfs_realtime_pb2.TripDescriptor.ADDED,
                                  gtfs_realtime_pb2.TripDescriptor.UNSCHEDULED,
                                  gtfs_realtime_pb2.TripDescriptor.REPLACEMENT,
                                  gtfs_realtime_pb2.TripDescriptor.DUPLICATED,
                                  gtfs_realtime_pb2.TripDescriptor.NEW):
                    jelzes = "uj_menet_jelolt"
                elif menetrend_id and vonal not in ismert_vonalak:
                    jelzes = "ismeretlen_vonal"
            if vonal and vonal not in VONALAK and not jelzes:
                kihagyott += 1
                continue
            megfigyeles_betolt(conn, nyers_id, i, elem, tipus, menetrend_id, vonal, feloldas,
                              potolt, jelzes)
    conn.execute("UPDATE nyers_fajl SET feldolgozva=true, kihagyott=%s WHERE id=%s",
                 (kihagyott, nyers_id))


def idojaras_betolt(conn, nyers_id, payload, rekord):
    # Egy válaszban három térség van; mindegyikből külön időjárási sor lesz.
    idojaras_adatok(payload, datetime.fromisoformat(rekord["vegzett_utc"]).timestamp())
    parameterek = rekord.get("parameterek")
    if not parameterek:
        raise ValueError("Hiányoznak az időjárási kérés paraméterei.")
    kert_lat = [float(x) for x in parameterek["latitude"].split(",")]
    kert_lon = [float(x) for x in parameterek["longitude"].split(",")]
    if len(kert_lat) != 3 or len(kert_lon) != 3:
        raise ValueError("Eltér az időjárási pontok száma.")
    for i, (nev, adat) in enumerate(zip(IDOJARAS_PONTOK, json.loads(payload))):
        aktualis = adat["current"]
        beszur(conn, "idojaras", {
            "nyers_id": nyers_id, "terseg": nev, "adat_ido": idopont(aktualis["time"]),
            "interval_mp": aktualis["interval"], "kert_lat": kert_lat[i], "kert_lon": kert_lon[i],
            "lat": adat["latitude"], "lon": adat["longitude"],
            "homerseklet": aktualis["temperature_2m"], "csapadek": aktualis["precipitation"],
            "szel": aktualis["wind_speed_10m"], "kod": aktualis["weather_code"],
            "egysegek": Jsonb(adat["current_units"]), "parameterek": Jsonb(parameterek),
        })
    conn.execute("UPDATE nyers_fajl SET feldolgozva=true WHERE id=%s", (nyers_id,))


def naplo_betolt(conn, adatmappa, naplofajl, jelolt=None):
    naplofajl = Path(naplofajl)
    naplo_adat = naplofajl.read_bytes()
    rekord = json.loads(naplo_adat)
    if rekord.get("teszt"):
        return False
    # A kérés azonosítója a fájlnév végén van, a -- jel után.
    azonosito = uuid.UUID(naplofajl.stem.split("--")[-1])
    naplo_hash = hashlib.sha256(naplo_adat).hexdigest()
    forras = rekord["forras"]
    if forras not in {"VehiclePositions", "TripUpdates", "Alerts", "Idojaras", "Menetrend"}:
        raise ValueError("Ismeretlen adatforrás.")
    # Egy napló és az összes belőle származó sor együtt készül el, vagy sehogy.
    with conn.transaction():
        # Két betöltő ne dolgozzon egyszerre ugyanazon az adatbázison.
        conn.execute("SELECT pg_advisory_xact_lock(741027)")
        regi = conn.execute("SELECT naplo_sha256 FROM lekeres WHERE id=%s", (azonosito,)).fetchone()
        if regi:
            if regi[0] != naplo_hash:
                raise ValueError("Megváltozott egy már betöltött napló.")
            return False
        nyers_id = None
        if rekord.get("fajl"):
            fajl = (Path(adatmappa) / rekord["fajl"]).resolve()
            if not fajl.is_relative_to(Path(adatmappa).resolve()):
                raise ValueError("A nyers fájl kilóg az adatmappából.")
            payload = gzip.decompress(fajl.read_bytes()) if fajl.suffix == ".gz" else fajl.read_bytes()
            if hashlib.sha256(payload).hexdigest() != rekord["sha256"]:
                raise ValueError("A nyers fájl ellenőrző összege nem egyezik.")
            regi = conn.execute("SELECT id, feldolgozva FROM nyers_fajl WHERE forras=%s AND sha256=%s",
                                (forras, rekord["sha256"])).fetchone()
            if regi:
                nyers_id, kesz = regi
            else:
                nyers_id = conn.execute(
                    "INSERT INTO nyers_fajl (forras,sha256,fajl,nyers_bajt) VALUES (%s,%s,%s,%s) RETURNING id",
                    (forras, rekord["sha256"], rekord["fajl"], len(payload)),
                ).fetchone()[0]
                kesz = False
            if not kesz and rekord["eredmeny"] in ("siker", "nem_valtozott"):
                if forras == "Menetrend":
                    menetrend_betolt(conn, fajl, rekord["sha256"])
                elif forras == "Idojaras":
                    idojaras_betolt(conn, nyers_id, payload, rekord)
                else:
                    jelolt = rekord.get("ismert_menetrend_sha256") or jelolt
                    rt_betolt(conn, nyers_id, payload, forras, jelolt)
        pontok = rekord.get("pontok", [])
        beszur(conn, "lekeres", {
            "id": azonosito, "naplo_sha256": naplo_hash, "forras": forras,
            "kezdett": datetime.fromisoformat(rekord["kezdett_utc"]),
            "vegzett": datetime.fromisoformat(rekord["vegzett_utc"]),
            "eredmeny": rekord["eredmeny"], "http_status": rekord.get("http_status"),
            "nyers_id": nyers_id, "ismert_menetrend_sha256": rekord.get("ismert_menetrend_sha256"),
            "jarmuvek": rekord.get("jarmuvek"), "menetfrissitesek": rekord.get("menetfrissitesek"),
            "feed_regi": rekord.get("feed_regi"),
            "regi_pontok": sum(p["regi"] for p in pontok) if pontok else None,
            "hianyzo_ertekek": sum(p["hianyzo_ertekek"] for p in pontok) if pontok else None,
        })
    return True


def main():
    # A kapcsolók mondják meg, melyik véges feladatot kell most elvégezni.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--beallitas", type=Path, default=Path(".env.db"))
    parser.add_argument("--letrehoz", action="store_true", help="Az üres táblák és nézet létrehozása.")
    parser.add_argument("--menetrend", type=Path, help="Egy már mentett menetrendi ZIP.")
    parser.add_argument("--adatmappa", type=Path, help="A gyűjtő adatmappája, a naplo könyvtár szülője.")
    parser.add_argument("--limit", type=int, default=20, help="Legfeljebb ennyi új napló (alapból 20).")
    parser.add_argument("--allapot", action="store_true", help="Rövid, csak olvasási összesítés.")
    args = parser.parse_args()
    if not any((args.letrehoz, args.menetrend, args.adatmappa, args.allapot)):
        parser.print_help()
        return
    if args.limit < 1:
        parser.error("A limit legalább 1 legyen.")
    with kapcsolat(args.beallitas) as conn:
        if args.letrehoz:
            sema(conn)
            print("A táblák és az adatminőség-nézet készen vannak.")
        jelolt = None
        if args.menetrend:
            with args.menetrend.open("rb") as fajl:
                jelolt = hashlib.file_digest(fajl, "sha256").hexdigest()
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(741027)")
                eredmeny = menetrend_betolt(conn, args.menetrend, jelolt)
            print("Menetrend: " + json.dumps(eredmeny, ensure_ascii=False))
        if args.adatmappa:
            fajlok = sorted((args.adatmappa / "naplo").glob("*/*.json"))
            if not fajlok:
                raise ValueError("Nem találtam naplókat ebben az adatmappában.")
            uj = 0
            for fajl in fajlok:
                if naplo_betolt(conn, args.adatmappa, fajl, jelolt):
                    uj += 1
                if uj >= args.limit:
                    break
            print("Új naplók: " + str(uj) + ". A korábbiakat nem töltöttem be újra.")
        if args.allapot:
            for tabla in ("nyers_fajl", "lekeres", "vonal", "megallo", "menet", "megallasi_ido",
                          "megfigyeles", "megallo_frissites", "zavar", "idojaras"):
                darab = conn.execute("SELECT count(*) FROM " + tabla).fetchone()[0]
                print(tabla + ": " + str(darab))
            meret = conn.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
            print("Adatbázis mérete: " + meret)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, psycopg.Error) as hiba:
        # A kapcsolódási hiba teljes szövegében jelszó is lehet.
        print("A betöltés megállt: " + type(hiba).__name__ + ". Az aktuális napló nem lett félig betöltve.",
              file=sys.stderr)
        raise SystemExit(1) from None
