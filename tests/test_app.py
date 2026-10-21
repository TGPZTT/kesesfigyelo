"""Az utasnézet számításainak és képernyőinek hálózat nélküli próbái."""

import json
import re
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from importlib.util import find_spec
from pathlib import Path

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
            "modszer": "kozles-haladas-ajto-1", "forras_csoport": "bkk", "pontossagi_rangsor": True,
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
    adat.update(modszer="hev-kozles-kontroll-1", forras_csoport="hev", pontossagi_rangsor=False)
    adat["allapot"] = "kesz"
    for mezo in ("vonalak", "orankent", "szakaszok", "iranyok"):
        for sor in adat[mezo]:
            sor["vonal_id"] = "H8"
    adat["megallo_nevek"] = {"A": "Örs vezér tere", "B": "Gödöllő"}
    return adat


@unittest.skipUnless(WEB_ELERHETO, "A web függőségei is szükségesek.")
class SzamitasTeszt(unittest.TestCase):
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

    def megjelenit(self):
        return AppTest.from_function(megnyit, args=(str(self.mappa),), default_timeout=15).run()

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
        oldal = self.megjelenit()
        self.rendben(oldal)
        self.assertEqual(self.darab(oldal), "80")
        self.assertNotIn("próbamintát", self.szoveg(oldal))

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
        hely = self.ment("jo", minta("2026-10-19", 80))
        oldal = self.megjelenit()
        self.assertIn("40 továbbhaladásnál", self.szoveg(oldal))
        elso = list(oldal.session_state["mentesek_allapota"])
        uj = minta("2026-10-19", 40, 300)
        uj["vonalak"][0].update(koran_erkezett=20, megvarta_indulast=15)
        (hely / "indulasok.json").write_text(json.dumps(uj), encoding="utf-8")
        oldal.run()
        self.rendben(oldal)
        self.assertNotEqual(elso, oldal.session_state["mentesek_allapota"])
        self.assertEqual(self.darab(oldal), "40")
        self.assertIn("20 továbbhaladásnál", self.szoveg(oldal))
        self.assertNotIn("40 továbbhaladásnál", self.szoveg(oldal))
        masodik = list(oldal.session_state["mentesek_allapota"])
        oldal.run()
        self.assertEqual(masodik, oldal.session_state["mentesek_allapota"])

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
        self.assertIn("Még nincs elég", self.szoveg(oldal))
        self.assertIn("nulla csapadék", self.szoveg(oldal))

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


if __name__ == "__main__":
    unittest.main()
