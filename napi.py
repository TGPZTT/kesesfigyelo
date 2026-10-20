"""Egy lezárt nap elemzése vagy kész eredményének letöltése. Gyűjtést nem indít."""

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

import elemzes
from gyujto import IDOJARAS_PONTOK

VONALAK = ["0460", "0975", "1610", "1695", "3010", "3020", "3030", "3046", "4800", "4820"]
ZONA = ZoneInfo("Europe/Budapest")
MAX_MERET = 25 * 1024 * 1024
FAJLOK = ("indulasok.json", "adatminoseg.json")
HIBA = "A napi frissítés nem sikerült. A korábbi kész eredmények megmaradtak."
HIBAK = {
    "nincs_kesz": "A nap vagy a betöltött adatok még nem állnak készen az elemzésre.",
    "menetrend": "A menetrendváltozatokat ellenőrizni kell, ezért nem készült új eredmény.",
    "adatbazis": "Az adatbázis elérése vagy olvasása nem sikerült.",
    "atadas": "A szerveres eredmény átvitele nem sikerült.",
    "ellenorzes": "Az adatok vagy beállítások ellenőrzése nem sikerült.",
    "fajl": "A helyi fájl olvasása vagy mentése nem sikerült.",
    "ismeretlen": "A frissítés váratlan hiba miatt megszakadt.",
}


class NapiHiba(ValueError):
    def __init__(self, kod):
        self.kod = kod if isinstance(kod, str) and kod in HIBAK else "ismeretlen"
        super().__init__(HIBAK[self.kod])


def lepes(kod, muvelet, *args, **kwargs):
    # Csak a lépés rögzített hibakódja marad meg, a kapcsolatadatok nem.
    try:
        return muvelet(*args, **kwargs)
    except NapiHiba:
        raise
    except psycopg.Error:
        raise NapiHiba("adatbazis") from None
    except (ValueError, OSError, subprocess.SubprocessError):
        raise NapiHiba(kod) from None


def hiba_besorolas(hiba):
    if isinstance(hiba, NapiHiba):
        return hiba.kod
    if isinstance(hiba, psycopg.Error):
        return "adatbazis"
    if isinstance(hiba, (ValueError, TypeError, KeyError)):
        return "ellenorzes"
    if isinstance(hiba, OSError):
        return "fajl"
    return "ismeretlen"


def lezart_nap(szoveg=None, most=None):
    most = (most or datetime.now(UTC)).astimezone(ZONA)
    nap = date.fromisoformat(szoveg) if szoveg else most.date() - timedelta(days=1)
    hatar = datetime.combine(nap + timedelta(days=1), datetime.min.time(), ZONA) + timedelta(hours=4)
    if most < hatar:
        raise NapiHiba("nincs_kesz")
    return nap


def json_ir(cel, adat):
    # A nagy export tömör szöveg, a kis állapotfájl embernek is olvasható.
    forma = {"separators": (",", ":")} if cel.name == "indulasok.json" else {"indent": 2}
    szoveg = json.dumps(adat, ensure_ascii=False, allow_nan=False, **forma)
    atmeneti = cel.with_name(cel.name + ".tmp")
    atmeneti.write_text(szoveg, encoding="utf-8")
    atmeneti.replace(cel)


def json_olvas(cel):
    if cel.stat().st_size > MAX_MERET:
        raise ValueError("Túl nagy eredményfájl.")
    return json.loads(cel.read_text(encoding="utf-8"))


def veges(adat):
    if isinstance(adat, float) and not math.isfinite(adat):
        raise ValueError("Nem véges szám az eredményben.")
    if isinstance(adat, dict):
        for kulcs, ertek in adat.items():
            if kulcs == "n" and (type(ertek) is not int or ertek < 0):
                raise ValueError("Hibás mintanagyság.")
            veges(ertek)
    if isinstance(adat, list):
        for ertek in adat:
            veges(ertek)


def napi_orak(nap):
    kezdet = datetime.combine(nap, datetime.min.time(), ZONA)
    veg = (kezdet + timedelta(days=1)).astimezone(UTC)
    ido = kezdet.astimezone(UTC)
    while ido < veg:
        yield ido
        ido += timedelta(hours=1)


