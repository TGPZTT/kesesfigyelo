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
uv run --locked python -m unittest -v test_gyujto test_betolto
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

Adatok forrása: BKK Zrt., CC BY 4.0. Időjárás: [Open-Meteo](https://open-meteo.com/), CC BY 4.0; az ingyenes API nem üzleti használatra való.
