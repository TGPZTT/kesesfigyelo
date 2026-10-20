# Módszertan

## Mit akarok megtudni?

A kérdés az, hogy melyik vonalon, mikor és hol romlik a közlekedés, és ez mennyi plusz várakozást jelent.
A menetrendi késés önmagában nem elég. Egy öt percet késő, de szabályosan érkező villamossor más helyzet,
mint két egymás mögött érkező villamos és az utánuk maradó hosszú szünet.

A BKK válasza nem kész induláslista. Ugyanahhoz az induláshoz sok, időközben változó becslés tartozhat.
Először ezekből kell megállapítani, mit tudunk az indulásról. Utána lehet késést és várakozást számolni.
A bizonytalan és hiányzó esetek darabszáma az eredmény mellett is megmarad.

## Röviden a fogalmakról

| Fogalom | Mit jelent itt? |
| --- | --- |
| Vonal | Például a 97E vagy a közösen vizsgált 4–6. Egy vonalon sok menet közlekedik. |
| Menet | A vonal egy konkrét végighaladása, egy adott szolgálati napon és irányban. Nem azonos a járművel. |
| Jármű | A busz, villamos vagy troli. Ugyanaz a jármű egymás után több menetet is teljesíthet. |
| Megállói indulás | Egy menet indulása egy meghatározott megállóból. A megálló sorszáma is számít, mert egy menet visszatérhet ugyanoda. |
| Megfigyelés | Egy mentett válasz egy eleme. Sok megfigyelés szólhat ugyanarról az indulásról. |
| Becslés | A szolgáltató által közölt várható idő. Később változhat. A nulla bizonytalanság sem önálló bizonyíték az indulásra. |
| Szolgálati nap | A menet menetrendi napja. A szombati `25:10:00` vasárnap hajnali 01:10-et jelent. |
| Késés | A megállapított indulás és a menetrendi indulás különbsége. A negatív érték korai indulás. |
| Követési idő | Két egymást követő indulás közti idő ugyanabban a megállóban, irányban és összehasonlítható járatcsoportban. |
| Plusz várakozás | A számított tényleges és menetrendi várakozás különbsége. Ez utasmodellből kapott érték, nem mért utasadat. |
| Lefedettség | Mennyi tervezett indulásról, illetve mekkora időszakról van használható adat. |
| Medián és 90. percentilis | A medián a sorba rendezett értékek közepe. A 90. percentilis a sor 90%-ánál számított határ, két szomszédos érték között szükség szerint interpolálva. Kis mintánál nem jelenti azt, hogy pontosan 90% van alatta. |

A korai érkezés és a korai indulás külön dolog. A jármű megérkezhet korábban, majd kivárhatja az indulását.
Az utas számára az a probléma, ha már a meghirdetett indulás előtt elmegy. A negatív késést ezért nem írom át nullára.

## Gyűjtés

A gyűjtő és az adatbázis a szerveren fut. A betöltő külön dolgozik, az elemző csak a mentett adatokat olvassa.
Az eredeti válaszokat megtartom, hogy később vissza lehessen nézni, miből számoltam.

Október 18-án 19:17–19:30 között a VPS leállása miatt kimaradt a gyűjtés. A járműhelyzeteknél és menetfrissítéseknél
13 perc telt el két sikeres kérés között. Indulás után a gyűjtés magától folytatódott, a korábbi fájlok megmaradtak.
A hiányzó időszakot nem pótolom becsléssel. Az adatminőségi kimutatásban és az érintett elemzéseknél látszania kell.

A VehiclePositions és a TripUpdates tervezett lekérése 30, az Alertsé 60 másodpercenként történik. A félperces minta a megállók közti mozgás követéséhez kell. A ritkábban változó zavarjelzésekhez egy percet választottam. A menetrendet naponta ellenőrzöm, a ZIP változatait megtartom. Ezek saját beállítások, nem a BKK által megadott kvóták. Két kérés kezdete között legalább 10 másodperc van, lassulás után nincs gyors pótlás. A letöltések egymás után futnak, ezért egy lassú válasz késleltetheti a következőt. Ez a naplóban látszik.

A válaszok tömörítve kerülnek a data/nyers mappába. Ugyanazt a tartalmat csak egyszer tárolom, de minden lekérési kísérlet külön bejegyzést kap a data/naplo alatt. A fájl csak kész állapotban kerül a helyére. A program nem töröl régi adatot, és mentés előtt legalább 2 GiB szabad helyet hagy.

Hálózati hibánál vár, ismétlődő BKK-hibánál egyre többet. A szerver által kért várakozást újraindítás után is betartja. Elutasított BKK-hozzáférésnél vagy mentési hibánál leáll. Az időjárási hiba csak az időjárási kérést halasztja, legalább 15 perccel. Egy BKK-korlátozás sem tiltja az időjárási kérést. A kulcs helyi fájlban van, a naplóba nem kerül bele.

A legfontosabb buktató, hogy a TripUpdates időpontja lehet előrejelzés. Attól, hogy az időpont már elmúlt, még nem biztos, hogy akkor indult el a jármű. A hiányzó adatot nem veszem nulla késésnek. A NO_DATA, a SKIPPED és a CANCELED külön állapot. Az ADDED menet jogosan hiányozhat a statikus menetrendből. Az eltűnő menet önmagában nem bizonyít törlést. Sok egymás utáni járműpozíció sem jelent sok külön indulást.

