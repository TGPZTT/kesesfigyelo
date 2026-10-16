"""A gyujto offline probai: kitalalt adatokkal, ideiglenes mappaban."""

import gzip
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import traceback
import unittest
import zipfile
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from google.transit import gtfs_realtime_pb2

import gyujto


def proba_feed(idobelyeg=None, vegyes=False):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    if idobelyeg is not None:
        feed.header.timestamp = idobelyeg
    elem = feed.entity.add()
    elem.id = "ut-1"
    elem.trip_update.trip.trip_id = "menet-1"
    if vegyes:
        alak = feed.entity.add()
        alak.id = "alak-1"
        alak.shape.shape_id = "vonal-1"
        alak.shape.encoded_polyline = "teszt"
    return feed.SerializeToString()


def proba_menetrend(tomorites=zipfile.ZIP_DEFLATED):
    fajlok = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n1,BKK,https://example.invalid,Europe/Budapest\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\nR,1,1,Vonal,3\n",
        "trips.txt": "route_id,service_id,trip_id\nR,S,T\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nP,Megallo,47.5,19.1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT,10:00:00,10:00:00,P,1\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nS,1,1,1,1,1,1,1,20260101,20261231\n",
        "calendar_dates.txt": "service_id,date,exception_type\nS,20261016,1\n",
    }
    adat = io.BytesIO()
    with zipfile.ZipFile(adat, "w", compression=tomorites) as archiv:
        for nev, tartalom in fajlok.items():
            archiv.writestr(nev, tartalom)
    return adat.getvalue()


class ProbaValasz:
    def __init__(self, adat, status=200, fejlecek=None):
        self.adat = io.BytesIO(adat)
        self.status = status
        self.headers = fejlecek or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.adat.close()

    def read(self, meret=-1):
        return self.adat.read(meret)


class ProbaOra:
    def __init__(self):
        self.masodperc = 0

    def monotonic(self):
        return self.masodperc

    def time(self):
        return 1760616000 + self.masodperc

    def sleep(self, mennyit):
        self.masodperc += mennyit