def idojaras_adatbazisbol(conn, nap):
    kezdet = datetime.combine(nap, datetime.min.time(), ZONA)
    veg = kezdet + timedelta(days=1)
    # Az óra végén közölt csapadék az előző negyedórához tartozik.
    # Az utolsó órához ezért a következő éjfél adata is kell.
    sorok = conn.execute("""
        WITH keresek AS (
            SELECT nyers_id,min(vegzett) rogzitve
            FROM lekeres
            WHERE forras='Idojaras' AND eredmeny='siker'
              AND kezdett >= %s AND kezdett < %s
            GROUP BY nyers_id)
        SELECT DISTINCT ON (i.terseg,i.adat_ido)
               i.nyers_id,i.terseg,i.adat_ido,i.interval_mp,
               i.homerseklet,i.csapadek,i.szel,i.kod,k.rogzitve
        FROM keresek k JOIN idojaras i ON i.nyers_id=k.nyers_id
        JOIN nyers_fajl n ON n.id=i.nyers_id
        WHERE i.adat_ido >= %s AND i.adat_ido <= %s
          AND n.feldolgozva AND n.feldolgozasi_hiba IS NULL
          AND k.rogzitve-i.adat_ido BETWEEN INTERVAL '-5 seconds' AND INTERVAL '1800 seconds'
        ORDER BY i.terseg,i.adat_ido,k.rogzitve DESC,i.nyers_id DESC
        """, (kezdet - timedelta(minutes=30), veg + timedelta(minutes=30), kezdet, veg)).fetchall()
    return [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in s.items()} for s in sorok]


def idojaras_orankent(sorok, nap):
    # Ugyanazon modellidő új változatából a később rögzítettet használjuk.
    egyedi = {}
    for sor in sorok:
        if sor.get("terseg") not in IDOJARAS_PONTOK or sor.get("interval_mp") != 900:
            raise ValueError("Eltérő időjárási térség vagy időtartam.")
        ido = datetime.fromisoformat(sor["adat_ido"])
        rogzitve = datetime.fromisoformat(sor.get("rogzitve", sor["adat_ido"]))
        if ido.tzinfo is None or rogzitve.tzinfo is None:
            raise ValueError("Hiányzik az időjárás időzónája.")
        if ido.minute % 15 or ido.second or ido.microsecond:
            raise ValueError("Az időjárás nem negyedórás időpontra vonatkozik.")
        for nev in ("homerseklet", "csapadek", "szel"):
            ertek = sor.get(nev)
            if ertek is not None and (type(ertek) not in (int, float) or not math.isfinite(ertek)):
                raise ValueError("Hibás időjárási érték.")
            if nev != "homerseklet" and ertek is not None and ertek < 0:
                raise ValueError("Negatív csapadék vagy szél.")
        kulcs = (sor["terseg"], ido.astimezone(UTC))
        elozo = egyedi.get(kulcs)
        if elozo is None or rogzitve > elozo[0]:
            egyedi[kulcs] = (rogzitve, sor)
        elif rogzitve == elozo[0] and any(sor.get(k) != elozo[1].get(k)
                                        for k in ("homerseklet", "csapadek", "szel", "interval_mp")):
            raise ValueError("Ellentmondó időjárási változatok.")
    eredmeny = []
    for ora in napi_orak(nap):
        veg = ora + timedelta(hours=1)
        for terseg in IDOJARAS_PONTOK:
            pontok = [(ido, s[1]) for (hely, ido), s in egyedi.items() if hely == terseg]
            hom = [s["homerseklet"] for ido, s in pontok if ora <= ido < veg and s.get("homerseklet") is not None]
            szel = [s["szel"] for ido, s in pontok if ora <= ido < veg and s.get("szel") is not None]
            csap = sorted((ido, s["csapadek"]) for ido, s in pontok
                          if ora < ido <= veg and s.get("csapadek") is not None)
            # Nem arányosítunk és nem töltünk ki rést nullával.
            elvart = [ora + timedelta(minutes=15 * i) for i in range(1, 5)]
            teljes = [ido for ido, _ in csap] == elvart
            eredmeny.append({
                "terseg": terseg, "ora_utc": ora.strftime("%Y-%m-%dT%H"),
                "homerseklet_min": min(hom) if hom else None,
                "homerseklet_max": max(hom) if hom else None,
                "homerseklet_atlag": sum(hom) / len(hom) if hom else None,
                "szel_atlag": sum(szel) / len(szel) if szel else None,
                "szel_max": max(szel) if szel else None,
                "csapadek_mm": sum(ertek for _, ertek in csap) if teljes else None,
                "negyedorak": len(csap), "elvart_negyedorak": 4,
                "homerseklet_mintak": len(hom), "szel_mintak": len(szel)})
    return eredmeny


def hev_adatbazisbol(conn, nap, menetrend):
    try:
        # H8-hiba esetén a savepoint visszaáll, a tíz alapvonal kiadható marad.
        with conn.transaction():
            kornyezet = lepes("menetrend", elemzes.minta_kornyezete, conn, nap, ["H8"], menetrend)
            menetek = list(elemzes.adatbazisbol(conn, nap, ["H8"], menetrend))
            return {"nap": str(nap), "menetrend_id": menetrend, "mintamenetek": None,
                    "menetek": menetek, **kornyezet}
    except Exception as hiba:  # noqa: BLE001 -- A külön H8-hiba rögzített alstátuszt kap.
        return {"nap": str(nap), "allapot": "hiba", "hiba_kod": hiba_besorolas(hiba)}


