"""Kis kitalált menetek; ezekhez nem kell adatbázis vagy internet."""

import copy
import os
import unittest
from collections import Counter
from datetime import UTC, date, datetime
from statistics import median

from psycopg.rows import dict_row

import elemzes
import test_betolto as betoltes_proba
from betolto import menetrendi_ido

ALAP = int(datetime(2026, 10, 17, tzinfo=UTC).timestamp())


def kozles(ido, indulas, sorrend=1, **plusz):
    adat = {
        "sorrend": sorrend, "megallo_id": "M" + str(sorrend),
        "adat_ido": ALAP + ido, "feed_ido": ALAP + ido + 5,
        "jarmu_id": "J1", "indulas": ALAP + indulas if indulas is not None else None,
        "erkezes": ALAP + indulas - 10 if indulas is not None else None, "bizonytalansag": 0,
        "erkezes_bizonytalansag": 0,
        "allapot": 0, "menet_allapot": 0,
    }
    adat.update(plusz)
    return adat


def pont(ido, sorrend, allapot=1, **plusz):
    adat = {
        "adat_ido": ALAP + ido, "jarmu_id": "J1", "sorrend": sorrend,
        "megallo_id": "M" + str(sorrend), "allapot": allapot, "menet_allapot": 0,
        "lat": 47.5 + (sorrend - 1) / 1000, "lon": 19.0,
    }
    adat.update(plusz)
    return adat


def kis_menet():
    return {
        "menet_id": "T1", "szolgalati_nap": "2026-10-17", "vonal_id": "3046",
        "irany": 0,
        "megallok": [
            {"sorrend": i, "megallo_id": "M" + str(i),
             "tervezett": ALAP + (i - 1) * 120,
             "tervezett_erkezes": ALAP + (i - 1) * 120,
             "lat": 47.5 + (i - 1) / 1000, "lon": 19.0, "felszallas": 0}
            for i in (1, 2, 3)
        ],
        "kozlesek": [kozles(60, 30), kozles(90, 30),
                     kozles(160, 145, 2), kozles(190, 145, 2)],
        "poziciok": [pont(-10, 1), pont(20, 1), pont(40, 2, 2),
                     pont(140, 2), pont(160, 3, 2)],
    }


def elso(menet):
    return elemzes.indulasok(menet)[0]


class EllenorzottIndulasProba(unittest.TestCase):
    def elso(self, menet):
        return elemzes.ellenorzott_indulasok(menet)[0]

    def test_a_vegso_kozles_az_ido_nem_a_gps_kozepe(self):
        m = kis_menet()
        for s in m["kozlesek"]:
            if s["sorrend"] == 1:
                s["indulas"] = ALAP + 23
        eredeti = copy.deepcopy(m)
        a = self.elso(m)
        self.assertEqual(a["indulas"], ALAP + 23)
        self.assertEqual(a["mozgasos_indulas"], ALAP + 30)
        self.assertEqual(m, eredeti)

    def test_athaladas_megallas_es_ajtonyitas_nelkul(self):
        m = kis_menet()
        m["poziciok"] = [pont(20, 1, 2, lat=47.4998), pont(40, 2, 2)]
        a = self.elso(m)
        self.assertEqual(a["indulas"], ALAP + 30)
        self.assertEqual(a["esemeny_tipus"], "tovabbhaladas")
        self.assertEqual(a["ajto_ellenorzes"], "nincs_minta")
        for p in m["poziciok"]:
            p["ajto_nyitva"] = False
        self.assertEqual(self.elso(m)["indulas"], ALAP + 30)

    def test_kesobbi_nyitott_ajto_ellentmondas(self):
        m = kis_menet()
        m["poziciok"].append(pont(36, 1, ajto_nyitva=True))
        a = self.elso(m)
        self.assertIsNone(a["indulas"])
        self.assertEqual(a["elutasitas"], "kesobbi_nyitott_ajto")

    def test_ajtojel_technikai_turesenek_hatarai(self):
        for ido, elfogadott in ((29, True), (35, True), (36, False)):
            m = kis_menet()
            m["poziciok"].append(pont(ido, 1, ajto_nyitva=True))
            with self.subTest(ido=ido):
                self.assertEqual(self.elso(m)["indulas"] is not None, elfogadott)

    def test_kesobbi_allas_zart_ajtoval_kulon_jelzes(self):
        m = kis_menet()
        m["poziciok"].append(pont(36, 1, ajto_nyitva=False))
        a = self.elso(m)
        self.assertIsNotNone(a["indulas"])
        self.assertTrue(a["kesobbi_allas"])

    def test_hev_ajtojelbol_nem_vonunk_le_kovetkeztetest(self):
        m = kis_menet()
        m["vonal_id"] = "H8"
        m["poziciok"].append(pont(36, 1, ajto_nyitva=True))
        a = self.elso(m)
        self.assertEqual(a["indulas"], ALAP + 30)
        self.assertEqual(a["ajto_ellenorzes"], "nem_hasznalhato")
        er = elemzes.feldolgozas({"menetek": [m]}, date(2026, 10, 17))
        self.assertEqual(er["modszer"], elemzes.HEV_MODSZER)
        self.assertFalse(er["hivatalos_pontossaggal_osszevetheto"])
        self.assertFalse(er["pontossagi_rangsor"])
        self.assertEqual(er["utazas"]["hev"], [])

    def test_hev_kovetes_kulon_allomasonkent_keszul(self):
        m = kis_menet()
        m["vonal_id"] = "H8"
        e = elemzes.ellenorzott_indulasok(m)
        csoportok = list(elemzes.kovetesi_csoportok(e, []))
        self.assertEqual({hely["megallo_id"] for hely, _, _ in csoportok}, {"M1", "M2"})
        self.assertTrue(all(hely["vonalak"] == ["H8"] for hely, _, _ in csoportok))

    def test_hev_azonos_allomasazonosito_ket_iranyban_kulon_marad(self):
        m = kis_menet()
        m["vonal_id"] = "H8"
        e = elemzes.ellenorzott_indulasok(m)
        e += [dict(s, irany=1) for s in e]
        csoportok = list(elemzes.kovetesi_csoportok(e, []))
        self.assertEqual(len(csoportok), 4)
        self.assertTrue(all(len({s["irany"] for s in sorok}) == 1 for _, sorok, _ in csoportok))
        elemzes.kovetesi_orak(e, date(2026, 10, 17), [])

    def test_hev_es_bkk_nem_kerul_kozos_eredmenybe(self):
        m = kis_menet()
        h = dict(m, vonal_id="H8")
        with self.assertRaisesRegex(ValueError, "külön"):
            elemzes.feldolgozas({"menetek": [m, h]}, date(2026, 10, 17))

    def test_egy_befagyott_idobelyeg_nem_ket_kozles(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 30), kozles(60, 30, feed_ido=ALAP + 100)]
        self.assertEqual(self.elso(m)["elutasitas"], "nem_stabil")

    def test_a_kesobbi_javitas_utani_vegso_ido_kell(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 24), kozles(90, 24), kozles(120, 32)]
        self.assertIsNone(self.elso(m)["indulas"])
        m["kozlesek"].append(kozles(150, 32))
        self.assertEqual(self.elso(m)["indulas"], ALAP + 32)

    def test_vegso_allapot_visszavonja_a_korabbi_jo_idot(self):
        for plusz in ({"bizonytalansag": 30}, {"allapot": 2}, {"allapot": 1},
                      {"menet_allapot": 1}, {"adat_ido": None}):
            m = kis_menet()
            m["kozlesek"].append(kozles(200, 30, **plusz))
            with self.subTest(plusz=plusz):
                self.assertIsNone(self.elso(m)["indulas"])

    def test_azonos_idobelyeghez_ellentetes_tartalom_nem_tunik_el(self):
        m = kis_menet()
        m["kozlesek"].append(kozles(60, 31, feed_ido=ALAP + 200))
        m["kozlesek"] = elemzes.kozlesek_ritkitasa(m["kozlesek"])
        self.assertEqual(self.elso(m)["elutasitas"], "nem_stabil")
        m["kozlesek"].append(kozles(210, 31))
        self.assertEqual(self.elso(m)["indulas"], ALAP + 31)

    def test_azonos_feed_es_sajat_ido_mellett_nem_valaszthato_valtozat(self):
        m = kis_menet()
        m["kozlesek"].append(kozles(60, 31))
        self.assertEqual(self.elso(m)["elutasitas"], "azonos_ido_ellentmondas")

    def test_jovobeli_sajat_ido_nem_bizonyitek(self):
        m = kis_menet()
        m["kozlesek"][0]["feed_ido"] = ALAP
        self.assertEqual(self.elso(m)["elutasitas"], "jovobeli_sajat_ido")

    def test_hibas_vagy_letert_pontot_nem_hidal_at(self):
        for plusz in ({"lat": None}, {"lat": float("nan")}, {"lat": 100}, {"letert": True}):
            m = kis_menet()
            m["poziciok"].append(pont(31, 1, 2, **plusz))
            with self.subTest(plusz=plusz):
                self.assertIsNone(self.elso(m)["indulas"])

    def test_azonos_idopontu_ellentetes_ajtojel_megszakit(self):
        m = kis_menet()
        m["poziciok"] += [pont(31, 1, ajto_nyitva=True), pont(31, 1, ajto_nyitva=False)]
        self.assertIsNone(self.elso(m)["indulas"])

    def test_a_mar_elhaladt_jarmuhoz_nem_gyart_kesobbi_indulast(self):
        m = kis_menet()
        m["poziciok"] = [pont(0, 1, 2), pont(20, 2, 2), pont(40, 2, 2, lat=47.502)]
        self.assertEqual(self.elso(m)["elutasitas"], "korabban_tovabbhaladt")

    def test_korai_sorszamugras_utan_valodi_megallasi_jel_helyreallit(self):
        m = kis_menet()
        m["poziciok"] = [pont(-10, 2, 2), pont(20, 1, ajto_nyitva=True), pont(40, 2, 2)]
        self.assertEqual(self.elso(m)["indulas"], ALAP + 30)

    def test_hianyos_azonositas_es_masik_jarmu_nem_fogadhato_el(self):
        for plusz in ({"jarmu_id": "J2"}, {"megallo_id": "MASIK"}):
            m = kis_menet()
            m["kozlesek"][0].update(plusz)
            self.assertEqual(self.elso(m)["elutasitas"], "azonositas")
        m = kis_menet()
        m["poziciok"].append(pont(10, 1, jarmu_id="J2"))
        self.assertIsNone(self.elso(m)["erkezes"])

    def test_tavoli_mellekelhaladas_es_gpsugras_nem_megallolatogatas(self):
        for lat in (47.51, 48.5):
            m = kis_menet()
            m["poziciok"] = [pont(20, 1, 2, lat=lat), pont(40, 2, 2, lat=lat + 0.001)]
            self.assertIsNone(self.elso(m)["indulas"])

    def test_torles_utani_adat_nem_tamasztja_ala_az_indulast(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(10, 30, bizonytalansag=30), kozles(25, 30, menet_allapot=3)]
        self.assertEqual(self.elso(m)["minoseg"], "torolt")

    def test_korabbi_torles_friss_normal_kozles_es_mozgas_utan_feloldhato(self):
        m = kis_menet()
        m["kozlesek"].append(kozles(-3600, None, menet_allapot=3, feed_ido=ALAP + 25))
        self.assertEqual(self.elso(m)["indulas"], ALAP + 30)

    def test_regi_jarmuadat_uj_feedben_nem_oldja_fel_a_torlest(self):
        sorok = [kozles(20, 15), kozles(10, None, menet_allapot=3, feed_ido=ALAP + 25),
                 kozles(20, 15, feed_ido=ALAP + 100)]
        self.assertEqual(elemzes.fennallo_torles(sorok), ALAP + 25)

    def test_kesobbi_torles_nem_torli_a_mar_lezajlott_indulast(self):
        m = kis_menet()
        m["kozlesek"].append(kozles(-3600, None, menet_allapot=3, feed_ido=ALAP + 200))
        self.assertEqual(elemzes.fennallo_torles(m["kozlesek"]), ALAP + 200)
        self.assertEqual(self.elso(m)["indulas"], ALAP + 30)

    def test_azonos_valaszban_normal_es_torolt_allapot_nem_feloldas(self):
        sorok = [kozles(20, None, menet_allapot=3, feed_ido=ALAP + 25),
                 kozles(25, 20, feed_ido=ALAP + 25)]
        self.assertEqual(elemzes.fennallo_torles(sorok), ALAP + 25)
        self.assertEqual(elemzes.fennallo_torles(list(reversed(sorok))), ALAP + 25)

    def test_valoban_korai_idot_nem_kerekiti_nullara(self):
        m = kis_menet()
        m["megallok"][0]["tervezett"] = ALAP + 60
        self.assertEqual(self.elso(m)["keses_mp"], -30)


