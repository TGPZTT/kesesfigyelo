"""Kis kitalált minták; az adatbázisos próbák külön ideiglenes sémában futnak."""

import hashlib
import io
import json
import os
import tempfile
import unittest
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from google.transit import gtfs_realtime_pb2 as pb
from psycopg import sql

import betolto
import gyujto


# Ugyanaz a megálló kétszer szerepel, a harmadik idő már másnapra nyúlik.
def kis_menetrend(verzio="egy", plusz=None):
    fajlok = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n1,BKK,https://example.invalid,Europe/Budapest\n",
        "feed_info.txt": "feed_publisher_name,feed_publisher_url,feed_lang,feed_version,feed_start_date,feed_end_date\nBKK,https://example.invalid,hu," + verzio + ",20261016,20261019\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n0460,1,46,Vonal,3\n9999,1,999,Másik,3\n",
        "trips.txt": "route_id,service_id,trip_id,direction_id\n0460,S01,T001,0\n9999,S99,T999,1\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n001,Egy,47.5,19.1\n002,Kettő,47.6,19.2\n999,Másik,47.7,19.3\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT001,23:59:30,23:59:30,001,1\nT001,,,002,2\nT001,24:03:00,24:03:30,001,3\nT999,10:00:00,10:00:00,999,1\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nS01,1,1,1,1,1,1,1,20261016,20261018\nS99,1,1,1,1,1,1,1,20261016,20261018\n",
        "calendar_dates.txt": "service_id,date,exception_type\nS01,20261017,2\nS01,20261019,1\n",
    }
    fajlok.update(plusz or {})
    tartalom = io.BytesIO()
    with zipfile.ZipFile(tartalom, "w", zipfile.ZIP_DEFLATED) as csomag:
        for nev, szoveg in fajlok.items():
            csomag.writestr(nev, szoveg)
    return tartalom.getvalue()


def kis_feed(forras="TripUpdates", ido=1792152000):
    feed = pb.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = ido
    elem = feed.entity.add()
    elem.id = "elem-1"
    if forras == "TripUpdates":
        menet = elem.trip_update
        menet.trip.trip_id = "T001"
        menet.trip.route_id = "0460"
        menet.trip.start_date = "20261016"
        megallo = menet.stop_time_update.add()
        megallo.stop_id = "001"
        megallo.stop_sequence = 1
        megallo.departure.time = ido + 60
    elif forras == "VehiclePositions":
        jarmu = elem.vehicle
        jarmu.trip.trip_id = "T001"
        jarmu.trip.route_id = "0460"
        jarmu.trip.start_date = "20261016"
        jarmu.vehicle.id = "jarmu-1"
        jarmu.position.latitude = 47.5
        jarmu.position.longitude = 19.1
    else:
        elem.alert.header_text.translation.add(text="Terelés", language="hu")
    return feed


def kis_idojaras(ido=1792152000):
    return [{
        "latitude": hely[0], "longitude": hely[1],
        "current_units": {"time": "unixtime", "interval": "seconds", **gyujto.IDOJARAS_EGYSEGEK},
        "current": {"time": ido, "interval": 900, "temperature_2m": 10.5,
                    "precipitation": 0, "wind_speed_10m": 2.0, "weather_code": 0},
    } for hely in gyujto.IDOJARAS_PONTOK.values()]


class IdoProba(unittest.TestCase):
    def test_hianyzo_es_24_ora_feletti_ido(self):
        self.assertIsNone(betolto.ido_mp(None))
        self.assertIsNone(betolto.ido_mp(""))
        self.assertEqual(betolto.ido_mp("00:00:00"), 0)
        self.assertEqual(betolto.ido_mp("25:02:03"), 90123)
        for hibas in ("12:60:00", "12:00:60", "-1:00:00", "abc"):
            with self.subTest(hibas=hibas), self.assertRaises(ValueError):
                betolto.ido_mp(hibas)

    def test_oraatallitas_es_masnap(self):
        self.assertEqual(
            betolto.menetrendi_ido(date(2026, 10, 25), 3 * 3600),
            datetime(2026, 10, 25, 2, tzinfo=UTC),
        )
        self.assertEqual(
            betolto.menetrendi_ido(date(2026, 3, 29), 3 * 3600),
            datetime(2026, 3, 29, 1, tzinfo=UTC),
        )
        self.assertEqual(
            betolto.menetrendi_ido(date(2026, 10, 16), 25 * 3600),
            datetime(2026, 10, 16, 23, tzinfo=UTC),
        )


