"""Az utasnézet számításainak és képernyőinek hálózat nélküli próbái."""

import json
import re
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from importlib.util import find_spec
from pathlib import Path
from threading import Barrier, Lock
from unittest.mock import patch

WEB_ELERHETO = find_spec("streamlit") is not None and find_spec("plotly") is not None
if WEB_ELERHETO:
    import pandas as pd
    from streamlit.testing.v1 import AppTest

    import app


class TablazatOlvaso(HTMLParser):
    """A felhasználónak küldött HTML celláit olvassa, nem a belső adatszerkezetet."""

    def __init__(self):
        super().__init__()
        self.fejlec = []
        self.sorok = []
        self.sor = []
        self.cella = None
        self.szoveg = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.sor = []
        if tag in ("th", "td"):
            self.cella = tag
            self.szoveg = []

    def handle_data(self, data):
        if self.cella:
            self.szoveg.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cella:
            ertek = "".join(self.szoveg).strip()
            if tag == "th":
                self.fejlec.append(ertek)
            else:
                if ertek == "Nincs adat":
                    ertek = None
                elif re.fullmatch(r"-?\d+(,\d+)?", ertek):
                    ertek = float(ertek.replace(",", ".")) if "," in ertek else int(ertek)
                self.sor.append(ertek)
            self.cella = None
        if tag == "tr" and self.sor:
            self.sorok.append(self.sor)


def tablazatok(oldal):
    eredmeny = []
    for elem in oldal.get("html"):
        if "<table" in elem.proto.body:
            olvaso = TablazatOlvaso()
            olvaso.feed(elem.proto.body)
            eredmeny.append(pd.DataFrame(olvaso.sorok, columns=olvaso.fejlec))
    return eredmeny


def megnyit(mappa):
    from pathlib import Path

    import app

    app.MAPPA = Path(mappa)
    app.main()