class MozgasosIdokeretProba(unittest.TestCase):
    def test_hibas_menetrendi_megallopont_nem_allitja_le_a_napot(self):
        for lat in (None, float("nan"), 100):
            m = kis_menet()
            m["megallok"][0]["lat"] = lat
            self.assertIsNone(elemzes.mozgasbol_indulasok(m)[0]["indulas"])

    def elso(self, menet):
        return elemzes.mozgasbol_indulasok(menet)[0]

    def test_a_tu_nem_valaszt_idokeretet_es_nem_huzza_a_kozeperteket(self):
        m = kis_menet()
        eredeti = copy.deepcopy(m)
        a = self.elso(m)
        for s in m["kozlesek"]:
            s["indulas"] += 500
        b = self.elso(m)
        self.assertEqual((a["also"], a["felso"]), (ALAP + 20, ALAP + 40))
        self.assertEqual(a["indulas"], b["indulas"])
        self.assertEqual(eredeti["poziciok"], m["poziciok"])
        m["kozlesek"] = []
        self.assertEqual(self.elso(m)["indulas"], a["indulas"])

    def test_a_tu_kulonbsege_lathato_de_nem_torli_a_mozgast(self):
        m = kis_menet()
        for s in m["kozlesek"]:
            if s["sorrend"] == 1:
                s["indulas"] = ALAP
        s = self.elso(m)
        self.assertFalse(s["tu_egyezes"])
        self.assertIsNotNone(s["indulas"])

    def test_nincs_gps_nincs_idokeret(self):
        m = kis_menet()
        for p in m["poziciok"]:
            p["lat"] = None
        self.assertIsNone(self.elso(m)["indulas"])

    def test_nan_es_ervenytelen_koordinata_nem_fer_bele(self):
        for lat in (float("nan"), float("inf"), 100):
            m = kis_menet()
            m["poziciok"][1]["lat"] = lat
            self.assertIsNone(self.elso(m)["indulas"])

    def test_ugras_es_allo_koordinata_nem_indulas(self):
        for pontok in ([pont(29, 1), pont(30, 2, 2, lat=47.6)],
                       [pont(20, 1), pont(40, 2, 2, lat=47.5)]):
            m = kis_menet()
            m["poziciok"] = pontok
            self.assertIsNone(self.elso(m)["indulas"])

    def test_rossz_megallo_es_masik_jarmu_nem_fer_bele(self):
        for plusz in ({"megallo_id": "ROSSZ"}, {"jarmu_id": "J2"}):
            m = kis_menet()
            m["poziciok"] = [pont(20, 1), pont(40, 2, 2, **plusz)]
            self.assertIsNone(self.elso(m)["indulas"])

    def test_hibas_koztes_pontot_nem_hidal_at(self):
        m = kis_menet()
        m["poziciok"].append(pont(25, 1, lat=None))
        self.assertIsNone(self.elso(m)["indulas"])

    def test_azonos_idoju_ellentmondas_megszakit(self):
        m = kis_menet()
        m["poziciok"].append(pont(20, 1, lat=47.51))
        self.assertIsNone(self.elso(m)["indulas"])

    def test_valtozatlan_pont_ismetlese_nem_tobbszoroz(self):
        m = kis_menet()
        m["poziciok"] += copy.deepcopy(m["poziciok"])
        self.assertEqual(self.elso(m)["indulas"], ALAP + 30)

    def test_jovobeli_sajat_ido_kizarhato_de_regi_meroora_nem_azonos_a_kesesel(self):
        m = kis_menet()
        m["poziciok"][1]["feed_ido"] = ALAP
        self.assertIsNone(self.elso(m)["indulas"])
        m = kis_menet()
        for p in m["poziciok"]:
            p["feed_ido"] = p["adat_ido"] + 1000
        self.assertIsNotNone(self.elso(m)["indulas"])  # Későn kézbesített múltbeli helyzet.

    def test_visszaugras_es_hosszu_res_nem_uj_indulas(self):
        for pontok in ([pont(0, 2, 2), pont(20, 1), pont(40, 2, 2)],
                       [pont(20, 1), pont(141, 2, 2)]):
            m = kis_menet()
            m["poziciok"] = pontok
            self.assertIsNone(self.elso(m)["indulas"])

    def test_teljes_ora_elcsuszas_kulso_ora_nelkul_nem_felismerheto(self):
        m = kis_menet()
        for p in m["poziciok"]:
            p["adat_ido"] += 180
        self.assertEqual(self.elso(m)["keses_mp"], 210)

    def test_nagy_keses_nem_tunik_el_a_rangsorbol(self):
        m = kis_menet()
        for p in m["poziciok"]:
            p["adat_ido"] += 4000
        s = self.elso(m)
        self.assertTrue(s["menetrend_ok"])
        self.assertGreater(s["keses_mp"], 3600)

    def test_vegallomasi_erkezes_kulon_kozrefogassal(self):
        m = kis_menet()
        m["poziciok"] += [pont(210, 3, 2, lat=47.501), pont(230, 3, 1)]
        s = elemzes.mozgasbol_indulasok(m, True)[-1]
        self.assertEqual((s["erkezes_also"], s["erkezes_felso"]), (ALAP + 210, ALAP + 230))
        self.assertIsNone(s["indulas"])

    def test_tu_erkezes_nem_potolja_a_hianyzo_megfigyelest(self):
        self.assertIsNone(self.elso(kis_menet())["erkezes"])


class UtazasiValasztasProba(unittest.TestCase):
    def sor(self, v, t, erkezik):
        return {"vonal_id": v, "menet_id": v + str(t), "szolgalati_nap": "2026-10-17",
                "megallo_id": "M1", "irany": 0,
                "tervezett": t, "indulas": t, "also": t - 5, "felso": t + 5,
                "menetrend_ok": True, "minoseg": "alatamasztott", "jarmu_id": v + str(t),
                "cel_erkezes": erkezik, "cel_also": erkezik - 5, "cel_felso": erkezik + 5}

    def minta(self):
        return [self.sor("A", 0, 1000), self.sor("A", 100, 1100),
                self.sor("B", 10, 200), self.sor("B", 120, 300)]

    def test_kesobbi_busz_rovid_menetideje_felulirja_a_varast(self):
        er = elemzes.buszos_valasztas(self.minta(), 20, 90, [])
        self.assertEqual(er["lefedett_mp"], 70)
        self.assertEqual(er["kesobbi_gyorsabb_mp"], 70)
        s = {r["valasztas"]: r for r in er["valasztasok"]}
        self.assertEqual(s["elso"]["varakozas_mp"], 45)
        self.assertEqual(s["B"]["varakozas_mp"], 65)
        self.assertEqual(s["B"]["menetido_mp"], 180)
        self.assertLess(s["B"]["teljes_felso_mp"], s["elso"]["teljes_also_mp"])

    def test_hianyzo_cel_erkezes_minden_valasztasbol_kiveszi_az_ablakot(self):
        sorok = self.minta()
        sorok[-1]["cel_erkezes"] = None
        self.assertEqual(elemzes.buszos_valasztas(sorok, 20, 90, [])["lefedett_mp"], 0)

    def test_azonos_indulasi_kozepido_nem_valaszt_onkenyesen_buszt(self):
        sorok = self.minta()
        masik = dict(sorok[1], menet_id="MASIK", jarmu_id="MASIK", cel_erkezes=900)
        sorok.append(masik)
        self.assertEqual(elemzes.buszos_valasztas(sorok, 20, 90, [])["lefedett_mp"], 0)

    def test_nem_ismert_indulasi_sorrendnel_nincs_utolagos_elony(self):
        sorok = self.minta()
        sorok[-1].update(indulas=102, also=97, felso=107)
        self.assertEqual(elemzes.buszos_valasztas(sorok, 20, 90, [])["lefedett_mp"], 0)

    def test_ismeretlen_koztes_busz_megszakitja_az_ablakot(self):
        sorok = self.minta()
        hibas = self.sor("B", 60, 240)
        hibas.update(indulas=None, minoseg="bizonytalan")
        sorok.append(hibas)
        self.assertEqual(elemzes.buszos_valasztas(sorok, 20, 90, [])["lefedett_mp"], 0)

    def test_potlojelzes_miatt_is_kimarad(self):
        er = elemzes.buszos_valasztas(self.minta(), 20, 90, [{"vonal_id": "A", "also": 30, "felso": 40}])
        self.assertEqual(er["lefedett_mp"], 0)

    def test_ismeretlen_masik_megallo_nem_tiltja_az_egesz_halozatot(self):
        tiltas = {"vonal_id": None, "also": 30, "felso": 40, "megallo_idk": ["MASIK"]}
        self.assertEqual(elemzes.buszos_valasztas(self.minta(), 20, 90, [tiltas])["lefedett_mp"], 70)
        tiltas["megallo_idk"] = ["M1"]
        self.assertEqual(elemzes.buszos_valasztas(self.minta(), 20, 90, [tiltas])["lefedett_mp"], 0)


