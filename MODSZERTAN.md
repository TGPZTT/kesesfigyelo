# Módszertan

## Mit akarok megtudni?

A kérdés az, hogy melyik vonalon, mikor és hol romlik a közlekedés, és ez mennyi plusz várakozást jelent.
A menetrendi késés önmagában nem elég: egy öt percet késő, de szabályosan érkező villamossor más helyzet,
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
| Becslés | A szolgáltató által közölt várható idő. Később változhat; a nulla bizonytalanság sem önálló bizonyíték az indulásra. |
| Szolgálati nap | A menet menetrendi napja. A szombati `25:10:00` vasárnap hajnali 01:10-et jelent. |
| Késés | A megállapított indulás és a menetrendi indulás különbsége. A negatív érték korai indulás. |
| Követési idő | Két egymást követő indulás közti idő ugyanabban a megállóban, irányban és összehasonlítható járatcsoportban. |
| Plusz várakozás | A számított tényleges és menetrendi várakozás különbsége. Ez utasmodellből kapott érték, nem mért utasadat. |
| Lefedettség | Mennyi tervezett indulásról, illetve mekkora időszakról van használható adat. |
| Medián és 90. percentilis | A mediánnál az értékek fele kisebb vagy egyenlő. A 90. percentilisnél ez az arány 90%. |

A korai érkezés és a korai indulás külön dolog. A jármű megérkezhet korábban, majd kivárhatja az indulását.
Az utas számára az a probléma, ha már a meghirdetett indulás előtt elmegy. A negatív késést ezért nem írom át nullára.

## Gyűjtés

A gyűjtő és az adatbázis a szerveren fut. A betöltő külön dolgozik, az elemző csak a mentett adatokat olvassa.
Az eredeti válaszokat megtartom, hogy később vissza lehessen nézni, miből számoltam.

Október 18-án 19:17–19:30 között a VPS leállása miatt kimaradt a gyűjtés. A járműhelyzeteknél és menetfrissítéseknél
13 perc telt el két sikeres kérés között. Indulás után a gyűjtés magától folytatódott, a korábbi fájlok megmaradtak.
A hiányzó időszakot nem pótolom becsléssel; az adatminőségi kimutatásban és az érintett elemzéseknél látszania kell.

A VehiclePositions és a TripUpdates tervezett lekérése 30, az Alertsé 60 másodpercenként történik. A félperces minta a megállók közti mozgás követéséhez kell; a ritkábban változó zavarjelzésekhez egy percet választottam. A menetrendet naponta ellenőrzöm, a ZIP változatait megtartom. Ezek saját beállítások, nem a BKK által megadott kvóták. Két kérés kezdete között legalább 10 másodperc van, lassulás után nincs gyors pótlás. A letöltések egymás után futnak, ezért egy lassú válasz késleltetheti a következőt; ez a naplóban látszik.

A válaszok tömörítve kerülnek a data/nyers mappába. Ugyanazt a tartalmat csak egyszer tárolom, de minden lekérési kísérlet külön bejegyzést kap a data/naplo alatt. A fájl csak kész állapotban kerül a helyére. A program nem töröl régi adatot, és mentés előtt legalább 2 GiB szabad helyet hagy.

Hálózati hibánál vár, ismétlődő BKK-hibánál egyre többet. A szerver által kért várakozást újraindítás után is betartja. Elutasított BKK-hozzáférésnél vagy mentési hibánál leáll. Az időjárási hiba csak az időjárási kérést halasztja, legalább 15 perccel; egy BKK-korlátozás sem tiltja az időjárási kérést. A kulcs helyi fájlban van, a naplóba nem kerül bele.

A legfontosabb buktató, hogy a TripUpdates időpontja lehet előrejelzés. Attól, hogy az időpont már elmúlt, még nem biztos, hogy akkor indult el a jármű. A hiányzó adatot nem veszem nulla késésnek. A NO_DATA, a SKIPPED és a CANCELED külön állapot. Az ADDED menet jogosan hiányozhat a statikus menetrendből. Az eltűnő menet önmagában nem bizonyít törlést. Sok egymás utáni járműpozíció sem jelent sok külön indulást.

Külön mentem a lekérés és a forrásadat időpontját, UTC szerint. Feldolgozáskor figyelni kell a szolgáltatási napra, a megállósorrendre, a 24 órán túli menetrendi időkre és az óraátállításra. Az elemzés előtt a menetrendváltozatokat is össze kell vetni.

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

