"""Indulások keresése mentett adatokban. A gyűjtőhöz nem nyúl."""

import argparse
import gzip
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from betolto import kapcsolat, menetrendi_ido


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
    egyedi = {}
    for sor in sorok:
        kulcs = (sor["sorrend"], sor.get("adat_ido"),
                 sor["feed_ido"] if sor.get("adat_ido") is None else None)
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
    """Egy menetrendi megállásból legfeljebb egy indulásjelölt készül."""
    megallok = sorted(menet["megallok"], key=lambda s: s["sorrend"])
    kozlesek = kozlesek_ritkitasa(menet["kozlesek"])
    poziciok = menet["poziciok"]
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
        jarmu = utolso_jo.get("jarmu_id")
        if (not jarmu or elozo.get("jarmu_id") != jarmu or vegso.get("jarmu_id") != jarmu
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
                s.update(minoseg="bizonytalan", indulas=None, keses_mp=None, menetrend_ok=False)
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


def kovetes(esemenyek, kezdet, veg, szegely=900, kizarasok=()):
    # Egy megállóhelyet és irányt kell átadni; az órán túli indulásokkal együtt.
    if len({(s["megallo_id"], s["irany"]) for s in esemenyek}) != 1:
        raise ValueError("A követés egy megállóhelyre és irányra számolható.")
    if any(s["also"] <= veg + szegely and s["felso"] >= kezdet - szegely for s in kizarasok):
        return {"hasznalhato": False, "indok": "Menetrenden kívüli vagy pótló menetet is láttunk a vonalon."}
    sorok = sorted(esemenyek, key=lambda s: s["tervezett"])
    blokkok, blokk = [], []
    for s in sorok:
        if s.get("indulas") is not None and s["minoseg"] in ("alatamasztott", "kovetett"):
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
        jo = s.get("indulas") is not None and s["minoseg"] in ("alatamasztott", "kovetett")
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
                      "alatamasztott": a["minoseg"] == b["minoseg"] == "alatamasztott"})
    return parok


def reszidos_varakozas(parok, tervezett, kezdet, veg):
    """Ugyanazon rövid időszakokon számolunk, időtartammal súlyozva."""
    if kezdet >= veg:
        raise ValueError("Az időablak vége legyen későbbi a kezdeténél.")
    lefedett, terulet, terv_terulet, alatamasztott = 0, 0, 0, 0
    kovetesek = []
    for p in parok:
        if p["elso"] == p["masodik"] and kezdet <= p["elso"] < veg:
            kovetesek.append(0)
            alatamasztott += p["alatamasztott"]
            continue
        bal, jobb = max(p["elso"], kezdet), min(p["masodik"], veg)
        if bal >= jobb:
            continue
        ido = jobb - bal
        terv = varakozas(tervezett, bal, jobb)
        terulet += ((p["masodik"] - bal) ** 2 - (p["masodik"] - jobb) ** 2) / 2
        terv_terulet += terv["varakozas_mp"] * ido
        lefedett += ido
        alatamasztott += p["alatamasztott"]
        kovetesek.append(p["masodik"] - p["elso"])
    varas = terulet / lefedett if lefedett else None
    terv_varas = terv_terulet / lefedett if lefedett else None
    return {"hasznalhato": bool(lefedett), "parok": len(kovetesek),
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
                   OR m.vonal_id IS NULL AND m.potolt_vonal_id IS NULL AND (
                       m.megallo_id IN ('F00935','F00933','F03541') OR EXISTS (
                           SELECT 1 FROM megallo_frissites s WHERE s.nyers_id=m.nyers_id
                             AND s.megfigyeles_sorrend=m.sorrend
                             AND s.megallo_id IN ('F00935','F00933','F03541'))))
              AND (t.menet_id IS NULL OR coalesce(m.menet_allapot,0) NOT IN (0,3)
                   OR m.potlas_jelzes IS NOT NULL)
        )
        SELECT m.vonal_id,m.potolt_vonal_id,m.menet_id,m.szolgalati_nap::text,
               extract(epoch FROM min(least(coalesce(m.adat_ido,m.feed_ido),u.also)))::bigint also,
               extract(epoch FROM max(greatest(coalesce(m.adat_ido,m.feed_ido),u.felso)))::bigint felso
        FROM m LEFT JOIN LATERAL (
            SELECT min(least(s.erkezes,s.indulas)) also,max(greatest(s.erkezes,s.indulas)) felso
            FROM megallo_frissites s WHERE s.nyers_id=m.nyers_id AND s.megfigyeles_sorrend=m.sorrend
        ) u ON true
        GROUP BY m.vonal_id,m.potolt_vonal_id,m.menet_id,m.szolgalati_nap
        ORDER BY m.vonal_id,m.menet_id,m.szolgalati_nap
        """, (menetrend_id, kezdet - timedelta(hours=4), veg + timedelta(hours=4), vonalak, vonalak)).fetchall()
    nevek = conn.execute("SELECT megallo_id,nev FROM megallo WHERE menetrend_id=%s",
                         (menetrend_id,)).fetchall()
    return {"ellenorzott_menetrendek": [s["id"] for s in valtozatok], "kizarasok": kizarasok,
            "megallo_nevek": {s["megallo_id"]: s["nev"] for s in nevek}}


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
            SELECT DISTINCT extract(epoch FROM m.adat_ido)::bigint adat_ido,
                   m.jarmu_id,m.megallo_sorrend sorrend,m.megallo_id,
                   coalesce(m.jarmu_allapot,2) allapot,coalesce(m.menet_allapot,0) menet_allapot,m.lat,m.lon
            FROM megfigyeles m JOIN nyers_fajl n ON n.id=m.nyers_id
            WHERE m.menet_id=%s AND m.szolgalati_nap=%s AND n.feed_ido>=%s AND n.feed_ido<%s
              AND m.tipus='vehicle' AND m.adat_ido IS NOT NULL
            ORDER BY adat_ido
            """, param).fetchall()
        sorok = conn.execute("""
            WITH u AS (
                SELECT DISTINCT ON(m.adat_ido) m.*,n.feed_ido
                FROM megfigyeles m JOIN nyers_fajl n ON n.id=m.nyers_id
                WHERE m.menet_id=%s AND m.szolgalati_nap=%s AND n.feed_ido>=%s AND n.feed_ido<%s
                  AND m.tipus='trip_update'
                ORDER BY m.adat_ido,n.feed_ido DESC,m.nyers_id DESC
            )
            SELECT s.megallo_sorrend sorrend,s.megallo_id,u.jarmu_id,
                   extract(epoch FROM u.adat_ido)::bigint adat_ido,
                   extract(epoch FROM u.feed_ido)::bigint feed_ido,
                   extract(epoch FROM s.indulas)::bigint indulas,
                   extract(epoch FROM s.erkezes)::bigint erkezes,
                   s.indulas_bizonytalansag bizonytalansag,s.erkezes_bizonytalansag,
                   coalesce(s.allapot,0) allapot,coalesce(u.menet_allapot,0) menet_allapot
            FROM u LEFT JOIN megallo_frissites s ON s.nyers_id=u.nyers_id AND s.megfigyeles_sorrend=u.sorrend
            ORDER BY u.adat_ido,u.feed_ido
            """, param).fetchall()
        menet["kozlesek"] = kozlesek_ritkitasa(sorok)
        yield menet


