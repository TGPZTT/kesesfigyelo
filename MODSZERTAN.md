# Módszertan

Egyelőre a gyűjtő helyi változata van kész. A felügyelet nélküli szerveres futás, a késésszámítás és az adatbázisba töltés még hátravan. Az eredeti válaszokat mentem el, hogy később vissza lehessen nézni, miből számoltam.

A VehiclePositions és a TripUpdates tervezett lekérése 30, az Alertsé 60 másodpercenként történik. A félperces minta a megállók közti mozgás követéséhez kell; a ritkábban változó zavarjelzésekhez egy percet választottam. A menetrendet naponta ellenőrzöm, a ZIP változatait megtartom. Ezek saját beállítások, nem a BKK által megadott kvóták. Két kérés kezdete között legalább 10 másodperc van, lassulás után nincs gyors pótlás. A letöltések egymás után futnak, ezért egy lassú válasz késleltetheti a következőt; ez a naplóban látszik.

A válaszok tömörítve kerülnek a data/nyers mappába. Ugyanazt a tartalmat csak egyszer tárolom, de minden lekérési kísérlet külön bejegyzést kap a data/naplo alatt. A fájl csak kész állapotban kerül a helyére. A program nem töröl régi adatot, és mentés előtt legalább 2 GiB szabad helyet hagy.

Hálózati hibánál vár, ismétlődő BKK-hibánál egyre többet. A szerver által kért várakozást újraindítás után is betartja. Elutasított BKK-hozzáférésnél vagy mentési hibánál leáll. Az időjárási hiba csak az időjárási kérést halasztja, legalább 15 perccel; egy BKK-korlátozás sem tiltja az időjárási kérést. A kulcs helyi fájlban van, a naplóba nem kerül bele.

A legfontosabb buktató, hogy a TripUpdates időpontja lehet előrejelzés. Attól, hogy az időpont már elmúlt, még nem biztos, hogy akkor indult el a jármű. A hiányzó adatot nem veszem nulla késésnek. A NO_DATA, a SKIPPED és a CANCELED külön állapot. Az ADDED menet jogosan hiányozhat a statikus menetrendből. Az eltűnő menet önmagában nem bizonyít törlést. Sok egymás utáni járműpozíció sem jelent sok külön indulást.

Külön mentem a lekérés és a forrásadat időpontját, UTC szerint. Feldolgozáskor figyelni kell a szolgáltatási napra, a megállósorrendre, a 24 órán túli menetrendi időkre és az óraátállításra. A legutóbb letöltött menetrend és a valós idejű adat verzióját még össze kell egyeztetni.

Az órás összesítés most a gyűjtés ellenőrzésére való. A siker azt jelenti, hogy a választ elmentettem és a formátumát ellenőriztem. Ettől még lehet régi a tartalma, ezt külön jelzem. A járművek és menetfrissítések darabszáma az órán belüli legnagyobb pillanatnyi érték, nem egyedi járművek vagy indulások száma. A teljes órára tervezett darabszám csak viszonyítás, egy fél órája futó gyűjtésnél nem elvárt teljesítmény.

Futás közben csak a lezárt óra és a szükséges előzmények naplóit olvasom újra. Az összesítés hibája nem állítja le a nyers mentést. A teljes történet a --minoseg kapcsolóval számolható újra.

A szüneteket forrásonként, a lekérések kezdőidejéből számolom. A korábbi max_res_mp helyett egyértelműbb mezők vannak:

- max_keresi_res_mp a két egymást követő próbálkozás közti legnagyobb szünet, a hibás kérések is számítanak.
- max_sikeres_res_mp a két egymást követő sikeres válaszhoz tartozó lekérés közti legnagyobb szünet. A közben sikertelen kérések nem szakítják meg.
- utolso_keres_ota_mp és utolso_siker_ota_mp az utolsó próbálkozás, illetve sikeres lekérés óta eltelt idő az óra végén, a folyó óránál az ellenőrzés pillanatában. Így a még tartó kimaradás is látszik.

A lezárult szünet a későbbi kérés órájába kerül, akkor is, ha átnyúlik egy órahatáron. Az üres órák is megjelennek. A null azt jelenti, hogy nincs még megfelelő korábbi esemény, nem azt, hogy nem volt kimaradás. Ezek a letöltés folytonosságát írják le, a forrásadat frissességét és egy adott vonal lefedettségét külön kell vizsgálni.

A buszok a 46, 97E, 161 és 169E; villamosból az 1, 2, 3 és 4–6, troliból a 80 és 82 kerül a mintába. A keleti városrész buszait a közös cél felé utazás miatt választottam. Melléjük sűrű belső és hosszabb keresztirányú villamosok, valamint trolik kerülnek összehasonlításnak. Ez tíz vonal, a 4–6-ot egynek számolom. A H8 ezen felüli kiegészítés. A minta nem reprezentálja egész Budapestet.

A 2026. október 16-án letöltött 2802.20261016 menetrendben ellenőrzött azonosítók:

| Járműfajta | Vonal → route_id |
| --- | --- |
| Busz, route_type 3 | 46 → 0460; 97E → 0975; 161 → 1610; 169E → 1695 |
| Villamos, route_type 0 | 1 → 3010; 2 → 3020; 3 → 3030; 4–6 → 3046 |
| Troli, route_type 11 | 80 → 4800; 82 → 4820 |
| HÉV, route_type 109 | H8 → H8 |

