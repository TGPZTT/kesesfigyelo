"""Indulások keresése mentett adatokban. A gyűjtőhöz nem nyúl."""

import argparse
import gzip
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from betolto import kapcsolat, menetrendi_ido

MODSZER = "kozles-haladas-ajto-4"
HEV_MODSZER = "hev-kozles-kontroll-4"


def menetrendi_kozlesek(sorok):
    """A terv változásai a beérkezés sorrendjében, a hiány visszatérésével együtt."""
    elozo, eredmeny = {}, []
    sorok = [s for s in sorok if type(s.get("feed_ido")) in (int, float) and math.isfinite(s["feed_ido"])]
    for s in sorted(sorok, key=kozles_sorrend):
        sorrend = s.get("sorrend")
        alairas = tuple(s.get(k) for k in ("megallo_id", "forras_tervezett_erkezes",
                                         "forras_tervezett_indulas", "menet_allapot"))
        if sorrend not in elozo or elozo[sorrend] != alairas:
            eredmeny.append({k: s.get(k) for k in ("sorrend", "megallo_id", "feed_ido", "adat_ido",
                                                 "forras_tervezett_erkezes", "forras_tervezett_indulas",
                                                 "menet_allapot")})
            elozo[sorrend] = alairas
    return eredmeny


def menetrendi_alap(menet):
    """A GTFS a fő alap; az előzetes BKK-terv külön diagnosztika."""
    if menet.get("menetrend_feloldva") == MODSZER:
        return menet
    # A régi, már feloldott bemenet BKK-tervét sem engedjük vissza a fő alapba.
    megallok = sorted((dict(s, tervezett=s.get("gtfs_tervezett", s["tervezett"]),
                            tervezett_erkezes=s.get("gtfs_tervezett_erkezes", s.get("tervezett_erkezes")))
                       for s in menet["megallok"]), key=lambda s: s["sorrend"])
    if not megallok:
        return dict(menet, menetrend_feloldva=MODSZER)
    mozgas_kezdetek = []
    # A legelső követhető mozgásnál már korábban is úton lehetett a jármű.
    # Az ennél későbbi tervet ezért nem visszük vissza a teljes út elejére.
    for pontok in helyzetek(menet, monoton=False).values():
        for a, b in pairwise(pontok):
            if pontpar_jo(a, b) and tavolsag(a, b) >= 30:
                mozgas_kezdetek.append(a["adat_ido"])
                break
    hatar = min(mozgas_kezdetek, default=megallok[0]["tervezett"])
    # Ritkított közlésből nem található ki, mikor jelent meg először a terv.
    tortenet = [s for s in (menet.get("menetrendi_kozlesek") or [])
                if type(s.get("feed_ido")) in (int, float) and math.isfinite(s["feed_ido"])]
    terv, ellentmond = {}, set()
    for s in sorted(tortenet, key=kozles_sorrend):
        if s.get("feed_ido") is None:
            continue
        i = s["sorrend"]
        if s["feed_ido"] <= hatar:
            elozo = terv.get(i)
            mezok = ("megallo_id", "forras_tervezett_erkezes", "forras_tervezett_indulas", "menet_allapot")
            if elozo and elozo["feed_ido"] == s["feed_ido"] and any(elozo.get(k) != s.get(k) for k in mezok):
                ellentmond.add(i)
            elif elozo and elozo["feed_ido"] < s["feed_ido"]:
                ellentmond.discard(i)
            terv[i] = s
    kesobb_valtozo = {s["sorrend"] for s in tortenet if s.get("feed_ido", 0) > hatar
                     and s.get("forras_tervezett_indulas") != terv.get(s["sorrend"], {}).get("forras_tervezett_indulas")}
    allapot = "nincs_eloterv" if "menetrendi_kozlesek" in menet else "nincs_tervtortenet"
    hasznal = False
    van = any(s.get("forras_tervezett_indulas") is not None for s in terv.values())
    if van and not hev_vonal(menet["vonal_id"]):
        teljes = all(s["sorrend"] in terv and terv[s["sorrend"]].get("forras_tervezett_indulas") is not None
                     for s in megallok)
        allapot = "reszleges_eloterv"
        if teljes:
            elozmeny = None
            hasznal = not ellentmond
            for s in megallok:
                t = terv[s["sorrend"]]
                de = t["forras_tervezett_indulas"]
                ar = t.get("forras_tervezett_erkezes")
                hasznal &= (t.get("megallo_id") == s["megallo_id"] and (t.get("menet_allapot") or 0) == 0
                            and (ar is None or ar <= de)
                            and (elozmeny is None or elozmeny <= (ar if ar is not None else de)))
                elozmeny = de
            allapot = "bkk_eloterve" if hasznal else "hibas_eloterv"
            if hasznal and all(terv[s["sorrend"]]["forras_tervezett_indulas"] == s["tervezett"] for s in megallok):
                allapot = "bkk_egyezik"
    if hev_vonal(menet["vonal_id"]):
        allapot = "hev_gtfs"
    uj = []
    for s in megallok:
        t = terv.get(s["sorrend"], {})
        de = t.get("forras_tervezett_indulas")
        ar = t.get("forras_tervezett_erkezes")
        # A korábban közölt terv sem bizonyítja a kihirdetett menetrend módosítását.
        uj.append(dict(s, gtfs_tervezett=s["tervezett"], gtfs_tervezett_erkezes=s.get("tervezett_erkezes"),
                       menetrendi_forras="gtfs", bkk_terv_ellenorzott=hasznal,
                       bkk_tervezett_indulas=de if hasznal else None,
                       bkk_tervezett_erkezes=ar if hasznal else None,
                       terv_allapot=allapot, terv_hatar=hatar, terv_feed=t.get("feed_ido"),
                       forras_tervezett_indulas=de, forras_tervezett_erkezes=ar,
                       terv_kesobb_valtozott=s["sorrend"] in kesobb_valtozo))
    return dict(menet, megallok=uj, menetrend_feloldva=MODSZER)


def helyzetek(menet, monoton=True):
    """Saját mérési idő szerinti pontok. A hibás pont megszakítja a láncot."""
    megallok = {s["sorrend"]: s for s in menet["megallok"]}
    csoportok = defaultdict(list)
    for p in menet["poziciok"]:
        if p.get("adat_ido") is not None and p.get("jarmu_id"):
            csoportok[(p["jarmu_id"], p["adat_ido"])].append(p)
    eredmeny = defaultdict(list)
    for (jarmu, ido), valtozatok in sorted(csoportok.items()):
        p = dict(valtozatok[0])
        mezok = ("sorrend", "megallo_id", "allapot", "menet_allapot", "lat", "lon",
                 "sebesseg", "ajto_nyitva", "letert")
        megallo = megallok.get(p.get("sorrend"))
        koordinata = all(type(p.get(k)) in (int, float) and math.isfinite(p[k]) for k in ("lat", "lon"))
        p["jo"] = bool(
            megallo and p.get("megallo_id") == megallo["megallo_id"]
            and p.get("menet_allapot", 0) == 0 and p.get("allapot", 2) in (0, 1, 2)
            and koordinata and -90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180
            and all(all(p.get(k) == v.get(k) for k in mezok) for v in valtozatok)
            and all(v.get("feed_ido") is None or ido <= v["feed_ido"] + 5 for v in valtozatok))
        eredmeny[jarmu].append(p)
    for pontok in (eredmeny.values() if monoton else ()):
        legnagyobb = -1
        for p in pontok:
            if p["jo"]:
                if p["sorrend"] < legnagyobb:
                    p["jo"] = False
                legnagyobb = max(legnagyobb, p["sorrend"])
    return eredmeny


def hev_vonal(vonal):
    return vonal.startswith("H") and vonal[1:].isdigit()


def kozles_sorrend(sor):
    # Azonos saját időhöz is érkezhet újabb válasz. A feed ideje az elsődleges.
    return sor.get("feed_ido", kozles_ideje(sor)), kozles_ideje(sor)


def ertekelheto(sor):
    """Ellenőrzött idő, a kapott azonosító szerinti tervvel. Nem független igazolás."""
    return sor["indulas"] is not None and sor["menetrend_ok"]


def terv_osszegzes(sorok):
    """A mozgás ellenőrzése és a menetrendi alap külön marad az exportban."""
    return {"bkk_terv_db": sum(s.get("bkk_terv_ellenorzott", False) for s in sorok),
            "eltero_terv_db": sum(s.get("bkk_terv_ellenorzott", False)
                                  and s["bkk_tervezett_indulas"] != s["tervezett"] for s in sorok),
            "utolagos_terv_db": sum(s.get("terv_kesobb_valtozott", False) for s in sorok),
            "nagy_elteres_db": sum(abs(s["keses_mp"]) >= 1800 for s in sorok)}


def fennallo_torles(kozlesek):
    """A státusz a válaszhoz tartozik, nem a korábbi járműmérés idejéhez."""
    torles = None
    valaszok = defaultdict(list)
    for s in kozlesek:
        valaszok[s.get("feed_ido", kozles_ideje(s))].append(s)
    for ido, sorok in sorted(valaszok.items()):
        if any(s.get("menet_allapot", 0) == 3 for s in sorok):
            if torles is None:
                torles = ido
        elif (torles is not None and all(s.get("menet_allapot", 0) == 0 for s in sorok)
              and any(s.get("adat_ido") is not None and torles <= s["adat_ido"] <= ido + 5 for s in sorok)):
            # Újabb, már a törlés jelzése utáni járműadat kell a visszaállításhoz.
            torles = None
    return torles


def vegso_kozles(frissitesek, megallo, jarmu):
    """Az utolsó ismert változatot két külön saját időnek kell alátámasztania."""
    if not frissitesek:
        return None, "nincs_kozles"
    if any(s.get("adat_ido") is not None and s.get("feed_ido") is not None
           and s["adat_ido"] > s["feed_ido"] + 5 for s in frissitesek):
        return None, "jovobeli_sajat_ido"
    csoportok = defaultdict(list)
    for s in frissitesek:
        csoportok[(s.get("adat_ido"), s.get("feed_ido"))].append(s)
    mezok = ("indulas", "bizonytalansag", "allapot", "menet_allapot", "megallo_id", "jarmu_id")
    if any(len({tuple(s.get(k) for k in mezok) for s in sorok}) > 1 for sorok in csoportok.values()):
        return None, "azonos_ido_ellentmondas"
    # A TU saját ideje a felhasznált járműadaté. Az új válasz ezt változatlanul
    # hagyva is javíthatja a becslést. A válaszok sorrendjét a feed ideje adja.
    rendezett = sorted(frissitesek, key=kozles_sorrend)
    utolso = rendezett[-1]
    if any(s.get("allapot", 0) == 1 for s in frissitesek):
        return None, "kihagyott"
    if utolso.get("allapot", 0) != 0 or utolso.get("menet_allapot", 0) != 0:
        return None, "forras_allapot"
    ido = utolso.get("indulas")
    if (ido is None or utolso.get("adat_ido") is None or ido > utolso["adat_ido"]
            or utolso.get("bizonytalansag") != 0):
        return None, "nem_multbeli_vegso"
    if any(s.get("jarmu_id") not in (None, jarmu) or s.get("megallo_id") != megallo["megallo_id"]
           for s in frissitesek):
        return None, "azonositas"
    egyedi = {s["adat_ido"]: s for s in rendezett if s.get("adat_ido") is not None}
    utolso_ketto = sorted(egyedi.values(), key=kozles_sorrend)[-2:]
    if len(utolso_ketto) != 2 or any(
            s.get("indulas") != ido or ido > s["adat_ido"] or s.get("bizonytalansag") != 0
            or s.get("allapot", 0) != 0 or s.get("menet_allapot", 0) != 0 for s in utolso_ketto):
        return None, "nem_stabil"
    return utolso, None