def osszegzes(esemenyek, nap):
    kezdet = datetime.combine(nap, datetime.min.time(), ZoneInfo("Europe/Budapest"))
    veg = kezdet + timedelta(days=1)
    napi = [s for s in esemenyek if kezdet.timestamp() <= s["tervezett"] < veg.timestamp()]
    vonalak = []
    for vonal in sorted({s["vonal_id"] for s in napi}):
        sorok = [s for s in napi if s["vonal_id"] == vonal]
        fizikai = [s for s in sorok if s["indulas"] is not None]
        jok = [s for s in sorok if s["indulas"] is not None and s["menetrend_ok"]]
        koran_erkezett = [s for s in jok if s["erkezes"] is not None
                         and s.get("tervezett_erkezes") is not None and s["erkezes"] < s["tervezett_erkezes"]]
        vonalak.append({"vonal_id": vonal, "tervezett": len(sorok), "minoseg": dict(Counter(s["minoseg"] for s in sorok)),
                        "tervezett_menetek": len({(s["menet_id"], s["szolgalati_nap"]) for s in sorok}),
                        "hasznalt_menetek": len({(s["menet_id"], s["szolgalati_nap"]) for s in jok}),
                        "lefedettseg": len(jok) / len(sorok),
                        "fizikai_indulas": len(fizikai), "ellenorizendo_menetrend": len(fizikai) - len(jok),
                        "median_minden_jelolttel_mp": median(s["keses_mp"] for s in fizikai) if fizikai else None,
                        "keseshez_hasznalt": len(jok), "median_keses_mp": median(s["keses_mp"] for s in jok) if jok else None,
                        "p90_keses_mp": p90([s["keses_mp"] for s in jok]) if jok else None,
                        "korai_indulas": sum(s["keses_mp"] < 0 for s in jok),
                        "koran_erkezett": len(koran_erkezett),
                        "megvarta_indulast": sum(s["indulas"] >= s["tervezett"] for s in koran_erkezett)})
    orak, szakaszok = defaultdict(list), defaultdict(list)
    for s in napi:
        if s["indulas"] is not None and s["menetrend_ok"]:
            ora = datetime.fromtimestamp(s["tervezett"], ZoneInfo("Europe/Budapest")).hour
            orak[(s["vonal_id"], s["irany"], ora)].append(s["keses_mp"])
    menetek = defaultdict(list)
    for s in esemenyek:
        menetek[(s["menet_id"], s["szolgalati_nap"])].append(s)
    for megallasok in menetek.values():
        megallasok.sort(key=lambda s: s["sorrend"])
        for a, b in pairwise(megallasok):
            if (b["sorrend"] == a["kovetkezo_sorrend"]
                    and a["indulas"] is not None and b["indulas"] is not None
                    and a["menetrend_ok"] and b["menetrend_ok"]
                    and a["jarmu_id"] == b["jarmu_id"]
                    and kezdet.timestamp() <= b["tervezett"] < veg.timestamp()):
                szakaszok[(a["vonal_id"], a["irany"], a["megallo_id"], b["megallo_id"])].append(b["keses_mp"] - a["keses_mp"])
    return {"nap": str(nap), "vonalak": vonalak,
            "orankent": [{"vonal_id": k[0], "irany": k[1], "ora": k[2], "n": len(v),
                          "median_keses_mp": median(v), "korai_indulas": sum(t < 0 for t in v)}
                         for k, v in sorted(orak.items())],
            "szakaszok": [{"vonal_id": k[0], "irany": k[1], "honnan": k[2], "hova": k[3],
                           "n": len(v), "median_valtozas_mp": median(v)} for k, v in sorted(szakaszok.items())]}


