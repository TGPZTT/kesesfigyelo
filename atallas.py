"""Hat forrásmező pótlása a már betöltött eredeti válaszokból.

A hívó indítja a tranzakciót. Hiba esetén az oszlopok és az értékek együtt
visszavonódnak. A gyűjtőfájlokat és a régi adatbázismezőket nem írja át.
"""
import gzip
import hashlib
from pathlib import Path
from time import monotonic

from google.transit import gtfs_realtime_pb2 as pb
from psycopg import sql
from psycopg.pq import TransactionStatus

from betolto import idopont, mezo
from bkk_bovites import jarmu_bovites, megallo_bovites

MEZOK = {
    'megfigyeles': {'sebesseg':'double precision', 'ajto_nyitva':'boolean',
                    'megallo_tavolsag':'integer', 'letert':'boolean'},
    'megallo_frissites': {'forras_tervezett_erkezes':'timestamp with time zone',
                        'forras_tervezett_indulas':'timestamp with time zone'},
}


def oszlopok(conn):
    for table, fields in MEZOK.items():
        existing = dict(conn.execute("SELECT column_name,data_type FROM information_schema.columns "
                                    "WHERE table_schema=current_schema() AND table_name=%s", (table,)))
        if not existing:
            raise ValueError('Hiányzik az átállítandó tábla.')
        for name, kind in fields.items():
            if name in existing and existing[name] != kind:
                raise ValueError('Eltérő meglévő oszloptípus.')
            if name not in existing:
                conn.execute(sql.SQL('ALTER TABLE {} ADD COLUMN {} {}').format(
                    sql.Identifier(table), sql.Identifier(name), sql.SQL(kind)))


def nyers(row, root):
    raw_id, name, digest, feed_time = row
    path = Path(name)
    path = path if path.is_absolute() else root / path
    # A szerver abszolút elérési útját is a külön helyi másolatra képezzük.
    if path.is_absolute() and not path.resolve().is_relative_to(root.resolve()):
        prefix = '/home/ubuntu/kesesfigyelo/data/'
        if not name.startswith(prefix):
            raise ValueError('A nyers fájl kilóg az adatmappából.')
        path = root / name.removeprefix(prefix)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('A nyers fájl kilóg az adatmappából.')
    with (gzip.open(path,'rb') if path.suffix == '.gz' else path.open('rb')) as stream:
        payload = stream.read()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError('Eltér a nyers fájl ellenőrző összege.')
    feed = pb.FeedMessage.FromString(payload)
    if not feed.IsInitialized() or idopont(mezo(feed.header,'timestamp')) != feed_time:
        raise ValueError('Hiányos vagy eltérő idejű nyers válasz.')
    if feed.header.incrementality != 0 or feed.header.gtfs_realtime_version not in ('1.0','2.0'):
        raise ValueError('Nem támogatott nyers válasz.')
    return feed