def tovabbhaladas(pontok, megallo, ido):
    """Közeli, folytonos mozgás. Megállást vagy ajtónyitást nem követel meg."""
    kozeli = [p for p in pontok if abs(p["adat_ido"] - ido) <= 120]
    elotte = [p for p in kozeli if p["jo"] and p["adat_ido"] <= ido
              and p["sorrend"] <= megallo["sorrend"]]
    if not elotte:
        return None, "nincs_elotte"
    a = elotte[-1]
    utana = [p for p in kozeli if p["jo"] and p["adat_ido"] >= ido
             and p["sorrend"] > megallo["sorrend"] and tavolsag(p, megallo) >= 40
             and tavolsag(a, p) >= 30]
    if not utana:
        return None, "nincs_utana"
    b = utana[0]
    lanc = [p for p in kozeli if a["adat_ido"] <= p["adat_ido"] <= b["adat_ido"]]
    if b["adat_ido"] - a["adat_ido"] > 120:
        return None, "ritka_helyzet"
    if any(not p["jo"] or p.get("letert") is True for p in lanc):
        return None, "hibas_helyzet"
    # A már elhagyott megállóhoz nem fogadunk el későbbi indulást.
    if any(p["adat_ido"] < ido - 5 and p["sorrend"] > megallo["sorrend"]
           and tavolsag(p, megallo) >= 100 for p in lanc):
        return None, "korabban_tovabbhaladt"
    for x, y in pairwise(lanc):
        if (y["adat_ido"] <= x["adat_ido"] or tavolsag(x, y) / (y["adat_ido"] - x["adat_ido"]) > 45):
            return None, "hibas_mozgas"
        if y["sorrend"] < x["sorrend"] and not (
                y["sorrend"] == megallo["sorrend"] and tavolsag(y, megallo) <= 100
                and (y.get("ajto_nyitva") is True or y.get("allapot") == 1)):
            return None, "visszalepes"
    # Ha nincs közeli pont, a két helyzet közti szakasznak kell a megálló közelében haladnia.
    skala = math.cos(math.radians(megallo["lat"]))
    ax, ay = (a["lon"] - megallo["lon"]) * skala, a["lat"] - megallo["lat"]
    dx, dy = (b["lon"] - a["lon"]) * skala, b["lat"] - a["lat"]
    arany = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    tav = math.hypot(ax + arany * dx, ay + arany * dy) * 111_200
    if min(tavolsag(a, megallo), tavolsag(b, megallo)) > 100 and tav > 100:
        return None, "nem_erinti_a_megallot"
    return (a["adat_ido"], b["adat_ido"]), None


def vegighaladas_hatarok(menet, pontok):
    """Visszatérés egy már bejárt szakaszra, két-két továbbhaladással jelezve."""
    megallok = {s["sorrend"]: s for s in menet["megallok"]
                if all(type(s.get(k)) in (int, float) and math.isfinite(s[k]) for k in ("lat", "lon"))}
    sorozatok, sorozat = [], []
    for a, b in pairwise(pontok):
        megallo = megallok.get(a.get("sorrend"))
        if not (megallo and pontpar_jo(a, b) and b["sorrend"] > a["sorrend"]
                and tavolsag(a, megallo) <= 100 and tavolsag(b, megallo) >= 40
                and tavolsag(a, b) >= 30):
            continue
        jel = (a["sorrend"], a["adat_ido"], b["adat_ido"])
        if sorozat and jel[0] <= sorozat[-1][0]:
            # Egy közeli sorszámjavítás még nem másik végighaladás.
            if jel[1] - sorozat[-1][2] <= 120:
                continue
            sorozatok.append(sorozat)
            sorozat = []
        sorozat.append(jel)
    sorozatok.append(sorozat)
    kovethetok = [s for s in sorozatok if len(s) >= 2]
    hatarok = []
    for elozo, uj in pairwise(kovethetok):
        if uj[0][0] <= elozo[-1][0]:
            # Az új sorozat első indulása előtt már érkezhetett közeli helyzet.
            kezdet = min((p["adat_ido"] for p in pontok
                          if elozo[-1][2] < p["adat_ido"] <= uj[0][1] and p["jo"]
                          and p["sorrend"] <= uj[0][0] and p["sorrend"] in megallok
                          and tavolsag(p, megallok[p["sorrend"]]) <= 100), default=uj[0][1])
            hatarok.append(kezdet)
    return hatarok


def ellenorzott_indulasok(menet, vegallomas=False):
    """Utólagos közlés, mozgással ellenőrizve. A HÉV külön forráscsoport."""
    menet = menetrendi_alap(menet)
    hev = hev_vonal(menet["vonal_id"])
    pontok = helyzetek(menet, monoton=False)
    vp_azonositok = {p.get("jarmu_id") for p in menet["poziciok"] if p.get("jarmu_id")}
    tu_azonositok = {s.get("jarmu_id") for s in menet["kozlesek"] if s.get("jarmu_id")}
    jarmu = next(iter(vp_azonositok)) if len(vp_azonositok) == 1 and tu_azonositok <= vp_azonositok else None
    frissitesek = defaultdict(list)
    for s in menet["kozlesek"]:
        frissitesek[s.get("sorrend")].append(s)
    torles = menet["torles_ido"] if "torles_ido" in menet else fennallo_torles(menet["kozlesek"])
    eredmeny = mozgasbol_indulasok(menet, vegallomas)
    for s in eredmeny:
        s.update(mozgasos_indulas=s["indulas"], mozgas_also=s["also"], mozgas_felso=s["felso"],
                 indulas=None, keses_mp=None, also=None, felso=None, ok=[], minoseg="bizonytalan",
                 esemeny_tipus=None, ajto_ellenorzes="nem_hasznalhato" if hev else "nincs_minta",
                 forras_csoport="hev" if hev else "bkk", jarmu_menetbol=False, elutasitas=None,
                 modszer=HEV_MODSZER if hev else MODSZER, tu_egyezes=None)
        hiba = None
        sorok = frissitesek[s["sorrend"]]
        jelolt = max(sorok, key=kozles_sorrend, default={})
        s["jelolt"] = jelolt.get("indulas")
        if torles is not None:
            sorok = [u for u in sorok if u.get("feed_ido", kozles_ideje(u)) < torles]
        if not jarmu:
            hiba = "azonositas"
        elif (any(type(s.get(k)) not in (int, float) or not math.isfinite(s[k]) for k in ("lat", "lon"))
              or not -90 <= s["lat"] <= 90 or not -180 <= s["lon"] <= 180):
            hiba = "megallo_helyzet"
        else:
            jelolt, hiba = vegso_kozles(sorok, s, jarmu)
        if not hiba:
            ido = jelolt["indulas"]
            s["jelolt"] = ido
            keret, hiba = tovabbhaladas(pontok[jarmu], s, ido)
            if not hiba and torles is not None and keret[1] >= torles:
                hiba = "torolt"
        if not hiba:
            kozel = [p for p in pontok[jarmu] if p["jo"] and p["sorrend"] == s["sorrend"]
                     and abs(p["adat_ido"] - ido) <= 120 and tavolsag(p, s) <= 100]
            ajtok = [p for p in kozel if p.get("ajto_nyitva") is not None]
            nyitott = [p for p in ajtok if p.get("ajto_nyitva") is True]
            if not hev:
                s["ajto_ellenorzes"] = "nyitott_minta" if nyitott else "csak_zart" if ajtok else "nincs_minta"
                # Öt másodperc technikai tűrés, nem igazolt mérési pontosság.
                if any(p["adat_ido"] > ido + 5 for p in nyitott):
                    hiba = "kesobbi_nyitott_ajto"
                    s["ajto_ellenorzes"] = "ellentmond"
            s["kesobbi_allas"] = any(p.get("allapot") == 1 and p["adat_ido"] > ido + 5 for p in kozel)
            s["esemeny_tipus"] = "megallas_jelevel" if nyitott or any(p.get("allapot") == 1 for p in kozel) else "tovabbhaladas"
        if hiba:
            if hiba == "azonositas":
                s.update(erkezes=None, erkezes_also=None, erkezes_felso=None, jarmu_id=None)
            if torles is not None and hiba != "kihagyott":
                hiba = "torolt"
            s.update(elutasitas=hiba, minoseg=hiba if hiba in ("torolt", "kihagyott") else "bizonytalan")
            if not pontok and not menet["kozlesek"]:
                s["minoseg"] = "nem_lattuk"
            s["ok"].append(hiba)
            continue
        s.update(indulas=ido, keses_mp=ido - s["tervezett"], also=keret[0], felso=keret[1],
                 jarmu_id=jarmu, jarmu_menetbol=jelolt.get("jarmu_id") is None, menetrend_ok=True,
                 minoseg="hev_kozles" if hev else "ajtojel" if nyitott else "kovetett")
        s["keses_gtfs_mp"] = ido - s["gtfs_tervezett"]
        if s["mozgas_also"] is not None:
            s["tu_egyezes"] = s["mozgas_also"] <= ido <= s["mozgas_felso"]
    # A közölt idők sem fordíthatják meg ugyanannak a járműnek a megállósorrendjét.
    jok = [s for s in eredmeny if s["indulas"] is not None]
    hibas = {id(s) for a, b in pairwise(jok) if b["indulas"] < a["indulas"] for s in (a, b)}
    for s in jok:
        if id(s) in hibas:
            s.update(indulas=None, keses_mp=None, minoseg="bizonytalan", elutasitas="forditott_idorend")
            s["ok"].append("forditott_idorend")
    # Külön végighaladások részleteiből nem készülhet egyetlen összerakott út.
    # A késés nagyságától független ellenőrzés. A hosszú, helyben várakozó
    # járművet nem zárja ki, és a megállás nélküli továbbhaladás is számít.
    jok = [s for s in eredmeny if s["indulas"] is not None]
    hatarok = vegighaladas_hatarok(menet, pontok[jarmu]) if jarmu and jok else []
    if jok and any(min(s["also"] for s in jok) < t <= max(s["also"] for s in jok) for t in hatarok):
        for s in eredmeny:
            s.update(indulas=None, keses_mp=None, also=None, felso=None, erkezes=None,
                     erkezes_also=None, erkezes_felso=None, tu_egyezes=None,
                     minoseg="bizonytalan", elutasitas="kevert_vegighaladas")
            s["ok"].append("kevert_vegighaladas")
    for s in eredmeny:
        s["keses_bkk_terv_mp"] = (s["indulas"] - s["bkk_tervezett_indulas"]
                                 if s["indulas"] is not None and s["bkk_terv_ellenorzott"] else None)
    return eredmeny


def pontpar_jo(a, b):
    ido = b["adat_ido"] - a["adat_ido"]
    tav = tavolsag(a, b) if a["jo"] and b["jo"] else None
    return (tav is not None and 0 < ido <= 120 and tav / ido <= 45
            and a["sorrend"] <= b["sorrend"])


def megallasi_idokeretek(pontok, megallo):
    """A mozgás adja a határokat. A menetrendi és a TU-idő itt nem szerepel."""
    if (any(type(megallo.get(k)) not in (int, float) or not math.isfinite(megallo[k]) for k in ("lat", "lon"))
            or not -90 <= megallo["lat"] <= 90 or not -180 <= megallo["lon"] <= 180):
        return None, None
    sorrend = megallo["sorrend"]
    indulasi, erkezesi = [], []
    for i, a in enumerate(pontok):
        if not (a["jo"] and a["sorrend"] == sorrend and a.get("allapot", 2) == 1
                and tavolsag(a, megallo) <= 100):
            continue
        if i:
            b = pontok[i - 1]
            if (pontpar_jo(b, a) and b.get("allapot", 2) != 1
                    and b["sorrend"] == sorrend and tavolsag(b, megallo) >= 40
                    and tavolsag(a, b) >= 30):
                erkezesi.append((b["adat_ido"], a["adat_ido"]))
        # Az utolsó álló ponttól az első megfelelő továbbhaladásig.
        # Közben hibás adatot, visszalépést vagy újabb állást nem ugrunk át.
        elozo = a
        for b in pontok[i + 1:]:
            if not pontpar_jo(elozo, b) or b["adat_ido"] - a["adat_ido"] > 120:
                break
            if b["sorrend"] == sorrend and b.get("allapot", 2) == 1:
                break
            if b["sorrend"] > sorrend and tavolsag(b, megallo) >= 40 and tavolsag(a, b) >= 30:
                indulasi.append((a["adat_ido"], b["adat_ido"]))
                break
            elozo = b
    # Két elkülönülő megállólátogatást nem választunk ki a TU-hoz igazítva.
    indulas = indulasi[0] if len(indulasi) == 1 else None
    erkezes = erkezesi[0] if len(erkezesi) == 1 else None
    if indulas and erkezes and erkezes[1] > indulas[0]:
        erkezes = None
    return indulas, erkezes


