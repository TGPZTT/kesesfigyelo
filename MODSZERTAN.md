# Módszertan

Egyelőre az adatgyűjtés van kész, a késésszámítás és az adatbázisba töltés még hátravan. Az eredeti BKK-válaszokat mentem el, hogy később vissza lehessen nézni, miből számoltam.

A VehiclePositions és a TripUpdates tervezett lekérése 30, az Alertsé 60 másodpercenként történik. A menetrendet naponta ellenőrzöm, a ZIP változatait megtartom. Ezek saját beállítások, nem a BKK által megadott kvóták. Két kérés kezdete között legalább 10 másodperc van, lassulás után nincs gyors pótlás.

A válaszok tömörítve kerülnek a data/nyers mappába. Ugyanazt a tartalmat csak egyszer tárolom, de minden lekérési kísérlet külön bejegyzést kap a data/naplo alatt. A fájl csak kész állapotban kerül a helyére. A program nem töröl régi adatot, és mentés előtt legalább 2 GiB szabad helyet hagy.

Hálózati hibánál vár, ismétlődő hibánál egyre többet. A szerver által kért várakozást újraindítás után is betartja. Elutasított hozzáférésnél vagy mentési hibánál leáll. A kulcs helyi fájlban van, a naplóba nem kerül bele.

A legfontosabb buktató, hogy a TripUpdates időpontja lehet előrejelzés. Attól, hogy az időpont már elmúlt, még nem biztos, hogy akkor indult el a jármű. A hiányzó adatot nem veszem nulla késésnek. A NO_DATA, a SKIPPED és a CANCELED külön állapot. Az eltűnő menet önmagában nem bizonyít törlést. Sok egymás utáni járműpozíció sem jelent sok külön indulást.

Külön mentem a lekérés és a forrásadat időpontját, UTC szerint. Feldolgozáskor figyelni kell a szolgáltatási napra, a megállósorrendre, a 24 órán túli menetrendi időkre és az óraátállításra. A legutóbb letöltött menetrend és a valós idejű adat verzióját még össze kell egyeztetni.

Az órás összesítés most a gyűjtés ellenőrzésére való. Hibákat, adatréseket és frissességet mutat. A benne szereplő darabszámok nem egyedi indulások. Egy fél órája futó gyűjtést sem szabad egy teljes óra elvárt darabszámához mérni.

A tervezett buszvonalak a 46, 97E, 161 és 169E. Villamosból az 1, 2, 3 és 4–6, troliból a 80 és 82 kerül a mintába. Ezek mellé jön még a H8. A 4–6-ot itt egynek számoltatom. A vonalazonosítókat és az öt percnél sűrűbb követést még ellenőrizni kell a menetrendben. Az eredmények erre a mintára vonatkoznak majd. A tényleges indulások meghatározása és az ismétlésbiztos adatbázis-import a következő lépés.

Források: [BKK](https://opendata.bkk.hu/data-sources), [GTFS Realtime](https://gtfs.org/documentation/realtime/reference/), [GTFS menetrend](https://gtfs.org/documentation/schedule/reference/).