Külön mentem a lekérés és a forrásadat időpontját, UTC szerint. Feldolgozáskor figyelni kell a szolgáltatási napra, a megállósorrendre, a 24 órán túli menetrendi időkre és az óraátállításra. Az elemzés előtt a menetrendváltozatokat is össze kell vetni.

Az órás összesítés most a gyűjtés ellenőrzésére való. A siker azt jelenti, hogy a választ elmentettem és a formátumát ellenőriztem. Ettől még lehet régi a tartalma, ezt külön jelzem. A járművek és menetfrissítések darabszáma az órán belüli legnagyobb pillanatnyi érték, nem egyedi járművek vagy indulások száma. A teljes órára tervezett darabszám csak viszonyítás, egy fél órája futó gyűjtésnél nem elvárt teljesítmény.

Futás közben csak a lezárt óra és a szükséges előzmények naplóit olvasom újra. Az összesítés hibája nem állítja le a nyers mentést. A teljes történet a --minoseg kapcsolóval számolható újra.

A szüneteket forrásonként, a lekérések kezdőidejéből számolom. A korábbi max_res_mp helyett egyértelműbb mezők vannak:

- max_keresi_res_mp a két egymást követő próbálkozás közti legnagyobb szünet, a hibás kérések is számítanak.
- max_sikeres_res_mp a két egymást követő sikeres válaszhoz tartozó lekérés közti legnagyobb szünet. A közben sikertelen kérések nem szakítják meg.
- utolso_keres_ota_mp és utolso_siker_ota_mp az utolsó próbálkozás, illetve sikeres lekérés óta eltelt idő az óra végén, a folyó óránál az ellenőrzés pillanatában. Így a még tartó kimaradás is látszik.

A lezárult szünet a későbbi kérés órájába kerül, akkor is, ha átnyúlik egy órahatáron. Az üres órák is megjelennek. A null azt jelenti, hogy nincs még megfelelő korábbi esemény, nem azt, hogy nem volt kimaradás. Ezek a letöltés folytonosságát írják le, a forrásadat frissességét és egy adott vonal lefedettségét külön kell vizsgálni.

Az Alerts sikeres letöltése csak azt igazolja, hogy választ kaptam és elmentettem.
A fejléc néha a zavarszövegek változása nélkül frissül, máskor régi marad.
Ebből nem tudom biztosan megmondani, hogy minden új zavar szerepel-e benne.
A régi vagy hiányzó forrásidőt külön jelzem. Ez önmagában nem a gyűjtő leállása.
Az `active_period` a jelzés megjelenítési időszaka, nem a frissítés vagy a valódi esemény mért ideje.
A késést és a várakozást nem az Alerts alapján számolom, így emiatt a megfelelő járműadatot nem dobom el.

A buszok a 46, 97E, 161 és 169E. Villamosból az 1, 2, 3 és 4–6, troliból a 80 és 82 kerül a mintába. A keleti városrész buszait a közös cél felé utazás miatt választottam. Melléjük sűrű belső és hosszabb keresztirányú villamosok, valamint trolik kerülnek összehasonlításnak. Ez tíz vonal, a 4–6-ot egynek számolom. A H8 ezen felüli kiegészítés. A minta nem reprezentálja egész Budapestet.

A 2026. október 16-án letöltött 2802.20261016 menetrendben ellenőrzött azonosítók:

| Járműfajta | Vonal → route_id |
| --- | --- |
| Busz, route_type 3 | 46 → 0460, 97E → 0975, 161 → 1610, 169E → 1695 |
| Villamos, route_type 0 | 1 → 3010, 2 → 3020, 3 → 3030, 4–6 → 3046 |
| Troli, route_type 11 | 80 → 4800, 82 → 4820 |
| HÉV, route_type 109 | H8 → H8 |

Mind a tíz vonal aktív október 16-án és 17-én. A 4–6 október 16-án Újbuda-központból (F01998) Széll Kálmán tér felé 07:01, 07:03, 07:05 és 07:07-kor indul. Ez kétperces követés. Október 17-én az ellenkező irányban, Széll Kálmán térről (F02477) 07:00, 07:04, 07:08 és 07:12 szerepel. A napi kivételeket is figyelembe vettem. Ez az adott megállóra és időszakra igaz, nem egész napos garancia. A sima 4-es 3040 és a pótlóbusz VP46 más azonosító, ezeken a napokon egyik sem aktív.

A H8 menetrendje október 17-én főleg Cinkota–Gödöllő meneteket tartalmaz. A megváltozott útvonalat nem szabad menetrendi kimaradásnak nézni. A gyűjtő a teljes feedeket menti, a vonalszűrés az adatbázisba töltéskor történik. Az indulások meghatározása külön feldolgozási lépés, nem a betöltő feladata.

Az október 16-i 17:47 UTC körüli egyszeri mintában mind a tíz vonal jelen volt a pozíciók és a menetfrissítések között. A H8-nál 5 jármű és 16 menetfrissítés látszott, az azonosítóik egyeztek a mentett menetrenddel. A TripUpdates fejlécének kora kb. 5 másodperc volt, mégis 16 H8-menetből 15 saját időbélyege 90 másodpercnél régebbi. Az éppen látható 5 jármű meneteinél ez 52–178 másodperc volt. Ez nem önmagában üzemkiesés. A fejléc, a jármű és az egyes menetek frissességét külön kell nézni. A feed nem adott menetrend-verziót. Az azonosítóegyezés nem helyettesíti a későbbi verziókezelést.