def mozgasbol_indulasok(menet, vegallomas=False):
    """Az időpont az időkeret közepe, nem másodpercre megmért indulás."""
    megallok = sorted(menet["megallok"], key=lambda s: s["sorrend"])
    pontok = helyzetek(menet)
    kozlesek = menet["kozlesek"]
    torlesek = [kozles_ideje(s) for s in kozlesek if s.get("menet_allapot") == 3]
    torles = min(torlesek) if torlesek else None
    eredmeny = []
    for i, megallo in enumerate(megallok):
        utolso = i == len(megallok) - 1
        if (utolso and not vegallomas) or megallo.get("tervezett") is None:
            continue
        if not vegallomas and megallo.get("felszallas", 0) != 0:
            continue
        sor = {k: menet[k] for k in ("menet_id", "szolgalati_nap", "vonal_id", "irany")}
        sor.update(megallo)
        sor.update(indulas=None, erkezes=None, also=None, felso=None, erkezes_also=None, erkezes_felso=None,
                   keses_mp=None, minoseg="bizonytalan", menetrend_ok=True, jarmu_id=None, ok=[],
                   kovetkezo_sorrend=megallok[i + 1]["sorrend"] if not utolso else None,
                   ors_fele=any(s["megallo_id"] == "008029" and s.get("kiszallas", 0) == 0 for s in megallok[i + 1:]),
                   megalloban_idok=[], jelolt=None, tu_egyezes=None)
        jeloltek = []
        for jarmu, sorozat in pontok.items():
            indul, erkezik = megallasi_idokeretek(sorozat, megallo)
            if indul or erkezik:
                jeloltek.append((jarmu, indul, erkezik))
        eredmeny.append(sor)
        if len(jeloltek) != 1:
            sor["ok"].append("Nincs egyértelmű, helyzettel közrefogott megállólátogatás.")
            if not pontok and not kozlesek:
                sor["minoseg"] = "nem_lattuk"
            continue
        jarmu, indul, erkezik = jeloltek[0]
        if torles is not None and (indul is None or indul[1] > torles):
            sor.update(minoseg="torolt", menetrend_ok=False)
            continue
        frissitesek = [s for s in kozlesek if s.get("sorrend") == megallo["sorrend"]]
        if any(s.get("allapot", 0) == 1 for s in frissitesek):
            sor["ok"].append("A forrás kihagyott megállást is jelzett.")
            sor.update(minoseg="kihagyott", menetrend_ok=False)
            continue
        sor["jarmu_id"] = jarmu
        if erkezik:
            sor.update(erkezes_also=erkezik[0], erkezes_felso=erkezik[1],
                       erkezes=sum(erkezik) / 2)
        if not indul:
            sor["ok"].append("Az elindulást nem fogja közre két megfelelő helyzetadat.")
            continue
        sor.update(also=indul[0], felso=indul[1], indulas=sum(indul) / 2,
                   keses_mp=sum(indul) / 2 - sor["tervezett"], minoseg="alatamasztott")
        sor["megalloban_idok"] = [p["adat_ido"] for p in pontok[jarmu]
                                  if p["jo"] and p["sorrend"] == megallo["sorrend"] and p.get("allapot") == 1]
        # A TU csak összevetés. Nem szűkíti a mérési keretet és nem választ látogatást.
        multbeli = [s for s in frissitesek if s.get("adat_ido") is not None and s.get("indulas") is not None
                    and s["indulas"] <= s["adat_ido"] and s.get("bizonytalansag") == 0
                    and s.get("megallo_id") == megallo["megallo_id"]
                    and s.get("jarmu_id") in (None, jarmu) and s.get("menet_allapot", 0) == 0]
        if multbeli:
            vegso = max(multbeli, key=lambda s: (s["adat_ido"], s.get("feed_ido", 0)))
            sor["jelolt"] = vegso["indulas"]
            sor["tu_egyezes"] = indul[0] <= vegso["indulas"] <= indul[1]
        if sor["keses_mp"] < -300 or sor["keses_mp"] > 3600:
            # Az eltérés nagysága önmagában nem ok a késések eltüntetésére.
            sor["ok"].append("Nagy menetrendi eltérés, az összesítésben benne marad.")
    return eredmeny


def intervallum_osszegzes(sorok):
    jok = [s for s in sorok if ertekelheto(s)
           and s.get("also") is not None and s.get("felso") is not None]
    parok = Counter((s["also"] - s["tervezett"], s["felso"] - s["tervezett"]) for s in jok)
    return {"idokeretek": [[a, b, db] for (a, b), db in sorted(parok.items())],
            "tu_osszevetheto": sum(s.get("tu_egyezes") is not None for s in jok),
            "tu_eltero": sum(s.get("tu_egyezes") is False for s in jok)}


def tavolsag(a, b):
    # Rövid, megállók körüli távolság, méterben.
    if any(p.get(k) is None for p in (a, b) for k in ("lat", "lon")):
        return None
    dy = (b["lat"] - a["lat"]) * 111_200
    dx = (b["lon"] - a["lon"]) * 111_200 * math.cos(math.radians(a["lat"]))
    return math.hypot(dx, dy)


def kozles_ideje(sor):
    # A státusz saját idő nélkül is fontos, de indulást nem igazolhat.
    return sor["adat_ido"] if sor.get("adat_ido") is not None else sor["feed_ido"]


def kozlesek_ritkitasa(sorok):
    # Egy változatlan közlés sokszori letöltése nem sok külön bizonyíték.
    # Törlésnél a teljes válaszcsoport és az első megjelenés ideje is számít.
    # Ezeket az utakat nem ritkítjuk, így a visszaállítás sem válhat látszólagossá.
    if any(s.get("menet_allapot") == 3 for s in sorok):
        return sorted(sorok, key=kozles_sorrend)
    egyedi = {}
    for sor in sorok:
        # Azonos saját időhöz tartozó eltérő tartalmat is megtartunk.
        kulcs = tuple((k, v) for k, v in sorted(sor.items()) if k != "feed_ido")
        if sor.get("adat_ido") is None:
            kulcs += (("feed_ido", sor["feed_ido"]),)
        if kulcs not in egyedi or sor["feed_ido"] >= egyedi[kulcs]["feed_ido"]:
            egyedi[kulcs] = sor
    csoportok = defaultdict(list)
    for sor in sorted(egyedi.values(), key=lambda s: (kozles_ideje(s), s["feed_ido"])):
        csoportok[sor["sorrend"]].append(sor)
    eredmeny = []
    for csoport in csoportok.values():
        elozo = None
        szakasz = []
        for sor in csoport:
            alairas = tuple((k, v) for k, v in sorted(sor.items())
                            if k not in ("adat_ido", "feed_ido"))
            alairas += (("multbeli", sor.get("adat_ido") is not None and sor.get("indulas") is not None
                         and sor["indulas"] <= sor["adat_ido"]),)
            if alairas != elozo:
                eredmeny.extend(szakasz)
                szakasz = []
            szakasz.append(sor)
            if len(szakasz) > 3:
                szakasz.pop(1)
            elozo = alairas
        eredmeny.extend(szakasz)
    return eredmeny


def idokeret(poziciok, megallo, kovetkezo, indulas, jarmu, elozo_megallo=None):
    # Csak az indulás körüli látogatást nézzük, nem az egész menet min/max idejét.
    pontok = [p for p in poziciok if p.get("jarmu_id") == jarmu
              and p.get("adat_ido") is not None and p.get("sorrend") is not None
              and p.get("menet_allapot", 0) == 0
              and abs(p["adat_ido"] - indulas) <= 120]
    pontok.sort(key=lambda p: p["adat_ido"])
    for a, b in pairwise(pontok):
        if a["adat_ido"] == b["adat_ido"] and any(a.get(k) != b.get(k) for k in (
                "sorrend", "megallo_id", "allapot", "lat", "lon")):
            return None, None, False
    sorrend = megallo["sorrend"]
    elotte = [p for p in pontok if p["adat_ido"] <= indulas and p["sorrend"] <= sorrend]
    if not elotte:
        return None, None, False
    elso = elotte[-1]
    # A már továbbhaladt jármű visszaugró sorszáma nem új megállólátogatás.
    if (elso["sorrend"] == sorrend and (tavolsag(megallo, elso) or 0) > 100
            and any(p["adat_ido"] < elso["adat_ido"] and p["sorrend"] > sorrend
                    and (tavolsag(megallo, p) or 0) >= 40 for p in pontok)):
        return None, None, False
    # Az első továbbhaladás számít, akkor is, ha korábbi a TU-ban közölt időnél.
    utana = [p for p in pontok if p["adat_ido"] > elso["adat_ido"] and p["sorrend"] > sorrend]
    # A sorszám néha már az álló járműnél előreugrik.
    utana = [p for p in utana if tavolsag(megallo, p) is None or tavolsag(megallo, p) >= 40]
    if not utana:
        return None, None, False
    utolso = utana[0]
    if utolso["adat_ido"] < indulas:
        return None, None, False
    if elso["sorrend"] == sorrend and elso.get("megallo_id") != megallo["megallo_id"]:
        return None, None, False
    # Ha a koordináta az ellenkező irányba mutat, a sorszám önmagában kevés.
    if elozo_megallo and kovetkezo and all(p.get(k) is not None for p in (elozo_megallo, megallo, kovetkezo, utolso)
                        for k in ("lat", "lon")):
        skala = math.cos(math.radians(megallo["lat"])) ** 2
        irany = ((utana[0]["lat"] - megallo["lat"]) * (kovetkezo["lat"] - megallo["lat"])
                 + (utana[0]["lon"] - megallo["lon"]) * (kovetkezo["lon"] - megallo["lon"]) * skala)
        if irany < 0 and tavolsag(utolso, elozo_megallo) < tavolsag(megallo, elozo_megallo):
            return None, None, False
    allasok = [p for p in elotte if p["sorrend"] == sorrend
               and p.get("megallo_id") == megallo["megallo_id"] and p.get("allapot") == 1
               and (tavolsag(megallo, p) is None or tavolsag(megallo, p) <= 100)]
    # Egy régebbi látogatást nem kötünk össze egy későbbi elhaladással.
    if allasok and not any(p["sorrend"] > sorrend for p in pontok
                          if allasok[-1]["adat_ido"] < p["adat_ido"] < elso["adat_ido"]) and utolso["adat_ido"] - allasok[-1]["adat_ido"] <= 120:
        return allasok[-1]["adat_ido"], utolso["adat_ido"], True
    return None, None, True


