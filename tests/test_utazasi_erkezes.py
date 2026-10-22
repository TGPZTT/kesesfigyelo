"""Érkezés lassú beállásnál, ajtójelzésnél és hibás helyzetadatoknál."""
import copy
import unittest

import elemzes
from tests.test_elemzes import ALAP, kis_menet, pont


class UtazasiErkezesProba(unittest.TestCase):
    def setUp(self):
        self.megallo = kis_menet()["megallok"][1]
        self.pontok = [pont(0, 2, 2, lat=47.5004),
                       pont(30, 2, 2, lat=47.5009),
                       pont(60, 2, 1, lat=47.501)]
        for p in self.pontok:
            p["jo"] = True

    def keret(self, pontok=None):
        return elemzes.utazasi_erkezesi_idokeret(self.pontok if pontok is None else pontok, self.megallo)

    def test_lassu_beallasnal_a_korabbi_kozeledes_is_kozrefog(self):
        self.assertEqual(self.keret(), (ALAP, ALAP + 60))
        self.assertIsNone(elemzes.megallasi_idokeretek(self.pontok, self.megallo)[1])

    def test_regi_kozvetlen_erkezesi_pontpar_valtozatlan(self):
        self.pontok.pop(1)
        self.assertEqual(self.keret(), elemzes.megallasi_idokeretek(self.pontok, self.megallo)[1])

    def test_elozo_megallotol_indulo_kozeli_kozeledes_is_hasznalhato(self):
        self.pontok[0].update(sorrend=1, megallo_id="M1")
        self.assertEqual(self.keret(), (ALAP, ALAP + 60))

    def test_ajtonyitas_kulon_megallasjelzes_nelkul_is_hasznalhato(self):
        self.pontok[-1].update(allapot=2, ajto_nyitva=True)
        self.assertEqual(self.keret(), (ALAP, ALAP + 60))

    def test_puszta_kozelseg_nem_bizonyit_leszallasi_lehetoseget(self):
        self.pontok[-1].update(allapot=2, ajto_nyitva=False)
        self.assertIsNone(self.keret())

    def test_ismetelt_ajtonyitas_es_allas_nem_tobb_erkezes(self):
        self.pontok += [dict(self.pontok[-1], adat_ido=ALAP + 90),
                        dict(self.pontok[-1], adat_ido=ALAP + 100, ajto_nyitva=True)]
        self.assertEqual(self.keret(), (ALAP, ALAP + 60))

    def test_ket_kulon_megerkezes_nem_valaszthato_ki_onkenyesen(self):
        self.pontok += [dict(self.pontok[0], adat_ido=ALAP + 90),
                        dict(self.pontok[-1], adat_ido=ALAP + 120)]
        self.assertIsNone(self.keret())

    def test_hibas_koztes_pont_nem_hidalhato_at(self):
        self.pontok[1]["jo"] = False
        self.assertIsNone(self.keret())

    def test_terelesjelzes_nem_torli_a_celnal_megfigyelt_erkezest(self):
        self.pontok[-1]["letert"] = True
        self.assertEqual(self.keret(), (ALAP, ALAP + 60))

    def test_vegallomasi_parkolobol_visszaallas_nem_uj_erkezes(self):
        self.pontok += [dict(self.pontok[-1], adat_ido=ALAP + 90, lat=47.503),
                        dict(self.pontok[-1], adat_ido=ALAP + 120)]
        self.assertEqual(self.keret(), (ALAP, ALAP + 60))

    def test_hosszu_res_teleportalas_es_forditott_sorrend_nem_erkezes(self):
        for mezok in ({"adat_ido": ALAP + 121}, {"lat": 48.0}, {"sorrend": 1}):
            with self.subTest(mezok=mezok):
                pontok = copy.deepcopy(self.pontok)
                pontok[-1].update(mezok)
                self.assertIsNone(self.keret(pontok))

    def test_ajto_masik_megallonal_es_tavoli_allas_nem_szamit(self):
        for mezok in ({"sorrend": 3}, {"lat": 47.503}):
            pontok = copy.deepcopy(self.pontok)
            pontok[-1].update(mezok)
            self.assertIsNone(self.keret(pontok))

    def test_nincs_kozeledes_es_allo_gps_nem_erkezes(self):
        self.assertIsNone(self.keret(self.pontok[-1:]))
        for p in self.pontok:
            p["lat"] = 47.501
        self.assertIsNone(self.keret())

    def test_hianyzo_es_ervenytelen_megallohelyzet_nem_allitja_le_a_napot(self):
        for ertek in (None, float("nan"), 100):
            self.megallo["lat"] = ertek
            self.assertIsNone(self.keret())

    def test_uj_erkezes_nem_irja_at_az_indulast_vagy_a_menetrendet(self):
        m = kis_menet()
        m["poziciok"] += [pont(210, 3, 2, lat=47.5014),
                          pont(230, 3, 2, lat=47.5019), pont(250, 3, 1)]
        sorok = elemzes.ellenorzott_indulasok(m, True)
        elotte = copy.deepcopy(sorok)
        elemzes.utazasi_erkezesek(m, sorok)
        for a, b in zip(elotte, sorok):
            for k in a.keys() - {"erkezes", "erkezes_also", "erkezes_felso", "jarmu_id"}:
                self.assertEqual(a[k], b[k], k)
        self.assertEqual((sorok[-1]["erkezes_also"], sorok[-1]["erkezes_felso"]),
                         (ALAP + 210, ALAP + 250))

    def test_kihagyott_torolt_es_kevert_ut_nem_kap_uj_erkezest(self):
        m = kis_menet()
        for ok in ("azonositas", "kihagyott", "torolt", "kevert_vegighaladas"):
            sorok = elemzes.ellenorzott_indulasok(m, True)
            sorok[-1]["elutasitas"] = ok
            elemzes.utazasi_erkezesek(m, sorok)
            self.assertIsNone(sorok[-1]["erkezes"])


if __name__ == "__main__":
    unittest.main()
