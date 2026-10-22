# Módszertan

A vizsgálat a menetrendi eltérést, a járatok közti szüneteket és az ezekből számított várakozást hasonlítja össze.

## Adatok és kiválasztás

| Forrás | Mire használom? |
| --- | --- |
| BKK GTFS ZIP | Az adott nap menetrendje, megállói, útvonalai és közlekedési napjai. |
| VehiclePositions | A jármű helyzete, megállósorszáma, saját időbélyege és elérhető üzemi jelzései. |
| TripUpdates | Egy konkrét közlekedés megállónkénti érkezési és indulási közlései, állapotai. Ezek előrejelzések is lehetnek. |
| Alerts | Forgalmi tájékoztatás. Nem ebből állapítom meg az indulást. |
| Open-Meteo | Hőmérséklet, szél és csapadék három térségben. Modelladat, nem megállóban végzett mérés. |

A tíz alapjárat buszból a 46, 97E, 161, 169E, villamosból az 1, 2, 3, 4–6, troliból a 80 és 82.
A keleti városrész buszai a közös cél felé utazás összevetéséhez kellenek, a többi járat eltérő közlekedési helyzeteket ad.
A 4–6 egy csoportként szerepel. A 2026. október 16-i menetrendben Újbuda-központból 07.01, 07.03, 07.05 és 07.07 szerepelt,
így teljesül az öt percnél sűrűbb követés feltétele. A H8 külön kiegészítésként szerepel.

Egy járműút során a jármű egy adott napra tervezett útvonalat egyszer végigjár. Ugyanaz a busz több ilyet teljesíthet.
A továbbhaladás a jármű indulását vagy megállás nélküli elhaladását jelenti egy adott megállónál.
A megállósorszám is része az azonosításnak, mert az útvonal visszatérhet ugyanahhoz a megállóhoz.

A gyűjtő a teljes válaszokat menti, az adatbázis a kijelölt járatokat, a pótlásjelölteket és a nem feloldott megfigyeléseket tartja meg.
A nyers fájlok tömörítve, SHA256 tartalmi ellenőrző összeggel maradnak meg. A program minden lekérési kísérletet külön naplósorba ír.
Ugyanaz a napló és ugyanaz a teljes válasz nem kerül kétszer feldolgozásra. Egy napló betöltése vagy teljesen sikerül, vagy visszagördül.
A kapcsolatok az [adatbázisábrán](adatbazis.svg), a pontos mezők az [SQL-sémában](adatbazis.sql) láthatók.

A félperces helyzet- és induláslekérés a megállók közti mozgáshoz kell, a ritkábban változó zavarokhoz egy perc elég.
Két kérés kezdete között legalább tíz másodperc van. Ezek saját beállítások, nem a BKK által megadott kvóták.

A hálózati és válaszhibák várakozást és naplóbejegyzést okoznak. Hibás hozzáférésnél vagy mentési hibánál a gyűjtő leáll,
hogy ne írjon észrevétlenül hibás adatot. Az újraindítás nem indít pótló kérésrohamot.

## Hogyan lesz a közlésekből továbbhaladási idő?

A FUTÁR a fedélzeti adatokat a BKK központján keresztül adja tovább. A HÉV-adatok MÁV-integráción át érkeznek.
A válasz elkészítésének ideje, a járműadat saját ideje és a letöltés ideje külön adat.
Egy válasz ismételt letöltése nem új járműmérés. A helyzet és az előrejelzés közös rendszerből származhat,
ezért egyezésük nem független bizonyíték.

A program egy járműút egy megállójához tartozó teljes mentett közléssort vizsgál. A következőket ellenőrzi.

1. A jármű, a járműút, a szolgálati nap, a megálló és a megállósorrend összetartozik-e?
2. A két legutóbbi, külön saját időbélyegű közlés ugyanazt a már elmúlt indulást adja-e, nulla közölt bizonytalansággal?
3. A jármű helyzetei követhető továbbhaladást mutatnak-e a megálló mellett, legfeljebb 120 másodperces közben?
4. Ellentmond-e ennek nyitott ajtó, lehetetlen helyzetugrás, megállósorrend vagy másik végighaladással kevert közlés?