def indulasok(menet):
    """Korábbi, közlésből kiinduló eljárás. Csak összehasonlító kontroll."""
    megallok = sorted(menet["megallok"], key=lambda s: s["sorrend"])
    kozlesek = kozlesek_ritkitasa(menet["kozlesek"])
    # Saját idő nélküli pozíció a menet jelenlétét jelzi, az indulásét nem.
    poziciok = [p for p in menet["poziciok"] if p.get("adat_ido") is not None]
    vp_jarmuvek = {s["jarmu_id"] for s in menet["poziciok"] if s.get("jarmu_id")}
    tu_jarmuvek = {s["jarmu_id"] for s in menet["kozlesek"] if s.get("jarmu_id")}
    # A TU járműazonosítója hiányozhat. Csak egyetlen, saját idejű VP-vel
    # megfigyelt jármű pótolhatja, és az idő nélküli ellentmondás is kizárja.
    menet_jarmu = next(iter(vp_jarmuvek)) if (
        len(vp_jarmuvek) == 1 and tu_jarmuvek <= vp_jarmuvek
        and any(s.get("jarmu_id") in vp_jarmuvek for s in poziciok)) else None
    stop_sorok = defaultdict(list)
    for sor in kozlesek:
        stop_sorok[sor["sorrend"]].append(sor)
    utolso = max(kozlesek, key=lambda s: (kozles_ideje(s), s["feed_ido"]), default={})
    torles = None
    indulasi_poziciok = poziciok
    if utolso.get("menet_allapot") == 3:
        # Egy későbbi törlés előtt a jármű már elindulhatott néhány megállóból.
        torles = min(kozles_ideje(s) for s in kozlesek if s.get("menet_allapot") == 3)
        indulasi_poziciok = [p for p in poziciok if p.get("adat_ido") is not None and p["adat_ido"] <= torles]
    eredmeny = []
    for hely, megallo in enumerate(megallok[:-1]):
        if megallo.get("felszallas", 0) != 0 or megallo.get("tervezett") is None:
            continue
        sor = {k: menet[k] for k in ("menet_id", "szolgalati_nap", "vonal_id", "irany")}
        sor.update(megallo)
        sor["kovetkezo_sorrend"] = megallok[hely + 1]["sorrend"]
        # A közös buszos példába csak az Örsig eljutó menet kerülhet.
        sor["ors_fele"] = any(s["megallo_id"] == "008029" and s.get("kiszallas") == 0
                              for s in megallok[hely + 1:])
        sor.update(indulas=None, erkezes=None, keses_mp=None, also=None, felso=None,
                   minoseg="bizonytalan", ok=[], menetrend_ok=True, jarmu_id=None, jelolt=None)
        sor["megalloban_idok"] = sorted({p["adat_ido"] for p in poziciok
                                        if p.get("adat_ido") is not None and p.get("allapot") == 1
                                        and p.get("sorrend") == megallo["sorrend"]
                                        and p.get("megallo_id") == megallo["megallo_id"]})
        eredmeny.append(sor)
        frissitesek = sorted(stop_sorok[megallo["sorrend"]], key=lambda s: (kozles_ideje(s), s["feed_ido"]))
        if torles is not None:
            frissitesek = [s for s in frissitesek if kozles_ideje(s) <= torles]
        if not frissitesek:
            sor.update(minoseg="nem_lattuk" if not kozlesek and not poziciok else "bizonytalan")
            sor["ok"].append("Nincs megállói időpont.")
            continue
        vegso = frissitesek[-1]
        sor["jelolt"] = vegso.get("indulas")
        if vegso.get("allapot", 0) != 0 or utolso.get("menet_allapot", 0) not in (0, 3):
            sor.update(minoseg="kihagyott" if vegso.get("allapot") == 1 else "bizonytalan",
                       menetrend_ok=False)
            sor["ok"].append("A forrás nem szokásos megállást jelez.")
            continue
        multbeli = [s for s in frissitesek if s.get("adat_ido") is not None and s.get("indulas") is not None
                    and s["indulas"] <= s["adat_ido"] and s.get("bizonytalansag") == 0
                    and s.get("allapot", 0) == 0 and s.get("menet_allapot", 0) == 0]
        if len(multbeli) < 2:
            sor["ok"].append("Nincs két külön idejű, múltbeli megerősítés.")
            continue
        elozo, utolso_jo = multbeli[-2:]
        indul = utolso_jo["indulas"]
        sor["jelolt"] = indul
        if elozo["indulas"] != indul:
            sor["ok"].append("Az utolsó múltbeli időpont még változott.")
            continue
        jarmu = utolso_jo.get("jarmu_id") or menet_jarmu
        if (not jarmu or (elozo.get("jarmu_id") or menet_jarmu) != jarmu
                or (vegso.get("jarmu_id") or menet_jarmu) != jarmu
                or any(s.get("megallo_id") != megallo["megallo_id"] for s in (elozo, utolso_jo))):
            sor["ok"].append("Nem egyezik a jármű vagy a megálló.")
            continue
        also, felso, haladt = idokeret(indulasi_poziciok, megallo, megallok[hely + 1], indul, jarmu,
                                      megallok[hely - 1] if hely else None)
        kesobbi_becsles = (vegso.get("bizonytalansag") != 0 or vegso.get("indulas") != indul)
        if not haladt or (kesobbi_becsles and also is None):
            sor["ok"].append("A közölt időt a közeli mozgás nem támasztja alá eléggé.")
            continue
        sor.update(indulas=indul, keses_mp=indul - sor["tervezett"], jarmu_id=jarmu,
                   also=also, felso=felso, minoseg="alatamasztott" if also is not None else "kovetett")
        if any(not s.get("jarmu_id") for s in (elozo, utolso_jo, vegso)):
            sor["jarmu_menetbol"] = True
        if (utolso_jo.get("erkezes_bizonytalansag") == 0
                and elozo.get("erkezes_bizonytalansag") == 0
                and utolso_jo.get("erkezes") == elozo.get("erkezes")
                and utolso_jo.get("erkezes") is not None and utolso_jo["erkezes"] <= indul):
            sor["erkezes"] = utolso_jo["erkezes"]
        if kesobbi_becsles:
            sor["ok"].append("A későbbi becslés helyett a mozgással egyező korábbi idő maradt.")
        if sor["keses_mp"] < -300 or sor["keses_mp"] > 3600:
            sor["menetrend_ok"] = False
            sor["ok"].append("Nagy eltérés: a menetrendi hozzárendelés külön ellenőrzést igényel.")
    if torles is not None:
        for s in eredmeny:
            if s["indulas"] is not None and s["also"] is not None and s["felso"] <= torles:
                s["kesobbi_torles"] = True
                s["ok"].append("A menetet később törölték; ezt a korábbi indulást mozgás is közrefogja.")
            else:
                s.update(minoseg="torolt", menetrend_ok=False, indulas=None, keses_mp=None, erkezes=None)
    # Egy meneten belül az indulásoknak a megállósorrendet is követniük kell.
    jok = [s for s in eredmeny if s["indulas"] is not None]
    for a, b in [(a, b) for a, b in pairwise(jok) if a["indulas"] > b["indulas"]]:
        for s in (a, b):
            s.update(minoseg="bizonytalan", menetrend_ok=False, indulas=None, keses_mp=None)
            s["ok"].append("Az időrend nem egyezik a megállósorrenddel.")
    return eredmeny


def ismetlesek(esemenyek):
    csoportok = defaultdict(list)
    for s in esemenyek:
        if s["indulas"] is not None:
            csoportok[(s["jarmu_id"], s["megallo_id"])].append(s)
    for sorok in csoportok.values():
        sorok.sort(key=lambda s: s["indulas"])
        parok = [(a, b) for a, b in pairwise(sorok)
                 if (a["menet_id"], a["szolgalati_nap"]) != (b["menet_id"], b["szolgalati_nap"])
                 and b["indulas"] - a["indulas"] <= 120]
        for par in parok:
            for s in par:
                s.update(minoseg="bizonytalan", indulas=None, keses_mp=None,
                         keses_bkk_terv_mp=None, menetrend_ok=False)
                s["ok"].append("Ugyanaz a jármű két közeli indulásként szerepel.")


def varakozas(idopontok, kezdet, veg):
    """Egyenletesen érkező utas várakozása, ugyanazon időablakban."""
    idok = sorted(idopontok)
    if kezdet >= veg or len(idok) < 2 or idok[0] > kezdet or idok[-1] < veg:
        raise ValueError("Az időablak előtt és után is kell indulás.")
    terulet = 0
    kovetesek = []
    for a, b in pairwise(idok):
        if a == b and kezdet <= a < veg:
            kovetesek.append(0)  # Két jármű egyszerre: nincs új várás, de van torlódás.
            continue
        bal, jobb = max(a, kezdet), min(b, veg)
        if jobb <= bal:
            continue
        terulet += ((b - bal) ** 2 - (b - jobb) ** 2) / 2
        kovetesek.append(b - a)
    return {"varakozas_mp": terulet / (veg - kezdet), "kovetesek_mp": kovetesek,
            "indulasok": sum(kezdet <= t < veg for t in idopontok)}


def p90(ertekek):
    # Két szomszédos rendezett érték közé is eshet a 90. percentilis.
    sor = sorted(ertekek)
    hely = (len(sor) - 1) * 0.9
    bal, jobb = math.floor(hely), math.ceil(hely)
    return sor[bal] + (sor[jobb] - sor[bal]) * (hely - bal)


def eloszlas(ertekek):
    # A pontos másodpercek darabszámai összeadhatók több napra is.
    return [[ertek, darab] for ertek, darab in sorted(Counter(ertekek).items())]


def kovetes(esemenyek, kezdet, veg, szegely=900, kizarasok=()):
    # Egy megállóhelyet és irányt kell átadni; az órán túli indulásokkal együtt.
    if len({(s["megallo_id"], s["irany"]) for s in esemenyek}) != 1:
        raise ValueError("A követés egy megállóhelyre és irányra számolható.")
    if any(s["also"] <= veg + szegely and s["felso"] >= kezdet - szegely for s in kizarasok):
        return {"hasznalhato": False, "indok": "Menetrenden kívüli vagy pótló menetet is láttunk a vonalon."}
    sorok = sorted(esemenyek, key=lambda s: s["tervezett"])
    blokkok, blokk = [], []
    for s in sorok:
        if (s.get("indulas") is not None and s.get("menetrend_ok", True)
                and s["minoseg"] in ("alatamasztott", "kovetett", "ajtojel", "hev_kozles")):
            blokk.append(s)
        else:
            if blokk:
                blokkok.append(blokk)
            blokk = []
    if blokk:
        blokkok.append(blokk)
    for blokk in blokkok:
        idok = sorted(s["indulas"] for s in blokk)
        if not (blokk[0]["tervezett"] <= kezdet - szegely
                and blokk[-1]["tervezett"] >= veg + szegely and idok[0] <= kezdet and idok[-1] >= veg):
            continue
        bal = max(t for t in idok if t <= kezdet)
        jobb = min(t for t in idok if t >= veg)
        belogo = [s for s in sorok if s not in blokk and (
            any(s.get(k) is not None and bal <= s[k] <= jobb for k in ("indulas", "jelolt"))
            or any(bal <= t <= jobb for t in s.get("megalloban_idok", [])))]
        if belogo:
            continue
        tenyleges = varakozas(idok, kezdet, veg)
        terv = varakozas([s["tervezett"] for s in blokk], kezdet, veg)
        return {"hasznalhato": True, **tenyleges,
                "tervezett_varakozas_mp": terv["varakozas_mp"],
                "median_kovetes_mp": median(tenyleges["kovetesek_mp"]),
                "p90_kovetes_mp": p90(tenyleges["kovetesek_mp"]),
                "max_kovetes_mp": max(tenyleges["kovetesek_mp"]),
                "tobblet_mp": tenyleges["varakozas_mp"] - terv["varakozas_mp"]}
    return {"hasznalhato": False, "indok": "Nincs teljes, követhető indulássorozat az időablak körül."}


