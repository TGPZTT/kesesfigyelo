# Módszertan

A vizsgálat a menetrendi eltérést, a járatok közti szüneteket és az ezekből számított várakozást hasonlítja össze.

## Adatok és kiválasztás

| Forrás | Mire használom? |
| --- | --- |
| BKK GTFS ZIP | Az adott nap menetrendje, megállói, útvonalai. |
| VehiclePositions | A jármű helyzete, megállónak a sorszáma, saját időbélyege és extra üzemi jelzései. |
| TripUpdates | Egy konkrét közlekedés megállónkénti érkezési és indulási adatai, állapotai. Viszont ezek lehet, hogy csak modellből számított előrejelzések. |
| Alerts | Forgalmi tájékoztatás. Nem ebből állapítom meg indulást. |
| Open-Meteo | Hőmérséklet, szél és csapadék három területre szólóan. Modelladat, nem megállóban végzett mérés. |

A választott tíz járat a következő: buszból a 46, 97E, 161, 169E, villamosból az 1, 2, 3, 4–6, troliból a 80 és 82.
A keleti városrész buszai a közös cél felé utazás miatt lettek így kiválasztva.
A 4–6 egy most együtt szerepel, mert felújítás miatt összevonták a két vonalat. Ennél teljesül az öt percnél sűrűbb követés feltétele. A H8 pedig csak külön kiegészítésként szerepel, mert azon a vonalon is épp karbantartás van és érdekes, hogy most mekkora zavart okoz ez. Majd később lehet érdekes összevetni a normális állapottal. Egy karbantartás előtti és utáni állapot is érdekes lett volna.

Egy járműút során az adott jármű egy adott napra tervezett útvonalat egyszer végigjár. Ugyanaz a busz több ilyet teljesíthet, és jellemzően teljesít is.
A továbbhaladás a jármű indulását vagy megállás nélküli elhaladását jelenti egy adott megállónál (ahol egyébként meg kéne állnia).
A megállósorszám is része az azonosításnak, mert az útvonal visszatérhet ugyanahhoz a megállóhoz.

## Adatéletciklus bemutatása a gyűjtéstől a weboldalig

A BKK respondjai több jármű és megálló adatait is tartalmazzák. Ugyanarról az indulásról először becslés,
aztán később már elmúlt időpont érkezhet, majd a közlés eltűnhet a forrásból. A mentésekből ezek változása is visszanézhető.

| Lépés | Mi történik? |
| --- | --- |
| Lekérés | A VPS-en futó `gyujto.py` ütemezve lekéri a BKK és az Open-Meteo adatait. |
| Nyers mentés | A válasz tömörített fájlba kerül. A tartalmából számított SHA256 ellenőrző összeg azonosítja, így a változatlan respond nem kap új fájlt. Minden request kísérlet külön naplóbejegyzést kap, a hibás és az ismételt is. |
| Adatbázis | A `betolto.py` ötpercenként legfeljebb száz új naplót vesz át. Ezek adatait PostgreSQL-táblákba bontja. Az ismételt betöltés nem duplázza az adatokat, hibánál pedig nem marad félkész betöltés. |
| Napi elemzés | A `napi.py` az előző nap eltárolt adataiból számol. Az `elemzes.py` összerendeli a respondokat, ellenőrzi az indulásokat, majd elkészülnek az összesítések. |
| Weboldal | Az ellenőrzött napi eredményfájlok átkerülnek a weboldalhoz tartozó külön adatmappába. Az `app.py` ezeket olvassa, és az új nap adataival a grafikonok és a következtetések is frissülnek. |
| Működésfigyelés | Egy külön rövid program percenként ellenőrzi, hogy fut-e a gyűjtő, elég frissek-e a sikeres lekérések, és megvannak-e a mentett fájlok. Életjelet vagy hibajelzést küld a Healthchecks.io-nak. Hiba vagy elmaradó életjel esetén emailes értesítés érkezik. |
| Biztonsági mentés | Az adatbázisról naponta mentés készül. A nyers fájlokat és a kész adatbázismentéseket óránként másolja a rendszer a Google Drive-ra. |

A számításból kihagyott adatok nyers mentése és az adatbázis ezen sora megmarad. A feldolgozás ezért újrafuttatható a gyűjtés megismétlése nélkül.
A Healthchecks.io a működést figyeli, de sajnos nem indítja újra a gyűjtőt.
A kapcsolatok az [adatbázisábrán](adatbazis.svg), a pontos mezők az [SQL-sémában](adatbazis.sql) láthatók.

A félperces helyzet- és induláslekérés a megállók közti mozgáshoz kell, a ritkábban változó zavarokhoz (alert adatok) egy perc is elég.
Két request kezdete között legalább tíz másodperc van, de ezek nem egyforma requestek. Eltolva mennek a BKK felé, és nem egyben. Ezek saját beállítások, nem a BKK által megadott kvóták. A BKK csak annyit mond, hogy lehetőleg 5mp gyakoriság felett legyenek.