def hev_szamol(minta, nap):
    if minta is None:
        return {"nap": str(nap), "allapot": "nincs_minta", "hiba_kod": "nincs_minta"}
    if not isinstance(minta, dict):
        return {"nap": str(nap), "allapot": "hiba", "hiba_kod": "ellenorzes"}
    if minta.get("allapot") == "hiba":
        kod = minta.get("hiba_kod")
        return {"nap": str(nap), "allapot": "hiba",
                "hiba_kod": kod if isinstance(kod, str) and kod in HIBAK else "ismeretlen"}
    try:
        if minta.get("nap") != str(nap) or minta.get("mintamenetek"):
            raise ValueError("Eltérő H8-minta.")
        if any(s.get("vonal_id") != "H8" for s in minta["menetek"]):
            raise ValueError("Más vonal került a H8-mintába.")
        adat = elemzes.feldolgozas(minta, nap)
        adat.pop("esemenyek")
        veges(adat)
        if not adat["vonalak"] or not sum(s["keseshez_hasznalt"] for s in adat["vonalak"]):
            adat.update(allapot="nincs_hasznalhato", hiba_kod="nincs_hasznalhato")
        else:
            adat.update(allapot="kesz", hiba_kod=None)
        return adat
    except Exception as hiba:  # noqa: BLE001 -- A H8 számítási hibája nem írhat ki nyers kivételt.
        return {"nap": str(nap), "allapot": "hiba", "hiba_kod": hiba_besorolas(hiba)}


