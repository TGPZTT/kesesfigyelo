-- Az első változat rögzített vonalszűréssel dolgozik. Más szűrés vagy feldolgozás
-- új adatbázisba tölthető újra, az eredeti nyers fájlokból.
-- A nyers fájl egyszer szerepel, de minden kérés külön sor marad.
-- A TIMESTAMPTZ mezők időpontok; a betöltő UTC szerint kezeli őket.
-- A lat szélességet, a lon hosszúságot jelent, földrajzi fokban.
CREATE TABLE IF NOT EXISTS nyers_fajl (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, -- Saját számos azonosító.
    forras TEXT NOT NULL,
    sha256 TEXT NOT NULL, -- A letöltött válasz ellenőrző összege, a .gz tömörítés előtt.
    fajl TEXT NOT NULL, -- A mentett fájl útvonala.
    nyers_bajt BIGINT NOT NULL CHECK (nyers_bajt >= 0), -- A válasz mérete, a .gz tömörítés előtt.
    feed_ido TIMESTAMPTZ, -- A valós idejű válasz fejlécének saját időpontja.
    feed_verzio TEXT, -- GTFS Realtime formátumverzió, például 2.0.
    menetrend_verzio TEXT, -- A szolgáltató menetrend-verziója, ha megadta.
    idozona TEXT,
    ervenyes_tol DATE,
    ervenyes_ig DATE,
    novekmenyes BOOLEAN, -- Teljes válasz helyett csak változásokat tartalmaz-e.
    jelolt_menetrend TEXT, -- A feloldáshoz használt menetrendi ZIP SHA256-értéke.
    feldolgozva BOOLEAN NOT NULL DEFAULT FALSE, -- Elkészültek-e a belőle bontott sorok.
    feldolgozasi_hiba TEXT, -- Például nem támogatott válaszformátum.
    kihagyott INTEGER NOT NULL DEFAULT 0 CHECK (kihagyott >= 0), -- Szűrt vagy nem kezelt elemek száma.
    UNIQUE (forras, sha256)
);

CREATE TABLE IF NOT EXISTS lekeres (
    id UUID PRIMARY KEY, -- A napló fájlnevében szereplő kérésazonosító.
    naplo_sha256 TEXT NOT NULL, -- Ebből észrevehető, ha a naplót utólag átírták.
    forras TEXT NOT NULL,
    kezdett TIMESTAMPTZ NOT NULL, -- A letöltési kísérlet kezdete.
    vegzett TIMESTAMPTZ NOT NULL, -- A letöltési kísérlet vége.
    eredmeny TEXT NOT NULL,
    http_status INTEGER,
    nyers_id BIGINT REFERENCES nyers_fajl (id),
    ismert_menetrend_sha256 TEXT, -- Ez a menetrend volt ismert a kérés idején.
    jarmuvek INTEGER, -- Az egész válaszban lévő járművek száma, szűrés előtt.
    menetfrissitesek INTEGER, -- Az egész válasz menetfrissítéseinek száma.
    feed_regi BOOLEAN, -- A gyűjtő saját korhatára szerint régi válasz.
    regi_pontok INTEGER, -- Régi időjárási térségek száma ebben a kérésben.
    hianyzo_ertekek INTEGER -- Hiányzó időjárási értékek száma ebben a kérésben.
);

CREATE INDEX IF NOT EXISTS lekeres_forras_ido ON lekeres (forras, kezdett);
CREATE INDEX IF NOT EXISTS lekeres_siker_ido ON lekeres (forras, kezdett)
    WHERE eredmeny = 'siker';

-- A menetrend az eredeti ZIP-re mutat. A BKK saját azonosítói szövegek.
CREATE TABLE IF NOT EXISTS vonal (
    menetrend_id BIGINT NOT NULL REFERENCES nyers_fajl (id),
    vonal_id TEXT NOT NULL,
    nev TEXT,
    tipus INTEGER, -- GTFS járműfajta: például 0 villamos, 3 busz.
    PRIMARY KEY (menetrend_id, vonal_id)
);

CREATE TABLE IF NOT EXISTS megallo (
    menetrend_id BIGINT NOT NULL REFERENCES nyers_fajl (id),
    megallo_id TEXT NOT NULL,
    nev TEXT,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    PRIMARY KEY (menetrend_id, megallo_id)
);