class IndulasProba(unittest.TestCase):
    def test_utvonal_teljes_sorrenddel_es_egyedi_menetnapokkal(self):
        menet = kis_menet()
        masik = copy.deepcopy(menet)
        masik["menet_id"] = "T2"
        masik["megallok"][1]["megallo_id"] = "MASIK"
        sorok = elemzes.utvonal_reszletek([menet, copy.deepcopy(menet), masik], date(2026, 10, 17))
        self.assertEqual(len(sorok), 2)
        self.assertEqual({tuple(s["megallo_idk"]) for s in sorok}, {("M1", "M2", "M3"), ("M1", "MASIK", "M3")})
        self.assertTrue(all(len(s["menetek"]) == 1 for s in sorok))

    def test_stabil_indulas_a_megallas_es_tovabbhaladas_kozott(self):
        e = elso(kis_menet())
        self.assertEqual(e["indulas"], ALAP + 30)
        self.assertEqual(e["keses_mp"], 30)
        self.assertEqual(e["minoseg"], "alatamasztott")
        self.assertLessEqual(e["also"], e["indulas"])
        self.assertGreaterEqual(e["felso"], e["indulas"])

    def test_a_kesobbi_stabil_ido_felulirja_az_elso_nullas_becslest(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(15, 10), kozles(60, 30), kozles(90, 30)]
        self.assertEqual(elso(m)["indulas"], ALAP + 30)

    def test_egyetlen_uj_ertek_meg_nem_stabil(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 30), kozles(90, 30), kozles(120, 35)]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_ismetelt_sajat_ido_nem_ket_megerosites(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 30), kozles(60, 30, feed_ido=ALAP + 180)]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_hianyzo_sajat_idot_nem_potol_a_valasz_ideje(self):
        for elso_ido in (None, ALAP + 60):
            with self.subTest(elso_ido=elso_ido):
                m = kis_menet()
                m["kozlesek"] = [kozles(60, 30, adat_ido=elso_ido),
                                 kozles(90, 30, adat_ido=None)]
                e = elso(m)
                self.assertIsNone(e["indulas"])
                self.assertNotIn(e["minoseg"], ("alatamasztott", "kovetett"))

    def test_a_jovobeli_kozlesek_nem_igazolnak_indulast(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(10, 30), kozles(20, 30)]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_a_ritkitas_ne_veszitse_el_a_ket_multbeli_megerositest(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(t, 30) for t in (10, 20, 60, 90)]
        self.assertEqual(elso(m)["minoseg"], "alatamasztott")

    def test_kesobbi_bizonytalan_kozlesnel_kell_a_jarmuves_alatamasztas(self):
        m = kis_menet()
        m["kozlesek"].append(kozles(120, 32, bizonytalansag=30))
        self.assertEqual(elso(m)["indulas"], ALAP + 30)
        m["poziciok"] = [pont(40, 2, 2), pont(160, 3, 2)]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_nincs_adat_allapotot_nem_tekintunk_pontos_indulasnak(self):
        m = kis_menet()
        m["kozlesek"].append(kozles(120, 30, allapot=2))
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_torolt_es_kihagyott_megallo_kulon_marad(self):
        for mezok, minoseg in (({"menet_allapot": 3}, "torolt"),
                              ({"allapot": 1}, "kihagyott")):
            with self.subTest(minoseg=minoseg):
                m = kis_menet()
                m["kozlesek"] = [kozles(60, 30, **mezok), kozles(90, 30, **mezok)]
                self.assertEqual(elso(m)["minoseg"], minoseg)

    def test_kesobbi_torles_nem_torli_a_mar_igazolt_indulast(self):
        m = kis_menet()
        torles = kozles(200, 30, None, adat_ido=None, feed_ido=ALAP + 200,
                        megallo_id=None, menet_allapot=3)
        torles["indulas"] = None
        m["kozlesek"].append(torles)
        e = elso(m)
        self.assertEqual(e["minoseg"], "alatamasztott")
        self.assertEqual(e["indulas"], ALAP + 30)
        self.assertTrue(e["kesobbi_torles"])

    def test_torles_elotti_es_utani_megallas_kulon_marad(self):
        m = kis_menet()
        m["kozlesek"].append(kozles(100, None, None, megallo_id=None, menet_allapot=3))
        # A később közölt megálló-frissítésen is törölt a menet.
        m["kozlesek"].append(kozles(200, None, None, megallo_id=None, menet_allapot=3))
        e = elemzes.indulasok(m)
        self.assertEqual(e[0]["indulas"], ALAP + 30)
        self.assertTrue(e[0]["kesobbi_torles"])
        self.assertEqual(e[1]["minoseg"], "torolt")
        self.assertIsNone(e[1]["indulas"])

    def test_ismetelt_torles_nem_tolhatja_ki_a_hatarat(self):
        m = kis_menet()
        for ido in (50, 200):
            m["kozlesek"].append(kozles(ido, None, None, megallo_id=None, menet_allapot=3))
        self.assertEqual(elso(m)["minoseg"], "torolt")
        self.assertIsNone(elso(m)["indulas"])

    def test_kesobbi_torles_mellett_a_puszta_tovabbhaladas_keves(self):
        m = kis_menet()
        m["poziciok"] = [pont(20, 1, 2), pont(40, 2, 2)]
        self.assertEqual(elso(m)["minoseg"], "kovetett")
        m["kozlesek"].append(kozles(200, None, None, megallo_id=None, menet_allapot=3))
        self.assertEqual(elso(m)["minoseg"], "torolt")

    def test_torles_utan_megerositett_idopont_nem_eleg(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 30), kozles(110, 30),
                         kozles(100, None, None, megallo_id=None, menet_allapot=3),
                         kozles(200, None, None, megallo_id=None, menet_allapot=3)]
        self.assertEqual(elso(m)["minoseg"], "torolt")

    def test_torles_utani_pozicio_nem_igazol_korabbi_indulast(self):
        m = kis_menet()
        m["poziciok"] = [pont(20, 1), pont(110, 2, 2)]
        m["kozlesek"].append(kozles(200, None, None, megallo_id=None, menet_allapot=3))
        m["kozlesek"].append(kozles(100, None, None, megallo_id=None, menet_allapot=3))
        self.assertEqual(elso(m)["minoseg"], "torolt")

    def test_torles_elotti_no_data_vagy_kihagyas_sem_jo_indulas(self):
        for allapot in (1, 2):
            with self.subTest(allapot=allapot):
                m = kis_menet()
                m["kozlesek"].append(kozles(95, 30, allapot=allapot))
                m["kozlesek"].append(kozles(200, None, None, megallo_id=None, menet_allapot=3))
                self.assertEqual(elso(m)["minoseg"], "torolt")

    def test_masik_jarmu_nem_igazolja_a_tovabbhaladast(self):
        m = kis_menet()
        m["poziciok"] = [pont(20, 1), pont(40, 2, 2, jarmu_id="MASIK")]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_sorszamugras_nem_bizonyit_megallast_a_koztes_megalloban(self):
        m = kis_menet()
        m["poziciok"] = [pont(20, 1), pont(160, 3, 2)]
        masodik = elemzes.indulasok(m)[1]
        self.assertNotEqual(masodik["minoseg"], "alatamasztott")

    def test_rossz_helyen_levo_jarmu_nem_ad_biztos_indulast(self):
        m = kis_menet()
        m["poziciok"] = [pont(20, 1, lat=47.49), pont(40, 2, 2, lat=47.48)]
        self.assertNotEqual(elso(m)["minoseg"], "alatamasztott")

    def test_tavoli_visszaugro_sorszam_nem_uj_indulas(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 30), kozles(90, 30)]
        # Már 138 méterrel túl van rajta, majd 206 méternél visszaugrik a sorszám.
        m["poziciok"] = [pont(-6, 2, 2, lat=47.5 + 138 / 111_200),
                         pont(20, 1, 2, lat=47.5 + 206 / 111_200), pont(69, 2, 2)]
        e = elso(m)
        self.assertIsNone(e["indulas"])
        self.assertEqual(e["minoseg"], "bizonytalan")

    def test_tavoli_kozeledo_pont_meg_nem_hiba(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 30), kozles(90, 30)]
        m["poziciok"] = [pont(20, 1, 2, lat=47.5 - 206 / 111_200), pont(69, 2, 2)]
        e = elso(m)
        self.assertEqual(e["indulas"], ALAP + 30)
        self.assertEqual(e["minoseg"], "kovetett")
        self.assertIsNone(e["also"])

    def test_hianyzo_elozo_koordinata_nem_akasztja_meg_az_ellenorzest(self):
        m = kis_menet()
        m["megallok"][0].update(lat=None, lon=None)
        # A sorszám nő, de a koordináta az ellenkező irányba mutat.
        m["poziciok"] = [pont(140, 2), pont(160, 3, 2, lat=47.500)]
        eredmeny = elemzes.indulasok(m)
        self.assertEqual(len(eredmeny), 2)
        self.assertEqual(eredmeny[1]["megallo_id"], "M2")

    def test_korai_erkezes_utan_pontos_indulas(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 0, erkezes=ALAP - 40),
                         kozles(90, 0, erkezes=ALAP - 40)]
        m["poziciok"] = [pont(-5, 1), pont(10, 2, 2)]
        e = elso(m)
        self.assertEqual(e["erkezes"], ALAP - 40)
        self.assertEqual(e["keses_mp"], 0)

    def test_bizonytalan_erkezest_nem_mondunk_pontosnak(self):
        for elso_bizonytalansag, masodik_bizonytalansag in ((None, None), (None, 0), (30, 0)):
            with self.subTest(elso=elso_bizonytalansag, masodik=masodik_bizonytalansag):
                m = kis_menet()
                m["kozlesek"] = [
                    kozles(60, 30, erkezes_bizonytalansag=elso_bizonytalansag),
                    kozles(90, 30, erkezes_bizonytalansag=masodik_bizonytalansag),
                ]
                self.assertIsNone(elso(m)["erkezes"])

    def test_valodi_korai_indulas_elojele_megmarad(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(10, -40), kozles(40, -40)]
        m["poziciok"] = [pont(-45, 1), pont(-30, 2, 2)]
        e = elso(m)
        self.assertEqual(e["indulas"], ALAP - 40)
        self.assertEqual(e["keses_mp"], -40)

    def test_hianyzo_megfigyeles_nem_torles(self):
        m = kis_menet()
        m["kozlesek"] = []
        m["poziciok"] = []
        self.assertEqual(elso(m)["minoseg"], "nem_lattuk")

    def test_vegallomas_es_felszallas_nelkuli_megallo_nem_indulasi_minta(self):
        m = kis_menet()
        m["megallok"][1]["felszallas"] = 1
        self.assertEqual([e["sorrend"] for e in elemzes.indulasok(m)], [1])

    def test_azonos_valasz_nem_gyart_uj_indulast(self):
        m = kis_menet()
        m["kozlesek"] *= 2
        m["poziciok"] *= 2
        esemenyek = elemzes.indulasok(m)
        self.assertEqual(len(esemenyek), 2)
        self.assertEqual(esemenyek[0]["indulas"], ALAP + 30)

    def test_ejfel_utan_is_megmarad_a_szolgalati_nap(self):
        m = kis_menet()
        m["szolgalati_nap"] = "2026-10-16"
        e = elso(m)
        self.assertEqual(e["szolgalati_nap"], "2026-10-16")
        self.assertEqual(e["tervezett"], ALAP)

    def test_a_bemeneti_adat_nem_modosul(self):
        m = kis_menet()
        eredeti = copy.deepcopy(m)
        elemzes.indulasok(m)
        self.assertEqual(m, eredeti)

    def test_uj_jarmu_bizonytalan_kozlese_nem_igazolja_a_regit(self):
        m = kis_menet()
        m["kozlesek"].append(kozles(120, 32, jarmu_id="J2", bizonytalansag=30))
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_torolt_menet_pozicioja_nem_igazolja_a_tovabbhaladast(self):
        m = kis_menet()
        m["poziciok"] = [pont(20, 1, menet_allapot=3), pont(40, 2, 2, menet_allapot=3)]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_orakkal_kesobbi_tovabbhaladas_nem_eleg(self):
        m = kis_menet()
        m["poziciok"] = [pont(20, 1), pont(7200, 2, 2)]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_azonos_sajat_idoju_ellentmondo_poziciok_nem_tovabbhaladas(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 20), kozles(90, 20)]
        m["poziciok"] = [pont(20, 1), pont(20, 2, 2)]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_a_kozolt_ido_elott_mar_tavozott_jarmu_nem_igazolja_a_kesobbi_indulast(self):
        m = kis_menet()
        m["kozlesek"] = [kozles(60, 40), kozles(90, 40)]
        m["poziciok"] = [pont(0, 1), pont(20, 2, 2), pont(50, 2, 2)]
        self.assertEqual(elso(m)["minoseg"], "bizonytalan")

    def test_harom_indulasnal_is_kezelheto_a_forditott_idorend(self):
        m = kis_menet()
        m["megallok"].append({"sorrend": 4, "megallo_id": "M4", "tervezett": ALAP + 360,
                              "tervezett_erkezes": ALAP + 360, "lat": 47.503,
                              "lon": 19.0, "felszallas": 0})
        m["kozlesek"] = [kozles(100, 90), kozles(110, 90),
                         kozles(100, 30, 2), kozles(110, 30, 2),
                         kozles(170, 150, 3), kozles(180, 150, 3)]
        m["poziciok"] = [pont(20, 2), pont(40, 3, 2), pont(80, 1),
                         pont(100, 2, 2), pont(140, 3), pont(160, 4, 2)]
        e = elemzes.indulasok(m)
        self.assertIsNone(e[0]["indulas"])
        self.assertIsNone(e[1]["indulas"])
        self.assertEqual(e[0]["minoseg"], "bizonytalan")


