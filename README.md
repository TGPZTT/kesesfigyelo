# Késésfigyelő

BKK-adatokból késések vizsgálata.

Python 3.14.8 és uv kell. Beállítás: `uv sync --locked`

A kulcs a helyi `.env.bkk` fájlba kerül: `BKK_API_KEY=...`
Ehhez a `.env.example` BKK-s sora ad üres mintát; a valódi kulcs és a `data/` nincs a Gitben.

Adatforrás-próba: `uv run --locked python proba.py`

Gyűjtő súgója: `uv run --locked python gyujto.py --help`

Mentett minták offline ellenőrzése: `uv run --locked python gyujto.py --ellenorzes MINTAMAPPA`
Ez alapból a `data/teszt` mappába dolgozik, nem indít internetes kérést.
A korábbi `.pb` mintákat, a `.pb.gz` és időjárási `.json.gz` fájlokat is olvassa.

Véges élő próbakör (három kérés): `uv run --locked python gyujto.py --egyszer`
Statikus menetrend egyszeri mentése: `uv run --locked python gyujto.py --menetrend`
Időjárás egyszeri mentése, kulcs nélkül: `uv run --locked python gyujto.py --idojaras`
Helyi óránkénti összesítés: `uv run --locked python gyujto.py --minoseg`
A lekérési és a sikeres válaszok közti szünetet külön mutatja, az üres órákkal együtt.

Folyamatos mód csak külön indítással: `uv run --locked python gyujto.py --folyamatos`.
VP/TU 30, Alerts 60 másodpercenként, a menetrend naponta ellenőrződik;
legalább 10 másodperc telik el két kérés kezdete között. Újrainduláskor nincs pótló kérésroham.
Az időjárást három térségre, egy közös kérésben, 15 percenként menti.
Az egyszeri módok is betartják a naplózott várakozást; az időjárásnál ez legalább 15 perc.
Terminálban indított gyűjtés leállítása: Ctrl+C. A szerveres szolgáltatás ettől külön fut.

A nyers fájlok, a naplók és az órás összesítések a `data/` alatt vannak.
Az eredeti válaszok tömörítve, tartalomazonosítóval maradnak meg; a napló minden próbát külön őriz.
A működés és az értelmezés korlátai: [MODSZERTAN.md](MODSZERTAN.md).

## Adatbázis