def atallas(conn, adatmappa, haladas=print):
    """Csak az új mezők változnak. A két átmeneti tábla a tranzakció végén eltűnik."""
    start = monotonic()
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError('Az átállítást egyetlen tranzakcióban kell indítani.')
    conn.execute('SELECT pg_advisory_xact_lock(741027)')
    oszlopok(conn)
    conn.execute('''CREATE TEMP TABLE _vp_potlas (
        nyers_id bigint, sorrend integer, sebesseg double precision,
        ajto_nyitva boolean, megallo_tavolsag integer, letert boolean) ON COMMIT DROP''')
    conn.execute('''CREATE TEMP TABLE _tu_potlas (
        nyers_id bigint, megfigyeles_sorrend integer, sorrend integer,
        megallo_id text, megallo_sorrend integer,
        forras_tervezett_erkezes timestamptz, forras_tervezett_indulas timestamptz) ON COMMIT DROP''')
    files = conn.execute("SELECT id,fajl,sha256,feed_ido FROM nyers_fajl "
                         "WHERE forras IN ('VehiclePositions','TripUpdates') AND feldolgozva "
                         "AND feldolgozasi_hiba IS NULL ORDER BY id").fetchall()
    staged = {'vehicle':0,'trip_update':0,'megallo_frissites':0}
    for number, row in enumerate(files, 1):
        feed = nyers(row, Path(adatmappa))
        parents = conn.execute('''SELECT sorrend,elem_id,tipus,jarmu_id,menet_id,adat_ido
            FROM megfigyeles WHERE nyers_id=%s ORDER BY sorrend''', (row[0],)).fetchall()
        vehicles, stops = [], []
        for index, entity_id, kind, vehicle_id, trip_id, data_time in parents:
            if index < 0 or index >= len(feed.entity):
                raise ValueError('Eltér a betöltött elem sorszáma.')
            entity = feed.entity[index]
            if kind not in ('vehicle','trip_update') or not entity.HasField(kind) or entity.is_deleted:
                raise ValueError('Eltér a betöltött elem típusa.')
            item = getattr(entity, kind)
            identity = (entity.id, mezo(item.vehicle,'id'), mezo(item.trip,'trip_id'),
                        idopont(mezo(item,'timestamp')))
            if identity != (entity_id, vehicle_id, trip_id, data_time):
                raise ValueError('Eltér a nyers és a betöltött elem azonosítása.')
            staged[kind] += 1
            if kind == 'vehicle':
                extension = jarmu_bovites(item.vehicle)
                vehicles.append((row[0],index,mezo(item.position,'speed'),extension['ajto_nyitva'],
                                 extension['megallo_tavolsag'],extension['letert']))
            else:
                for stop_index, stop in enumerate(item.stop_time_update):
                    extension = megallo_bovites(stop)
                    stops.append((row[0],index,stop_index,mezo(stop,'stop_id'),mezo(stop,'stop_sequence'),
                                  idopont(extension['forras_tervezett_erkezes']),
                                  idopont(extension['forras_tervezett_indulas'])))
        for table, values in (('_vp_potlas',vehicles),('_tu_potlas',stops)):
            if values:
                with conn.cursor().copy(sql.SQL('COPY {} FROM STDIN').format(sql.Identifier(table))) as copy:
                    for value in values:
                        copy.write_row(value)
        staged['megallo_frissites'] += len(stops)
        if number % 500 == 0 or number == len(files):
            haladas('Ellenőrzött nyers válaszok ' + str(number) + ' / ' + str(len(files)), flush=True)
    # A kimaradt vagy többször felsorolt forrásfájlt a darabszámok is megfogják.
    for kind in ('vehicle','trip_update'):
        actual = conn.execute('SELECT count(*) FROM megfigyeles WHERE tipus=%s', (kind,)).fetchone()[0]
        if actual != staged[kind]:
            raise ValueError('Nem fedik le a nyers fájlok az összes megfigyelést.')
    if conn.execute('SELECT count(*) FROM megallo_frissites').fetchone()[0] != staged['megallo_frissites']:
        raise ValueError('Eltér a nyers és a betöltött megállói sorok száma.')
    conn.execute('ANALYZE _vp_potlas')
    conn.execute('ANALYZE _tu_potlas')
    haladas('Minden forrás ellenőrizve. Az új mezők visszatöltése indul.', flush=True)
    vp = conn.execute('''UPDATE megfigyeles m SET
        sebesseg=s.sebesseg,ajto_nyitva=s.ajto_nyitva,megallo_tavolsag=s.megallo_tavolsag,letert=s.letert
        FROM _vp_potlas s WHERE m.nyers_id=s.nyers_id AND m.sorrend=s.sorrend
        AND (m.sebesseg,m.ajto_nyitva,m.megallo_tavolsag,m.letert)
            IS DISTINCT FROM (s.sebesseg,s.ajto_nyitva,s.megallo_tavolsag,s.letert)''').rowcount
    haladas('Visszatöltött járműhelyzetek ' + str(vp), flush=True)
    tu = conn.execute('''UPDATE megallo_frissites m SET
        forras_tervezett_erkezes=s.forras_tervezett_erkezes,
        forras_tervezett_indulas=s.forras_tervezett_indulas
        FROM _tu_potlas s WHERE m.nyers_id=s.nyers_id
          AND m.megfigyeles_sorrend=s.megfigyeles_sorrend AND m.sorrend=s.sorrend
          AND m.megallo_id IS NOT DISTINCT FROM s.megallo_id
          AND m.megallo_sorrend IS NOT DISTINCT FROM s.megallo_sorrend
          AND (m.forras_tervezett_erkezes,m.forras_tervezett_indulas)
            IS DISTINCT FROM (s.forras_tervezett_erkezes,s.forras_tervezett_indulas)''').rowcount
    haladas('Visszatöltött megállói frissítések ' + str(tu), flush=True)
    # Az egyezésbe a hiányzó mezők is beletartoznak. A NULL nem nulla vagy hamis.
    matched, errors = conn.execute('''SELECT count(*),count(*) FILTER (WHERE
        (m.sebesseg,m.ajto_nyitva,m.megallo_tavolsag,m.letert)
        IS DISTINCT FROM (s.sebesseg,s.ajto_nyitva,s.megallo_tavolsag,s.letert))
        FROM _vp_potlas s JOIN megfigyeles m USING(nyers_id,sorrend)''').fetchone()
    if matched != staged['vehicle'] or errors:
        raise ValueError('Eltér a visszatöltött járműadat.')
    matched, errors = conn.execute('''SELECT count(*),count(*) FILTER (WHERE
        m.megallo_id IS DISTINCT FROM s.megallo_id OR m.megallo_sorrend IS DISTINCT FROM s.megallo_sorrend OR
        (m.forras_tervezett_erkezes,m.forras_tervezett_indulas)
        IS DISTINCT FROM (s.forras_tervezett_erkezes,s.forras_tervezett_indulas))
        FROM _tu_potlas s JOIN megallo_frissites m USING(nyers_id,megfigyeles_sorrend,sorrend)''').fetchone()
    if matched != staged['megallo_frissites'] or errors:
        raise ValueError('Eltér a visszatöltött megállói adat.')
    return {'nyers_fajlok':len(files), 'ellenorzott_sorok':staged,
            'modositott_jarmusor':vp, 'modositott_megalloi_sor':tu,
            'teljes_forras_egyezes':True, 'masodperc':round(monotonic()-start,2)}
