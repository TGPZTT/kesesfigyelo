"""A mentett BKK-adatok menetrendi eltérései, várakozása és adatminősége."""

import gc
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from html import escape
from itertools import pairwise
from pathlib import Path
from textwrap import wrap
from threading import BoundedSemaphore
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

MAPPA = Path(__file__).resolve().parent
IDOZONA = ZoneInfo("Europe/Budapest")
VONALAK = {"0460": "46", "0975": "97E", "1610": "161", "1695": "169E",
           "3010": "1", "3020": "2", "3030": "3", "3046": "4–6",
           "4800": "80", "4820": "82", "H8": "H8", "OPH8": "H8 pótlóbusz"}
NAPNEVEK = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]
NAPMONDATBAN = ["hétfőn", "kedden", "szerdán", "csütörtökön", "pénteken", "szombaton", "vasárnap"]
HONAPOK = ["január", "február", "március", "április", "május", "június",
           "július", "augusztus", "szeptember", "október", "november", "december"]
NEZETEK = {"attekintes": "Áttekintés", "jaratonkent": "Járatonként",
           "adatok": "Adatok és hiányok", "idojaras": "Időjárás", "hev": "HÉV"}
# A vizsgált BKK GTFS routes.txt route_color és route_text_color mezői.
MODSZINEK = {"busz": "#009EE3", "villamos": "#FFD800", "trolibusz": "#E41F18", "HÉV": "#ED6E86"}
FELIRATSZINEK = {"busz": "#FFFFFF", "villamos": "#000000", "trolibusz": "#FFFFFF", "HÉV": "#FFFFFF"}
SZINEK = {"adat": "#475569", "terv": "#94A3B8", "hiany": "#CBD5E1"}
TERSEGEK = {"Belvaros": ("Belváros", ("3010", "3020", "3030", "3046", "4800", "4820")),
            "Rakosmente": ("Rákosmente", ("0460", "0975", "1610", "1695")),
            "Godollo": ("Gödöllő", ("H8",))}
HIBAK = {
    "nincs_kesz": "A nap vagy a betöltött adatok még nem állnak készen az elemzésre.",
    "menetrend": "A menetrendváltozatokat ellenőrizni kell, ezért nem készült új eredmény.",
    "adatbazis": "Az adatbázis elérése vagy olvasása nem sikerült.",
    "atadas": "A szerveres eredmény átvitele nem sikerült.",
    "ellenorzes": "Az adatok vagy beállítások ellenőrzése nem sikerült.",
    "fajl": "A helyi fájl olvasása vagy mentése nem sikerült.",
    "ismeretlen": "A frissítés váratlan hiba miatt megszakadt.",
}


def kozlekedes(vonal):
    if vonal in ("3010", "3020", "3030", "3046"):
        return "villamos"
    if vonal in ("4800", "4820"):
        return "trolibusz"
    return "HÉV" if vonal == "H8" else "busz"


def vonal_neve(vonal):
    return VONALAK.get(vonal, vonal) + " " + kozlekedes(vonal)


def nap_neve(nap):
    ido = datetime.fromisoformat(nap)
    return HONAPOK[ido.month - 1] + " " + str(ido.day) + "., " + NAPNEVEK[ido.weekday()]


def szam(ertek):
    return f"{ertek:,}".replace(",", " ")


def perc(mp):
    return round(mp / 60, 1) if mp is not None else None


def szazalek(arany):
    return round(100 * arany, 1) if arany is not None else None


def idotartam(mp):
    if mp is None:
        return "Nincs elég adat"
    perc_ertek, masodperc = divmod(round(abs(mp)), 60)
    szoveg = str(perc_ertek) + " perc " if perc_ertek else ""
    return szoveg + str(masodperc) + " mp"


def elteres(mp):
    if mp is None:
        return "Nincs elég adat"
    if round(mp) == 0:
        return "A menetrendi idő"
    return idotartam(mp) + (" később" if mp > 0 else " korábban")


def legnagyobb_keses(sor):
    eloszlas = sor.get("keses_eloszlas")
    n = sor.get("keseshez_hasznalt") or sor.get("n", 0)
    if not n or not eloszlas or sum(db for _, db in eloszlas) != n:
        return None
    return max(0, max(mp for mp, db in eloszlas if db))


def bevezeto():
    st.write("A késés számítása azon alapul, hogy a BKK (utólag) kiadja az indulási időket, amit ellenőrizni kell, "
             "és a menetrendtől való eltérést ez alapján kell számítani. "
             "Vannak nap közben közölt adhoc módosítások a menetrendben, de ezek nincsenek kifüggesztve a megállóban, "
             "így ezt is késésnek számolja a program. "
             "Külön adatnak számít minden egyes jármű minden egyes megállóból való továbbhaladása, 30mp-enként érkezik ilyen adat. "
             "Az adat kimarad a számításból, ha valami anomália van, pl az indulási idők ellentmondanak egymásnak, "
             "vagy a mozgás nem követhető, vagy menet közben „teleportál” a jármű az adatok szerint.")


def helyi_ido(ertek):
    ido = datetime.fromisoformat(ertek)
    if ido.tzinfo is None:
        raise ValueError("Hiányzó időzóna.")
    return ido.astimezone(IDOZONA)


def tablazat_html(sorok, mod=None):
    """Valódi fejléces táblázat, szövegként kezelt cellákkal."""
    szin = MODSZINEK.get(mod, "#475569")
    felirat = FELIRATSZINEK.get(mod, "#FFFFFF")
    keret = pd.DataFrame(sorok)
    keret = keret.astype(object).where(pd.notna(keret), "Nincs adat")
    tabla = keret.to_html(index=False, border=0, na_rep="Nincs adat", escape=True,
                         float_format=lambda v: str(round(v, 1)).replace(".", ","))
    tabla = tabla.replace("<thead>", '<thead style="background:' + szin + ";color:" + felirat + '">')
    return ('<div class="utas-tabla" role="region" tabindex="0" aria-label="'
            + escape((mod + " – ") if mod else "") + 'eredmények">' + tabla + "</div>")


def abra(kep, magyarazat="", margok=None):
    kep.update_layout(margin={"l": 0, "r": 0, "t": 15, "b": 0} | (margok or {}), legend_title_text="",
                      font={"size": 14, "color": "#1f2937"}, hoverlabel={"font_size": 14}, separators=", ")
    st.plotly_chart(kep, width="stretch", config={"displaylogo": False})
    if magyarazat:
        st.caption(magyarazat)


def csak_olvashato(adat):
    """A közösen használt mentést egyik látogató megjelenítése sem írhatja át."""
    if isinstance(adat, dict):
        return MappingProxyType({k: csak_olvashato(v) for k, v in adat.items()})
    if isinstance(adat, list):
        return tuple(csak_olvashato(v) for v in adat)
    return adat


@st.cache_resource(show_spinner=False, max_entries=64)
def beolvas(fajl, modositas):
    adat = json.loads(Path(fajl).read_text(encoding="utf-8"))
    if isinstance(adat, dict):
        adat.pop("esemenyek", None)
    return csak_olvashato(adat)


@st.cache_data(show_spinner=False, max_entries=128)
def mentes_fejlece(fajl, modositas):
    """A napi változatok kiválasztásához csak a rövid leírás marad a memóriában."""
    adat = json.loads(Path(fajl).read_text(encoding="utf-8"))
    if regi_modszer(adat):
        if not isinstance(adat.get("nap"), str):
            raise ValueError("Hiányzó nap.")
        return {"nap": adat["nap"], "regi": True}
    minta_ellenorzese(adat)
    if adat["forras_csoport"] != "bkk":
        raise ValueError("A HÉV a napi eredmény külön része.")
    return {"nap": adat["nap"], "modszer": adat["modszer"],
            "keszult_utc": adat.get("keszult_utc", ""),
            "mintamenetek": bool(adat.get("mintamenetek")),
            "vonalak": [s["vonal_id"] for s in adat["vonalak"]]}


def mentesek_allapota():
    fajlok = list((MAPPA / "data").glob("elemzes*/*.json")) + [MAPPA / ".napi-allapot.json"]
    allapot = []
    for fajl in sorted(fajlok):
        try:
            adat = fajl.stat()
            allapot.append((str(fajl), adat.st_mtime_ns, adat.st_size))
        except FileNotFoundError:
            pass
        except OSError:
            allapot.append((str(fajl), None, None))
    return allapot


@st.fragment(run_every=60)
def uj_mentes_figyelese():
    most = mentesek_allapota()
    elozo = st.session_state.get("mentesek_allapota")
    st.session_state["mentesek_allapota"] = most
    if elozo is not None and elozo != most:
        st.rerun()


def minta_ellenorzese(adat):
    if not isinstance(adat, Mapping) or not isinstance(adat.get("vonalak"), (list, tuple)) or not adat["vonalak"]:
        raise ValueError("Nincs napi vonalminta.")
    modszer = adat.get("modszer")
    if modszer not in ("kozles-haladas-ajto-4", "hev-kozles-kontroll-4"):
        raise ValueError("Más feldolgozási módszer.")
    hev = modszer == "hev-kozles-kontroll-4"
    if (adat.get("ido_jelentese") != "utolagos_kozles_mozgassal_ellenorizve"
            or adat.get("idokeret_jelentese") != "mozgasos_ellenorzes_nem_pontossagi_hatar"
            or adat.get("forras_csoport") != ("hev" if hev else "bkk")
            or adat.get("pontossagi_rangsor") is not (not hev)
            or adat.get("hivatalos_pontossaggal_osszevetheto") is not False):
        raise ValueError("Eltérő időértelmezés.")
    datetime.fromisoformat(adat["nap"])
    azonositok = [s["vonal_id"] for s in adat["vonalak"]]
    if len(set(azonositok)) != len(azonositok) or any((v == "H8") != hev for v in azonositok):
        raise ValueError("Eltérő vagy ismételt vonalcsoport.")
    for sor in adat["vonalak"]:
        n, terv = sor["keseshez_hasznalt"], sor["tervezett"]
        if type(n) is not int or type(terv) is not int or not 0 <= n <= terv or not terv:
            raise ValueError("Hibás darabszám.")
        eloszlas = sor["keses_eloszlas"]
        if (any(type(mp) not in (int, float) or not math.isfinite(mp) or type(db) is not int or db <= 0
                for mp, db in eloszlas) or sum(db for _, db in eloszlas) != n):
            raise ValueError("Hiányos késési eloszlás.")
        if not isinstance(sor["minoseg"], Mapping):
            raise TypeError("Hiányos minősítés.")


def napok_kivalasztasa(mintak):
    # A régi időértelmezést nem keverjük az új eredményekkel.
    napok = {}
    for fajl, adat in mintak.items():
        if adat.get("modszer") != "kozles-haladas-ajto-4":
            continue
        elozo = mintak[napok[adat["nap"]]] if adat["nap"] in napok else {}
        sorrend = (not adat.get("mintamenetek"), len(adat["vonalak"]), adat.get("keszult_utc", ""))
        regi = (not elozo.get("mintamenetek"), len(elozo.get("vonalak", [])), elozo.get("keszult_utc", ""))
        if not elozo or sorrend > regi:
            napok[adat["nap"]] = fajl
    return dict(sorted(napok.items()))


def kvantilis(eloszlas, arany):
    """A darabszámokból ugyanazt kapjuk, mint a teljes rendezett mintából."""
    n = sum(db for _, db in eloszlas)
    if not n:
        return None
    hely = (n - 1) * arany
    bal, jobb = math.floor(hely), math.ceil(hely)
    eddig, ertekek = 0, {}
    for ertek, db in sorted(eloszlas):
        for index in (bal, jobb):
            if eddig <= index < eddig + db:
                ertekek[index] = ertek
        eddig += db
    return ertekek[bal] + (ertekek[jobb] - ertekek[bal]) * (hely - bal)


def osszevon(sorok, kulcsok, szakasz=False):
    csoportok = defaultdict(list)
    for sor in sorok:
        csoportok[tuple(sor[k] for k in kulcsok)].append(sor)
    eredmeny = []
    eloszlas_nev = "valtozas_eloszlas" if szakasz else "keses_eloszlas"
    median_nev = "median_valtozas_mp" if szakasz else "median_keses_mp"
    for kulcs, reszek in sorted(csoportok.items()):
        eloszlas = Counter()
        teljes = True
        for sor in reszek:
            n = sor.get("keseshez_hasznalt", sor.get("n", 0))
            if eloszlas_nev not in sor or sum(db for _, db in sor[eloszlas_nev]) != n:
                teljes = False
            else:
                for ertek, db in sor[eloszlas_nev]:
                    eloszlas[ertek] += db
        sor = dict(zip(kulcsok, kulcs))
        for mezo in ("keseshez_hasznalt", "n", "tervezett", "tervezett_parok", "korai_indulas",
                     "koran_erkezett", "megvarta_indulast", "ellenorizendo_menetrend",
                     "bkk_terv_db", "eltero_terv_db", "utolagos_terv_db", "nagy_elteres_db",
                     "tu_osszevetheto", "tu_eltero"):
            sor[mezo] = sum(s.get(mezo, 0) for s in reszek)
        minoseg = Counter()
        for s in reszek:
            minoseg.update(s.get("minoseg", {}))
        sor["minoseg"] = dict(minoseg)
        keretek = Counter()
        for s in reszek:
            for also, felso, db in s.get("idokeretek", []):
                keretek[(also, felso)] += db
        sor["idokeretek"] = [[a, b, db] for (a, b), db in sorted(keretek.items())]
        sor[eloszlas_nev] = sorted(eloszlas.items()) if teljes else None
        sor[median_nev] = kvantilis(eloszlas.items(), 0.5) if teljes else (
            reszek[0].get(median_nev) if len(reszek) == 1 else None)
        sor["p90_keses_mp"] = kvantilis(eloszlas.items(), 0.9) if teljes else (
            reszek[0].get("p90_keses_mp") if len(reszek) == 1 else None)
        n = sor["keseshez_hasznalt"] if "keseshez_hasznalt" in reszek[0] else sor["n"]
        terv = sor["tervezett_parok"] if szakasz else sor["tervezett"]
        sor["lefedettseg"] = n / terv if terv else None
        eredmeny.append(sor)
    return eredmeny