def ellenoriz(adat, minoseg, nap, vonalak=None, kell_indulas=True):
    if not isinstance(adat, dict) or adat.get("nap") != str(nap) or adat.get("mintamenetek"):
        raise ValueError("Nem a kért teljes nap eredménye.")
    veges(adat)
    veges(minoseg)
    sorok = adat.get("vonalak")
    if not isinstance(sorok, list) or not sorok:
        raise ValueError("Nincs vonaleredmény.")
    azonositok = [s["vonal_id"] for s in sorok]
    if len(set(azonositok)) != len(azonositok) or vonalak and set(azonositok) != set(vonalak):
        raise ValueError("Eltér a kiválasztott vonalak köre.")
    for sor in sorok:
        for kulcs in ("tervezett", "keseshez_hasznalt", "tervezett_menetek", "hasznalt_menetek"):
            if type(sor.get(kulcs)) is not int or sor[kulcs] < 0:
                raise ValueError("Hibás darabszám.")
        if not sor["tervezett"] or sor["keseshez_hasznalt"] > sor["tervezett"]:
            raise ValueError("Hibás indulási mintanagyság.")
        if sor["hasznalt_menetek"] > sor["tervezett_menetek"]:
            raise ValueError("Hibás menetszám.")
        if (type(sor["lefedettseg"]) not in (int, float) or not 0 <= sor["lefedettseg"] <= 1
                or not math.isclose(sor["lefedettseg"], sor["keseshez_hasznalt"] / sor["tervezett"])):
            raise ValueError("Hibás lefedettség.")
        if adat.get("modszer") in (elemzes.MODSZER, elemzes.HEV_MODSZER):
            keretek = sor.get("idokeretek", [])
            if (sum(db for _, _, db in keretek) != sor["keseshez_hasznalt"]
                    or any(a > b or b - a > 120 or type(db) is not int or db <= 0 for a, b, db in keretek)):
                raise ValueError("Hiányos vagy hibás indulási időkeretek.")
    if kell_indulas and not sum(s["keseshez_hasznalt"] for s in sorok):
        raise ValueError("Nincs egyetlen használható indulás sem.")
    if "menet_lathatosag" in adat:
        jelenlet = adat["menet_lathatosag"]
        if (not isinstance(jelenlet, list) or len(jelenlet) != len(sorok)
                or {s["vonal_id"] for s in jelenlet} != set(azonositok)):
            raise ValueError("Hiányos menetjelenlét.")
        for sor in jelenlet:
            menetek = sor["menetek"]
            kulcsok = [(m["menet_id"], m["szolgalati_nap"]) for m in menetek]
            if len(kulcsok) != len(set(kulcsok)):
                raise ValueError("Ismételt menet a jelenléti listában.")
            for m in menetek:
                if not isinstance(m["menet_id"], str) or not m["menet_id"]:
                    raise ValueError("Hibás menetazonosító.")
                date.fromisoformat(m["szolgalati_nap"])
                if type(m["pozicio"]) is not bool or type(m["menetfrissites"]) is not bool:
                    raise ValueError("Hibás jelenlétjelző.")
            szamok = {
                "tervezett_menetek": len(menetek),
                "latott_menetek": sum(m["pozicio"] or m["menetfrissites"] for m in menetek),
                "nem_latott_menetek": sum(not m["pozicio"] and not m["menetfrissites"] for m in menetek),
                "pozicioval": sum(m["pozicio"] for m in menetek),
                "menetfrissitessel": sum(m["menetfrissites"] for m in menetek)}
            if any(type(sor[k]) is not int or sor[k] != v for k, v in szamok.items()):
                raise ValueError("A menetlista és az összesítés eltér.")
            terv = next(s["tervezett_menetek"] for s in sorok if s["vonal_id"] == sor["vonal_id"])
            if terv != len(menetek):
                raise ValueError("Eltér a jelenléti és az indulási menetek száma.")
    for kulcs in ("orankent", "szakaszok", "kovetesi_orak", "kozos_buszok"):
        if not isinstance(adat.get(kulcs), list):
            raise TypeError("Hiányos elemzés.")
    if not isinstance(adat.get("kovetesi_reszek"), dict):
        raise TypeError("Hiányzik a követés elemzése.")
    if not isinstance(minoseg, list) or not minoseg:
        raise ValueError("Hiányzik az órás gyűjtési minőség.")
    orak = set()
    for sor in minoseg:
        ido = datetime.fromisoformat(sor["ora_utc"] + ":00:00+00:00")
        if ido.astimezone(ZONA).date() != nap or sor["ora_utc"] in orak:
            raise ValueError("Hibás vagy ismétlődő minőségi óra.")
        orak.add(sor["ora_utc"])
        if set(sor["forrasok"]) != {"VehiclePositions", "TripUpdates", "Alerts", "Idojaras"}:
            raise ValueError("Hiányos forráslista.")
        for forras in sor["forrasok"].values():
            for kulcs in ("probak", "siker", "hibak"):
                if type(forras.get(kulcs)) is not int or forras[kulcs] < 0:
                    raise ValueError("Hibás lekérési darabszám.")
            if forras["probak"] != forras["siker"] + forras["hibak"]:
                raise ValueError("Nem egyeznek a lekérési darabszámok.")
    kezdet = datetime.combine(nap, datetime.min.time(), ZONA)
    elvart = int(((kezdet + timedelta(days=1)).timestamp() - kezdet.timestamp()) / 3600)
    if len(orak) != elvart:
        raise ValueError("Nem teljes a minőségexport naptári napja.")
    hev = adat.get("hev")
    if hev is not None:
        if not isinstance(hev, dict) or hev.get("nap") != str(nap):
            raise ValueError("Hibás H8-kiegészítés.")
        if hev.get("allapot") == "kesz":
            if hev.get("hiba_kod") is not None or "hev" in hev or "esemenyek" in hev:
                raise ValueError("Hibás H8-eredmény.")
            ellenoriz(hev, minoseg, nap, ["H8"])
        elif hev.get("allapot") == "nincs_hasznalhato":
            if "hev" in hev or "esemenyek" in hev or hev.get("hiba_kod") != "nincs_hasznalhato" or any(
                    s.get("vonal_id") != "H8" or s.get("keseshez_hasznalt") != 0 for s in hev.get("vonalak", [])):
                raise ValueError("Ellentmondó H8-adathiány.")
            if hev.get("vonalak") == []:
                if any(hev.get(k) for k in ("orankent", "szakaszok", "menet_lathatosag")):
                    raise ValueError("Üres H8-vonalhoz nem tartozhat eredmény.")
            else:
                ellenoriz(hev, minoseg, nap, ["H8"], kell_indulas=False)
        elif not (hev.get("allapot") == "nincs_minta" and hev.get("hiba_kod") == "nincs_minta"
                  or hev.get("allapot") == "hiba" and hev.get("hiba_kod") in HIBAK):
            raise ValueError("Hiányzó H8-alstátusz.")
    if "idojaras" in adat:
        elvart_parok = {(t, o.strftime("%Y-%m-%dT%H")) for t in IDOJARAS_PONTOK for o in napi_orak(nap)}
        parok = []
        for s in adat["idojaras"]:
            parok.append((s["terseg"], s["ora_utc"]))
            for k in ("negyedorak", "homerseklet_mintak", "szel_mintak"):
                if type(s.get(k)) is not int or not 0 <= s[k] <= 4:
                    raise ValueError("Hibás időjárási mintanagyság.")
            if s.get("elvart_negyedorak") != 4 or ((s["csapadek_mm"] is not None) != (s["negyedorak"] == 4)):
                raise ValueError("Hiányos órához nem adható teljes csapadék.")
            for k in ("homerseklet_min", "homerseklet_max", "homerseklet_atlag", "szel_atlag", "szel_max", "csapadek_mm"):
                if s[k] is not None and (type(s[k]) not in (int, float) or not math.isfinite(s[k])):
                    raise ValueError("Hibás órás időjárás.")
            for db, mezok in (("homerseklet_mintak", ("homerseklet_min", "homerseklet_atlag", "homerseklet_max")),
                              ("szel_mintak", ("szel_atlag", "szel_max"))):
                if any((s[db] == 0) != (s[m] is None) for m in mezok):
                    raise ValueError("Ellentmondó időjárási mintanagyság.")
                ertekek = [s[m] for m in mezok]
                if s[db] and any(a > b and not math.isclose(a, b) for a, b in pairwise(ertekek)):
                    raise ValueError("Ellentmondó időjárási minimum és maximum.")
            if any(s[m] is not None and s[m] < 0 for m in ("szel_atlag", "szel_max", "csapadek_mm")):
                raise ValueError("Negatív órás csapadék vagy szél.")
        if len(parok) != len(set(parok)) or set(parok) != elvart_parok:
            raise ValueError("Hiányos vagy ismételt időjárási órák.")