def minta(nap, n=80, median=60):
    eloszlas = [[median, n]] if n else []
    return {"nap": nap, "keszult_utc": datetime.now(UTC).isoformat(),
            "modszer": "kozles-haladas-ajto-4", "forras_csoport": "bkk", "pontossagi_rangsor": True,
            "hivatalos_pontossaggal_osszevetheto": False,
            "ido_jelentese": "utolagos_kozles_mozgassal_ellenorizve",
            "idokeret_jelentese": "mozgasos_ellenorzes_nem_pontossagi_hatar",
            "ellenorzes": {"megallasjel_nelkul": n // 2, "elutasitasok": {}, "ajtovizsgalat": {}},
            "vonalak": [{"vonal_id": "0975", "tervezett": 100, "keseshez_hasznalt": n,
                         "hasznalt_menetek": 10 if n else 0, "lefedettseg": n / 100,
                         "median_keses_mp": median if n else None, "p90_keses_mp": median if n else None,
                         "keses_eloszlas": eloszlas, "korai_indulas": 2 if n else 0,
                         "koran_erkezett": 5 if n else 0, "megvarta_indulast": 3 if n else 0,
                         "ellenorizendo_menetrend": 0,
                         "minoseg": {"alatamasztott": n, "nem_lattuk": 100 - n}}],
            "orankent": [{"vonal_id": "0975", "irany": 0, "ora": 8, "n": n,
                          "tervezett": 100, "lefedettseg": n / 100,
                          "median_keses_mp": median if n else None, "keses_eloszlas": eloszlas}],
            "szakaszok": [{"vonal_id": "0975", "irany": 0, "honnan": "A", "hova": "B",
                           "n": 4 if n else 0, "tervezett_parok": 8, "lefedettseg": 0.5 if n else 0,
                           "median_valtozas_mp": -60 if n else None,
                           "valtozas_eloszlas": [[-60, 4]] if n else []}],
            "iranyok": [{"vonal_id": "0975", "irany": 0, "utvonalak": [
                {"elso_megallo_id": "A", "utolso_megallo_id": "B", "tervezett_menetek": 10}]}],
            "megallo_nevek": {"A": "Külső végállomás", "B": "Örs vezér tere", "C": "Rövid út végállomása"},
            "kovetesi_reszek": {"naponta": [], "orankent": []}, "kozos_buszok": []}


def varakozas(nap="2026-10-19", ora=8, irany=0, hely="Bakancsos utca, Örs felé", mp=120, ido=1800):
    return {"hely": hely, "megallo_id": "A", "vonalak": ["0975"],
            "iranyok": [{"vonal_id": "0975", "irany": irany}],
            "kezdet": nap + "T" + str(ora).zfill(2) + ":00:00+02:00",
            "veg": nap + "T" + str(ora + 1).zfill(2) + ":00:00+02:00",
            "hasznalhato": bool(ido), "parok": 5, "par_reszletek": 4,
            "lefedett_mp": ido, "kimaradt_mp": 3600 - ido,
            "lefedettseg": ido / 3600, "varakozas_mp": mp if ido else None,
            "tervezett_varakozas_mp": 90 if ido else None,
            "tobblet_mp": mp - 90 if ido else None}


def idojaras(ora="2026-10-19T06", terseg="Rakosmente"):
    return {"terseg": terseg, "ora_utc": ora, "homerseklet_min": 10, "homerseklet_max": 12,
            "homerseklet_atlag": 11, "szel_atlag": 8, "szel_max": 10, "csapadek_mm": 0,
            "negyedorak": 4, "elvart_negyedorak": 4, "homerseklet_mintak": 4, "szel_mintak": 4}


def hev_minta(nap, n=40):
    adat = minta(nap, n)
    adat.update(modszer="hev-kozles-kontroll-4", forras_csoport="hev", pontossagi_rangsor=False)
    adat["allapot"] = "kesz"
    for mezo in ("vonalak", "orankent", "szakaszok", "iranyok"):
        for sor in adat[mezo]:
            sor["vonal_id"] = "H8"
    adat["megallo_nevek"] = {"A": "Örs vezér tere", "B": "Gödöllő"}
    return adat


def reszletes_minta(nap, maximum=600, hev=False):
    adat = hev_minta(nap,80) if hev else minta(nap)
    vonal = "H8" if hev else "0975"
    n = adat["orankent"][0]["n"]
    for sor in adat["vonalak"] + adat["orankent"]:
        sor["keses_eloszlas"] = [[60,n - 1],[maximum,1]]
    terv = int(datetime.fromisoformat(nap + "T08:20:00+02:00").timestamp())
    maximum_pont = {"menet_id":"m", "szolgalati_nap":nap,"vonal_id":vonal,"irany":0,
                   "sorrend":2,"megallo_id":"B","tervezett":terv,"indulas":terv + maximum,"keses_mp":maximum}
    elso = dict(maximum_pont,sorrend=1,megallo_id="A",tervezett=terv - 600,
                indulas=terv - 540,keses_mp=60)
    adat["keses_reszletek"] = {"orankent":[{"vonal_id":vonal,"irany":0,"ora":8,"menet_db":4,
                                          "maximum":maximum_pont,"maximum_db":1}],
                              "szelso_utak":[{"vonal_id":vonal,"irany":0,"maximum":maximum_pont,
                                              "megallok":[elso,maximum_pont]}]}
    return adat


@unittest.skipUnless(WEB_ELERHETO, "A web függőségei is szükségesek.")
class SzamitasTeszt(unittest.TestCase):
    def test_napok_iranyok_es_mintadarabok_az_oras_sorokban_kulon_maradnak(self):
        a,b = reszletes_minta("2026-10-18"), reszletes_minta("2026-10-19",900)
        b["orankent"].append(dict(b["orankent"][0],irany=1,median_keses_mp=120))
        sorok = app.napi_oras_sorok([b,a],"0975")
        self.assertEqual([(s["nap"],s["irany"]) for s in sorok],
                         [("2026-10-18",0),("2026-10-19",0),("2026-10-19",1)])
        self.assertEqual([s["menet_db"] for s in sorok], [4,4,None])
        self.assertEqual(len(app.napi_oras_sorok([a,b],"0975",0)),2)

    def test_hev_oras_minimum_kulon_vonatokat_ker_es_a_hiany_nem_nulla(self):
        sor = {"n":10,"lefedettseg":0.5,"median_keses_mp":0,"menet_db":2}
        self.assertTrue(app.ora_hasznalhato(sor,True))
        for hibas in (dict(sor,menet_db=1),dict(sor,menet_db=None),dict(sor,n=9),
                      dict(sor,lefedettseg=0.49),dict(sor,median_keses_mp=None)):
            self.assertFalse(app.ora_hasznalhato(hibas,True))
        self.assertFalse(app.ora_hasznalhato(sor))
        self.assertTrue(app.ora_hasznalhato(dict(sor,n=30)))

    def test_maximum_a_kijelolt_napot_es_iranyt_koveti(self):
        a,b = reszletes_minta("2026-10-18",600),reszletes_minta("2026-10-19",900)
        self.assertEqual(app.keses_maximuma([a,b],"0975",0)["mp"],900)
        self.assertEqual(app.keses_maximuma([a],"0975",0)["mp"],600)
        self.assertIsNone(app.keses_maximuma([a,b],"0975",1))
        del b["keses_reszletek"]
        leg = app.keses_maximuma([b],"0975",0)
        self.assertEqual(leg["ora"],8)
        self.assertIsNone(leg["reszlet"])

    def test_uj_idoertelmezes_nem_jelenik_meg_regi_meresi_hatarokkal(self):
        adat = minta("2026-10-19")
        app.minta_ellenorzese(adat)
        app.minta_ellenorzese(hev_minta("2026-10-19"))
        with self.assertRaises(ValueError):
            app.minta_ellenorzese(dict(adat, modszer="helyzet-idokeret-1"))
        for kulcs, ertek in (("idokeret_jelentese", "pontossagi_hatar"), ("forras_csoport", "hev"),
                             ("pontossagi_rangsor", False), ("hivatalos_pontossaggal_osszevetheto", True)):
            with self.subTest(kulcs=kulcs), self.assertRaises(ValueError):
                app.minta_ellenorzese(dict(adat, **{kulcs: ertek}))

    def test_oras_mintaminimum_nem_a_keses_nagysagatol_fugg(self):
        alap = {"n": 30, "lefedettseg": 0.5, "median_keses_mp": 0}
        sorok = [alap, {**alap, "median_keses_mp": 1800},
                 {**alap, "n": 29}, {**alap, "lefedettseg": 0.49},
                 {**alap, "median_keses_mp": None}, {**alap, "lefedettseg": None}]
        self.assertEqual(app.osszevetheto_orak(sorok), sorok[:2])
        self.assertEqual(len(sorok), 6)

    def test_maximum_csak_teljes_eloszlasbol_es_nem_abszolut_eltteres(self):
        self.assertEqual(app.legnagyobb_keses({"n": 3, "keses_eloszlas": [[-900, 1], [10, 1], [20, 1]]}), 20)
        self.assertEqual(app.legnagyobb_keses({"n": 1, "keses_eloszlas": [[-10, 1]]}), 0)
        self.assertIsNone(app.legnagyobb_keses({"n": 4, "keses_eloszlas": [[20, 3]]}))
        self.assertIsNone(app.legnagyobb_keses({"n": 0, "keses_eloszlas": []}))
        orankent = app.osszevon([minta("2026-10-19")["orankent"][0]], ("vonal_id",))[0]
        self.assertEqual(app.legnagyobb_keses(orankent), 60)
        self.assertEqual(app.kuszob_arany(orankent, 60), 1)

    def test_azonos_oras_kapcsolat_nem_keveri_a_napszakokat(self):
        sorok = [{"nap": nap, "ora": ora, "homerseklet_atlag": x + kulonbseg,
                  "median_keses_mp": y + kulonbseg * 10}
                 for ora, x, y in ((6, 2, 500), (12, 20, 300), (18, 12, 400))
                 for nap, kulonbseg in (("2026-10-17", 0), ("2026-10-18", 2))]
        self.assertLess(app.korrelacio([s["homerseklet_atlag"] for s in sorok],
                                       [s["median_keses_mp"] for s in sorok]), 0)
        parok = app.azonos_oras_parok(sorok, "homerseklet_atlag")
        self.assertEqual(len(parok), 3)
        self.assertEqual([s["kulonbseg_mp"] for s in parok], [20, 20, 20])
        self.assertEqual(app.azonos_oras_parok(sorok[:1], "homerseklet_atlag"), [])
        self.assertIsNone(app.korrelacio([1, 1, 1], [1, 2, 3]))

    def test_homersekletet_nem_zarja_ki_a_hianyos_csapadek(self):
        sor = {**idojaras(), "teljes": False, "negyedorak": 3, "csapadek_mm": None}
        self.assertTrue(app.idojaras_hasznalhato(sor, "homerseklet_atlag"))
        self.assertFalse(app.idojaras_hasznalhato(sor, "csapadek_mm"))
        self.assertFalse(app.idojaras_hasznalhato(sor))

    def test_peronnevek_osszevonasa_menetek_duplazasa_nelkul(self):
        adat = minta("2026-10-19")
        adat["megallo_nevek"].update(A="Cinkota", A2="Cinkota", B="Gödöllő", B2="Gödöllő")
        adat["utvonal_reszletek"] = [
            {"vonal_id": "H8", "irany": 0, "megallo_idk": ["A", "B"],
             "menetek": [{"menet_id": "t1", "szolgalati_nap": "2026-10-19"}]},
            {"vonal_id": "H8", "irany": 0, "megallo_idk": ["A2", "B2"],
             "menetek": [{"menet_id": "t1", "szolgalati_nap": "2026-10-19"},
                         {"menet_id": "t2", "szolgalati_nap": "2026-10-19"}]}]
        self.assertEqual(app.utvonal_valtozatok([adat, deepcopy(adat)], "H8", 0),
                         [{"megallok": ["Cinkota", "Gödöllő"], "utak": 2}])

    def test_kuszob_ketoldali_beleertett_hatar_es_nem_medianokbol_szamol(self):
        sorok = [{"vonal_id": "0975", "keseshez_hasznalt": 4,
                  "keses_eloszlas": [[-61, 1], [-60, 1], [60, 1], [61, 1]]},
                 {"vonal_id": "0975", "keseshez_hasznalt": 6, "keses_eloszlas": [[0, 6]]}]
        sor = app.osszevon(sorok, ("vonal_id",))[0]
        self.assertEqual(app.kuszob_arany(sor, 60), 0.8)
        self.assertEqual(app.kuszob_arany(sor, 120), 1)
        self.assertIsNone(app.kuszob_arany({"n": 0, "keses_eloszlas": []}, 60))
        self.assertIsNone(app.kuszob_arany({"n": 2, "keses_eloszlas": [[0, 1]]}, 60))

    def test_menetek_napvaltasnal_egyszer_es_forrasjelzok_egyesulnek(self):
        elso = {"menet_lathatosag": [{"vonal_id": "0975", "menetek": [
            {"menet_id": "a", "szolgalati_nap": "2026-10-18", "pozicio": True, "menetfrissites": False},
            {"menet_id": "b", "szolgalati_nap": "2026-10-18", "pozicio": False, "menetfrissites": False}]}]}
        masodik = deepcopy(elso)
        masodik["menet_lathatosag"][0]["menetek"][0].update(pozicio=False, menetfrissites=True)
        masodik["menet_lathatosag"][0]["menetek"].append(
            {"menet_id": "a", "szolgalati_nap": "2026-10-19", "pozicio": True, "menetfrissites": False})
        sor = app.menet_osszesites([elso, masodik])[0]
        self.assertEqual(sor, {"vonal_id": "0975", "tervezett_menetek": 3, "latott_menetek": 2,
                              "nem_latott_menetek": 1, "pozicioval": 2, "menetfrissitessel": 1})

    def test_idojaras_hianyos_oraja_nem_nullacsapadek_es_nem_kapcsolodik(self):
        adat = minta("2026-10-19")
        rossz = idojaras()
        rossz.update(szel_mintak=3, szel_atlag=100)
        adat["idojaras"] = [rossz, idojaras("2026-10-19T07")]
        adat["orankent"].append({**adat["orankent"][0], "ora": 9, "n": 20, "keses_eloszlas": [[300, 20]]})
        orak = app.idojaras_orak([adat], "Rakosmente")
        self.assertEqual(len(orak), 24)
        self.assertEqual(sum(s["teljes"] for s in orak), 1)
        self.assertNotIn("csapadek_mm", orak[0])
        parok = app.idojaras_kapcsolas([adat], orak, "0975")
        self.assertEqual(len(parok), 1)
        self.assertEqual((parok[0]["ora"], parok[0]["n"], parok[0]["median_keses_mp"]), (9, 20, 300))

    def test_idojaras_ketiranyt_egyszer_von_ossze(self):
        adat = minta("2026-10-19", 9, 0)
        adat["idojaras"] = [idojaras()]
        adat["orankent"].append({**adat["orankent"][0], "irany": 1, "n": 1, "keses_eloszlas": [[600, 1]]})
        parok = app.idojaras_kapcsolas([adat], app.idojaras_orak([adat], "Rakosmente"), "0975")
        self.assertEqual(len(parok), 1)
        self.assertEqual(parok[0]["n"], 10)
        self.assertEqual(parok[0]["median_keses_mp"], 0)

    def test_idojaras_tavaszi_23_es_oszi_25_ora_dupla_keses_nelkul(self):
        self.assertEqual(len(app.idojaras_orak([minta("2026-03-29")], "Rakosmente")), 23)
        adat = minta("2026-10-25")
        adat["idojaras"] = [idojaras("2026-10-25T00"), idojaras("2026-10-25T01")]
        adat["orankent"][0]["ora"] = 2
        orak = app.idojaras_orak([adat], "Rakosmente")
        self.assertEqual(len(orak), 25)
        self.assertEqual(sum(s["teljes"] for s in orak), 2)
        self.assertEqual(app.idojaras_kapcsolas([adat], orak, "0975"), [])

    def test_hev_mas_nap_vagy_mas_vonal_eseten_nem_kerul_be(self):
        adat = minta("2026-10-19")
        adat["hev"] = hev_minta("2026-10-19")
        self.assertEqual(len(app.hev_adatok([adat])), 1)
        adat["hev"]["nap"] = "2026-10-18"
        self.assertEqual(app.hev_adatok([adat]), [])
        adat["hev"]["nap"] = "2026-10-19"
        adat["hev"]["vonalak"][0]["vonal_id"] = "OPH8"
        self.assertEqual(app.hev_adatok([adat]), [])

    def test_html_cella_szoveg_es_hianyzo_ertek_biztonsagos(self):
        html = app.tablazat_html([{"Megálló": "<script>rossz()</script>", "Eltérés": None}], "villamos")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<td>Nincs adat</td>", html)
        self.assertNotIn("<td>None</td>", html)
        self.assertIn("role=\"region\"", html)
        self.assertIn("<th>Megálló</th>", html)

    def test_gyakorisagi_kvantilis_interpolacio_es_ures_minta(self):
        eloszlas = [[600, 1], [-60, 1], [60, 8]]
        self.assertEqual(app.kvantilis(eloszlas, 0), -60)
        self.assertEqual(app.kvantilis(eloszlas, 0.5), 60)
        self.assertAlmostEqual(app.kvantilis(eloszlas, 0.9), 114)
        self.assertEqual(app.kvantilis(eloszlas, 1), 600)
        self.assertIsNone(app.kvantilis([], 0.5))

    def test_osszevont_median_nem_napi_medianok_atlaga(self):
        a = minta("2026-10-17", 90, 0)["vonalak"][0]
        b = minta("2026-10-18", 10, 600)["vonalak"][0]
        a["tervezett"], b["tervezett"] = 100, 400
        sor = app.osszevon([a, b], ("vonal_id",))[0]
        self.assertEqual(sor["median_keses_mp"], 0)
        self.assertAlmostEqual(sor["p90_keses_mp"], 60)
        self.assertEqual(sor["keseshez_hasznalt"], 100)
        self.assertEqual(sor["tervezett"], 500)
        self.assertEqual(sor["lefedettseg"], 0.2)

    def test_osszevonas_iranyonkent_kulon_marad(self):
        a = minta("2026-10-17", 80, -60)["orankent"][0]
        b = {**a, "irany": 1, "keses_eloszlas": [[300, 80]], "median_keses_mp": 300}
        sorok = app.osszevon([a, b], ("vonal_id", "irany"))
        self.assertEqual([(s["irany"], s["median_keses_mp"]) for s in sorok], [(0, -60), (1, 300)])

    def test_regi_exportbol_nincs_kitalalt_tobbnapos_median(self):
        a = minta("2026-10-17")["vonalak"][0]
        b = minta("2026-10-18", 20, 600)["vonalak"][0]
        del a["keses_eloszlas"]
        self.assertEqual(app.osszevon([a], ("vonal_id",))[0]["median_keses_mp"], 60)
        sor = app.osszevon([a, b], ("vonal_id",))[0]
        self.assertIsNone(sor["median_keses_mp"])
        self.assertIsNone(sor["p90_keses_mp"])
        self.assertEqual(sor["keseshez_hasznalt"], 100)

    def test_ures_szakasz_nem_nullavaltozas_es_a_nevezo_osszeadodik(self):
        a = minta("2026-10-17")["szakaszok"][0]
        b = minta("2026-10-18", 0)["szakaszok"][0]
        sor = app.osszevon([a, b], ("honnan", "hova"), True)[0]
        self.assertEqual(sor["n"], 4)
        self.assertEqual(sor["tervezett_parok"], 16)
        self.assertEqual(sor["lefedettseg"], 0.25)
        self.assertEqual(sor["median_valtozas_mp"], -60)
        self.assertIsNone(app.osszevon([b], ("honnan", "hova"), True)[0]["median_valtozas_mp"])

    def test_irany_celallomas_es_roviditett_utak(self):
        adat = minta("2026-10-17")
        adat["iranyok"][0]["utvonalak"][0]["tervezett_menetek"] = 90
        adat["iranyok"][0]["utvonalak"].append(
            {"elso_megallo_id": "A", "utolso_megallo_id": "C", "tervezett_menetek": 5})
        nev = app.irany_neve([adat], "0975", 0)
        self.assertIn("Örs vezér tere felé", nev)
        self.assertNotIn("rövidített", nev)
        self.assertNotIn("0", nev)
        adat["iranyok"][0]["utvonalak"][1]["tervezett_menetek"] = 40
        self.assertIn("Örs vezér tere", app.irany_neve([adat], "0975", 0))

    def test_hianyzo_iranynevbol_nem_lesz_kitalalt_cel(self):
        adat = minta("2026-10-17")
        adat.pop("iranyok")
        self.assertIn("nincs", app.irany_neve([adat], "0975", 0))
        self.assertEqual(app.irany_utvonalak([adat], "0975", 0), {})

    def test_varakozas_idotartammal_sulyoz_es_reszleteket_szamol(self):
        a, b = varakozas(mp=120, ido=900), varakozas(ora=9, mp=360, ido=2700)
        a["parok"], b["parok"] = 99, 99
        a["par_reszletek"], b["par_reszletek"] = 2, 3
        sor = app.varakozas_osszesites([a, b])
        self.assertEqual(sor["varakozas_mp"], 300)
        self.assertEqual(sor["tervezett_varakozas_mp"], 90)
        self.assertEqual(sor["tobblet_mp"], 210)
        self.assertEqual(sor["lefedett_mp"], 3600)
        self.assertEqual(sor["teljes_mp"], 7200)
        self.assertEqual(sor["reszletek"], 5)
        self.assertEqual(sor["orak"], 2)

    def test_hianyzo_varakozasi_idoszak_nem_nullavarakozas(self):
        for sorok in ([], [varakozas(ido=0)]):
            with self.subTest(sorok=sorok):
                adat = app.varakozas_osszesites(sorok)
                self.assertIsNone(adat["varakozas_mp"])
                self.assertIsNone(adat["tobblet_mp"])
                self.assertEqual(adat["lefedett_mp"], 0)

    def test_pozitiv_lefedettseg_melletti_hianyos_ertek_nem_csokkenti_az_atlagot(self):
        hibas = varakozas(ora=9)
        hibas["varakozas_mp"] = None
        with self.assertRaises(ValueError):
            app.varakozas_osszesites([varakozas(), hibas])


@unittest.skipUnless(WEB_ELERHETO, "A web függőségei is szükségesek.")
class WebTeszt(unittest.TestCase):
    def setUp(self):
        self.atmeneti = tempfile.TemporaryDirectory()
        self.addCleanup(self.atmeneti.cleanup)
        self.mappa = Path(self.atmeneti.name)
        self.addCleanup(setattr, app, "MAPPA", app.MAPPA)

    def ment(self, nev, adat):
        mappa = self.mappa / "data" / ("elemzes-" + nev)
        mappa.mkdir(parents=True)
        (mappa / "indulasok.json").write_text(json.dumps(adat), encoding="utf-8")
        return mappa

    def megjelenit(self, parameterek=None):
        oldal = AppTest.from_function(megnyit, args=(str(self.mappa),), default_timeout=15)
        if parameterek:
            oldal.query_params.update(parameterek)
        return oldal.run()

    def rendben(self, oldal):
        self.assertFalse(oldal.exception)
        self.assertFalse(oldal.error)
        self.assertFalse(oldal.get("expander"))
        self.assertNotIn("·", self.szoveg(oldal))

    def szoveg(self, oldal):
        return "\n".join(s.value for nev in ("markdown", "caption", "info", "warning") for s in oldal.get(nev))

    def darab(self, oldal):
        return oldal.metric[0].value

    def nezet(self, oldal, index):
        oldal.sidebar.radio[0].set_value(oldal.sidebar.radio[0].options[index]).run()
        self.rendben(oldal)

    def allapot(self, **plusz):
        adat = {"utolso_probalkozas_utc": datetime.now(UTC).isoformat(),
                "allapot": "sikeres", "nap": "2026-10-19", **plusz}
        (self.mappa / ".napi-allapot.json").write_text(json.dumps(adat), encoding="utf-8")

    def test_parhuzamos_keresek_sorban_dolgoznak_es_mind_elkeszulnek(self):
        inditas, zar = Barrier(4), Lock()
        aktiv, maximum, kesz = 0, 0, []

        def megjelenites():
            nonlocal aktiv, maximum
            with zar:
                aktiv += 1
                maximum = max(maximum, aktiv)
            time.sleep(0.03)
            with zar:
                aktiv -= 1
                kesz.append(True)

        def kereses():
            inditas.wait(timeout=5)
            app.main()

        with patch.object(app, "oldal", side_effect=megjelenites), ThreadPoolExecutor(max_workers=4) as szalak:
            list(szalak.map(lambda _: kereses(), range(4)))
        self.assertEqual(maximum, 1)
        self.assertEqual(len(kesz), 4)

    def test_a_kozos_mentest_egyik_latogato_sem_irhatja_at(self):
        mappa = self.ment("kozos", minta("2026-10-19"))
        fajl = mappa / "indulasok.json"
        elso = app.beolvas(str(fajl), fajl.stat().st_mtime_ns)
        masodik = app.beolvas(str(fajl), fajl.stat().st_mtime_ns)
        self.assertIs(elso, masodik)
        with self.assertRaises(TypeError):
            elso["nap"] = "2026-10-20"
        with self.assertRaises(TypeError):
            elso["vonalak"][0]["keses_eloszlas"][0][0] = 999
        self.assertEqual(masodik["nap"], "2026-10-19")
        self.assertEqual(masodik["vonalak"][0]["keses_eloszlas"][0][0], 60)

    def test_alapbol_minden_nap_es_uj_nap_automatikusan_bekerul(self):
        self.ment("szombat", minta("2026-10-17", 90, 0))
        oldal = self.megjelenit()
        self.assertEqual(self.darab(oldal), "90")
        self.ment("vasarnap", minta("2026-10-18", 10, 600))
        oldal.run()
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "100")
        self.assertIn("vasárnap", self.szoveg(oldal))
        self.assertIn("Az új napok automatikusan bekerülnek", self.szoveg(oldal))

    def test_kezi_napvalasztas_uj_nap_mellett_is_megmarad(self):
        self.ment("szombat", minta("2026-10-17", 30))
        self.ment("vasarnap", minta("2026-10-18", 70))
        oldal = self.megjelenit()
        oldal.sidebar.radio(key="idoszak_mod").set_value("Napok kiválasztása").run()
        oldal.sidebar.multiselect[0].set_value(["2026-10-17"]).run()
        self.ment("hetfo", minta("2026-10-19", 40))
        oldal.run()
        self.rendben(oldal)
        self.assertEqual(oldal.sidebar.multiselect[0].value, ["2026-10-17"])
        self.assertEqual(self.darab(oldal), "30")
        oldal.sidebar.radio(key="idoszak_mod").set_value("Minden rendelkezésre álló nap").run()
        self.assertEqual(self.darab(oldal), "140")

    def test_egy_nap_egyetlen_teljes_ujabb_valtozata_szamit(self):
        regi, uj, proba = minta("2026-10-19", 10), minta("2026-10-19", 80), minta("2026-10-19", 5)
        regi["keszult_utc"], uj["keszult_utc"] = "2026-10-20T07:00:00+00:00", "2026-10-20T08:00:00+00:00"
        proba["mintamenetek"] = ["proba"]
        for nev, adat in (("regi", regi), ("uj", uj), ("proba", proba)):
            self.ment(nev, adat)
        # A korábbi változatok teljes tartalma nem kerül a megjelenítés gyorsítótárába.
        with patch.object(app, "beolvas", wraps=app.beolvas) as olvas:
            oldal = self.megjelenit()
            self.assertEqual([Path(h.args[0]).parent.name for h in olvas.call_args_list], ["elemzes-uj"])
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "80")
        self.assertNotIn("próbamintát", self.szoveg(oldal))
        fajl = self.mappa / "data" / "elemzes-uj" / "indulasok.json"
        fejlec = app.mentes_fejlece(str(fajl), fajl.stat().st_mtime_ns)
        self.assertNotIn("orankent", fejlec)
        self.assertEqual(fejlec["vonalak"], ["0975"])
        with patch.object(app, "beolvas", wraps=app.beolvas) as olvas:
            oldal.run()
            self.assertEqual([Path(h.args[0]).parent.name for h in olvas.call_args_list], ["elemzes-uj"])
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "80")

    def test_hibas_export_mellett_a_jo_minden_oldalon_hasznalhato(self):
        self.ment("jo", minta("2026-10-19"))
        hibas = self.ment("hibas", {})
        (hibas / "indulasok.json").write_text("{", encoding="utf-8")
        self.ment("hianyos", {"nap": "2026-10-20", "vonalak": [{"vonal_id": "0975"}]})
        oldal = self.megjelenit()
        self.assertEqual(self.darab(oldal), "80")
        for i in range(4):
            self.nezet(oldal, i)
            self.assertGreaterEqual(len(oldal.warning), 2)

    def test_frissites_a_szoveges_eredmenyt_is_modositja(self):
        masik = dict(minta("2026-10-19", 20, 300)["vonalak"][0], vonal_id="1610")
        adat = minta("2026-10-19", 80)
        adat["vonalak"].append(masik)
        hely = self.ment("jo", adat)
        oldal = self.megjelenit()
        self.assertIn("97E busznál a legnagyobb (100,0%)", self.szoveg(oldal))
        elso = list(oldal.session_state["mentesek_allapota"])
        uj = minta("2026-10-19", 40, 300)
        uj["vonalak"][0].update(koran_erkezett=20, megvarta_indulast=15)
        uj["vonalak"].append(masik)
        (hely / "indulasok.json").write_text(json.dumps(uj), encoding="utf-8")
        oldal.run()
        self.rendben(oldal)
        self.assertNotEqual(elso, oldal.session_state["mentesek_allapota"])
        self.assertEqual(self.darab(oldal), "60")
        self.assertIn("mind a 2 járatnál ugyanannyi, 0,0%", self.szoveg(oldal))
        self.assertNotIn("97E busznál a legnagyobb", self.szoveg(oldal))
        masodik = list(oldal.session_state["mentesek_allapota"])
        oldal.run()
        self.assertEqual(masodik, oldal.session_state["mentesek_allapota"])

    def test_csak_valos_adatresnel_jelenik_meg_a_szakadas_magyarazata(self):
        adat = reszletes_minta("2026-10-19", 900)
        hely = self.ment("jo", adat)
        oldal = self.megjelenit()
        self.nezet(oldal, 1)
        mondat = "(A hiányzó vagy elutasított közlésnél megszakadhat a vonal.)"
        self.assertNotIn(mondat, self.szoveg(oldal))
        self.assertIn("legnagyobb növekedés", self.szoveg(oldal))
        pontok = adat["keses_reszletek"]["szelso_utak"][0]["megallok"]
        pontok.insert(1, dict(pontok[0], megallo_id="hiany", indulas=None))
        (hely / "indulasok.json").write_text(json.dumps(adat), encoding="utf-8")
        oldal.run()
        self.rendben(oldal)
        self.assertIn(mondat, self.szoveg(oldal))
        self.assertNotIn("legnagyobb növekedés", self.szoveg(oldal))

    def test_elso_export_elott_is_mukodik_a_frissites(self):
        oldal = self.megjelenit()
        self.assertIn("Még nincs", self.szoveg(oldal))
        self.ment("elso", minta("2026-10-19"))
        oldal.run()
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "80")

    def test_ures_napvalasztas_nem_mutat_nullas_eredmenyt(self):
        self.ment("jo", minta("2026-10-19"))
        oldal = self.megjelenit()
        oldal.sidebar.radio(key="idoszak_mod").set_value("Napok kiválasztása").run()
        oldal.sidebar.multiselect[0].set_value([]).run()
        self.rendben(oldal)
        self.assertIn("legalább egy nap", self.szoveg(oldal))
        self.assertFalse(oldal.metric)

    def test_felso_oldal_es_napok_urlbol_minden_nezetben_visszaallnak(self):
        for nap,n in (("2026-10-17",30),("2026-10-18",50),("2026-10-19",70)):
            self.ment(nap,minta(nap,n))
        for kod,nev in app.NEZETEK.items():
            with self.subTest(nezet=nev):
                oldal = self.megjelenit({"nezet":kod,"napok":"2026-10-19,2026-10-17"})
                self.rendben(oldal)
                self.assertEqual(oldal.sidebar.radio(key="oldal_nezet").value,nev)
                self.assertEqual(oldal.sidebar.radio(key="idoszak_mod").value,"Napok kiválasztása")
                self.assertEqual(oldal.sidebar.multiselect[0].value,["2026-10-17","2026-10-19"])
                if kod == "attekintes":
                    self.assertEqual(self.darab(oldal),"100")

    def test_valtas_utan_az_url_uj_munkamenetben_is_ugyanazt_mutatja(self):
        self.ment("szombat",minta("2026-10-17",30))
        self.ment("hetfo",minta("2026-10-19",70))
        oldal = self.megjelenit()
        self.nezet(oldal,1)
        oldal.sidebar.radio(key="idoszak_mod").set_value("Napok kiválasztása").run()
        oldal.sidebar.multiselect[0].set_value(["2026-10-17"]).run()
        uj = self.megjelenit(dict(oldal.query_params))
        self.rendben(uj)
        self.assertEqual(uj.sidebar.radio(key="oldal_nezet").value,"Járatonként")
        self.assertEqual(uj.sidebar.multiselect[0].value,["2026-10-17"])
        self.assertEqual([m.value for m in uj.metric],[m.value for m in oldal.metric])

    def test_hibas_urlparameterek_nem_rajzolnak_kitalalt_eredmenyt(self):
        self.ment("szombat",minta("2026-10-17",30))
        self.ment("hetfo",minta("2026-10-19",70))
        oldal = self.megjelenit({"nezet":"nemletezik","napok":"2026-13-99,hianyzo"})
        self.rendben(oldal)
        self.assertEqual(oldal.sidebar.radio(key="oldal_nezet").value,"Áttekintés")
        self.assertEqual(oldal.sidebar.radio(key="idoszak_mod").value,"Minden rendelkezésre álló nap")
        self.assertEqual(self.darab(oldal),"100")
        oldal = self.megjelenit({"nezet":"attekintes","napok":"2026-10-17,2026-10-17,2026-10-18,hibas"})
        self.rendben(oldal)
        self.assertEqual(oldal.sidebar.multiselect[0].value,["2026-10-17"])
        self.assertEqual(self.darab(oldal),"30")

    def test_ures_napkijeloles_is_visszanyithato_urlbol(self):
        self.ment("jo",minta("2026-10-19"))
        oldal = self.megjelenit({"nezet":"hev","napok":""})
        self.rendben(oldal)
        self.assertEqual(oldal.sidebar.radio(key="oldal_nezet").value,"HÉV")
        self.assertEqual(oldal.sidebar.multiselect[0].value,[])
        self.assertIn("legalább egy nap",self.szoveg(oldal))
        self.assertFalse(oldal.metric)
        uj = self.megjelenit(dict(oldal.query_params))
        self.rendben(uj)
        self.assertEqual(uj.sidebar.multiselect[0].value,[])
        self.assertFalse(uj.metric)

    def test_sikertelen_regi_frissites_lathato_es_nyers_hiba_nem_jelenik_meg(self):
        self.ment("jo", minta("2026-10-19"))
        self.allapot(allapot="hiba", hiba_kod="atadas", hiba="Nyers nem kiírható tartalom",
                     utolso_probalkozas_utc=(datetime.now(UTC) - timedelta(hours=40)).isoformat())
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertIn("eredmény átvitele nem sikerült", self.szoveg(oldal))
        self.assertIn("36 órája", self.szoveg(oldal))
        self.assertNotIn("Nyers nem kiírható", self.szoveg(oldal))
        self.allapot(allapot="hiba", hiba_kod="Nyers nem kiírható tartalom")
        oldal.run()
        self.assertNotIn("Nyers nem kiírható", self.szoveg(oldal))

    def test_sikeres_masolas_nem_takarja_el_a_szerver_hibajat(self):
        self.ment("jo", minta("2026-10-19"))
        self.allapot(forras_allapot={"allapot": "hiba", "hiba_kod": "menetrend",
                     "utolso_probalkozas_utc": (datetime.now(UTC) - timedelta(hours=40)).isoformat()})
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertIn("VPS legutóbbi napi feldolgozása sikertelen", self.szoveg(oldal))
        self.assertIn("menetrendváltozatokat ellenőrizni kell", self.szoveg(oldal))
        self.assertIn("VPS feldolgozásáról több mint 36 órás", self.szoveg(oldal))

    def test_hev_szazalekok_az_adattal_frissulnek(self):
        adat = minta("2026-10-19")
        adat["hev"] = hev_minta("2026-10-19", 40)
        adat["hev"]["vonalak"][0]["keses_eloszlas"] = [[30, 10], [100, 20], [360, 10]]
        adat["hev"]["vonalak"][0]["idokeretek"] = [[20, 40, 10], [80, 120, 20], [350, 370, 10]]
        hely = self.ment("jo", adat)
        oldal = self.megjelenit()
        self.nezet(oldal, 4)
        self.rendben(oldal)
        self.assertIn("25,0%-a legfeljebb", self.szoveg(oldal))
        adat["hev"]["vonalak"][0]["keses_eloszlas"] = [[30, 20], [100, 5], [360, 15]]
        adat["hev"]["vonalak"][0]["idokeretek"] = [[20, 40, 20], [80, 120, 5], [350, 370, 15]]
        (hely / "indulasok.json").write_text(json.dumps(adat), encoding="utf-8")
        oldal.run()
        self.assertIn("50,0%-a legfeljebb", self.szoveg(oldal))
        self.assertNotIn("99,59", self.szoveg(oldal))
        self.assertNotIn("Jellemző menetidő", self.szoveg(oldal))

    def test_uj_oras_abra_es_maximum_a_napvalasztassal_egyutt_frissul(self):
        self.ment("vasarnap",reszletes_minta("2026-10-18",600))
        self.ment("hetfo",reszletes_minta("2026-10-19",900))
        oldal = self.megjelenit()
        self.nezet(oldal,1)
        self.assertIn("15 perc 0 mp volt",self.szoveg(oldal))
        self.assertIn("08:35:00",self.szoveg(oldal))
        oldal.sidebar.radio(key="idoszak_mod").set_value("Napok kiválasztása").run()
        oldal.sidebar.multiselect[0].set_value(["2026-10-18"]).run()
        self.rendben(oldal)
        self.assertIn("10 perc 0 mp volt",self.szoveg(oldal))
        self.assertIn("08:30:00",self.szoveg(oldal))
        self.assertNotIn("08:35:00",self.szoveg(oldal))
        kepek = [json.loads(x.proto.spec) for x in oldal.get("plotly_chart")]
        heat = next(k for k in kepek if k["data"][0]["type"]=="heatmap")
        self.assertEqual(heat["data"][0]["y"],["október 18., vasárnap"])
        pelda = next(k for k in kepek if k["data"][0].get("name")=="Menetrend")
        self.assertEqual(pelda["data"][0]["y"],[0.0,10.0])
        self.assertEqual(pelda["data"][1]["y"],[1.0,20.0])
        self.assertFalse(pelda["data"][1]["connectgaps"])

    def test_hev_uj_abrak_a_ket_iranyt_eloszlast_es_maximumot_megtartjak(self):
        adat = minta("2026-10-19")
        adat["hev"] = reszletes_minta("2026-10-19",900,True)
        self.ment("jo",adat)
        oldal = self.megjelenit()
        self.nezet(oldal,4)
        self.assertIn("15 perc 0 mp volt",self.szoveg(oldal))
        self.assertIn("Öt percnél nagyobb",str([json.loads(x.proto.spec) for x in oldal.get("plotly_chart")]))
        self.assertIn("08:35:00",self.szoveg(oldal))
        self.assertGreaterEqual(len(oldal.get("plotly_chart")),3)

    def test_hev_hiba_es_ures_minta_nem_takarja_el_a_tobbi_jaratot(self):
        adat = minta("2026-10-19")
        adat["hev"] = {"allapot": "hiba", "hiba_kod": "adatbazis", "hiba": "Tilos nyers tartalom"}
        hely = self.ment("jo", adat)
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "80")
        self.assertNotIn("Tilos nyers tartalom", self.szoveg(oldal))
        adat["hev"] = hev_minta("2026-10-19", 0)
        (hely / "indulasok.json").write_text(json.dumps(adat), encoding="utf-8")
        self.nezet(oldal, 4)
        self.rendben(oldal)
        self.assertIn("nincs elegendő adat", self.szoveg(oldal))

    def test_regi_nap_nem_kerul_az_uj_modszeru_osszesitesbe(self):
        regi = minta("2026-10-18", 90)
        regi["modszer"] = "helyzet-idokeret-1"
        self.ment("regi", regi)
        self.ment("uj", minta("2026-10-19", 40))
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "40")
        self.assertIn("újraszámolásig nem szerepelnek", self.szoveg(oldal))
        oldal.sidebar.radio(key="idoszak_mod").set_value("Napok kiválasztása").run()
        self.assertEqual(oldal.sidebar.multiselect[0].value, ["2026-10-19"])

    def test_jeloles_elotti_mentes_nem_hibas_es_nem_duplazza_az_uj_napot(self):
        regi = minta("2026-10-19", 90)
        for kulcs in ("modszer", "forras_csoport", "ido_jelentese", "idokeret_jelentese",
                      "pontossagi_rangsor", "hivatalos_pontossaggal_osszevetheto"):
            regi.pop(kulcs)
        regi.update(napi_sema=1, menetrend_id=1)
        self.ment("regi", regi)
        self.ment("uj", minta("2026-10-19", 40))
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "40")
        self.assertFalse(oldal.warning)
        self.assertNotIn("újraszámolásig", self.szoveg(oldal))

    def test_uj_hianyos_es_ismeretlen_modszeru_mentes_tovabbra_is_hibat_jelez(self):
        self.ment("jo", minta("2026-10-19", 40))
        hibas = minta("2026-10-18")
        hibas.pop("modszer")
        hibas.update(napi_sema=1, menetrend_id=1)
        self.ment("hianyos", hibas)
        self.ment("ismeretlen", dict(minta("2026-10-18"), modszer="ismeretlen-1"))
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "40")
        self.assertEqual(len(oldal.warning), 2)

    def test_uj_rangsor_a_kozolt_idot_hasznalja(self):
        adat = minta("2026-10-19")
        adat["vonalak"][0].update(keses_eloszlas=[[0, 20], [90, 60]], idokeretek=[[-120, 120, 80]])
        self.ment("uj", adat)
        oldal = self.megjelenit()
        self.rendben(oldal)
        kep = json.loads(oldal.get("plotly_chart")[0].proto.spec)
        self.assertEqual(kep["data"][0]["x"], [25.0])
        self.assertNotIn("Nem dönthető el", str(kep))
        oldal.radio[0].set_value(120).run()
        kep = json.loads(oldal.get("plotly_chart")[0].proto.spec)
        self.assertEqual(kep["data"][0]["x"], [100.0])

    def test_hev_irany_es_napvalasztas_valodi_eredmenyt_valtoztat(self):
        for nap, szorzo in (("2026-10-17", 1), ("2026-10-18", 2)):
            adat = minta(nap)
            hev = hev_minta(nap)
            hev["megallo_nevek"].update(A="Kerepes", C="Cinkota")
            hev["iranyok"].append({"vonal_id": "H8", "irany": 1, "utvonalak": [
                {"elso_megallo_id": "B", "utolso_megallo_id": "C", "tervezett_menetek": 10}]})
            hev["kovetesi_reszek"]["naponta"] = [dict(
                varakozas(nap, irany=irany), vonalak=["H8"],
                iranyok=[{"vonal_id": "H8", "irany": irany}],
                median_kovetes_mp=szorzo * (1200 + irany * 600), max_kovetes_mp=9000) for irany in (0, 1)]
            adat["hev"] = hev
            self.ment(nap, adat)
        oldal = self.megjelenit()
        self.nezet(oldal, 4)
        self.assertIn("Gödöllő felé. A legnagyobb napi medián 40,0 perc", self.szoveg(oldal))
        oldal.selectbox(key="hev_irany").set_value(1).run()
        self.assertIn("Cinkota felé. A legnagyobb napi medián 60,0 perc", self.szoveg(oldal))
        oldal.sidebar.radio(key="idoszak_mod").set_value("Napok kiválasztása").run()
        oldal.sidebar.multiselect[0].set_value(["2026-10-17"]).run()
        self.rendben(oldal)
        self.assertIn("Cinkota felé. A legnagyobb napi medián 30,0 perc", self.szoveg(oldal))
        self.assertNotIn("60,0 perc", self.szoveg(oldal))

    def test_regi_hev_es_uj_bkk_nem_keveredik(self):
        adat = minta("2026-10-19")
        adat["hev"] = hev_minta(adat["nap"])
        adat["hev"]["modszer"] = "helyzet-idokeret-1"
        self.ment("uj", adat)
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "80")
        self.nezet(oldal, 4)
        self.assertFalse(oldal.metric)
        self.assertIn("nincs értékelhető H8-eredmény", self.szoveg(oldal))

    def test_idojarashoz_nincs_helyi_szuro_es_a_hiany_nem_nulla_korrelacio(self):
        adat = minta("2026-10-19")
        adat["idojaras"] = [idojaras()]
        self.ment("jo", adat)
        oldal = self.megjelenit()
        self.nezet(oldal, 3)
        self.assertFalse(oldal.selectbox)
        self.assertIn("legalább három összevethető nap", self.szoveg(oldal))
        self.assertIn("Most 1 nap van kijelölve", self.szoveg(oldal))
        self.assertIn("nulla csapadék", self.szoveg(oldal))

    def test_ures_oramezo_oka_es_maximum_jelolese_az_adatokbol_keszul(self):
        adat = reszletes_minta("2026-10-19", 900)
        adat["orankent"].append(dict(adat["orankent"][0], ora=0, n=22, tervezett=68,
                                     lefedettseg=22 / 68, median_keses_mp=330, keses_eloszlas=[[330,22]]))
        self.ment("jo", adat)
        oldal = self.megjelenit()
        self.nezet(oldal, 1)
        kepek = [json.loads(x.proto.spec) for x in oldal.get("plotly_chart")]
        heat = kepek[0]
        self.assertIn("Kevés vizsgálható", heat["data"][1]["customdata"][0][0][4])
        self.assertEqual(heat["data"][1]["customdata"][0][1][4], "Nem volt tervezett továbbhaladás")
        self.assertIsNone(heat["data"][0]["z"][0][0])
        self.assertEqual(heat["data"][0]["text"][0][8],"80")
        self.assertEqual(heat["data"][1]["z"][0][0], 1)
        self.assertEqual(heat["data"][1]["z"][0][1], 0)
        osszes = kepek[1]["data"][0]
        self.assertIsNone(osszes["y"][0])
        self.assertEqual(len(osszes["x"]), 24)
        self.assertFalse(osszes["connectgaps"])
        pelda = kepek[-1]
        self.assertIn("15 perc 0 mp késés", pelda["layout"]["annotations"][0]["text"])
        self.assertIn("Örs vezér tere", pelda["layout"]["annotations"][0]["text"])
        self.assertEqual(pelda["layout"]["shapes"][0]["y1"] - pelda["layout"]["shapes"][0]["y0"], 15)

    def test_rangsor_mondat_a_hatar_es_az_export_valtozasat_is_koveti(self):
        adat = minta("2026-10-19")
        alap = adat["vonalak"][0]
        eloszlasok = {"0975": [[0,60],[90,20]], "1610": [[0,70],[150,10]],
                      "1695": [[0,40],[90,40]], "0460": [[0,50],[180,30]],
                      "3010": [[0,10],[90,70]], "3020": [[0,20],[90,60]]}
        adat["vonalak"] = [dict(alap,vonal_id=v,keses_eloszlas=e) for v,e in eloszlasok.items()]
        hely = self.ment("jo",adat)
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertIn("legfeljebb 1 perces eltérés aránya", self.szoveg(oldal))
        self.assertIn("161 busznál a legnagyobb (87,5%)", self.szoveg(oldal))
        kep = json.loads(oldal.get("plotly_chart")[0].proto.spec)
        self.assertEqual(kep["data"][0]["name"], "Legfeljebb 1 perc eltérés")
        self.assertEqual(kep["data"][1]["name"], "1 percnél nagyobb eltérés")
        self.assertEqual(kep["data"][0]["text"][0], "87,5%")
        self.assertEqual(kep["data"][0]["x"][0], 87.5)
        self.assertEqual(kep["data"][1]["x"][0], 12.5)
        self.assertNotIn("vizsgálható", kep["layout"]["xaxis"]["title"]["text"])
        self.assertNotIn("követhető", kep["data"][0]["hovertemplate"])
        oldal.radio[0].set_value(120).run()
        self.assertIn("legfeljebb 2 perces eltérés aránya", self.szoveg(oldal))
        self.assertIn("97E busznál", self.szoveg(oldal))
        self.assertIn("a legnagyobb (100,0%)", self.szoveg(oldal))
        kep = json.loads(oldal.get("plotly_chart")[0].proto.spec)
        self.assertEqual(kep["data"][0]["name"], "Legfeljebb 2 perc eltérés")
        self.assertEqual(kep["data"][1]["name"], "2 percnél nagyobb eltérés")
        self.assertEqual(kep["data"][0]["text"][0], "100,0%")
        adat["vonalak"][0]["keses_eloszlas"] = [[180,80]]
        (hely / "indulasok.json").write_text(json.dumps(adat),encoding="utf-8")
        oldal.run()
        self.rendben(oldal)
        self.assertNotIn("a 97E busznál a legnagyobb", self.szoveg(oldal))
        self.assertIn("97E busznál a legkisebb (0,0%)", self.szoveg(oldal))
        adat["vonalak"][0].update(keseshez_hasznalt=40,keses_eloszlas=[[180,40]],lefedettseg=.4)
        (hely / "indulasok.json").write_text(json.dumps(adat),encoding="utf-8")
        oldal.run()
        self.rendben(oldal)
        self.assertIn("97E busznál a legkisebb (0,0%)",self.szoveg(oldal))
        kep = json.loads(oldal.get("plotly_chart")[0].proto.spec)
        self.assertIn("97E busz<br>40 megállói elindulás alapján",kep["data"][0]["y"])

    def test_napi_abran_a_darabszam_eger_nelkul_lathato_es_napszuressel_frissul(self):
        for nap,n in (("2026-10-17",30),("2026-10-18",50),("2026-10-19",70)):
            self.ment(nap,minta(nap,n))
        oldal = self.megjelenit()
        kep = json.loads(oldal.get("plotly_chart")[1].proto.spec)
        self.assertEqual(kep["data"][0]["text"][0],
                         ["1,0 perc<br>30 továbbhaladás","1,0 perc<br>50 továbbhaladás","1,0 perc<br>70 továbbhaladás"])
        oldal.sidebar.radio(key="idoszak_mod").set_value("Napok kiválasztása").run()
        oldal.sidebar.multiselect[0].set_value(["2026-10-17","2026-10-19"]).run()
        self.rendben(oldal)
        kep = json.loads(oldal.get("plotly_chart")[1].proto.spec)
        self.assertEqual(kep["data"][0]["text"][0],["1,0 perc<br>30 továbbhaladás","1,0 perc<br>70 továbbhaladás"])
        self.assertNotIn("október 18",str(kep))

    def test_szakasz_eljele_nem_jelent_onmagaban_javulast(self):
        adat = minta("2026-10-19")
        adat["utvonal_reszletek"] = [{"vonal_id":"0975","irany":0,"megallo_idk":["A","B"],
                                      "menetek":[{"menet_id":"m","szolgalati_nap":adat["nap"]}]}]
        hely = self.ment("jo",adat)
        oldal = self.megjelenit()
        self.nezet(oldal,1)
        for elso,masodik in ((120,60),(-22,-64),(-64,-22),(-30,30),(30,-30)):
            with self.subTest(elso=elso,masodik=masodik):
                delta = masodik - elso
                adat["szakaszok"][0].update(median_valtozas_mp=delta,valtozas_eloszlas=[[delta,4]])
                (hely / "indulasok.json").write_text(json.dumps(adat),encoding="utf-8")
                oldal.run()
                self.rendben(oldal)
                szoveg = self.szoveg(oldal)
                self.assertIn("a menetrendi eltérés változása két megálló között",szoveg)
                self.assertIn("A +1 perc egy perccel későbbre, a −1 perc egy perccel korábbra",szoveg)
                self.assertNotIn("csökkent a késése",szoveg)
                kepek = [json.loads(x.proto.spec) for x in oldal.get("plotly_chart")]
                self.assertIn("Menetrendi eltérés változása (medián, perc)",str(kepek))
                sor = app.szakasz_sorrend([adat],"0975",0,["Külső végállomás","Örs vezér tere"])[0]
                self.assertEqual(sor["Változás (perc)"],round(delta / 60,1))

    def test_ritka_megallosor_is_a_kozos_szakasz_teljes_mintajat_mutatja(self):
        adat = minta("2026-10-19")
        adat["utvonal_reszletek"] = [{"vonal_id":"0975","irany":0,"megallo_idk":ids,
            "menetek":[{"menet_id":str(i),"szolgalati_nap":adat["nap"]} for i in range(n)]}
            for ids,n in ((["A","B"],10),(["A","B","C"],2))]
        adat["szakaszok"][0].update(n=134,tervezett_parok=200,lefedettseg=.67,valtozas_eloszlas=[[-60,134]])
        self.ment("jo",adat)
        oldal = self.megjelenit()
        self.nezet(oldal,1)
        oldal.selectbox[2].set_value(1).run()
        self.rendben(oldal)
        self.assertEqual(oldal.selectbox[2].label,"Az ábrán látható megállósor")
        self.assertIn("A közös szakaszokhoz az irány minden útvonalának adatai számítanak",self.szoveg(oldal))
        self.assertIn("2 járműútra írta elő a menetrend",self.szoveg(oldal))
        kepek = [json.loads(x.proto.spec) for x in oldal.get("plotly_chart")]
        self.assertIn(134,kepek[-1]["data"][0]["customdata"][0])

    def test_adatminoseg_a_teljes_forras_oras_maximumat_nevezi_meg_magyar_datummal(self):
        hely = self.ment("jo",minta("2026-10-19"))
        sor = {"probak":10,"siker":9,"hibak":1,"max_jarmu":123,"max_menetfrissites":456}
        (hely / "adatminoseg.json").write_text(json.dumps([{"ora_utc":"2026-10-19T06",
            "forrasok":{"VehiclePositions":sor,"TripUpdates":sor}}]),encoding="utf-8")
        oldal = self.megjelenit()
        self.nezet(oldal,2)
        self.assertIn("óránkénti legnagyobb jármű- és menetfrissítésszáma",self.szoveg(oldal))
        self.assertIn("A teljes BKK-forrás",self.szoveg(oldal))
        kep = json.loads(oldal.get("plotly_chart")[-1].proto.spec)
        self.assertIn("Járműutakról kapott közlések",[s["name"] for s in kep["data"]])
        self.assertNotIn("Közlekedő járatok",str(kep))
        self.assertEqual(kep["layout"]["xaxis"]["ticktext"],["október 19.<br>08:00"])
        self.assertIn("október 19., hétfő 08:00",str(kep["data"][0]["customdata"]))

    def test_hev_ervenytelen_irany_valasztasbol_mukodo_allapotba_all_vissza(self):
        adat = minta("2026-10-19")
        hev = hev_minta(adat["nap"])
        hev["megallo_nevek"].update(A="Kerepes", C="Cinkota", D="Kerepes")
        hev["iranyok"].append({"vonal_id":"H8","irany":1,"utvonalak":[
            {"elso_megallo_id":"B","utolso_megallo_id":"C","tervezett_menetek":10}]})
        sorok = [dict(varakozas(irany=i),vonalak=["H8"],median_kovetes_mp=1200)
                 for i in (0,1)]
        hev["kovetesi_reszek"]["naponta"] = sorok
        adat["hev"] = hev
        hely = self.ment("jo",adat)
        oldal = self.megjelenit()
        self.nezet(oldal,4)
        self.assertEqual(oldal.selectbox(key="hev_irany").value,0)
        self.assertIn("következő két ábrához",oldal.selectbox(key="hev_irany").label)
        self.assertEqual(oldal.selectbox(key="hev_szakasz_irany").label,
                         "A megállósoros ábrák iránya")
        self.assertEqual(sum(s.value == "Hogyan változik az eltérés két megálló között?"
                             for s in oldal.subheader), 1)
        sorok.append(dict(sorok[0],megallo_id="D"))
        (hely / "indulasok.json").write_text(json.dumps(adat),encoding="utf-8")
        oldal.run()
        self.rendben(oldal)
        self.assertEqual(oldal.selectbox(key="hev_irany").value,1)
        self.assertEqual(oldal.selectbox(key="hev_irany").options,["Cinkota felé"])
        abrak = str([json.loads(x.proto.spec) for x in oldal.get("plotly_chart")])
        self.assertIn("30 mp többlet",abrak)

    def test_idojaras_napvalasztasi_utmutatoja_a_kijelolessel_frissul(self):
        for nap in ("2026-10-17","2026-10-18","2026-10-19"):
            self.ment(nap,minta(nap))
        oldal = self.megjelenit()
        self.nezet(oldal,3)
        self.assertIn("Még nincs elég",self.szoveg(oldal))
        oldal.sidebar.radio(key="idoszak_mod").set_value("Napok kiválasztása").run()
        oldal.sidebar.multiselect[0].set_value(["2026-10-17","2026-10-18"]).run()
        self.assertIn("Most 2 nap van kijelölve",self.szoveg(oldal))
        oldal.sidebar.multiselect[0].set_value(["2026-10-17"]).run()
        self.assertIn("Most 1 nap van kijelölve",self.szoveg(oldal))

    def test_hianyos_minoseg_mellett_a_masik_nap_adata_megmarad(self):
        rossz = self.ment("rossz", minta("2026-10-17"))
        jo = self.ment("jo", minta("2026-10-19"))
        (rossz / "adatminoseg.json").write_text(json.dumps([{"ora_utc": "2026-10-17T06"}]), encoding="utf-8")
        (jo / "adatminoseg.json").write_text(json.dumps([{"ora_utc": "2026-10-19T06", "forrasok": {
            "Alerts": {"probak": 10, "siker": 9, "hibak": 1,
                       "max_sikeres_res_mp": 90, "utolso_siker_ota_mp": 30}}}]), encoding="utf-8")
        oldal = self.megjelenit()
        self.nezet(oldal, 2)
        self.assertIn("szombat", self.szoveg(oldal))
        self.assertIn("10 kérésből 1", self.szoveg(oldal))
        self.assertFalse(tablazatok(oldal))