Ha valami hálózati vagy bármilyen kritikus hiba van, ami miatt leáll a gyűjtés, akkor az újraindítás nem indít pótló kérésrohamot.
Hibás kilépés után a systemd szolgáltatáskezelő egy perc múlva újraindítja a gyűjtőt. A VPS újraindulásakor is automatikusan elindul.

## Hogyan lesz a respondokból továbbhaladási idő?

A FUTÁR a fedélzeti adatokat a BKK központján keresztül adja tovább. A HÉV-adatok HÉV fedélzeti egységétől a MÁV-hoz mennek, majd a MÁV-tól mennek a BKK-hoz.
A helyzet és az előrejelzés közös rendszerből származhat,ezért ezt óvatosan kell kezelni.

A program egy járműút egy megállójához tartozó teljes mentett közléssort vizsgál. A következőket ellenőrzi (bővebben a word mellékletben olvasható erről).

1. A jármű, a járműút, a szolgálati nap, a megálló és a megállósorrend összetartozik-e?
2. A két legutóbbi, külön saját időbélyegű közlés ugyanazt a már elmúlt indulást adja-e, nulla közölt bizonytalansággal?
3. A jármű helyzetei követhető továbbhaladást mutatnak-e a megálló mellett, legfeljebb 120 másodperces tartományban?
4. Ellentmond-e ennek nyitott ajtó, lehetetlen helyzetugrás, megállósorrend vagy másik végighaladással kevert közlés?

A mozgásellenőrzés 100 méteres megállókörnyezetet használ. A továbbhaladó pont legalább 40 méterre legyen a megállótól,
és legalább 30 méterre az előző ponttól. Ekkor gondolhatjuk, hogy mozgás van. Ha egyik pont sem közeli, az összekötő szakasz érintse a megállókörnyezetet.
A 45 m/s feletti sebességgel sem mehet semmilyen jármű. A közölt indulás után több mint öt másodperccel jelzett nyitott BKK-ajtó is ellentmondás.
Ezek a választott ellenőrzési kritériumok szóbeli összefoglalása, de a részletes feltételek az `elemzes.py` fájlban vannak.

Fontos belátni, hogy az ajtónyitás vagy megállás nem kötelező. Felszálló/leszálló utas nélkül a busz megállás nélkül is továbbhaladhat. 
Természetesen a kimaradó esetek nyers adatai mindig mentve maradnak, nem törlődnek, csak az indulási számításból maradnak ki.

A kihagyott megálló (`SKIPPED`), az adathiány (`NO_DATA`) és a törölt közlekedés (`CANCELED`) külön állapot.
Egy későbbi törlési jelzés nem törli a korábban már ellenőrizhető továbbhaladást hibás törlési jelzést feltételezve.
Friss normál állapot feloldhatja a törlési jelzést, egy régi válasz ismétlése nem.

## Mihez képest számít a késés?

**Késés = az elfogadott indulás − az adott napra érvényes, letöltött GTFS-menetrend indulása.**
Ha a menetrend 06.00, a közölt indulás 06.10, akkor a késés tíz perc.
A negatív eltérés korábbi indulást jelent, megmarad az eredményben.
A BKK által külön közölt más tervezett időpont csak ellenőrző adat. Nem írja át a fő késést.

A szolgálati nap a menetrendi közlekedés napja(i). A szombati `25:10:00` vasárnap 01.10-et jelent.
Az időpontokat UTC-ben tárolom, mert ilyen formában jön, de a naptárat és az óraátállítást budapesti idő szerint kezelem.
A menetrendváltozatokat az elemzés előtt összevetem. A járat azonosítója önmagában nem bizonyít helyes menetrendi hozzárendelést.

A nagy eltérés önmagában nem kizárási ok, mert a karbantartásnál nagy késések is lehetnek.

## Mit mutatnak az eredmények?

| Mutató | Számítás és jelentés |
| --- | --- |
| Pontos indulások aránya | A legfeljebb egy vagy két perccel korábbi vagy későbbi közölt indulások aránya a vizsgálható indulásokból. |
| Felhasználhatósági arány | Vizsgálható megállói továbbhaladások száma osztva a menetrend szerint tervezettekkel. Ez csak adatmennyiség, önmagában nem pontosság. |
| Medián eltérés | A sorba rendezett eltérések középső értéke. A napok mediánjait nem átlagolom. |
| Legnagyobb késés | Egyetlen elfogadott közlés max értéke (a helyével és időpontjával). |
| Szakasz változása | Ugyanazon járműút két egymást követő megállójának késéskülönbsége, majd a napi ilyen adatok mediánja. Megmutatja,hogy mennyivel nőtt vagy csökkent a késés két egymást követő megálló között. |
| Követési idő | Egymást követő járművek indulása között eltelt idő azonos megállóban és irányban. |
| Adatban nem szereplő közlekedés | A menetrendi járműúthoz nem érkezett járműhelyzet vagy menetfrissítés. Ez nem bizonyított járatkimaradás. |