class JarmuAzonositasProba(unittest.TestCase):
    def hianyzo_jarmu(self):
        menet = kis_menet()
        for sor in menet["kozlesek"]:
            sor["jarmu_id"] = None
        return menet

    def test_egyertelmu_menet_potolja_a_tu_jarmuvet_a_forras_atirasa_nelkul(self):
        menet = self.hianyzo_jarmu()
        eredeti = copy.deepcopy(menet)
        eredmeny = elemzes.feldolgozas({"menetek": [menet]}, date(2026, 10, 17))
        self.assertEqual(menet, eredeti)
        self.assertEqual([s["indulas"] for s in eredmeny["esemenyek"]], [ALAP + 30, ALAP + 145])
        self.assertTrue(all(s["jarmu_id"] == "J1" for s in eredmeny["esemenyek"]))
        self.assertEqual(eredmeny["jarmu_azonositas"], [
            {"vonal_id": "3046", "menetbol_azonositott_indulasok": 2, "menetbol_azonositott_menetek": 1}])
        rendes = elemzes.feldolgozas({"menetek": [kis_menet()]}, date(2026, 10, 17))
        self.assertEqual(rendes["jarmu_azonositas"][0]["menetbol_azonositott_indulasok"], 0)

    def test_meglevo_egyezo_azonosito_megmarad_es_ellentmondot_nem_potolunk(self):
        menet = self.hianyzo_jarmu()
        menet["kozlesek"][0]["jarmu_id"] = "J1"
        self.assertEqual(elso(menet)["indulas"], ALAP + 30)
        for ideje in (ALAP + 160, None):
            with self.subTest(ideje=ideje):
                rossz = copy.deepcopy(menet)
                rossz["kozlesek"][2].update(jarmu_id="MASIK", adat_ido=ideje)
                self.assertIsNone(elso(rossz)["indulas"])
        for sor in menet["kozlesek"]:
            sor["jarmu_id"] = "MASIK"
        self.assertIsNone(elso(menet)["indulas"])
        self.assertTrue(all(s["jarmu_id"] == "MASIK" for s in menet["kozlesek"]))

    def test_masik_vp_jarmu_tavol_es_ido_nelkul_is_tiltja_a_potlast(self):
        for ideje in (ALAP + 3600, None):
            with self.subTest(ideje=ideje):
                menet = self.hianyzo_jarmu()
                menet["poziciok"].append(pont(3600, 3, jarmu_id="MASIK", adat_ido=ideje))
                self.assertIsNone(elso(menet)["indulas"])

    def test_hianyzo_vp_azonosito_vagy_sajat_ido_nem_eleg(self):
        for valtozat in ("nincs", "azonosito", "ido"):
            with self.subTest(valtozat=valtozat):
                menet = self.hianyzo_jarmu()
                if valtozat == "nincs":
                    menet["poziciok"] = []
                else:
                    for sor in menet["poziciok"]:
                        sor["jarmu_id" if valtozat == "azonosito" else "adat_ido"] = None
                self.assertIsNone(elso(menet)["indulas"])

    def test_a_tu_sajat_ideje_stabilitasa_es_megalloja_tovabbra_is_kell(self):
        for valtozat in ("ido", "azonos_ido", "valtozo_indulas", "megallo"):
            with self.subTest(valtozat=valtozat):
                menet = self.hianyzo_jarmu()
                if valtozat == "ido":
                    for sor in menet["kozlesek"]:
                        sor["adat_ido"] = None
                elif valtozat == "azonos_ido":
                    menet["kozlesek"][1]["adat_ido"] = menet["kozlesek"][0]["adat_ido"]
                elif valtozat == "valtozo_indulas":
                    menet["kozlesek"][1]["indulas"] += 1
                else:
                    menet["kozlesek"][1]["megallo_id"] = "MASIK"
                self.assertIsNone(elso(menet)["indulas"])

    def test_a_120_masodperces_mozgasi_hatar_nem_valtozik(self):
        menet = self.hianyzo_jarmu()
        menet["poziciok"] = [pont(20, 1), pont(200, 2, 2)]
        self.assertIsNone(elso(menet)["indulas"])

    def test_napi_osszefoglalo_nem_szamolja_duplan_vagy_masnapra_az_indulast(self):
        menet = self.hianyzo_jarmu()
        masik = copy.deepcopy(menet)
        masik["menet_id"] = "T2"
        eredmeny = elemzes.feldolgozas({"menetek": [menet, masik]}, date(2026, 10, 17))
        self.assertEqual(eredmeny["jarmu_azonositas"][0]["menetbol_azonositott_indulasok"], 0)
        masnap = elemzes.feldolgozas({"menetek": [menet]}, date(2026, 10, 18))
        self.assertEqual(masnap["jarmu_azonositas"], [])


class RitkitasProba(unittest.TestCase):
    def test_azonos_sajat_idonel_az_ellentmondas_is_megmarad(self):
        regi = kozles(60, 25, feed_ido=ALAP + 70)
        uj = kozles(60, 30, feed_ido=ALAP + 80)
        eredmeny = elemzes.kozlesek_ritkitasa([uj, regi])
        self.assertEqual(len(eredmeny), 2)
        self.assertEqual({s["indulas"] for s in eredmeny}, {ALAP + 25, ALAP + 30})

    def test_ertek_es_allapotvaltozas_nem_tunik_el(self):
        adatok = [kozles(60, 30), kozles(90, 30), kozles(120, 35),
                  kozles(150, 35), kozles(180, 35, bizonytalansag=30)]
        eredmeny = elemzes.kozlesek_ritkitasa(adatok)
        self.assertEqual({e["indulas"] for e in eredmeny}, {ALAP + 30, ALAP + 35})
        self.assertTrue(any(e["bizonytalansag"] == 30 for e in eredmeny))


class VarakozasProba(unittest.TestCase):
    def test_uj_minositesekkel_is_teljes_a_varakozasi_szamitas(self):
        for minoseg in ("kovetett", "ajtojel", "hev_kozles"):
            sorok = indulasi_sor([0, 120, 600], [0, 120, 600])
            for s in sorok:
                s.update(minoseg=minoseg, modszer=elemzes.MODSZER)
            with self.subTest(minoseg=minoseg):
                parok = elemzes.kovetesi_parok(sorok, 0, 600)
                adat = elemzes.reszidos_varakozas(parok, [0, 120, 600], 0, 600)
                self.assertEqual(adat["lefedett_mp"], 600)
                self.assertEqual(adat["varakozas_mp"], 204)
                self.assertEqual(adat["alatamasztott_parok"], 2)
                teljes = elemzes.kovetes(sorok, 0, 600, szegely=0)
                self.assertEqual(teljes["varakozas_mp"], 204)

    # Két perc, majd nyolc perc követés: az átlagos várás 3 perc 24 másodperc.
    def test_hosszu_kozben_tobb_utas_var(self):
        self.assertAlmostEqual(elemzes.varakozas([0, 120, 600], 0, 600)["varakozas_mp"], 204)
        self.assertAlmostEqual(elemzes.varakozas([0, 300, 600], 0, 600)["varakozas_mp"], 150)

    def test_ablakhataron_tul_indulo_jarmu_is_szamit(self):
        self.assertAlmostEqual(elemzes.varakozas([0, 120, 600], 60, 180)["varakozas_mp"], 240)
        self.assertAlmostEqual(elemzes.varakozas([0, 300, 600], 60, 180)["varakozas_mp"], 180)

    def test_a_valodi_idorend_szamit(self):
        e = elemzes.varakozas([600, 0, 120], 0, 600)
        self.assertAlmostEqual(e["varakozas_mp"], 204)
        self.assertEqual(e["kovetesek_mp"], [120, 480])

    def test_azonos_idopont_ketszer_nem_roviditi_a_varast(self):
        e = elemzes.varakozas([0, 120, 120, 600], 0, 600)
        self.assertAlmostEqual(e["varakozas_mp"], 204)
        self.assertEqual(e["kovetesek_mp"], [120, 0, 480])

    def test_hianyos_idoablakbol_nem_lesz_eszrevetlen_atlag(self):
        for idok, kezdet, veg in (([], 0, 600), ([0, 120], 0, 600),
                                  ([120, 600], 0, 600), ([0, 600], 600, 0)):
            with self.subTest(idok=idok, kezdet=kezdet), self.assertRaises(ValueError):
                elemzes.varakozas(idok, kezdet, veg)


def indulasi_sor(tervezett, tenyleges):
    return [
        {"menet_id": "T" + str(i), "szolgalati_nap": "2026-10-17",
         "vonal_id": "3046", "irany": 0, "sorrend": 1, "megallo_id": "M1",
         "tervezett": terv, "indulas": indulas, "erkezes": indulas,
         "keses_mp": indulas - terv if indulas is not None else None,
         "also": indulas, "felso": indulas,
         "minoseg": "alatamasztott" if indulas is not None else "nem_lattuk",
         "ok": [], "menetrend_ok": True, "jarmu_id": "J" + str(i)}
        for i, (terv, indulas) in enumerate(zip(tervezett, tenyleges))
    ]


class KovetesProba(unittest.TestCase):
    def test_a_varas_kulonbsege_nem_az_atlagos_keses(self):
        sorok = indulasi_sor([0, 300, 600], [0, 120, 600])
        e = elemzes.kovetes(sorok, 0, 600, szegely=0)
        self.assertTrue(e["hasznalhato"])
        self.assertAlmostEqual(e["tervezett_varakozas_mp"], 150)
        self.assertAlmostEqual(e["varakozas_mp"], 204)
        self.assertAlmostEqual(e["tobblet_mp"], 54)

    def test_negativ_varakozasi_kulonbseg_is_megmarad(self):
        sorok = indulasi_sor([0, 120, 600], [0, 300, 600])
        e = elemzes.kovetes(sorok, 0, 600, szegely=0)
        self.assertTrue(e["hasznalhato"])
        self.assertAlmostEqual(e["tobblet_mp"], -54)

    def test_hianyzo_menetbol_nem_gyartunk_hosszu_kovetest(self):
        sorok = indulasi_sor([0, 300, 600], [0, None, 600])
        self.assertFalse(elemzes.kovetes(sorok, 0, 600, szegely=0)["hasznalhato"])

    def test_korai_de_egyenletes_kozlekedesnel_nincs_plusz_varas(self):
        sorok = indulasi_sor([0, 300, 600, 900], [-60, 240, 540, 840])
        e = elemzes.kovetes(sorok, 0, 600, szegely=0)
        self.assertTrue(e["hasznalhato"])
        self.assertAlmostEqual(e["tobblet_mp"], 0)

    def test_masik_idoszak_bizonytalan_indulasa_belog(self):
        sorok = indulasi_sor([0, 300, 600, 900], [0, 300, 600, None])
        sorok[-1].update(jelolt=450, minoseg="bizonytalan")
        self.assertFalse(elemzes.kovetes(sorok, 0, 600, szegely=0)["hasznalhato"])

    def test_idopont_nelkuli_megfigyelt_jarmu_is_elbizonytalanit(self):
        sorok = indulasi_sor([0, 300, 600, 900], [0, 300, 600, None])
        sorok[-1].update(minoseg="bizonytalan", megalloban_idok=[450])
        self.assertFalse(elemzes.kovetes(sorok, 0, 600, szegely=0)["hasznalhato"])

    def test_ismeretlen_extra_menet_a_szegelyben_is_kizarja_az_orat(self):
        idok = list(range(-900, 1501, 300))
        sorok = indulasi_sor(idok, idok)
        for also, felso in ((200, 210), (-300, -200), (800, 950)):
            with self.subTest(also=also, felso=felso):
                e = elemzes.kovetes(sorok, 0, 600,
                                    kizarasok=[{"also": also, "felso": felso}])
                self.assertFalse(e["hasznalhato"])
        e = elemzes.kovetes(sorok, 0, 600, kizarasok=[{"also": 2000, "felso": 2100}])
        self.assertTrue(e["hasznalhato"])


class KovetesiOraProba(unittest.TestCase):
    def test_oraatallitas_napjan_23_vagy_25_kulon_ora_van(self):
        esetek = (
            (date(2026, 3, 29), datetime(2026, 3, 28, 23, tzinfo=UTC), 23, 0),
            (date(2026, 10, 25), datetime(2026, 10, 24, 22, tzinfo=UTC), 25, 2),
        )
        for nap, kezdet, orak, ket_orak in esetek:
            with self.subTest(nap=nap):
                start = int(kezdet.timestamp())
                idok = list(range(start - 1800, start + orak * 3600 + 1801, 300))
                sorok = indulasi_sor(idok, idok)
                for sor in sorok:
                    sor.update(megallo_id="F00935", szolgalati_nap=nap.isoformat())
                eredmeny = elemzes.kovetesi_orak(sorok, nap)
                self.assertEqual(len(eredmeny), orak)
                self.assertEqual(sum(e["ora"] == 2 for e in eredmeny), ket_orak)
                # Ősszel két 02:00 van, de az időzóna miatt két külön időpont.
                idopontok = [datetime.fromisoformat(e["kezdet"]).timestamp() for e in eredmeny]
                self.assertEqual(idopontok, list(range(start, start + orak * 3600, 3600)))

    def test_kozos_buszhoz_kesobbi_ors_es_szokasos_kiszallas_kell(self):
        kezdet = int(datetime(2026, 10, 16, 22, tzinfo=UTC).timestamp())
        idok = list(range(kezdet - 900, kezdet + 4501, 300))
        for ors_helye, kiszallas, vart in ((2, 0, True), (2, 1, False), (2, 2, False),
                                         (2, 3, False), (2, None, False), (0, 0, False),
                                         (None, 0, False)):
            with self.subTest(ors_helye=ors_helye, kiszallas=kiszallas):
                m = kis_menet()
                m["kozlesek"], m["poziciok"] = [], []
                hely = 1 if ors_helye == 0 else 0
                m["megallok"][hely]["megallo_id"] = "F03541"
                if ors_helye is not None:
                    m["megallok"][ors_helye]["megallo_id"] = "008029"
                    if kiszallas is not None:
                        m["megallok"][ors_helye]["kiszallas"] = kiszallas
                megallas = elemzes.indulasok(m)[hely]
                self.assertEqual(megallas["ors_fele"], vart)
                sorok = []
                for vonal in ("0975", "1610", "1695"):
                    vonal_sorai = indulasi_sor(idok, idok)
                    for sor in vonal_sorai:
                        sor.update(vonal_id=vonal, megallo_id="F03541", ors_fele=megallas["ors_fele"])
                    sorok.extend(vonal_sorai)
                orak = elemzes.kovetesi_orak(sorok, date(2026, 10, 17))
                kozos = [s for s in orak if len(s["vonalak"]) == 3]
                self.assertEqual(len(kozos), 24 if vart else 0)
                if vart:
                    self.assertTrue(kozos[0]["hasznalhato"])