A mozgásellenőrzés 100 méteres megállókörnyezetet használ. A továbbhaladó pont legalább 40 méterre legyen a megállótól,
és legalább 30 méterre az előző ponttól. Ha egyik pont sem közeli, az összekötő szakasz érintse a megállókörnyezetet.
A 45 m/s feletti helyzetugrás hibajelzés. A közölt indulás után több mint öt másodperccel jelzett nyitott BKK-ajtó ellentmondás.
Ezek választott ellenőrzési határok, nem igazolt mérési hibák. A részletes feltételek az `elemzes.py` fájlban vannak.

Ajtónyitás vagy megállás nem kötelező. Utas nélkül a busz megállás nélkül is továbbhaladhat,
és a rövid megállás két mintavétel közé eshet. Az ilyen eset megmarad, ha a többi ellenőrzés teljesül.
A kimaradó eset nyers adatai is mentve maradnak, csak az indulási számításból maradnak ki.

A kihagyott megálló (`SKIPPED`), az adathiány (`NO_DATA`) és a törölt közlekedés (`CANCELED`) külön állapot.
Egy későbbi törlési jelzés nem törli a korábban már ellenőrizhető továbbhaladást.
Friss normál állapot feloldhatja a törlési jelzést, egy régi válasz ismétlése nem.
Ha egy azonosítóhoz több, egymással kevert végighaladás tartozik, nem választom ki utólag a menetrendhez legközelebbit.

## Mihez képest számít a késés?

**Késés = az elfogadott közölt indulás − az adott napra érvényes, letöltött GTFS-menetrend indulása.**
Ha a menetrend 06.00, a közölt indulás 06.10, akkor a késés tíz perc.
A negatív eltérés korábbi indulást jelent, megmarad az eredményben.
A BKK által külön közölt más tervezett időpont ellenőrző adat. Nem írja át a fő késést.

A szolgálati nap a menetrendi közlekedés napja. A szombati `25:10:00` vasárnap 01.10-et jelent.
Az időpontokat UTC-ben tárolom, a naptárt és az óraátállítást budapesti idő szerint kezelem.
A menetrendváltozatokat az elemzés előtt összevetem. A járat azonosítója önmagában nem bizonyít helyes menetrendi hozzárendelést.
A letöltött GTFS minden kifüggesztett változattal való egyezését nem ellenőriztem helyszínen.

A nagy eltérés önmagában nem kizárási ok. Félórás eltérést külön ellenőrzési jelzés mutat.
A mozgás időablaka nem az indulási idő igazolt hibahatára. Közös szolgáltatói órahiba vagy téves menetrendi párosítás így is átjuthat.
Ennek kizárásához független helyszíni mérés kellene.

## Mit mutatnak az eredmények?

| Mutató | Számítás és jelentés |
| --- | --- |
| Pontos indulások aránya | A legfeljebb egy vagy két perccel korábbi vagy későbbi közölt indulások aránya a vizsgálható indulásokból. |
| Felhasználható arány | Vizsgálható megállói továbbhaladások száma osztva a menetrend szerint tervezettekkel. Ez adatmennyiség, nem pontosság. |
| Medián eltérés | A sorba rendezett eltérések középső értéke. A napok mediánjait nem átlagolom. |
| Legnagyobb késés | Egyetlen elfogadott közlés szélső értéke, a helyével és időpontjával. Nem az egész közlekedés bizonyított maximuma. |
| Szakasz változása | Ugyanazon járműút két egymást követő megállójának késéskülönbsége, majd ezek mediánja. Nem állásidő. |
| Követési idő | Egymást követő járművek indulása között eltelt idő, azonos megállóban és irányban. |
| Adatban nem szereplő közlekedés | A menetrendi járműúthoz nem érkezett járműhelyzet vagy menetfrissítés. Ez nem bizonyított járatkimaradás. |

A darabszámok megállónkénti események. Egy hosszabb út több eseményt ad, ezért a rangsor nem utasszámmal súlyozott.
A közös napok eredménye az eseményekből készül, nem a napi százalékok átlagából.
A felület a darabszámot és az adatlefedettséget is mutatja. Az órás BKK-értékhez legalább 30 esemény és 50% lefedettség kell.
A legfeljebb 60 másodperces mozgásközökből szigorúbb ellenőrző eredmény is készül.

A sikeres letöltés nem bizonyít friss forrástartalmat. Az órás jármű- és közlésszám egy válaszban látott legnagyobb darabszám,
nem az órában közlekedő egyedi járművek száma. A régi Alerts-fejléc önmagában nem a gyűjtő leállása.

## Várakozás és buszválasztás