def kovetesi_parok(esemenyek, kezdet, veg, kizarasok=()):
    """A bizonytalan rés körül a többi követhető szakaszt megtartjuk."""
    if kezdet >= veg:
        raise ValueError("Az időablak vége legyen későbbi a kezdeténél.")
    if len({(s["megallo_id"], s["irany"]) for s in esemenyek}) > 1:
        raise ValueError("A követés egy megállóhelyre és irányra számolható.")
    sorok, blokk = [], 0
    for s in sorted(esemenyek, key=lambda s: s["tervezett"]):
        jo = (s.get("indulas") is not None and s.get("menetrend_ok", True)
              and s["minoseg"] in ("alatamasztott", "kovetett", "ajtojel", "hev_kozles"))
        sorok.append((s, blokk if jo else None))
        if not jo:
            blokk += 1
    tenyleges = sorted([(s, b) for s, b in sorok if b is not None], key=lambda p: p[0]["indulas"])
    terv = [s["tervezett"] for s, _ in sorok]
    parok = []
    for (a, elso_blokk), (b, masodik_blokk) in pairwise(tenyleges):
        bal, jobb = a["indulas"], b["indulas"]
        kezdes, vege = max(bal, kezdet), min(jobb, veg)
        if elso_blokk != masodik_blokk:
            continue
        if bal == jobb:
            if not kezdet <= bal < veg:
                continue
        elif kezdes >= vege:
            continue
        # A teljes követési köz számít, az órahatáron kívüli része is.
        if any(s["also"] <= jobb and s["felso"] >= bal for s in kizarasok):
            continue
        belogo = False
        for s, masik_blokk in sorok:
            if masik_blokk == elso_blokk:
                continue
            idok = [s[k] for k in ("indulas", "jelolt") if s.get(k) is not None]
            idok += s.get("megalloban_idok", [])
            # Bizonytalan indulásnál a köztes idő sem tiszta. Igazolt indulásnál
            # egy régi megállólátogatást nem kötünk hozzá a későbbi induláshoz.
            metsz = any(bal <= t <= jobb for t in idok)
            if masik_blokk is None and idok:
                metsz = min(idok) <= jobb and max(idok) >= bal
            if metsz:
                belogo = True
                break
        if belogo or terv[0] > kezdes or terv[-1] < vege:
            continue
        parok.append({"elso": bal, "masodik": jobb,
                      "alatamasztott": all(s["minoseg"] == "alatamasztott"
                                           or s.get("modszer") in (MODSZER, HEV_MODSZER) for s in (a, b))})
    return parok


def reszidos_varakozas(parok, tervezett, kezdet, veg):
    """Ugyanazon rövid időszakokon számolunk, időtartammal súlyozva."""
    if kezdet >= veg:
        raise ValueError("Az időablak vége legyen későbbi a kezdeténél.")
    lefedett, terulet, terv_terulet, alatamasztott, reszletek = 0, 0, 0, 0, 0
    kovetesek = []
    for p in parok:
        if p["elso"] == p["masodik"] and kezdet <= p["elso"] < veg:
            kovetesek.append(0)
            alatamasztott += p["alatamasztott"]
            continue
        bal, jobb = max(p["elso"], kezdet), min(p["masodik"], veg)
        if bal >= jobb:
            continue
        reszletek += 1
        ido = jobb - bal
        terv = varakozas(tervezett, bal, jobb)
        terulet += ((p["masodik"] - bal) ** 2 - (p["masodik"] - jobb) ** 2) / 2
        terv_terulet += terv["varakozas_mp"] * ido
        lefedett += ido
        alatamasztott += p["alatamasztott"]
        kovetesek.append(p["masodik"] - p["elso"])
    varas = terulet / lefedett if lefedett else None
    terv_varas = terv_terulet / lefedett if lefedett else None
    return {"hasznalhato": bool(lefedett), "parok": len(kovetesek), "par_reszletek": reszletek,
            "nulla_kovetes": kovetesek.count(0),
            "alatamasztott_parok": alatamasztott,
            "lefedett_mp": lefedett, "kimaradt_mp": veg - kezdet - lefedett,
            "lefedettseg": lefedett / (veg - kezdet),
            "varakozas_mp": varas, "tervezett_varakozas_mp": terv_varas,
            "tobblet_mp": varas - terv_varas if lefedett else None,
            "median_kovetes_mp": median(kovetesek) if kovetesek else None,
            "p90_kovetes_mp": p90(kovetesek) if kovetesek else None,
            "max_kovetes_mp": max(kovetesek) if kovetesek else None}


def menetrendi_sorok(conn, nap, vonalak, menetrend_id, menet_azonositok=None):
    sorok = conn.execute("""
        SELECT m.menet_id, m.vonal_id, m.irany, d.nap::text szolgalati_nap,
               s.sorrend, s.megallo_id, s.erkezes_mp, s.indulas_mp,
               coalesce(s.felszallas,0) felszallas, coalesce(s.kiszallas,0) kiszallas, g.lat, g.lon
        FROM menet m CROSS JOIN LATERAL unnest(m.napok) d(nap)
        JOIN megallasi_ido s USING (menetrend_id,menet_id)
        JOIN megallo g USING (menetrend_id,megallo_id)
        WHERE m.menetrend_id=%s AND m.vonal_id=ANY(%s) AND d.nap BETWEEN %s AND %s
          AND (%s::text[] IS NULL OR m.menet_id=ANY(%s))
        ORDER BY m.vonal_id,m.menet_id,d.nap,s.sorrend
        """, (menetrend_id, vonalak, nap - timedelta(days=1), nap + timedelta(days=1),
              menet_azonositok, menet_azonositok)).fetchall()
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest"))
    veg = kezdet + timedelta(days=1)
    idok = defaultdict(list)
    for s in sorok:
        if s["indulas_mp"] is not None:
            idok[(s["menet_id"], s["szolgalati_nap"])].append(
                menetrendi_ido(date.fromisoformat(s["szolgalati_nap"]), s["indulas_mp"]).timestamp())
    erintett = {k for k, v in idok.items() if max(v) >= kezdet.timestamp() - 7200
                and min(v) <= veg.timestamp() + 7200}
    return [s for s in sorok if (s["menet_id"], s["szolgalati_nap"]) in erintett]


def minta_kornyezete(conn, nap, vonalak, menetrend_id):
    # A napi fájlokhoz tartozó menetrendeket összevetjük, mielőtt késést számolunk.
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest"))
    veg = kezdet + timedelta(days=1)
    forrasok = conn.execute("""
        SELECT DISTINCT n.jelolt_menetrend sha,n.menetrend_verzio verzio
        FROM nyers_fajl n WHERE n.feed_ido>=%s AND n.feed_ido<%s
            AND n.forras IN ('VehiclePositions','TripUpdates')
        UNION
        SELECT DISTINCT l.ismert_menetrend_sha256,n.menetrend_verzio
        FROM lekeres l JOIN nyers_fajl n ON n.id=l.nyers_id
        WHERE l.kezdett>=%s AND l.kezdett<%s AND l.forras IN ('VehiclePositions','TripUpdates')
        """, (kezdet - timedelta(hours=4), veg + timedelta(hours=4)) * 2).fetchall()
    sha_ertekek = {s["sha"] for s in forrasok if s["sha"]}
    verziok = {s["verzio"] for s in forrasok if s["verzio"]}
    valtozatok = conn.execute("""
        SELECT id,sha256,menetrend_verzio,idozona FROM nyers_fajl
        WHERE (id=%s OR sha256=ANY(%s) OR menetrend_verzio=ANY(%s))
          AND forras='Menetrend' AND feldolgozva
        ORDER BY id
        """, (menetrend_id, sorted(sha_ertekek), sorted(verziok))).fetchall()
    if menetrend_id not in {s["id"] for s in valtozatok}:
        raise ValueError("Nincs ilyen menetrend az adatbázisban.")
    if sha_ertekek - {s["sha256"] for s in valtozatok} or verziok - {s["menetrend_verzio"] for s in valtozatok}:
        raise ValueError("Egy hivatkozott menetrendváltozat még nincs betöltve.")
    alap = menetrendi_sorok(conn, nap, vonalak, menetrend_id)
    if not alap:
        raise ValueError("A kiválasztott naphoz és vonalakhoz nincs menetrendi sor.")
    for s in valtozatok:
        if s["idozona"] != "Europe/Budapest":
            raise ValueError("Az elemző Budapest időzónájára készült.")
        if s["id"] != menetrend_id and menetrendi_sorok(conn, nap, vonalak, s["id"]) != alap:
            raise ValueError("Eltér a vizsgált menetrend a forrásadatok változatai között; külön ellenőrzés kell.")
    # A plusz járatot nem szabad észrevétlenül kihagyni a követési sorból.
    kizarasok = conn.execute("""
        WITH m AS MATERIALIZED (
            SELECT m.*,n.feed_ido
            FROM megfigyeles m JOIN nyers_fajl n ON n.id=m.nyers_id
            LEFT JOIN menet t ON t.menetrend_id=%s AND t.menet_id=m.menet_id
                AND m.szolgalati_nap=ANY(t.napok)
            WHERE n.feed_ido>=%s AND n.feed_ido<%s
              AND (m.vonal_id=ANY(%s) OR m.potolt_vonal_id=ANY(%s)
                   OR m.vonal_id='OPH8' AND 'H8'=ANY(%s)
                      AND m.szolgalati_nap BETWEEN DATE '2026-10-17' AND DATE '2026-11-06'
                   OR m.vonal_id IS NULL AND m.potolt_vonal_id IS NULL)
              AND (t.menet_id IS NULL OR coalesce(m.menet_allapot,0) NOT IN (0,3)
                   OR m.potlas_jelzes IS NOT NULL)
        )
        SELECT m.vonal_id,
               CASE WHEN m.vonal_id='OPH8'
                         AND m.szolgalati_nap BETWEEN DATE '2026-10-17' AND DATE '2026-11-06'
                    THEN 'H8' ELSE m.potolt_vonal_id END potolt_vonal_id,
               m.menet_id,m.szolgalati_nap::text,
               array_agg(DISTINCT m.megallo_id) megallok_vp,
               jsonb_agg(DISTINCT u.megallo_idk) megallok_tu,
               extract(epoch FROM min(least(coalesce(m.adat_ido,m.feed_ido),u.also)))::bigint also,
               extract(epoch FROM max(greatest(coalesce(m.adat_ido,m.feed_ido),u.felso)))::bigint felso
        FROM m LEFT JOIN LATERAL (
            SELECT min(least(s.erkezes,s.indulas)) also,max(greatest(s.erkezes,s.indulas)) felso,
                   array_agg(DISTINCT s.megallo_id) megallo_idk
            FROM megallo_frissites s WHERE s.nyers_id=m.nyers_id AND s.megfigyeles_sorrend=m.sorrend
        ) u ON true
        GROUP BY m.vonal_id,m.potolt_vonal_id,m.menet_id,m.szolgalati_nap
        ORDER BY m.vonal_id,m.menet_id,m.szolgalati_nap
        """, (menetrend_id, kezdet - timedelta(hours=4), veg + timedelta(hours=4),
              vonalak, vonalak, vonalak)).fetchall()
    for sor in kizarasok:
        helyek = set(sor.pop("megallok_vp") or [])
        for csoport in sor.pop("megallok_tu") or []:
            helyek.update(csoport or [])
        sor["megallo_idk"] = sorted(m for m in helyek if m is not None)
    nevek = conn.execute("SELECT megallo_id,nev FROM megallo WHERE menetrend_id=%s",
                         (menetrend_id,)).fetchall()
    return {"ellenorzott_menetrendek": [s["id"] for s in valtozatok], "kizarasok": kizarasok,
            "megallo_nevek": {s["megallo_id"]: s["nev"] for s in nevek}}