class ReszidosKovetesProba(unittest.TestCase):
    def szamol(self, terv, tenyleges, kezdet, veg, kizarasok=()):
        sorok = indulasi_sor(terv, tenyleges)
        parok = elemzes.kovetesi_parok(sorok, kezdet, veg, kizarasok)
        return elemzes.reszidos_varakozas(parok, terv, kezdet, veg)

    def test_hianyzo_indulas_ket_oldalan_a_jo_reszek_megmaradnak(self):
        e = self.szamol([0, 100, 200, 300, 400], [0, 100, None, 300, 400], 0, 400)
        self.assertEqual(e["parok"], 2)
        self.assertEqual(e["lefedett_mp"], 200)
        self.assertEqual(e["kimaradt_mp"], 200)
        self.assertEqual(e["lefedettseg"], 0.5)
        self.assertEqual(e["varakozas_mp"], 50)
        self.assertEqual(e["tobblet_mp"], 0)

    def test_a_nulladik_idopont_is_indulas(self):
        e = self.szamol([0, 100], [0, 100], 0, 100)
        self.assertTrue(e["hasznalhato"])
        self.assertEqual(e["parok"], 1)

    def test_a_valodi_sorrendcsere_megmarad(self):
        e = self.szamol([0, 100, 200, 300], [0, 200, 100, 300], 0, 300)
        self.assertEqual(e["parok"], 3)
        self.assertEqual(e["median_kovetes_mp"], 100)
        self.assertEqual(e["lefedett_mp"], 300)

    def test_masik_blokkbol_kozbeert_elfogadott_jarmuvet_nem_ugorjuk_at(self):
        e = self.szamol([0, 100, 200, 300, 400], [0, 300, None, 100, 200], 0, 400)
        self.assertEqual(e["parok"], 1)
        self.assertEqual(e["lefedett_mp"], 100)

    def test_bizonytalan_tartomany_pont_nelkul_is_metszheti_a_part(self):
        sorok = indulasi_sor([300, 600, 900], [None, 600, 900])
        sorok[0].update(jelolt=950, megalloban_idok=[550])
        self.assertEqual(elemzes.kovetesi_parok(sorok, 600, 900), [])

    def test_igazolt_indulast_nem_kotunk_ossze_egy_regi_megallassal(self):
        sorok = indulasi_sor([0, 100, 200, 300], [900, None, 100, 200])
        sorok[0]["megalloban_idok"] = [-100, 850]
        parok = elemzes.kovetesi_parok(sorok, 0, 300)
        self.assertEqual([(p["elso"], p["masodik"]) for p in parok], [(100, 200)])

    def test_a_bizonytalan_jelolt_es_megallasi_pont_is_szamit(self):
        for plusz in ({"jelolt": 700}, {"megalloban_idok": [700]}, {"jelolt": 600}):
            with self.subTest(plusz=plusz):
                sorok = indulasi_sor([300, 600, 900], [None, 600, 900])
                sorok[0].update(plusz)
                self.assertEqual(elemzes.kovetesi_parok(sorok, 600, 900), [])

    def test_az_extra_menetet_a_teljes_kovetesi_kozben_vizsgaljuk(self):
        e = self.szamol([0, 600], [0, 600], 100, 200, [{"also": 500, "felso": 550}])
        self.assertEqual(e["lefedett_mp"], 0)
        self.assertIsNone(e["varakozas_mp"])

    def test_mas_idoszak_potlasa_nem_veszi_el_a_jo_part(self):
        e = self.szamol([0, 600], [0, 600], 100, 200, [{"also": 700, "felso": 800}])
        self.assertEqual(e["lefedett_mp"], 100)

    def test_a_teljes_menetrendbol_szamoljuk_az_azonos_idoszakot(self):
        # A követhető blokkhoz későbbi terv tartozik, de az utas korábban vár.
        e = self.szamol([0, 100, 200, 300], [None, None, 50, 250], 50, 250)
        self.assertEqual(e["varakozas_mp"], 100)
        self.assertEqual(e["tervezett_varakozas_mp"], 50)
        self.assertEqual(e["tobblet_mp"], 50)

    def test_hianyzo_tervperemnel_nincs_osszehasonlitas(self):
        e = self.szamol([100, 200], [0, 300], 0, 300)
        self.assertFalse(e["hasznalhato"])
        self.assertEqual(e["lefedett_mp"], 0)

    def test_egyszerre_indulo_ket_jarmu_nem_ad_dupla_varakozasi_idot(self):
        e = self.szamol([0, 100, 200, 300], [0, 100, 100, 300], 0, 300)
        self.assertEqual(e["lefedett_mp"], 300)
        self.assertAlmostEqual(e["varakozas_mp"], (100 ** 2 + 200 ** 2) / 600)
        self.assertEqual(e["parok"], 3)
        self.assertEqual(e["par_reszletek"], 2)
        self.assertEqual(e["nulla_kovetes"], 1)
        self.assertEqual(e["median_kovetes_mp"], 100)

    def test_oraatlogo_par_ket_reszlet_de_a_nullakoz_nem_idotartam(self):
        parok = [{"elso": 0, "masodik": 7200, "alatamasztott": True},
                 {"elso": 3600, "masodik": 3600, "alatamasztott": True}]
        terv = [0, 3600, 7200]
        teljes = elemzes.reszidos_varakozas(parok, terv, 0, 7200)
        orak = [elemzes.reszidos_varakozas(parok, terv, i, i + 3600) for i in (0, 3600)]
        self.assertEqual(teljes["par_reszletek"], 1)
        self.assertEqual(sum(s["par_reszletek"] for s in orak), 2)
        self.assertEqual(sum(s["lefedett_mp"] for s in orak), teljes["lefedett_mp"])
        self.assertEqual(teljes["nulla_kovetes"], 1)

    def test_hosszal_sulyozunk_nem_a_reszek_atlagat_atlagoljuk(self):
        e = self.szamol([0, 300, 600], [0, 120, 600], 0, 600)
        self.assertEqual(e["varakozas_mp"], 204)
        self.assertEqual(e["tervezett_varakozas_mp"], 150)
        self.assertEqual(e["tobblet_mp"], 54)

    def test_masodpercenkenti_fuggetlen_szamitas_egyezik(self):
        terv, tenyleges = [0, 100, 250, 600], [0, 200, 300, 600]
        e = self.szamol(terv, tenyleges, 45, 510)
        for idok, mezo in ((terv, "tervezett_varakozas_mp"), (tenyleges, "varakozas_mp")):
            # Minden másodperc közepén érkező utas következő indulásig vár.
            varas = sum(min(x for x in idok if x > t + 0.5) - (t + 0.5) for t in range(45, 510))
            self.assertAlmostEqual(e[mezo], varas / 465)

    def test_keves_adatbol_nincs_nullaval_kitoltott_eredmeny(self):
        for terv, tenyleges in (([], []), ([0], [0]), ([0, 100], [0, None])):
            with self.subTest(terv=terv):
                e = self.szamol(terv, tenyleges, 0, 600)
                self.assertFalse(e["hasznalhato"])
                self.assertIsNone(e["tobblet_mp"])
                self.assertEqual(e["kimaradt_mp"], 600)

    def test_mas_peron_es_forditott_idoablak_hiba(self):
        sorok = indulasi_sor([0, 100], [0, 100])
        with self.assertRaises(ValueError):
            elemzes.kovetesi_parok(sorok, 100, 0)
        sorok[-1]["megallo_id"] = "M2"
        with self.assertRaises(ValueError):
            elemzes.kovetesi_parok(sorok, 0, 100)

    def test_napi_es_oras_sulyozas_oraatallitaskor_is_egyezik(self):
        for nap, kezdet, orak in ((date(2026, 3, 29), datetime(2026, 3, 28, 23, tzinfo=UTC), 23),
                                 (date(2026, 10, 25), datetime(2026, 10, 24, 22, tzinfo=UTC), 25)):
            with self.subTest(nap=nap):
                start = int(kezdet.timestamp())
                terv = list(range(start - 300, start + orak * 3600 + 601, 300))
                sorok = indulasi_sor(terv, [t + 50 for t in terv])
                for sor in sorok:
                    sor.update(megallo_id="F00935")
                e = elemzes.kovetesi_reszek(sorok, nap)
                napi, oras = e["naponta"][0], e["orankent"]
                self.assertEqual(len(oras), orak)
                self.assertEqual(napi["lefedett_mp"], orak * 3600)
                self.assertEqual(sum(s["lefedett_mp"] for s in oras), napi["lefedett_mp"])
                self.assertAlmostEqual(sum(s["lefedett_mp"] * s["varakozas_mp"] for s in oras)
                                       / napi["lefedett_mp"], napi["varakozas_mp"])
                self.assertAlmostEqual(napi["tobblet_mp"], 0)
                self.assertEqual(len({s["kezdet"] for s in oras}), orak)


class KozosBuszProba(unittest.TestCase):
    def orak(self):
        vonalak = ["0975", "1610", "1695"]
        return [
            {"megallo_id": "F03541", "kezdet": "2026-10-17T10:00:00+02:00",
             "vonalak": csoport, "hasznalhato": True, "varakozas_mp": varas,
             "indulasok": darab}
            for csoport, varas, darab in ((vonalak, 90, 20), ([vonalak[0]], 150, 9),
                                         ([vonalak[1]], 450, 4), ([vonalak[2]], 300, 7))
        ]

    def test_hianyos_vagy_mas_orabol_szamolt_eredmeny_nem_osszevetheto(self):
        for eset in ("hianyzik", "mas_ora", "kulon_bizonytalan", "egyutt_bizonytalan"):
            with self.subTest(eset=eset):
                sorok = self.orak()
                if eset == "hianyzik":
                    sorok.pop()
                elif eset == "mas_ora":
                    sorok[-1]["kezdet"] = "2026-10-17T11:00:00+02:00"
                elif eset == "kulon_bizonytalan":
                    sorok[-1]["hasznalhato"] = False
                else:
                    sorok[0]["hasznalhato"] = False
                self.assertEqual(elemzes.kozos_buszok(sorok), [])

    def test_teljes_ora_kulon_vonalainak_varakozasai_atlagolas_nelkul_maradnak(self):
        e = elemzes.kozos_buszok(list(reversed(self.orak())))
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["kezdet"], "2026-10-17T10:00:00+02:00")
        self.assertEqual(e[0]["indulasok"], 20)
        self.assertEqual(e[0]["egyutt_mp"], 90)
        self.assertEqual(e[0]["kulon_mp"], {"0975": 150, "1610": 450, "1695": 300})