CREATE TABLE IF NOT EXISTS menet (
    menetrend_id BIGINT NOT NULL REFERENCES nyers_fajl (id),
    menet_id TEXT NOT NULL,
    vonal_id TEXT NOT NULL,
    szolgalat_id TEXT NOT NULL, -- A menetrend közlekedési naptárának azonosítója.
    irany INTEGER, -- A forrás 0/1 iránykódja; önmagában nem égtáj.
    napok DATE[] NOT NULL, -- Ezeken a napokon közlekedik, a kivételekkel együtt.
    PRIMARY KEY (menetrend_id, menet_id),
    FOREIGN KEY (menetrend_id, vonal_id) REFERENCES vonal (menetrend_id, vonal_id)
);

-- A nap másodperce lehet 86400-nál nagyobb. A sorrend a körjáratokat is kezeli.
CREATE TABLE IF NOT EXISTS megallasi_ido (
    menetrend_id BIGINT NOT NULL,
    menet_id TEXT NOT NULL,
    sorrend INTEGER NOT NULL, -- A megálló helye a menetben, a GTFS stop_sequence.
    megallo_id TEXT NOT NULL,
    erkezes_mp INTEGER, -- Érkezés a szolgáltatási nap kezdetétől, másodpercben.
    indulas_mp INTEGER, -- Indulás ugyanígy; 86400-nál nagyobb is lehet.
    erkezes TEXT, -- Az eredeti menetrendi szöveg, például 25:10:00.
    indulas TEXT,
    felszallas INTEGER, -- GTFS pickup_type: 0 szokásos, 1 nem lehet felszállni.
    kiszallas INTEGER, -- GTFS drop_off_type: 0 szokásos, 1 nem lehet leszállni.
    PRIMARY KEY (menetrend_id, menet_id, sorrend),
    FOREIGN KEY (menetrend_id, menet_id) REFERENCES menet (menetrend_id, menet_id),
    FOREIGN KEY (menetrend_id, megallo_id) REFERENCES megallo (menetrend_id, megallo_id)
);

-- Egy sor egy mentett válasz egy járműhelyzete vagy menetfrissítése.
CREATE TABLE IF NOT EXISTS megfigyeles (
    nyers_id BIGINT NOT NULL REFERENCES nyers_fajl (id),
    sorrend INTEGER NOT NULL, -- Az elem helye a nyers válaszban, nullától számolva.
    elem_id TEXT, -- A BKK válaszbeli elemének azonosítója.
    tipus TEXT NOT NULL, -- vehicle vagy trip_update.
    forras_vonal_id TEXT, -- A válaszban ténylegesen megadott vonalazonosító.
    vonal_id TEXT, -- A megadott vagy a menetrendből feloldott vonal.
    menetrend_id BIGINT REFERENCES nyers_fajl (id),
    feloldas TEXT, -- Honnan ismert a vonal, vagy miért nem sikerült feloldani.
    potolt_vonal_id TEXT, -- Névegyezésből kapott kapcsolatjelölt; több találatnál NULL.
    potlas_jelzes TEXT, -- Pótlóvonal vagy ellenőrzendő jelölt; a módszertan felsorolja az értékeket.
    menet_id TEXT,
    szolgalati_nap DATE, -- A menet napja; éjfél után eltérhet a naptári naptól.
    kezdes TEXT, -- A menet forrás szerinti kezdőideje, ha szerepel.
    irany INTEGER, -- A forrás 0/1 iránykódja.
    menet_allapot INTEGER, -- GTFS schedule_relationship, például törölt vagy hozzáadott menet.
    keses INTEGER, -- A teljes menethez megadott késés másodpercben, ha van.
    jarmu_id TEXT,
    adat_ido TIMESTAMPTZ, -- Az egyedi jármű vagy menetfrissítés saját időpontja.
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    megallo_id TEXT,
    megallo_sorrend INTEGER, -- A megálló sorszáma a menetben, a forrás szerint.
    jarmu_allapot INTEGER, -- GTFS current_status: érkezik, megállóban áll vagy úton van.
    sebesseg DOUBLE PRECISION, -- A közölt sebesség méter/másodpercben, nem két pontból számítva.
    ajto_nyitva BOOLEAN, -- BKK-kiegészítés. A hiányzó jel NULL, nem zárt ajtó.
    megallo_tavolsag INTEGER, -- BKK stop_distance. HÉV-nél negatív is lehet.
    letert BOOLEAN, -- A forrás útvonaltól eltérést jelzett-e.
    PRIMARY KEY (nyers_id, sorrend)
);