def potlasi_minta(conn, nap, vonalak):
    # A MÁV október 17. és november 6. közötti pótlásához ellenőrzött kapcsolat.
    # Az OPH8 busz marad, a vasúti menetrendből nem gyártunk neki indulásokat.
    if "H8" not in vonalak:
        return []
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest"))
    veg = kezdet + timedelta(days=1)
    return conn.execute("""
        SELECT m.vonal_id,'H8'::text potolt_vonal_id,m.szolgalati_nap::text,
               count(DISTINCT m.menet_id) menetek,
               count(DISTINCT m.jarmu_id) jarmuvek,
               count(*) FILTER (WHERE m.tipus='vehicle') poziciok,
               count(*) FILTER (WHERE m.tipus='trip_update') menetfrissitesek,
               extract(epoch FROM min(n.feed_ido))::bigint elso_feed_ido,
               extract(epoch FROM max(n.feed_ido))::bigint utolso_feed_ido,
               extract(epoch FROM min(m.adat_ido))::bigint elso_sajat_ido,
               extract(epoch FROM max(m.adat_ido))::bigint utolso_sajat_ido
        FROM megfigyeles m JOIN nyers_fajl n ON n.id=m.nyers_id
        WHERE m.vonal_id='OPH8'
          AND m.szolgalati_nap BETWEEN DATE '2026-10-17' AND DATE '2026-11-06'
          AND n.feed_ido>=%s AND n.feed_ido<%s
        GROUP BY m.vonal_id,m.szolgalati_nap
        ORDER BY m.szolgalati_nap
        """, (kezdet - timedelta(hours=4), veg + timedelta(hours=4))).fetchall()


def adatbazisbol(conn, nap, vonalak, menetrend_id, menet_azonositok=None):
    """Egy menetet olvasunk egyszerre; az adatbázisba nem írunk."""
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest"))
    veg = kezdet + timedelta(days=1)
    terv = menetrendi_sorok(conn, nap, vonalak, menetrend_id, menet_azonositok)
    menetek = {}
    for s in terv:
        kulcs = (s["menet_id"], s["szolgalati_nap"])
        menet = menetek.setdefault(kulcs, {k: s[k] for k in ("menet_id", "vonal_id", "irany", "szolgalati_nap")})
        megallo = {k: s[k] for k in ("sorrend", "megallo_id", "lat", "lon", "felszallas", "kiszallas")}
        for mezo, mp in (("tervezett", "indulas_mp"), ("tervezett_erkezes", "erkezes_mp")):
            megallo[mezo] = (int(menetrendi_ido(date.fromisoformat(s["szolgalati_nap"]), s[mp]).timestamp())
                            if s[mp] is not None else None)
        menet.setdefault("megallok", []).append(megallo)
    for menet in menetek.values():
        param = (menet["menet_id"], menet["szolgalati_nap"], kezdet - timedelta(hours=4), veg + timedelta(hours=4))
        menet["poziciok"] = conn.execute("""
            SELECT extract(epoch FROM m.adat_ido)::bigint adat_ido,
                   m.jarmu_id,m.megallo_sorrend sorrend,m.megallo_id,
                   coalesce(m.jarmu_allapot,2) allapot,coalesce(m.menet_allapot,0) menet_allapot,m.lat,m.lon,
                   m.sebesseg,m.ajto_nyitva,m.megallo_tavolsag,m.letert,
                   extract(epoch FROM min(n.feed_ido))::bigint feed_ido
            FROM megfigyeles m JOIN nyers_fajl n ON n.id=m.nyers_id
            WHERE m.menet_id=%s AND m.szolgalati_nap=%s AND n.feed_ido>=%s AND n.feed_ido<%s
              AND m.tipus='vehicle'
            GROUP BY m.adat_ido,m.jarmu_id,m.megallo_sorrend,m.megallo_id,
                     m.jarmu_allapot,m.menet_allapot,m.lat,m.lon,
                     m.sebesseg,m.ajto_nyitva,m.megallo_tavolsag,m.letert
            ORDER BY adat_ido
            """, param).fetchall()
        sorok = conn.execute("""
            WITH u AS (
                SELECT m.*,n.feed_ido
                FROM megfigyeles m JOIN nyers_fajl n ON n.id=m.nyers_id
                WHERE m.menet_id=%s AND m.szolgalati_nap=%s AND n.feed_ido>=%s AND n.feed_ido<%s
                  AND m.tipus='trip_update'
            )
            SELECT s.megallo_sorrend sorrend,s.megallo_id,u.jarmu_id,
                   extract(epoch FROM u.adat_ido)::bigint adat_ido,
                   extract(epoch FROM u.feed_ido)::bigint feed_ido,
                   extract(epoch FROM s.indulas)::bigint indulas,
                   extract(epoch FROM s.erkezes)::bigint erkezes,
                   extract(epoch FROM s.forras_tervezett_indulas)::bigint forras_tervezett_indulas,
                   extract(epoch FROM s.forras_tervezett_erkezes)::bigint forras_tervezett_erkezes,
                   s.indulas_bizonytalansag bizonytalansag,s.erkezes_bizonytalansag,
                   coalesce(s.allapot,0) allapot,coalesce(u.menet_allapot,0) menet_allapot
            FROM u LEFT JOIN megallo_frissites s ON s.nyers_id=u.nyers_id AND s.megfigyeles_sorrend=u.sorrend
            ORDER BY u.adat_ido,u.feed_ido
            """, param).fetchall()
        menet["menetrendi_kozlesek"] = menetrendi_kozlesek(sorok)
        menet["kozlesek"] = kozlesek_ritkitasa(sorok)
        yield menet


def keses_reszletek(esemenyek, nap):
    """Kis kiegészítés az órás ábrákhoz és a legnagyobb késés visszakereséséhez."""
    napi = [s for s in esemenyek if kezdet_napon(s["tervezett"], nap) and ertekelheto(s)]
    orak, iranyok = defaultdict(list), defaultdict(list)
    for sor in napi:
        ora = datetime.fromtimestamp(sor["tervezett"], ZoneInfo("Europe/Budapest")).hour
        orak[(sor["vonal_id"], sor["irany"], ora)].append(sor)
        iranyok[(sor["vonal_id"], sor["irany"])].append(sor)

    def legkesobbi(sorok):
        # Azonos maximum esetén az első menetrendi időpont adja a bemutatott példát.
        return min(sorok, key=lambda s: (-s["keses_mp"], s["tervezett"], s["menet_id"], s["sorrend"]))

    def pont(sor):
        return {k: sor[k] for k in ("menet_id", "szolgalati_nap", "vonal_id", "irany", "sorrend",
                                    "megallo_id", "tervezett", "indulas", "keses_mp")}

    oras = []
    for (vonal, irany, ora), sorok in sorted(orak.items()):
        maximum = legkesobbi(sorok)
        oras.append({"vonal_id": vonal, "irany": irany, "ora": ora,
                     "menet_db": len({(s["menet_id"], s["szolgalati_nap"]) for s in sorok}),
                     "maximum": pont(maximum),
                     "maximum_db": sum(s["keses_mp"] == maximum["keses_mp"] for s in sorok)})
    peldak = []
    for (vonal, irany), sorok in sorted(iranyok.items()):
        maximum = legkesobbi(sorok)
        if maximum["keses_mp"] <= 0:
            continue
        kulcs = (maximum["menet_id"], maximum["szolgalati_nap"], vonal, irany)
        ut = sorted((s for s in esemenyek if
                     (s["menet_id"], s["szolgalati_nap"], s["vonal_id"], s["irany"]) == kulcs),
                    key=lambda s: s["sorrend"])
        # A hiányzó vagy elutasított közlés lyuk marad a vonalban.
        megallok = [dict(pont(s), indulas=s["indulas"] if ertekelheto(s) else None,
                         keses_mp=s["keses_mp"] if ertekelheto(s) else None) for s in ut]
        peldak.append({"vonal_id": vonal, "irany": irany, "maximum": pont(maximum), "megallok": megallok})
    return {"orankent": oras, "szelso_utak": peldak}


def osszegzes(esemenyek, nap):
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest"))
    veg = kezdet + timedelta(days=1)
    napi = [s for s in esemenyek if kezdet.timestamp() <= s["tervezett"] < veg.timestamp()]
    vonalak = []
    for vonal in sorted({s["vonal_id"] for s in napi}):
        sorok = [s for s in napi if s["vonal_id"] == vonal]
        fizikai = [s for s in sorok if s["indulas"] is not None]
        jok = [s for s in sorok if ertekelheto(s)]
        koran_erkezett = [s for s in jok if s["erkezes"] is not None
                         and s.get("tervezett_erkezes") is not None
                         and (s["erkezes_felso"] if s.get("erkezes_felso") is not None else s["erkezes"]) < s["tervezett_erkezes"]]
        vonalak.append({"vonal_id": vonal, "tervezett": len(sorok), "minoseg": dict(Counter(s["minoseg"] for s in sorok)),
                        "tervezett_menetek": len({(s["menet_id"], s["szolgalati_nap"]) for s in sorok}),
                        "hasznalt_menetek": len({(s["menet_id"], s["szolgalati_nap"]) for s in jok}),
                        "lefedettseg": len(jok) / len(sorok),
                        "fizikai_indulas": len(fizikai), "ellenorizendo_menetrend": len(fizikai) - len(jok),
                        "median_minden_jelolttel_mp": median(s["keses_mp"] for s in fizikai) if fizikai else None,
                        "keseshez_hasznalt": len(jok), "median_keses_mp": median(s["keses_mp"] for s in jok) if jok else None,
                        "p90_keses_mp": p90([s["keses_mp"] for s in jok]) if jok else None,
                        "keses_eloszlas": eloszlas(s["keses_mp"] for s in jok),
                        "korai_indulas": sum(s["keses_mp"] < 0 for s in jok),
                        "koran_erkezett": len(koran_erkezett),
                        "megvarta_indulast": sum((s["also"] if s.get("also") is not None else s["indulas"]) >= s["tervezett"]
                                                for s in koran_erkezett),
                        **terv_osszegzes(jok),
                        **intervallum_osszegzes(sorok)})
    orak, szakaszok = defaultdict(list), defaultdict(list)
    ora_tervek = defaultdict(Counter)
    tervezett_orak, tervezett_parok = Counter(), Counter()
    for s in napi:
        ora = datetime.fromtimestamp(s["tervezett"], ZoneInfo("Europe/Budapest")).hour
        tervezett_orak[(s["vonal_id"], s["irany"], ora)] += 1
        if ertekelheto(s):
            orak[(s["vonal_id"], s["irany"], ora)].append(s["keses_mp"])
            ora_tervek[(s["vonal_id"], s["irany"], ora)].update(terv_osszegzes([s]))
    menetek = defaultdict(list)
    for s in esemenyek:
        menetek[(s["menet_id"], s["szolgalati_nap"])].append(s)
    for megallasok in menetek.values():
        megallasok.sort(key=lambda s: s["sorrend"])
        for a, b in pairwise(megallasok):
            if (b["sorrend"] == a["kovetkezo_sorrend"]
                    and kezdet.timestamp() <= b["tervezett"] < veg.timestamp()):
                tervezett_parok[(a["vonal_id"], a["irany"], a["megallo_id"], b["megallo_id"])] += 1
            if (b["sorrend"] == a["kovetkezo_sorrend"]
                    and a["indulas"] is not None and b["indulas"] is not None
                    and a["menetrend_ok"] and b["menetrend_ok"]
                    and a["jarmu_id"] == b["jarmu_id"]
                    and kezdet.timestamp() <= b["tervezett"] < veg.timestamp()):
                szakaszok[(a["vonal_id"], a["irany"], a["megallo_id"], b["megallo_id"])].append(b["keses_mp"] - a["keses_mp"])
    return {"nap": str(nap), "vonalak": vonalak,
            "orankent": [{"vonal_id": k[0], "irany": k[1], "ora": k[2], "n": len(v),
                          "tervezett": tervezett_orak[k], "lefedettseg": len(v) / tervezett_orak[k],
                          "median_keses_mp": median(v) if v else None, "korai_indulas": sum(t < 0 for t in v),
                          **dict(ora_tervek[k]),
                          "keses_eloszlas": eloszlas(v)}
                         for k in sorted(tervezett_orak) for v in [orak[k]]],
            "szakaszok": [{"vonal_id": k[0], "irany": k[1], "honnan": k[2], "hova": k[3],
                           "tervezett_parok": tervezett_parok[k], "lefedettseg": len(v) / tervezett_parok[k],
                           "n": len(v), "median_valtozas_mp": median(v) if v else None,
                           "valtozas_eloszlas": eloszlas(v)}
                          for k in sorted(tervezett_parok) for v in [szakaszok[k]]]}