class IsmetlesProba(unittest.TestCase):
    def test_ket_menethez_rendelt_ugyanazon_jarmu_nem_ket_indulas(self):
        sorok = indulasi_sor([0, 30, 600], [0, 30, 600])
        for sor in sorok:
            sor["jarmu_id"] = "J1"
        elemzes.ismetlesek(sorok)
        self.assertIsNone(sorok[0]["indulas"])
        self.assertIsNone(sorok[1]["indulas"])
        self.assertEqual(sorok[2]["indulas"], 600)

    def test_kulon_jarmuvek_kozeli_indulasa_lehet_valodi_torlodas(self):
        sorok = indulasi_sor([0, 30], [0, 30])
        elemzes.ismetlesek(sorok)
        self.assertEqual([s["indulas"] for s in sorok], [0, 30])

    def test_azonos_menetazonosito_mas_szolgalati_napon_masik_menet(self):
        sorok = indulasi_sor([ALAP, ALAP + 30], [ALAP, ALAP + 30])
        for sor, nap in zip(sorok, ("2026-10-16", "2026-10-17")):
            sor.update(menet_id="T1", jarmu_id="J1", szolgalati_nap=nap)
        elemzes.ismetlesek(sorok)
        self.assertEqual([s["indulas"] for s in sorok], [None, None])
        self.assertTrue(all(s["minoseg"] == "bizonytalan" for s in sorok))