CREATE INDEX IF NOT EXISTS megfigyeles_menet ON megfigyeles (menet_id, szolgalati_nap);
CREATE INDEX IF NOT EXISTS megfigyeles_vonal ON megfigyeles (vonal_id);

-- Ezek előrejelzések. A hiányzó érték NULL, az állapot külön mező.
CREATE TABLE IF NOT EXISTS megallo_frissites (
    nyers_id BIGINT NOT NULL,
    megfigyeles_sorrend INTEGER NOT NULL, -- Melyik megfigyeléshez tartozik ugyanabban a fájlban.
    sorrend INTEGER NOT NULL, -- A frissítés helye a listában; nem a menetrendi sorszám.
    megallo_id TEXT,
    megallo_sorrend INTEGER, -- GTFS stop_sequence, ha megadta a forrás.
    allapot INTEGER, -- GTFS állapot, például SKIPPED vagy NO_DATA.
    erkezes TIMESTAMPTZ, -- A válaszban szereplő, gyakran becsült érkezési időpont.
    indulas TIMESTAMPTZ, -- A válaszban szereplő, gyakran becsült indulási időpont.
    erkezes_keses INTEGER, -- Másodperc; a negatív érték korábbi érkezést jelent.
    indulas_keses INTEGER, -- Másodperc; NULL esetén nincs külön késésmező.
    erkezes_bizonytalansag INTEGER, -- A forrás időbecslésének bizonytalansága, másodpercben.
    indulas_bizonytalansag INTEGER,
    forras_tervezett_erkezes TIMESTAMPTZ, -- A BKK-kiegészítés menetrendje, nem az érkezési becslés.
    forras_tervezett_indulas TIMESTAMPTZ, -- Eltérhet a külön letöltött GTFS időpontjától.
    PRIMARY KEY (nyers_id, megfigyeles_sorrend, sorrend),
    FOREIGN KEY (nyers_id, megfigyeles_sorrend) REFERENCES megfigyeles (nyers_id, sorrend)
);

CREATE TABLE IF NOT EXISTS zavar (
    nyers_id BIGINT NOT NULL REFERENCES nyers_fajl (id),
    sorrend INTEGER NOT NULL, -- A zavar helye a nyers válaszban, nullától számolva.
    elem_id TEXT,
    ok INTEGER, -- GTFS cause kód: a zavar oka.
    hatas INTEGER, -- GTFS effect kód: a közlekedésre gyakorolt hatás.
    cim TEXT,
    leiras TEXT,
    idoszakok JSONB NOT NULL, -- active_period lista, start/end időbélyegekkel.
    erintettek JSONB NOT NULL, -- informed_entity lista: vonal, menet, megálló és más feltételek.
    PRIMARY KEY (nyers_id, sorrend)
);

-- Azonos időpontra is jöhet új modellérték, ezért a nyers válasz is része a kulcsnak.
CREATE TABLE IF NOT EXISTS idojaras (
    nyers_id BIGINT NOT NULL REFERENCES nyers_fajl (id),
    terseg TEXT NOT NULL,
    adat_ido TIMESTAMPTZ,
    interval_mp INTEGER, -- Az időjárási adat időtartama másodpercben, jellemzően 900.
    kert_lat DOUBLE PRECISION, -- A kérésben megadott szélesség.
    kert_lon DOUBLE PRECISION, -- A kérésben megadott hosszúság.
    lat DOUBLE PRECISION, -- A szolgáltató visszaadott rácspontjának szélessége.
    lon DOUBLE PRECISION, -- A visszaadott rácspont hosszúsága.
    homerseklet DOUBLE PRECISION, -- Celsius-fok.
    csapadek DOUBLE PRECISION, -- Az előző interval_mp időtartam összege, mm.
    szel DOUBLE PRECISION, -- Szélsebesség km/h-ban.
    kod INTEGER, -- WMO időjárási állapotkód.
    egysegek JSONB, -- A szolgáltató által visszaadott mértékegységek.
    parameterek JSONB, -- A kérés beállításai, például helyek és modellválasztás.
    PRIMARY KEY (nyers_id, terseg)
);