@contextmanager
def zar(alap):
    hely = alap / ".napi-zar"
    hely.mkdir(exist_ok=True)
    # A fájl megmarad, a zárat a rendszer oldja fel kilépéskor vagy áramkimaradáskor.
    with (hely / "futas.lock").open("a+b") as fajl:
        if not fajl.tell():
            fajl.write(b"0")
            fajl.flush()
        fajl.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fajl.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fajl.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise FileExistsError("Már fut napi frissítés.") from None
        try:
            yield
        finally:
            fajl.seek(0)
            if os.name == "nt":
                msvcrt.locking(fajl.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fajl.fileno(), fcntl.LOCK_UN)


def allapot(alap, nap, siker, most, forras_allapot=None, hiba_kod=None):
    cel = alap / ".napi-allapot.json"
    try:
        elozo = json_olvas(cel)
    except (OSError, ValueError):
        elozo = {}
    kod = hiba_kod if isinstance(hiba_kod, str) and hiba_kod in HIBAK else "ismeretlen"
    adat = {"utolso_probalkozas_utc": most.isoformat(), "allapot": "sikeres" if siker else "hiba",
            "nap": str(nap) if nap else None, "hiba": None if siker else HIBA,
            "hiba_kod": None if siker else kod,
            "utolso_siker_utc": most.isoformat() if siker else elozo.get("utolso_siker_utc")}
    if forras_allapot is not None:
        adat["forras_allapot"] = forras_allapot
    elif "forras_allapot" in elozo:
        adat["forras_allapot"] = elozo["forras_allapot"]
    json_ir(cel, adat)


def tiszta_allapot(adat):
    eredmeny = {"allapot": "ismeretlen", "nap": None, "utolso_probalkozas_utc": None,
               "utolso_siker_utc": None, "hiba": None, "hiba_kod": None}
    if not isinstance(adat, dict):
        return eredmeny
    if adat.get("allapot") in ("sikeres", "hiba"):
        eredmeny["allapot"] = adat["allapot"]
        eredmeny["hiba"] = HIBA if adat["allapot"] == "hiba" else None
        if adat["allapot"] == "hiba":
            kod = adat.get("hiba_kod")
            eredmeny["hiba_kod"] = kod if isinstance(kod, str) and kod in HIBAK else "ismeretlen"
    for nev in ("nap", "utolso_probalkozas_utc", "utolso_siker_utc"):
        ertek = adat.get(nev)
        if isinstance(ertek, str) and len(ertek) <= 40:
            try:
                if nev == "nap":
                    eredmeny[nev] = date.fromisoformat(ertek).isoformat()
                elif datetime.fromisoformat(ertek).tzinfo:
                    eredmeny[nev] = datetime.fromisoformat(ertek).astimezone(UTC).isoformat()
            except ValueError:
                pass
    return eredmeny


def minoseg_adatbazisbol(conn, nap):
    kezdet = datetime.combine(nap, datetime.min.time(), ZONA)
    sorok = conn.execute("SELECT * FROM adatminoseg WHERE ora_utc >= %s AND ora_utc < %s ORDER BY ora_utc,forras",
                         (kezdet, kezdet + timedelta(days=1))).fetchall()
    orak = {}
    for sor in sorok:
        ora = sor["ora_utc"].astimezone(UTC).strftime("%Y-%m-%dT%H")
        adat = {k: float(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, datetime) else v
                for k, v in sor.items() if k not in ("ora_utc", "forras")}
        orak.setdefault(ora, {})[sor["forras"]] = adat
    return [{"ora_utc": k, "forrasok": v} for k, v in orak.items()]