A H8 menetrendje október 17-én főleg Cinkota–Gödöllő meneteket tartalmaz. A megváltozott útvonalat nem szabad menetrendi kimaradásnak nézni. A gyűjtő a teljes feedeket menti, a vonalszűrés az adatbázisba töltéskor történik. Az indulások meghatározása külön feldolgozási lépés, nem a betöltő feladata.

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

A három tervezett elemzés a napszakok és napok közti eltérés, a vonal mentén felhalmozódó késés és a sűrű járatok követési ideje.
A saját kérdés: ha a közölt időpont szerint korábban érkezett a jármű, kivárta-e a menetrendi indulását?
Ehhez a stabil érkezési közlést és a továbbhaladással ellenőrzött indulást együtt nézem.
A saját bővítés a 97E, 161 és 169E együttes utasvárakozása, közös megállóból és irányban, az Örs vezér tere felé.
A 46-os ebben a csoportban nem szerepel; a tíz alapvonal elemzésében továbbra is benne van.
A közös megállót és célt is ellenőrizni kell: csak az utas számára ténylegesen helyettesítő menetek kerülhetnek egy csoportba.
Minden eredmény mellé megfigyelésszám és adatlefedettség kell.

## Indulás, késés és várakozás

Az elemző csak mentett adatból dolgozik, az adatbázisba nem ír. Az indulások keresése és a követési számítás
külön kipróbálható. A weboldal az előre kiszámolt eredményeket olvassa.

Egy esemény kulcsa a menet, a szolgálati nap és a megállósorszám. A végső megállót és a felszállást nem engedő megállásokat kihagyom.
Azonos saját időpontú közlés többszöri letöltése egy bizonyíték. A letöltés ideje helyett a jármű vagy a menetfrissítés saját idejét nézem.
Az elemzéshez külön megadott menetrendváltozat tartozik; az azonosítóegyezés önmagában nem bizonyítja, hogy jól választottam változatot.
Az adott naphoz és vonalakhoz tartozó menetrendnek egyeznie kell a megfigyelésekben hivatkozott változatok között.
Ha a releváns menetrendi adatok eltérnek, az automatikus elemzés leáll; a változat kiválasztásáról külön kell dönteni.
Ez nem állítja le a gyűjtést.

Saját idő nélküli státuszközlésnél a válasz fejlécidejét használom a sorrendhez. Így egy törlés vagy NO_DATA jelzés nem vész el,
de ez nem helyettesíti az indulás igazolásához szükséges saját időpontot.

A legutóbbi megfelelő, múltbeli indulást keresem. Legalább két külön saját időpontú közlésben ugyanannak kell maradnia,
nulla közölt bizonytalansággal, azonos járművel és megállóval. A korábban változó becslés ettől még használhatóvá válhat.
A jármű indulás körüli továbbhaladását is ellenőrzöm. A nulla bizonytalanságot a szolgáltató adja: nem saját mérési pontosság.

| `minoseg` | Mit tudunk az eseményről? |
| --- | --- |
| `alatamasztott` | Stabil közölt indulás, amelyet a megállóban állás és a továbbhaladás közti, legfeljebb 120 másodperces ablak is alátámaszt. |
| `kovetett` | Stabil közölt indulás és közeli továbbhaladás látszik, de nincs megfelelő megállóban állási időpont az ablakhoz. |
| `bizonytalan` | Van adat, de az időpontot, a mozgást vagy a hozzárendelést nem sikerült kellően ellenőrizni. |
| `nem_lattuk` | A menetrendi menethez nincs megfelelő megfigyelés. Ez nem bizonyított kimaradás. |
| `torolt` | A forrás töröltnek jelölte a menetet. Ez nem bizonyítja, hogy a teljes menet kimaradt. |
| `kihagyott` | A forrás az adott megállás kihagyását jelzi. |

A mozgásvizsgálat az indulás előtti és utáni két percre korlátozódik. Ha van koordináta, az álló pont legfeljebb 100 méterre lehet a megállótól,
a továbbhaladó pontnak pedig legalább 40 méterre kell lennie. Ha a pont az előző megálló felé halad vissza, nem fogadom el.
A végállomási kifordulást ez az irányellenőrzés nem minősíti téves haladásnak.
Az időablak felső széle a vizsgált megállólátogatás után látott első továbbhaladás.
Nem választhatok helyette egy későbbi pontot csak azért, hogy a közölt indulási idő beleférjen az ablakba.
Ha a jármű már továbbhaladt, majd a sorszáma visszaugrik, miközben a megállótól több mint 100 méterre van,
ezt nem tekintem új megállólátogatásnak.
Ezek egyszerű, saját ellenőrzési határok, nem a BKK által garantált pontosságok. Megállósorszám-váltás önmagában nem elég, mert álló járműnél is előfordul.