def kovetesi_csoportok(esemenyek, kizarasok):
    # Az első példák ugyanazon peronról, azonos cél felé indulnak.
    csoportok = [("Nyugati, Újbuda felé", "F00935", {"3046"}, None),
                 ("Nyugati, Széll Kálmán tér felé", "F00933", {"3046"}, None),
                 ("Bakancsos utca, Örs felé együtt", "F03541", {"0975", "1610", "1695"}, None),
                 ("Bakancsos utca, 97E", "F03541", {"0975"}, None),
                 ("Bakancsos utca, 161", "F03541", {"1610"}, None),
                 ("Bakancsos utca, 169E", "F03541", {"1695"}, None)]
    szerepel = {m for _, m, v, _ in csoportok if v == {"3046"}}
    csoportok += [("4–6, " + m, m, {"3046"}, None) for m in sorted({
        s["megallo_id"] for s in esemenyek if s["vonal_id"] == "3046"} - szerepel)]
    csoportok += [(v + ", " + m, m, {v}, irany) for v, m, irany in sorted({
        (s["vonal_id"], s["megallo_id"], s["irany"]) for s in esemenyek if hev_vonal(s["vonal_id"])}, key=str)]
    for nev, megallo, vonalak, irany in csoportok:
        sorok = [s for s in esemenyek if s["megallo_id"] == megallo and s["vonal_id"] in vonalak
                 and (irany is None or s["irany"] == irany)]
        if megallo == "F03541":
            sorok = [s for s in sorok if s.get("ors_fele")]
        if {s["vonal_id"] for s in sorok} != vonalak:
            continue
        tiltott = [s for s in kizarasok if s["vonal_id"] in vonalak or s.get("potolt_vonal_id") in vonalak
                   or s["vonal_id"] is None and s.get("potolt_vonal_id") is None
                   and ("megallo_idk" not in s or megallo in s["megallo_idk"])]
        iranyok = sorted({(s["vonal_id"], s["irany"]) for s in sorok}, key=str)
        yield {"hely": nev, "megallo_id": megallo, "vonalak": sorted(vonalak),
               "iranyok": [{"vonal_id": vonal, "irany": irany} for vonal, irany in iranyok]}, sorok, tiltott


def kovetesi_orak(esemenyek, nap, kizarasok=()):
    # A korábbi, teljes órás feltétel szigorú összehasonlításnak megmarad.
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest"))
    veg = (kezdet + timedelta(days=1)).timestamp()
    eredmeny = []
    for hely, sorok, tiltott in kovetesi_csoportok(esemenyek, kizarasok):
        ido = kezdet.timestamp()
        while ido < veg:
            helyi = datetime.fromtimestamp(ido, ZoneInfo("Europe/Budapest"))
            eredmeny.append({**hely, "ora": helyi.hour, "kezdet": helyi.isoformat(),
                            **kovetes(sorok, ido, ido + 3600, kizarasok=tiltott)})
            ido += 3600
    return eredmeny


def kovetesi_reszek(esemenyek, nap, kizarasok=()):
    zona = ZoneInfo("Europe/Budapest")
    kezdet = datetime.combine(nap, datetime.min.time(), zona)
    veg = kezdet + timedelta(days=1)
    eleje, vege = kezdet.timestamp(), veg.timestamp()
    eredmeny = {"naponta": [], "orankent": []}
    for hely, sorok, tiltott in kovetesi_csoportok(esemenyek, kizarasok):
        parok = kovetesi_parok(sorok, eleje, vege, tiltott)
        terv = [s["tervezett"] for s in sorok]
        eredmeny["naponta"].append({**hely, "kezdet": kezdet.isoformat(), "veg": veg.isoformat(),
                                    **reszidos_varakozas(parok, terv, eleje, vege)})
        ido = eleje
        # Valós órákkal lépünk: az óraátállítás napja 23 vagy 25 órás lehet.
        while ido < vege:
            helyi = datetime.fromtimestamp(ido, zona)
            eredmeny["orankent"].append({**hely, "ora": helyi.hour, "kezdet": helyi.isoformat(),
                                        "veg": datetime.fromtimestamp(ido + 3600, zona).isoformat(),
                                        **reszidos_varakozas(parok, terv, ido, ido + 3600)})
            ido += 3600
    return eredmeny


def kozos_buszok(orak):
    # Csak ugyanazt az órát hasonlítjuk, ha mindhárom külön vonal is követhető.
    egyutt = [s for s in orak if s["megallo_id"] == "F03541" and len(s["vonalak"]) == 3]
    eredmeny = []
    for sor in egyutt:
        kulon = [s for s in orak if s["megallo_id"] == "F03541" and len(s["vonalak"]) == 1
                 and s["kezdet"] == sor["kezdet"] and s["hasznalhato"]]
        if sor["hasznalhato"] and len(kulon) == 3:
            eredmeny.append({"kezdet": sor["kezdet"], "indulasok": sor["indulasok"],
                            "egyutt_mp": sor["varakozas_mp"],
                            "kulon_mp": {s["vonalak"][0]: s["varakozas_mp"] for s in kulon}})
    return eredmeny


def utazasi_sorok(menetek, honnan, hova):
    """Ugyanazon jármű felszállási és leszállási megállóját kapcsolja össze."""
    eredmeny = []
    for megallok in menetek:
        for a in megallok:
            if a["megallo_id"] != honnan or a.get("felszallas", 0) != 0:
                continue
            celok = [b for b in megallok if b["megallo_id"] == hova
                     and b["sorrend"] > a["sorrend"] and b.get("kiszallas", 0) == 0]
            if len(celok) != 1:
                continue
            b = celok[0]
            jo = (a["indulas"] is not None and b["erkezes"] is not None
                  and a["menetrend_ok"] and b["menetrend_ok"] and a["jarmu_id"] == b["jarmu_id"]
                  and b["erkezes_also"] >= a["felso"])
            eredmeny.append(dict(a, cel_erkezes=b["erkezes"] if jo else None,
                                  cel_also=b["erkezes_also"] if jo else None,
                                  cel_felso=b["erkezes_felso"] if jo else None,
                                  cel_tervezett=b.get("tervezett_erkezes")))
    return eredmeny


def buszos_valasztas(sorok, kezdet, veg, kizarasok):
    """Előre rögzített szabályok ugyanazon, hiány nélkül követhető időszakokon."""
    vonalak = sorted({s["vonal_id"] for s in sorok})
    if len(vonalak) < 2:
        return None
    ablakok = {}
    for v in vonalak:
        resz = [s for s in sorok if s["vonal_id"] == v]
        tiltott = [s for s in kizarasok if s.get("vonal_id") == v or s.get("potolt_vonal_id") == v
                   or s.get("vonal_id") is None and s.get("potolt_vonal_id") is None
                   and ("megallo_idk" not in s or resz[0]["megallo_id"] in s["megallo_idk"])]
        parok = kovetesi_parok(resz, kezdet, veg, tiltott)
        idok = defaultdict(list)
        for s in resz:
            if s["indulas"] is not None:
                idok[s["indulas"]].append(s)
        ablakok[v] = []
        for p in parok:
            # Az azonos középidő nem azonosít egyértelműen egy buszt.
            if len(idok[p["elso"]]) != 1 or len(idok[p["masodik"]]) != 1:
                continue
            a, b = idok[p["elso"]][0], idok[p["masodik"]][0]
            if b["cel_erkezes"] is None or a["felso"] >= b["also"]:
                continue
            bal, jobb = max(kezdet, a["felso"]), min(veg, b["also"])
            if bal < jobb:
                ablakok[v].append((bal, jobb, b))
    hatarok = sorted({t for ablak in ablakok.values() for a, b, _ in ablak for t in (a, b)})
    mutatok = dict.fromkeys(vonalak, 0)
    osszeg = defaultdict(Counter)
    hasznalt = defaultdict(set)
    ido = kesobb_jobb = 0
    bizonytalan_sorrend = 0
    for bal, jobb in pairwise(hatarok):
        kozep = (bal + jobb) / 2
        valaszthato = []
        for v in vonalak:
            ablak = ablakok[v]
            while mutatok[v] < len(ablak) and ablak[mutatok[v]][1] <= bal:
                mutatok[v] += 1
            if mutatok[v] < len(ablak):
                a, b, busz = ablak[mutatok[v]]
                if a <= bal and jobb <= b:
                    valaszthato.append(busz)
        if len(valaszthato) != len(vonalak):
            continue
        elso = min(valaszthato, key=lambda s: s["indulas"])
        if any(elso["felso"] >= s["also"] for s in valaszthato if s is not elso):
            bizonytalan_sorrend += jobb - bal
            continue
        hossz = jobb - bal
        ido += hossz
        kesobb_jobb += hossz * any(s["cel_felso"] < elso["cel_also"] for s in valaszthato if s is not elso)
        for valasztas, busz in [("elso", elso)] + [(s["vonal_id"], s) for s in valaszthato]:
            osszeg[valasztas]["varakozas"] += (busz["indulas"] - kozep) * hossz
            osszeg[valasztas]["menetido"] += (busz["cel_erkezes"] - busz["indulas"]) * hossz
            osszeg[valasztas]["teljes_also"] += (busz["cel_also"] - kozep) * hossz
            osszeg[valasztas]["teljes_felso"] += (busz["cel_felso"] - kozep) * hossz
            hasznalt[valasztas].add((busz["menet_id"], busz["szolgalati_nap"]))
    return {"vonalak": vonalak, "lefedett_mp": ido, "vizsgalt_mp": veg - kezdet,
            "bizonytalan_sorrend_mp": bizonytalan_sorrend,
            "kesobbi_gyorsabb_mp": kesobb_jobb,
            "valasztasok": [{"valasztas": v, "n": len(hasznalt[v]),
                             **{k + "_mp": ertek / ido for k, ertek in ertekek.items()}}
                            for v, ertekek in sorted(osszeg.items())] if ido else []}


def utazasi_eredmenyek(adatok, nap):
    menetek = [ellenorzott_indulasok(m, True) for m in adatok["menetek"]
               if m["vonal_id"] in ("0975", "1610", "1695")]
    # A teljes úthoz is kizárjuk a más menetekkel ütköző járműazonosítást.
    ismetlesek([s for m in menetek for s in m])
    zona = ZoneInfo("Europe/Budapest")
    kezdet = datetime.combine(nap, datetime.min.time(), zona) + timedelta(hours=6)
    veg = kezdet + timedelta(hours=16)
    buszok = [m for m in menetek if m]
    buszos = []
    for honnan in ("F03541", "F03594", "011725", "F03499"):
        for hova in ("008029", "F03546"):
            sorok = utazasi_sorok(buszok, honnan, hova)
            if len({s["vonal_id"] for s in sorok}) < 2:
                continue
            er = buszos_valasztas(sorok, kezdet.timestamp(), veg.timestamp(), adatok.get("kizarasok", []))
            if er:
                buszos.append({"honnan": honnan, "hova": hova, **er})
    # A HÉV közölt indulását nem keverjük a más időkezelésű helyzetből becsült érkezéssel.
    # Ott a követés és a két állomás indulásai közti különbség készül el külön.
    return {"busz": buszos, "hev": []}


def json_mentes(cel, adat):
    # A korábbi kész eredményt csak a teljes új fájl váltja fel.
    atmeneti = cel.with_name(cel.name + ".tmp")
    if cel.suffix == ".gz":
        with gzip.open(atmeneti, "wt", encoding="utf-8", compresslevel=1) as fajl:
            json.dump(adat, fajl, ensure_ascii=False)
    else:
        atmeneti.write_text(json.dumps(adat, ensure_ascii=False, indent=2), encoding="utf-8")
    atmeneti.replace(cel)