def hev_adatok(adatok):
    """A HÉV külön mintája csak ellenőrizhető napi eredménnyel kerül a nézetbe."""
    eredmeny = []
    for adat in adatok:
        hev = adat.get("hev")
        if not isinstance(hev, Mapping) or hev.get("allapot") not in ("kesz", "nincs_hasznalhato"):
            continue
        try:
            minta_ellenorzese(hev)
            if hev["nap"] != adat["nap"] or any(s["vonal_id"] != "H8" for s in hev["vonalak"]):
                continue
        except (ValueError, TypeError, KeyError):
            continue
        eredmeny.append(hev)
    return eredmeny


def hev_hianyok(adatok, kesz):
    napok = {a["nap"] for a in kesz}
    for adat in adatok:
        if adat["nap"] in napok:
            if not sum(s["keseshez_hasznalt"] for s in adat["hev"]["vonalak"]):
                st.info(nap_neve(adat["nap"]) + " H8-mintájából nincs értékelhető megállói indulás. "
                        "A menetrend és az adatban szereplő menetek vizsgálhatók, "
                        "de késés vagy várakozási idő ebből nem állapítható meg.")
        else:
            hev = adat.get("hev") or {}
            kod = hev.get("hiba_kod") if isinstance(hev, Mapping) else None
            st.info(nap_neve(adat["nap"]) + " napjára nincs értékelhető H8-eredmény. "
                    + HIBAK.get(kod, "A hiányzó eredmény nem nulla késést jelent."))


def hev_hatter(adatok):
    if any("2026-10-17" <= a["nap"] <= "2026-11-06" for a in adatok):
        st.caption("Október 17. és november 6. között a H8 hévet karbantartják, és csak rövidített szakaszon megy. "
                   "Érdekes lett volna az összevetés, de sajnos csak kevés adat állt rendelkezésre a „rendes” időszakból, "
                   "túl hamar kezdődött a karbantartás, így összevetés végül nem készült. "
                   "Az Örs vezér tere és Cinkota közti pótlóbusz nem szerepel az elemzésben. "
                   "[Közlemény](https://www.mavcsoport.hu/mavinform/h8-h9-potlobuszok-fovarosi-szakaszon-oktober-17-november-6)")


def kuszob_arany(sor, hatar):
    eloszlas = sor.get("keses_eloszlas")
    n = sor.get("keseshez_hasznalt") or sor.get("n", 0)
    if not n or eloszlas is None or sum(db for _, db in eloszlas) != n:
        return None
    return sum(db for mp, db in eloszlas if -hatar <= mp <= hatar) / n


def menetrendi_alap_szoveg(sorok):
    """A darabszámok ugyanazokra a szűrt eseményekre vonatkoznak, mint az ábra."""
    n = sum(s.get("keseshez_hasznalt") or s.get("n", 0) for s in sorok)
    if not n:
        return []
    mas = sum(s.get("eltero_terv_db", 0) for s in sorok)
    nagy = sum(s.get("nagy_elteres_db", 0) for s in sorok)
    mondatok = ["A számítás " + szam(n) + " megállói indulást hasonlít a letöltött menetrendhez."]
    if mas:
        mondatok.append("A BKK más tervezett időt is közölt valami módosítás miatt " + szam(mas)
                        + " esetben, viszont ilyenkor nem ezt vettem alapnak, hanem a menetrendet, "
                        "hiszen az van kifüggesztve a megállóban.")
    if nagy:
        mondatok.append(szam(nagy) + " eltérés legalább félóra. Ezek benne maradnak az eredményben, "
                        "de ezek jellemzően a sűrű, egymásra torlódott járatok lehetnek.")
    return mondatok


def menetrendi_alap_kiiras(sorok):
    mondatok = menetrendi_alap_szoveg(sorok)
    if mondatok:
        st.caption(" ".join(mondatok))