Az időjárást az Open-Meteótól kérem, 15 percenként, a három helyre egy közös kéréssel. Ehhez nem kell kulcs vagy külön Python-csomag. Az egyszerű lekérés és a szabadon megadott három pont miatt választottam. A nem üzleti használatra ingyenes keretben ez napi legfeljebb 96 ilyen kérés, a három hely miatt 288 hívásegység. Az egyszeri próbák ezen felül számítanak.

Három rögzített pontot használok a menetrend megállókoordinátáiból:

| Térség | Kijelölt hely | Szélesség, hosszúság |
| --- | --- | --- |
| Belső Budapest | Deák Ferenc tér M, 007884 | 47.497413, 19.055158 |
| Rákosmente | Rákoskeresztúr, városközpont, 009684 | 47.478941, 19.256176 |
| H8 külső térsége | Gödöllő, Szabadság tér, 19868321 | 47.597505, 19.347599 |

A mentett mezők: temperature_2m (°C), precipitation (mm), wind_speed_10m (km/h), weather_code (WMO állapotkód). A current.time az adat érvényességi ideje UTC-ben, a current.interval az időtartama másodpercben. Ha az interval 900, a csapadék az előző 15 perc összege. A hiányzó érték null marad. A 30 percnél régebbi időjárási pontot réginek jelölöm. Ez saját ellenőrzési határ.

A best_match beállításnál a szolgáltató választ időjárási modellt. Ez modelladat, részben interpolált érték is lehet. Nem a megállóban működő mérőállomás adata. A 15 perces időlépcső nem jelent 15 percenként új modellfutást. A visszakapott rácspont eltérhet a kért koordinátától. A teljes eredeti JSON-válasz, az egységek, a rácspont, a lekérési idő és a kérés paraméterei megmaradnak. Újrafeldolgozáskor ezekből dolgozom, mert egy későbbi API-kérés már más adatot adhat.

Az időjárás külön sorban szerepel az órás összesítésben, óránként négy tervezett lekéréssel. A régi pontok és a hiányzó értékek száma kérésenként összeadódik. Feldolgozáskor az azonos térséghez és adat-időponthoz tartozó csapadékot nem szabad többször összeadni. Az időjárás kiegészítő magyarázat, nem bizonyíték arra, hogy az eső okozta a késést. A három pont térségi közelítés, nem minden megálló külön időjárása.

Az öt elemzési szempont a menetrendhez igazodás szerinti rangsor, a napszakok és napok közti eltérés,
a megállók között keletkező késés, a sűrű járatok követési ideje és az adatban nem szereplő tervezett menetek száma.
A korai érkezés utáni kivárás a korábbi, mozgásból becsült eljárás ellenőrző kérdése volt.
Az új web ezt nem mutatja, mert a mozgásellenőrzés időablaka nem igazolt indulási hibahatár.
A saját utaskérdés az, hogy érdemes-e az első buszra felszállni, vagy egy másik járatot megvárni.
A buszos bővítés a 97E, 161 és 169E közül az azonos megállóból azonos célig közlekedő járatok teljes utazási idejét hasonlítja össze.
A 46-os ebben a csoportban nem szerepel. A tíz alapvonal elemzésében továbbra is benne van.
A közös megállót és célt is ellenőrizni kell. Csak az utas számára ténylegesen helyettesítő menetek kerülhetnek egy csoportba.
Minden eredmény mellé megfigyelésszám és adatlefedettség kell.

A rangsor a menetrendi indulástól legfeljebb egy perccel eltérő indulások arányát mutatja az értékelhető indulások között.
A korai és a késői indulás egyaránt eltérés. A kétperces határ külön is választható, mert más határ más sorrendet adhat.
A nevező megállói indulások száma, ezért a hosszabb menetek több ponttal szerepelnek. Ez nem általános utaselégedettségi rangsor.
A sűrű villamosnál a követés és a várakozás külön fontos. A lefedettség és a szigorúbb indulásvizsgálat eredménye is kell a sorrend megítéléséhez.

A nem megfigyelt meneteket a menetrendi menetazonosító és a szolgálati nap alapján számolom.
Elég egy hozzá rendelhető járműpozíció vagy menetfrissítés ahhoz, hogy ne legyen megfigyelés nélküli,
akkor is, ha indulási időt ebből nem lehet megállapítani. Az időbélyeg nélküli közlés is jelenlét.
Csak olyan menet számít, amelynek van felszállást engedő tervezett indulása a vizsgált naptári napon.
Több nap közös összegében az éjfélen átnyúló menet egyszer szerepel.
A hiány azt jelenti, hogy a vizsgált adatban nincs hozzá közlés, nem azt, hogy biztosan nem közlekedett.

Az időjárási összevetésnél azonos térség és időpont ismétléseiből a később rögzített modellértéket használom.
A hőmérséklet és a szél az órán belüli időpontokhoz tartozik. A csapadékhoz az óra végén lezáruló négy negyedórát adom össze.
Ha egy negyedóra hiányzik, az órás csapadék ismeretlen marad. A kapcsolatvizsgálat a kiválasztott időjárási jellemző négy negyedóráját kéri. A hőmérsékletet nem zárja ki önmagában a hiányos csapadékóra.
A kiválasztott vonal órás késése mellé térségi időjárás kerül, nem az egyes megállók helyi mérése.

