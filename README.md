# Késésfigyelő

A Késésfigyelő a BKK mentett adataiból számol menetrendi eltérést, követési időt és várakozást.
A [weboldal](https://13.140.139.74/) belépés nélkül megnyitható.
A számítás szabályai a [módszertanban](MODSZERTAN.md), a kapcsolatok az [adatbázisábrán](adatbazis.svg) vannak.

## Használt eszközök

| Eszköz vagy szolgáltatás | Feladata |
| --- | --- |
| Python 3.14.8, uv | Elkülönített környezet, a csomagverziókat az `uv.lock` rögzíti. |
| BKK OpenData, GTFS és GTFS Realtime | Menetrend, járműhelyzetek, indulási közlések és forgalmi jelzések. |
| Open-Meteo | Negyedórás térségi időjárási modelladatok. |
| `gtfs-realtime-bindings` 3.0.0, Protobuf | A BKK bináris válaszainak kiolvasása. |
| PostgreSQL 18.6, `psycopg` 3.3.6 | Relációs adatbázis és Python-kapcsolat. |
| Streamlit 1.66.0, Plotly 6.9.0 | Webes felület és interaktív ábrák. |
| pandas 3.0.6, NumPy 2.5.4, tzdata 2026.5 | Táblázatok, kapcsolatvizsgálat és időzónák. |
| Docker Desktop | Helyi PostgreSQL és tesztadatbázis. A VPS-en a PostgreSQL közvetlenül fut. |
| Contabo VPS, Ubuntu 24.04.5 LTS, systemd | Gyűjtés és időzített feldolgozás a laptop nélkül is. |
| Caddy 2.11.7 | HTTPS-elérés és a tanúsítvány megújítása. |
| rclone, Google Drive | A nyers fájlok és a kész adatbázismentések másolása. |
| VS Code, Codex, Git, GitHub, OpenSSH | Helyi fejlesztés, verziókezelés és szerverelérés. |
| unittest, Ruff | Automatizált tesztek és kódellenőrzés. |

## Helyi indítás

Python 3.14.8 és uv szükséges. A repó főmappájában futtasd a következő parancsot.

```powershell
uv sync --locked --extra web
```

Az [.env.example](.env.example) `BKK_API_KEY` sorából készíts `.env.bkk` fájlt a saját BKK-kulcsoddal.
A PG kezdetű sorokból készíts `.env.db` fájlt az adatbázisod adataival. Ezek és a `data/` tartalma nem kerülnek Gitbe.

A kiszámolt `elemzes*/indulasok.json` és a hozzá tartozó `adatminoseg.json` fájlokat a `data/` alá másolva
az oldal adatbázis és BKK-kulcs nélkül is elindul.

```powershell
uv run --locked --extra web streamlit run app.py --server.address 127.0.0.1
```

## Gyűjtés és adatbázis

Az első két parancs egyszeri próba, a harmadik tartós gyűjtést indít.

```powershell
uv run --locked python proba.py
uv run --locked python gyujto.py --menetrend
uv run --locked python gyujto.py --folyamatos
```

A járműhelyzetek és indulási közlések 30, a forgalmi jelzések 60 másodpercenként érkeznek.
A menetrendet naponta, az időjárást 15 percenként ellenőrzi a gyűjtő.
A nyers válaszok tömörítve, a lekérési kísérletek külön naplóban maradnak meg.

A következő parancsok új helyi PostgreSQL-adatbázist indítanak Dockerrel, PowerShellből.
Meglévő adatbázisnál ezt a létrehozást hagyd ki.

```powershell
$env:POSTGRES_PASSWORD = [Net.NetworkCredential]::new("", (Read-Host "Postgres admin jelszó" -AsSecureString)).Password
docker run -d --name kesesfigyelo-db-1 --restart unless-stopped -p 127.0.0.1:5433:5432 -v kesesfigyelo-db:/var/lib/postgresql -e POSTGRES_PASSWORD postgres:18.6-bookworm
$env:POSTGRES_PASSWORD = $null
docker exec -it kesesfigyelo-db-1 psql -U postgres
```

A megnyíló SQL-parancssorban hozd létre a felhasználót és az adatbázist.

```sql
CREATE ROLE kesesfigyelo_betolto LOGIN;
\password kesesfigyelo_betolto
CREATE DATABASE kesesfigyelo OWNER kesesfigyelo_betolto;
\q
```

A megadott felhasználói jelszó kerüljön a `.env.db` fájlba. A következő parancsban a `MENETREND.zip` és `MINTAMAPPA`
helyére a mentett fájl és a `naplo/` alkönyvtárat is tartalmazó adatmappa útvonala kell.

```powershell
uv run --locked python betolto.py --letrehoz
uv run --locked python betolto.py --menetrend MENETREND.zip --adatmappa MINTAMAPPA --limit 20
uv run --locked python betolto.py --allapot
uv run --locked python napi.py --nap 2026-10-19
```

A betöltés futásonként legfeljebb a megadott számú új naplót dolgozza fel. Újraindítva a következőkkel folytatja.
A napi elemzéshez a nap végét követő négy óráig betöltött adatok kellenek.
Az eredmény és az újraszámolható `minta.json.gz` külön `data/elemzes-*` mappába kerül. Nap nélkül a tegnap készül el.
Mentett minta adatbázis nélküli újraszámolásához az `elemzes.py --nap 2026-10-19 --minta MINTA.json.gz` használható.

## Szerver és napi frissítés

A gyűjtő a `/home/ubuntu/kesesfigyelo` alatt fut. A betöltés ötpercenként legfeljebb 100 új naplót vesz át.
A napi elemzés budapesti idő szerint 06.15-kor dolgozza fel a tegnapot.
A web külön felhasználóval, az `/opt/kesesfigyelo-web` alól fut, és csak a `/var/lib/kesesfigyelo-web/data`
ellenőrzött exportjait olvassa. Az adatbázishoz és a BKK-kulcshoz nincs hozzáférése.
A jó eredmények automatikusan átkerülnek a webhez. A Git-push nem telepíti a szerver kódját.

SSH-belépés után ezekkel a parancsokkal ellenőrizhetők a szolgáltatások.

```bash
systemctl status kesesfigyelo.service kesesfigyelo-web.service
systemctl list-timers 'kesesfigyelo*'
```

A `kesesfigyelo` SSH-kapcsolat beállítása után egy kész nap letölthető a laptopra.

```powershell
uv run --locked python napi.py --letoltes kesesfigyelo --nap 2026-10-19
```

A laptop `Kesesfigyelo eredmenyek` feladata 09.00-kor és bejelentkezéskor másolja át az eredményt.
A web percenként észreveszi az új exportot, a számokkal együtt a következtetések is változnak.
A napi feldolgozás hibánál öt perc múlva újrapróbálkozik, egy órán belül legfeljebb három indítással.
Az adatbázisról naponta `.dump` mentés készül. A kész mentéseket és a nyers fájlokat óránként másolja a Drive-mentés.
A tesztüzemű Google-engedélyt hetente meg kell újítani.

## Tesztek és fájlok

```powershell
uv run --locked --extra web python -m unittest discover -v
```

Az adatbázisos próbákhoz külön tesztadatbázis kapcsolati fájlját add meg a `TEST_DATABASE_CONFIG`
környezeti változóban. Enélkül ezek a próbák kimaradnak.

| Hely | Tartalom |
| --- | --- |
| `gyujto.py`, `proba.py` | Gyűjtés és egyszeri adatforráspróba. |
| `betolto.py`, `bkk_bovites.py`, `adatbazis.sql` | Betöltés, BKK-mezők és adatbázisséma. |
| `elemzes.py`, `napi.py`, `app.py` | Számítás, napi feldolgozás és weboldal. |
| `atallas.py` | Régi adatbázis új mezőinek pótlása a nyers fájlokból, külön ellenőrzött átállás részeként. |
| `tests/` | Automatizált próbák. |
| `data/` | Nyers válaszok, naplók, menetrendek, exportok és mentések, Gitből kizárva. |

A forrás a [BKK OpenData](https://opendata.bkk.hu/data-sources) és az [Open-Meteo](https://open-meteo.com/), CC BY 4.0 licenccel.
Az oldal feldolgozott adatokat mutat. Az Open-Meteo ingyenes végpontja nem üzleti használatra való.