def kovetesi_csoportok(esemenyek, kizarasok):
    # Az első példák ugyanazon peronról, azonos cél felé indulnak.
    csoportok = [("Nyugati, Újbuda felé", "F00935", {"3046"}),
                 ("Nyugati, Széll Kálmán tér felé", "F00933", {"3046"}),
                 ("Bakancsos utca, Örs felé együtt", "F03541", {"0975", "1610", "1695"}),
                 ("Bakancsos utca, 97E", "F03541", {"0975"}),
                 ("Bakancsos utca, 161", "F03541", {"1610"}),
                 ("Bakancsos utca, 169E", "F03541", {"1695"})]
    for nev, megallo, vonalak in csoportok:
        sorok = [s for s in esemenyek if s["megallo_id"] == megallo and s["vonal_id"] in vonalak]
        if megallo == "F03541":
            sorok = [s for s in sorok if s.get("ors_fele")]
        if {s["vonal_id"] for s in sorok} != vonalak:
            continue
        tiltott = [s for s in kizarasok if s["vonal_id"] in vonalak or s.get("potolt_vonal_id") in vonalak
                   or s["vonal_id"] is None and s.get("potolt_vonal_id") is None]
        yield {"hely": nev, "megallo_id": megallo, "vonalak": sorted(vonalak)}, sorok, tiltott


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


def json_mentes(cel, adat):
    # A korábbi kész eredményt csak a teljes új fájl váltja fel.
    atmeneti = cel.with_name(cel.name + ".tmp")
    if cel.suffix == ".gz":
        with gzip.open(atmeneti, "wt", encoding="utf-8", compresslevel=1) as fajl:
            json.dump(adat, fajl, ensure_ascii=False)
    else:
        atmeneti.write_text(json.dumps(adat, ensure_ascii=False, indent=2), encoding="utf-8")
    atmeneti.replace(cel)


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
                    menetek = list(adatbazisbol(conn, nap, args.vonal.split(","), args.menetrend,
                                               args.menet.split(",") if args.menet else None))
            adatok = {"nap": str(nap), "menetrend_id": args.menetrend, "mintamenetek": args.menet,
                      "menetek": menetek, **kornyezet}
            json_mentes(args.kimenet / "minta.json.gz", adatok)
        esemenyek = [s for menet in adatok["menetek"] for s in indulasok(menet)]
        ismetlesek(esemenyek)
        eredmeny = osszegzes(esemenyek, nap)
        eredmeny["menetrend_id"] = adatok["menetrend_id"]
        eredmeny["mintamenetek"] = adatok.get("mintamenetek")
        eredmeny["ellenorzott_menetrendek"] = adatok.get("ellenorzott_menetrendek", [])
        eredmeny["kizarasok"] = adatok.get("kizarasok", [])
        eredmeny["megallo_nevek"] = adatok.get("megallo_nevek", {})
        eredmeny["kovetesi_orak"] = []
        eredmeny["kovetesi_reszek"] = {"naponta": [], "orankent": []}
        if not adatok.get("mintamenetek") and "kizarasok" in adatok:
            eredmeny["kovetesi_orak"] = kovetesi_orak(esemenyek, nap, adatok["kizarasok"])
            eredmeny["kovetesi_reszek"] = kovetesi_reszek(esemenyek, nap, adatok["kizarasok"])
        eredmeny["kozos_buszok"] = kozos_buszok(eredmeny["kovetesi_orak"])
        eredmeny["esemenyek"] = esemenyek
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