A modellben az utas a vizsgálható időszak bármely pillanatában azonos eséllyel érkezik a megállóba, a menetrendtől függetlenül.
Két indulás közti teljes időszak átlagos várakozása a követési idő fele. A hosszabb szünet nagyobb súlyt kap.
A közölt és menetrendi várakozást ugyanarra a követhető időszakra számolom. A kettő különbsége a többletvárakozás.
Ismeretlen köztes indulást nem hidalok át. Az áthaladó buszról feltételezem, hogy felszálló utasnak megállt volna.

A saját kérdés az első megfelelő buszra felszállást hasonlítja egy kiválasztott járat megvárásához, közös felszállóhely és cél között.
A teljes idő várakozásból és ugyanazon busz menetidejéből áll. Csak azok az időszakok számítanak,
amikor minden választás következő indulása és célba érkezése megállapítható.
Az időbeli sorrendjükben nem elkülöníthető buszokat nem választom szét önkényesen.
A weben legalább tízpercnyi közös idő és választásonként három busz kell.
Az eredmény csak erre a követhető időre érvényes, nem általános napi utazási tanács.

## HÉV

A H8 külön számítás és külön oldal. A közölt indulást ugyanúgy a letöltött menetrendhez mérem,
de a később nyitottnak jelzett ajtó itt nem kizárási feltétel, mert e mező használhatósága nem igazolt.
A közös mozgásellenőrzés néhány feltétele még olvassa az ajtójelet, ezért az eljárás nem teljesen független tőle.
A helyzetből becsült idő és a közölt idő külön marad. Nem tolok el időpontot feltételezésből,
és különböző időforrású indulást és érkezést nem kapcsolok teljes menetidővé.

A HÉV százaléka közölt idők menetrendi eltérése, nem a hivatalos szolgáltatói pontossági mutató.
Az órás értékhez legalább tíz esemény, két vonat és 50% lefedettség, a napi követéshez három vonatpár kell.
A 2026. október 17-től érvényes rövidített menetrendet használom. A felújítás előtti összehasonlító időszak hiányzik.
A pótlóbusz menetrendi párosítása nem megfelelően igazolt, ezért nem kap saját teljesítményelemzést.

## Időjárás

A belváros, Rákosmente és a H8 külső térségének modelladatait a járatok órás késéséhez kapcsolom.
Egy időjárási jellemző órájához mind a négy negyedóra kell, a hiányt nem átlagolom ki.
A csapadékot az óra végén lezáruló négy időszakból összeadom, az azonos időpontra ismételten kapott értéket nem duplázom.

A számítás legalább három napot, hat különböző órasávot, tizenkét párosított órát és hat maradék szabadságfokot kér.
A járat órájához legalább 30 esemény és 50% lefedettség szükséges.
A nap és az órasáv különbségeit közös lineáris illesztéssel becsülöm mindkét változónál,
majd a megmaradó eltérések Pearson-korrelációját (`r`) számolom. A korrekció nélküli eredmény is összevethető.
A pozitív előjel azonos, a negatív ellentétes irányú együttváltozás. Az abszolút érték a lineáris kapcsolat erősségét jelzi.
A négyzet (`r²`) a maradék ingadozás lineáris együttjárását fejezi ki, nem a késés időjárás okozta részét.

Változatlan adatból nincs korreláció. A legerősebb kapcsolat több összevetésből kiválasztott példa,
ezért nem előre kijelölt feltevés bizonyítása. Egy-egy nap elhagyásával az érzékenységet is ellenőrzöm.
Kevés nap, egymással összefüggő órák és térségi modellértékek alapján oksági hatás nem állapítható meg.
Utasszámot és közúti forgalmat nem mértem, így ezek hatását sem tudom elkülöníteni.

Források [GTFS Realtime](https://gtfs.org/documentation/realtime/reference/),
[GTFS menetrend](https://gtfs.org/documentation/schedule/reference/),
[BKK adatút](https://bkk.hu/rolunk/forgalmi-adatok-diagramok/miert-gyujtjuk-a-forgalmi-adatokat/),
[HÉV-integráció](https://bkk.hu/hirek/2021/08/megujul-a-bkk-futar-utazastervezo-alkalmazas.6729/),
[H8 közlemény](https://www.mavcsoport.hu/mavinform/h8-h9-potlobuszok-fovarosi-szakaszon-oktober-17-november-6),
[Open-Meteo](https://open-meteo.com/en/docs). A BKK és Open-Meteo adatok licence CC BY 4.0.