@unittest.skipUnless(os.environ.get("TEST_DATABASE_CONFIG"), "PostgreSQL-próbához TEST_DATABASE_CONFIG kell.")
class AdatbazisProba(unittest.TestCase):
    def setUp(self):
        atmeneti = tempfile.TemporaryDirectory()
        self.addCleanup(atmeneti.cleanup)
        self.data = Path(atmeneti.name)
        self.conn = betolto.kapcsolat(Path(os.environ["TEST_DATABASE_CONFIG"]))
        self.addCleanup(self.conn.close)
        self.sema_nev = "proba_" + uuid.uuid4().hex
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.sema_nev)))
        self.addCleanup(self.takarit)
        self.conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.sema_nev)))
        betolto.sema(self.conn)
        self.alap = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=4)

    def takarit(self):
        self.conn.execute("SET search_path TO public")
        self.conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.sema_nev)))

    def sor(self, lekerdezes, parameterek=()):
        return self.conn.execute(lekerdezes, parameterek).fetchone()

    def menetrend(self, verzio="egy", plusz=None):
        adat = kis_menetrend(verzio, plusz)
        sha = hashlib.sha256(adat).hexdigest()
        fajl = self.data / (sha + ".zip")
        fajl.write_bytes(adat)
        with self.conn.transaction():
            eredmeny = betolto.menetrend_betolt(self.conn, fajl, sha)
        return sha, fajl, eredmeny

    def naplo(self, forras, adat=None, perc=0, menetrend=None, **tobbi):
        kezdet = (self.alap + timedelta(minutes=perc)).timestamp()
        if adat is None:
            rekord = {"forras": forras, "kezdett_utc": gyujto.utc(kezdet),
                      "vegzett_utc": gyujto.utc(kezdet + 1), "eredmeny": "halozati_hiba"}
        else:
            rekord = gyujto.valasz_mentese(self.data, forras, adat, kezdet, kezdet + 1)
            rekord["http_status"] = 200
        if forras in gyujto.FORRASOK:
            rekord["ismert_menetrend_sha256"] = menetrend
        if forras == "Idojaras":
            rekord["parameterek"] = gyujto.idojaras_parameterek()
        rekord.update(tobbi)
        return gyujto.naplo(self.data, rekord)

    def betolt(self, fajl, jelolt=None):
        return betolto.naplo_betolt(self.conn, self.data, fajl, jelolt)

    def test_tiz_tabla_es_egy_minosegi_nezet(self):
        tablak = self.conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        ).fetchall()
        self.assertEqual({sor[0] for sor in tablak}, {
            "nyers_fajl", "lekeres", "vonal", "megallo", "menet",
            "megallasi_ido", "megfigyeles", "megallo_frissites", "zavar", "idojaras",
        })
        self.assertEqual(self.sor(
            "SELECT count(*) FROM information_schema.views "
            "WHERE table_schema = current_schema() AND table_name = 'adatminoseg'"
        ), (1,))

    def test_menetrend_verzio_sorrend_es_napi_kivetelek(self):
        sha, fajl, eredmeny = self.menetrend()
        menetrend_id = eredmeny["menetrend_id"]
        self.assertIsInstance(menetrend_id, int)
        with self.conn.transaction():
            ujra = betolto.menetrend_betolt(self.conn, fajl, sha)
        self.assertTrue(ujra["kihagyva"])
        self.assertEqual(ujra["menetrend_id"], menetrend_id)
        self.assertEqual(self.sor(
            "SELECT forras, sha256, menetrend_verzio, ervenyes_tol, ervenyes_ig, idozona "
            "FROM nyers_fajl WHERE id = %s", (menetrend_id,),
        ), ("Menetrend", sha, "egy", date(2026, 10, 16), date(2026, 10, 19), "Europe/Budapest"))
        self.assertEqual(self.sor("SELECT count(*) FROM vonal"), (1,))
        self.assertEqual(self.sor("SELECT vonal_id FROM vonal"), ("0460",))
        self.assertEqual(self.sor("SELECT count(*) FROM megallasi_ido WHERE megallo_id = '001'"), (2,))
        self.assertEqual(self.sor("SELECT indulas_mp, indulas FROM megallasi_ido WHERE sorrend = 3"), (86610, "24:03:30"))
        self.assertEqual(self.sor("SELECT indulas_mp FROM megallasi_ido WHERE sorrend = 2"), (None,))
        napok = [date(2026, 10, 16), date(2026, 10, 18), date(2026, 10, 19)]
        self.assertEqual(self.sor("SELECT napok FROM menet"), (napok,))
        masik_sha, _, masik = self.menetrend("ketto", {
            "calendar_dates.txt": "service_id,date,exception_type\nS01,20261018,2\nS01,20261019,1\n",
        })
        self.assertNotEqual(sha, masik_sha)
        self.assertNotEqual(menetrend_id, masik["menetrend_id"])
        self.assertEqual(self.sor("SELECT count(*) FROM menet WHERE menet_id = 'T001'"), (2,))
        self.assertEqual(self.sor("SELECT napok FROM menet WHERE menetrend_id = %s", (menetrend_id,)), (napok,))
        self.assertEqual(self.sor("SELECT napok FROM menet WHERE menetrend_id = %s", (masik["menetrend_id"],)),
                         ([date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 19)],))

    def test_naptar_helyett_csak_kiveteles_napok(self):
        self.menetrend(plusz={
            "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n",
            "calendar_dates.txt": "service_id,date,exception_type\nS01,20261019,1\nS01,20261016,1\n",
        })
        self.assertEqual(self.sor("SELECT napok FROM menet"), ([date(2026, 10, 16), date(2026, 10, 19)],))

    def test_nem_tamogatott_surusegi_menetrend_nem_marad_felig_bent(self):
        with self.assertRaises(ValueError):
            self.menetrend(plusz={"frequencies.txt": "trip_id,start_time,end_time,headway_secs\nT001,06:00:00,08:00:00,120\n"})
        self.assertEqual(self.sor("SELECT count(*) FROM nyers_fajl"), (0,))
        self.assertEqual(self.sor("SELECT count(*) FROM menet"), (0,))

    def test_ugyanaz_a_naplo_egyszer_ket_keres_kulon_sor(self):
        adat = kis_feed().SerializeToString()
        elso = self.naplo("TripUpdates", adat)
        masodik = self.naplo("TripUpdates", adat, perc=1)
        self.assertTrue(self.betolt(elso))
        self.assertFalse(self.betolt(elso))
        self.assertTrue(self.betolt(masodik))
        self.assertEqual(self.sor("SELECT count(*) FROM lekeres"), (2,))
        self.assertEqual(self.sor("SELECT count(*) FROM nyers_fajl"), (1,))
        self.assertEqual(self.sor("SELECT count(*) FROM megfigyeles"), (1,))
        self.assertEqual(self.sor("SELECT count(*) FROM megallo_frissites"), (1,))

    def test_mar_betoltott_naplo_nem_irhato_at_eszrevetlenul(self):
        fajl = self.naplo("TripUpdates", kis_feed().SerializeToString())
        self.betolt(fajl)
        rekord = json.loads(fajl.read_bytes())
        rekord["http_status"] = 201
        fajl.write_text(json.dumps(rekord), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.betolt(fajl)
        self.assertEqual(self.sor("SELECT count(*), max(http_status) FROM lekeres"), (1, 200))

    def test_hibas_lenyomatbol_nem_lesz_adatbazissor(self):
        fajl = self.naplo("TripUpdates", kis_feed().SerializeToString())
        rekord = json.loads(fajl.read_bytes())
        rekord["sha256"] = "0" * 64
        fajl.write_text(json.dumps(rekord), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.betolt(fajl)
        self.assertEqual(self.sor("SELECT count(*) FROM lekeres"), (0,))
        self.assertEqual(self.sor("SELECT count(*) FROM nyers_fajl"), (0,))

    def test_valtozatlan_elem_uj_feedben_es_modosult_elorejelzes(self):
        feed = kis_feed()
        for szam in range(4):
            if szam == 1:
                feed.header.timestamp += 30
            if szam == 2:
                feed.entity[0].trip_update.stop_time_update[0].departure.time += 45
            if szam == 3:
                feed.entity[0].trip_update.trip.start_date = "20261017"
            self.betolt(self.naplo("TripUpdates", feed.SerializeToString(), perc=szam))
        self.assertEqual(self.sor("SELECT count(*) FROM nyers_fajl"), (4,))
        self.assertEqual(self.sor("SELECT count(*) FROM megfigyeles"), (4,))
        self.assertEqual(self.sor("SELECT count(*) FROM megallo_frissites"), (4,))
        self.assertEqual(self.sor("SELECT count(DISTINCT szolgalati_nap) FROM megfigyeles"), (2,))
        self.assertEqual(self.sor("SELECT count(DISTINCT indulas) FROM megallo_frissites"), (2,))
        self.assertEqual(self.sor(
            "SELECT count(*) FROM megallo_frissites f JOIN megfigyeles m "
            "ON (m.nyers_id, m.sorrend) = (f.nyers_id, f.megfigyeles_sorrend)"
        ), (4,))

    def test_megszakadt_betoltes_visszagorgetheto(self):
        feed = kis_feed()
        masik = feed.entity.add()
        masik.CopyFrom(feed.entity[0])
        masik.id = "elem-2"
        masik.trip_update.trip.trip_id = "T002"
        masik.trip_update.stop_time_update[0].departure.time += 60
        fajl = self.naplo("TripUpdates", feed.SerializeToString())
        eredeti = betolto.beszur

        def megszakit(conn, tabla, sor):
            eredeti(conn, tabla, sor)
            if tabla == "megallo_frissites":
                raise RuntimeError("proba_megszakitas")

        with patch.object(betolto, "beszur", side_effect=megszakit), self.assertRaises(RuntimeError):
            self.betolt(fajl)
        self.assertEqual(self.sor("SELECT count(*) FROM lekeres"), (0,))
        self.assertEqual(self.sor("SELECT count(*) FROM nyers_fajl"), (0,))
        self.assertEqual(self.sor("SELECT count(*) FROM megfigyeles"), (0,))
        self.assertEqual(self.sor("SELECT count(*) FROM megallo_frissites"), (0,))
        self.assertTrue(self.betolt(fajl))
        sorok = self.conn.execute(
            "SELECT m.menet_id, f.megallo_id, f.indulas FROM megfigyeles m "
            "JOIN megallo_frissites f ON (m.nyers_id, m.sorrend) = (f.nyers_id, f.megfigyeles_sorrend) "
            "ORDER BY m.menet_id"
        ).fetchall()
        self.assertEqual(sorok, [
            ("T001", "001", datetime.fromtimestamp(1792152060, UTC)),
            ("T002", "001", datetime.fromtimestamp(1792152120, UTC)),
        ])

    def test_hianyzo_ertek_nem_nulla(self):
        feed = kis_feed()
        menet = feed.entity[0].trip_update
        menet.stop_time_update[0].ClearField("departure")
        masik = menet.stop_time_update.add()
        masik.stop_id = "002"
        masik.departure.time = 0
        masik.departure.delay = 0
        masik.departure.uncertainty = 0
        self.betolt(self.naplo("TripUpdates", feed.SerializeToString()))
        sorok = self.conn.execute("SELECT megallo_id, megallo_sorrend, indulas, indulas_keses, indulas_bizonytalansag FROM megallo_frissites ORDER BY megallo_id").fetchall()
        self.assertEqual(sorok[0], ("001", 1, None, None, None))
        self.assertEqual(sorok[1], ("002", None, datetime(1970, 1, 1, tzinfo=UTC), 0, 0))
        self.assertEqual(self.sor("SELECT kezdes FROM megfigyeles"), (None,))

    def test_no_data_es_skipped_idoponttal_is_kulon_allapot(self):
        feed = kis_feed()
        menet = feed.entity[0].trip_update
        menet.stop_time_update[0].schedule_relationship = pb.TripUpdate.StopTimeUpdate.NO_DATA
        masik = menet.stop_time_update.add()
        masik.stop_id = "002"
        masik.stop_sequence = 2
        masik.schedule_relationship = pb.TripUpdate.StopTimeUpdate.SKIPPED
        masik.departure.time = 1792152100
        self.betolt(self.naplo("TripUpdates", feed.SerializeToString()))
        sorok = self.conn.execute("SELECT allapot, indulas IS NOT NULL FROM megallo_frissites ORDER BY megallo_sorrend").fetchall()
        self.assertEqual(sorok, [(2, True), (1, True)])

    def test_torolt_es_hozzaadott_menet_statika_nelkul_is_megmarad(self):
        feed = kis_feed()
        feed.entity[0].trip_update.trip.schedule_relationship = pb.TripDescriptor.CANCELED
        uj = feed.entity.add()
        uj.id = "plusz"
        uj.trip_update.trip.trip_id = "NINCS-A-MENETRENDBEN"
        uj.trip_update.trip.route_id = "0460"
        uj.trip_update.trip.start_date = "20261016"
        uj.trip_update.trip.schedule_relationship = pb.TripDescriptor.ADDED
        self.betolt(self.naplo("TripUpdates", feed.SerializeToString()))
        allapotok = self.conn.execute("SELECT menet_allapot FROM megfigyeles ORDER BY menet_allapot").fetchall()
        self.assertEqual(allapotok, [(1,), (3,)])

    def test_vonalszures_es_hianyos_jarmu(self):
        feed = kis_feed("VehiclePositions")
        feed.entity[0].vehicle.ClearField("trip")
        masik = feed.entity.add()
        masik.id = "mas-vonal"
        masik.vehicle.trip.trip_id = "T999"
        masik.vehicle.trip.route_id = "9999"
        self.betolt(self.naplo("VehiclePositions", feed.SerializeToString()))
        self.assertEqual(self.sor("SELECT count(*) FROM megfigyeles"), (1,))
        self.assertEqual(self.sor("SELECT menet_id, jarmu_id, lat, forras_vonal_id, vonal_id FROM megfigyeles"),
                         (None, "jarmu-1", 47.5, None, None))
        self.assertEqual(self.sor("SELECT kihagyott FROM nyers_fajl"), (1,))
        self.assertEqual(self.sor("SELECT jarmuvek FROM lekeres"), (2,))

    def test_statika_feloldja_a_vonalat_de_csak_jelolt_marad(self):
        sha, _, eredmeny = self.menetrend()
        feed = kis_feed()
        feed.entity[0].trip_update.trip.ClearField("route_id")
        self.betolt(self.naplo("TripUpdates", feed.SerializeToString(), menetrend=sha))
        sor = self.sor("SELECT menetrend_id, vonal_id, feloldas FROM megfigyeles")
        self.assertEqual(sor[:2], (eredmeny["menetrend_id"], "0460"))
        self.assertIn("jelolt", sor[2])
        self.assertEqual(self.sor("SELECT forras_vonal_id FROM megfigyeles"), (None,))
        self.assertEqual(self.sor("SELECT ismert_menetrend_sha256 FROM lekeres"), (sha,))

    def test_zavar_tobb_idoszak_es_egyuttes_feltetelek(self):
        feed = kis_feed("Alerts")
        zavar = feed.entity[0].alert
        zavar.active_period.add(start=1792152000)
        zavar.active_period.add(end=1792155000)
        elso = zavar.informed_entity.add(route_id="0460", stop_id="001", direction_id=1)
        elso.trip.trip_id = "T001"
        elso.trip.route_id = "0460"
        elso.trip.direction_id = 0
        elso.trip.schedule_relationship = pb.TripDescriptor.ADDED
        elso.trip.start_date = "20261016"
        elso.trip.start_time = "25:00:00"
        zavar.informed_entity.add(route_id="0975")
        self.betolt(self.naplo("Alerts", feed.SerializeToString()))
        idoszakok, erintettek = self.sor("SELECT idoszakok, erintettek FROM zavar")
        self.assertEqual(idoszakok, [{"start": "1792152000"}, {"end": "1792155000"}])
        self.assertEqual(erintettek, [{
            "route_id": "0460", "stop_id": "001", "direction_id": 1,
            "trip": {"trip_id": "T001", "route_id": "0460", "direction_id": 0,
                     "schedule_relationship": 1, "start_date": "20261016", "start_time": "25:00:00"},
        }, {"route_id": "0975"}])
        self.assertEqual(self.sor("SELECT count(*) FROM megfigyeles"), (0,))

    def test_zavar_hianyzo_es_nullas_mezok(self):
        feed = kis_feed("Alerts")
        feed.entity[0].alert.active_period.add(start=0)
        feed.entity[0].alert.informed_entity.add(direction_id=0)
        masik = feed.entity.add()
        masik.id = "masodik"
        masik.alert.header_text.translation.add(text="Másik", language="hu")
        self.betolt(self.naplo("Alerts", feed.SerializeToString()))
        sorok = self.conn.execute("SELECT elem_id, idoszakok, erintettek FROM zavar ORDER BY elem_id").fetchall()
        self.assertEqual(sorok, [("elem-1", [{"start": "0"}], [{"direction_id": 0}]), ("masodik", [], [])])

    def test_idojaras_azonos_idopont_uj_ertek_es_hiany(self):
        adat = kis_idojaras()
        elso = self.naplo("Idojaras", json.dumps(adat).encode())
        self.betolt(elso)
        self.assertFalse(self.betolt(elso))
        adat[0]["current"]["precipitation"] = 0.5
        adat[1]["current"]["precipitation"] = None
        self.betolt(self.naplo("Idojaras", json.dumps(adat).encode(), perc=15))
        self.assertEqual(self.sor("SELECT count(*) FROM idojaras"), (6,))
        self.assertEqual(self.sor("SELECT count(DISTINCT adat_ido) FROM idojaras"), (1,))
        self.assertEqual(self.sor("SELECT count(*) FROM idojaras WHERE csapadek IS NULL"), (1,))
        self.assertEqual(self.sor("SELECT count(*) FROM idojaras WHERE csapadek = 0"), (4,))
        self.assertEqual(self.sor("SELECT count(*) FROM idojaras WHERE interval_mp = 900 AND parameterek IS NOT NULL AND egysegek IS NOT NULL"), (6,))

    def test_sikertelen_keres_es_ures_ora_minosege(self):
        adat = kis_feed().SerializeToString()
        for perc, tartalom in ((59, adat), (60, None), (61, adat), (181, adat)):
            self.betolt(self.naplo("TripUpdates", tartalom, perc=perc))
        ora = self.alap + timedelta(hours=1)
        sor = self.sor("SELECT probak, siker, hibak, max_keresi_res_mp, max_sikeres_res_mp FROM adatminoseg WHERE ora_utc = %s AND forras = 'TripUpdates'", (ora,))
        self.assertEqual(sor, (2, 1, 1, 60, 120))
        ures = self.sor("SELECT probak, siker, utolso_keres_ota_mp, utolso_siker_ota_mp FROM adatminoseg WHERE ora_utc = %s AND forras = 'TripUpdates'", (ora + timedelta(hours=1),))
        self.assertEqual(ures, (0, 0, 7140, 7140))
        self.assertEqual(self.sor("SELECT count(*) FROM lekeres WHERE nyers_id IS NULL"), (1,))
        self.assertEqual(self.sor("SELECT count(*) FROM nyers_fajl"), (1,))
        self.assertEqual(self.sor("SELECT count(*) FROM megfigyeles"), (1,))
        self.assertEqual(self.sor("SELECT max_menetfrissites FROM adatminoseg WHERE ora_utc = %s AND forras = 'TripUpdates'", (ora,)), (1,))

    def test_tesztkent_jelolt_naplo_nem_eles_adat(self):
        fajl = self.naplo("TripUpdates", kis_feed().SerializeToString(), teszt=True)
        self.assertFalse(self.betolt(fajl))
        self.assertEqual(self.sor("SELECT count(*) FROM lekeres"), (0,))


if __name__ == "__main__":
    unittest.main()
