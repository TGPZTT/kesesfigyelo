"""Kis kitalált menetek; ezekhez nem kell adatbázis vagy internet."""

import copy
import os
import unittest
from datetime import UTC, date, datetime

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


class IndulasProba(unittest.TestCase):
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


class RitkitasProba(unittest.TestCase):
    def test_azonos_sajat_idonel_a_frissebb_valasz_marad(self):
        regi = kozles(60, 25, feed_ido=ALAP + 70)
        uj = kozles(60, 30, feed_ido=ALAP + 80)
        eredmeny = elemzes.kozlesek_ritkitasa([uj, regi])
        self.assertEqual(len(eredmeny), 1)
        self.assertEqual(eredmeny[0]["indulas"], ALAP + 30)

    def test_ertek_es_allapotvaltozas_nem_tunik_el(self):
        adatok = [kozles(60, 30), kozles(90, 30), kozles(120, 35),
                  kozles(150, 35), kozles(180, 35, bizonytalansag=30)]
        eredmeny = elemzes.kozlesek_ritkitasa(adatok)
        self.assertEqual({e["indulas"] for e in eredmeny}, {ALAP + 30, ALAP + 35})
        self.assertTrue(any(e["bizonytalansag"] == 30 for e in eredmeny))


class VarakozasProba(unittest.TestCase):
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
        self.assertEqual(e["nulla_kovetes"], 1)
        self.assertEqual(e["median_kovetes_mp"], 100)

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

    def test_nagy_negativ_elteres_lathato_marad_de_nem_megy_a_fokesesbe(self):
        sorok = indulasi_sor([ALAP + 600, ALAP + 1200], [ALAP, ALAP + 1300])
        sorok[0]["menetrend_ok"] = False
        vonal = elemzes.osszegzes(sorok, date(2026, 10, 17))["vonalak"][0]
        self.assertEqual(vonal["fizikai_indulas"], 2)
        self.assertEqual(vonal["ellenorizendo_menetrend"], 1)
        self.assertEqual(vonal["keseshez_hasznalt"], 1)
        self.assertEqual(vonal["median_minden_jelolttel_mp"], -250)
        self.assertEqual(vonal["median_keses_mp"], 100)


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


if __name__ == "__main__":
    unittest.main()