Az időjárási hőtérképen minden vizsgált járat és mindhárom időjárási jellemző szerepel.
Az összevetéshez legalább 30 felhasználható elindulás és 50 százalék adatlefedettség kell óránként.
Legalább két napon meglévő azonos órákból indulok ki. A nap és az óra különbségére is korrigált számítás alább szerepel.
Ehhez összesen legalább három nap, 12 óra és hat különböző órasáv kell. Ez saját mintaminimum, nem bizonyossági határ. Az órák és a megállói adatok nem független megfigyelések.
Változatlan csapadékból vagy késésből nincs korreláció. A hiányzó érték nem nulla. A −0,3 és +0,3 közötti kapcsolatot leíró értelemben gyengének jelölöm.
A legerősebb abszolút kapcsolat külön ábrát kap. Ez utólagos kiemelés, nem előre megfogalmazott feltevés igazolása.
Az ábrán óránként a legkisebb és legnagyobb időjárási értékű nap alkot párt. Legalább 1 °C, 1 km/h vagy 0,1 mm eltérés kell. A korreláció minden megfelelő órából készül, az ábra ezekből mutat párokat.

A fő nézet a medián mellett a legnagyobb megfigyelt késést mutatja a teljes gyakorisági eloszlásból. Ez egy szélső eset, nem jellemző késés és nem az adathiányos időszakok igazolt maximuma.
A megállólisták az aktív menetrendből készülnek. Azonos nevű, egymás melletti peronokat egy megállóként mutatok. Az utak darabszámát menetazonosító és szolgálati nap szerint egyesítem.
Az október 17–19-i mentett csapadékértékek mind nullák, így ezekből esős és száraz időszakok késéskülönbsége nem számítható.
A hőmérséklet vagy a szél együtt változhat a napszakkal és a forgalommal. Egy közös ábra ezért nem bizonyít ok-okozati kapcsolatot.

## Indulás, késés és várakozás

Az új feldolgozás egyelőre helyi próba. A szerveren futó számítás és a webes eredmények még nem változtak.
A BKK módszerének neve `kozles-haladas-ajto-1`, a HÉV külön változata `hev-kozles-kontroll-1`.
A kétféle forrást nem vonom közös pontossági rangsorba. A régi és új exportot sem keverem.

A feladat lényegi buktatója, hogy a TripUpdates indulási ideje előrejelzés is lehet.
A nulla bizonytalanság a szolgáltató állítása. Nem külön mérés, és önmagában nem igazolja az indulást.
A helyzet és az időbecslés közös rendszerből származhat. Az egyezésük sem független bizonyíték.

Az adat útja

- A FUTÁR fedélzeti egysége helyzetet és üzemi adatokat továbbít a BKK központjába. A HÉV adatai a MÁV integrációján keresztül jutnak ide.
- A VehiclePositions saját időbélyege a helyzethez tartozik. Az ajtójel külön időbélyeget nem kap.
- A TripUpdates saját ideje a felhasznált járműadat ideje. Ugyanazzal a saját idővel újabb, javított becslés is érkezhet.
- A feed ideje a válasz elkészítéséhez tartozik. A lekérés és a fájlmentés ideje ettől külön adat.

Az új szabály

1. A szolgálati napot, járművet, megállóazonosítót és megállósorrendet összerendelem a menetrenddel. Más jármű adata nem pótolja a hiányzó időt.
2. Az utolsó közölt változatot használom. Már múltbeli indulást kell tartalmaznia, nulla közölt bizonytalansággal. Két külön saját időhöz tartozó utolsó közlésnek ugyanazt kell mondania. Egy befagyott válasz sok letöltése csak egy közlés.
3. Megkeresem az előtte és utána jelzett helyzetet. A járműnek a megálló közelében, a megfelelő irányban kell továbbhaladnia. A két pont között legfeljebb 120 másodperc telhet el. Hibás köztes helyzetet nem ugrok át.
4. Ha van használható ajtójel, az ellentmondását is figyelem. A BKK-jármű közölt indulásánál több mint öt másodperccel későbbi nyitott ajtó kizárja az esetet. Az öt másodperc választott technikai tűrés, nem igazolt pontosság.
5. Ellenőrzöm az időrendet és a más közlekedésekhez is hozzárendelt járműadatokat. A kihagyott megállót, a törlést és a hiányt külön kezelem.

A törlési jelzés ideje a válaszhoz tartozik, nem az abban szereplő régi járműméréshez.
Későbbi, friss járműadattal közölt normál állapot feloldhatja a törlést. Egy régi válasz ismétlése erre nem elég.
A törlési jelzés előtt már megtörtént és ellenőrizhető elindulás megmaradhat.

Az ajtónyitás vagy az álló mintapont nem követelmény. A busz rövid megállása két mintavétel közé eshet,
és utas hiányában megállás nélkül is továbbmehet. Ezeket megtartom, ha a többi feltétel teljesül.
A „megállásjel nélkül” jelölés nem bizonyítja, hogy a busz biztosan nem állt meg.
A csak zárt ajtót tartalmazó sorozat sem bizonyít ajtózárási időpontot.