def napi_menetek(menetek, nap):
    """Csak aznap tervezett felszállási indulással rendelkező menetek."""
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest")).timestamp()
    veg = datetime.combine(nap + timedelta(days=1), datetime.min.time(), ZoneInfo("Europe/Budapest")).timestamp()
    for menet in menetek:
        megallok = sorted(menet["megallok"], key=lambda s: s["sorrend"])
        if any(s.get("felszallas", 0) == 0 and s.get("tervezett") is not None
               and kezdet <= s["tervezett"] < veg for s in megallok[:-1]):
            yield menet, megallok


def menet_lathatosag(menetek, nap):
    egyedi = {}
    for menet, _ in napi_menetek(menetek, nap):
        kulcs = (menet["vonal_id"], menet["menet_id"], menet["szolgalati_nap"])
        sor = egyedi.setdefault(kulcs, {"menet_id": menet["menet_id"], "szolgalati_nap": menet["szolgalati_nap"],
                                        "pozicio": False, "menetfrissites": False})
        # Régi mintához külön, nyers megfigyelésekből ellenőrzött jelenlét adható.
        jelenlet = menet.get("megfigyeles_jelenlet", {})
        sor["pozicio"] |= bool(menet["poziciok"]) or bool(jelenlet.get("pozicioval"))
        sor["menetfrissites"] |= bool(menet["kozlesek"]) or bool(jelenlet.get("menetfrissitessel"))
    vonalak = defaultdict(list)
    for (vonal, _, _), sor in sorted(egyedi.items()):
        vonalak[vonal].append(sor)
    return [{"vonal_id": vonal, "tervezett_menetek": len(sorok),
             "latott_menetek": sum(s["pozicio"] or s["menetfrissites"] for s in sorok),
             "nem_latott_menetek": sum(not s["pozicio"] and not s["menetfrissites"] for s in sorok),
             "pozicioval": sum(s["pozicio"] for s in sorok),
             "menetfrissitessel": sum(s["menetfrissites"] for s in sorok), "menetek": sorok}
            for vonal, sorok in vonalak.items()]


def utvonal_reszletek(menetek, nap):
    csoportok = defaultdict(set)
    for menet, megallok in napi_menetek(menetek, nap):
        kulcs = (menet["vonal_id"], menet["irany"], tuple(s["megallo_id"] for s in megallok))
        csoportok[kulcs].add((menet["menet_id"], menet["szolgalati_nap"]))
    return [{"vonal_id": v, "irany": i, "megallo_idk": list(megallok),
             "menetek": [{"menet_id": m, "szolgalati_nap": n} for m, n in sorted(azonositok)]}
            for (v, i, megallok), azonositok in sorted(csoportok.items(), key=lambda s: str(s[0]))]


def menetrendi_iranyok(menetek, nap):
    valtozatok = defaultdict(set)
    for menet, megallok in napi_menetek(menetek, nap):
        kulcs = (menet["vonal_id"], menet["irany"],
                 megallok[0]["megallo_id"], megallok[-1]["megallo_id"])
        valtozatok[kulcs].add((menet["menet_id"], menet["szolgalati_nap"]))
    iranyok = defaultdict(list)
    for (vonal, irany, elso, utolso), azonositok in sorted(valtozatok.items(), key=lambda s: str(s[0])):
        iranyok[(vonal, irany)].append({"elso_megallo_id": elso, "utolso_megallo_id": utolso,
                                      "tervezett_menetek": len(azonositok)})
    return [{"vonal_id": vonal, "irany": irany, "utvonalak": sorok}
            for (vonal, irany), sorok in iranyok.items()]


def feldolgozas(adatok, nap):
    # Ugyanaz a számítás fut a kézi és a napi exportnál.
    adatok = dict(adatok, menetek=[menetrendi_alap(m) for m in adatok["menetek"]])
    forrasok = {hev_vonal(m["vonal_id"]) for m in adatok["menetek"]}
    if len(forrasok) > 1:
        raise ValueError("A HÉV külön feldolgozást igényel.")
    hev = forrasok == {True}
    esemenyek = [s for menet in adatok["menetek"] for s in ellenorzott_indulasok(menet)]
    ismetlesek(esemenyek)
    eredmeny = osszegzes(esemenyek, nap)
    eredmeny["keses_reszletek"] = keses_reszletek(esemenyek, nap)
    eredmeny["modszer"] = HEV_MODSZER if hev else MODSZER
    eredmeny["ido_jelentese"] = "utolagos_kozles_mozgassal_ellenorizve"
    eredmeny["idokeret_jelentese"] = "mozgasos_ellenorzes_nem_pontossagi_hatar"
    eredmeny["hivatalos_pontossaggal_osszevetheto"] = False
    eredmeny["pontossagi_rangsor"] = not hev
    eredmeny["forras_csoport"] = "hev" if hev else "bkk"
    # Az előző, mozgásból becsült idő csak az átállás ellenőrzésére marad meg.
    regi = [s for menet in adatok["menetek"] for s in mozgasbol_indulasok(menet)]
    ismetlesek(regi)
    eredmeny["korabbi_modszer"] = osszegzes(regi, nap)["vonalak"]
    eredmeny["ellenorzes"] = {
        "menetrendi_alap": dict(Counter(s["terv_allapot"] for s in esemenyek
                                        if s["indulas"] is not None and kezdet_napon(s["tervezett"], nap))),
        "modositott_terv": sum(s["bkk_terv_ellenorzott"] and s["bkk_tervezett_indulas"] != s["tervezett"] for s in esemenyek
                              if s["indulas"] is not None and kezdet_napon(s["tervezett"], nap)),
        "utolagos_tervvaltas": sum(s["terv_kesobb_valtozott"] for s in esemenyek
                                  if s["indulas"] is not None and kezdet_napon(s["tervezett"], nap)),
        "legalabb_felora_elteres": sum(abs(s["keses_mp"]) >= 1800 for s in esemenyek
                                      if ertekelheto(s) and kezdet_napon(s["tervezett"], nap)),
        "elutasitasok": dict(Counter(s["elutasitas"] for s in esemenyek
                                     if s["elutasitas"] and kezdet_napon(s["tervezett"], nap))),
        "ajtovizsgalat": dict(Counter(s["ajto_ellenorzes"] for s in esemenyek
                                     if s["indulas"] is not None and kezdet_napon(s["tervezett"], nap))),
        "megallasjel_nelkul": sum(s["indulas"] is not None and s["esemeny_tipus"] == "tovabbhaladas"
                                 and kezdet_napon(s["tervezett"], nap) for s in esemenyek),
    }
    eredmeny["iranyok"] = menetrendi_iranyok(adatok["menetek"], nap)
    eredmeny["utvonal_reszletek"] = utvonal_reszletek(adatok["menetek"], nap)
    eredmeny["menet_lathatosag"] = menet_lathatosag(adatok["menetek"], nap)
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest")).timestamp()
    veg = datetime.combine(nap + timedelta(days=1), datetime.min.time(), ZoneInfo("Europe/Budapest")).timestamp()
    azonositott = [s for s in esemenyek if s.get("jarmu_menetbol") and s["indulas"] is not None
                  and s["menetrend_ok"] and kezdet <= s["tervezett"] < veg]
    eredmeny["jarmu_azonositas"] = []
    for vonal in eredmeny["vonalak"]:
        sorok = [s for s in azonositott if s["vonal_id"] == vonal["vonal_id"]]
        eredmeny["jarmu_azonositas"].append({
            "vonal_id": vonal["vonal_id"], "menetbol_azonositott_indulasok": len(sorok),
            "menetbol_azonositott_menetek": len({(s["menet_id"], s["szolgalati_nap"]) for s in sorok}),
        })
    for nev in ("menetrend_id", "mintamenetek", "ellenorzott_menetrendek",
                "kizarasok", "megallo_nevek", "potlasi_minta"):
        if nev in adatok:
            eredmeny[nev] = adatok[nev]
    eredmeny["keszult_utc"] = datetime.now(UTC).isoformat()
    eredmeny["kovetesi_orak"] = []
    eredmeny["kovetesi_reszek"] = {"naponta": [], "orankent": []}
    if not adatok.get("mintamenetek") and "kizarasok" in adatok:
        eredmeny["kovetesi_orak"] = kovetesi_orak(esemenyek, nap, adatok["kizarasok"])
        eredmeny["kovetesi_reszek"] = kovetesi_reszek(esemenyek, nap, adatok["kizarasok"])
    eredmeny["kozos_buszok"] = kozos_buszok(eredmeny["kovetesi_orak"])
    eredmeny["utazas"] = utazasi_eredmenyek(adatok, nap)
    # Érzékenységi próba, csak a legfeljebb egyperces mérési keretekkel.
    szigorubb = [s if s["also"] is not None and s["felso"] - s["also"] <= 60 else
                dict(s, indulas=None, keses_mp=None, erkezes=None) for s in esemenyek]
    eredmeny["kontroll"] = osszegzes(szigorubb, nap)
    eredmeny["esemenyek"] = esemenyek
    return eredmeny


def kezdet_napon(ido, nap):
    return datetime.fromtimestamp(ido, ZoneInfo("Europe/Budapest")).date() == nap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for nev, leiras in (("--nap", "Helyi naptári nap, például 2026-10-17"),
                      ("--vonal", "Vonalazonosítók vesszővel, például 3046")):
        parser.add_argument(nev, help=leiras)
    parser.add_argument("--menetrend", type=int, help="A menetrendi ZIP adatbázisbeli azonosítója")
    parser.add_argument("--menet", help="Kis próbához csak ezek a menetazonosítók, vesszővel")
    parser.add_argument("--beallitas", default=".env.db")
    parser.add_argument("--minta", type=Path, help="Korábban kimentett elemzési minta (.json.gz)")
    parser.add_argument("--kimenet", type=Path, default=Path("data/elemzes"))
    args = parser.parse_args()
    if not args.nap or (not args.minta and (not args.vonal or args.menetrend is None)):
        parser.print_help()
        return
    try:
        nap = date.fromisoformat(args.nap)
        args.kimenet.mkdir(parents=True, exist_ok=True)
        if args.minta:
            with gzip.open(args.minta, "rt", encoding="utf-8") as fajl:
                adatok = json.load(fajl)
            if adatok.get("nap") != str(nap) or not isinstance(adatok.get("menetek"), list):
                raise ValueError("A minta másik naphoz tartozik.")
        else:
            with kapcsolat(args.beallitas) as conn:
                conn.row_factory = dict_row
                with conn.transaction():
                    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    conn.execute("SET LOCAL statement_timeout='120s'")
                    kornyezet = minta_kornyezete(conn, nap, args.vonal.split(","), args.menetrend)
                    kornyezet["potlasi_minta"] = potlasi_minta(conn, nap, args.vonal.split(","))
                    menetek = list(adatbazisbol(conn, nap, args.vonal.split(","), args.menetrend,
                                               args.menet.split(",") if args.menet else None))
            adatok = {"nap": str(nap), "menetrend_id": args.menetrend, "mintamenetek": args.menet,
                      "menetek": menetek, **kornyezet}
            json_mentes(args.kimenet / "minta.json.gz", adatok)
        eredmeny = feldolgozas(adatok, nap)
        json_mentes(args.kimenet / "indulasok.json", eredmeny)
        for sor in eredmeny["vonalak"]:
            print(sor["vonal_id"] + ": " + str(sor["keseshez_hasznalt"]) + "/" + str(sor["tervezett"]) + " indulás a késési mintában.")
        print("Eredmény: " + str(args.kimenet / "indulasok.json"))
    except (OSError, ValueError, psycopg.Error) as hiba:
        # Kapcsolati hibánál ne írjuk ki a kapcsolatadatokat.
        print("Az elemzés nem készült el: " + ("adatbázishiba." if isinstance(hiba, psycopg.Error) else str(hiba)))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