def adat_szegely(conn, nap):
    kezdet = datetime.combine(nap, datetime.min.time(), ZONA)
    hatar = kezdet + timedelta(days=1, hours=4)
    sorok = conn.execute("""
        SELECT l.forras, min(l.kezdett) elso, max(l.kezdett) utolso,
               max(n.feed_ido) forras_utolso
        FROM lekeres l JOIN nyers_fajl n ON n.id=l.nyers_id
        WHERE l.forras IN ('VehiclePositions','TripUpdates') AND l.eredmeny='siker'
          AND n.feldolgozva AND NOT coalesce(l.feed_regi, true)
          AND l.kezdett <= statement_timestamp() AND n.feed_ido <= l.vegzett
        GROUP BY l.forras
        """).fetchall()
    if len(sorok) != 2 or any(s["elso"] > kezdet or s["utolso"] < hatar
                             or s["forras_utolso"] < hatar - timedelta(minutes=3) for s in sorok):
        raise ValueError("A betöltött források még nem érnek túl a nap négyórás szegélyén.")
    hibas = conn.execute("""
        SELECT count(*) n FROM lekeres l JOIN nyers_fajl n ON n.id=l.nyers_id
        WHERE l.forras IN ('VehiclePositions','TripUpdates') AND l.kezdett >= %s
          AND l.kezdett < %s AND (NOT n.feldolgozva OR n.feldolgozasi_hiba IS NOT NULL)
        """, (kezdet - timedelta(hours=4), hatar)).fetchone()
    if hibas["n"]:
        raise ValueError("A napi források betöltése még nem hibamentes.")
    return {"ellenorzott_utc": datetime.now(UTC).isoformat(),
            "nap_utani_hatar": hatar.isoformat(),
            "forrasok": [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in s.items()}
                        for s in sorok]}


def menetrend_kivalasztas(conn, nap):
    kezdet = datetime.combine(nap, datetime.min.time(), ZONA)
    sor = conn.execute("""
        SELECT min(n.id) id FROM nyers_fajl n
        WHERE n.forras='Menetrend' AND n.feldolgozva
          AND n.ervenyes_tol <= %s AND n.ervenyes_ig >= %s
          AND EXISTS (
            SELECT 1 FROM lekeres l WHERE l.ismert_menetrend_sha256=n.sha256
              AND l.forras IN ('VehiclePositions','TripUpdates') AND l.eredmeny='siker'
              AND l.kezdett >= %s AND l.kezdett < %s)
        """, (nap, nap, kezdet, kezdet + timedelta(days=1))).fetchone()
    if not sor or sor["id"] is None:
        raise ValueError("Nincs a nap sikeres lekéréseihez kötött érvényes menetrend.")
    # A minta_kornyezete ezután az összes érintett változat tartalmát összeveti.
    return sor["id"]


def minta_es_minoseg(args, nap, vonalak):
    if args.minta:
        if not args.minoseg:
            raise ValueError("Mentett mintához mentett minőségexport is kell.")
        with gzip.open(args.minta, "rt", encoding="utf-8") as fajl:
            adatok = json.load(fajl)
        minoseg = json_olvas(args.minoseg)
    else:
        if args.menetrend is not None and args.menetrend <= 0:
            raise ValueError("Hibás menetrendazonosító.")
        with lepes("adatbazis", elemzes.kapcsolat, args.beallitas) as conn:
            conn.row_factory = dict_row
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                conn.execute("SET LOCAL statement_timeout='120s'")
                szegely = lepes("nincs_kesz", adat_szegely, conn, nap)
                menetrend = args.menetrend if args.menetrend is not None else lepes(
                    "menetrend", menetrend_kivalasztas, conn, nap)
                kornyezet = lepes("menetrend", elemzes.minta_kornyezete, conn, nap, vonalak, menetrend)
                kornyezet["potlasi_minta"] = elemzes.potlasi_minta(conn, nap, ["H8"])
                menetek = list(elemzes.adatbazisbol(conn, nap, vonalak, menetrend))
                minoseg = minoseg_adatbazisbol(conn, nap)
                if set(vonalak) == set(VONALAK):
                    kornyezet["hev_minta"] = hev_adatbazisbol(conn, nap, menetrend)
                    kornyezet["hev_minta"]["potlasi_minta"] = kornyezet["potlasi_minta"]
                try:
                    with conn.transaction():
                        kornyezet["idojaras_minta"] = idojaras_adatbazisbol(conn, nap)
                except Exception as hiba:  # noqa: BLE001 -- A külön időjárási hiba csak tisztított állapot.
                    kornyezet["idojaras_minta"] = []
                    kornyezet["idojaras_hiba_kod"] = hiba_besorolas(hiba)
        adatok = {"nap": str(nap), "menetrend_id": menetrend, "mintamenetek": None,
                  "menetek": menetek, "adat_szegely": szegely, **kornyezet}
    if (adatok.get("nap") != str(nap) or not isinstance(adatok.get("menetek"), list)
            or not adatok["menetek"] or adatok.get("mintamenetek") or "kizarasok" not in adatok):
        raise ValueError("Hiányos vagy eltérő napi minta.")
    return adatok, minoseg