A mozgás ellenőrzésénél 100 méteres megállókörnyezetet használok. A továbbhaladó pont legalább 40 méterre legyen
a megállótól, és legalább 30 métert mozduljon az előző ponthoz képest. Ha egyik pont sem közeli,
a köztük húzott szakasznak kell érintenie a megálló környezetét. Ez íves útvonalnál adatvesztést okozhat.
A 45 méter/másodpercnél nagyobb helyzetugrás hibajelzés. Ezek szűrési határok, nem bemért GPS-hibák.
A már egyértelműen elhaladt járműhöz nem fogadok el későbbi indulást.
A korán előrelépő megállósorszám után egy közeli állás vagy nyitott ajtó helyreállíthatja a követést.

A késés a megtartott utólagos közlés és a menetrendi indulás különbsége. Nem a GPS-minták közepét használom.
A negatív értéket korai indulásként megtartom. A nagy késést sem törlöm pusztán a nagysága miatt.
A mozgásból számolt régi becslés összehasonlításként megmarad. A mozgás ellenőrzésének két időpontja
nem mérési hibahatár, és nem használható igazolt pontossági tartományként.
A legfeljebb 60 másodperces megfigyelési közökkel külön szigorúbb összesítés is készül.

A HÉV külön eset

A HÉV-nél az ajtójel használhatósága nem igazolt, ezért nem szűrök vele.
A közölt indulást és a helyzetből becsült időt külön tartom meg. Nincs önkényes időeltolás.
A követési időt és a két állomás közölt indulása között eltelt időt lehet vizsgálni.
Utóbbi az egyik állomás indulásától a következő indulásáig tart, ezért a következő állomáson töltött időt is tartalmazza.
A közölt indulást nem párosítom a más időkezelésű helyzetből becsült érkezéssel teljes HÉV-menetidővé.
A százalék a vizsgálható közölt idők menetrendi eltérését írja le, a hivatalos pontossággal nem vethető össze.
A HÉV külön oldalon szerepel. A fő állomások napi jellemző követési ideje választható, külön irányonként.
A napok mediánját nem átlagolom. Háromnál kevesebb követhető vonatpárhoz nem jelenik meg napi érték.

Az ellenőrzés határa

A több felhasználható adat nem jelent igazolt nagyobb mérési pontosságot.
Közös órahiba vagy következetesen hibás szolgáltatói közlés így is átcsúszhat.
Ehhez külön, helyszínen rögzített ellenőrző minta kellene. Egy másik FUTÁR-adatot mutató alkalmazás nem független mérés.
A hiányzó esetek nem lesznek nulla késésű vagy kimaradt járatok.
A felhasználható arány azt mutatja, hány tervezett megállói induláshoz lehetett megtartani az adatot.
Egy jármű végighaladása több megállói adatot ad, ezek nem független utazások.

Az ajtójelet, sebességet és két további BKK-mezőt az eredeti bináris válaszokból lehet visszanyerni.
Az új betöltő külön oszlopokban tárolja őket. A hiányzó ajtójel NULL marad, nem hamis érték.
A régi adatbázis sémáját a program nem alakítja át magától. A háromnapos helyi próba a mentett mintákat
és az eredeti járműválaszok ellenőrzött kivonatát használja, adatbázis-módosítás nélkül.

Várakozás és buszválasztás

A várakozási modellben az utas egyenletesen, a menetrend ismerete nélkül érkezik a megállóba.
Az átlagot időtartammal súlyozom. A hosszú követési szünet több utast érint, ezért nagyobb súlyt kap.
A menetrendi és a becsült várakozás ugyanazon megfigyelhető időszakokra készül.
Az áthaladás is elérhető járatnak számít, azzal a feltevéssel, hogy felszálló utas esetén megállt volna.
Ismeretlen köztes indulást, eltűnést vagy pótlási jelzést nem hidalok át.
Az ismeretlen vonalhoz tartozó adatot csak a hozzá rendelt megállónál kezelem kizárásként.
A Nyugati az alapértelmezett 4–6-példa, a többi megálló ugyanebből a számításból választható.

A buszos kérdéshez néhány közös rákosmenti felszállóhelyet vizsgálok, Örs vagy Borsó utca célponttal.
Csak az adott célig közlekedő és ott leszállást engedő járatok kerülnek bele.
A teljes idő a várakozás és az ugyanazon buszon töltött menetidő összege.
Az előre rögzített választások az első megfelelő busz, illetve mindig ugyanannak a járatnak a megvárása.
Minden választást ugyanazon utasérkezési időszakokra számolok.
Mindegyik járat következő indulását és célba érkezését is ismerni kell.
Ha az indulás körüli mozgásellenőrzések időablakai átfednek, az időszakot óvatosságból kihagyom.
Ez nem ismert mérési hibahatár, hanem az egyértelmű sorrendet segítő szűrés.
Azonos közölt indulási időhöz tartozó több busz közül sem választok önkényesen.
A weben csak legalább tízpercnyi közös megfigyeléssel és választásonként legalább három busszal rendelkező megállópár jelenik meg.

Külön számolom, az utasérkezések mekkora részében ért célba korábban egy később induló busz.
Ehhez az érkezési időkereteknek is egyértelmű sorrendet kell adniuk.
Ez utólagos összevetés. Nem olyan stratégia, amelyben az utas előre ismeri a jövőbeli érkezést.
A kevés közös megfigyelésből nem adok általános vagy mai utazási tanácsot.
A H8 teljes menetidejének korábbi, kevert időforrású becslése az új exportból kimarad.