A felület a darabszámot és az adatlefedettséget is mutatja. Választott szabály, hogy az órás BKK-értékhez legalább 30 esemény és 50% lefedettség kell.
A legfeljebb 60 másodperces mozgásközökből szigorúbb ellenőrző eredmény is készül.

## Várakozás és buszválasztás

A modellben az utas a vizsgálható időszak bármely pillanatában azonos eséllyel (egyenletes eloszlással) érkezik a megállóba, a menetrendtől függetlenül.
Két indulás közti teljes időszak átlagos várakozása a követési idő fele. A hosszabb szünet nagyobb súlyt kap.
A késést és a menetrendi várakozást ugyanarra az időszakra számolja a program. A kettő különbsége a többletvárakozás.
Az áthaladó buszról feltételezem, hogy felszálló utasnak megállt volna.

A saját kérdés az első megfelelő buszra felszállást hasonlítja egy kiválasztott (akár rövidebb menetidejű) járat megvárásához, közös a felszállóhely és a cél is, de a kettő között mások a megállók (számosságban is).
A teljes idő a várakozásból és ugyanazon busz menetidejéből áll. Csak azok az időszakok számítanak, amikor minden választás következő indulása és célba érkezése megállapítható.
A célba érkezést a közeledő megállós helyzet, és az első közeli megállás- vagy ajtójelzés adja.
A köztes helyzeteknek is érvényesnek kell lenniük, a teljes időköz, azaz a célmegállóba érkezést behatároló két helyzetadat között eltelt idő max 120 másodperc.
Az ismétlődő állásjelzés nem új érkezés. Két külön megérkezés közül nem választok utólag.
Az időbeli sorrendjükben nem elkülöníthető buszokat nem választom szét önkényesen.
Az eredmény csak a vizsgált adatokra érvényesek persze, nem minden hasonló helyzetre szóló általános utazási tanács.

## HÉV

A H8-as hév külön számítás és külön oldal. A közölt indulást ugyanúgy a letöltött menetrendhez mérem,
de a később nyitottnak jelzett ajtó itt nem kizárási feltétel, mert ennek a mezőnek használhatósága nem tűnt megbízhatónak.
A közös mozgásellenőrzés néhány feltétele még olvassa az ajtójelet, ezért az eljárás nem teljesen független tőle.

Az órás értékhez legalább tíz esemény, két vonat és 50% lefedettség, a napi követéshez három vonatpár kell.
A 2026. október 17-től érvényes rövidített menetrendet használom. A felújítás előtti összehasonlító időszak az adatokban szerepel, de ezekből nincs elég, úgyhogy az elemzésből hiányzik.
A pótlóbusz menetrendi párosítása nem vezetett megfelelően a BKK adatközléseiben (feltűnik az adatok között, olyan, ami az lehet, de a valóságban tudom, hogy jóval több pótlás van), ezért nem kap saját elemzést.

## Időjárás

A belváros, Rákosmente és a H8 külső térségének modelladatait a járatok órás késéséhez kapcsolom.
Egy órát csak akkor veszek teljesen elemezhetőnek, ha mind a négy negyedóra megvan, a hiányt nem átlagolom ki.
A csapadékot az óra végén lezáruló négy időszakból összeadom.

A járat órájához legalább 30 esemény és 50% lefedettség szükséges.
A nap és az órasáv különbségeit közös lineáris illesztéssel becsülöm mindkét változónál,
majd a megmaradó eltérések Pearson-korrelációját (`r`) számolom. A korrekció nélküli eredmény is összevethető.
A pozitív előjel azonos, a negatív ellentétes irányú együttváltozás. Az abszolút érték a lineáris kapcsolat erősségét jelzi.

Kevés nap, egymással összefüggő órák alapján oksági hatás nem állapítható meg.
Utasszámot és közúti forgalmat nem mértem, így ezek hatását sem tudom elkülöníteni.

Források [GTFS Realtime](https://gtfs.org/documentation/realtime/reference/),
[GTFS menetrend](https://gtfs.org/documentation/schedule/reference/),
[BKK adatút](https://bkk.hu/rolunk/forgalmi-adatok-diagramok/miert-gyujtjuk-a-forgalmi-adatokat/),
[HÉV-integráció](https://bkk.hu/hirek/2021/08/megujul-a-bkk-futar-utazastervezo-alkalmazas.6729/),
[H8 közlemény](https://www.mavcsoport.hu/mavinform/h8-h9-potlobuszok-fovarosi-szakaszon-oktober-17-november-6),
[Open-Meteo](https://open-meteo.com/en/docs). A BKK és Open-Meteo adatok licence CC BY 4.0.