@unittest.skipUnless(WEB_ELERHETO, "A web függőségei is szükségesek.")
class UjElemzesTeszt(unittest.TestCase):
    def test_szakaszsorrend_menetrend_szerint_es_hiany_uresen(self):
        adat = minta("2026-10-19")
        adat["szakaszok"].append({**adat["szakaszok"][0], "honnan": "C", "hova": "A",
                                  "median_valtozas_mp": 120, "valtozas_eloszlas": [[120, 4]]})
        sorrend = ["Rövid út végállomása", "Külső végállomás", "Örs vezér tere", "Még egy megálló"]
        sorok = app.szakasz_sorrend([adat], "0975", 0, sorrend)
        self.assertEqual([s["Megálló"] for s in sorok], sorrend[1:])
        self.assertEqual([s["Változás (perc)"] for s in sorok], [2.0, -1.0, None])
        self.assertEqual([s["Megfigyelt megállópár"] for s in sorok], [4, 4, 0])

    def test_idojarasi_korrelacio_eltavolitja_a_kozos_napszakot_es_frissul(self):
        adatok = []
        for nap, eltol in (("2026-10-18", -1), ("2026-10-19", 1)):
            adat = minta(nap)
            adat["idojaras"], adat["orankent"] = [], []
            for ora in range(8, 14):
                w = idojaras(nap + "T" + str(ora - 2).zfill(2))
                w["homerseklet_atlag"] = 10 + ora + eltol
                adat["idojaras"].append(w)
                adat["orankent"].append({**minta(nap)["orankent"][0], "ora": ora,
                                        "median_keses_mp": 1000 - 30 * ora + eltol * 60,
                                        "keses_eloszlas": [[1000 - 30 * ora + eltol * 60, 80]]})
            adatok.append(adat)
        eredmeny = app.idojaras_osszefugges(adatok)
        h = next(s for s in eredmeny if s["vonal"] == "0975" and s["nev"] == "Hőmérséklet")
        self.assertAlmostEqual(h["r_napszak"], 1.0)
        self.assertIsNone(h["r"])  # Két nap különbségéből nincs napra is korrigált kapcsolat.
        self.assertEqual(h["orak"], 12)
        self.assertEqual(h["n"], 960)
        eso = next(s for s in eredmeny if s["vonal"] == "0975" and s["nev"] == "Csapadék")
        self.assertIsNone(eso["r"])
        self.assertEqual(eso["ok"], "Nem változott az időjárási érték")
        adatok.pop()
        h = next(s for s in app.idojaras_osszefugges(adatok) if s["vonal"] == "0975" and s["nev"] == "Hőmérséklet")
        self.assertIsNone(h["r"])

    def test_mozgasos_ellenorzes_nem_pontossagi_tartomany(self):
        sor = {"n": 10, "keses_eloszlas": [[0, 7], [90, 3]],
               "idokeretek": [[-120, 120, 10]]}
        self.assertEqual(app.kuszob_arany(sor, 60), 0.7)
        self.assertEqual(app.kuszob_arany(sor, 120), 1)
        sor["idokeretek"] = [[0, 0, 10]]
        self.assertEqual(app.kuszob_arany(sor, 60), 0.7)

    def test_kulonbozo_modszerek_nem_keverednek(self):
        regi, uj = minta("2026-10-18"), minta("2026-10-19")
        regi["modszer"] = "helyzet-idokeret-1"
        self.assertEqual(app.napok_kivalasztasa({"regi": regi, "uj": uj}), {"2026-10-19": "uj"})

    def test_ismetlodo_vegighaladasok_elotti_export_kulon_marad(self):
        for modszer in ("kozles-haladas-ajto-1", "hev-kozles-kontroll-1",
                        "kozles-haladas-ajto-2", "hev-kozles-kontroll-2",
                        "kozles-haladas-ajto-3", "hev-kozles-kontroll-3"):
            with self.subTest(modszer=modszer):
                adat = dict(minta("2026-10-18"), modszer=modszer)
                self.assertTrue(app.regi_modszer(adat))
                self.assertFalse(app.napok_kivalasztasa({"regi": adat}))
                with self.assertRaises(ValueError):
                    app.minta_ellenorzese(adat)

    def test_buszos_napokat_kozos_megfigyelesi_idovel_sulyoz(self):
        a = {"lefedett_mp": 100, "vizsgalt_mp": 500, "kesobbi_gyorsabb_mp": 20,
             "valasztasok": [{"valasztas": "elso", "n": 2, "varakozas_mp": 10,
                             "menetido_mp": 100, "teljes_also_mp": 100, "teljes_felso_mp": 120}]}
        b = deepcopy(a)
        b["lefedett_mp"] = 300
        b["valasztasok"][0]["varakozas_mp"] = 30
        er = app.buszos_osszesites([a, b])
        self.assertEqual(er["ido"], 400)
        self.assertEqual(er["valasztasok"][0]["varakozas_mp"], 25)
        self.assertEqual(er["valasztasok"][0]["n"], 4)

    def test_a_napkozi_kulonbseg_onmagaban_nem_idojarasi_hatas(self):
        sorok = [{"nap": "2026-10-" + str(17 + nap), "ora": ora,
                  "hom": 10 + nap * 3 + ora, "median_keses_mp": nap * 120 - ora * 5}
                 for nap in range(4) for ora in range(8, 16)]
        self.assertIsNone(app.idojaras_erzekenyseg(sorok, "hom")["r"])
        for s in sorok:
            nap = int(s["nap"][-2:])
            hatas = (nap % 2 * 2 - 1) * ((s["ora"] % 3) - 1)
            s["hom"] += hatas
            s["median_keses_mp"] += hatas * 30
        er = app.idojaras_erzekenyseg(sorok, "hom")
        self.assertAlmostEqual(er["r"], 1)
        self.assertTrue(er["kihagyas"])