Ha egy korábbi, nulla bizonytalanságú indulást később becslés vált fel, a korábbi idő csak megállási ablakkal megerősítve maradhat meg.
A későbbi NO_DATA vagy nem szokásos állapot nem tűnik el attól, hogy előtte volt egy kedvező közlés.
Egy későbbi menet-törlés nem teszi meg nem történtté a korábbi indulást. Csak akkor tartom meg,
ha a stabil közlések és a teljes megállási-továbbhaladási ablak is az első megfigyelt törlési jelzés előtt vannak.
A későbbi törlés jelzése ilyenkor is megmarad. A pusztán követett, teljes ablakkal nem igazolt eset ehhez nem elég.
Ha ugyanaz a jármű két külön menet alatt, ugyanott két percen belül indulásként szerepel, az események külön ellenőrzést igényelnek.
A megállósorrenddel ellentétes indulási idősort sem fogadom el.

A `menetrend_ok` külön jelzi, hogy az időpontot szabad-e menetrendi késésként használni.
Az öt percnél nagyobb koraiság és az egy óránál nagyobb késés felülvizsgálati jelzés; nem javítom meg önkényes időeltolással.
Egy fizikailag követhető indulás ilyenkor még hasznos lehet a követéshez, miközben a menetrendi párosítása nem biztos.
A néhány másodperces negatív késés sem jelent bizonyított szabályszegést: a forrás és a mintavétel bizonytalanságát is figyelembe kell venni.

A késés az indulás és a menetrendi indulás különbsége, másodpercben. A korai érkezést külön számolom,
ha az érkezési idő is stabilan szerepel a közlésben. Külön látszik, ha a korán érkező jármű kivárta a menetrendi indulását.
A szakaszon keletkező késést ugyanannak a menetnek két egymást követő, használható megállásából kell számolni;
két különböző összetételű megállói átlag különbsége ehhez nem elég.

A követést ugyanazon megállóhelyen és irányban, a tényleges indulásokat időrendbe rendezve számolom.
A várakozásnál azt feltételezem, hogy az utas egyenletesen érkezik a vizsgált időszakban, és felszállhat a következő vizsgált járatra.
Teljes követési közöknél az átlagos várakozás: `sum(követés²) / (2 × sum(követés))`.
Az óra szélén átlógó közöket csak a vizsgált időablakban számolom; a tényleges és a menetrendi várakozás ugyanarra az időszakra vonatkozik.
A plusz várakozás a két érték különbsége, és negatív is lehet.

Nem zárok ki egy egész órát csak azért, mert egy része bizonytalan. A fő követési számítás két egymás melletti,
ellenőrzött indulás közét használja. A tényleges sorrend számít: két jármű felcserélt sorrendje önmagában nem adatvesztés.
A menetrendi sorban nem lehet közöttük bizonytalan indulás, és másik menet lehetséges időszaka sem metszheti a közöt.
Egy bizonytalan menet jelölt idejét és megállóban látott időpontjait együtt nézem: a köztük lévő tartomány is bizonytalan,
nem csak a felsorolt pontok. A megfigyelt ADDED és pótló menetek érintett időszakát is kihagyom.
Ez óvatos szűrés; egy teljesen meg nem figyelt plusz indulást ebből nem lehet kizárni.

A megtartott szakaszokon ugyanazt az abszolút időtartamot használom a megfigyelt és a menetrendi várakozáshoz.
A menetrendi oldalon a teljes vonatkozó indulássor szerepel. A napi értékeket a lefedett idővel súlyozom;
nem átlagolok össze egyformán egy ötperces és egy egyórás részletet. Órahatárnál csak az adott órára eső részt számolom.
A darabszám és a lefedett idő minden eredmény mellett látható. Egy órahatáron átérő pár mindkét órában szerepelhet,
ezért az órás párszámok összege nem feltétlenül a napi párok száma.