class OsszegzesProba(unittest.TestCase):
    def test_pontos_eloszlasbol_tobb_nap_minden_megfigyelese_osszevonhato(self):
        egyutt = Counter()
        napi_medianok = []
        for kesesek in ([-60, 0, 0, 60], [600]):
            terv = [ALAP + i * 600 for i in range(len(kesesek))]
            sorok = indulasi_sor(terv, [t + k for t, k in zip(terv, kesesek)])
            eredmeny = elemzes.osszegzes(sorok, date(2026, 10, 17))
            vonal = eredmeny["vonalak"][0]
            egyutt.update(dict(vonal["keses_eloszlas"]))
            napi_medianok.append(vonal["median_keses_mp"])
            self.assertEqual(sum(db for _, db in vonal["keses_eloszlas"]), vonal["keseshez_hasznalt"])
            oras = Counter()
            for sor in eredmeny["orankent"]:
                oras.update(dict(sor["keses_eloszlas"]))
            self.assertEqual(oras, Counter(kesesek))
        ertekek = list(egyutt.elements())
        self.assertEqual(median(ertekek), 0)
        self.assertEqual(sum(napi_medianok) / len(napi_medianok), 300)
        self.assertAlmostEqual(elemzes.p90(ertekek), 384)

    def test_elozo_naprol_atnyulo_es_aznapi_menet_kulon_szamit(self):
        sorok = indulasi_sor([ALAP, ALAP + 600], [ALAP, ALAP + 600])
        for sor, nap in zip(sorok, ("2026-10-16", "2026-10-17")):
            sor.update(menet_id="T1", szolgalati_nap=nap)
        vonal = elemzes.osszegzes(sorok, date(2026, 10, 17))["vonalak"][0]
        self.assertEqual(vonal["tervezett_menetek"], 2)
        self.assertEqual(vonal["hasznalt_menetek"], 2)

    def test_szakaszvaltozas_csak_ugyanazon_menet_szomszedos_megalloibol(self):
        terv = [ALAP + i * 600 for i in range(8)]
        sorok = indulasi_sor(terv, [t + k for t, k in zip(terv, (10, 50, 400, -200, 0, 90, 0, 90))])
        hozzarendeles = (("T1", 1), ("T1", 2), ("T2", 1), ("T3", 2),
                        ("T4", 1), ("T4", 3), ("T5", 1), ("T5", 2))
        for sor, (menet, sorszam) in zip(sorok, hozzarendeles):
            sor.update(menet_id=menet, sorrend=sorszam, kovetkezo_sorrend=sorszam + 1,
                       megallo_id="M" + str(sorszam), jarmu_id=menet)
        sorok[-1]["jarmu_id"] = "masik"
        # T2 és T3 nem pár; T4 átugrik egy megállót; T5 járművet váltott.
        szakaszok = elemzes.osszegzes(sorok, date(2026, 10, 17))["szakaszok"]
        self.assertEqual(len(szakaszok), 1)
        self.assertEqual(szakaszok[0]["n"], 1)
        self.assertEqual(szakaszok[0]["median_valtozas_mp"], 40)
        self.assertEqual(szakaszok[0]["valtozas_eloszlas"], [[40, 1]])

    def test_korai_erkezes_utan_a_kivart_indulas_nem_korai_indulas(self):
        terv = [ALAP, ALAP + 600, ALAP + 1200]
        sorok = indulasi_sor(terv, [terv[0], terv[1] - 20, terv[2] + 20])
        for sor in sorok:
            sor.update(erkezes=sor["tervezett"] - 40, tervezett_erkezes=sor["tervezett"])
        vonal = elemzes.osszegzes(sorok, date(2026, 10, 17))["vonalak"][0]
        self.assertEqual(vonal["koran_erkezett"], 3)
        self.assertEqual(vonal["megvarta_indulast"], 2)
        self.assertEqual(vonal["korai_indulas"], 1)
        self.assertEqual(vonal["median_keses_mp"], 0)

    def test_korai_erkezes_es_kivart_indulas_teljes_idokeretbol(self):
        sorok = indulasi_sor([ALAP, ALAP + 600, ALAP + 1200], [ALAP + 5, ALAP + 605, ALAP + 1205])
        for sor in sorok:
            t = sor["tervezett"]
            sor.update(erkezes=t - 20, erkezes_felso=t - 10, tervezett_erkezes=t, also=t + 1)
        sorok[0]["erkezes_felso"] = ALAP + 5
        sorok[1]["also"] = ALAP + 590
        vonal = elemzes.osszegzes(sorok, date(2026, 10, 17))["vonalak"][0]
        self.assertEqual(vonal["koran_erkezett"], 2)
        self.assertEqual(vonal["megvarta_indulast"], 1)

    def test_nagy_negativ_elteres_lathato_marad_de_nem_megy_a_fokesesbe(self):
        sorok = indulasi_sor([ALAP + 600, ALAP + 1200], [ALAP, ALAP + 1300])
        sorok[0]["menetrend_ok"] = False
        vonal = elemzes.osszegzes(sorok, date(2026, 10, 17))["vonalak"][0]
        self.assertEqual(vonal["fizikai_indulas"], 2)
        self.assertEqual(vonal["ellenorizendo_menetrend"], 1)
        self.assertEqual(vonal["keseshez_hasznalt"], 1)
        self.assertEqual(vonal["median_minden_jelolttel_mp"], -250)
        self.assertEqual(vonal["median_keses_mp"], 100)
        self.assertEqual(vonal["keses_eloszlas"], [[100, 1]])

    def test_oras_lefedettsegben_a_nem_latott_indulas_a_nevezoben_marad(self):
        sorok = indulasi_sor([ALAP, ALAP + 300, ALAP + 600],
                            [ALAP + 30, None, ALAP + 600])
        eredmeny = elemzes.osszegzes(sorok, date(2026, 10, 17))
        ora = eredmeny["orankent"][0]
        self.assertEqual(ora["tervezett"], 3)
        self.assertEqual(ora["n"], 2)
        self.assertAlmostEqual(ora["lefedettseg"], 2 / 3)
        self.assertEqual(ora["median_keses_mp"], 15)
        self.assertEqual(eredmeny["vonalak"][0]["minoseg"]["nem_lattuk"], 1)

    def test_szakaszparok_lefedettsege_a_hianyos_es_jarmuvalto_menetet_is_szamolja(self):
        terv = [ALAP + i * 120 for i in range(6)]
        sorok = indulasi_sor(terv, [terv[0] + 30, terv[1] + 90, terv[2], None,
                                   terv[4] + 40, terv[5] + 60])
        for i, sor in enumerate(sorok):
            sorrend = i % 2 + 1
            sor.update(menet_id="T" + str(i // 2), jarmu_id="J" + str(i // 2),
                       sorrend=sorrend, kovetkezo_sorrend=sorrend + 1,
                       megallo_id="M" + str(sorrend))
        sorok[-1]["jarmu_id"] = "MASIK"
        szakasz = elemzes.osszegzes(sorok, date(2026, 10, 17))["szakaszok"][0]
        self.assertEqual(szakasz["tervezett_parok"], 3)
        self.assertEqual(szakasz["n"], 1)
        self.assertAlmostEqual(szakasz["lefedettseg"], 1 / 3)
        self.assertEqual(szakasz["median_valtozas_mp"], 60)

    def test_a_foszamitas_megtartja_a_kovetheto_athaladast(self):
        menet = kis_menet()
        # A második megállóból a továbbhaladás látszik, külön álló pont már nincs.
        menet["poziciok"] = [p for p in menet["poziciok"] if p["adat_ido"] != ALAP + 140]
        minta = {"menetek": [menet], "kizarasok": []}
        eredeti = copy.deepcopy(minta)
        eredmeny = elemzes.feldolgozas(minta, date(2026, 10, 17))
        fo = eredmeny["vonalak"][0]
        kontroll = eredmeny["kontroll"]["vonalak"][0]
        self.assertEqual(fo["keseshez_hasznalt"], 2)
        self.assertEqual(kontroll["keseshez_hasznalt"], 1)
        self.assertEqual(fo["tervezett"], kontroll["tervezett"])
        self.assertEqual(kontroll["lefedettseg"], 0.5)
        self.assertEqual(fo["keses_eloszlas"], [[25, 1], [30, 1]])
        self.assertEqual(eredmeny["korabbi_modszer"][0]["keses_eloszlas"], [[30, 1]])
        self.assertEqual(kontroll["keses_eloszlas"], [[30, 1]])
        self.assertEqual(eredmeny["szakaszok"][0]["valtozas_eloszlas"], [[-5, 1]])
        self.assertEqual(eredmeny["kontroll"]["szakaszok"][0]["valtozas_eloszlas"], [])
        masodik = eredmeny["esemenyek"][1]
        self.assertEqual(masodik["esemeny_tipus"], "tovabbhaladas")
        self.assertEqual(masodik["indulas"], ALAP + 145)
        self.assertEqual(masodik["keses_mp"], 25)
        self.assertEqual(minta, eredeti)

    def test_teljesen_hianyzo_ora_es_szakasz_ismeretlen_ertekkel_megmarad(self):
        sorok = indulasi_sor([ALAP, ALAP + 120, ALAP + 3600],
                            [None, None, ALAP + 3630])
        for i, sor in enumerate(sorok[:2]):
            sor.update(menet_id="HIANYZIK", sorrend=i + 1, kovetkezo_sorrend=i + 2,
                       megallo_id="M" + str(i + 1))
        eredmeny = elemzes.osszegzes(sorok, date(2026, 10, 17))
        orak = {s["ora"]: s for s in eredmeny["orankent"]}
        self.assertEqual(orak[2]["tervezett"], 2)
        self.assertEqual(orak[2]["n"], 0)
        self.assertEqual(orak[2]["lefedettseg"], 0)
        self.assertIsNone(orak[2]["median_keses_mp"])
        self.assertEqual(orak[2]["keses_eloszlas"], [])
        self.assertEqual(orak[3]["n"], 1)
        self.assertEqual(orak[3]["median_keses_mp"], 30)
        self.assertEqual(len(eredmeny["szakaszok"]), 1)
        szakasz = eredmeny["szakaszok"][0]
        self.assertEqual(szakasz["tervezett_parok"], 1)
        self.assertEqual(szakasz["n"], 0)
        self.assertEqual(szakasz["lefedettseg"], 0)
        self.assertIsNone(szakasz["median_valtozas_mp"])
        self.assertEqual(szakasz["valtozas_eloszlas"], [])


class MenetLathatosagProba(unittest.TestCase):
    def test_jelenlet_nem_azonos_az_igazolt_indulassal_es_ismetles_nem_duplaz(self):
        menetek = []
        for azonosito, vp, tu in (("CSAK_VP", True, False), ("CSAK_TU", False, True),
                                  ("MINDKETTO", True, True), ("HIANYZIK", False, False)):
            menet = kis_menet()
            menet.update(menet_id=azonosito, poziciok=[{"adat_ido": None}] if vp else [],
                         kozlesek=[{"menet_allapot": 3}] if tu else [])
            menetek.append(menet)
        menetek += [copy.deepcopy(menetek[0]), copy.deepcopy(menetek[-1])]
        sor = elemzes.menet_lathatosag(menetek, date(2026, 10, 17))[0]
        self.assertEqual(sor["tervezett_menetek"], 4)
        self.assertEqual(sor["latott_menetek"], 3)
        self.assertEqual(sor["nem_latott_menetek"], 1)
        self.assertEqual(sor["pozicioval"], 2)
        self.assertEqual(sor["menetfrissitessel"], 2)
        self.assertEqual(len(sor["menetek"]), 4)

    def test_naphataron_atnyulo_menet_ket_exportbol_is_egyszer_vonhato_ossze(self):
        menet = kis_menet()
        menet.update(szolgalati_nap="2026-10-16", poziciok=[], kozlesek=[])
        for sor, ido in zip(menet["megallok"], (ALAP - 7201, ALAP - 7199, ALAP - 7100)):
            sor["tervezett"] = ido
        elso = elemzes.menet_lathatosag([menet], date(2026, 10, 16))
        menet["poziciok"] = [{"adat_ido": None}]
        masodik = elemzes.menet_lathatosag([menet], date(2026, 10, 17))
        self.assertEqual(elso[0]["tervezett_menetek"], 1)
        self.assertEqual(masodik[0]["tervezett_menetek"], 1)
        egyedi = {}
        for vonal in elso + masodik:
            for m in vonal["menetek"]:
                kulcs = (vonal["vonal_id"], m["menet_id"], m["szolgalati_nap"])
                egyedi[kulcs] = egyedi.get(kulcs, False) or m["pozicio"] or m["menetfrissites"]
        self.assertEqual(len(egyedi), 1)
        self.assertEqual(sum(egyedi.values()), 1)

    def test_csak_vegallomasi_erkezes_es_nincs_felszallas_nem_napi_tervezett_menet(self):
        terminalis = kis_menet()
        for sor, ido in zip(terminalis["megallok"], (ALAP - 7300, ALAP - 7201, ALAP - 7199)):
            sor["tervezett"] = ido
        nincs_felszallas = kis_menet()
        for sor in nincs_felszallas["megallok"]:
            sor["felszallas"] = 1
        self.assertEqual(elemzes.menet_lathatosag([terminalis, nincs_felszallas], date(2026, 10, 17)), [])

    def test_azonos_azonosito_mas_szolgalati_napon_kulon_menet(self):
        menetek = [kis_menet(), kis_menet()]
        menetek[0]["szolgalati_nap"] = "2026-10-16"
        sor = elemzes.menet_lathatosag(menetek, date(2026, 10, 17))[0]
        self.assertEqual(sor["tervezett_menetek"], 2)
        self.assertEqual(sor["latott_menetek"], 2)

    def test_potlo_kizaras_es_kulon_jelenlet_nem_irja_at_a_regi_indulasi_eredmenyt(self):
        menet = kis_menet()
        menet.update(poziciok=[], kozlesek=[])
        minta = {"menetek": [menet], "kizarasok": [
            {"vonal_id": "VP46", "potolt_vonal_id": "3046", "menet_id": "EXTRA",
             "szolgalati_nap": "2026-10-17", "also": ALAP, "felso": ALAP + 300}]}
        eredeti = elemzes.feldolgozas(minta, date(2026, 10, 17))
        menet["megfigyeles_jelenlet"] = {"pozicioval": True, "menetfrissitessel": False}
        uj = elemzes.feldolgozas(minta, date(2026, 10, 17))
        self.assertEqual(eredeti["menet_lathatosag"][0]["nem_latott_menetek"], 1)
        self.assertEqual(uj["menet_lathatosag"][0]["latott_menetek"], 1)
        self.assertEqual(uj["menet_lathatosag"][0]["tervezett_menetek"], 1)
        for kulcs in eredeti.keys() - {"keszult_utc", "menet_lathatosag"}:
            self.assertEqual(uj[kulcs], eredeti[kulcs])
        # Az új adatbázisos minta már megtartja a saját idő nélküli VP-t is.
        menet["poziciok"] = [{"adat_ido": None}]
        self.assertEqual(elemzes.ellenorzott_indulasok(menet), eredeti["esemenyek"])
        menet["megfigyeles_jelenlet"]["pozicioval"] = False
        self.assertEqual(elemzes.menet_lathatosag([menet], date(2026, 10, 17))[0]["latott_menetek"], 1)


class IranyProba(unittest.TestCase):
    def test_valtozatok_eredeti_vegallomasai_es_menetszamai_megmaradnak(self):
        alap = kis_menet()
        masik = copy.deepcopy(alap)
        masik["menet_id"] = "T2"
        masik["megallok"][-1]["megallo_id"] = "MASIK_VEG"
        vissza = copy.deepcopy(alap)
        vissza.update(menet_id="T3", irany=1)
        for sor, nev in zip(vissza["megallok"], ("M3", "M2", "M1")):
            sor["megallo_id"] = nev
        # A lista tárolási sorrendje és a duplán átadott menet nem változtat az eredményen.
        masik["megallok"].reverse()
        menetek = [masik, vissza, alap, copy.deepcopy(alap)]
        eredeti = copy.deepcopy(menetek)
        eredmeny = elemzes.menetrendi_iranyok(menetek, date(2026, 10, 17))
        self.assertEqual(eredmeny, [
            {"vonal_id": "3046", "irany": 0, "utvonalak": [
                {"elso_megallo_id": "M1", "utolso_megallo_id": "M3", "tervezett_menetek": 1},
                {"elso_megallo_id": "M1", "utolso_megallo_id": "MASIK_VEG", "tervezett_menetek": 1}]},
            {"vonal_id": "3046", "irany": 1, "utvonalak": [
                {"elso_megallo_id": "M3", "utolso_megallo_id": "M1", "tervezett_menetek": 1}]}])
        self.assertEqual(menetek, eredeti)

    def test_iranyokban_csak_a_nap_felszallasi_indulasaihoz_tartozo_menetek_szamitanak(self):
        alap = kis_menet()
        atnyulo = copy.deepcopy(alap)
        atnyulo["szolgalati_nap"] = "2026-10-16"
        masnap = copy.deepcopy(alap)
        masnap["szolgalati_nap"] = "2026-10-18"
        for sor in masnap["megallok"]:
            sor["tervezett"] += 86400
        nincs_felszallas = copy.deepcopy(alap)
        nincs_felszallas["menet_id"] = "URES"
        for sor in nincs_felszallas["megallok"]:
            sor["felszallas"] = 1
        eredmeny = elemzes.menetrendi_iranyok(
            [alap, atnyulo, masnap, nincs_felszallas], date(2026, 10, 17))
        self.assertEqual(eredmeny[0]["utvonalak"][0]["tervezett_menetek"], 2)
        minta = {"menetek": [alap], "megallo_nevek": {"M1": "Első", "M3": "Utolsó"}}
        export = elemzes.feldolgozas(minta, date(2026, 10, 17))
        self.assertEqual(export["iranyok"][0]["utvonalak"][0]["utolso_megallo_id"], "M3")
        self.assertEqual(export["megallo_nevek"]["M3"], "Utolsó")

    def test_kozos_kovetesi_hely_iranya_vonalankent_marad_meg(self):
        sorok = indulasi_sor([ALAP, ALAP + 100, ALAP + 200], [ALAP, ALAP + 100, ALAP + 200])
        for sor, vonal, irany in zip(sorok, ("0975", "1610", "1695"), (0, 1, 0)):
            sor.update(vonal_id=vonal, irany=irany, megallo_id="F03541", ors_fele=True)
        csoportok = list(elemzes.kovetesi_csoportok(sorok, []))
        kozos = next(hely for hely, _, _ in csoportok if len(hely["vonalak"]) == 3)
        self.assertEqual(kozos["iranyok"], [
            {"vonal_id": "0975", "irany": 0}, {"vonal_id": "1610", "irany": 1},
            {"vonal_id": "1695", "irany": 0}])


class MentettPeldaProba(unittest.TestCase):
    # Két 2026. október 17-i eset néhány sora, a mentett BKK-válaszokból.
    def test_nyugati_korrigalt_indulas_080924(self):
        m = kis_menet()
        m.update(menet_id="D225124130", vonal_id="3046")
        m["megallok"] = [
            {"sorrend": 7, "megallo_id": "F00935", "tervezett": 1792217160,
             "tervezett_erkezes": 1792217160, "lat": 47.509922, "lon": 19.056658, "felszallas": 0},
            {"sorrend": 8, "megallo_id": "F01081", "tervezett": 1792217280,
             "tervezett_erkezes": 1792217280, "lat": 47.505586, "lon": 19.06287, "felszallas": 0},
        ]
        # Saját idő, válasz ideje, indulás, indulási bizonytalanság.
        m["kozlesek"] = [
            kozles(ido - ALAP, indul - ALAP, 7, megallo_id="F00935", jarmu_id="2011",
                   feed_ido=feed, erkezes=1792217329, bizonytalansag=bizonytalan)
            for ido, feed, indul, bizonytalan in (
                (1792217329, 1792217339, 1792217329, 0),
                (1792217346, 1792217360, 1792217356, None),
                (1792217395, 1792217399, 1792217364, 0),
                (1792218644, 1792222248, 1792217364, 0),
            )
        ]
        m["poziciok"] = [
            pont(1792217346 - ALAP, 7, megallo_id="F00935", jarmu_id="2011",
                 lat=47.510013580322266, lon=19.05654525756836),
            pont(1792217379 - ALAP, 8, 2, megallo_id="F01081", jarmu_id="2011",
                 lat=47.509647369384766, lon=19.056859970092773),
            pont(1792217412 - ALAP, 8, 2, megallo_id="F01081", jarmu_id="2011",
                 lat=47.50843048095703, lon=19.05887794494629),
        ]
        e = elso(m)
        self.assertEqual(e["indulas"], 1792217364)  # 08:09:24 magyar idő szerint.
        self.assertEqual(e["keses_mp"], 204)
        self.assertEqual(e["minoseg"], "alatamasztott")

    def test_az_egyes_villamos_kesobbi_modellje_nem_irja_felul_az_indulast(self):
        m = kis_menet()
        m.update(menet_id="D23436193", vonal_id="3010")
        m["megallok"] = [
            {"sorrend": 2, "megallo_id": "F00587", "tervezett": 1792226700,
             "tervezett_erkezes": 1792226700, "lat": 47.544884, "lon": 19.03477, "felszallas": 0},
            {"sorrend": 3, "megallo_id": "F00615", "tervezett": 1792226760,
             "tervezett_erkezes": 1792226760, "lat": 47.541116, "lon": 19.040536, "felszallas": 0},
        ]
        m["kozlesek"] = [
            kozles(ido - ALAP, indul - ALAP, 2, megallo_id="F00587", jarmu_id="5833",
                   feed_ido=feed, erkezes=erkezik, bizonytalansag=bizonytalan,
                   erkezes_bizonytalansag=bizonytalan)
            for ido, feed, indul, erkezik, bizonytalan in (
                (1792226230, 1792226236, 1792226211, 1792226189, 0),
                (1792227544, 1792227551, 1792226211, 1792226189, 0),
                (1792229262, 1792233040, 1792226338, 1792226338, 30),
            )
        ]
        m["poziciok"] = [
            pont(1792226210 - ALAP, 2, megallo_id="F00587", jarmu_id="5833",
                 lat=47.54530715942383, lon=19.034313201904297),
            pont(1792226248 - ALAP, 3, 2, megallo_id="F00615", jarmu_id="5833",
                 lat=47.5440559387207, lon=19.036197662353516),
        ]
        e = elso(m)
        self.assertEqual(e["indulas"], 1792226211)  # 10:36:51 magyar idő szerint.
        self.assertEqual(e["keses_mp"], -489)
        self.assertEqual(e["minoseg"], "alatamasztott")
        self.assertFalse(e["menetrend_ok"])


class MenetrendiIdoProba(unittest.TestCase):
    def test_huszonnegy_ora_felett_es_oraatallitaskor_is_a_meglevo_szamitas_marad(self):
        esetek = (
            (date(2026, 10, 16), 25 * 3600, datetime(2026, 10, 16, 23, tzinfo=UTC)),
            (date(2026, 10, 25), 3 * 3600, datetime(2026, 10, 25, 2, tzinfo=UTC)),
            (date(2026, 3, 29), 3 * 3600, datetime(2026, 3, 29, 1, tzinfo=UTC)),
        )
        for nap, masodperc, vart in esetek:
            with self.subTest(nap=nap):
                self.assertEqual(menetrendi_ido(nap, masodperc), vart)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_CONFIG"), "PostgreSQL-próbához TEST_DATABASE_CONFIG kell.")
class AdatbazisosElemzesProba(unittest.TestCase):
    # A betöltő próbáinak külön sémáját és kis mintáit használjuk újra.
    takarit = betoltes_proba.AdatbazisProba.takarit
    sor = betoltes_proba.AdatbazisProba.sor
    menetrend = betoltes_proba.AdatbazisProba.menetrend
    naplo = betoltes_proba.AdatbazisProba.naplo
    betolt = betoltes_proba.AdatbazisProba.betolt

    def setUp(self):
        betoltes_proba.AdatbazisProba.setUp(self)
        self.alap = datetime(2026, 10, 16, 12, tzinfo=UTC)
        self.nap = date(2026, 10, 16)

    def test_sajat_ido_nelkuli_jarmu_is_jelenlet_de_nem_igazolt_indulas(self):
        sha, _, eredmeny = self.menetrend()
        feed = betoltes_proba.kis_feed("VehiclePositions", int(self.alap.timestamp()))
        self.assertFalse(feed.entity[0].vehicle.HasField("timestamp"))
        self.betolt(self.naplo("VehiclePositions", feed.SerializeToString(), menetrend=sha))
        self.conn.row_factory = dict_row
        menetek = list(elemzes.adatbazisbol(self.conn, self.nap, ["0460"], eredmeny["menetrend_id"]))
        menet = next(m for m in menetek if m["szolgalati_nap"] == "2026-10-16")
        self.assertEqual(len(menet["poziciok"]), 1)
        self.assertIsNone(menet["poziciok"][0]["adat_ido"])
        self.assertTrue(all(s["indulas"] is None for s in elemzes.indulasok(menet)))
        sor = elemzes.menet_lathatosag(menetek, self.nap)[0]
        self.assertEqual(sor["latott_menetek"], 1)
        self.assertEqual(sor["nem_latott_menetek"], 0)

    def test_sajat_ido_nelkuli_torles_az_exportban_is_megmarad(self):
        sha, _, eredmeny = self.menetrend()
        alap = int(self.alap.timestamp())
        for i in range(3):
            feed = betoltes_proba.kis_feed(ido=alap + i * 60)
            menet = feed.entity[0].trip_update
            menet.vehicle.id = "J1"
            if i < 2:
                menet.timestamp = alap + i * 60
                menet.stop_time_update[0].departure.time = alap - 30
                menet.stop_time_update[0].departure.uncertainty = 0
            else:
                menet.trip.schedule_relationship = betoltes_proba.pb.TripDescriptor.CANCELED
                menet.ClearField("stop_time_update")
            self.betolt(self.naplo("TripUpdates", feed.SerializeToString(), perc=i, menetrend=sha))
        self.conn.row_factory = dict_row
        menetek = list(elemzes.adatbazisbol(self.conn, self.nap, ["0460"], eredmeny["menetrend_id"]))
        m = next(m for m in menetek if m["szolgalati_nap"] == "2026-10-16")
        self.assertEqual(len(m["kozlesek"]), 3)
        self.assertTrue(any(s["adat_ido"] is None and s["menet_allapot"] == 3 for s in m["kozlesek"]))
        self.assertEqual(elemzes.indulasok(m)[0]["minoseg"], "torolt")

    def test_kesobbi_lekeres_masik_menetrendje_sem_maradhat_ki(self):
        sha, _, eredmeny = self.menetrend()
        masik_sha, _, _ = self.menetrend("ketto", {
            "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                              "T001,23:58:30,23:58:30,001,1\n"
                              "T001,,,002,2\nT001,24:03:00,24:03:30,001,3\n",
        })
        adat = betoltes_proba.kis_feed(ido=int(self.alap.timestamp())).SerializeToString()
        self.betolt(self.naplo("TripUpdates", adat, menetrend=sha))
        self.betolt(self.naplo("TripUpdates", adat, perc=1, menetrend=masik_sha))
        self.assertEqual(self.sor("SELECT count(*) FROM nyers_fajl WHERE forras='TripUpdates'"), (1,))
        self.assertEqual(self.sor("SELECT jelolt_menetrend FROM nyers_fajl WHERE forras='TripUpdates'"), (sha,))
        self.conn.row_factory = dict_row
        with self.assertRaisesRegex(ValueError, "Eltér a vizsgált menetrend"):
            elemzes.minta_kornyezete(self.conn, self.nap, ["0460"], eredmeny["menetrend_id"])

    def test_mas_verzioszam_azonos_menetrendi_sorokkal_hasznalhato(self):
        sha, _, eredmeny = self.menetrend()
        masik_sha, _, masik = self.menetrend("ketto")
        adat = betoltes_proba.kis_feed(ido=int(self.alap.timestamp())).SerializeToString()
        self.betolt(self.naplo("TripUpdates", adat, menetrend=sha))
        self.betolt(self.naplo("TripUpdates", adat, perc=1, menetrend=masik_sha))
        self.conn.row_factory = dict_row
        e = elemzes.minta_kornyezete(self.conn, self.nap, ["0460"], eredmeny["menetrend_id"])
        self.assertEqual(set(e["ellenorzott_menetrendek"]),
                         {eredmeny["menetrend_id"], masik["menetrend_id"]})
        self.assertEqual(e["kizarasok"], [])

    def test_plusz_menet_jovobeli_indulasa_is_resze_a_kizarasnak(self):
        sha, _, eredmeny = self.menetrend()
        alap = int(self.alap.timestamp())
        feed = betoltes_proba.kis_feed(ido=alap)
        menet = feed.entity[0].trip_update
        menet.trip.trip_id = "PLUSZ"
        menet.trip.schedule_relationship = betoltes_proba.pb.TripDescriptor.ADDED
        menet.timestamp = alap
        menet.stop_time_update[0].departure.time = alap + 1800
        self.betolt(self.naplo("TripUpdates", feed.SerializeToString(), menetrend=sha))
        self.conn.row_factory = dict_row
        e = elemzes.minta_kornyezete(self.conn, self.nap, ["0460"], eredmeny["menetrend_id"])
        self.assertEqual(len(e["kizarasok"]), 1)
        plusz = e["kizarasok"][0]
        self.assertEqual(plusz["menet_id"], "PLUSZ")
        self.assertEqual(plusz["also"], alap)
        self.assertEqual(plusz["felso"], alap + 1800)

    def h8_menetrend(self):
        self.nap = date(2026, 10, 18)
        self.alap = datetime(2026, 10, 18, 12, tzinfo=UTC)
        return self.menetrend("h8", {
            "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n"
                          "0460,1,46,Vonal,3\nH8,1,H8,Hév,109\n",
            "trips.txt": "route_id,service_id,trip_id,direction_id\n"
                         "0460,S01,T001,0\nH8,S01,HEV001,0\n",
            "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                              "T001,12:00:00,12:00:00,001,1\nT001,12:10:00,12:10:00,002,2\n"
                              "HEV001,12:00:00,12:00:00,001,1\nHEV001,12:10:00,12:10:00,002,2\n",
        })

    def potlo_megfigyeles(self, sha, vonal, menet, nap, perc=0, forras="TripUpdates"):
        ido = int(self.alap.timestamp()) + perc * 60
        feed = betoltes_proba.kis_feed(forras, ido)
        adat = feed.entity[0].trip_update if forras == "TripUpdates" else feed.entity[0].vehicle
        adat.trip.trip_id = menet
        adat.trip.route_id = vonal
        adat.trip.start_date = nap.replace("-", "")
        adat.vehicle.id = "BUSZ1"
        adat.timestamp = ido
        self.betolt(self.naplo(forras, feed.SerializeToString(), perc=perc, menetrend=sha))

    def test_oph8_potlas_kulon_busz_marad_es_nem_gyart_vasuti_indulast(self):
        sha, _, eredmeny = self.h8_menetrend()
        self.potlo_megfigyeles(sha, "OPH8", "BUSZMENET", "2026-10-18")
        self.potlo_megfigyeles(sha, "OPH9", "MASIKBUSZ", "2026-10-18", perc=1)
        self.conn.row_factory = dict_row
        elotte = self.conn.execute(
            "SELECT vonal_id,potolt_vonal_id,menet_id FROM megfigyeles ORDER BY menet_id"
        ).fetchall()
        e = elemzes.minta_kornyezete(self.conn, self.nap, ["H8"], eredmeny["menetrend_id"])
        self.assertEqual([(s["vonal_id"], s["potolt_vonal_id"], s["menet_id"]) for s in e["kizarasok"]],
                         [("OPH8", "H8", "BUSZMENET")])
        menetek = list(elemzes.adatbazisbol(self.conn, self.nap, ["H8"], eredmeny["menetrend_id"]))
        self.assertTrue(menetek)
        self.assertEqual({m["menet_id"] for m in menetek}, {"HEV001"})
        self.assertTrue(all(s["indulas"] is None for m in menetek for s in elemzes.indulasok(m)))
        utana = self.conn.execute(
            "SELECT vonal_id,potolt_vonal_id,menet_id FROM megfigyeles ORDER BY menet_id"
        ).fetchall()
        self.assertEqual(elotte, utana)
        self.assertTrue(all(s["potolt_vonal_id"] is None for s in utana))
        masik = elemzes.minta_kornyezete(self.conn, self.nap, ["0460"], eredmeny["menetrend_id"])
        self.assertEqual(masik["kizarasok"], [])
        self.assertEqual(elemzes.potlasi_minta(self.conn, self.nap, ["0460"]), [])

    def test_oph8_kapcsolat_csak_az_igazolt_szolgalati_napokra_ervenyes(self):
        sha, _, eredmeny = self.h8_menetrend()
        napok = ["2026-10-16", "2026-10-17", "2026-11-06", "2026-11-07"]
        for i, nap in enumerate(napok):
            self.potlo_megfigyeles(sha, "OPH8", "BUSZ" + str(i), nap, perc=i)
        self.conn.row_factory = dict_row
        e = elemzes.minta_kornyezete(self.conn, self.nap, ["H8"], eredmeny["menetrend_id"])
        self.assertEqual({s["szolgalati_nap"] for s in e["kizarasok"]},
                         {"2026-10-17", "2026-11-06"})
        minta = elemzes.potlasi_minta(self.conn, self.nap, ["H8"])
        self.assertEqual({s["szolgalati_nap"] for s in minta}, {"2026-10-17", "2026-11-06"})

    def test_oph8_megfigyelesszam_nem_menetszam_es_ismetelt_fajl_nem_duplaz(self):
        sha, _, _ = self.h8_menetrend()
        self.potlo_megfigyeles(sha, "OPH8", "BUSZ1", "2026-10-18")
        self.potlo_megfigyeles(sha, "OPH8", "BUSZ1", "2026-10-18")
        self.potlo_megfigyeles(sha, "OPH8", "BUSZ1", "2026-10-18", perc=1)
        self.potlo_megfigyeles(sha, "OPH8", "BUSZ2", "2026-10-18", perc=2)
        self.potlo_megfigyeles(sha, "OPH8", "BUSZ1", "2026-10-18", forras="VehiclePositions")
        self.conn.row_factory = dict_row
        minta = elemzes.potlasi_minta(self.conn, self.nap, ["H8"])
        self.assertEqual(len(minta), 1)
        self.assertEqual(minta[0]["menetek"], 2)
        self.assertEqual(minta[0]["jarmuvek"], 1)
        self.assertEqual(minta[0]["menetfrissitesek"], 3)
        self.assertEqual(minta[0]["poziciok"], 1)
        self.assertEqual(minta[0]["utolso_sajat_ido"], int(self.alap.timestamp()) + 120)

    def test_elozo_napi_potlo_a_hatarablakban_sem_uj_hetfoi_menet(self):
        sha, _, eredmeny = self.h8_menetrend()
        self.alap = datetime(2026, 10, 18, 21, tzinfo=UTC)
        self.potlo_megfigyeles(sha, "OPH8", "VASARNAP", "2026-10-18")
        self.conn.row_factory = dict_row
        hetfo = date(2026, 10, 19)
        e = elemzes.minta_kornyezete(self.conn, hetfo, ["H8"], eredmeny["menetrend_id"])
        self.assertEqual([s["szolgalati_nap"] for s in e["kizarasok"]], ["2026-10-18"])
        minta = elemzes.potlasi_minta(self.conn, hetfo, ["H8"])
        self.assertEqual([s["szolgalati_nap"] for s in minta], ["2026-10-18"])
        self.assertEqual(minta[0]["menetek"], 1)


if __name__ == "__main__":
    unittest.main()