@unittest.skipUnless(WEB_ELERHETO, "A web függőségei is szükségesek.")
class ErthetosegiSzamitasProba(unittest.TestCase):
    def test_a_homersekleti_mondat_a_kozos_korrekcio_eredmenyet_koveti(self):
        sorok = []
        for nap in range(4):
            for ora in range(8):
                hatas = (nap % 2 * 2 - 1) * ((ora % 3) - 1)
                mas_hatas = (nap // 2 * 2 - 1) * (-1) ** ora
                sorok.append({"nap": "2026-10-" + str(17 + nap), "ora": ora,
                              "homerseklet_atlag": 10 + nap * 3 + ora + hatas,
                              "median_keses_mp": 1000 + nap * 120 + ora * 30 + mas_hatas * 90})
        def szoveg():
            kapcsolat = {"vonal": "0975", "nev": "Hőmérséklet", "mezo": "homerseklet_atlag",
                         "sorok": sorok, "r": app.idojaras_erzekenyseg(sorok, "homerseklet_atlag")["r"]}
            return app.homerseklet_kovetkeztetes([kapcsolat])
        elotte = deepcopy(sorok)
        self.assertIn("eredetileg látszó kapcsolat", szoveg())
        self.assertIn("után gyenge", szoveg())
        self.assertEqual(sorok, elotte)
        for s in sorok:
            nap, ora = int(s["nap"][-2:]) - 17, s["ora"]
            hatas = (nap % 2 * 2 - 1) * ((ora % 3) - 1)
            s["median_keses_mp"] = 1000 + nap * 120 + ora * 30 + hatas * 90
        self.assertIn("nagyobb késés társul", szoveg())
        for s in sorok:
            s["median_keses_mp"] = 4000 - s["median_keses_mp"]
        self.assertIn("kisebb késés társul", szoveg())
        self.assertIsNone(app.homerseklet_kovetkeztetes([]))

    def test_az_esetleiras_nem_szamol_valtozast_a_hianyzo_megallon_at(self):
        adat = reszletes_minta("2026-10-19")
        pontok = adat["keses_reszletek"]["szelso_utak"][0]["megallok"]
        elotte = deepcopy(pontok)
        szoveg = " ".join(app.keses_pelda_osszefoglalo([adat], pontok))
        self.assertIn("1 perc 0 mp", szoveg)
        self.assertIn("10 perc 0 mp", szoveg)
        self.assertIn("9 perc 0 mp", szoveg)
        self.assertIn("Minden követhető megállónál", szoveg)
        self.assertEqual(pontok, elotte)
        pontok[0]["indulas"] = pontok[0]["tervezett"]
        self.assertIn("a menetrenddel egyező időpont", " ".join(app.keses_pelda_osszefoglalo([adat], pontok)))
        pontok.insert(1, dict(pontok[0], megallo_id="hiany", indulas=None))
        szoveg = " ".join(app.keses_pelda_osszefoglalo([adat], pontok))
        self.assertNotIn("legnagyobb növekedés", szoveg)
        pontok[0]["indulas"] = pontok[0]["tervezett"] - 60
        szoveg = " ".join(app.keses_pelda_osszefoglalo([adat], pontok))
        self.assertNotIn("Minden követhető megállónál", szoveg)

    def test_az_osszesitett_orak_kihagyjak_a_gyenge_napi_mintat_es_megtartjak_a_lyukat(self):
        a,b = reszletes_minta("2026-10-18"),reszletes_minta("2026-10-19")
        a["orankent"].append(dict(a["orankent"][0],ora=0,n=22,tervezett=68,
                                 lefedettseg=22/68,median_keses_mp=330,keses_eloszlas=[[330,22]]))
        b["orankent"].append(dict(b["orankent"][0],ora=10))
        elotte = deepcopy([a,b])
        eredmeny = app.osszesitett_orak([a,b],"0975",0)
        self.assertEqual([s["ora"] for s in eredmeny],list(range(24)))
        self.assertIsNone(eredmeny[0]["median_keses_mp"])
        self.assertEqual(eredmeny[8]["n"],160)
        self.assertIsNone(eredmeny[9]["median_keses_mp"])
        self.assertEqual(eredmeny[10]["n"],80)
        self.assertEqual([a,b],elotte)

    def test_hev_osszesitesbe_sem_kerul_egyetlen_vonat_sok_allomasi_adata(self):
        adat = reszletes_minta("2026-10-19",hev=True)
        adat["keses_reszletek"]["orankent"][0]["menet_db"] = 1
        self.assertIsNone(app.osszesitett_orak([adat],"H8",0)[8]["median_keses_mp"])
        adat["keses_reszletek"]["orankent"][0]["menet_db"] = 2
        self.assertIsNotNone(app.osszesitett_orak([adat],"H8",0)[8]["median_keses_mp"])

    def test_ures_orak_okai_elvalnak_egymastol(self):
        jo = {"n":30,"tervezett":60,"lefedettseg":.5,"median_keses_mp":0,"menet_db":2}
        self.assertEqual(app.ora_hianyanak_oka({}),"Nem volt tervezett továbbhaladás")
        self.assertIn("Egyetlen",app.ora_hianyanak_oka(dict(jo,n=0)))
        self.assertIn("Kevés",app.ora_hianyanak_oka(dict(jo,n=22)))
        self.assertIn("kevesebb mint fele",app.ora_hianyanak_oka(dict(jo,lefedettseg=.4)))
        self.assertIn("Kettőnél kevesebb",app.ora_hianyanak_oka(dict(jo,menet_db=1),True))
        self.assertIn("hiányzik",app.ora_hianyanak_oka(dict(jo,menet_db=None),True))
        self.assertTrue(app.ora_hasznalhato(jo,True))

    def test_pontabra_ugyanazt_a_korrigalt_kapcsolatot_mutatja_es_valtozik(self):
        sorok = []
        for nap in range(4):
            for ora in range(8):
                hatas = (nap % 2 * 2 - 1) * ((ora % 3) - 1)
                sorok.append({"nap":"2026-10-"+str(17+nap),"ora":8+ora,"n":80,
                              "szel_atlag":20+nap*3+ora+hatas,
                              "median_keses_mp":1000+nap*120+ora*30+hatas*90})
        elotte = deepcopy(sorok)
        adat = {"sorok":sorok,"mezo":"szel_atlag","nev":"Szél","vonal":"3046"}
        kep = app.idojarasi_pontabra(adat)
        pontok = kep.data[0]
        self.assertEqual(len(pontok.x),32)
        self.assertEqual(pontok.mode,"markers")
        self.assertAlmostEqual(app.korrelacio(pontok.x,pontok.y),1)
        self.assertAlmostEqual(app.korrelacio(pontok.x,pontok.y),app.idojaras_erzekenyseg(sorok,"szel_atlag")["r"])
        # A másik panel ugyanazokat az órákat mutatja a fizikai, eredeti egységekben.
        nyers = kep.data[2]
        self.assertEqual(list(nyers.x), [s["szel_atlag"] for s in sorok])
        self.assertEqual(list(nyers.y), [s["median_keses_mp"] / 60 for s in sorok])
        self.assertTrue(all(ertek >= 0 for ertek in nyers.x))
        self.assertLess(min(pontok.x), 0)
        self.assertEqual(list(nyers.customdata), list(pontok.customdata))
        self.assertEqual(nyers.xaxis, "x")
        self.assertEqual(pontok.xaxis, "x2")
        # Az eredeti egyenes helyes tengelymetszettel, mindkét végpontnál azonos meredekséggel fut.
        vonal = kep.data[3]
        ax, ay = sum(nyers.x) / 32, sum(nyers.y) / 32
        meredekseg = sum((x - ax) * (y - ay) for x, y in zip(nyers.x, nyers.y)) / sum((x - ax) ** 2 for x in nyers.x)
        for x, y in zip(vonal.x, vonal.y):
            self.assertAlmostEqual(y, ay + meredekseg * (x - ax))
        self.assertIn("eltérése a várhatótól", kep.layout.xaxis2.title.text)
        self.assertEqual(sorok,elotte)
        for s in sorok:
            s["median_keses_mp"] = 3000 - s["median_keses_mp"]
        uj = app.idojarasi_pontabra(adat)
        self.assertAlmostEqual(app.korrelacio(uj.data[0].x,uj.data[0].y),-1)
        self.assertNotEqual(list(pontok.y),list(uj.data[0].y))
        self.assertIsNone(app.idojarasi_pontabra(dict(adat,sorok=sorok[:8])))

    def test_azonos_rangsorbol_nem_talal_ki_kulonbseget(self):
        rang = [({"vonal_id":v,"keseshez_hasznalt":n},.8)
                for v,n in (("0975",80),("1610",40),("1695",100))]
        szoveg = " ".join(app.rangsor_osszefoglalo(rang,120))
        self.assertIn("mind a 3 járatnál ugyanannyi, 80,0%",szoveg)
        self.assertNotIn("legkisebb",szoveg)
        self.assertNotIn("megállói elindulás alapján",szoveg)
        self.assertEqual(app.rangsor_osszefoglalo(rang[:1],60),[])

    def test_varakozasi_kulonbseg_eljele_es_kerekitese_helyes(self):
        self.assertIn("11 mp többletvárakozást",app.varakozas_kulonbseg(11.4))
        self.assertIn("rövidebb volt",app.varakozas_kulonbseg(-11.6))
        self.assertIn("12 mp",app.varakozas_kulonbseg(-11.6))
        self.assertIn("Másodpercre kerekítve",app.varakozas_kulonbseg(.1))


@unittest.skipUnless(WEB_ELERHETO, "A webes csomagok nem érhetők el.")
class MenetrendiForrasSzovegProba(unittest.TestCase):
    def test_a_buszos_kovetkeztetes_az_idok_valtozasaval_megfordul(self):
        def valasztas(nev, teljes):
            return {"valasztas": nev, "varakozas_mp": 60, "menetido_mp": teljes - 60,
                    "teljes_also_mp": teljes - 10, "teljes_felso_mp": teljes + 10}
        elso, masik = valasztas("elso", 600), valasztas("1610", 720)
        er = {"valasztasok": [elso, masik]}
        szoveg = app.buszos_kovetkeztetes(er)
        self.assertIn("megérte felszállni az első megfelelő buszra", szoveg)
        self.assertIn("10 perc 0 mp", szoveg)
        er["valasztasok"] = [valasztas("elso", 800), masik]
        szoveg = app.buszos_kovetkeztetes(er)
        self.assertIn("megérte erre a buszra várni", szoveg)
        self.assertIn("161 megvárásával", szoveg)
        self.assertNotIn("megérte felszállni", szoveg)

    def test_atfedo_buszos_idokbol_nem_ad_tanacsot(self):
        er = {"valasztasok": [
            {"valasztas": "elso", "varakozas_mp": 60, "menetido_mp": 540,
             "teljes_also_mp": 580, "teljes_felso_mp": 620},
            {"valasztas": "0975", "varakozas_mp": 90, "menetido_mp": 520,
             "teljes_also_mp": 590, "teljes_felso_mp": 630}]}
        szoveg = app.buszos_kovetkeztetes(er)
        self.assertIn("nem dönthető el a sorrend", szoveg)
        self.assertNotIn("megérte", szoveg)

    def test_a_szurt_mintaszambol_keszul_a_forras_magyarazata(self):
        sorok = [{"vonal_id": "0460", "tervezett": 100, "n": 60,
                  "bkk_terv_db": 30, "eltero_terv_db": 4, "nagy_elteres_db": 2},
                 {"vonal_id": "0460", "tervezett": 50, "n": 20,
                  "bkk_terv_db": 10, "eltero_terv_db": 1, "nagy_elteres_db": 1}]
        egyutt = app.osszevon(sorok, ("vonal_id",))
        szoveg = " ".join(app.menetrendi_alap_szoveg(egyutt))
        self.assertIn("80 megállói indulás", szoveg)
        self.assertIn("5 esetben", szoveg)
        self.assertIn("nem ezt vettem alapnak, hanem a menetrendet", szoveg)
        self.assertIn("3 eltérés", szoveg)
        mas = " ".join(app.menetrendi_alap_szoveg(sorok[1:]))
        self.assertIn("20 megállói indulás", mas)
        self.assertIn("1 eltérés", mas)

    def test_ures_vagy_szelseg_nelkuli_adat_nem_kap_felesleges_magyarazatot(self):
        self.assertEqual(app.menetrendi_alap_szoveg([]), [])
        szoveg = app.menetrendi_alap_szoveg([{"keseshez_hasznalt": 12}])
        self.assertEqual(len(szoveg), 1)
        self.assertIn("12 megállói indulás", szoveg[0])
        self.assertIn("a letöltött menetrendhez", szoveg[0])


if __name__ == "__main__":
    unittest.main()