A korábbi teljes órás számítás külön, szigorúbb ellenőrzésként megmarad. Ott az óra előtt és után is 15 perces
ellenőrzési szegély van; az ADDED vagy pótló menet időszaka is ennyivel bővül. A két módszer lefedettsége ezért eltér.
Egyikből sem helyettesítem az ismeretlen indulást menetrendi idővel vagy kitalált középértékkel.
A hiányzó szakaszhoz nincs várakozási érték, nem nulla tartozik. A megtartott részidőszak eredménye nem automatikusan teljes napi átlag.
A kiírt érték a véletlenszerűen érkező utas modellje; ritka járatnál, menetrendhez igazodó utasokra nem feltétlenül igaz.

Nem minden mutatóhoz ugyanazokat az adatokat használom:

| Adat | Mire használható? |
| --- | --- |
| Bizonytalan vagy nem látott indulás | Adatminőségre, jelenlét és hiány bemutatására; pontos késésnek nem veszem. |
| Alátámasztott indulás, bizonytalan menetrendi párosítással | Követéshez még használható, menetrendi késéshez nem. |
| Használható indulás és megfelelő menetrendi pár | Késéshez, koraisághoz, ugyanazon menet szakaszai közti változáshoz. |
| Két szomszédos indulás közti ellenőrzött időszak | Követéshez és azonos időszakú menetrendi várakozással való összevetéshez. |

A járműpozíciók közti időablak nem másodpercre pontos mérés, és nem statisztikai konfidenciaintervallum.
A stabil TripUpdates-idő is a szolgáltató közlése. A két forrás egyezése erősíti az értelmezést,
de nem független helyszíni mérés. A grafikonok ezért kerekített értékeket mutatnak.

A közös buszos várakozást csak olyan órában hasonlítom a három külön vonalhoz, amely mind a négy számításban használható.
A közös cél az Örs vezér tere, a megálló a Bakancsos utca F03541 peronja.
Csak az a menet számít, amelynek későbbi megállói között az Örs 008029 megállója leszállási lehetőséggel szerepel.
Ez a felszállásig tartó várakozásról szól;
a rövidebb várakozás nem feltétlenül jelent korábbi célba érést, mert a buszok menetideje eltérhet.

Az eredmények mellett szerepelnie kell a használt indulások és menetek számának, a vizsgált napoknak és a lefedettségnek.
A több ezer megállói indulás nem több ezer független utazás: egy menet sok megállójával is szerepelhet.
Egy szombati nap alapján csak arról a napról állítok valamit. A napok közti összevetéshez több teljes nap kell;
az időjárás és a zavarjelzések együttjárása pedig önmagában nem bizonyít ok-okozatot.

## Adatbázisba töltés

A `betolto.py` a kész nyers fájlokat és naplókat olvassa, a gyűjtőtől külön fut.
A teljes nyers mentés megmarad. A menetrendi menetadatoknál a kijelölt tíz vonal, a H8 és a pótlóvonalak kerülnek táblákba.
A valós idejű adatokból az ellenőrzendő új meneteket és ismeretlen vonalakat is megtartom.
A fel nem oldott vonalú megfigyeléseket is megtartom, külön jelöléssel. A zavarok teljes köre és a kis statikus megállólista is bent van.
Az időjárás mindhárom kijelölt pontra megmarad.

A szerveres betöltés ötpercenként legfeljebb 100 új naplót vesz sorra. A korábbiakat átugorja,
így lemaradás után a következő adaggal folytatja. A gyűjtő közben önállóan ment tovább.
Az adatbázisról naponta külön mentés készül; a kész fájlt az óránkénti felhőmentés is felviszi.
A mentés visszaállítását külön próba-adatbázisban ellenőriztem. A két mentés közti időszak a nyers fájlokból újra betölthető.

Tíz tábla van, az órás adatminőség külön számított nézet.

[Az adatbázis teljes ábrája](adatbazis.svg) minden oszlopot, típust, rövid jelentést és a tényleges PK/FK-kapcsolatokat mutatja.
Az SVG nagyítható, így az apró oszlopnevek is olvashatók. A PK elsődleges kulcs, az FK idegen kulcs;
ha egy kulcs több oszlopból áll, azokat együtt kell használni. A kapcsolatvégek Crow’s Foot jelölést használnak.
A valós idejű menet menetrendhez párosítása nem kikényszerített idegen kulcs, ezért nincs valódi FK-ként berajzolva.