def szamol(adatok, nap):
    adat = elemzes.feldolgozas(adatok, nap)
    adat.pop("esemenyek")
    adat["adat_szegely"] = adatok.get("adat_szegely")
    if {s["vonal_id"] for s in adat["vonalak"]} == set(VONALAK):
        adat["hev"] = hev_szamol(adatok.get("hev_minta"), nap)
    adat["idojaras"] = idojaras_orankent(adatok.get("idojaras_minta", []), nap)
    hiba = adatok.get("idojaras_hiba_kod")
    adat["idojaras_leiras"] = {
        "allapot": "hiba" if hiba else "kesz" if adatok.get("idojaras_minta") else
                   "nincs_adat" if "idojaras_minta" in adatok else "nincs_minta",
        "hiba_kod": hiba if isinstance(hiba, str) and hiba in HIBAK else "ismeretlen" if hiba else None,
        "forras": "Open-Meteo", "tipus": "modelladat",
        "egysegek": {"homerseklet": "°C", "csapadek": "mm", "szel": "km/h"},
        "homerseklet_szel_ido": "[ora_utc, ora_utc + 1 ora)",
        "csapadek_ido": "(ora_utc, ora_utc + 1 ora] vegu elozo 900 masodperc"}
    return adat


def kozzetes(alap, szakasz, nev):
    adatmap = alap / "data"
    adatmap.mkdir(exist_ok=True)
    cel = adatmap / nev
    if cel.exists():
        raise ValueError("Ez az eredménymappa már létezik.")
    # Az előkészítés ugyanazon lemezen történik. A kész mappa egyszerre jelenik meg.
    szakasz.rename(cel)
    return cel


def keszit(args, alap, szakasz, nap, most):
    vonalak = args.vonal.split(",")
    adatok, minoseg = minta_es_minoseg(args, nap, vonalak)
    adat = szamol(adatok, nap)
    ellenoriz(adat, minoseg, nap, vonalak)
    azonosito = nap.strftime("%Y%m%d") + "-" + most.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    mintanev = "elemzesi-mintak-" + azonosito
    mintamappa = szakasz / "minta"
    mintamappa.mkdir()
    with gzip.open(mintamappa / "minta.json.gz", "wt", encoding="utf-8", compresslevel=1) as fajl:
        json.dump(adatok, fajl, ensure_ascii=False, allow_nan=False)
    export = szakasz / "export"
    export.mkdir()
    adat.update(napi_sema=1, minta_fajl=mintanev + "/minta.json.gz")
    adat.setdefault("keszult_utc", most.isoformat())
    json_ir(export / "indulasok.json", adat)
    json_ir(export / "adatminoseg.json", minoseg)
    ellenoriz(json_olvas(export / "indulasok.json"), json_olvas(export / "adatminoseg.json"), nap, vonalak)
    kozzetes(alap, mintamappa, mintanev)
    return kozzetes(alap, export, "elemzes-" + azonosito)