class GyujtoProba(unittest.TestCase):
    def setUp(self):
        ideiglenes = tempfile.TemporaryDirectory()
        self.addCleanup(ideiglenes.cleanup)
        self.data = Path(ideiglenes.name) / "data"
        self.data.mkdir()

    def test_azonos_tartalom_csak_egyszer_tarolodik(self):
        adat = proba_feed(100)
        elso = gyujto.mentes(self.data, "TripUpdates", adat)
        masodik = gyujto.mentes(self.data, "TripUpdates", adat)
        self.assertTrue(elso["uj_fajl"])
        self.assertFalse(masodik["uj_fajl"])
        self.assertEqual(elso["fajl"], masodik["fajl"])
        self.assertEqual(elso["sha256"], hashlib.sha256(adat).hexdigest())
        self.assertEqual(elso["nyers_bajt"], len(adat))
        self.assertEqual(gzip.decompress((self.data / elso["fajl"]).read_bytes()), adat)

    def test_azonos_adat_ket_kulon_probakent_naplozodik(self):
        adat = proba_feed(100)
        for ido in (100, 130):
            rekord = gyujto.valasz_mentese(self.data, "TripUpdates", adat, ido, ido + 1)
            gyujto.naplo(self.data, rekord)
        self.assertEqual(len(list(self.data.rglob("*.pb.gz"))), 1)
        naplok = list((self.data / "naplo").rglob("*.json"))
        self.assertEqual(len(naplok), 2)
        idok = {json.loads(p.read_text())["kezdett_utc"] for p in naplok}
        self.assertEqual(len(idok), 2)

    def test_hibas_feed_is_megmarad(self):
        adat = b"nem protobuf: \xff\xff"
        rekord = gyujto.valasz_mentese(self.data, "TripUpdates", adat, 100, 101)
        self.assertEqual(rekord["eredmeny"], "hibas_valasz")
        self.assertEqual(
            gzip.decompress((self.data / rekord["fajl"]).read_bytes()), adat
        )

    def test_hianyzo_idobelyeg_nem_nulla(self):
        rekord = gyujto.feed_adatok(proba_feed(), "TripUpdates", 1000)
        self.assertIsNone(rekord["feed_ido"])
        self.assertIsNone(rekord["feed_kor_mp"])
        self.assertIsNone(rekord["feed_regi"])
        self.assertIsNone(rekord["feed_jovobeli"])
        self.assertEqual(rekord["menet_ido_hianyzik"], 1)

    def test_feed_kora_es_jovobeli_ideje(self):
        regi = gyujto.feed_adatok(proba_feed(100), "TripUpdates", 200)
        self.assertTrue(regi["feed_regi"])
        jovobeli = gyujto.feed_adatok(proba_feed(210), "TripUpdates", 200)
        self.assertTrue(jovobeli["feed_jovobeli"])
        jelzes = gyujto.feed_adatok(proba_feed(100), "Alerts", 200)
        self.assertFalse(jelzes["feed_regi"])

    def test_alakzat_nem_menetfrissites(self):
        rekord = gyujto.feed_adatok(proba_feed(100, vegyes=True), "TripUpdates", 101)
        self.assertEqual(rekord["elemek"], 2)
        self.assertEqual(rekord["menetfrissitesek"], 1)
        self.assertEqual(rekord["alakzatok"], 1)
        self.assertIn("nem igazolt", rekord["ertelmezes"])

    def test_lemondas_es_jarmu_frissesseg_kulon_merheto(self):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(proba_feed(200))
        feed.entity[0].trip_update.trip.schedule_relationship = 3
        for azonosito, ido in (("regi", 100), ("hianyzo", None)):
            elem = feed.entity.add()
            elem.id = azonosito
            elem.vehicle.vehicle.id = azonosito
            if ido is not None:
                elem.vehicle.timestamp = ido
        rekord = gyujto.feed_adatok(feed.SerializeToString(), "VehiclePositions", 200)
        self.assertEqual(rekord["torolt_menetek"], 1)
        self.assertEqual(rekord["jarmuvek"], 2)
        self.assertEqual(rekord["jarmu_ido_hianyzik"], 1)
        self.assertEqual(rekord["regi_jarmupoziciok"], 1)

    def test_differencialis_feed_nem_teljes_pillanatkep(self):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(proba_feed(100))
        feed.header.incrementality = 1
        rekord = gyujto.valasz_mentese(
            self.data, "TripUpdates", feed.SerializeToString(), 100, 101
        )
        self.assertEqual(rekord["eredmeny"], "hibas_valasz")

    def test_menetrend_zip_es_kotelezo_fajlok(self):
        gyujto.menetrend_ellenorzes(proba_menetrend())
        with self.assertRaises((ValueError, zipfile.BadZipFile)):
            gyujto.menetrend_ellenorzes(b"nem zip")
        adat = io.BytesIO()
        with zipfile.ZipFile(adat, "w") as archiv:
            archiv.writestr("readme.txt", "hianyoznak az adatok")
        with self.assertRaises(ValueError):
            gyujto.menetrend_ellenorzes(adat.getvalue())
        rekord = gyujto.valasz_mentese(
            self.data, "Menetrend", proba_menetrend(zipfile.ZIP_BZIP2), 100, 101
        )
        self.assertEqual(rekord["eredmeny"], "hibas_valasz")

    def test_serult_zip_nem_sikeres_menetrend(self):
        adat = bytearray(proba_menetrend())
        with zipfile.ZipFile(io.BytesIO(adat)) as archiv:
            fajl = archiv.getinfo("agency.txt")
            hely = (
                fajl.header_offset + 30 + len(fajl.filename.encode()) + len(fajl.extra)
            )
        adat[hely] ^= 255
        rekord = gyujto.valasz_mentese(self.data, "Menetrend", bytes(adat), 100, 101)
        self.assertEqual(rekord["eredmeny"], "hibas_valasz")
        self.assertEqual((self.data / rekord["fajl"]).read_bytes(), bytes(adat))

    def test_menetrend_eredeti_zip_valtozatlan(self):
        adat = proba_menetrend()
        gyujto.menetrend_ellenorzes(adat)
        mentett = gyujto.mentes(self.data, "menetrend", adat, tomorit=False)
        self.assertEqual((self.data / mentett["fajl"]).read_bytes(), adat)

    def test_304_megtartja_a_korabbi_menetrend_hivatkozasat(self):
        adat = proba_menetrend()
        with (
            patch.object(
                gyujto, "letolt", return_value=(adat, 200, {"ETag": "proba-etag"})
            ),
            redirect_stdout(io.StringIO()),
        ):
            elso = gyujto.lepes(self.data, "Menetrend", "")
        with (
            patch.object(gyujto, "letolt", return_value=(b"", 304, {})) as kereses,
            redirect_stdout(io.StringIO()),
        ):
            masodik = gyujto.lepes(self.data, "Menetrend", "")
        self.assertEqual(masodik["eredmeny"], "nem_valtozott")
        self.assertEqual(masodik["fajl"], elso["fajl"])
        self.assertEqual(kereses.call_args.args[2]["If-None-Match"], "proba-etag")
        self.assertEqual(len(list(self.data.rglob("*.zip"))), 1)
        fajl = self.data / elso["fajl"]
        for tartalom in (None, b"serult archivum"):
            with self.subTest(tartalom=tartalom):
                if tartalom is None:
                    fajl.unlink()
                else:
                    fajl.write_bytes(tartalom)
                with (
                    patch.object(
                        gyujto, "letolt", return_value=(b"", 304, {})
                    ) as kereses,
                    redirect_stdout(io.StringIO()),
                ):
                    rekord = gyujto.lepes(self.data, "Menetrend", "", elozo=elso)
                self.assertEqual(kereses.call_args.args[2], {})
                self.assertEqual(rekord["eredmeny"], "hibas_http_status")

    def test_tul_nagy_halozati_valasz_elutasitva(self):
        with (
            patch.object(gyujto, "http_megnyitas", return_value=ProbaValasz(b"123456")),
            self.assertRaises(gyujto.LetoltesHiba) as eredmeny,
        ):
            gyujto.letolt("https://example.invalid/?key=TESZT_TITOK", 5)
        self.assertEqual(eredmeny.exception.fajta, "tul_nagy_valasz")

    def test_idotullepes_biztonsagos_hibava_alakul(self):
        with (
            patch.object(
                gyujto, "http_megnyitas", side_effect=TimeoutError("TESZT_TITOK")
            ),
            self.assertRaises(gyujto.LetoltesHiba) as eredmeny,
        ):
            gyujto.letolt("https://example.invalid/?key=TESZT_TITOK", 100)
        self.assertEqual(eredmeny.exception.fajta, "halozati_hiba")
        self.assertNotIn("TESZT_TITOK", str(eredmeny.exception))

    def test_retry_after_masodperc_es_datum(self):
        self.assertEqual(gyujto.retry_after("120", now=1000), 120)
        datum = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
        self.assertEqual(
            gyujto.retry_after(
                "Fri, 16 Oct 2026 12:00:00 GMT", now=datum.timestamp() - 42
            ),
            42,
        )
        self.assertEqual(
            gyujto.retry_after(
                "Fri, 16 Oct 2026 12:00:00 GMT", now=datum.timestamp() + 42
            ),
            0,
        )
        self.assertIsNone(gyujto.retry_after("nem datum"))
        self.assertLessEqual(gyujto.retry_after("9" * 100), gyujto.MAX_VARAKOZAS)

    def test_429_varakozas_naplo_es_kimenet_titokmentes(self):
        titok = "CSAK_KITALALT_TESZT_KULCS"
        url = "https://example.invalid/?key=" + titok
        hiba = HTTPError(url, 429, url, {"Retry-After": "120"}, None)
        self.addCleanup(hiba.close)
        kimenet = io.StringIO()
        with (
            patch.object(gyujto, "http_megnyitas", side_effect=hiba),
            redirect_stdout(kimenet),
        ):
            rekord = gyujto.lepes(self.data, "TripUpdates", titok, hibak=1)
        self.assertEqual(rekord["http_status"], 429)
        self.assertEqual(rekord["retry_after_mp"], 120)
        self.assertEqual(rekord["varakozas_mp"], 120)
        self.assertEqual(rekord["egymas_utani_hibak"], 2)
        self.assertTrue(hiba.closed)
        naplo = "".join(p.read_text() for p in self.data.rglob("*.json"))
        for tartalom in (kimenet.getvalue(), naplo):
            self.assertNotIn(titok, tartalom)
            self.assertNotIn("https://", tartalom)
        hiba = HTTPError(url, 429, url, {}, None)
        self.addCleanup(hiba.close)
        with patch.object(gyujto, "http_megnyitas", side_effect=hiba):
            try:
                gyujto.letolt(url, 100)
            except gyujto.LetoltesHiba as biztonsagos:
                self.assertNotIn(
                    titok, "".join(traceback.format_exception(biztonsagos))
                )

    def test_tartalek_tarhely_nelkul_nincs_siker(self):
        adat = proba_feed(100)
        kimenet = io.StringIO()
        with (
            patch.object(gyujto, "letolt", return_value=(adat, 200, {})),
            patch.object(gyujto.shutil, "disk_usage") as lemez,
            redirect_stdout(kimenet),
        ):
            lemez.return_value.free = 1
            rekord = gyujto.lepes(self.data, "TripUpdates", "KITALALT")
        self.assertEqual(rekord["eredmeny"], "helyi_hiba")
        self.assertNotIn("siker", kimenet.getvalue())
        self.assertEqual(list(self.data.rglob("*.pb.gz")), [])

    def test_serult_archivumot_nem_ir_felul(self):
        adat = proba_feed(100)
        rekord = gyujto.mentes(self.data, "TripUpdates", adat)
        fajl = self.data / rekord["fajl"]
        fajl.write_bytes(gzip.compress(b"serult masik tartalom"))
        elotte = fajl.read_bytes()
        with self.assertRaises(OSError):
            gyujto.mentes(self.data, "TripUpdates", adat)
        self.assertEqual(fajl.read_bytes(), elotte)

    def test_kihagyott_uteseket_nem_potolja_rohamban(self):
        self.assertEqual(gyujto.kovetkezo_utes(100, 100, 30), (130, 0))
        self.assertEqual(gyujto.kovetkezo_utes(100, 195, 30), (220, 3))

    def test_egyszeri_kor_veges_es_nem_indit_keresrohamot(self):
        ora = ProbaOra()
        keresesek = []

        def lepes(data, forras, kulcs, hibak, **kwargs):
            keresesek.append((forras, ora.masodperc))
            if len(keresesek) == 1:
                ora.masodperc += 45
            return {
                "eredmeny": "siker",
                "egymas_utani_hibak": 0,
                "http_status": 200,
                "varakozas_mp": 30,
            }

        with (
            patch.object(gyujto.time, "monotonic", ora.monotonic),
            patch.object(gyujto.time, "time", ora.time),
            patch.object(gyujto.time, "sleep", ora.sleep),
            patch.object(gyujto, "lepes", side_effect=lepes),
        ):
            gyujto.futtat(self.data, "KITALALT", egyszer=True)
        self.assertEqual([p[0] for p in keresesek], list(gyujto.FORRASOK))
        self.assertEqual([p[1] for p in keresesek], [0, 45, 55])

    def test_429_utan_mas_forras_is_var(self):
        ora = ProbaOra()
        keresesek = []

        def lepes(data, forras, kulcs, hibak, **kwargs):
            keresesek.append(ora.masodperc)
            if len(keresesek) == 1:
                return {
                    "eredmeny": "http_hiba",
                    "egymas_utani_hibak": 1,
                    "http_status": 429,
                    "varakozas_mp": 70,
                }
            return {
                "eredmeny": "siker",
                "egymas_utani_hibak": 0,
                "http_status": 200,
                "varakozas_mp": 30,
            }

        with (
            patch.object(gyujto.time, "monotonic", ora.monotonic),
            patch.object(gyujto.time, "time", ora.time),
            patch.object(gyujto.time, "sleep", ora.sleep),
            patch.object(gyujto, "lepes", side_effect=lepes),
        ):
            gyujto.futtat(self.data, "KITALALT", egyszer=True)
        self.assertEqual(keresesek, [0, 70, 80])

    def test_orankenti_minoseg_kulon_latja_a_hibakat(self):
        for ido, status in ((100, "siker"), (130, "halozati_hiba"), (160, "siker")):
            rekord = {
                "forras": "TripUpdates",
                "kezdett_utc": gyujto.utc(ido),
                "eredmeny": status,
            }
            if status == "siker":
                rekord.update({"feed_ido": None, "menetfrissitesek": 5})
            gyujto.naplo(self.data, rekord)
        gyujto.naplo(
            self.data,
            {
                "forras": "TripUpdates",
                "kezdett_utc": gyujto.utc(190),
                "eredmeny": "siker",
                "teszt": True,
            },
        )
        rekord = gyujto.minoseg(self.data)[0]["forrasok"]["TripUpdates"]
        self.assertEqual(rekord["probak"], 3)
        self.assertEqual(rekord["siker"], 2)
        self.assertEqual(rekord["hibak"], 1)
        self.assertEqual(rekord["ido_hianyzik"], 2)
        self.assertEqual(rekord["max_res_mp"], 30)

    def test_kapcsolok_nelkul_csak_sugo(self):
        with (
            patch.object(
                gyujto, "beolvas_kulcs", side_effect=AssertionError("titokfajl")
            ),
            patch.object(gyujto, "letolt", side_effect=AssertionError("halozat")),
            redirect_stdout(io.StringIO()) as kimenet,
        ):
            self.assertEqual(gyujto.main([]), 0)
        self.assertIn("--folyamatos", kimenet.getvalue())

    def test_ures_mintamappa_nem_sikeres_ellenorzes(self):
        with (
            patch.object(
                gyujto, "beolvas_kulcs", side_effect=AssertionError("titokfajl")
            ),
            patch.object(gyujto, "letolt", side_effect=AssertionError("halozat")),
            redirect_stdout(io.StringIO()),
        ):
            eredmeny = gyujto.main(
                ["--ellenorzes", str(self.data / "ures"), "--adatmappa", str(self.data)]
            )
        self.assertEqual(eredmeny, 1)

    def test_masodik_peldany_nem_indulhat(self):
        with (
            gyujto.egy_peldany(self.data),
            self.assertRaises((RuntimeError, OSError)),
            gyujto.egy_peldany(self.data),
        ):
            self.fail("A masodik gyujto belepett a zarolt reszbe.")
        with gyujto.egy_peldany(self.data):
            pass

    def test_ervenyes_protobuf_eleje_is_hianyos_halozati_valasz(self):
        adat = proba_feed(100)
        gyujto.feed_adatok(adat, "TripUpdates", 101)
        valasz = ProbaValasz(adat, fejlecek={"Content-Length": str(len(adat) + 5)})
        with (
            patch.object(gyujto, "http_megnyitas", return_value=valasz),
            redirect_stdout(io.StringIO()),
        ):
            rekord = gyujto.lepes(self.data, "TripUpdates", "KITALALT")
        self.assertEqual(rekord["eredmeny"], "hianyos_valasz")
        self.assertNotIn("fajl", rekord)

    def test_kulcsos_keres_atiranyitasa_korlatozott(self):
        keres = Request("https://example.invalid/feed?key=KITALALT")
        atiranyitas = gyujto.BiztonsagosAtiranyitas()
        for url in (
            "https://masik.invalid/feed?key=KITALALT",
            "https://example.invalid:444/feed?key=KITALALT",
            "http://example.invalid/feed?key=KITALALT",
        ):
            with (
                self.subTest(url=url),
                self.assertRaises(gyujto.LetoltesHiba) as eredmeny,
            ):
                atiranyitas.redirect_request(keres, None, 302, "atiranyitas", {}, url)
            self.assertEqual(eredmeny.exception.fajta, "tiltott_atiranyitas")
        engedett = atiranyitas.redirect_request(
            keres,
            None,
            302,
            "atiranyitas",
            {},
            "https://example.invalid/uj?key=KITALALT",
        )
        self.assertEqual(engedett.full_url, "https://example.invalid/uj?key=KITALALT")

    def test_kisbetus_retry_after_fejlec_is_mukodik(self):
        hiba = HTTPError(
            "https://example.invalid", 429, "korlat", {"retry-after": "73"}, None
        )
        self.addCleanup(hiba.close)
        with (
            patch.object(gyujto, "http_megnyitas", side_effect=hiba),
            self.assertRaises(gyujto.LetoltesHiba) as eredmeny,
        ):
            gyujto.letolt("https://example.invalid", 100)
        self.assertEqual(eredmeny.exception.varakozas, 73)
        self.assertTrue(hiba.closed)

    def test_ujraindulas_megorzi_a_sikeres_keresek_varakozasat(self):
        ora = ProbaOra()
        gyujto.naplo(
            self.data,
            {
                "forras": "Alerts",
                "kezdett_utc": gyujto.utc(ora.time() - 2),
                "kovetkezo_engedelyezett_utc": gyujto.utc(ora.time() + 58),
                "eredmeny": "siker",
                "egymas_utani_hibak": 0,
                "http_status": 200,
            },
        )
        keresesek = []

        def lepes(data, forras, kulcs, hibak, **kwargs):
            keresesek.append((forras, ora.masodperc))
            return {
                "eredmeny": "siker",
                "egymas_utani_hibak": 0,
                "http_status": 200,
                "varakozas_mp": 30,
            }

        with (
            patch.object(gyujto.time, "monotonic", ora.monotonic),
            patch.object(gyujto.time, "time", ora.time),
            patch.object(gyujto.time, "sleep", ora.sleep),
            patch.object(gyujto, "lepes", side_effect=lepes),
        ):
            gyujto.futtat(self.data, "KITALALT", egyszer=True)
        self.assertEqual(
            keresesek, [("VehiclePositions", 8), ("TripUpdates", 18), ("Alerts", 58)]
        )

    def test_ures_ora_es_orahataron_atnyulo_adatres_lathato(self):
        for ido in (3590, 7210):
            gyujto.naplo(
                self.data,
                {
                    "forras": "TripUpdates",
                    "kezdett_utc": gyujto.utc(ido),
                    "eredmeny": "siker",
                },
            )
        orak = gyujto.minoseg(self.data)
        self.assertEqual(len(orak), 3)
        self.assertEqual(orak[1]["forrasok"]["TripUpdates"]["probak"], 0)
        self.assertEqual(orak[2]["forrasok"]["TripUpdates"]["max_res_mp"], 3620)
        egy_ora = gyujto.minoseg(self.data, ora=orak[2]["ora_utc"])
        self.assertEqual(egy_ora[0]["forrasok"]["TripUpdates"]["max_res_mp"], 3620)

    def test_import_nem_ker_titkot_vagy_halozatot(self):
        kod = (
            "from unittest.mock import patch\n"
            "with patch('pathlib.Path.read_text', side_effect=AssertionError('fajlolvasas')), "
            "patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('halozat')), "
            "patch('socket.create_connection', side_effect=AssertionError('halozat')):\n"
            "    import gyujto\n"
        )
        eredmeny = subprocess.run(
            [sys.executable, "-c", kod],
            cwd=Path(__file__).parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stderr)


if __name__ == "__main__":
    unittest.main()