-- A nézet csak a már betöltött naplókból számol. Az üres órák is látszanak.
CREATE OR REPLACE VIEW adatminoseg AS
WITH most AS (
    SELECT statement_timestamp() AS ido
), keresek AS (
    SELECT l.*, n.feed_ido,
        lag(l.kezdett) OVER (PARTITION BY l.forras ORDER BY l.kezdett, l.id) AS elozo_keres,
        max(l.kezdett) FILTER (WHERE l.eredmeny = 'siker') OVER (
            PARTITION BY l.forras ORDER BY l.kezdett, l.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS elozo_siker
    FROM lekeres l
    LEFT JOIN nyers_fajl n ON n.id = l.nyers_id
    WHERE l.forras IN ('VehiclePositions', 'TripUpdates', 'Alerts', 'Idojaras')
        AND l.kezdett <= (SELECT ido FROM most)
), orak AS (
    SELECT ora AT TIME ZONE 'UTC' AS ora_utc
    FROM generate_series(
        (SELECT date_trunc('hour', min(kezdett) AT TIME ZONE 'UTC') FROM keresek),
        (SELECT date_trunc('hour', ido AT TIME ZONE 'UTC') FROM most),
        interval '1 hour'
    ) AS sor(ora)
), forrasok(forras, teljes_orara_tervezett) AS (
    VALUES ('VehiclePositions', 120), ('TripUpdates', 120), ('Alerts', 60), ('Idojaras', 4)
), osszeg AS (
    SELECT date_trunc('hour', kezdett AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS ora_utc,
        forras,
        count(*) AS probak,
        count(*) FILTER (WHERE eredmeny = 'siker') AS siker,
        count(*) FILTER (WHERE eredmeny <> 'siker') AS hibak,
        count(*) FILTER (WHERE feed_regi) AS regi_feed,
        count(*) FILTER (WHERE eredmeny = 'siker' AND feed_ido IS NULL
            AND forras <> 'Idojaras') AS ido_hianyzik,
        max(jarmuvek) AS max_jarmu,
        max(menetfrissitesek) AS max_menetfrissites,
        sum(regi_pontok) AS regi_pontok,
        sum(hianyzo_ertekek) AS hianyzo_ertekek,
        max(extract(epoch FROM kezdett - elozo_keres)) AS max_keresi_res_mp,
        max(extract(epoch FROM kezdett - elozo_siker))
            FILTER (WHERE eredmeny = 'siker') AS max_sikeres_res_mp
    FROM keresek
    GROUP BY 1, 2
)
SELECT o.ora_utc, f.forras,
    least(o.ora_utc + interval '1 hour', m.ido) AS ellenorzott_utc,
    coalesce(s.probak, 0) AS probak,
    coalesce(s.siker, 0) AS siker,
    coalesce(s.hibak, 0) AS hibak,
    coalesce(s.regi_feed, 0) AS regi_feed,
    coalesce(s.ido_hianyzik, 0) AS ido_hianyzik,
    coalesce(s.max_jarmu, 0) AS max_jarmu,
    coalesce(s.max_menetfrissites, 0) AS max_menetfrissites,
    coalesce(s.regi_pontok, 0) AS regi_pontok,
    coalesce(s.hianyzo_ertekek, 0) AS hianyzo_ertekek,
    s.max_keresi_res_mp,
    s.max_sikeres_res_mp,
    extract(epoch FROM least(o.ora_utc + interval '1 hour', m.ido) - e.kezdett)
        AS utolso_keres_ota_mp,
    extract(epoch FROM least(o.ora_utc + interval '1 hour', m.ido) - j.kezdett)
        AS utolso_siker_ota_mp,
    f.teljes_orara_tervezett,
    TRUE AS reszora_lehet
FROM orak o
CROSS JOIN forrasok f
CROSS JOIN most m
LEFT JOIN osszeg s ON s.ora_utc = o.ora_utc AND s.forras = f.forras
LEFT JOIN LATERAL (
    SELECT kezdett FROM lekeres
    WHERE forras = f.forras AND kezdett < o.ora_utc + interval '1 hour'
        AND kezdett <= m.ido
    ORDER BY kezdett DESC LIMIT 1
) e ON TRUE
LEFT JOIN LATERAL (
    SELECT kezdett FROM lekeres
    WHERE forras = f.forras AND eredmeny = 'siker'
        AND kezdett < o.ora_utc + interval '1 hour' AND kezdett <= m.ido
    ORDER BY kezdett DESC LIMIT 1
) j ON TRUE;