PostgreSQL 18.6-tal kipróbálva. A betöltő a már mentett fájlokat olvassa,
nem kér új BKK- vagy időjárási adatot. Egy futás véges, alapból legfeljebb 20 új naplót tölt be.
Kapcsolók nélkül csak a súgót írja ki.
Tíz tábla és egy adatminőség-nézet készül; a táblázatos séma a [módszertanban](MODSZERTAN.md#adatbázisba-töltés) van.
Az [adatbázisábrán](adatbazis.svg) a tíz tábla, mind a 119 oszlop és a tényleges idegen kulcsok szerepelnek.
Az ábra a PostgreSQL-sémából készült. Egy vonal egy idegen kulcs, több összetartozó mező esetén közös felirattal.
A pótlóbuszok és az ellenőrzendő új menetek is bekerülnek, külön `potlas_jelzes` mezővel.
A `potolt_vonal_id` névegyezésből kapott kapcsolatjelölt, az eredeti buszazonosító megmarad.

A `.env.example` PG-vel kezdődő sorait másold a helyi `.env.db` fájlba,
és add meg az adatbázis jelszavát. A BKK-kulcs külön, a `.env.bkk` fájlban marad.
A `.env.db` nincs a Gitben.

Új helyi adatbázis Dockerrel, PowerShellben. Ha már megvan, ezt a létrehozást hagyd ki.
A [hivatalos PostgreSQL-kép](https://hub.docker.com/_/postgres) adatai külön Docker-kötetben maradnak.

```powershell
$env:POSTGRES_PASSWORD = [Net.NetworkCredential]::new("", (Read-Host "Postgres admin jelszó" -AsSecureString)).Password
docker run -d --name kesesfigyelo-db-1 --restart unless-stopped -p 127.0.0.1:5433:5432 -v kesesfigyelo-db:/var/lib/postgresql -e POSTGRES_PASSWORD postgres:18.6-bookworm
$env:POSTGRES_PASSWORD = $null
docker exec kesesfigyelo-db-1 pg_isready -U postgres
```

Ha az utolsó parancs `accepting connections` választ ad, lépj be:
`docker exec -it kesesfigyelo-db-1 psql -U postgres`
Ott egyszer hozd létre a saját adatbázist és a betöltő felhasználóját:

```sql
CREATE ROLE kesesfigyelo_betolto LOGIN;
\password kesesfigyelo_betolto
CREATE DATABASE kesesfigyelo OWNER kesesfigyelo_betolto;
\q
```

A `\password` kérdésénél megadott jelszó kerüljön a `.env.db` `PGPASSWORD` sorába.
A betöltő felhasználó nem rendszergazda; a saját adatbázisában dolgozik.
A következő parancsokban a `MENETREND.zip` és a `MINTAMAPPA` helyére a mentett fájl és adatmappa útvonala kell.
A mintamappa tartalmazza a `naplo` és a hozzá tartozó nyers fájlok mappáját.

```powershell
uv run --locked python betolto.py --letrehoz
uv run --locked python betolto.py --menetrend MENETREND.zip --adatmappa MINTAMAPPA --limit 20
uv run --locked python betolto.py --allapot
```

Az első parancs táblákat és nézetet készít a már létező adatbázisba.
A betöltő meglévő táblákat nem alakít át. Eltérő séma esetén új, üres adatbázisba töltsd be a mentett fájlokat.
A második előbb a menetrendet, utána a naplókat tölti be. Újabb futtatáskor a korábbi naplókat átugorja,
és a következő legfeljebb 20 újat tölti be. A harmadik csak a darabszámokat és a méretet mutatja.
Az adatminőség-nézet az importált naplókról szól; a futó gyűjtés állapotát külön kell ellenőrizni.

Tesztek PostgreSQL-lel, külön ideiglenes táblacsoportban:

```powershell
$env:TEST_DATABASE_CONFIG = ".env.db"
uv run --locked python -m unittest -v tests.test_gyujto tests.test_betolto
$env:TEST_DATABASE_CONFIG = $null
```

A teszt a saját ideiglenes tábláit eltávolítja, a betöltött mintát megtartja.
`TEST_DATABASE_CONFIG` nélkül az adatbázist igénylő próbák kimaradnak.

Szerveren a betöltő külön `.venv-db` környezetben fut. A helyi Unix-kapcsolatnál
a `.env.db` beállítása `PGHOST=/var/run/postgresql`, `PGPORT=5432`, a saját adatbázis és felhasználó neve.
Ilyenkor a helyi felhasználó azonosítása miatt nem kell külön adatbázisjelszó.

A beállított szerveren a betöltés ötpercenként, legfeljebb 100 új naplóval fut.
Ellenőrzés SSH-belépés után:

```bash
.venv-db/bin/python betolto.py --allapot
systemctl status kesesfigyelo-betoltes.service
journalctl -u kesesfigyelo-betoltes.service -n 15 --no-pager
systemctl list-timers 'kesesfigyelo*'
```

A betöltő két adag között `inactive`, ez rendben van. Az időzítő legyen `active`, a legutóbbi futás eredménye `success`.

A napi adatbázismentés a `data/adatbazis` mappába kerül, PostgreSQL custom (`.dump`) formátumban.
A kész fájlokat a meglévő felhőmentés is másolja. Visszaállításra a `pg_restore` való;
a próba külön, üres adatbázisba történik. A futó PostgreSQL adatkönyvtárát nem másolom mentésként.

## Elemzés

Az `elemzes.py` a már betöltött adatbázisból olvas, nem gyűjt és nem ír az adatbázisba.
A nap és a vizsgált vonalak mellett meg kell adni a menetrendi fájl `nyers_fajl.id` azonosítóját.
Az érintett menetrendváltozatokat összeveti; eltérésnél megáll.

Példa a 4–6-ra, ha a használt menetrend azonosítója 1:

```powershell
uv run --locked python elemzes.py --nap 2026-10-17 --vonal 3046 --menetrend 1
```

Az eredmény a `data/elemzes/indulasok.json`, a megismételhető helyi minta a `minta.json.gz`.
Kis próbához a `--menet` kapcsolóval menetazonosítók is megadhatók, vesszővel elválasztva.
Ilyen részleges mintából nem számol teljes órás követést.

Újraszámolás a kimentett mintából, adatbázis nélkül:

```powershell
uv run --locked python elemzes.py --nap 2026-10-17 --minta data/elemzes/minta.json.gz
uv run --locked python -m unittest tests.test_elemzes
```

Az adatbázisos elemzési próbákhoz ugyanaz a `TEST_DATABASE_CONFIG` kell, mint a betöltő tesztjeihez.
Az indulások minősége, a kizárt esetek és a felhasznált darabszámok is megmaradnak.
Az összesítés a továbbhaladások utólag közölt idejét használja, mozgásellenőrzéssel és BKK-ajtóadatokkal.
Az áthaladások is megmaradnak. A HÉV külön eljárással készül, hivatalos pontosságot ebből nem számolok.
A régi adatbázisban hiányzó mezőkhöz külön sémaátállítás és a nyers adatok visszatöltése kell.

## Webes nézet

Helyi indítás Streamlittel:

```powershell
uv run --locked --extra web streamlit run app.py --server.address 127.0.0.1
```

Az oldal a `data/elemzes*/indulasok.json` fájlokat olvassa. Ehhez előbb a fenti elemzést kell lefuttatni,
vagy egy már kiszámolt mintát bemásolni. A weboldal nem kér élő BKK-adatot és nem csatlakozik az adatbázishoz.
Öt oldala van, áttekintés, járatonkénti részletek, adatminőség, időjárás és HÉV. A grafikonok Plotlyval készülnek.
Bal oldalon több nap is kijelölhető, a dátum mellett a hét napja is látszik.
A közös eredményt a megfigyelésekből számolja. Egy napot kiválasztva külön is megnézhető.
Az irányok végállomásnevet kapnak, a 4–6 várakozásánál megálló választható.
A buszos példában a várakozás és a menetidő együtt szerepel, néhány közös felszállóhely és célpont között.
A grafikonok a járműtípus BKK-színét használják.
Az áttekintésben az egy- vagy kétperces menetrendi eltérés alapján összehasonlíthatók a vonalak.
A H8-nál a közölt idők eltérése és a vonatok közti idő vizsgálható, néhány fő állomás és irány közül választva.
A HÉV közölt indulását nem keveri a helyzetből becsült érkezéssel teljes menetidővé.
Az órás bontás a napokat és az irányokat külön mutatja. Az óra a menetrendi indulásé.
Óránként legalább 30 megállói elindulás kell, HÉV-nél legalább 10 és két külön vonat, legalább 50% lefedettséggel.
Az összesített órás görbe is csak az ezeknek megfelelő napok és órák adataiból készül. A hiányzó órákon nem húz át vonalat.
A napi ábra külön jelzi a menetrendi indulás nélküli és az elégtelen adatú órákat, az ok és a darabszám helyben leolvasható.
A legnagyobb közölt késésnél a hely és az időpont is szerepel. A hozzá tartozó megállósoron a menetrend és a közölt idők együtt látszanak.
Ez egyetlen szélső eset. A szakaszonkénti medián külön, több jármű megállópárjaiból készül.
Ezeket a részleteket az elemző a `keses_reszletek` mezőben menti. Régebbi exportból pontos időpontot nem talál ki az oldal.
Az oldal csak az új módszerrel készült napokat olvassa. A régi exportokat újra kell számolni.
Az időjárásnézet a nap és napszak átlagos különbségét is figyelembe veszi. Oksági hatást nem állít.
A pontábra ugyanazokat a korrigált értékeket használja, mint a közölt korreláció. A járatrangsor és a többletvárakozás szövege az aktuális kijelölésből készül.
A webes csomagok külön, `web` csoportban vannak, a gyűjtőnek nincs rájuk szüksége.

A szerveres változat [itt nyitható meg](https://13.140.139.74/), belépés nélkül.
Caddy kezeli a HTTPS-t és az IP-cím tanúsítványának automatikus megújítását.
A `kesesfigyelo-web.service` külön felhasználóval és Python-környezettel fut az `/opt/kesesfigyelo-web` mappából.
Csak az ellenőrzött kis exportokat és a tisztított frissítési állapotot olvashatja.
A napi feldolgozás után ezek automatikusan átkerülnek a web mappájába. A laptopnak nem kell bekapcsolva lennie.
Új kódot külön kell ide áttenni és a webszolgáltatást újraindítani. A Git-push önmagában nem telepít.

A lekérések órás minőségéhez az elemzés mappájába tett `adatminoseg.json` kell.
Ez a gyűjtő mentett `data/adatminoseg/` összesítéseinek az adott napra szűrt, időrendbe rendezett listája.
Az órák UTC szerint vannak mentve, a weboldal budapesti időben mutatja őket.
Ha ez a fájl hiányzik, az oldal ezt jelzi; az indulások besorolása ettől még megtekinthető.

## Napi eredmények

Egy lezárt nap feldolgozása a meglévő adatbázisból, például a VPS-en:

```bash
.venv-db/bin/python napi.py --nap 2026-10-19
```

Nap nélkül a tegnapi budapesti napot választja, leghamarabb hajnali 4 után.
A betöltött adatoknak is el kell érniük a nap utáni négyórás szegélyt.
A menetrendet a napi lekérések alapján választja és a változatokat összeveti.
Az eredmény és a megismételhető minta külön, időbélyeges mappába kerül.
Hibás futás nem írja felül a korábbi jó eredményt.
A tíz alapvonal mellett külön elkészül a H8 és a három térség időjárási összesítése.
Ezek hiánya vagy hibája külön jelzést kap. A mentett mintába az újraszámoláshoz szükséges kiegészítések is bekerülnek.

A kész eredmény letöltése a laptopra a beállított SSH-kapcsolattal:

```powershell
uv run --locked --extra web python napi.py --letoltes kesesfigyelo --nap 2026-10-19
```

Csak a kis összesítést és az órás adatminőséget másolja, ellenőrző összeggel.
A nyers adatok és az adatbázis a szerveren maradnak.
A web percenként észreveszi az új helyi fájlt. Alapból minden kész napot összesít, az újakat is.
Kézi napválasztáskor a kijelölés megmarad. A számok és az eredményeket leíró mondatok együtt frissülnek.
A felület a helyi másolás és a szerveres elemzés állapotát külön mutatja.
Kikapcsolt laptopon nincs helyi frissítés.

A VPS `kesesfigyelo-elemzes.timer` időzítője budapesti idő szerint reggel 06.15-kor dolgozza fel a tegnapi napot.
A laptop `Kesesfigyelo eredmenyek` Windows-feladata 09.00-kor és bejelentkezéskor másolja át a kész eredményt.
Csak bejelentkezett felhasználóval fut, nem ébreszti fel a gépet. Reggel 9 előtt még az előző kész napot kéri.
Hálózati hibánál félóránként legfeljebb háromszor újrapróbálkozik.
Többnapos kihagyás után a köztes napok a fenti `--nap` kapcsolóval tölthetők le.

Az új számítás és átadás próbái:

```powershell
uv run --locked --extra web python -m unittest tests.test_elemzes tests.test_napi tests.test_app
```

Az automatizált tesztek a `tests/` mappában vannak. Az összes futtatása a repó főmappájából
`uv run --locked --extra web python -m unittest discover -v` paranccsal történik.

A 4-es feldolgozás a késést mindig az adott napra érvényes, letöltött GTFS-menetrendhez méri.
A BKK más tervezett időpontjai külön ellenőrző adatként maradnak meg, a fő késést nem módosítják.
Ehhez az új adatbázisoszlopok és a megtartott nyers TripUpdates fájlok újrabetöltése szükséges.
A régi adatbázist a betöltő nem alakítja át automatikusan.
Az `atallas.py` külön átállító függvénye a megtartott eredeti válaszokból pótolja az új mezőket.
A hívó indítja a tranzakciót, és a véglegesítés előtt ellenőrzi a korábbi oszlopok teljes egyezését.
Az átállás előtt friss mentés kell. A gyűjtő közben tovább menti az új válaszokat.

Adatok forrása: BKK Zrt., CC BY 4.0. Időjárás: [Open-Meteo](https://open-meteo.com/), CC BY 4.0. Az ingyenes API nem üzleti használatra való.
