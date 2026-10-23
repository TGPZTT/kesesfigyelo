"""A napi export hibái ne takarják el és ne írják át a régi eredményt."""

import gzip
import hashlib
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import napi
import web_frissites
from tests.test_elemzes import kis_menet

NAP = date(2026, 10, 19)
MOST = datetime(2026, 10, 20, 6, tzinfo=UTC)


def eredmeny():
    return {"nap": str(NAP), "vonalak": [{"vonal_id": "3046", "tervezett": 4, "keseshez_hasznalt": 3,
            "tervezett_menetek": 2, "hasznalt_menetek": 2, "lefedettseg": 0.75}],
            "orankent": [{"n": 3}], "szakaszok": [], "kovetesi_orak": [],
            "kovetesi_reszek": {"naponta": [], "orankent": []}, "kozos_buszok": []}


def minoseg(nap=NAP):
    kezdet = datetime.combine(nap, datetime.min.time(), napi.ZONA)
    veg = kezdet + timedelta(days=1)
    ido = kezdet.astimezone(UTC)
    sorok = []
    while ido < veg:
        sorok.append({"ora_utc": ido.strftime("%Y-%m-%dT%H"), "forrasok": {
            f: {"probak": 2, "siker": 1, "hibak": 1}
            for f in ("VehiclePositions", "TripUpdates", "Alerts", "Idojaras")}})
        ido += timedelta(hours=1)
    return sorok