Időjárás

Az időjárást a késés órájához és a járat térségéhez kapcsolom.
Egy teljes órához négy negyedórás érték kell. A hiányzó csapadék nem nulla.
Legalább 30 vizsgálható elindulás és 50 százalékos felhasználható arány kell egy járat órájához.
A kapcsolatvizsgálathoz legalább három nap, hat órasáv és tizenkét párosított órás érték szükséges.
A nap és az óra átlagos eltérését külön levonom mindkét változóból, majd a maradékok Pearson-korrelációját számolom.
Legalább hat maradék szabadságfokot kérek. Változatlan adatból nincs korreláció.
Megmarad a csak napszakra korrigált eredmény is, és elegendő nap esetén egy-egy nap elhagyásának próbája.

Ebből nem állapítható meg oksági hatás. Az időjárás közvetlenül is lassíthat,
de utasszámon, autóforgalmon vagy utazási szokásokon keresztül is hathat.
A több utazást okozó kellemes idő lehetséges magyarázat, nem ebből a mintából igazolt tény.
A felújítás, hétvégi menetrend és adathiány szintén befolyásolhatja az eredményt.
Az egymás melletti órák és ugyanazon nap járatai összefüggenek.
A legerősebb kapcsolat több összevetés közül kiválasztott példa, nem előre kijelölt hipotézis bizonyítása.
A hiányzó esős időszakot semmilyen korrekció nem pótolja.

Az eljárás és a nyelvezet forrásai