Mind a tíz vonal aktív október 16-án és 17-én. A 4–6 október 16-án Újbuda-központból (F01998) Széll Kálmán tér felé 07:01, 07:03, 07:05 és 07:07-kor indul: ez kétperces követés. Október 17-én az ellenkező irányban, Széll Kálmán térről (F02477) 07:00, 07:04, 07:08 és 07:12 szerepel. A napi kivételeket is figyelembe vettem. Ez az adott megállóra és időszakra igaz, nem egész napos garancia. A sima 4-es 3040 és a pótlóbusz VP46 más azonosító, ezeken a napokon egyik sem aktív.

A H8 menetrendje október 17-én főleg Cinkota–Gödöllő meneteket tartalmaz. A megváltozott útvonalat nem szabad menetrendi kimaradásnak nézni. A gyűjtő a teljes feedeket menti, a vonalszűrés később történik. A tényleges indulások meghatározása és az ismétlésbiztos adatbázis-import a következő lépés.

Az október 16-i 17:47 UTC körüli egyszeri mintában mind a tíz vonal jelen volt a pozíciók és a menetfrissítések között. A H8-nál 5 jármű és 16 menetfrissítés látszott, az azonosítóik egyeztek a mentett menetrenddel. A TripUpdates fejlécének kora kb. 5 másodperc volt, mégis 16 H8-menetből 15 saját időbélyege 90 másodpercnél régebbi. Az éppen látható 5 jármű meneteinél ez 52–178 másodperc volt. Ez nem önmagában üzemkiesés: a fejléc, a jármű és az egyes menetek frissességét külön kell nézni. A feed nem adott menetrend-verziót; az azonosítóegyezés nem helyettesíti a későbbi verziókezelést.

Az időjárást az Open-Meteótól kérem, 15 percenként, a három helyre egy közös kéréssel. Ehhez nem kell kulcs vagy külön Python-csomag. Az egyszerű lekérés és a szabadon megadott három pont miatt választottam. A nem üzleti használatra ingyenes keretben ez napi legfeljebb 96 ilyen kérés, a három hely miatt 288 hívásegység. Az egyszeri próbák ezen felül számítanak.

Három rögzített pontot használok a menetrend megállókoordinátáiból:

| Térség | Kijelölt hely | Szélesség, hosszúság |
| --- | --- | --- |
| Belső Budapest | Deák Ferenc tér M, 007884 | 47.497413, 19.055158 |
| Rákosmente | Rákoskeresztúr, városközpont, 009684 | 47.478941, 19.256176 |
| H8 külső térsége | Gödöllő, Szabadság tér, 19868321 | 47.597505, 19.347599 |

A mentett mezők: temperature_2m (°C), precipitation (mm), wind_speed_10m (km/h), weather_code (WMO állapotkód). A current.time az adat érvényességi ideje UTC-ben, a current.interval az időtartama másodpercben. Ha az interval 900, a csapadék az előző 15 perc összege. A hiányzó érték null marad. A 30 percnél régebbi időjárási pontot réginek jelölöm; ez saját ellenőrzési határ.

A best_match beállításnál a szolgáltató választ időjárási modellt. Ez modelladat, részben interpolált érték is lehet; nem a megállóban működő mérőállomás adata. A 15 perces időlépcső nem jelent 15 percenként új modellfutást. A visszakapott rácspont eltérhet a kért koordinátától. A teljes eredeti JSON-válasz, az egységek, a rácspont, a lekérési idő és a kérés paraméterei megmaradnak. Újrafeldolgozáskor ezekből dolgozom, mert egy későbbi API-kérés már más adatot adhat.

Az időjárás külön sorban szerepel az órás összesítésben, óránként négy tervezett lekéréssel. A régi pontok és a hiányzó értékek száma kérésenként összeadódik. Feldolgozáskor az azonos térséghez és adat-időponthoz tartozó csapadékot nem szabad többször összeadni. Az időjárás kiegészítő magyarázat, nem bizonyíték arra, hogy az eső okozta a késést. A három pont térségi közelítés, nem minden megálló külön időjárása.

A három első elemzés a napszakok és napok közti eltérés, a vonal mentén felhalmozódó késés és a sűrű járatok követési ideje. A saját bővítés a közös cél felé közlekedő, egymást helyettesítő járatok együttes utasvárakozása. Az adatokból születő külön saját kérdés még nyitott. Minden eredmény mellé megfigyelésszám és adatlefedettség kell.

Források: [BKK](https://opendata.bkk.hu/data-sources), [GTFS Realtime](https://gtfs.org/documentation/realtime/reference/), [GTFS menetrend](https://gtfs.org/documentation/schedule/reference/), [Open-Meteo leírás](https://open-meteo.com/en/docs), [ingyenes használat](https://open-meteo.com/en/terms), [keretek](https://open-meteo.com/en/pricing), [több hely számlálása](https://github.com/open-meteo/open-meteo/issues/1295). Időjárási adatok: Open-Meteo, CC BY 4.0.