| Tábla | Mit tárol | Azonosító és kapcsolat |
| --- | --- | --- |
| `nyers_fajl` | Eredeti fájl helye, ellenőrző összege, forrásideje; a menetrendi ZIP-nél verzió, érvényesség és időzóna is | A forrás + SHA256 egyedi. Saját számos azonosítója van. |
| `lekeres` | Minden lekérési kísérlet, ideje és eredménye | A napló UUID-je a kulcs; sikeres válasz esetén a nyers fájlhoz kapcsolódik. |
| `vonal` | A teljes kis vonaljegyzék nevekkel és típusokkal | Menetrendi fájl + eredeti vonalazonosító. |
| `megallo` | Megállók neve és helye | Menetrendi fájl + eredeti megállóazonosító. |
| `menet` | Tervezett menet, irány és közlekedési napok | Menetrendi fájl + menetazonosító; a vonalhoz kapcsolódik. A `napok` dátumlista. |
| `megallasi_ido` | Megállósorrend, tervezett érkezés és indulás | Változat + menet + sorrend; megállóra hivatkozik. Ugyanaz a megálló több helyen is szerepelhet. |
| `megfigyeles` | Egy válasz járműhelyzete vagy menetfrissítése, pótlásjelzéssel | Nyers fájl + elemsorrend; a menetrendi jelölt és a vonal feloldása külön megmarad. |
| `megallo_frissites` | A menetfrissítés megállónkénti időpontjai, késései és állapotai | Megfigyelés + a megállófrissítés elemsorrendje. |
| `zavar` | Zavarszöveg, időszakok és érintettek | Nyers fájl + elemsorrend; az időszakok és érintettek JSON-listák. |
| `idojaras` | Modellértékek, időpont, időtartam, koordináták, egységek | Nyers fájl + térség. Az azonos időpontra érkező módosított érték is megmarad. |
| `adatminoseg` | Órás darabszámok, hibák és szünetek | Nézet a betöltött naplókból, forrásonként és UTC-óránként. |

A menetrend a heti naptárból és a napi kivételekből áll össze; a csak kivételekkel megadott napokat is kezeli.
A közlekedési napok rendezett `DATE[]` listaként kerülnek minden menethez. Egy nap ellenőrzése például
`DATE '2026-10-17' = ANY(napok)`; a napok külön sorokká is bonthatók az `unnest(napok)` kifejezéssel.
A `menetrend_id` a menetrendi ZIP `nyers_fajl.id` azonosítójára mutat, így a hosszú SHA256-értéket nem kell minden sorban ismételni.
A BKK azonosítói szövegek, a kezdő nullák megmaradnak. A menetrendi idő eredeti szövege és másodperce is bent van,
így például a `25:10:00` értelmezhető. UTC-re számításkor a szolgáltatási nap és a helyi időzóna számít.
A `frequencies.txt` alapján megadott követés betöltése még nem támogatott: ilyen kiválasztott menetnél egyértelműen megáll.
A mostani BKK-menetrendben nincs ilyen fájl.

A betöltő ellenőrzi a nyers fájl SHA256-összegét. Ez a fájl tartalmából számolt ellenőrző érték.
Egy napló UUID-je csak egyszer kerül be;
ha ugyanazt a naplót utólag átírnák, azt nem fogadja el észrevétlenül. Egy napló feldolgozása egy tranzakció,
így hiba esetén abból nem marad félkész adat. A korábban sikeresen betöltött naplók megmaradnak.
Ugyanazt a teljes nyers választ csak egyszer bontom táblákra, az ismételt lekérései külön sorok maradnak.
Különböző válaszokban egy változatlan jármű vagy menetfrissítés ismétlődhet: ezek külön megfigyelések.
Ez könnyebben követhető, de a megállófrissítések több helyet foglalhatnak. A teljes betöltés előtt a növekedést mérni kell.

A napló `ismert_menetrend_sha256` mezője azt mutatja, melyik menetrend volt ismert a gyűjtéskor.
A `--menetrend` kapcsolóval megadott ZIP ennek hiányában utólagos jelölt a menetazonosító feloldásához.
Mindkét esetben jelölt kapcsolatról van szó; a helyes szolgáltatói verziót az azonosítóegyezés önmagában nem bizonyítja.
Az eredeti naplómező, a jelölt és a feloldás eredménye külön marad.
Ugyanaz a nyers válasz az első betöltéskor kap jelöltet. Ha egy későbbi lekérés már másik menetrendet ismer,
az a lekérés saját sorában megmarad, de a korábban betöltött megfigyelést nem írja át.