def menetrendhez_igazodas(adatok, sorok):
    st.subheader("Melyik járatnál mekkora a pontos indulások aránya?")
    hatar = st.radio("Eltérés nem nagyobb, mint", [60, 120],
                     format_func=lambda mp: str(mp // 60) + " perc", horizontal=True)
    rangsor = [(s, kuszob_arany(s, hatar)) for s in sorok if s["vonal_id"] not in ("H8", "OPH8")]
    rangsor = sorted(((s, a) for s, a in rangsor if a is not None), key=lambda p: (-p[1], p[0]["vonal_id"]))
    if not rangsor:
        st.info("Ehhez az összevetéshez nincs elegendő adat.")
        return
    kep = go.Figure()
    nevek = [vonal_neve(s["vonal_id"]) + "<br>" + szam(s["keseshez_hasznalt"])
             + " megállói elindulás alapján" for s, _ in rangsor]
    perc = str(hatar // 60)
    for belul, nev, szin in ((True, "Legfeljebb " + perc + " perc eltérés", None),
                             (False, perc + " percnél nagyobb eltérés", "#475569")):
        kep.add_trace(go.Bar(
            y=nevek, x=[100 * (a if belul else 1 - a) for _, a in rangsor], orientation="h", name=nev,
            marker_color=szin or [MODSZINEK[kozlekedes(s["vonal_id"])] for s, _ in rangsor],
            text=[arany_szoveg(a if belul else 1 - a) for _, a in rangsor],
            textposition="inside", insidetextanchor="middle",
            insidetextfont={"color": ["white" if kozlekedes(s["vonal_id"]) == "trolibusz" else "#000000"
                                      for s, _ in rangsor] if belul else "white", "size": 13},
            hovertemplate="%{y}<br>%{text}<extra>" + nev + "</extra>"))
    kep.update_layout(barmode="stack", height=max(360, len(rangsor) * 55), legend={"orientation": "h", "y": 1.15})
    kep.update_xaxes(title="Az indulási idők megoszlása a menetrendtől való eltérés szerint (%)", range=[0, 100])
    kep.update_yaxes(autorange="reversed")
    abra(kep, "A százalékok természetesen csak a vizsgálható indulásokra vonatkoznak, minden megálló és mindkét irány együtt szerepel itt.")


def rangsor_osszefoglalo(rangsor, hatar):
    """Ugyanabból a sorrendből készül, mint az ábra, az aktuális tűréshatárral."""
    if len(rangsor) < 2:
        return []
    eleje = "A legfeljebb " + str(hatar // 60) + " perces eltérés aránya "
    if rangsor[0][1] == rangsor[-1][1]:
        return [eleje + "mind a " + str(len(rangsor)) + " járatnál ugyanannyi, "
                + arany_szoveg(rangsor[0][1]) + "."]
    def felsorol(ertek):
        return " és a ".join(vonal_neve(s["vonal_id"]) + "nál" for s, a in rangsor if a == ertek)
    return [eleje + "a " + felsorol(rangsor[0][1]) + " a legnagyobb (" + arany_szoveg(rangsor[0][1])
            + "), a " + felsorol(rangsor[-1][1]) + " a legkisebb (" + arany_szoveg(rangsor[-1][1]) + ")."]


def varakozas_kulonbseg(mp):
    if round(mp) == 0:
        return "Másodpercre kerekítve nincs különbség."
    if mp > 0:
        return "Ez átlagosan " + idotartam(mp) + " többletvárakozást jelent."
    return "Az átlagos várakozás rövidebb volt. A különbség " + idotartam(-mp) + "."


def menet_osszesites(adatok):
    menetek = {}
    for adat in adatok:
        for sor in adat.get("menet_lathatosag", []):
            for menet in sor.get("menetek", []):
                kulcs = (sor["vonal_id"], menet["menet_id"], menet["szolgalati_nap"])
                elozo = menetek.setdefault(kulcs, {"pozicio": False, "menetfrissites": False})
                for mezo in elozo:
                    elozo[mezo] = elozo[mezo] or bool(menet[mezo])
    sorok = {}
    for (vonal, _, _), menet in menetek.items():
        sor = sorok.setdefault(vonal, {"vonal_id": vonal, "tervezett_menetek": 0,
                                      "latott_menetek": 0, "pozicioval": 0, "menetfrissitessel": 0})
        sor["tervezett_menetek"] += 1
        sor["latott_menetek"] += bool(menet["pozicio"] or menet["menetfrissites"])
        sor["pozicioval"] += bool(menet["pozicio"])
        sor["menetfrissitessel"] += bool(menet["menetfrissites"])
    for sor in sorok.values():
        sor["nem_latott_menetek"] = sor["tervezett_menetek"] - sor["latott_menetek"]
    return list(sorok.values())


def megallonev(adatok, megallo):
    nevek = {a.get("megallo_nevek", {}).get(megallo) for a in adatok}
    return " / ".join(sorted(n for n in nevek if n)) or "Név nélkül mentett megálló"


def irany_utvonalak(adatok, vonal, irany):
    utak = Counter()
    for adat in adatok:
        for sor in adat.get("iranyok", []):
            if sor["vonal_id"] == vonal and sor["irany"] == irany:
                for ut in sor["utvonalak"]:
                    utak[(ut["elso_megallo_id"], ut["utolso_megallo_id"])] += ut["tervezett_menetek"]
    return utak


def irany_neve(adatok, vonal, irany):
    utak = irany_utvonalak(adatok, vonal, irany)
    if not utak:
        return "A mentésben nincs megnevezett úti cél"
    celok = Counter()
    for (_, veg), n in utak.items():
        celok[megallonev(adatok, veg)] += n
    return celok.most_common(1)[0][0] + " felé"


def utvonal_valtozatok(adatok, vonal, irany):
    """A peronazonosítók helyett a megállók neve és sorrendje látszik."""
    csoportok = defaultdict(set)
    for adat in adatok:
        for sor in adat.get("utvonal_reszletek", []):
            if sor["vonal_id"] != vonal or sor["irany"] != irany:
                continue
            nevek = []
            for azon in sor["megallo_idk"]:
                nev = megallonev(adatok, azon)
                if not nevek or nevek[-1] != nev:
                    nevek.append(nev)
            if len(nevek) > 1:
                csoportok[tuple(nevek)].update((m["menet_id"], m["szolgalati_nap"]) for m in sor["menetek"])
    return sorted([{"megallok": list(nevek), "utak": len(menetek)} for nevek, menetek in csoportok.items()],
                  key=lambda s: (-s["utak"], s["megallok"]))


def varakozas_osszesites(sorok):
    for sor in sorok:
        if sor["lefedett_mp"] and any(sor.get(m) is None for m in ("varakozas_mp", "tervezett_varakozas_mp")):
            raise ValueError("A használható időhöz hiányzik a várakozási eredmény.")
    ido = sum(s["lefedett_mp"] for s in sorok)
    teljes = sum(s["lefedett_mp"] + s["kimaradt_mp"] for s in sorok)
    adat = {"lefedett_mp": ido, "teljes_mp": teljes,
            "reszletek": sum(s.get("par_reszletek", s["parok"]) for s in sorok),
            "orak": sum(bool(s["lefedett_mp"]) for s in sorok), "vizsgalt_orak": len(sorok)}
    for mezo in ("varakozas_mp", "tervezett_varakozas_mp"):
        adat[mezo] = sum(s[mezo] * s["lefedett_mp"] for s in sorok
                        if s["lefedett_mp"] and s.get(mezo) is not None) / ido if ido else None
    adat["tobblet_mp"] = adat["varakozas_mp"] - adat["tervezett_varakozas_mp"] if ido else None
    return adat


def varakozas_nezet(adatok, vonal=None, irany=None):
    st.subheader("Ha véletlenszerűen megjelenek egy megállóban a 4-6 vonalán, akkor átlagosan mennyit kell várni?")
    sorok = [dict(s, nap=a["nap"]) for a in adatok for s in a.get("kovetesi_reszek", {}).get("orankent", [])
             if tuple(s["vonalak"]) == ("3046",) and 6 <= datetime.fromisoformat(s["kezdet"]).hour < 22]
    nevek = sorted({megallonev(adatok, s["megallo_id"]) for s in sorok})
    if not nevek:
        st.info("Még nincs használható várakozási számítás.")
        return
    alap = next((i for i, n in enumerate(nevek) if "Nyugati" in n), 0)
    nev = st.selectbox("A várakozás helye", nevek, index=alap, key="varakozas_hely")
    rajz = []
    for sid in sorted({s["megallo_id"] for s in sorok if megallonev(adatok, s["megallo_id"]) == nev}):
        resz = [s for s in sorok if s["megallo_id"] == sid]
        er = varakozas_osszesites(resz)
        iranyok = {i["irany"] for s in resz for i in s.get("iranyok", [])}
        merre = ", ".join(irany_neve(adatok, "3046", i) for i in sorted(iranyok))
        for tipus, mezo in (("Adatból becsült", "varakozas_mp"), ("Menetrend szerint", "tervezett_varakozas_mp")):
            if er[mezo] is not None:
                rajz.append({"Irány": merre or sid, "Átlagos várakozás (perc)": perc(er[mezo]), "Számítás": tipus,
                             "Követhető idő (óra)": round(er["lefedett_mp"] / 3600, 1),
                             "Induláspárok részletei": er["reszletek"]})
        if er["lefedett_mp"]:
            st.write(merre + ". Becsült várakozás " + idotartam(er["varakozas_mp"])
                     + ", menetrend szerint " + idotartam(er["tervezett_varakozas_mp"]) + ".")
            st.caption(varakozas_kulonbseg(er["tobblet_mp"]))
    if rajz:
        kep = px.bar(pd.DataFrame(rajz), x="Irány", y="Átlagos várakozás (perc)", color="Számítás",
                     barmode="group", color_discrete_map={"Adatból becsült": MODSZINEK["villamos"], "Menetrend szerint": SZINEK["terv"]},
                     hover_data=["Követhető idő (óra)", "Induláspárok részletei"])
        abra(kep, "A kijelölt napok követhető időszakai 6–22 óra között.")
    else:
        st.info("Ennél a megállónál nincs elég egymást követő, behatárolható elindulás a várakozás kiszámításához.")


def sajat_kerdes(adatok):
    st.subheader("Mi történik, ha a busz nem áll meg?")
    if not all("ellenorzes" in a for a in adatok):
        st.info("Ehhez a mentéshez nincs külön megállásjel-összesítés.")
        return
    n = sum(a["ellenorzes"]["megallasjel_nelkul"] for a in adatok)
    st.write(szam(n) + " továbbhaladásnál nem érkezett megállásjel, de az idő és a mozgás megfelelt az ellenőrzésnek. "
             "Egy rövid megállás két helyzetadat közé is eshet.")


def attekintes(adatok):
    st.header("Adatok bemutatása")
    bevezeto()
    st.divider()
    sorok = osszevon([s for a in adatok for s in a["vonalak"]], ("vonal_id",))
    n, terv = sum(s["keseshez_hasznalt"] for s in sorok), sum(s["tervezett"] for s in sorok)
    bal, jobb = st.columns(2)
    bal.metric("Megállónként vizsgált továbbhaladások száma:", szam(n))
    jobb.metric("A tervezett elindulások ekkora része vizsgálható:", arany_szoveg(n / terv) if terv else "Nincs adat")
    st.divider()
    menetrendhez_igazodas(adatok, sorok)
    st.divider()
    if len(adatok) > 1:
        napi_abra(adatok)
        st.divider()
    varakozas_nezet(adatok)
    st.divider()
    kozos_buszok(adatok)


def kozos_buszok(adatok):
    sorok = [dict(s, nap=a["nap"]) for a in adatok for s in a.get("utazas", {}).get("busz", [])]
    if not sorok:
        st.info("A várakozást és a buszon töltött időt együtt mérő eredmény még nem áll rendelkezésre.")
        return
    st.write("Ha olyan buszokat nézünk, amik ugyanazon a szakaszon mennek, és van néhány közös megálló, "
             "közös a végállomás, akkor érdemes megvárni a menetrend szerint hamarabb beérkezőt, "
             "vagy szálljunk fel az elsőre, ami jön? Itt is a véletlenszerű megállóba érkezés a kiindulópont. "
             "Több megállós buszok több késést tudnak felszedni?")
    parok = defaultdict(list)
    for s in sorok:
        parok[(s["honnan"], s["hova"])].append(s)
    hasznalhato = {par for par, resz in parok.items()
                   for er in [buszos_osszesites(resz)]
                   if er["ido"] >= 600 and er["valasztasok"] and min(v["n"] for v in er["valasztasok"]) >= 3}
    sorok = [s for s in sorok if (s["honnan"], s["hova"]) in hasznalhato]
    if not sorok:
        st.info("A kijelölt napokon nincs legalább tízpercnyi közös megfigyelés, minden választáshoz legalább három busz megérkezésével.")
        return
    honnanok = sorted({s["honnan"] for s in sorok}, key=lambda m: megallonev(adatok, m))
    bal, jobb = st.columns(2)
    alap = next((m for m in ("F03499", "F03541", "011725") if m in honnanok), honnanok[0])
    honnan = bal.selectbox("Honnan indulunk?", honnanok, index=honnanok.index(alap),
                           format_func=lambda m: megallonev(adatok, m), key="busz_honnan")
    hovak = sorted({s["hova"] for s in sorok if s["honnan"] == honnan}, key=lambda m: megallonev(adatok, m))
    hova = jobb.selectbox("Hová mennénk?", hovak, index=hovak.index("008029") if "008029" in hovak else 0,
                          format_func=lambda m: megallonev(adatok, m), key="busz_hova")
    resz = [s for s in sorok if s["honnan"] == honnan and s["hova"] == hova]
    # Eltérő járatkészletű napokból nem készül észrevétlenül más összehasonlítás.
    keszletek = {tuple(s["vonalak"]) for s in resz}
    if len(keszletek) != 1:
        st.info("A kijelölt napokon eltér a választható járatok köre. Ehhez az összevetéshez válassz kevesebb napot.")
        return
    if len({s.get("erkezes_modszer", "kozvetlen-pontpar-1") for s in resz}) != 1:
        st.info("A buszos eredmények frissítése még nem teljes. Ehhez az összevetéshez válassz kevesebb napot.")
        return
    er = buszos_osszesites(resz)
    if not er["ido"]:
        st.info("Nincs közös, hiány nélkül követhető időszak, ahol minden busz indulása és célba érkezése is behatárolható.")
        return
    jaratok = [s["valasztas"] for s in er["valasztasok"] if s["valasztas"] != "elso"]
    if set(jaratok) == {"0975", "1610"} and hova == "008029":
        st.write("A 97E expressz és a 161 több közös megállóból is az Örs vezér tere végállomásra visz.")
    else:
        st.write("A " + " és a ".join(VONALAK[v] for v in jaratok) + " közös célja " + megallonev(adatok, hova) + ".")
    st.caption("A teljes idő a várakozást és a buszon töltött időt együtt tartalmazza.")
    rajz = []
    for s in er["valasztasok"]:
        nev = "Az első megfelelő busz" if s["valasztas"] == "elso" else "Mindig a " + VONALAK[s["valasztas"]]
        for mezo, resz_neve in (("varakozas_mp", "Várakozás"), ("menetido_mp", "Buszon töltött idő")):
            rajz.append({"Választás": nev, "Átlagos idő (perc)": s[mezo] / 60, "Az utazás része": resz_neve,
                         "Felhasznált buszutak": s["n"]})
    kep = px.bar(pd.DataFrame(rajz), y="Választás", x="Átlagos idő (perc)", color="Az utazás része", orientation="h",
                 color_discrete_map={"Várakozás": "#93C5FD", "Buszon töltött idő": MODSZINEK["busz"]},
                 hover_data=["Felhasznált buszutak"])
    valasztasok = er["valasztasok"]
    teljes = [s["varakozas_mp"] + s["menetido_mp"] for s in valasztasok]
    kep.add_trace(go.Scatter(
        x=[t / 60 for t in teljes],
        y=["Az első megfelelő busz" if s["valasztas"] == "elso" else "Mindig a " + VONALAK[s["valasztas"]] for s in valasztasok],
        mode="markers", marker={"size": 5, "color": "#111827"}, name="A célba érkezés becslési tartománya",
        error_x={"type": "data", "symmetric": False,
                 "array": [(s["teljes_felso_mp"] - t) / 60 for s, t in zip(valasztasok, teljes)],
                 "arrayminus": [(t - s["teljes_also_mp"]) / 60 for s, t in zip(valasztasok, teljes)]},
        hovertemplate="Teljes idő %{x:.1f} perc<extra></extra>"))
    nevek = ["Az első megfelelő busz" if s["valasztas"] == "elso"
             else "Mindig a " + VONALAK[s["valasztas"]] for s in valasztasok]
    kep.update_yaxes(tickmode="array", tickvals=nevek,
                     ticktext=[nev + "<br>" + szam(s["n"]) + " külön buszút alapján"
                               for nev, s in zip(nevek, valasztasok)])
    kep.update_layout(barmode="stack", legend={"orientation": "h", "y": 1.15})
    abra(kep, "A vizsgált idő " + arany_szoveg(er["ido"] / er["teljes"])
         + "-ában az összehasonlított járatok indulása és célba érkezése is követhető volt. "
         "Az eredmény ezekre az időszakokra vonatkozik.  \n"
         "Például a busz helyzetadata már a célmegállóra mutatott, de nem érkezett megállást vagy ajtónyitást jelző adat, "
         "ezért az érkezési idő kimaradt a számításból.")
    st.write(buszos_kovetkeztetes(er))
    if er["kesobbi_jobb"]:
        st.write("Az összehasonlítható idő " + arany_szoveg(er["kesobbi_jobb"] / er["ido"])
                 + "-ában a számítás szerint a későbbi busz megvárásával lehetett hamarabb célba érni.")
    else:
        st.write("Nem volt egyértelműen korábban célba érő, később induló busz.")


def buszos_kovetkeztetes(er):
    """Az átlagokból és időkorlátokból következik, nem a példában szereplő járatból."""
    elso = next(s for s in er["valasztasok"] if s["valasztas"] == "elso")
    legjobb = min((s for s in er["valasztasok"] if s["valasztas"] != "elso"),
                  key=lambda s: s["varakozas_mp"] + s["menetido_mp"])
    if legjobb["teljes_felso_mp"] < elso["teljes_also_mp"]:
        return ("A " + VONALAK[legjobb["valasztas"]] + " megvárásával rövidebb volt a számított teljes idő: "
                 + idotartam(legjobb["varakozas_mp"] + legjobb["menetido_mp"]) + ", az első busszal "
                 + idotartam(elso["varakozas_mp"] + elso["menetido_mp"])
                 + ". A követhető időszakokban átlagosan megérte erre a buszra várni.")
    elif elso["teljes_felso_mp"] < legjobb["teljes_also_mp"]:
        return ("Az első megfelelő busszal rövidebb volt a számított teljes idő: "
                 + idotartam(elso["varakozas_mp"] + elso["menetido_mp"]) + ", a "
                 + VONALAK[legjobb["valasztas"]] + " megvárásával "
                 + idotartam(legjobb["varakozas_mp"] + legjobb["menetido_mp"])
                 + ". A követhető időszakokban átlagosan megérte felszállni az első megfelelő buszra.")
    else:
        return ("Az első busz és a " + VONALAK[legjobb["valasztas"]]
                 + " megvárása között a becslési tartományok alapján nem dönthető el a sorrend.")


def napi_oras_sorok(adatok, vonal, irany=None):
    """A napot is megtartja, ezért nem keveredik össze például a hétfő és a kedd reggel."""
    sorok = []
    for adat in adatok:
        reszletek = {(s["vonal_id"], s["irany"], s["ora"]): s
                     for s in adat.get("keses_reszletek", {}).get("orankent", [])}
        for sor in adat.get("orankent", []):
            if sor["vonal_id"] == vonal and (irany is None or sor["irany"] == irany):
                plusz = reszletek.get((vonal, sor["irany"], sor["ora"]), {})
                sorok.append(dict(sor, nap=adat["nap"], menet_db=plusz.get("menet_db"),
                                  maximum=plusz.get("maximum"), maximum_db=plusz.get("maximum_db")))
    return sorted(sorok, key=lambda s: (s["nap"], s["irany"], s["ora"]))


def ora_hasznalhato(sor, hev=False):
    # Ritkább HÉV-nél a buszos harmincas határ a legtöbb órát elrejtené.
    return (sor["n"] >= (10 if hev else 30) and (sor.get("lefedettseg") or 0) >= 0.5
            and sor.get("median_keses_mp") is not None
            and (not hev or (sor.get("menet_db") or 0) >= 2))


def ora_hianyanak_oka(sor, hev=False):
    if not sor.get("tervezett"):
        return "Nem volt tervezett továbbhaladás"
    if not sor.get("n"):
        return "Egyetlen tervezett továbbhaladás sem vizsgálható"
    if sor["n"] < (10 if hev else 30):
        return "Kevés vizsgálható továbbhaladás"
    if (sor.get("lefedettseg") or 0) < 0.5:
        return "A tervezett továbbhaladások kevesebb mint fele követhető"
    if hev and sor.get("menet_db") is None:
        return "A külön vonatok száma hiányzik ebből az exportból"
    if hev and sor["menet_db"] < 2:
        return "Kettőnél kevesebb külön vonat követhető"
    return "Az eltérés nem számítható"


def osszesitett_orak(adatok, vonal, irany):
    # Ugyanazok a nap–óra párok szerepelnek, mint a napi ábrán.
    sorok = [s for s in napi_oras_sorok(adatok, vonal, irany) if ora_hasznalhato(s, vonal == "H8")]
    index = {s["ora"]: s for s in osszevon(sorok, ("ora",))}
    # A hiányzó órát is megtartjuk, különben a vonal átugraná a lyukat.
    return [index.get(ora, {"ora": ora, "n": 0, "lefedettseg": None, "median_keses_mp": None})
            for ora in range(24)]


def ora_neve(ora):
    return str(ora).zfill(2) + "–" + str(ora + 1).zfill(2) + " óra"


def oras_ertek(sor, hev=False, maximum=False):
    if not sor.get("n"):
        return None
    # Egy megfigyelt szélső esethez nem kell a jellemző érték teljes mintája.
    if maximum:
        return legnagyobb_keses(sor)
    return sor.get("median_keses_mp") if ora_hasznalhato(sor, hev) else None


def nap_ora_abra(adatok, vonal, irany=None):
    st.subheader("Melyik napon, hány órakor volt nagyobb eltérés?")
    sorok = napi_oras_sorok(adatok, vonal, irany)
    iranyok = sorted({s["irany"] for s in sorok})
    napok = sorted({a["nap"] for a in adatok})
    hev = vonal == "H8"
    if not iranyok:
        st.info("A kijelölt napokon nincs elegendő adat a naponkénti órás összevetéshez.")
        return
    mutato = st.radio("A hőtérképen látható érték", ["Jellemző eltérés", "Legnagyobb rögzített késés"],
                       horizontal=True, key="oras_mutato_" + vonal, label_visibility="collapsed")
    maximum = mutato == "Legnagyobb rögzített késés"
    jok = [s for s in sorok if oras_ertek(s, hev, maximum) is not None]
    if not jok:
        st.info("A kijelölt napokon nincs elegendő adat számítható órás eltéréshez. A mezők részletei mutatják az okot.")
    szin = MODSZINEK[kozlekedes(vonal)]
    ertekek = [oras_ertek(s, hev, maximum) / 60 for s in jok]
    hatar = max(1, max((abs(v) for v in ertekek), default=0))
    negativ = any(v < 0 for v in ertekek)
    skala = [[0, "#475569"], [0.5, "#FFFFFF"], [1, szin]] if negativ else [[0, "#FFFFFF"], [1, szin]]
    kep = make_subplots(rows=len(iranyok), cols=1, shared_xaxes=True,
                        subplot_titles=[irany_neve(adatok, vonal, i) for i in iranyok],
                        vertical_spacing=0.18 if len(iranyok) > 1 else 0.1)
    for panel, irany_ertek in enumerate(iranyok, 1):
        index = {(s["nap"], s["ora"]): s for s in sorok if s["irany"] == irany_ertek}
        z, hiany, custom, feliratok = [], [], [], []
        for nap in napok:
            szinek, hiany_szinek, adatok_hover, percek = [], [], [], []
            for ora in range(24):
                s = index.get((nap, ora), {})
                ertek = oras_ertek(s, hev, maximum)
                hasznalhato = ertek is not None
                szinek.append(ertek / 60 if hasznalhato else None)
                percek.append(str(perc(ertek)).replace(".", ",") if hasznalhato else "")
                hiany_szinek.append(None if hasznalhato else int(bool(s.get("tervezett"))))
                adatok_hover.append([s.get("n", 0), s.get("tervezett", 0),
                                     arany_szoveg(s.get("lefedettseg")) if s.get("tervezett") else "Nem értelmezhető",
                                     str(s["menet_db"]) if s.get("menet_db") is not None else "Nincs adat",
                                     (("Legnagyobb rögzített késés " + idotartam(ertek)) if maximum
                                      else "Medián " + elteres(ertek)) if hasznalhato
                                     else ora_hianyanak_oka(s, hev)])
            z.append(szinek)
            hiany.append(hiany_szinek)
            custom.append(adatok_hover)
            feliratok.append(percek)
        hover = ("%{y}<br>%{x}<br>%{customdata[4]}"
                 "<br>%{customdata[0]} vizsgálható megállói továbbhaladás"
                 "<br>%{customdata[1]} tervezett megállói továbbhaladás"
                 "<br>Felhasználható arány %{customdata[2]}"
                 + ("<br>Külön vonatok száma %{customdata[3]}" if hev else "") + "<extra></extra>")
        kep.add_trace(go.Heatmap(z=z, x=[ora_neve(h) for h in range(24)],
                                y=[nap_neve(n) for n in napok], colorscale=skala,
                                zmin=-hatar if negativ else 0, zmax=hatar, hoverongaps=False,
                                text=feliratok, texttemplate="%{text}", textfont={"size": 11},
                                customdata=custom, showscale=panel == 1 and bool(jok),
                                colorbar={"title": "perc", "len": 0.65},
                                hovertemplate=hover), row=panel, col=1)
        # Külön állapotszínek, ezek nem nulla késést jelentenek.
        kep.add_trace(go.Heatmap(z=hiany, x=[ora_neve(h) for h in range(24)],
                                y=[nap_neve(n) for n in napok], zmin=0, zmax=1,
                                colorscale=[[0, "#F1F5F9"], [1, "#CBD5E1"]], showscale=False,
                                customdata=custom, hoverongaps=False, hovertemplate=hover), row=panel, col=1)
        kep.update_yaxes(autorange="reversed", row=panel, col=1)
        irany_jok = [s for s in jok if s["irany"] == irany_ertek]
        if irany_jok:
            leg = min(irany_jok, key=lambda s: (-oras_ertek(s, hev, maximum), s["nap"], s["ora"]))
            ertek = oras_ertek(leg, hev, maximum)
            if ertek > 0:
                szoveg = " a legnagyobb rögzített késés " if maximum else " az órákra bontott mediánok közül a legnagyobb "
                st.write(irany_neve(adatok, vonal, irany_ertek) + szoveg
                         + idotartam(ertek) + " volt (" + nap_neve(leg["nap"])
                         + ", " + ora_neve(leg["ora"]) + ").")
            else:
                st.write(irany_neve(adatok, vonal, irany_ertek)
                         + (" egyik bemutatott órában sem volt pozitív közölt késés." if maximum
                            else " egyik bemutatott órában sem volt későbbi a közölt idők mediánja a menetrendnél."))
    kep.update_xaxes(tickangle=-60, tickfont={"size": 11}, showticklabels=True)
    kep.update_layout(height=max(330, len(iranyok) * (len(napok) * 35 + 160)), plot_bgcolor="#E5E7EB")
    abra(kep, margok={"b": 70, "t": 55})


def keses_maximuma(adatok, vonal, irany=None):
    sorok = napi_oras_sorok(adatok, vonal, irany)
    mertek = [(s, legnagyobb_keses(s)) for s in sorok]
    mertek = [(s, m) for s, m in mertek if m is not None and m > 0]
    if not mertek:
        return None
    s, mp = min(mertek, key=lambda p: (-p[1], p[0]["nap"], p[0]["ora"], p[0]["irany"]))
    reszlet = s.get("maximum")
    # Régebbi exportból csak az órasáv állapítható meg, pontos időt nem találunk ki.
    if not isinstance(reszlet, Mapping) or reszlet.get("keses_mp") != mp:
        reszlet = None
    return {"mp": mp, "nap": s["nap"], "ora": s["ora"], "irany": s["irany"], "reszlet": reszlet}


def hev_kovetes_alatamasztasa(pont):
    kov = pont.get("kovetkezo_vonat")
    mezok = {"vonal_id", "megallo_id", "irany", "menet_id", "szolgalati_nap", "tervezett", "indulas"}
    if (not isinstance(kov, Mapping) or not mezok <= pont.keys() or not mezok <= kov.keys()
            or any(type(s[k]) not in (int, float) or not math.isfinite(s[k])
                   for s in (pont, kov) for k in ("tervezett", "indulas"))
            or kov.get("masik_jarmu") is not True
            or pont.get("vonal_id") != "H8" or kov.get("vonal_id") != "H8"
            or (pont["megallo_id"], pont["irany"]) != (kov["megallo_id"], kov["irany"])
            or (pont["menet_id"], pont["szolgalati_nap"]) == (kov["menet_id"], kov["szolgalati_nap"])
            or not pont["tervezett"] < pont["indulas"] < kov["tervezett"]
            or kov.get("indulas") is None or kov["indulas"] <= pont["indulas"]):
        return ""
    idokoz = kov["tervezett"] - pont["tervezett"]
    kovetes = "az órás követés" if idokoz == 3600 else "a menetrendi követés (" + idotartam(idokoz) + ")"
    return "Ennél az esetnél " + kovetes + " és a következő vonat adatai is alátámasztják a késést."


def maximum_szoveg(adatok, vonal, irany=None):
    leg = keses_maximuma(adatok, vonal, irany)
    if not leg:
        st.caption("A kiválasztott adatok között nincs pozitív közölt késés.")
        return
    st.write("A legnagyobb késés " + idotartam(leg["mp"]) + " volt, "
             + irany_neve(adatok, vonal, leg["irany"]) + ".")
    s = leg["reszlet"]
    if s:
        terv = datetime.fromtimestamp(s["tervezett"], IDOZONA)
        kozolt = datetime.fromtimestamp(s["indulas"], IDOZONA)
        hely = megallonev(adatok, s["megallo_id"])
        helyszoveg = "Ez az érték " + hely + " megállóban rögzült." if vonal == "H8" else hely + "."
        if vonal == "H8":
            st.caption((helyszoveg + " " + hev_kovetes_alatamasztasa(s)).strip())
        else:
            st.caption(helyszoveg + " Menetrendi indulás "
                       + nap_neve(terv.date().isoformat()) + " " + terv.strftime("%H:%M:%S")
                       + ". Továbbhaladás " + nap_neve(kozolt.date().isoformat()) + " "
                       + kozolt.strftime("%H:%M:%S") + ".")
    else:
        st.caption("A hozzá tartozó menetrendi óra " + nap_neve(leg["nap"]) + ", " + ora_neve(leg["ora"])
                   + ". Ez a régebbi export nem tartalmazza a pontos időpontot és megállót.")
    return leg


def keses_pelda(adatok, vonal, irany=None, cim=True, rekord=None):
    peldak = [p for a in adatok for p in a.get("keses_reszletek", {}).get("szelso_utak", [])
              if p["vonal_id"] == vonal and (irany is None or p["irany"] == irany)]
    if rekord is not None:
        kulcsok = ("menet_id", "szolgalati_nap", "irany", "sorrend", "tervezett", "keses_mp")
        peldak = [p for p in peldak if all(p["maximum"].get(k) == rekord.get(k) for k in kulcsok)]
    if not peldak:
        return
    pelda = min(peldak, key=lambda p: (-p["maximum"]["keses_mp"], p["maximum"]["tervezett"]))
    if cim:
        st.subheader("A legnagyobb késésű eset a megállók mentén" if vonal == "H8"
                     else "A legnagyobb eredeti menetrendhez mért késésű eset a megállók mentén")
    pontok = pelda["megallok"]
    kezdet = pontok[0]["tervezett"]
    kep = go.Figure()
    for mezo, nev, szin, stilus in (("tervezett", "Menetrend", "#64748B", "dash"),
                                    ("indulas", "Közölt továbbhaladás", MODSZINEK[kozlekedes(vonal)], "solid")):
        kep.add_trace(go.Scatter(x=list(range(len(pontok))),
                                y=[(s[mezo] - kezdet) / 60 if s[mezo] is not None else None for s in pontok],
                                customdata=[[megallonev(adatok, s["megallo_id"]),
                                             datetime.fromtimestamp(s[mezo], IDOZONA).strftime("%Y-%m-%d %H:%M:%S")
                                             if s[mezo] is not None else "Nincs adat"] for s in pontok],
                                mode="lines+markers", connectgaps=False, name=nev,
                                line={"color": szin, "dash": stilus},
                                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra>" + nev + "</extra>"))
    maximum = pelda["maximum"]
    index = next((i for i, s in enumerate(pontok)
                  if (s["sorrend"], s["tervezett"]) == (maximum["sorrend"], maximum["tervezett"])), None)
    if index is not None:
        terv = (maximum["tervezett"] - kezdet) / 60
        kozolt = (maximum["indulas"] - kezdet) / 60
        kep.add_shape(type="line", x0=index, x1=index, y0=terv, y1=kozolt,
                      line={"color": "#111827", "width": 2, "dash": "dot"})
        nev = megallonev(adatok, maximum["megallo_id"])
        felirat = "<br>".join(escape(s) for s in wrap(nev, 35)) + "<br>" + idotartam(maximum["keses_mp"]) + " késés"
        kep.add_annotation(x=index, y=kozolt, text=felirat, showarrow=True, ax=0, ay=-55,
                           xanchor="right" if index > len(pontok) / 2 else "left",
                           bgcolor="white", bordercolor="#64748B", font={"size": 13, "color": "#111827"})
    kep.update_xaxes(tickmode="array", tickvals=list(range(len(pontok))),
                     ticktext=[megallonev(adatok, s["megallo_id"]) for s in pontok],
                     tickangle=-90 if len(pontok) > 25 else -65,
                     tickfont={"size": 11}, automargin=True)
    kep.update_yaxes(title="Az első tervezett indulás óta eltelt idő (perc)")
    kep.update_layout(height=650, legend={"orientation": "h", "y": 1.12})
    elso = datetime.fromtimestamp(kezdet, IDOZONA)
    atnyulik = any(datetime.fromtimestamp(s["tervezett"], IDOZONA).date() != elso.date() for s in pontok)
    leiras = (("" if vonal == "H8" else "Menetrendi indulás: ") + megallonev(adatok, pontok[0]["megallo_id"]) + ", "
              + nap_neve(elso.date().isoformat()) + " " + elso.strftime("%H:%M") + ", "
              + irany_neve(adatok, vonal, pelda["irany"]) + ". "
              + ("A teljes út az éjfél utáni megállókat is tartalmazza. " if atnyulik else "")
               + ("(A hiányzó vagy elutasított közlésnél megszakadhat a vonal.) "
                  if vonal != "H8" and any(s["indulas"] is None for s in pontok) else ""))
    st.write(leiras.rstrip() + "  \n" + " ".join(keses_pelda_osszefoglalo(adatok, pontok)))
    abra(kep, margok={"b": 250})


def keses_pelda_osszefoglalo(adatok, pontok):
    """Csak az export közölt időit írja le, a hiányzó szakaszon nem számol változást."""
    def elteres_mp(pont):
        return pont["indulas"] - pont["tervezett"] if pont["indulas"] is not None else None
    kovetheto = [s for s in pontok if elteres_mp(s) is not None]
    if not kovetheto:
        return []
    elso, utolso = kovetheto[0], kovetheto[-1]
    def kozolt(pont):
        mp = elteres_mp(pont)
        if round(mp) == 0:
            return "a menetrenddel egyező időpont"
        return idotartam(mp) + (" késés" if mp > 0 else " korábbi indulás")
    mondatok = ["Az első követhető megállónál (" + megallonev(adatok, elso["megallo_id"])
                + ") " + kozolt(elso) + ", az utolsónál ("
                + megallonev(adatok, utolso["megallo_id"]) + ") " + kozolt(utolso) + " számítható."]
    parok = [(a, b, elteres_mp(b) - elteres_mp(a)) for a, b in pairwise(pontok)
             if elteres_mp(a) is not None and elteres_mp(b) is not None]
    if parok:
        a, b, novekedes = max(parok, key=lambda p: p[2])
        if novekedes > 0:
            mondatok.append("A legnagyobb növekedés " + megallonev(adatok, a["megallo_id"])
                            + " és " + megallonev(adatok, b["megallo_id"]) + " között volt: "
                            + idotartam(novekedes) + ".")
    if all(elteres_mp(s) > 0 for s in kovetheto):
        mondatok.append("Minden követhető megállónál későbbi időt közöltek a menetrendnél.")
    return mondatok


def hev_napi_eloszlas(adatok):
    st.subheader("Mekkora eltérések fordultak elő az egyes napokon?")
    kategoriak = ["Több mint egy perccel korábban", "Legfeljebb egy perc eltérés",
                  "Egy–öt perc késés", "Öt percnél nagyobb késés"]
    sorok = []
    for adat in sorted(adatok, key=lambda a: a["nap"]):
        csoport = [0, 0, 0, 0]
        for sor in adat["vonalak"]:
            for mp, db in sor["keses_eloszlas"]:
                index = 0 if mp < -60 else 1 if mp <= 60 else 2 if mp <= 300 else 3
                csoport[index] += db
        sorok.append({"nap": adat["nap"], "n": sum(csoport), "db": csoport})
    if not any(s["n"] for s in sorok):
        st.info("Az eltérések eloszlásához nincs adat.")
        return
    kep = go.Figure()
    for index, nev in enumerate(kategoriak):
        kep.add_trace(go.Bar(x=[nap_neve(s["nap"]) for s in sorok],
                             y=[100 * s["db"][index] / s["n"] if s["n"] else None for s in sorok],
                             name=nev, marker_color=MODSZINEK["HÉV"] if index >= 2 else "#64748B",
                             opacity=1 if index in (0, 3) else 0.4,
                             customdata=[[s["db"][index], s["n"]] for s in sorok],
                             hovertemplate="%{x}<br>%{y:.1f}%<br>%{customdata[0]} a %{customdata[1]} vizsgálható elindulásból<extra>"
                                           + nev + "</extra>"))
    kep.update_layout(barmode="stack", legend={"orientation": "h", "y": 1.25}, height=440)
    kep.update_yaxes(title="A vizsgálható közlések aránya (%)", range=[0, 100])
    kep.update_xaxes(tickmode="array", tickvals=[nap_neve(s["nap"]) for s in sorok],
                     ticktext=[nap_neve(s["nap"]) + "<br>" + szam(s["n"]) + " vizsgálható elindulás" for s in sorok])
    abra(kep, margok={"t": 70})
    leg = min((s for s in sorok if s["n"]), key=lambda s: (-s["db"][3] / s["n"], s["nap"]))
    if not leg["db"][3]:
        st.write("A kijelölt napok vizsgálható közlései között nem volt öt percnél nagyobb késés.")
        return
    nap = datetime.fromisoformat(leg["nap"])
    st.write("Az öt percnél nagyobb közölt késések aránya " + NAPMONDATBAN[nap.weekday()]
             + " volt a legnagyobb, " + arany_szoveg(leg["db"][3] / leg["n"])
             + " (" + nap_neve(leg["nap"]).split(",")[0] + "). "
             + szam(leg["n"]) + " vizsgálható állomási elindulásból " + szam(leg["db"][3]) + " tartozott ide.")


def vonalreszlet(adatok):
    st.header("Kiválasztott járat elemzése")
    hev = hev_adatok(adatok)
    vonalak = sorted({s["vonal_id"] for a in adatok + hev for s in a["vonalak"]})
    with st.container(border=True):
        bal, jobb = st.columns(2)
        vonal = bal.selectbox("Járat", vonalak, format_func=vonal_neve)
        forras = hev if vonal == "H8" else adatok
        iranyok = sorted({s["irany"] for a in forras for s in a.get("iranyok", []) if s["vonal_id"] == vonal})
        if not iranyok:
            st.info("A mentésből hiányzik az útirány. Ehhez új elemzési eredmény szükséges.")
            return
        irany = jobb.selectbox("Merre?", iranyok, format_func=lambda i: irany_neve(forras, vonal, i))
    if vonal == "H8":
        hev_hianyok(adatok, hev)
        hev_hatter(adatok)
        hev_modszer()
    orak = [s for a in forras for s in a.get("orankent", []) if s["vonal_id"] == vonal and s["irany"] == irany]
    osszes = osszevon(orak, ("vonal_id", "irany"))
    if osszes:
        s = osszes[0]
        bal, kozep, jobb = st.columns(3)
        bal.metric("Medián késés", elteres(s["median_keses_mp"]))
        kozep.metric("Legnagyobb késés", idotartam(legnagyobb_keses(s)))
        jobb.metric("Ennyi továbbhaladásról van adat:", szam(s["n"]))
        st.caption("A tervezett elindulásokból vizsgálható arány " + arany_szoveg(s["lefedettseg"]) + ".")
    maximum_szoveg(forras, vonal, irany)
    st.divider()
    nap_ora_abra(forras, vonal, irany)
    st.divider()
    st.subheader("Az órák összesítve")
    sorok = osszesitett_orak(forras, vonal, irany)
    if any(s["median_keses_mp"] is not None for s in sorok):
        kep = go.Figure(go.Scatter(x=[s["ora"] for s in sorok],
                                   y=[perc(s["median_keses_mp"]) for s in sorok],
                                   mode="lines+markers", connectgaps=False,
                                   line={"color": MODSZINEK[kozlekedes(vonal)]},
                                   customdata=[[s["n"],arany_szoveg(s["lefedettseg"])] for s in sorok],
                                   hovertemplate="%{x} óra<br>Medián %{y:.1f} perc"
                                                 "<br>%{customdata[0]} megállói továbbhaladás"
                                                 "<br>Felhasználható arány %{customdata[1]}<extra></extra>"))
        kep.update_xaxes(title="Óra", tickvals=list(range(24)))
        kep.update_yaxes(title="Jellemző eltérés (medián, perc)")
        abra(kep, "A kijelölt napok értékelhető órái együtt.")
    else:
        st.info("Az összesített órás eltéréshez nincs elegendő adat.")
    st.divider()
    szakasz_nezet(forras, vonal, irany)
    st.divider()
    keses_pelda(forras, vonal, irany)


def szakasz_nezet(forras, vonal, irany, cim=True, reszletek=True):
    if cim:
        st.subheader("Hogyan változik az eltérés két megálló között?")
    # Az előjel irányt jelez: a korai közlés még korábbivá is válhat.
    st.write("Az érték a menetrendi eltérés változása két megálló között. "
             "Itt azt mutatja meg, hogy nő-e a késés vagy csökken az előző megállóhoz képest. "
             "Gyorsabban megy vagy lassabban két megálló között a kelleténél?  \n")
    valtozatok = utvonal_valtozatok(forras, vonal, irany)
    if not valtozatok:
        st.info("Ehhez a mentéshez nincs teljes megállósorrend.")
        return
    index = 0
    if len(valtozatok) > 1:
        index = st.selectbox("Az ábrán látható megállósor (előre kiszámolt néhány példa)", range(len(valtozatok)),
                             format_func=lambda i: valtozatok[i]["megallok"][0] + " → "
                             + valtozatok[i]["megallok"][-1] + " (" + str(len(valtozatok[i]["megallok"])) + " megálló)")
    valasztott = valtozatok[index]
    if reszletek:
        st.caption("Ezt a teljes megállósort " + szam(valasztott["utak"])
                   + " járműútra írta elő a menetrend a kijelölt napokon.")
    rajz = szakasz_sorrend(forras, vonal, irany, valasztott["megallok"])
    keret = pd.DataFrame(rajz)
    kep = go.Figure(go.Scatter(x=keret["Sorszám"], y=keret["Változás (perc)"], mode="lines+markers",
                              line={"color": MODSZINEK[kozlekedes(vonal)]}, connectgaps=False,
                              customdata=keret[["Szakasz", "Megfigyelt megállópár"]],
                              hovertemplate="%{customdata[0]}<br>%{y:.1f} perc<br>%{customdata[1]} megfigyelt megállópár<extra></extra>",
                              name="Jellemző változás (medián)"))
    mert = [s for s in rajz if s["Változás (perc)"] is not None]
    if mert:
        maximum = max(s["Változás (perc)"] for s in mert)
        kiemelt = [s for s in mert if s["Változás (perc)"] == maximum]
        kep.add_trace(go.Scatter(x=[s["Sorszám"] for s in kiemelt], y=[maximum] * len(kiemelt), mode="markers",
                                marker={"color": "#6D28D9", "size": 12, "symbol": "diamond"},
                                name="Legnagyobb jellemző késésnövekedés" if maximum > 0 else "Legnagyobb érték", text=[s["Szakasz"] for s in kiemelt],
                                hovertemplate="%{text}<br>%{y:.1f} perc<extra></extra>"))
    kep.update_xaxes(tickmode="array", tickvals=keret["Sorszám"], ticktext=keret["Megálló"],
                     tickangle=-90 if len(keret) > 25 else -65, tickfont={"size": 11}, automargin=True)
    kep.update_yaxes(title="Menetrendi eltérés változása (medián, perc)", zeroline=True, zerolinecolor="#475569")
    kep.add_hline(y=0, line_dash="dash", line_color="#64748B",
                  annotation_text="Az eltérés nem változik", annotation_position="bottom right")
    kep.update_layout(height=660, legend={"orientation": "h", "y": 1.15, "x": 0})
    if mert:
        if maximum > 0:
            szoveg = "Legnagyobb jellemző késésnövekedés: " + str(maximum).replace(".", ",") + " perc."
            if vonal == "H8":
                szoveg += " " + kiemelt[0]["Szakasz"] + ", " + szam(kiemelt[0]["Megfigyelt megállópár"]) + " megfigyelt megállópár alapján."
            st.write(szoveg)
        else:
            st.write("Ezen a megállósoron egyik vizsgálható szakaszon sem változott későbbi irányba az eltérés mediánja.")
    abra(kep, margok={"b": 280, "t": 55})
    hiany = sum(s["Változás (perc)"] is None for s in rajz)
    if hiany:
        st.caption("Figyelem! " + str(hiany) + " szakasz számításához nincs elegendő jó minőségű adat!")


def adatminoseg(adatok, fajlok):
    st.header("Mennyi adat használható?")
    teljes = adatok + hev_adatok(adatok)
    sorok = osszevon([s for a in teljes for s in a["vonalak"]], ("vonal_id",))
    n, terv = sum(s["keseshez_hasznalt"] for s in sorok), sum(s["tervezett"] for s in sorok)
    st.write("A menetrend szerinti " + szam(terv) + " elindulásból " + szam(n)
             + " időpontja vizsgálható. Hiányzó időpont vagy nem követhető mozgás esetén az adat kimarad, de ez nem járatkimaradás.")
    rajz = [{"Járat": vonal_neve(s["vonal_id"]), "Használható (%)": szazalek(s["lefedettseg"]),
             "Tervezett elindulás": s["tervezett"], "Vizsgálható elindulás": s["keseshez_hasznalt"],
             "Típus": kozlekedes(s["vonal_id"])} for s in sorok]
    if rajz:
        kep = px.bar(pd.DataFrame(rajz), y="Járat", x="Használható (%)", orientation="h",
                     color="Típus", color_discrete_map=MODSZINEK,
                     hover_data=["Tervezett elindulás", "Vizsgálható elindulás"])
        kep.update_layout(showlegend=False, height=max(340, len(rajz) * 36))
        abra(kep)
        st.caption("Figyelem!, a százalék itt az adat mennyiségét mutatja, nem a járat pontosságát.  \n"
                   + " ".join(menetrendi_alap_szoveg(sorok)))
    else:
        menetrendi_alap_kiiras(sorok)
    st.divider()
    menetek = menet_osszesites(teljes)
    if menetek:
        db = sum(s["tervezett_menetek"] for s in menetek)
        hiany = sum(s["nem_latott_menetek"] for s in menetek)
        st.subheader("Hány járműútról nem érkezett semmilyen adat?")
        st.write(szam(db) + " tervezett végighaladásból " + szam(hiany) + " egyáltalán nem jelent meg az adatokban.")
        rossz = sorted(menetek, key=lambda s: s["nem_latott_menetek"], reverse=True)
        if hiany:
            st.write("A legtöbb ilyen eset a " + vonal_neve(rossz[0]["vonal_id"]) + " adataiból hiányzik, "
                     + szam(rossz[0]["nem_latott_menetek"]) + " a " + szam(rossz[0]["tervezett_menetek"]) + " tervezett közlekedésből.")
    st.divider()
    st.subheader("Mikor akadt el az adatérkezés?")
    orak = []
    for adat, fajl in zip(adatok, fajlok):
        try:
            for ora in beolvas(str(fajl.parent / "adatminoseg.json"), (fajl.parent / "adatminoseg.json").stat().st_mtime_ns):
                ido = datetime.fromisoformat(ora["ora_utc"] + ":00:00+00:00").astimezone(IDOZONA)
                if ido.date().isoformat() != adat["nap"]:
                    continue
                for forras, s in ora["forrasok"].items():
                    orak.append(dict(s, ido=ido, forras=forras))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            st.warning(nap_neve(adat["nap"]) + " gyűjtési részletei most nem olvashatók.")
    if not orak:
        st.info("A gyűjtés óránkénti adatai nem olvashatók.")
        return
    nevek = {"VehiclePositions": "Járművek helyzete", "TripUpdates": "Indulási közlések",
             "Alerts": "Forgalmi jelzések", "Idojaras": "Időjárás", "Weather": "Időjárás"}
    idok = sorted({s["ido"] for s in orak})
    forrasok = sorted({s["forras"] for s in orak})
    index = {(s["forras"], s["ido"]): s for s in orak}
    z, custom = [], []
    for f in forrasok:
        row, detail = [], []
        for ido in idok:
            s = index.get((f, ido), {})
            probak, siker = s.get("probak", 0), s.get("siker", 0)
            row.append(round(siker / probak * 100, 1) if probak else None)
            detail.append([probak, siker, s.get("hibak", 0), perc(s.get("max_sikeres_res_mp"))])
        z.append(row)
        custom.append(detail)
    kep = go.Figure(go.Heatmap(z=z, x=[i.strftime("%m.%d. %H:%M") for i in idok],
                              y=[nevek.get(f, f) for f in forrasok], customdata=custom,
                              colorscale=[[0, "#FECACA"], [1, "#166534"]], zmin=0, zmax=100, colorbar_title="siker %",
                              hovertemplate="%{y}<br>%{x}<br>%{customdata[1]} siker / %{customdata[0]} kérés<br>%{customdata[2]} hiba<br>Leghosszabb szünet %{customdata[3]} perc<extra></extra>"))
    abra(kep)
    probak, hibak = sum(s["probak"] for s in orak), sum(s["hibak"] for s in orak)
    st.write(szam(probak) + " requestből/ adatkérésből " + szam(hibak) + " hibával végződött. "
             "A sikeres letöltés még nem jelenti azt, hogy minden járműről volt is friss adat.")
    rajz = []
    for s in orak:
        for mezo, nev in (("max_jarmu", "Szolgálatban lévő járművek"), ("max_menetfrissites", "Indulási adatsorok")):
            forras = "VehiclePositions" if mezo == "max_jarmu" else "TripUpdates"
            if s["forras"] == forras and s.get(mezo) is not None:
                rajz.append({"Idő": s["ido"], "Egy válaszban látott legtöbb": s[mezo], "Adat": nev,
                             "Idő magyarul": nap_neve(s["ido"].date().isoformat()) + " " + s["ido"].strftime("%H:%M"),
                             "Sikeres kérések": s["siker"]})
    if rajz:
        kep = px.line(pd.DataFrame(rajz), x="Idő", y="Egy válaszban látott legtöbb", color="Adat",
                     color_discrete_sequence=["#009EE3", "#6D28D9"], custom_data=["Idő magyarul", "Sikeres kérések"])
        kep.update_traces(hovertemplate="%{customdata[0]}<br>Egy válaszban látott legtöbb %{y}"
                                        "<br>%{customdata[1]} sikeres kérés<extra>%{fullData.name}</extra>")
        feliratos_idok = sorted({s["Idő"] for s in rajz})[::max(1, math.ceil(len(idok) / 8))]
        kep.update_xaxes(tickmode="array", tickvals=feliratos_idok,
                         ticktext=[HONAPOK[i.month - 1] + " " + str(i.day) + ".<br>" + i.strftime("%H:%M")
                                   for i in feliratos_idok])
        abra(kep, "A teljes BKK-forrás óránkénti legnagyobb jármű- és menetfrissítésszáma látszik.")


def idojaras_orak(adatok, terseg):
    """A hiányzó órák is megmaradnak, a helyi nap lehet 23 vagy 25 órás."""
    eredmeny = []
    for adat in adatok:
        mentett = {}
        for sor in adat.get("idojaras", []):
            if sor.get("terseg") != terseg:
                continue
            ido = datetime.fromisoformat(sor["ora_utc"])
            if ido.tzinfo is None:
                ido = ido.replace(tzinfo=UTC)
            ido = ido.astimezone(UTC)
            if ido in mentett:
                raise ValueError("Ismétlődő időjárási óra.")
            mentett[ido] = sor
        kezdet = datetime.fromisoformat(adat["nap"]).replace(tzinfo=IDOZONA)
        veg = (kezdet + timedelta(days=1)).astimezone(UTC)
        ido = kezdet.astimezone(UTC)
        while ido < veg:
            sor = dict(mentett.get(ido, {}))
            helyi = ido.astimezone(IDOZONA)
            sor.update(nap=adat["nap"], ido=helyi, ora=helyi.hour)
            sor["teljes"] = all(sor.get(k) == 4 for k in (
                "negyedorak", "elvart_negyedorak", "homerseklet_mintak", "szel_mintak")) and all(
                isinstance(sor.get(k), (int, float)) and math.isfinite(sor[k]) for k in (
                    "homerseklet_min", "homerseklet_max", "homerseklet_atlag", "szel_atlag", "szel_max", "csapadek_mm"))
            eredmeny.append(sor)
            ido += timedelta(hours=1)
    return eredmeny


def idojaras_hasznalhato(sor, mezo=None):
    if mezo is None:
        return sor["teljes"]
    darab = {"homerseklet_atlag": "homerseklet_mintak", "szel_atlag": "szel_mintak", "csapadek_mm": "negyedorak"}[mezo]
    ertek = sor.get(mezo)
    return sor.get(darab) == 4 and isinstance(ertek, (int, float)) and math.isfinite(ertek)


def idojaras_kapcsolas(adatok, orak, vonal, mezo=None):
    napi = {a["nap"]: a for a in adatok}
    darab = Counter((s["nap"], s["ora"]) for s in orak)
    eredmeny = []
    for ora in orak:
        if not idojaras_hasznalhato(ora, mezo) or darab[(ora["nap"], ora["ora"])] != 1:
            continue
        sorok = [s for s in napi.get(ora["nap"], {}).get("orankent", [])
                 if s["vonal_id"] == vonal and s["ora"] == ora["ora"]]
        osszes = osszevon(sorok, ("vonal_id",))
        if osszes and osszes[0]["n"] and osszes[0]["median_keses_mp"] is not None:
            eredmeny.append({**ora, **osszes[0]})
    return eredmeny


def osszevetheto_orak(sorok):
    """Közös mintaminimum, a késés nagyságától függetlenül."""
    return [s for s in sorok if s["median_keses_mp"] is not None
            and s["n"] >= 30 and (s["lefedettseg"] or 0) >= 0.5]


def azonos_oras_parok(sorok, mezo):
    """Óránként egy pár a kisebb és nagyobb időjárási értékű napból."""
    orak = defaultdict(list)
    for sor in sorok:
        orak[sor["ora"]].append(sor)
    eredmeny = []
    minimum = 0.1 if mezo == "csapadek_mm" else 1
    for ora, resz in sorted(orak.items()):
        if len({s["nap"] for s in resz}) < 2:
            continue
        kisebb = min(resz, key=lambda s: (s[mezo], s["nap"]))
        nagyobb = max(resz, key=lambda s: (s[mezo], s["nap"]))
        if nagyobb[mezo] - kisebb[mezo] < minimum:
            continue
        eredmeny.append({"ora": ora, "kisebb": kisebb, "nagyobb": nagyobb,
                         "kulonbseg_mp": nagyobb["median_keses_mp"] - kisebb["median_keses_mp"]})
    return eredmeny


def korrelacio(x, y):
    if len(x) < 3 or len(x) != len(y):
        return None
    ax, ay = sum(x) / len(x), sum(y) / len(y)
    szamlalo = sum((a - ax) * (b - ay) for a, b in zip(x, y))
    nevezo = math.sqrt(sum((a - ax) ** 2 for a in x) * sum((b - ay) ** 2 for b in y))
    return szamlalo / nevezo if nevezo else None


def idojarasi_pontabra(kapcsolat):
    sorok, mezo = kapcsolat["sorok"], kapcsolat["mezo"]
    maradek = idojaras_maradekok(sorok, mezo)
    if maradek is None:
        return None
    x, masodpercek = maradek
    y = [mp / 60 for mp in masodpercek]
    nev, egyseg = {"Hőmérséklet": ("Hőmérséklet", "°C"), "Szél": ("Szélsebesség", "km/h"),
                   "Csapadék": ("Csapadék", "mm")}[kapcsolat["nev"]]
    kep = make_subplots(rows=1, cols=2, horizontal_spacing=.14,
                        subplot_titles=("Eredeti órás adatok", "A nap és az órasáv eltérései nélkül"))
    adatok = [[nap_neve(s["nap"]), ora_neve(s["ora"]), s["n"]] for s in sorok]
    jelolo = {"color": MODSZINEK[kozlekedes(kapcsolat["vonal"])], "size": 8,
              "line": {"color": "#475569", "width": 1}}
    # Ugyanazok az órák szerepelnek mindkét oldalon. A korrekció nem válogat új mintát.
    nyers_x = [s[mezo] for s in sorok]
    nyers_y = [s["median_keses_mp"] / 60 for s in sorok]
    for oszlop, xx, yy in ((2, x, y), (1, nyers_x, nyers_y)):
        kep.add_trace(go.Scatter(x=xx, y=yy, mode="markers", marker=jelolo, showlegend=False,
                                 customdata=adatok,
                                 hovertemplate="%{customdata[0]}, %{customdata[1]}<br>%{customdata[2]} továbbhaladás"
                                               "<br>%{x:.2f} " + egyseg + ", %{y:.2f} perc<extra></extra>"),
                      row=1, col=oszlop)
        # Az eredeti adatoknál az egyenes tengelymetszete is számít.
        ax, ay = sum(xx) / len(xx), sum(yy) / len(yy)
        meredekseg = sum((a - ax) * (b - ay) for a, b in zip(xx, yy)) / sum((a - ax) ** 2 for a in xx)
        szelso = [min(xx), max(xx)]
        kep.add_trace(go.Scatter(x=szelso, y=[ay + meredekseg * (a - ax) for a in szelso], mode="lines",
                                 line={"color": "#475569"}, showlegend=False, hoverinfo="skip"), row=1, col=oszlop)
    kep.add_hline(y=0, line_dash="dot", line_color="#94A3B8", row=1, col=2)
    kep.add_vline(x=0, line_dash="dot", line_color="#94A3B8", row=1, col=2)
    kep.update_xaxes(title=nev + " (" + egyseg + ")", row=1, col=1)
    kep.update_yaxes(title="Késésmedián (perc)", row=1, col=1)
    kep.update_xaxes(title=nev + " eltérése a várhatótól (" + egyseg + ")", row=1, col=2)
    kep.update_yaxes(title="Késés eltérése a várhatótól (perc)", row=1, col=2)
    kep.update_xaxes(automargin=True)
    kep.update_yaxes(automargin=True)
    kep.update_layout(height=500)
    return kep


def idojaras_keresek(adatok, fajlok, kezdet, veg):
    osszes, hibas = 0, 0
    for adat, fajl in zip(adatok, fajlok or []):
        try:
            for sor in json.loads((fajl.parent / "adatminoseg.json").read_text(encoding="utf-8")):
                ido = datetime.fromisoformat(sor["ora_utc"] + ":00:00+00:00").astimezone(IDOZONA)
                if ido.date().isoformat() == adat["nap"] and kezdet <= ido.hour < veg:
                    adatforras = sor["forrasok"].get("Idojaras", {})
                    osszes += adatforras.get("probak", 0)
                    hibas += adatforras.get("hibak", 0)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return osszes, hibas


def idojaras_nezet(adatok, fajlok=None):
    st.header("Együtt változik az időjárás és a késés?")
    st.write("Az r (diagramon látható számok) előjele az együttváltozás irányát, "
             "a nagysága a lineáris kapcsolat erősségét mutatja.")
    kapcsolatok = idojaras_osszefugges(adatok)
    vonalak = list(dict.fromkeys(s["vonal"] for s in kapcsolatok))
    nevek = ["Hőmérséklet", "Szél", "Csapadék"]
    index = {(s["vonal"], s["nev"]): s for s in kapcsolatok}
    z, felirat, custom = [], [], []
    for v in vonalak:
        sorok = [index[(v, nev)] for nev in nevek]
        z.append([s["r"] for s in sorok])
        felirat.append([str(round(s["r"], 2)).replace(".", ",") if s["r"] is not None else "—" for s in sorok])
        custom.append([[s["orak"], s["n"], s["ok"], round(s["r"] ** 2, 3) if s["r"] is not None else None] for s in sorok])
    kep = go.Figure(go.Heatmap(z=z, x=nevek, y=[vonal_neve(v) for v in vonalak], zmin=-1, zmax=1,
                              colorscale=[[0, "#1D4ED8"], [.5, "#F3F4F6"], [1, "#B91C1C"]],
                              text=felirat, texttemplate="%{text}", customdata=custom,
                              hovertemplate="%{y}<br>%{x}<br>r = %{text}, r² = %{customdata[3]}<br>%{customdata[0]} óra, %{customdata[1]} elindulás<br>%{customdata[2]}<extra></extra>"))
    kep.update_layout(height=max(360, 39 * len(vonalak)), plot_bgcolor="#E2E8F0")
    abra(kep)
    szamithato = [s for s in kapcsolatok if s["r"] is not None]
    gyenge = [s for s in szamithato if abs(s["r"]) < .3]
    if gyenge:
        st.write("A " + str(len(szamithato)) + " számítható összevetésből " + str(len(gyenge))
                 + " gyenge kapcsolatot mutat (−0,3 és +0,3 között).")
    st.write("Az időjárás és a késés adataiból is kiszűröm a napok és órák átlagos különbségeit. "
             "Így a délutáni meleg és a délutáni késés egybeesése önmagában nem jelent kapcsolatot.")
    homerseklet = homerseklet_kovetkeztetes(kapcsolatok)
    if homerseklet:
        st.write(homerseklet)
    st.divider()
    if szamithato:
        legerosebb = max(szamithato, key=lambda s: abs(s["r"]))
        st.subheader("A mintában legerősebb kapcsolat")
        szoveg = (vonal_neve(legerosebb["vonal"]) + ", " + legerosebb["nev"].lower() + ": r = "
                  + str(round(legerosebb["r"], 2)).replace(".", ",") + ".")
        if abs(legerosebb["r"]) >= .3:
            ido = {"Hőmérséklet": "A melegebb", "Szél": "A szelesebb", "Csapadék": "A csapadékosabb"}[legerosebb["nev"]]
            ok = {"Hőmérséklet": "hőmérséklet", "Szél": "szél", "Csapadék": "csapadék"}[legerosebb["nev"]]
            szoveg += " " + ido + " órákhoz " + ("nagyobb" if legerosebb["r"] > 0 else "kisebb") + " késés társult. "
            szoveg += "Ez önmagában nem bizonyítja, hogy a " + ok
            szoveg += " okozta a késést." if legerosebb["r"] > 0 else " csökkentette a késést."
        else:
            szoveg += " Még a legerősebb kapcsolat is gyenge."
        st.write(szoveg)
        kep = idojarasi_pontabra(legerosebb)
        if kep is not None:
            abra(kep, margok={"b": 85, "t": 45})
    else:
        db = len({a["nap"] for a in adatok})
        if db < 3:
            st.info("Ehhez legalább három összevethető nap kell. Most " + str(db)
                    + " nap van kijelölve. Válassz több napot vagy a teljes időszakot.")
        else:
            st.info("Még nincs elég összevethető adat vagy változó időjárás a kapcsolat számításához.")
    esok = [s["csapadek_mm"] for terseg in TERSEGEK for s in idojaras_orak(adatok, terseg)
            if idojaras_hasznalhato(s, "csapadek_mm")]
    if esok and not any(esok):
        st.write("Minden teljes órában nulla csapadék szerepel, ezért esős és száraz idő nem hasonlítható össze.")
    probak, hibak = idojaras_keresek(adatok, fajlok, 0, 24)
    terseg = next(iter(TERSEGEK))
    orak = idojaras_orak(adatok, terseg)
    teljes = sum(idojaras_hasznalhato(s, "homerseklet_atlag") for s in orak)
    mentes = "A belvárosi hőmérséklet " + str(teljes) + "/" + str(len(orak)) + " órában teljes."
    if probak:
        mentes += " " + str(probak) + " lekérésből " + str(hibak) + " hibás volt."
    st.caption(mentes + " Egy hiányzó negyedóra miatt már kimarad az óra, nem csináltam átlagolásos pótlást a hiányzó adatoknál. "
               "Forrás: [Open-Meteo](https://open-meteo.com/) térségi modelladat.")


def homerseklet_kovetkeztetes(kapcsolatok):
    """A nap és óra közös korrekcióját a vele azonos mintájú nyers kapcsolathoz méri."""
    peldak = []
    for s in kapcsolatok:
        if s["nev"] != "Hőmérséklet" or s["r"] is None:
            continue
        nyers = korrelacio([p[s["mezo"]] for p in s["sorok"]], [p["median_keses_mp"] for p in s["sorok"]])
        if nyers is not None:
            peldak.append((s, nyers))
    if not peldak:
        return None
    s, nyers = max(peldak, key=lambda p: abs(p[1]) - abs(p[0]["r"]))
    ertekek = " (r: " + str(round(nyers, 2)).replace(".", ",") + " → " + str(round(s["r"], 2)).replace(".", ",") + ")."
    if abs(s["r"]) < .3:
        eredmeny = ("Az eredetileg látszó kapcsolat a napok és órák közti átlagos különbségek kiszűrése után gyenge"
                    if abs(nyers) >= .3 else "A hőmérséklet és a késés kapcsolata a napok és órák közti átlagos különbségek kiszűrése után is gyenge")
    else:
        eredmeny = "A melegebb órákhoz " + ("nagyobb" if s["r"] > 0 else "kisebb") + " késés társul a napok és órák közti átlagos különbségek kiszűrése után"
    return vonal_neve(s["vonal"]) + ": " + eredmeny[0].lower() + eredmeny[1:] + ertekek


def mentes_allapota(adat, gyujtes=True):
    ido = adat.get("keszult_utc") if adat else None
    if ido:
        try:
            helyi = helyi_ido(ido)
            st.caption("Legutóbbi eredmény " + helyi.strftime("%Y. %m. %d. %H:%M") + ".")
            if (datetime.now(UTC) - helyi).total_seconds() < -300:
                st.warning("Az export készítési ideje a jövőben van.")
        except (ValueError, TypeError, AttributeError):
            st.warning("Az export készítési ideje hibás.")
    _reszletek, figyelmeztetesek = frissitesi_adatok()
    for szoveg in figyelmeztetesek:
        st.warning(szoveg)
    if gyujtes:
        st.caption("A mentések naponta kerülnek feldolgozásra az adatbázisból, és 30mp-enként kerülnek bekérésre a BKK-tól.")


def frissitesi_adatok():
    reszletek = []
    figyelmeztetesek = []
    allapotfajl = MAPPA / ".napi-allapot.json"
    if not allapotfajl.exists():
        reszletek.append("Nincs állapotjelentés a napi frissítésről. Az ütemezett működés ebből az oldalból nem igazolható.")
        return reszletek, figyelmeztetesek
    try:
        allapot = beolvas(str(allapotfajl), allapotfajl.stat().st_mtime_ns)
        probalkozas = helyi_ido(allapot["utolso_probalkozas_utc"])
        reszletek.append("A frissítés utolsó ismert próbája " + probalkozas.strftime("%Y-%m-%d %H:%M %Z")
                         + ", vizsgált nap " + str(allapot.get("nap") or "ismeretlen") + ".")
        if allapot.get("allapot") == "hiba":
            figyelmeztetesek.append("A legutóbbi frissítés sikertelen volt. "
                                   + HIBAK.get(allapot.get("hiba_kod"), "")
                                   + " A korábbi jó mentések továbbra is láthatók.")
        elif allapot.get("allapot") != "sikeres":
            figyelmeztetesek.append("A frissítés eredménye még nem ismert.")
        if (datetime.now(UTC) - probalkozas).total_seconds() > 36 * 3600:
            figyelmeztetesek.append("Több mint 36 órája nincs új frissítési állapot. A feldolgozást ellenőrizni kell.")
        forras = allapot.get("forras_allapot")
        if forras is not None:
            if not isinstance(forras, Mapping):
                raise TypeError("Hibás szerverállapot.")
            if forras.get("allapot") == "hiba":
                figyelmeztetesek.append("A VPS legutóbbi napi feldolgozása sikertelen volt. "
                                       + HIBAK.get(forras.get("hiba_kod"), "")
                                       + " Egy korábbi jó export sikeres átmásolása ezt nem javítja meg.")
            elif forras.get("allapot") != "sikeres":
                figyelmeztetesek.append("A VPS napi feldolgozásának eredménye nem ismert.")
            if forras.get("utolso_probalkozas_utc"):
                ido = helyi_ido(forras["utolso_probalkozas_utc"])
                reszletek.append("A VPS feldolgozásának utolsó ismert próbája " + ido.strftime("%Y-%m-%d %H:%M %Z")
                                 + ", vizsgált nap " + str(forras.get("nap") or "ismeretlen") + ".")
                if (datetime.now(UTC) - ido).total_seconds() > 36 * 3600:
                    figyelmeztetesek.append("A VPS feldolgozásáról több mint 36 órás az utolsó állapotjelentés.")
            if forras.get("utolso_siker_utc"):
                reszletek.append("A VPS utolsó sikeres napi feldolgozása "
                                 + helyi_ido(forras["utolso_siker_utc"]).strftime("%Y-%m-%d %H:%M %Z") + ".")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        figyelmeztetesek.append("A napi frissítés állapotjelentése nem olvasható. A korábbi mentések továbbra is láthatók.")
    return reszletek, figyelmeztetesek


def arany_szoveg(arany):
    return str(round(100 * arany, 1)).replace(".", ",") + "%" if arany is not None else "Nincs elég adat"


def hev_modszer():
    st.write("A program a MÁV által közölt HÉV-indulásokat veti össze a menetrenddel. "
             "A közvetett adatszolgáltatás nem minden adatot ad át megbízhatóan, de használható.")


def hev_osszehasonlitas(sor):
    n, terv = sor["keseshez_hasznalt"], sor["tervezett"]
    bal, kozep, jobb = st.columns(3)
    bal.metric("Vizsgálható továbbhaladás", szam(n))
    kozep.metric("A menetrendből követhető", arany_szoveg(n / terv) if terv else "Nincs adat")
    jobb.metric("Medián eltérés a menetrendtől", elteres(sor["median_keses_mp"]))
    arany = kuszob_arany(sor, 60)
    if arany is not None:
        st.write("A vizsgálható közölt idők " + arany_szoveg(arany)
                 + "-a legfeljebb egy perccel tér el a menetrendtől.")
    else:
        st.info("A közölt idők összevetéséhez nincs elegendő adat.")


def napi_abra(adatok):
    if len(adatok) < 2:
        return
    st.subheader("Mennyit változott a késés napról napra?")
    sorok = [dict(s, nap=a["nap"]) for a in adatok for s in a["vonalak"]]
    napok = sorted({s["nap"] for s in sorok})
    vonalak = sorted({s["vonal_id"] for s in sorok})
    index = {(s["vonal_id"], s["nap"]): s for s in sorok}
    z, szoveg, adatok_hover = [], [], []
    for v in vonalak:
        row, texts, hover = [], [], []
        for nap in napok:
            s = index.get((v, nap), {})
            ertek = perc(s.get("median_keses_mp"))
            row.append(ertek)
            texts.append(str(ertek).replace(".", ",") if ertek is not None else "Nincs adat")
            hover.append([s.get("keseshez_hasznalt", 0), szazalek(s.get("lefedettseg"))])
        z.append(row)
        szoveg.append(texts)
        adatok_hover.append(hover)
    kep = go.Figure(go.Heatmap(z=z, x=[nap_neve(n) for n in napok], y=[vonal_neve(v) for v in vonalak],
                              text=szoveg, texttemplate="%{text}", colorscale="YlOrRd", colorbar_title="perc",
                              customdata=adatok_hover,
                              hovertemplate="%{y}<br>%{x}<br>Medián %{z:.1f} perc<br>%{customdata[0]} elindulás<br>%{customdata[1]}% használható<extra></extra>"))
    kep.update_layout(height=max(340, len(vonalak) * 58))
    abra(kep, "Minden megálló és mindkét irány együtt jelenik itt meg.")


def szakasz_sorrend(adatok, vonal, irany, megallok):
    """Az összes szakasz megmarad a kiválasztott menetrendi megállósorban, a hiány is."""
    osszes = osszevon([s for a in adatok for s in a.get("szakaszok", [])
                      if s["vonal_id"] == vonal and s["irany"] == irany], ("honnan", "hova"), True)
    nevek = defaultdict(list)
    for sor in osszes:
        nevek[(megallonev(adatok, sor["honnan"]), megallonev(adatok, sor["hova"]))].append(sor)
    eredmeny = []
    for i, (honnan, hova) in enumerate(pairwise(megallok), 1):
        resz = nevek.get((honnan, hova), [])
        sor = osszevon([dict(s, csoport=0) for s in resz], ("csoport",), True)
        s = sor[0] if sor else {}
        eredmeny.append({"Sorszám": i, "Szakasz": honnan + " → " + hova, "Megálló": hova,
                         "Változás (perc)": perc(s.get("median_valtozas_mp")), "Megfigyelt megállópár": s.get("n", 0)})
    return eredmeny


def idojaras_osszefugges(adatok):
    """Az óra szerinti középérték kivonása csökkenti a napszak közös hatását."""
    eredmeny = []
    for terseg, (_, vonalak) in TERSEGEK.items():
        orak = idojaras_orak(adatok, terseg)
        for vonal in vonalak:
            forras = hev_adatok(adatok) if vonal == "H8" else adatok
            for mezo, nev in (("homerseklet_atlag", "Hőmérséklet"), ("szel_atlag", "Szél"), ("csapadek_mm", "Csapadék")):
                sorok = osszevetheto_orak(idojaras_kapcsolas(forras, orak, vonal, mezo))
                csoportok = defaultdict(list)
                for s in sorok:
                    csoportok[s["ora"]].append(s)
                # Csak több napból megfigyelt órákat lehet egymással összevetni.
                paros_csoportok = [resz for resz in csoportok.values() if len({s["nap"] for s in resz}) >= 2]
                paros = [s for resz in paros_csoportok for s in resz]
                x, y = [], []
                for resz in paros_csoportok:
                    atlag_x = sum(s[mezo] for s in resz) / len(resz)
                    atlag_y = sum(s["median_keses_mp"] for s in resz) / len(resz)
                    x.extend(s[mezo] - atlag_x for s in resz)
                    y.extend(s["median_keses_mp"] - atlag_y for s in resz)
                r = korrelacio(x, y) if len(paros) >= 12 and len({s["ora"] for s in paros}) >= 6 else None
                ok = "Kevés összevethető óra"
                if len(paros) >= 12:
                    if not any(x):
                        ok = "Nem változott az időjárási érték"
                    elif not any(y):
                        ok = "Nem változott a késés"
                    elif r is not None:
                        ok = "Számítható"
                erzekenyseg = idojaras_erzekenyseg(paros, mezo)
                if r is not None and erzekenyseg["r"] is None:
                    ok = "Kevés nap vagy kevés, a nap és óra hatásától különválasztható eltérés"
                eredmeny.append({"vonal": vonal, "mezo": mezo, "nev": nev, "r": erzekenyseg["r"],
                                 "r_napszak": r, "erzekenyseg": erzekenyseg, "orak": len(paros),
                                 "n": sum(s["n"] for s in paros), "ok": ok, "sorok": paros})
    return eredmeny


def idojaras_maradekok(sorok, mezo):
    """A korreláció és az ábrája pontosan ugyanazokat a korrigált értékeket használja."""
    napok = sorted({s["nap"] for s in sorok})
    orak = sorted({s["ora"] for s in sorok})
    if len(napok) < 3 or len(orak) < 6 or len(sorok) < 12:
        return None
    # A kategóriák első szintjét a konstans helyettesíti.
    x = np.array([[1] + [int(s["nap"] == n) for n in napok[1:]]
                  + [int(s["ora"] == o) for o in orak[1:]] for s in sorok], dtype=float)
    if len(sorok) - np.linalg.matrix_rank(x) < 6:
        return None
    maradek = []
    for kulcs in (mezo, "median_keses_mp"):
        y = np.array([s[kulcs] for s in sorok], dtype=float)
        r = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
        if np.ptp(r) < 1e-8:
            return None
        maradek.append(r.tolist())
    return maradek


def idojaras_erzekenyseg(sorok, mezo):
    def korrigalt(resz):
        maradek = idojaras_maradekok(resz, mezo)
        return korrelacio(*maradek) if maradek is not None else None
    napok = sorted({s["nap"] for s in sorok})
    kihagyas = [korrigalt([s for s in sorok if s["nap"] != nap]) for nap in napok]
    return {"r": korrigalt(sorok), "napok": len(napok),
            "kihagyas": [r for r in kihagyas if r is not None]}


def regi_modszer(adat):
    if not isinstance(adat, Mapping):
        return False
    if adat.get("modszer") in ("helyzet-idokeret-1", "kozles-haladas-ajto-1", "hev-kozles-kontroll-1",
                              "kozles-haladas-ajto-2", "hev-kozles-kontroll-2",
                              "kozles-haladas-ajto-3", "hev-kozles-kontroll-3"):
        return True
    # A legkorábbi napi exportokban még nem volt módszerjelölés.
    # Az új időértelmezést tartalmazó, hibás mentés továbbra is figyelmeztetést kap.
    return ("modszer" not in adat and adat.get("napi_sema") == 1
            and {"nap", "keszult_utc", "menetrend_id", "vonalak"} <= adat.keys()
            and isinstance(adat["vonalak"], (list, tuple))
            and not any(k in adat for k in ("forras_csoport", "ido_jelentese", "idokeret_jelentese")))


def buszos_osszesites(sorok):
    ido = sum(s["lefedett_mp"] for s in sorok)
    osszeg = defaultdict(Counter)
    for s in sorok:
        for v in s["valasztasok"]:
            for k in ("varakozas_mp", "menetido_mp", "teljes_also_mp", "teljes_felso_mp"):
                osszeg[v["valasztas"]][k] += v[k] * s["lefedett_mp"]
            osszeg[v["valasztas"]]["n"] += v["n"]
    return {"ido": ido, "teljes": sum(s["vizsgalt_mp"] for s in sorok),
            "kesobbi_jobb": sum(s["kesobbi_gyorsabb_mp"] for s in sorok),
            "valasztasok": [{"valasztas": v, **{k: ertek if k == "n" else ertek / ido for k, ertek in e.items()}}
                            for v, e in sorted(osszeg.items())] if ido else []}


def hev_nezet(adatok):
    st.header("H8 HÉV")
    hev_hatter(adatok)
    hev_modszer()
    hev = hev_adatok(adatok)
    hev_hianyok(adatok, hev)
    for s in osszevon([s for a in hev for s in a["vonalak"]], ("vonal_id",)):
        hev_osszehasonlitas(s)
    st.divider()
    nap_ora_abra(hev, "H8")
    st.divider()
    hev_napi_eloszlas(hev)
    st.divider()
    hev_kovetes(hev)
    iranyok = sorted({s["irany"] for a in hev for s in a.get("iranyok", [])})
    if iranyok:
        st.divider()
        st.subheader("Hogyan változik az eltérés két megálló között?")
        irany = st.selectbox("A szakaszos ábra iránya", iranyok,
                             format_func=lambda i: irany_neve(hev, "H8", i), key="hev_szakasz_irany")
        st.caption("Ez az irányválasztó csak a következő ábrát módosítja.")
        szakasz_nezet(hev, "H8", irany, cim=False, reszletek=False)
    st.divider()
    st.subheader("A legnagyobb késésű eset a megállók mentén")
    rekord = maximum_szoveg(hev, "H8")
    if rekord and rekord["reszlet"]:
        keses_pelda(hev, "H8", cim=False, rekord=rekord["reszlet"])


def hev_valaszthato_helyek(hev, sorok):
    """Csak számítható állomás–irány párok, külön megállóazonosítók összevonása nélkül."""
    fo = ("Cinkota", "Kistarcsa", "Kerepes", "Gödöllő, Szabadság tér")
    csoportok = defaultdict(list)
    for sor in sorok:
        nev = megallonev(hev, sor["megallo_id"])
        if nev in fo:
            csoportok[(nev, sor["iranyok"][0]["irany"])].append(sor)
    helyek = {}
    for kulcs, resz in sorted(csoportok.items()):
        azonos = {s["megallo_id"] for s in resz}
        szamithato = any(s["parok"] >= 3 and s.get("median_kovetes_mp") is not None for s in resz)
        if len(azonos) == 1 and szamithato:
            helyek[kulcs] = next(iter(azonos))
    return helyek


def hev_kovetes(hev):
    st.subheader("Mennyi idő telt el két vonat között?")
    sorok = [dict(s, nap=a["nap"]) for a in hev for s in a.get("kovetesi_reszek", {}).get("naponta", [])
             if tuple(s["vonalak"]) == ("H8",) and len(s["iranyok"]) == 1]
    lehet = hev_valaszthato_helyek(hev, sorok)
    if not lehet:
        st.info("A kijelölt napokon nincs elegendő, egy állomáshoz és irányhoz kapcsolható adat. Válassz más napokat.")
        return
    nevek = sorted({nev for nev, _ in lehet})
    alap = "Kerepes" if "Kerepes" in nevek else nevek[0]
    if st.session_state.get("hev_allomas") not in nevek:
        st.session_state["hev_allomas"] = alap
    bal, jobb = st.columns(2)
    nev = bal.selectbox("Állomás", nevek, key="hev_allomas")
    iranyok = sorted({i for hely, i in lehet if hely == nev})
    if st.session_state.get("hev_irany") not in iranyok:
        st.session_state["hev_irany"] = iranyok[0]
    irany = jobb.selectbox("Irány", iranyok,
                           format_func=lambda i: irany_neve(hev, "H8", i), key="hev_irany")
    hely = lehet[(nev, irany)]
    rajz = []
    for s in sorok:
        if s["megallo_id"] != hely or s["iranyok"][0]["irany"] != irany:
            continue
        rajz.append({"Nap": nap_neve(s["nap"]),
                     "hetvege": datetime.fromisoformat(s["nap"]).weekday() >= 5,
                     "Jellemző időköz (medián, perc)": perc(s["median_kovetes_mp"]) if s["parok"] >= 3 else None,
                     "Követhető vonatpár": s["parok"], "A napból követhető (%)": szazalek(s["lefedettseg"])})
    kep = px.line(pd.DataFrame(rajz), x="Nap", y="Jellemző időköz (medián, perc)",
                  color_discrete_sequence=[MODSZINEK["HÉV"]],
                  hover_data=["Követhető vonatpár", "A napból követhető (%)"])
    kep.update_traces(connectgaps=False, hoverinfo="skip", hovertemplate=None, showlegend=False)
    # A pontok színe a dátumot követi, a vonal megtartja a napok sorrendjét és az adathiányokat.
    for hetvege, felirat, szin in ((False, "Hétköznap", MODSZINEK["HÉV"]),
                                  (True, "Hétvége", "#9D174D")):
        pontok = [s for s in rajz if s["hetvege"] == hetvege
                  and s["Jellemző időköz (medián, perc)"] is not None]
        if pontok:
            kep.add_trace(go.Scatter(x=[s["Nap"] for s in pontok],
                                    y=[s["Jellemző időköz (medián, perc)"] for s in pontok],
                                    mode="markers", name=felirat, marker={"color": szin, "size": 8},
                                    customdata=[[s["Követhető vonatpár"], s["A napból követhető (%)"]] for s in pontok],
                                    hovertemplate="%{x}<br>Jellemző időköz (medián, perc) %{y}"
                                    "<br>Követhető vonatpár %{customdata[0]}"
                                    "<br>A napból követhető (%) %{customdata[1]}<extra></extra>"))
    kep.update_layout(legend={"orientation": "h", "y": 1.15})
    mertek = [s for s in rajz if s["Jellemző időköz (medián, perc)"] is not None]
    if mertek:
        percek = [s["Jellemző időköz (medián, perc)"] for s in mertek]
        # A rövidebb követési idő se kerüljön a skála alá.
        also = 20 if min(percek) > 20 else max(0, 5 * math.floor((min(percek) - 1) / 5))
        kep.update_yaxes(range=[also, max(percek) + max(1, (max(percek) - also) * 0.05)])
    mintafeliratok = [s["Nap"] + "<br>" + szam(s["Követhető vonatpár"]) + " követhető vonatpár, "
                     + str(s["A napból követhető (%)"]).replace(".", ",") + "% a napból" for s in rajz]
    kep.update_xaxes(tickmode="array", tickvals=[s["Nap"] for s in rajz], ticktext=mintafeliratok)
    abra(kep)
    if mertek:
        leg = max(mertek, key=lambda s: s["Jellemző időköz (medián, perc)"])
        st.write(nev + ", " + irany_neve(hev, "H8", irany) + ". A legnagyobb napi medián "
                 + str(leg["Jellemző időköz (medián, perc)"]).replace(".", ",") + " perc (" + leg["Nap"]
                 + ", " + szam(leg["Követhető vonatpár"]) + " követhető vonatpár).")


def url_kivalasztas(napok, nezet=None, kijelolt=None):
    """Az elérhető napok és az ismert oldalak közé szorítja a hivatkozás értékeit."""
    oldal = NEZETEK.get(nezet, NEZETEK["attekintes"])
    if kijelolt is None or kijelolt == "mind" or not isinstance(kijelolt, str):
        return oldal, "Minden rendelkezésre álló nap", list(napok)
    if kijelolt == "":
        return oldal, "Napok kiválasztása", []
    valasztott = sorted(set(kijelolt.split(",")) & set(napok))
    if not valasztott:
        return oldal, "Minden rendelkezésre álló nap", list(napok)
    return oldal, "Napok kiválasztása", valasztott


def url_frissitese(nezet, mod, valasztott):
    parameterek = {kulcs: st.query_params.get_all(kulcs) for kulcs in st.query_params}
    parameterek["nezet"] = next(k for k, nev in NEZETEK.items() if nev == nezet)
    parameterek["napok"] = "mind" if mod == "Minden rendelkezésre álló nap" else ",".join(sorted(valasztott))
    st.query_params.from_dict(parameterek)


@st.cache_resource(show_spinner=False)
def megjelenites_zarja():
    # A teljes napi adatokat egyszerre egy oldalbetöltés dolgozza fel.
    return BoundedSemaphore(1)


def main():
    with megjelenites_zarja():
        try:
            oldal()
        finally:
            # Az ábrák körkörös hivatkozásai is felszabadulnak a következő kérés előtt.
            gc.collect()


def oldal():
    st.set_page_config(page_title="Késésfigyelő", layout="wide")
    st.html("""
    <style>
    [data-testid="stMainBlockContainer"] {padding-top:4rem; padding-bottom:1.2rem;}
    [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {gap:0.65rem;}
    [data-testid="stMainBlockContainer"] h1, [data-testid="stMainBlockContainer"] h2,
    [data-testid="stMainBlockContainer"] h3 {padding-top:0.35rem; padding-bottom:0.35rem;}
    [data-testid="stMainBlockContainer"] p {margin-bottom:0.25rem;}
    .utas-tabla {overflow-x:auto; margin:0.4rem 0 1.5rem; border:1px solid #cbd5e1; border-radius:8px;}
    .utas-tabla table {border-collapse:collapse; width:100%; font-size:0.95rem;}
    .utas-tabla th {text-align:left; padding:12px 14px; font-weight:700; white-space:normal; vertical-align:top;}
    .utas-tabla td {padding:10px 14px; border-top:1px solid #d1d5db;}
    .utas-tabla tbody tr:nth-child(even) {background:rgba(148,163,184,0.09);}
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color:#374151 !important; opacity:1 !important; font-size:0.98rem;}
    .utas-tabla:focus {outline:2px solid #009ee3; outline-offset:2px;}
    [data-testid="stSidebar"] {position:sticky; top:0; height:100vh;}
    [data-testid="stMetricValue"] {font-size:1.7rem; line-height:1.3;}
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] [data-testid="stMarkdownContainer"],
    [data-testid="stMetricValue"] p {white-space:normal; overflow:visible; text-overflow:clip;}
    </style>
    """)
    uj_mentes_figyelese()
    mintak = {}
    regi_napok = set()
    for fajl in sorted((MAPPA / "data").glob("elemzes*/indulasok.json")):
        try:
            adat = mentes_fejlece(str(fajl), fajl.stat().st_mtime_ns)
            if adat.get("regi"):
                regi_napok.add(adat["nap"])
                continue
            mintak[fajl] = adat
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            st.warning("Egy mentés nem olvasható vagy hiányos. A többi nap továbbra is használható.")
    if regi_napok - {a["nap"] for a in mintak.values()}:
        st.info("Egyes korábbi napok még más módszerrel készültek. Ezek újraszámolásig nem szerepelnek az összevetésben.")
    if not mintak:
        st.info("Még nincs megjeleníthető elemzési eredmény.")
        mentes_allapota(None)
        return
    napok = napok_kivalasztasa(mintak)
    if not st.session_state.get("url_betoltve"):
        oldal, idoszak, kijelolt = url_kivalasztas(napok, st.query_params.get("nezet"), st.query_params.get("napok"))
        st.session_state.update(oldal_nezet=oldal, idoszak_mod=idoszak, vizsgalt_napok=kijelolt, url_betoltve=True)
    st.sidebar.title("Késésfigyelő")
    nezet = st.sidebar.radio("Nézet", list(NEZETEK.values()), label_visibility="collapsed", key="oldal_nezet")
    st.sidebar.subheader("Időszak az egész oldalhoz")
    mod = st.sidebar.radio("Napok", ["Minden rendelkezésre álló nap", "Napok kiválasztása"],
                           label_visibility="collapsed", key="idoszak_mod")
    if mod == "Minden rendelkezésre álló nap":
        valasztott = list(napok)
        st.sidebar.caption("Az új napok automatikusan bekerülnek.")
    else:
        st.session_state["vizsgalt_napok"] = [n for n in st.session_state.get("vizsgalt_napok", list(napok)) if n in napok]
        valasztott = st.sidebar.multiselect("Vizsgált napok", list(napok),
                                           format_func=lambda n: nap_neve(n) + " (" + n[:4] + ")", key="vizsgalt_napok")
    url_frissitese(nezet, mod, valasztott)
    st.sidebar.caption("Elérhető adatok " + nap_neve(min(napok)) + " és " + nap_neve(max(napok)) + " között.")
    if not valasztott:
        st.info("Az elemzéshez legalább egy nap kijelölése szükséges.")
        return
    # A teljes adatok csak a kiválasztott napok nyertes változatából kellenek.
    adatok, fajlok = [], []
    for nap in sorted(valasztott):
        fajl = napok[nap]
        try:
            adat = beolvas(str(fajl), fajl.stat().st_mtime_ns)
            minta_ellenorzese(adat)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            st.warning("Egy mentés nem olvasható vagy hiányos. A többi nap továbbra is használható.")
            continue
        adatok.append(adat)
        fajlok.append(fajl)
    if not adatok:
        st.info("Még nincs megjeleníthető elemzési eredmény.")
        mentes_allapota(None)
        return
    if any(a.get("mintamenetek") for a in adatok):
        st.warning("A kiválasztás próbamintát is tartalmaz, nem teljes napi vonalvizsgálat.")
    st.sidebar.markdown("**A járatok színei**")
    st.sidebar.html('<p><span style="background:#009EE3;color:white;padding:4px 8px;border-radius:4px">Busz</span> '
                    '<span style="background:#FFD800;color:black;padding:4px 8px;border-radius:4px">Villamos</span> '
                    '<span style="background:#E41F18;color:white;padding:4px 8px;border-radius:4px">Troli</span> '
                    '<span style="background:#ED6E86;color:white;padding:4px 8px;border-radius:4px">HÉV</span></p>')
    try:
        if nezet == "Áttekintés":
            attekintes(adatok)
        elif nezet == "Járatonként":
            vonalreszlet(adatok)
        elif nezet == "Adatok és hiányok":
            adatminoseg(adatok, fajlok)
        elif nezet == "HÉV":
            hev_nezet(adatok)
        else:
            idojaras_nezet(adatok, fajlok)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        st.error("A kiválasztott mentés egyik részlete hiányos. Másik nap vagy oldal továbbra is választható. "
                 "Az eredeti adatok megmaradtak.")
    st.divider()
    mentes_allapota(max(adatok, key=lambda a: a.get("keszult_utc", "")), gyujtes=nezet != "Áttekintés")
    st.caption("Közlekedési adatok forrása: [BKK Zrt.](https://opendata.bkk.hu/data-sources), "
               "időjárás: [Open-Meteo](https://open-meteo.com/). "
               "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.hu). Az oldal feldolgozott adatokat mutat.")


if __name__ == "__main__":
    main()