[GTFS Realtime mezők](https://gtfs.org/documentation/realtime/reference/),
[GTFS ajánlások](https://gtfs.org/documentation/realtime/realtime-best-practices/),
[a BKK adatainak útja](https://bkk.hu/rolunk/forgalmi-adatok-diagramok/miert-gyujtjuk-a-forgalmi-adatokat/),
[FUTÁR és mobilhálózat](https://bkk.hu/hirek/2022/12/ujabb-bkk-fejlesztes-modernebb-lett-a-futar.8642/),
[HÉV-adatok integrációja](https://bkk.hu/hirek/2021/08/megujul-a-bkk-futar-utazastervezo-alkalmazas.6729/),
[Open-Meteo](https://open-meteo.com/en/docs).


## Adatbázisba töltés

A `betolto.py` a kész nyers fájlokat és naplókat olvassa, a gyűjtőtől külön fut.
A teljes nyers mentés megmarad. A menetrendi menetadatoknál a kijelölt tíz vonal, a H8 és a pótlóvonalak kerülnek táblákba.
A valós idejű adatokból az ellenőrzendő új meneteket és ismeretlen vonalakat is megtartom.
A fel nem oldott vonalú megfigyeléseket is megtartom, külön jelöléssel. A zavarok teljes köre és a kis statikus megállólista is bent van.
Az időjárás mindhárom kijelölt pontra megmarad.

A szerveres betöltés ötpercenként legfeljebb 100 új naplót vesz sorra. A korábbiakat átugorja,
így lemaradás után a következő adaggal folytatja. A gyűjtő közben önállóan ment tovább.
Az adatbázisról naponta külön mentés készül. A kész fájlt az óránkénti felhőmentés is felviszi.
A mentés visszaállítását külön próba-adatbázisban ellenőriztem. A két mentés közti időszak a nyers fájlokból újra betölthető.

Tíz tábla van, az órás adatminőség külön számított nézet.

[Az adatbázis teljes ábrája](adatbazis.svg) minden oszlopot, típust, rövid jelentést és a tényleges PK/FK-kapcsolatokat mutatja.
Az SVG nagyítható, így az apró oszlopnevek is olvashatók. A PK elsődleges kulcs, az FK idegen kulcs.
Ha egy kulcs több oszlopból áll, azokat együtt kell használni. A kapcsolatvégek Crow’s Foot jelölést használnak.
A valós idejű menet menetrendhez párosítása nem kikényszerített idegen kulcs, ezért nincs valódi FK-ként berajzolva.

| Tábla | Mit tárol | Azonosító és kapcsolat |
| --- | --- | --- |
| `nyers_fajl` | Eredeti fájl helye, ellenőrző összege, forrásideje. A menetrendi ZIP-nél verzió, érvényesség és időzóna is | A forrás + SHA256 egyedi. Saját számos azonosítója van. |
| `lekeres` | Minden lekérési kísérlet, ideje és eredménye | A napló UUID-je a kulcs. Sikeres válasz esetén a nyers fájlhoz kapcsolódik. |
| `vonal` | A teljes kis vonaljegyzék nevekkel és típusokkal | Menetrendi fájl + eredeti vonalazonosító. |
| `megallo` | Megállók neve és helye | Menetrendi fájl + eredeti megállóazonosító. |
| `menet` | Tervezett menet, irány és közlekedési napok | Menetrendi fájl + menetazonosító. A vonalhoz kapcsolódik. A `napok` dátumlista. |
| `megallasi_ido` | Megállósorrend, tervezett érkezés és indulás | Változat + menet + sorrend. Megállóra hivatkozik. Ugyanaz a megálló több helyen is szerepelhet. |
| `megfigyeles` | Egy válasz járműhelyzete vagy menetfrissítése, pótlásjelzéssel | Nyers fájl + elemsorrend. A menetrendi jelölt és a vonal feloldása külön megmarad. |
| `megallo_frissites` | A menetfrissítés megállónkénti időpontjai, késései és állapotai | Megfigyelés + a megállófrissítés elemsorrendje. |
| `zavar` | Zavarszöveg, időszakok és érintettek | Nyers fájl + elemsorrend. Az időszakok és érintettek JSON-listák. |
| `idojaras` | Modellértékek, időpont, időtartam, koordináták, egységek | Nyers fájl + térség. Az azonos időpontra érkező módosított érték is megmarad. |
| `adatminoseg` | Órás darabszámok, hibák és szünetek | Nézet a betöltött naplókból, forrásonként és UTC-óránként. |

A menetrend a heti naptárból és a napi kivételekből áll össze. A csak kivételekkel megadott napokat is kezeli.
A közlekedési napok rendezett `DATE[]` listaként kerülnek minden menethez. Egy nap ellenőrzése például
`DATE '2026-10-17' = ANY(napok)`. A napok külön sorokká is bonthatók az `unnest(napok)` kifejezéssel.
A `menetrend_id` a menetrendi ZIP `nyers_fajl.id` azonosítójára mutat, így a hosszú SHA256-értéket nem kell minden sorban ismételni.
A BKK azonosítói szövegek, a kezdő nullák megmaradnak. A menetrendi idő eredeti szövege és másodperce is bent van,
így például a `25:10:00` értelmezhető. UTC-re számításkor a szolgáltatási nap és a helyi időzóna számít.
A `frequencies.txt` alapján megadott követés betöltése még nem támogatott. Ilyen kiválasztott menetnél egyértelműen megáll.
A mostani BKK-menetrendben nincs ilyen fájl.

A betöltő ellenőrzi a nyers fájl SHA256-összegét. Ez a fájl tartalmából számolt ellenőrző érték.
Egy napló UUID-je csak egyszer kerül be.
Ha ugyanazt a naplót utólag átírnák, azt nem fogadja el észrevétlenül. Egy napló feldolgozása egy tranzakció,
így hiba esetén abból nem marad félkész adat. A korábban sikeresen betöltött naplók megmaradnak.
Ugyanazt a teljes nyers választ csak egyszer bontom táblákra, az ismételt lekérései külön sorok maradnak.
Különböző válaszokban egy változatlan jármű vagy menetfrissítés ismétlődhet. Ezek külön megfigyelések.
Ez könnyebben követhető, de a megállófrissítések több helyet foglalhatnak. A teljes betöltés előtt a növekedést mérni kell.

A napló `ismert_menetrend_sha256` mezője azt mutatja, melyik menetrend volt ismert a gyűjtéskor.
A `--menetrend` kapcsolóval megadott ZIP ennek hiányában utólagos jelölt a menetazonosító feloldásához.
Mindkét esetben jelölt kapcsolatról van szó. A helyes szolgáltatói verziót az azonosítóegyezés önmagában nem bizonyítja.
Az eredeti naplómező, a jelölt és a feloldás eredménye külön marad.
Ugyanaz a nyers válasz az első betöltéskor kap jelöltet. Ha egy későbbi lekérés már másik menetrendet ismer,
az a lekérés saját sorában megmarad, de a korábban betöltött megfigyelést nem írja át.

A megállófrissítések továbbra is előrejelzések, nem igazolt indulások.
A `NO_DATA`, `SKIPPED`, `CANCELED` állapotokat későbbi számításkor figyelembe kell venni,
akkor is, ha mellettük van kitöltött időpont. Az `ADDED` menetnek nem kötelező szerepelnie a statikus menetrendben.
A hiányzó táblamező `NULL` marad. A számszerű nulla külön érték. A zavar JSON-listái az eredeti GTFS-mezőneveket őrzik.
Ezekben a hiányzó mező kimarad, a megadott nulla megmarad. Az állapotkódok számok, a 64 bites időbélyegek szövegek.
Egy érintettségi elem feltételei együtt érvényesek, a külön elemek alternatívák.
A nem támogatott növekményes feed jelzést kap, a nyers fájl megmarad.

Az SQL-es `adatminoseg` csak a betöltött naplókat látja. Az első betöltött kérés órájától az ellenőrzés idejéig
az üres órákat és a folyó szüneteket is kiírja. Egy régi, véges minta után ezért nagy szünet látszik.
Ez önmagában nem jelenti, hogy a szerveres gyűjtő áll. A jármű- és menetszám itt is órás pillanatkép-maximum.
### Pótlóbuszok

A teljes vonaljegyzéket megtartom. A kijelölt vonalakon kívül a pótlóvonalak menetei és megfigyelései is bekerülnek.
A mostani BKK-mintában például `VP03` a 3-as, `VP46` a 4–6-os jelzésű busz.
A `vonal_id` mindig az eredeti vonal marad, nem írom át a villamoséra.
A `potolt_vonal_id` a kijelölt villamos, troli vagy HÉV névegyezésből kapott kapcsolatjelöltje.
A 4-es és 6-os jelzést a közösen vizsgált 4–6-hoz sorolom. Több lehetséges kapcsolatnál ez a mező üres.

| `potlas_jelzes` | Mit jelent |
| --- | --- |
| `potlovonal` | Busz a menetrendben VP/TP/MP/HP kezdetű BKK-azonosítóval, vagy GTFS 714-es pótlóbusztípussal. |
| `azonos_nev_jelolt` | Egy kijelölt villamossal, trolival vagy HÉV-vel azonos nevű busz. Önmagában nem bizonyított pótlás. |
| `vonaljel_jelolt` | A valós idejű válaszban pótlásra utaló BKK-azonosító, amely még nincs a menetrendben. |
| `uj_menet_jelolt` | Egyéb, nem kijelölt vonal új, hozzáadott, menetrend nélküli, másolt vagy lecserélt menete. Nem biztos, hogy pótlóbusz. |
| `ismeretlen_vonal` | Van ismert menetrend, de ez a vonal még hiányzik belőle. Megmarad ellenőrzésre. |
| üres | Nem kaptunk külön pótlásjelzést. Ez nem bizonyítja, hogy biztosan rendes közlekedés volt. |

A BKK-azonosítók előtagja a megfigyelt elnevezés, nem általános GTFS-szabály.
Az új és bizonytalan jelölteket nem számolom automatikusan a pótolt vonal indulásának vagy késésének.
Az Alerts szövege, időszaka és érintettsége segít ellenőrizni a kapcsolatot. Puszta közös zavarjelzésből nem állítok pótlást.
Ha egy ismert, szokásos másik buszvonal menete kap pótlási feladatot külön jelzés nélkül, ezt ebből a szűrésből nem lehet felismerni.
A teljes nyers válasz ilyenkor is megmarad. A kapcsolatok utólag pontosíthatók. Az új jelölés visszatöltéséhez új adatbázist használok.

Az OPH8 külön ellenőrzött eset. A megállók és a [hivatalos pótlási közlemény](https://www.mavcsoport.hu/mavinform/h8-h9-potlobuszok-fovarosi-szakaszon-oktober-17-november-6)
alapján a 2026. október 17. és november 6. közötti szolgálati napokon a H8-hoz kapcsolom az elemzésben.
Az eredeti buszazonosító és az adatbázis megmarad. OPH9-re vagy más időszakra ezt nem terjesztem ki.
A megfigyeléseket, meneteket és járműveket külön számolom.
Az éjféli időperembe belógó előző napi menet az eredeti szolgálati napján marad.
A busz menetrendje nincs meg a mentett GTFS-ben, ezért nem számolok neki vasúti menetrend szerinti késést.
A részleges buszminta nem bizonyítja a pótlóforgalom teljes lefedettségét.

Az október 17–19-i H8-minta már a pályamunkák idejére esik, módosított menetrenddel. Nincs megfelelő felújítás előtti összehasonlító időszak, ezért a munkák okozta többletkésést nem állapítom meg.
Az Örsöt érintő három ritka út október 16-ról 17-re átnyúló éjszakai menet. A mentett menetrendi időablakok 23:28–00:14, 23:48–00:34 és 00:18–01:04. Ez nem jelent egész napos közvetlen vasúti közlekedést.
A [hivatalos augusztusi riport](https://menetrendszeruseg.mavcsoport.hu/riportok/2026/08) H8/H9 mutatója 99,59 százalék. A havi teljes menetek arányát nem hasonlítom közvetlenül a háromnapos megállói indulások eltéréséhez vagy az adatfelhasználás százalékához.
A [MÁV HÉV-ről szóló havi közlése](https://www.mavcsoport.hu/mav-csoport/elso-tavaszi-honap-elenk-forgalom-es-javulo-turisztikai-menetrendszeruseg) hatperces késéshatárt említ. Ez eltér a saját, mindkét irányban legfeljebb egyperces eltérést elfogadó szabálytól.
A hatperces késéshatárt és a saját kétoldali indulási eltérést nem tekintem azonos mutatónak.
A havi riport teljes számítási eljárása nem szerepel a közölt oldalon. A közszolgáltatási szerződés 8. mellékletének végállomási és közbenső megállói tűrései más ellenőrzési szabályok, ezeket nem azonosítom a havi riport mutatójával.
A korábbi, közlésalapú eljárás október 20-i ellenőrzése a három mentett H8-mintából újra előállította az indulásokat. A gyakorisági eloszlások egyeztek a webes exporttal, ismételt eseménykulcs nem volt. 770 / 2584 adott legfeljebb egyperces eltérést, 2503 / 2584 hat percnél kisebb késést.
Ezek az átállás előtti, történeti ellenőrző számok. Az akkori web az időkeretes eredményt mutatta. Az új helyi felület már az ellenőrzött közölt időket használja. A megállást is mutató, kisebb kontrollminta egyperces aránya 357 / 1398 volt. A mozgás időablaka 375 esetben átlépte az egyperces határt, ezért a másodperces küszöbnél a becslés bizonytalansága is számít.

A betöltő szűrése rögzített. Más vonalkör vagy feldolgozási szabály esetén új adatbázisba kell újra betölteni
a megtartott nyers fájlokat. A korábbi eredményeket nem írja át magától.

Források: [BKK](https://opendata.bkk.hu/data-sources), [GTFS Realtime](https://gtfs.org/documentation/realtime/reference/), [GTFS menetrend](https://gtfs.org/documentation/schedule/reference/), [Open-Meteo leírás](https://open-meteo.com/en/docs), [ingyenes használat](https://open-meteo.com/en/terms), [keretek](https://open-meteo.com/en/pricing), [több hely számlálása](https://github.com/open-meteo/open-meteo/issues/1295). Az időjárási adatok forrása az Open-Meteo, CC BY 4.0.