A megállófrissítések továbbra is előrejelzések, nem igazolt indulások.
A `NO_DATA`, `SKIPPED`, `CANCELED` állapotokat későbbi számításkor figyelembe kell venni,
akkor is, ha mellettük van kitöltött időpont. Az `ADDED` menetnek nem kötelező szerepelnie a statikus menetrendben.
A hiányzó táblamező `NULL` marad; a számszerű nulla külön érték. A zavar JSON-listái az eredeti GTFS-mezőneveket őrzik.
Ezekben a hiányzó mező kimarad, a megadott nulla megmarad; az állapotkódok számok, a 64 bites időbélyegek szövegek.
Egy érintettségi elem feltételei együtt érvényesek, a külön elemek alternatívák.
A nem támogatott növekményes feed jelzést kap, a nyers fájl megmarad.

Az SQL-es `adatminoseg` csak a betöltött naplókat látja. Az első betöltött kérés órájától az ellenőrzés idejéig
az üres órákat és a folyó szüneteket is kiírja. Egy régi, véges minta után ezért nagy szünet látszik;
ez önmagában nem jelenti, hogy a szerveres gyűjtő áll. A jármű- és menetszám itt is órás pillanatkép-maximum.
### Pótlóbuszok

A teljes vonaljegyzéket megtartom. A kijelölt vonalakon kívül a pótlóvonalak menetei és megfigyelései is bekerülnek.
A mostani BKK-mintában például `VP03` a 3-as, `VP46` a 4–6-os jelzésű busz.
A `vonal_id` mindig az eredeti vonal marad, nem írom át a villamoséra.
A `potolt_vonal_id` a kijelölt villamos, troli vagy HÉV névegyezésből kapott kapcsolatjelöltje.
A 4-es és 6-os jelzést a közösen vizsgált 4–6-hoz sorolom. Több lehetséges kapcsolatnál ez a mező üres.

| `potlas_jelzes` | Mit jelent |
| --- | --- |
| `potlovonal` | Busz a menetrendben VP/TP/MP/HP kezdetű BKK-azonosítóval, vagy GTFS 714-es pótlóbusztípussal. |
| `azonos_nev_jelolt` | Egy kijelölt villamossal, trolival vagy HÉV-vel azonos nevű busz; önmagában nem bizonyított pótlás. |
| `vonaljel_jelolt` | A valós idejű válaszban pótlásra utaló BKK-azonosító, amely még nincs a menetrendben. |
| `uj_menet_jelolt` | Egyéb, nem kijelölt vonal új, hozzáadott, menetrend nélküli, másolt vagy lecserélt menete; nem biztos, hogy pótlóbusz. |
| `ismeretlen_vonal` | Van ismert menetrend, de ez a vonal még hiányzik belőle; megmarad ellenőrzésre. |
| üres | Nem kaptunk külön pótlásjelzést. Ez nem bizonyítja, hogy biztosan rendes közlekedés volt. |

A BKK-azonosítók előtagja a megfigyelt elnevezés, nem általános GTFS-szabály.
Az új és bizonytalan jelölteket nem számolom automatikusan a pótolt vonal indulásának vagy késésének.
Az Alerts szövege, időszaka és érintettsége segít ellenőrizni a kapcsolatot; puszta közös zavarjelzésből nem állítok pótlást.
Ha egy ismert, szokásos másik buszvonal menete kap pótlási feladatot külön jelzés nélkül, ezt ebből a szűrésből nem lehet felismerni.
A teljes nyers válasz ilyenkor is megmarad. A kapcsolatok utólag pontosíthatók; az új jelölés visszatöltéséhez új adatbázist használok.

A betöltő szűrése rögzített. Más vonalkör vagy feldolgozási szabály esetén új adatbázisba kell újra betölteni
a megtartott nyers fájlokat; a korábbi eredményeket nem írja át magától.

Források: [BKK](https://opendata.bkk.hu/data-sources), [GTFS Realtime](https://gtfs.org/documentation/realtime/reference/), [GTFS menetrend](https://gtfs.org/documentation/schedule/reference/), [Open-Meteo leírás](https://open-meteo.com/en/docs), [ingyenes használat](https://open-meteo.com/en/terms), [keretek](https://open-meteo.com/en/pricing), [több hely számlálása](https://github.com/open-meteo/open-meteo/issues/1295). Időjárási adatok: Open-Meteo, CC BY 4.0.
