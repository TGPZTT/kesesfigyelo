"""A mentett elemzési eredmények helyi webes nézete."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

MAPPA = Path(__file__).resolve().parent
IDOZONA = ZoneInfo("Europe/Budapest")
VONALAK = {"0460": "46", "0975": "97E", "1610": "161", "1695": "169E",
           "3010": "1", "3020": "2", "3030": "3", "3046": "4–6",
           "4800": "80", "4820": "82", "H8": "H8"}
MINOSEGEK = {"alatamasztott": "Megállás és továbbhaladás is látszott",
             "kovetett": "Továbbhaladással követett",
             "bizonytalan": "Bizonytalan", "nem_lattuk": "Nem láttuk",
             "torolt": "Töröltként jelzett"}


@st.cache_data(show_spinner=False)
def beolvas(fajl, modositas):
    # A módosítás ideje miatt egy friss export újra beolvasódik.
    adat = json.loads(Path(fajl).read_text(encoding="utf-8"))
    if isinstance(adat, dict):
        adat.pop("esemenyek", None)
    return adat


def perc(masodperc):
    return round(masodperc / 60, 1) if masodperc is not None else None


def tabla(sorok):
    st.dataframe(pd.DataFrame(sorok), hide_index=True, width="stretch")


def abra(kep, magyarazat):
    kep.update_layout(margin={"l": 0, "r": 0, "t": 15, "b": 0}, legend_title_text="")
    # A vonaljelek és órák címkék, nem folytonos számértékek.
    if kep.data[0].orientation == "h":
        kep.update_yaxes(type="category")
    else:
        kep.update_xaxes(type="category")
    st.plotly_chart(kep, width="stretch", config={"displaylogo": False})
    st.caption(magyarazat)


def megallonev(adat, azonosito):
    nevek = adat.get("megallo_nevek", {})
    return nevek[azonosito] + " (" + azonosito + ")" if azonosito in nevek else azonosito


def attekintes(adat):
    st.header("Áttekintés")
    sorok = [{"Vonal": VONALAK.get(s["vonal_id"], s["vonal_id"]),
              "Tervezett indulás": s["tervezett"], "Felhasznált indulás (n)": s["keseshez_hasznalt"],
              "Lefedettség (%)": round(100 * s["lefedettseg"], 1),
              "Medián eltérés (perc)": perc(s["median_keses_mp"]),
              "90. percentilis (perc)": perc(s["p90_keses_mp"]),
              "Közölt idő szerint korai": s["korai_indulas"]} for s in adat["vonalak"]]
    tabla(sorok)
    st.caption("Egy indulás egy menet egy megállóját jelenti. Ugyanaz a menet több sorhoz járul hozzá. "
               "A lefedettség a késésszámításhoz felhasznált és a tervezett indulások aránya.")
    rajz = pd.DataFrame([s for s in sorok if s["Medián eltérés (perc)"] is not None])
    if not rajz.empty:
        rajz = rajz.sort_values("Medián eltérés (perc)")
        abra(px.bar(rajz, x="Vonal", y="Medián eltérés (perc)",
                    hover_data=["Felhasznált indulás (n)", "Lefedettség (%)"]),
             "A pozitív eltérés későbbi, a negatív korábbi indulást jelent a kiválasztott menetrendhez képest. "
             "Az ábra " + str(sum(s["Felhasznált indulás (n)"] for s in sorok))
             + " megállói indulásból készült; a vonalak eltérő megálló- és napszaki összetételét nem igazítja ki.")
    st.write("A medián a középső érték; a 90. percentilisnél az eltérések 90%-a kisebb vagy egyenlő. "
             "Ezek a menetrendi eltérést írják le, önmagukban nem a teljes megbízhatóságot.")

    st.subheader("Korai érkezés és az indulási közlés")
    tabla([{"Vonal": VONALAK.get(s["vonal_id"], s["vonal_id"]),
            "Korai érkezés közölve (n)": s["koran_erkezett"],
            "Indulás a tervnél nem korábban": s["megvarta_indulast"],
            "Indulás a terv előtt": s["koran_erkezett"] - s["megvarta_indulast"]}
           for s in adat["vonalak"]])
    st.caption("Csak a stabil érkezési közléssel és használható indulással rendelkező esetek szerepelnek. "
               "A besorolás a közölt időpontokon alapul, nem bizonyítja másodpercre a tényleges korai indulást. "
               "A korai érkezés önmagában nem hiba: a jármű még kivárhatja a menetrendi indulást.")


def kovetesi_nezet(adat, vonal):
    # A részidőszakok eredményeit nem egészítjük ki teljes nappá.
    napok = [s for s in adat.get("kovetesi_reszek", {}).get("naponta", []) if vonal in s["vonalak"]]
    if not napok:
        st.info("Ehhez a vonalhoz ebben az exportban nincs részidőszakos követési eredmény.")
        return
    st.subheader("Követés és várakozás")
    hely = st.selectbox("Vizsgált megálló és járatcsoport", [s["hely"] for s in napok])
    sor = next(s for s in napok if s["hely"] == hely)
    tabla([{"Felhasznált párok (n)": sor["parok"],
            "Azonos közölt másodperc": sor.get("nulla_kovetes", 0),
            "Medián követés (perc)": perc(sor.get("median_kovetes_mp")),
            "90. percentilis (perc)": perc(sor.get("p90_kovetes_mp")),
            "Leghosszabb követés (perc)": perc(sor.get("max_kovetes_mp"))}])
    st.caption("A követés két egymás utáni indulás közti idő. Az azonos közölt másodperc külön járművekre "
               "vonatkozik, és nem bizonyít másodpercen belüli pontosságot.")
    tabla([{"Lefedett idő (óra)": round(sor["lefedett_mp"] / 3600, 2),
            "Kimaradt idő (óra)": round(sor["kimaradt_mp"] / 3600, 2),
            "Lefedettség (%)": round(100 * sor["lefedettseg"], 1),
            "Számított várakozás (perc)": perc(sor.get("varakozas_mp")),
            "Menetrendi várakozás (perc)": perc(sor.get("tervezett_varakozas_mp")),
            "Különbség (perc)": perc(sor.get("tobblet_mp"))}])
    st.write("A várakozás egy véletlenszerű időpontban érkező utas számított átlaga az ellenőrizhető "
             "időszakokon. A menetrendet ugyanazokon az időszakokon hasonlítjuk össze. "
             "Ez nem mért utasadat és nem a teljes nap várakozási átlaga.")
    st.caption("A napi számítás éjszakai üzemszünetet is tartalmazhat. Ritka busznál ez jelentősen "
               "növelheti az átlagot; a napszaki ábrán az utazás időszakát érdemes külön nézni. "
               "Eltérő lefedettségű járatcsoportok napi átlagait nem hasonlítjuk közvetlenül össze.")
    orak = [s for s in adat["kovetesi_reszek"].get("orankent", [])
            if s["hely"] == hely and s["hasznalhato"]]
    if orak:
        rajz = pd.DataFrame([{"Óra": datetime.fromisoformat(s["kezdet"]).strftime("%H:%M %z"),
                              "Plusz várakozás (perc)": perc(s["tobblet_mp"]),
                              "Párok (n)": s["parok"],
                              "Lefedettség (%)": round(100 * s["lefedettseg"], 1)} for s in orak])
        abra(px.bar(rajz, x="Óra", y="Plusz várakozás (perc)", hover_data=["Párok (n)", "Lefedettség (%)"]),
             "Óránként a megfigyelt és a menetrendi várakozás különbsége a lefedett részidőszakokon; "
             + str(len(orak)) + " órában van eredmény. A hiányzó órák nem nulla várakozást jelentenek. "
             "Az n és a lefedettség az oszlop fölé húzott egérrel is látszik; egy pár órahatárt is átléphet.")
        tabla(rajz)
    st.caption("A követési idő két szomszédos indulás közti idő. A bizonytalan köztes indulásokat érintő "
               "időszakokat nem számoljuk üres közlekedési résnek.")


def kozos_buszok(adat):
    sorok = adat.get("kozos_buszok", [])
    if not sorok:
        return
    st.subheader("Örs vezér tere felé: az első megfelelő busz")
    rajz = []
    for sor in sorok:
        ido = datetime.fromisoformat(sor["kezdet"]).strftime("%H:%M %z")
        kulon_n = {s["vonalak"][0]: s["indulasok"] for s in adat["kovetesi_orak"]
                   if s["megallo_id"] == "F03541" and len(s["vonalak"]) == 1
                   and s["kezdet"] == sor["kezdet"] and s["hasznalhato"]}
        for vonal, ido_mp in {"Együtt": sor["egyutt_mp"], **sor["kulon_mp"]}.items():
            rajz.append({"Óra": ido, "Járatcsoport": VONALAK.get(vonal, vonal),
                         "Várakozás (perc)": perc(ido_mp),
                         "Indulások (n)": sor["indulasok"] if vonal == "Együtt" else kulon_n[vonal]})
    abra(px.bar(pd.DataFrame(rajz), x="Óra", y="Várakozás (perc)", color="Járatcsoport",
                barmode="group", hover_data=["Indulások (n)"]),
         "Bakancsos utcánál a 97E, 161 és 169E együttes választása hasonlítható a külön vonalakhoz, "
         + str(len(sorok)) + " közös, teljes órában. A számítás véletlenszerű utasérkezést feltételez. "
         "Az első busz rövidebb várakozást adhat, de az eltérő menetidők miatt nem feltétlenül érkezik előbb a célhoz.")
    st.caption("Ez a teljes órákra szűrt összehasonlítás külön minta a fenti részidőszakos eredményhez képest.")


def vonalreszlet(adat):
    st.header("Vonalrészlet")
    vonal = st.selectbox("Vonal", [s["vonal_id"] for s in adat["vonalak"]],
                         format_func=lambda v: VONALAK.get(v, v))
    sorok = [s for s in adat.get("orankent", []) if s["vonal_id"] == vonal]
    if sorok:
        irany = st.selectbox("Irány a menetrendben", sorted({s["irany"] for s in sorok}),
                             format_func=lambda v: str(v) + ". irány")
        sorok = [s for s in sorok if s["irany"] == irany]
        rajz = pd.DataFrame([{"Óra": str(s["ora"]).zfill(2) + ":00",
                              "Medián eltérés (perc)": perc(s["median_keses_mp"]),
                              "Indulások (n)": s["n"]} for s in sorok])
        st.subheader("Napszak szerint")
        abra(px.bar(rajz, x="Óra", y="Medián eltérés (perc)", hover_data=["Indulások (n)"]),
             "Az óra a menetrendi indulás órája, budapesti idő szerint. Az ábra "
             + str(sum(s["n"] for s in sorok)) + " használható megállói indulást foglal össze; "
             "nem korrigál a megállók eltérő összetételére. A hiányzó oszlop nem nulla eltérés.")
        tabla(rajz)
        st.subheader("Melyik megállószakaszon változott a késés?")
        szakaszok = [s for s in adat.get("szakaszok", []) if s["vonal_id"] == vonal and s["irany"] == irany]
        if szakaszok:
            megallok = sorted({s["honnan"] for s in szakaszok}, key=lambda m: megallonev(adat, m))
            megallo = st.selectbox("Szakasz kezdő megállója", [None] + megallok,
                                   format_func=lambda m: "Mindegyik" if m is None else megallonev(adat, m))
            szurt = [s for s in szakaszok if megallo is None or s["honnan"] == megallo]
            tablazat = [{"Honnan": megallonev(adat, s["honnan"]), "Hová": megallonev(adat, s["hova"]),
                         "Medián változás (perc)": perc(s["median_valtozas_mp"]), "Megállópárok (n)": s["n"]}
                        for s in szurt]
            tabla(tablazat)
            rajz = pd.DataFrame(tablazat).sort_values("Medián változás (perc)", ascending=False).head(12)
            rajz["Szakasz"] = rajz["Honnan"] + " → " + rajz["Hová"]
            abra(px.bar(rajz, y="Szakasz", x="Medián változás (perc)", orientation="h",
                        hover_data=["Megállópárok (n)"]),
                 "Ugyanannak a menetnek és járműnek két szomszédos megállóját hasonlítjuk. "
                 "A pozitív érték növekvő késést jelent. Az ábra a szűrésből legfeljebb 12, "
                 "legnagyobb medián változású szakaszt mutat; az összes szakasz és az n a táblázatban szerepel.")
    else:
        st.info("Ehhez a vonalhoz nincs használható órás késési eredmény.")
    kovetesi_nezet(adat, vonal)
    if vonal in ("0975", "1610", "1695"):
        kozos_buszok(adat)


def adatminoseg(adat, fajl):
    st.header("Adatminőség")
    st.subheader("Az indulások értelmezhetősége")
    sorok = []
    for vonal in adat["vonalak"]:
        for minoseg, n in vonal["minoseg"].items():
            sorok.append({"Vonal": VONALAK.get(vonal["vonal_id"], vonal["vonal_id"]),
                          "Minősítés": MINOSEGEK.get(minoseg, minoseg), "Indulások (n)": n})
    if sorok:
        abra(px.bar(pd.DataFrame(sorok), x="Vonal", y="Indulások (n)", color="Minősítés"),
             "A tervezett megállói indulások megoszlása, n = " + str(sum(s["Indulások (n)"] for s in sorok))
             + ". A bizonytalan vagy nem látott indulás önmagában nem bizonyít járatkimaradást.")
    st.write("A megállás és a továbbhaladás együttes nyoma erősebb alátámasztás, mint a továbbhaladás önmagában. "
             "Egyik sem független helyszíni mérés. A menetrendhez párosítás külön ellenőrzés.")
    tabla([{"Vonal": VONALAK.get(s["vonal_id"], s["vonal_id"]),
            "Tervezett indulás": s["tervezett"], "Felhasznált a késéshez": s["keseshez_hasznalt"],
            "Menetrendi párosítás ellenőrzendő": s["ellenorizendo_menetrend"]} for s in adat["vonalak"]])
    reszek = adat.get("kovetesi_reszek", {}).get("naponta", [])
    if reszek:
        st.subheader("Mennyi időből számolható várakozás?")
        tabla([{"Hely és járatcsoport": s["hely"], "Párok (n)": s["parok"],
                "Lefedett idő (óra)": round(s["lefedett_mp"] / 3600, 2),
                "Kimaradt idő (óra)": round(s["kimaradt_mp"] / 3600, 2),
                "Lefedettség (%)": round(100 * s["lefedettseg"], 1)} for s in reszek])
        st.caption("A jó indulások aránya és a várakozásszámítás időbeli lefedettsége két külön mutató. "
                   "Egy bizonytalan köztes indulás miatt a környező időszak nem feltétlenül használható.")

    st.subheader("A lekérések folytonossága")
    minosegfajl = fajl.parent / "adatminoseg.json"
    if not minosegfajl.exists():
        st.info("Ehhez a mentett mintához nincs óránkénti gyűjtési minőségexport. "
                "Az indulási lefedettségből a lekérések folytonossága nem állapítható meg.")
        return
    minoseg = beolvas(str(minosegfajl), minosegfajl.stat().st_mtime_ns)
    sorok = []
    for ora in minoseg:
        ido = datetime.fromisoformat(ora["ora_utc"] + ":00:00+00:00").astimezone(IDOZONA)
        if ido.date().isoformat() != adat["nap"]:
            continue
        for forras, s in ora["forrasok"].items():
            sorok.append({"Óra": ido.strftime("%H:%M %z"), "Forrás": forras,
                          "Próbálkozás": s["probak"], "Sikeres": s["siker"], "Hibás": s["hibak"],
                          "Régi forrásadatú válaszok": s.get("regi_feed"),
                          "Hiányzó forrásidő": s.get("ido_hianyzik"),
                          "Járművek, pillanatkép maximum": s.get("max_jarmu"),
                          "Menetfrissítések, pillanatkép maximum": s.get("max_menetfrissites"),
                          "Leghosszabb sikeres szünet (mp)": s["max_sikeres_res_mp"],
                          "Utolsó siker óta (mp)": s["utolso_siker_ota_mp"]})
    if not sorok:
        st.info("A minőségexportban nincs ehhez a naphoz tartozó óra.")
        return
    forras = st.selectbox("Adatforrás", sorted({s["Forrás"] for s in sorok}))
    tabla_sorok = [s for s in sorok if s["Forrás"] == forras]
    rajz = pd.DataFrame(tabla_sorok)
    abra(px.bar(rajz, x="Óra", y=["Sikeres", "Hibás"], labels={"value": "Lekérések száma", "variable": "Eredmény"}),
         "A kiválasztott forrás lekérési kísérletei óránként, n = "
         + str(sum(s["Próbálkozás"] for s in tabla_sorok)) + ". A sikeres mentés még nem igazolja, hogy a forrás tartalma friss.")
    tabla(tabla_sorok)
    st.caption("A jármű- és menetszám az órán belüli legnagyobb pillanatkép, nem az egyedi járművek napi száma. "
               "A lezárult szünet a későbbi siker órájába kerül; az utolsó siker óta eltelt idő a még tartó hiányt mutatja. "
               "Az üres érték ismeretlent jelent. Ez mentett minőségadat, nem a szerver pillanatnyi állapota.")


def main():
    st.set_page_config(page_title="Késésfigyelő", layout="wide")
    st.title("Késésfigyelő")
    st.write("Menetrendi eltérés, követési idő és adatminőség a mentett BKK-adatokból.")
    fajlok = sorted((MAPPA / "data").glob("elemzes*/indulasok.json"))
    if not fajlok:
        st.info("Még nincs mentett elemzési eredmény. Előbb az elemzőt kell futtatni; az indítást a README írja le.")
        return
    try:
        mintak = {}
        for f in fajlok:
            try:
                a = beolvas(str(f), f.stat().st_mtime_ns)
                if isinstance(a, dict) and a.get("nap") and a.get("vonalak"):
                    mintak[f] = a
            except (OSError, ValueError):
                st.warning("Ez a mentés nem olvasható: " + f.parent.name + ". A többi minta továbbra is használható.")
        if not mintak:
            st.info("A mentett eredményekben még nincs megjeleníthető vonal.")
            return
        fajl = st.sidebar.selectbox("Mentett nap és minta", list(mintak),
                                    format_func=lambda f: mintak[f]["nap"] + " · "
                                    + str(len(mintak[f]["vonalak"])) + " vonal · " + f.parent.name)
        adat = mintak[fajl]
        nezet = st.sidebar.radio("Nézet", ["Áttekintés", "Vonalrészlet", "Adatminőség"])
        st.caption("Vizsgált nap: " + adat["nap"] + ". Időzóna: Europe/Budapest. "
                   "A számok a kiválasztott mentésből származnak; az oldal nem kér új adatot és nem olvas adatbázist.")
        st.info("Egy nap eredménye látható. A kiválasztott vonalak nem képviselik egész Budapestet; "
                "napok közti különbségről több nap feldolgozása után lehet állítani.")
        if adat.get("mintamenetek"):
            st.warning("Ez csak kiválasztott menetek próbája, nem teljes napi vonalminta.")
        if nezet == "Áttekintés":
            attekintes(adat)
        elif nezet == "Vonalrészlet":
            vonalreszlet(adat)
        else:
            adatminoseg(adat, fajl)
    except (OSError, ValueError, KeyError, TypeError):
        st.error("A kiválasztott mentés nem olvasható vagy hiányos. Készítsd el újra az elemzési exportot; "
                 "az eredeti mentett adatokhoz ez az oldal nem nyúl.")
    st.divider()
    st.caption("Adatok forrása: BKK Zrt., CC BY 4.0. "
               "A meghatározások és korlátok a repó MODSZERTAN.md fájljában szerepelnek.")


if __name__ == "__main__":
    main()