class NapiProba(unittest.TestCase):
    def test_lemezes_minta_ismetelten_olvashato_es_valtozatlan_jsonkent_mentheto(self):
        minta = KiegeszitesProba.minta(self, napi.VONALAK)
        minta["hev_minta"] = KiegeszitesProba.minta(self, ["H8"])
        eredeti = deepcopy(minta)
        with ExitStack() as tar:
            minta["menetek"] = napi.MentettMenetek(iter(minta["menetek"]), tar)
            minta["hev_minta"]["menetek"] = napi.MentettMenetek(iter(minta["hev_minta"]["menetek"]), tar)
            self.assertEqual(list(minta["menetek"]), eredeti["menetek"])
            self.assertEqual(list(minta["menetek"]), eredeti["menetek"])
            kimenet = io.StringIO()
            napi.minta_ir(kimenet, minta)
            self.assertEqual(json.loads(kimenet.getvalue()), eredeti)
            lista_eredmeny = napi.szamol(eredeti, date.fromisoformat(eredeti["nap"]))
            lemez_eredmeny = napi.szamol(minta, date.fromisoformat(eredeti["nap"]))
            for adat in (lista_eredmeny, lemez_eredmeny):
                adat.pop("keszult_utc")
                adat["hev"].pop("keszult_utc")
            self.assertEqual(lemez_eredmeny, lista_eredmeny)
            fajl = minta["menetek"].fajl
        self.assertTrue(fajl.closed)

    def test_nyers_minta_memoriaja_nem_no_a_teljes_nappal(self):
        import tracemalloc

        tracemalloc.start()
        try:
            with ExitStack() as tar:
                sorok = ({"menet_id": str(i), "adat": "x" * 131072} for i in range(100))
                menetek = napi.MentettMenetek(sorok, tar)
                self.assertEqual(len(menetek), 100)
                self.assertEqual(sum(1 for _ in menetek), 100)
                self.assertLess(tracemalloc.get_traced_memory()[1], 4 * 1024 * 1024)
        finally:
            tracemalloc.stop()

    def test_web_atadas_csak_legujabb_nap_regi_modszert_nem_masol_vissza(self):
        nap = date(2026, 10, 17)
        adat = napi.szamol(KiegeszitesProba.minta(self, napi.VONALAK), nap)
        adat["napi_sema"] = 1
        with tempfile.TemporaryDirectory() as hely:
            forras, cel = Path(hely) / "forras", Path(hely) / "web"
            (forras / "data").mkdir(parents=True)
            cel.mkdir()
            regi = "elemzes-20261017-20261022T060000000000Z-11111111"
            uj = "elemzes-20261017-20261023T060000000000Z-22222222"
            for nev, modszer, ido in ((regi, "regi-modszer", "2026-10-22T06:00:00+00:00"),
                                     (uj, napi.elemzes.MODSZER, "2026-10-23T06:00:00+00:00")):
                mappa = forras / "data" / nev
                mappa.mkdir()
                napi.json_ir(mappa / "indulasok.json", dict(adat, modszer=modszer, keszult_utc=ido))
                napi.json_ir(mappa / "adatminoseg.json", minoseg(nap))
            napi.allapot(forras, nap, True, MOST)
            web_frissites.atad(forras, cel)
            self.assertEqual([m.name for m in (cel / "data").iterdir()], [uj])
            (cel / "data" / regi).mkdir()
            for nev in napi.FAJLOK:
                (cel / "data" / regi / nev).write_bytes((forras / "data" / regi / nev).read_bytes())
            # Ugyanaz a mappanév korábban kézzel kiegészített fájlt takarhat.
            fajl = cel / "data" / uj / "indulasok.json"
            napi.json_ir(fajl, dict(napi.json_olvas(fajl), kiegeszites=True))
            web_frissites.atad(forras, cel)
            self.assertEqual(fajl.read_bytes(), (forras / "data" / uj / fajl.name).read_bytes())
            self.assertFalse((cel / "data" / regi).exists())
            self.assertEqual((next(cel.glob("archiv-*/")) / regi / fajl.name).read_bytes(),
                             (forras / "data" / regi / fajl.name).read_bytes())
            self.assertTrue(next(cel.glob("archiv-*/")).joinpath(uj, fajl.name).exists())
            web_frissites.atad(forras, cel)
            self.assertEqual(len(list(cel.glob("archiv-*"))), 1)
            self.assertEqual(napi.json_olvas(cel / ".napi-allapot.json")["allapot"], "sikeres")
            # Hibás újabb nap nem írhatja át a működő webes eredményt.
            elozo = fajl.read_bytes()
            ujabb = forras / "data" / uj.replace("22222222", "33333333")
            ujabb.mkdir()
            hibas = deepcopy(adat)
            hibas["keszult_utc"] = "2026-10-23T07:00:00+00:00"
            hibas["vonalak"][0]["keseshez_hasznalt"] = -1
            napi.json_ir(ujabb / "indulasok.json", hibas)
            napi.json_ir(ujabb / "adatminoseg.json", minoseg(nap))
            with self.assertRaises(ValueError):
                web_frissites.atad(forras, cel)
            self.assertEqual(fajl.read_bytes(), elozo)

    def test_menetlista_ismetles_es_ellentmondo_osszegzes_elutasitva(self):
        adat = eredmeny()
        adat["menet_lathatosag"] = [{
            "vonal_id": "3046", "tervezett_menetek": 2, "latott_menetek": 1,
            "nem_latott_menetek": 1, "pozicioval": 1, "menetfrissitessel": 0,
            "menetek": [
                {"menet_id": "egy", "szolgalati_nap": str(NAP), "pozicio": True, "menetfrissites": False},
                {"menet_id": "ketto", "szolgalati_nap": str(NAP), "pozicio": False, "menetfrissites": False}]}]
        napi.ellenoriz(adat, minoseg(), NAP, ["3046"])
        for hiba in ("ismetles", "darabszam", "jelzo", "hianyzo_vonal"):
            with self.subTest(hiba=hiba):
                rossz = deepcopy(adat)
                sor = rossz["menet_lathatosag"][0]
                if hiba == "ismetles":
                    sor["menetek"][1]["menet_id"] = "egy"
                elif hiba == "darabszam":
                    sor["nem_latott_menetek"] = 2
                elif hiba == "jelzo":
                    sor["menetek"][0]["pozicio"] = 1
                else:
                    rossz["menet_lathatosag"] = []
                with self.assertRaises(ValueError):
                    napi.ellenoriz(rossz, minoseg(), NAP, ["3046"])

    def futasi_hiba(self, alap, args, kod):
        kimenet = io.StringIO()
        with redirect_stdout(kimenet):
            eredmeny = napi.main(args, alap, MOST)
        self.assertEqual(eredmeny, 1)
        allapot = napi.json_olvas(alap / ".napi-allapot.json")
        self.assertEqual(allapot["hiba_kod"], kod)
        self.assertIn(napi.HIBAK[kod], kimenet.getvalue())
        # A próbahibák kapcsolatadatot és SQL-t is tartalmaznak.
        teljes = kimenet.getvalue() + json.dumps(allapot)
        for titok in ("PROBA_TITOK", "belsogep", "SELECT jelszo"):
            self.assertNotIn(titok, teljes)

    def test_keszenlet_es_menetrend_hibaja_megkulonboztetheto(self):
        for muvelet, kod in (("adat_szegely", "nincs_kesz"),
                             ("elemzes.minta_kornyezete", "menetrend")):
            with (self.subTest(muvelet=muvelet), tempfile.TemporaryDirectory() as hely,
                  patch("napi.elemzes.kapcsolat"),
                  patch("napi.adat_szegely", return_value={}),
                  patch("napi." + muvelet, side_effect=ValueError("PROBA_TITOK SELECT jelszo"))):
                self.futasi_hiba(Path(hely), ["--nap", str(NAP), "--menetrend", "1"], kod)
        with tempfile.TemporaryDirectory() as hely:
            self.futasi_hiba(Path(hely), ["--nap", "2026-10-20"], "nincs_kesz")

    def test_adatbazis_es_ssh_hibajabol_nem_jut_ki_kapcsolatadat(self):
        with tempfile.TemporaryDirectory() as hely:
            hiba = napi.psycopg.OperationalError("host=belsogep password=PROBA_TITOK SELECT jelszo")
            with patch("napi.elemzes.kapcsolat", side_effect=hiba):
                self.futasi_hiba(Path(hely), ["--nap", str(NAP)], "adatbazis")
        with tempfile.TemporaryDirectory() as hely:
            hiba = subprocess.CalledProcessError(255, ["ssh", "belsogep"],
                                                  output=b"PROBA_TITOK", stderr=b"SELECT jelszo")
            with patch("napi.subprocess.run", side_effect=hiba):
                self.futasi_hiba(Path(hely), ["--nap", str(NAP), "--letoltes", "kesesfigyelo"], "atadas")
        # Az SQL-hiba akkor is adatbázishiba, ha éppen a szegélyt ellenőriztük.
        with (tempfile.TemporaryDirectory() as hely, patch("napi.elemzes.kapcsolat"),
              patch("napi.adat_szegely", side_effect=napi.psycopg.ProgrammingError("SELECT jelszo"))):
            self.futasi_hiba(Path(hely), ["--nap", str(NAP)], "adatbazis")

    def test_validalas_es_varatlan_hiba_kulon_kategoriat_kap(self):
        for hiba, kod in ((ValueError("PROBA_TITOK"), "ellenorzes"),
                          (RuntimeError("PROBA_TITOK"), "ismeretlen"),
                          (OSError("PROBA_TITOK"), "fajl")):
            with (self.subTest(kod=kod), tempfile.TemporaryDirectory() as hely,
                  patch("napi.keszit", side_effect=hiba)):
                self.futasi_hiba(Path(hely), ["--nap", str(NAP)], kod)

    def test_regi_statusz_es_hivasi_mod_megmarad_a_hibakod_nelkul(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely)
            napi.allapot(alap, NAP, True, MOST)
            napi.allapot(alap, None, False, MOST)
            adat = napi.json_olvas(alap / ".napi-allapot.json")
            self.assertEqual(adat["hiba_kod"], "ismeretlen")
            self.assertEqual(adat["utolso_siker_utc"], MOST.isoformat())
            regi = {"allapot": "hiba", "nap": str(NAP), "utolso_siker_utc": MOST.isoformat()}
            self.assertEqual(napi.tiszta_allapot(regi)["hiba_kod"], "ismeretlen")
            napi.allapot(alap, NAP, True, MOST, napi.tiszta_allapot(regi))
            self.assertIsNone(napi.json_olvas(alap / ".napi-allapot.json")["hiba_kod"])
        for kod in (None, "PROBA_TITOK", [], {"hiba": "PROBA_TITOK"}):
            with self.subTest(kod=kod):
                adat = napi.tiszta_allapot({"allapot": "hiba", "hiba_kod": kod, "hiba": "PROBA_TITOK"})
                self.assertEqual(adat["hiba_kod"], "ismeretlen")
                self.assertNotIn("PROBA_TITOK", json.dumps(adat))
        for kod in napi.HIBAK:
            self.assertEqual(napi.tiszta_allapot({"allapot": "hiba", "hiba_kod": kod})["hiba_kod"], kod)
            self.assertIsNone(napi.tiszta_allapot({"allapot": "sikeres", "hiba_kod": kod})["hiba_kod"])

    def test_teljes_ujraszamitas_mentett_szintetikus_mintabol(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely)
            nap = date(2026, 10, 17)
            minta = alap / "eredeti.json.gz"
            adatok = {"nap": str(nap), "menetrend_id": 1, "menetek": [kis_menet()],
                      "ellenorzott_menetrendek": [1], "kizarasok": [], "megallo_nevek": {}}
            with gzip.open(minta, "wt", encoding="utf-8") as fajl:
                json.dump(adatok, fajl)
            napi.json_ir(alap / "minoseg.json", minoseg(nap))
            with redirect_stdout(io.StringIO()):
                kod = napi.main(["--nap", str(nap), "--vonal", "3046", "--minta", str(minta),
                                 "--minoseg", str(alap / "minoseg.json")], alap, MOST)
            self.assertEqual(kod, 0)
            export = next((alap / "data").glob("elemzes-*/indulasok.json"))
            eredeti = napi.elemzes.feldolgozas(adatok, nap)
            friss = napi.json_olvas(export)
            self.assertEqual(friss["vonalak"], eredeti["vonalak"])
            self.assertEqual(friss["kontroll"], eredeti["kontroll"])
            self.assertEqual(friss["vonalak"][0]["keseshez_hasznalt"], 2)
            self.assertNotIn("esemenyek", friss)

    def test_betoltesi_lemaradasnal_vagy_hibanal_nincs_napi_export(self):
        conn = MagicMock()
        kezdet = datetime.combine(NAP, datetime.min.time(), napi.ZONA)
        hatar = kezdet + timedelta(days=1, hours=4)
        sorok = [{"forras": f, "elso": kezdet - timedelta(hours=1),
                  "utolso": hatar, "forras_utolso": hatar - timedelta(seconds=30)}
                 for f in ("VehiclePositions", "TripUpdates")]
        conn.execute.return_value.fetchall.return_value = sorok
        conn.execute.return_value.fetchone.return_value = {"n": 0}
        self.assertEqual(len(napi.adat_szegely(conn, NAP)["forrasok"]), 2)
        sorok[1]["utolso"] -= timedelta(seconds=1)
        with self.assertRaises(ValueError):
            napi.adat_szegely(conn, NAP)
        sorok[1]["utolso"] = hatar
        conn.execute.return_value.fetchone.return_value = {"n": 1}
        with self.assertRaises(ValueError):
            napi.adat_szegely(conn, NAP)

    def test_napi_menetrend_a_sikeres_lekeresekhez_kotott(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"id": 6476}
        self.assertEqual(napi.menetrend_kivalasztas(conn, NAP), 6476)
        sql, param = conn.execute.call_args.args
        self.assertIn("l.ismert_menetrend_sha256=n.sha256", sql)
        self.assertIn("l.eredmeny='siker'", sql)
        self.assertEqual(param[:2], (NAP, NAP))
        conn.execute.return_value.fetchone.return_value = {"id": None}
        with self.assertRaises(ValueError):
            napi.menetrend_kivalasztas(conn, NAP)

    def test_tegnapi_nap_negyora_elott_meg_nem_zart(self):
        with self.assertRaises(ValueError):
            napi.lezart_nap(None, datetime(2026, 10, 20, 1, 59, tzinfo=UTC))
        self.assertEqual(napi.lezart_nap(None, datetime(2026, 10, 20, 2, tzinfo=UTC)), NAP)
        self.assertEqual(napi.lezart_nap("2026-10-18", datetime(2026, 10, 20, 1, tzinfo=UTC)), date(2026, 10, 18))

    def test_oraatallitas_utani_negyora_helyi_ido(self):
        with self.assertRaises(ValueError):
            napi.lezart_nap("2026-10-24", datetime(2026, 10, 25, 2, 59, tzinfo=UTC))
        self.assertEqual(napi.lezart_nap("2026-10-24", datetime(2026, 10, 25, 3, tzinfo=UTC)), date(2026, 10, 24))

    def test_teljes_nap_es_teli_nyari_ora_ellenorzese(self):
        for nap, orak in ((NAP, 24), (date(2026, 10, 25), 25), (date(2026, 3, 29), 23)):
            adat = eredmeny()
            adat["nap"] = str(nap)
            napi.ellenoriz(adat, minoseg(nap), nap, ["3046"])
            self.assertEqual(len(minoseg(nap)), orak)

    def test_hianyos_mas_napi_es_ismetelt_orak_elutasitasa(self):
        for adat in (minoseg()[:-1], minoseg(NAP - timedelta(days=1)), minoseg()[:-1] + [minoseg()[0]]):
            with self.assertRaises(ValueError):
                napi.ellenoriz(eredmeny(), adat, NAP)

    def test_ures_reszminta_rossz_vonal_es_darabszam_elutasitasa(self):
        for kulcs, ertek in (("vonalak", []), ("nap", "2026-10-18"), ("mintamenetek", "egy-menet")):
            adat = eredmeny()
            adat[kulcs] = ertek
            with self.assertRaises(ValueError):
                napi.ellenoriz(adat, minoseg(), NAP)
        for kulcs, ertek in (("tervezett", 0), ("keseshez_hasznalt", 5),
                            ("hasznalt_menetek", -1), ("lefedettseg", 1.1)):
            adat = eredmeny()
            adat["vonalak"][0][kulcs] = ertek
            with self.assertRaises(ValueError):
                napi.ellenoriz(adat, minoseg(), NAP)
        with self.assertRaises(ValueError):
            napi.ellenoriz(eredmeny(), minoseg(), NAP, ["0460"])

    def test_nem_veges_ertek_es_rossz_n_elutasitasa(self):
        for ertek in (float("nan"), float("inf"), -1, True):
            adat = eredmeny()
            adat["orankent"][0]["n"] = ertek
            with self.assertRaises(ValueError):
                napi.ellenoriz(adat, minoseg(), NAP)

    def test_ket_export_nem_fer_egymasra(self):
        with tempfile.TemporaryDirectory() as hely:
            with napi.zar(Path(hely)), self.assertRaises(FileExistsError), napi.zar(Path(hely)):
                self.fail("A második futás nem indulhat.")
            with napi.zar(Path(hely)):
                pass

    def test_folyamat_kilepese_utan_a_zar_magátol_felszabadul(self):
        with tempfile.TemporaryDirectory() as hely:
            kod = """
import os
from pathlib import Path
from napi import zar
import sys
with zar(Path(sys.argv[1])):
    os._exit(0)
"""
            subprocess.run([sys.executable, "-c", kod, hely], check=True, timeout=10,
                           capture_output=True, cwd=Path(napi.__file__).parent)
            with napi.zar(Path(hely)):
                pass

    def test_masik_elo_folyamatot_valoban_kizar(self):
        with tempfile.TemporaryDirectory() as hely:
            kod = """
from pathlib import Path
from napi import zar
import sys
with zar(Path(sys.argv[1])):
    print("zarva", flush=True)
    sys.stdin.readline()
"""
            with subprocess.Popen([sys.executable, "-c", kod, hely], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  cwd=Path(napi.__file__).parent) as gyerek:
                try:
                    self.assertEqual(gyerek.stdout.readline().strip(), "zarva")
                    with self.assertRaises(FileExistsError), napi.zar(Path(hely)):
                        self.fail("A másik élő futás zárját nem veheti el.")
                finally:
                    gyerek.communicate("\n", timeout=10)
            with napi.zar(Path(hely)):
                pass

    def test_hiba_megorzi_a_kesz_fajlt_es_az_utolso_sikert_titok_nelkul(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely)
            regi = alap / "data" / "elemzes-regi"
            regi.mkdir(parents=True)
            regi_fajl = regi / "indulasok.json"
            regi_fajl.write_bytes(b"korabbi eredmeny")
            napi.allapot(alap, NAP, True, MOST - timedelta(days=1))
            kimenet = io.StringIO()
            with patch("napi.keszit", side_effect=RuntimeError("PGPASSWORD=titkos-jelszo")), redirect_stdout(kimenet):
                kod = napi.main(["--nap", str(NAP), "--menetrend", "1"], alap, MOST)
            self.assertEqual(kod, 1)
            self.assertEqual(regi_fajl.read_bytes(), b"korabbi eredmeny")
            allapot = napi.json_olvas(alap / ".napi-allapot.json")
            self.assertEqual(allapot["allapot"], "hiba")
            self.assertEqual(allapot["utolso_siker_utc"], (MOST - timedelta(days=1)).isoformat())
            self.assertNotIn("titkos", kimenet.getvalue() + json.dumps(allapot))
            with napi.zar(alap):
                pass
            self.assertEqual(list((alap / ".napi-atmeneti").iterdir()), [])

    def test_export_csak_ellenorzes_utan_jelenik_meg_es_kulon_minta_marad(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely)
            minta = {"nap": str(NAP), "menetek": [{}], "kizarasok": []}
            with (patch("napi.minta_es_minoseg", return_value=(minta, minoseg())),
                  patch("napi.szamol", return_value=eredmeny()), redirect_stdout(io.StringIO())):
                kod = napi.main(["--nap", str(NAP), "--vonal", "3046", "--menetrend", "1"], alap, MOST)
            self.assertEqual(kod, 0)
            fajlok = list((alap / "data").glob("elemzes-*/indulasok.json"))
            self.assertEqual(len(fajlok), 1)
            adat = napi.json_olvas(fajlok[0])
            self.assertNotIn("esemenyek", adat)
            self.assertTrue((alap / "data" / adat["minta_fajl"]).is_file())
            self.assertEqual(adat["keszult_utc"], MOST.isoformat())

    def test_nem_irja_felul_a_mar_letezo_exportot(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely)
            (alap / "data" / "elemzes-megvan").mkdir(parents=True)
            uj = alap / "uj"
            uj.mkdir()
            with self.assertRaises(ValueError):
                napi.kozzetes(alap, uj, "elemzes-megvan")

    def test_letoltes_csak_ket_kis_fajlt_hoz_ellenorzott_ssh_val(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely)
            nev = "elemzes-20261019-20261020T060000000000Z-1234abcd"
            tartalmak = {f: json.dumps(a).encode() for f, a in zip(napi.FAJLOK, (eredmeny(), minoseg()))}
            meta = {"mappa": nev, "fajlok": {f: {"meret": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                                            for f, b in tartalmak.items()},
                    "forras_allapot": {"allapot": "hiba", "nap": str(NAP), "hiba": "nem másolható hibaérték",
                                       "hiba_kod": "menetrend",
                                       "utolso_probalkozas_utc": MOST.isoformat()}}
            hivasok = []

            def fut(parancs, **kwargs):
                hivasok.append(parancs)
                self.assertIn("StrictHostKeyChecking=yes", parancs)
                self.assertIn("BatchMode=yes", parancs)
                self.assertFalse(kwargs.get("shell", False))
                if parancs[0] == "scp":
                    cel = Path(parancs[-1])
                    cel.write_bytes(tartalmak[cel.name])
                    return subprocess.CompletedProcess(parancs, 0, b"")
                return subprocess.CompletedProcess(parancs, 0, json.dumps(meta).encode())

            with patch("napi.subprocess.run", side_effect=fut), redirect_stdout(io.StringIO()):
                    kod = napi.main(["--nap", str(NAP), "--vonal", "3046", "--letoltes", "kesesfigyelo"], alap, MOST)
                    masodik = napi.main(["--nap", str(NAP), "--vonal", "3046", "--letoltes", "kesesfigyelo"], alap, MOST)
            self.assertEqual((kod, masodik), (0, 0))
            self.assertEqual(sum(p[0] == "scp" for p in hivasok), 2)
            self.assertEqual({p.name for p in (alap / "data" / nev).iterdir()}, set(napi.FAJLOK))
            allapot = napi.json_olvas(alap / ".napi-allapot.json")
            self.assertEqual(allapot["allapot"], "sikeres")
            self.assertEqual(allapot["forras_allapot"]["allapot"], "hiba")
            self.assertEqual(allapot["forras_allapot"]["hiba_kod"], "menetrend")
            self.assertNotIn("nem másolható", json.dumps(allapot))

    def test_tavoli_statuszbol_csak_ervenyes_ido_es_allapot_marad(self):
        adat = napi.tiszta_allapot({"allapot": "sikeres", "utolso_siker_utc": "nem-idopont",
                                   "nap": "titok", "utolso_probalkozas_utc": "2026-10-20T12:00:00+02:00",
                                   "jelszo": "ne keruljon at"})
        self.assertEqual(adat["utolso_probalkozas_utc"], "2026-10-20T10:00:00+00:00")
        self.assertIsNone(adat["nap"])
        self.assertIsNone(adat["utolso_siker_utc"])
        self.assertNotIn("jelszo", adat)

    def test_mas_vonalkoru_vagy_regi_modszeru_uj_export_nem_fedi_el_a_kertet(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely) / "laptop"
            alap.mkdir()
            tavoli = Path(hely) / "vps" / "data"
            nevek = ["elemzes-20261019-20261020T060000000000Z-1234abcd",
                     "elemzes-20261019-20261020T070000000000Z-1234abcd",
                     "elemzes-20261019-20261020T080000000000Z-1234abcd"]
            for nev, vonal, modszer in zip(nevek, ("3046", "H8", "3046"),
                                           (napi.elemzes.MODSZER, napi.elemzes.MODSZER, "kozles-haladas-ajto-3")):
                mappa = tavoli / nev
                mappa.mkdir(parents=True)
                adat = eredmeny()
                adat["napi_sema"] = 1
                adat["modszer"] = modszer
                adat["vonalak"][0]["vonal_id"] = vonal
                adat["vonalak"][0]["idokeretek"] = [[-30, 30, 3]]
                napi.json_ir(mappa / "indulasok.json", adat)
                napi.json_ir(mappa / "adatminoseg.json", minoseg())
            eredeti_fut = subprocess.run

            def fut(parancs, **kwargs):
                if parancs[0] == "ssh":
                    kod = shlex.split(parancs[-1])[2]
                    kod = kod.replace("/home/ubuntu/kesesfigyelo/data", tavoli.as_posix())
                    return eredeti_fut([sys.executable, "-c", kod], **kwargs)
                forras = parancs[-2].split("/data/", 1)[1]
                Path(parancs[-1]).write_bytes((tavoli / forras).read_bytes())
                return subprocess.CompletedProcess(parancs, 0, b"")

            with patch("napi.subprocess.run", side_effect=fut), redirect_stdout(io.StringIO()):
                kod = napi.main(["--nap", str(NAP), "--vonal", "3046", "--letoltes", "kesesfigyelo"], alap, MOST)
            self.assertEqual(kod, 0)
            self.assertTrue((alap / "data" / nevek[0]).is_dir())
            self.assertFalse((alap / "data" / nevek[1]).exists())
            self.assertFalse((alap / "data" / nevek[2]).exists())

    def test_megsertett_letoltes_nem_kerul_a_megjelenitett_mappaba(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely)
            nev = "elemzes-20261019-20261020T060000000000Z-1234abcd"
            tartalmak = {f: json.dumps(a).encode() for f, a in zip(napi.FAJLOK, (eredmeny(), minoseg()))}
            meta = {"mappa": nev, "fajlok": {f: {"meret": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                                            for f, b in tartalmak.items()}}

            def fut(parancs, **kwargs):
                if parancs[0] == "scp":
                    cel = Path(parancs[-1])
                    cel.write_bytes(tartalmak[cel.name] + b" ")
                return subprocess.CompletedProcess(parancs, 0, json.dumps(meta).encode())

            with patch("napi.subprocess.run", side_effect=fut), redirect_stdout(io.StringIO()):
                kod = napi.main(["--nap", str(NAP), "--vonal", "3046", "--letoltes", "kesesfigyelo"], alap, MOST)
            self.assertEqual(kod, 1)
            self.assertFalse((alap / "data").exists())
            self.assertEqual(list((alap / ".napi-atmeneti").iterdir()), [])

    def test_hibas_tavoli_utvonal_nem_publikalhato(self):
        with tempfile.TemporaryDirectory() as hely:
            alap = Path(hely)
            meta = {"mappa": "../masik", "fajlok": {}}
            with (patch("napi.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(meta).encode())),
                  redirect_stdout(io.StringIO())):
                kod = napi.main(["--nap", str(NAP), "--letoltes", "kesesfigyelo"], alap, MOST)
            self.assertEqual(kod, 1)
            self.assertFalse((alap / "data").exists())

    def test_ssh_nev_nem_lehet_parancs(self):
        with tempfile.TemporaryDirectory() as hely, patch("napi.subprocess.run") as fut, redirect_stdout(io.StringIO()):
            kod = napi.main(["--nap", str(NAP), "--letoltes=-oProxyCommand=valami"], Path(hely), MOST)
            self.assertEqual(kod, 1)
            fut.assert_not_called()


class KiegeszitesProba(unittest.TestCase):
    def idojaras(self, ido, **ertekek):
        return {"terseg": "Belvaros", "adat_ido": ido.isoformat(), "interval_mp": 900,
                "homerseklet": 10, "szel": 4, "csapadek": 1, **ertekek}

    def minta(self, vonalak):
        menetek = []
        for vonal in vonalak:
            menet = kis_menet()
            menet.update(vonal_id=vonal, menet_id="T" + vonal)
            for sor in menet["kozlesek"] + menet["poziciok"]:
                sor["jarmu_id"] = "J" + vonal
            menetek.append(menet)
        return {"nap": "2026-10-17", "menetrend_id": 1, "menetek": menetek,
                "ellenorzott_menetrendek": [1], "kizarasok": [], "megallo_nevek": {}}

    def test_csapadek_oravege_homerseklet_oraeleje_es_napvege(self):
        nap = date(2026, 10, 17)
        ora = next(napi.napi_orak(nap))
        sorok = [self.idojaras(ora + timedelta(minutes=15 * i), homerseklet=i, csapadek=i)
                 for i in range(5)]
        utolso = list(napi.napi_orak(nap))[-1]
        sorok += [self.idojaras(utolso + timedelta(minutes=15 * i)) for i in range(1, 5)]
        orak = napi.idojaras_orankent(sorok, nap)
        self.assertEqual(len(orak), 72)
        self.assertEqual(orak[0]["homerseklet_atlag"], 1.5)
        self.assertEqual(orak[0]["csapadek_mm"], 10)
        self.assertEqual(orak[0]["negyedorak"], 4)
        self.assertEqual(orak[-3]["csapadek_mm"], 4)
        self.assertIsNone(orak[1]["csapadek_mm"])
        self.assertEqual(orak[1]["negyedorak"], 0)

    def test_hianyzo_negyedora_es_null_nem_nullacsapadek(self):
        ora = next(napi.napi_orak(NAP))
        for sorok in (
                [self.idojaras(ora + timedelta(minutes=15 * i)) for i in (1, 2, 4)],
                [self.idojaras(ora + timedelta(minutes=15 * i), csapadek=None if i == 3 else 0)
                 for i in range(1, 5)]):
            sor = napi.idojaras_orankent(sorok, NAP)[0]
            self.assertIsNone(sor["csapadek_mm"])
            self.assertEqual(sor["negyedorak"], 3)
        sorok = [self.idojaras(ora + timedelta(minutes=15 * i), csapadek=0) for i in range(1, 5)]
        self.assertEqual(napi.idojaras_orankent(sorok, NAP)[0]["csapadek_mm"], 0)

    def test_ismetelt_modellido_nem_ketszeres_csapadek_es_uj_valtozat_nyer(self):
        ora = next(napi.napi_orak(NAP))
        sorok = [self.idojaras(ora + timedelta(minutes=15 * i)) for i in range(1, 5)]
        sorok += [deepcopy(sorok[0]), dict(sorok[0], csapadek=2,
                                         rogzitve=(ora + timedelta(minutes=20)).isoformat())]
        sor = napi.idojaras_orankent(sorok, NAP)[0]
        self.assertEqual((sor["negyedorak"], sor["csapadek_mm"]), (4, 5))
        sorok[-1]["rogzitve"] = sorok[0]["adat_ido"]
        with self.assertRaises(ValueError):
            napi.idojaras_orankent(sorok, NAP)

    def test_oraatallitasnal_23_vagy_25_oranyi_mindharom_terseg(self):
        for nap, orak in ((date(2026, 3, 29), 23), (date(2026, 10, 25), 25)):
            sorok = napi.idojaras_orankent([], nap)
            self.assertEqual(len(sorok), orak * 3)
            self.assertEqual(len({(s["terseg"], s["ora_utc"]) for s in sorok}), orak * 3)

    def test_hibas_idojaras_nem_valhat_ervenyes_orava(self):
        ora = next(napi.napi_orak(NAP))
        for kulcs, ertek in (("interval_mp", 1800), ("homerseklet", float("nan")),
                            ("csapadek", -1), ("szel", True), ("terseg", "Ismeretlen"),
                            ("adat_ido", ora.replace(tzinfo=None).isoformat()),
                            ("adat_ido", (ora + timedelta(minutes=1)).isoformat())):
            with self.subTest(kulcs=kulcs, ertek=ertek), self.assertRaises(ValueError):
                napi.idojaras_orankent([self.idojaras(ora, **{kulcs: ertek})], NAP)

    def test_oraexport_hianyos_es_hibas_ertekeit_elutasitja(self):
        adat = eredmeny()
        adat["idojaras"] = napi.idojaras_orankent([], NAP)
        napi.ellenoriz(adat, minoseg(), NAP, ["3046"])
        for kulcs, ertek in (("csapadek_mm", 0), ("szel_atlag", -1), ("homerseklet_mintak", 1)):
            rossz = deepcopy(adat)
            rossz["idojaras"][0][kulcs] = ertek
            with self.assertRaises(ValueError):
                napi.ellenoriz(rossz, minoseg(), NAP, ["3046"])
        adat["idojaras"].pop()
        with self.assertRaises(ValueError):
            napi.ellenoriz(adat, minoseg(), NAP, ["3046"])

    def test_tort_atlag_kerekitese_nem_rossz_maximum(self):
        ora = next(napi.napi_orak(NAP))
        adat = eredmeny()
        adat["idojaras"] = napi.idojaras_orankent(
            [self.idojaras(ora + timedelta(minutes=15 * i), homerseklet=0.1, szel=0.1)
             for i in range(3)], NAP)
        napi.ellenoriz(adat, minoseg(), NAP, ["3046"])

    def test_hev_kiegeszites_es_idojaras_offline_reprodukalhato(self):
        nap = date(2026, 10, 17)
        minta = self.minta(napi.VONALAK)
        eredeti = napi.elemzes.feldolgozas(minta, nap)
        minta["hev_minta"] = self.minta(["H8"])
        minta["idojaras_minta"] = [self.idojaras(next(napi.napi_orak(nap)))]
        adat = napi.szamol(json.loads(json.dumps(minta)), nap)
        napi.ellenoriz(adat, minoseg(nap), nap, napi.VONALAK)
        for kulcs in eredeti:
            if kulcs not in ("esemenyek", "keszult_utc"):
                self.assertEqual(adat[kulcs], eredeti[kulcs], kulcs)
        self.assertEqual(adat["hev"]["allapot"], "kesz")
        self.assertEqual(adat["hev"]["vonalak"][0]["vonal_id"], "H8")
        self.assertNotIn("esemenyek", adat["hev"])
        self.assertEqual(adat["idojaras_leiras"]["allapot"], "kesz")
        self.assertEqual(len(adat["idojaras"]), 72)

    def test_hev_hiany_vagy_hiba_nem_tunteti_el_a_tiz_vonalat(self):
        nap = date(2026, 10, 17)
        for minta, allapot in ((None, "nincs_minta"),
                               ({"allapot": "hiba", "hiba_kod": "menetrend"}, "hiba"),
                               ({"nap": str(nap), "menetek": []}, "nincs_hasznalhato")):
            alap = self.minta(napi.VONALAK)
            alap["hev_minta"] = minta
            adat = napi.szamol(alap, nap)
            self.assertEqual(adat["hev"]["allapot"], allapot)
            napi.ellenoriz(adat, minoseg(nap), nap, napi.VONALAK)
            self.assertEqual(len(adat["vonalak"]), 10)
        minta = self.minta(["H8"])
        minta["menetek"][0].update(kozlesek=[], poziciok=[])
        adat = napi.hev_szamol(minta, nap)
        self.assertEqual(adat["allapot"], "nincs_hasznalhato")
        self.assertEqual(adat["vonalak"][0]["keseshez_hasznalt"], 0)

    def test_hev_onmagaban_nem_rekurziv_es_db_hibauzenet_nem_kerul_exportba(self):
        nap = date(2026, 10, 17)
        adat = napi.szamol(self.minta(["H8"]), nap)
        self.assertNotIn("hev", adat)
        with patch("napi.elemzes.minta_kornyezete", side_effect=napi.psycopg.ProgrammingError("PROBA_TITOK")):
            minta = napi.hev_adatbazisbol(MagicMock(), nap, 1)
        self.assertEqual(minta["hiba_kod"], "adatbazis")
        self.assertNotIn("PROBA_TITOK", json.dumps(minta))

    def test_db_mintaban_extra_hev_csak_a_tiz_alapvonalhoz(self):
        nap = date(2026, 10, 17)
        args = SimpleNamespace(minta=None, minoseg=None, menetrend=1, beallitas=Path("nem-olvassuk"))
        for vonalak, hivva in ((napi.VONALAK, True), (["H8"], False), (["3046"], False)):
            with (patch("napi.elemzes.kapcsolat"),
                  patch("napi.adat_szegely", return_value={}),
                  patch("napi.elemzes.minta_kornyezete", return_value={"kizarasok": []}),
                  patch("napi.elemzes.adatbazisbol", return_value=self.minta(vonalak)["menetek"]),
                  patch("napi.elemzes.potlasi_minta", return_value=[]),
                  patch("napi.minoseg_adatbazisbol", return_value=minoseg(nap)),
                  patch("napi.hev_adatbazisbol", return_value=self.minta(["H8"])) as hev,
                  patch("napi.idojaras_adatbazisbol", return_value=[]) as weather):
                adat, _ = napi.minta_es_minoseg(args, nap, vonalak)
            self.assertEqual(hev.called, hivva)
            self.assertEqual("hev_minta" in adat, hivva)
            self.assertIn("idojaras_minta", adat)
            weather.assert_called_once()

    def test_idojaras_db_hiba_kulon_allapot_titok_nelkul(self):
        nap = date(2026, 10, 17)
        args = SimpleNamespace(minta=None, minoseg=None, menetrend=1, beallitas=Path("nem-olvassuk"))
        with (patch("napi.elemzes.kapcsolat"),
              patch("napi.adat_szegely", return_value={}),
              patch("napi.elemzes.minta_kornyezete", return_value={"kizarasok": []}),
              patch("napi.elemzes.adatbazisbol", return_value=self.minta(["3046"])["menetek"]),
              patch("napi.elemzes.potlasi_minta", return_value=[]),
              patch("napi.minoseg_adatbazisbol", return_value=minoseg(nap)),
              patch("napi.idojaras_adatbazisbol", side_effect=napi.psycopg.OperationalError("PROBA_TITOK"))):
            minta, minosegi_adat = napi.minta_es_minoseg(args, nap, ["3046"])
        adat = napi.szamol(minta, nap)
        napi.ellenoriz(adat, minosegi_adat, nap, ["3046"])
        self.assertEqual(adat["idojaras_leiras"]["allapot"], "hiba")
        self.assertEqual(adat["idojaras_leiras"]["hiba_kod"], "adatbazis")
        self.assertNotIn("PROBA_TITOK", json.dumps(adat) + json.dumps(minta))


if __name__ == "__main__":
    unittest.main()