def letolt(args, alap, szakasz, nap):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.letoltes):
        raise ValueError("Hibás SSH-gépnév.")
    # A távoli parancs állandó kód. A nap dátumból készül, útvonalat nem veszünk át.
    kod = """
import hashlib,json,re
from pathlib import Path
alap=Path('/home/ubuntu/kesesfigyelo/data')
jeloltek=sorted(p for p in alap.glob('elemzes-DATUM-*')
    if p.is_dir() and re.fullmatch(r'elemzes-[0-9]{8}-[0-9]{8}T[0-9]{12}Z-[a-f0-9]{8}',p.name))
keresett=set(VONALAK)
hibas=False
p=None
for jelolt in reversed(jeloltek):
    try:
        f=jelolt/'indulasok.json'
        if f.stat().st_size>26214400: raise ValueError()
        a=json.loads(f.read_text(encoding='utf-8'))
        if a.get('napi_sema')==1 and a.get('nap')=='NAP' and {s['vonal_id'] for s in a['vonalak']}==keresett:
            p=jelolt
            break
    except (OSError,ValueError,KeyError,TypeError):
        hibas=True
if p is None: raise SystemExit(1)
fajlok={}
for nev in ('indulasok.json','adatminoseg.json'):
    f=p/nev
    if f.stat().st_size>26214400: raise SystemExit(1)
    b=f.read_bytes()
    fajlok[nev]={'meret':len(b),'sha256':hashlib.sha256(b).hexdigest()}
try:
    statuszfajl=alap.parent/'.napi-allapot.json'
    if statuszfajl.stat().st_size>8192: raise ValueError()
    statusz=json.loads(statuszfajl.read_text(encoding='utf-8'))
    statusz={k:statusz.get(k) for k in ('allapot','nap','utolso_probalkozas_utc','utolso_siker_utc','hiba_kod')}
except (OSError,ValueError,AttributeError):
    statusz={}
if hibas: statusz['allapot']='hiba'
print(json.dumps({'mappa':p.name,'fajlok':fajlok,'forras_allapot':statusz}))
""".replace("DATUM", nap.strftime("%Y%m%d")).replace("NAP", str(nap)).replace("VONALAK", repr(args.vonal.split(",")))
    opciok = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15"]
    ablak = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    valasz = lepes("atadas", subprocess.run, ["ssh", *opciok, args.letoltes, "python3 -c " + shlex.quote(kod)],
                   capture_output=True, check=True, timeout=60, creationflags=ablak)
    if len(valasz.stdout) > 8192:
        raise ValueError("Hibás távoli eredménylista.")
    leiras = json.loads(valasz.stdout)
    nev = leiras["mappa"]
    if not re.fullmatch("elemzes-" + nap.strftime("%Y%m%d") + r"-[0-9]{8}T[0-9]{12}Z-[a-f0-9]{8}", nev):
        raise ValueError("Hibás távoli mappanév.")
    if set(leiras["fajlok"]) != set(FAJLOK):
        raise ValueError("Hiányos távoli export.")
    megvan = alap / "data" / nev
    export = megvan if megvan.exists() else szakasz / "export"
    if not megvan.exists():
        export.mkdir()
        for fajl in FAJLOK:
            adat = leiras["fajlok"][fajl]
            if type(adat["meret"]) is not int or not 0 < adat["meret"] <= MAX_MERET:
                raise ValueError("Túl nagy vagy üres távoli fájl.")
            forras = args.letoltes + ":/home/ubuntu/kesesfigyelo/data/" + nev + "/" + fajl
            lepes("atadas", subprocess.run, ["scp", *opciok, forras, str(export / fajl)],
                  capture_output=True, check=True, timeout=180, creationflags=ablak)
    for fajl in FAJLOK:
        tartalom = (export / fajl).read_bytes()
        adat = leiras["fajlok"][fajl]
        if len(tartalom) != adat["meret"] or hashlib.sha256(tartalom).hexdigest() != adat["sha256"]:
            raise ValueError("Eltér a letöltött fájl ellenőrző összege.")
    ellenoriz(json_olvas(export / FAJLOK[0]), json_olvas(export / FAJLOK[1]), nap, args.vonal.split(","))
    cel = megvan if megvan.exists() else kozzetes(alap, export, nev)
    return cel, tiszta_allapot(leiras.get("forras_allapot"))


def main(argv=None, alap=None, most=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nap", help="Alapból a tegnapi budapesti naptári nap, leghamarabb 04 órától.")
    parser.add_argument("--menetrend", type=int, help="GTFS-azonosító. Alapból a nap lekéréseiből választ, majd összevet.")
    parser.add_argument("--vonal", default=",".join(VONALAK))
    parser.add_argument("--beallitas", type=Path, default=Path(".env.db"))
    parser.add_argument("--minta", type=Path, help="Újraszámítás mentett teljes napi mintából.")
    parser.add_argument("--minoseg", type=Path, help="A mintához tartozó mentett órás minőségexport.")
    parser.add_argument("--letoltes", metavar="SSH_GEP", help="Csak a kész kis export letöltése, például kesesfigyelo.")
    args = parser.parse_args(argv)
    alap = Path(alap or Path(__file__).resolve().parent)
    rogzitett_ido = most
    most = most or datetime.now(UTC)
    nap = None
    try:
        with zar(alap):
            try:
                nap = lezart_nap(args.nap, most)
                vonalak = args.vonal.split(",")
                if (not vonalak or len(set(vonalak)) != len(vonalak)
                        or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", v) for v in vonalak)):
                    raise ValueError("Hibás vonalazonosítók.")
                if args.letoltes and (args.minta or args.minoseg or args.menetrend):
                    raise ValueError("A letöltés és az elemzés külön művelet.")
                if not args.beallitas.is_absolute():
                    args.beallitas = alap / args.beallitas
                atmeneti = alap / ".napi-atmeneti"
                atmeneti.mkdir(exist_ok=True)
                # A saját ideiglenes könyvtárat a Python kezeli és takarítja.
                with tempfile.TemporaryDirectory(dir=atmeneti) as hely:
                    szakasz = Path(hely)
                    if args.letoltes:
                        cel, forras_allapot = letolt(args, alap, szakasz, nap)
                    else:
                        cel, forras_allapot = keszit(args, alap, szakasz, nap, most), None
                allapot(alap, nap, True, rogzitett_ido or datetime.now(UTC), forras_allapot)
                print("Elkészült " + cel.name)
                return 0
            except Exception as hiba:
                # Sem adatbázis-hibából, sem SSH-kimenetből nem kerül titok a naplóba.
                allapot(alap, nap, False, rogzitett_ido or datetime.now(UTC), hiba_kod=hiba_besorolas(hiba))
                raise
    except Exception as hiba:  # noqa: BLE001 -- A programhatáron az ismeretlen hiba sem írhat ki kapcsolatadatot.
        print(HIBA + " " + HIBAK[hiba_besorolas(hiba)])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
