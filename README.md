# Késésfigyelő

A program a BKK adataiból vizsgálja a késéseket, a járatok közti időt és az utasok várakozását.
A projekthez készült (python generált) [weboldal](https://13.140.139.74/) belépés nélkül megnyitható, és tervezetten még néhány napig naponta új adatokkal bővül.

## Dokumentáció

| Anyag | Tartalom |
| --- | --- |
| [Adatgyűjtési terv](docs/adatgyujtesi-terv.docx) | A terv leírja, hogy milyen adatokat gyűjt a rendszer, és hogyan dolgozza fel őket. |
| [Dokumentáció](docs/dokumentacio.docx) | A dokumentáció bemutatja a rendszer működését, a legfontosabb eredményeket és a korlátokat. |
| [Adatcsomagok és döntések](docs/adatcsomagok-es-dontesek.docx) | Ez a dokumentáció melléklete, ami valódi adatpéldákon keresztül mutatja be a request után kapott adatokat, és a feldolgozás/szűrés menetét, feltételeit. |
| [Módszertan](MODSZERTAN.md) | Ebben a dokumentumban vannak a mutatók és a számítás szabályai összefoglalva. |
| [Adatbázisábra](adatbazis.svg) | A PostgreSQL-ből generált ER-diagram (SchemaSpy és Graphviz) . |
| [Adatbázisséma](adatbazis.sql) | Ez az SQL-fájl hozza létre a táblákat és az adatminőségi nézetet. |

## Adatminta

Az [adatminta](minta/adatminta.zip) az október 17–21-i eredményeket és öt eredeti, tömörített BKK-választ tartalmaz.
A kész eredményekből a weboldal adatbázis és BKK-kulcs nélkül is megnyitható.
Az öt válasz csak egy rövid részlet a gyűjtésből, nem az öt nap teljes bemenete.

A teljes adatbázis természetesen nem fér fel githubra, de a minta csomagban a 169E egy október 20-i útjának összes mentett helyzetadata és megállói frissítése is megvan, a menetrendi sorokkal együtt.
Ebből a [feldolgozó](elemzes.py) újraszámolja ennek az egy útnak az eredményét.
A `manifest.json` felsorolja a csomag fájljait és az ellenőrző összegeiket.

## Indítás

[Git](https://git-scm.com/), [uv](https://docs.astral.sh/uv/) és Python 3.14.8 szükséges.
A következő parancsok PowerShellből indítják a helyi oldalt.

```powershell
git clone https://github.com/TGPZTT/kesesfigyelo.git
cd kesesfigyelo
uv sync --locked --extra web
Expand-Archive -LiteralPath minta/adatminta.zip -DestinationPath . -Force
uv run --locked --extra web streamlit run app.py --server.address 127.0.0.1
```

A helyi cím ez kell, hogy legyen: [http://127.0.0.1:8501](http://127.0.0.1:8501).

## Eszközök

| Eszköz vagy szolgáltatás | Feladat |
| --- | --- |
| Python 3.14.8, uv | A Python futtatja a programot, az uv a benne leírt package verziókból állítja össze a környezetet. |
| BKK OpenData, GTFS, GTFS Realtime | Ezekhez kell api kulcs, de ha ez megvan, akkor a requestek után innen érkezik a menetrend, a járműhelyzet, a megállói adatok és a forgalmi (alert) tájékoztatás. |
| Open-Meteo | A három területre ad időjárási adatokat (amik valójában csak modelladatok, de kellően pontosak). |
| `gtfs-realtime-bindings` 3.0.0, Protobuf | Ezekkel olvassa ki a program a BKK response válaszait. |
| PostgreSQL 18.6, `psycopg` 3.3.6 | Relációs adatbázist hoz létre és ebben tárolja az adatokat, a psycopg kapcsolja hozzá a Pythont. |
| Streamlit 1.66.0, Plotly 6.9.0 | Ezekkel generálódik az oldal és az interaktív ábrákat is ez állítja be. |
| pandas 3.0.6, NumPy 2.5.4, tzdata 2026.5 | Adatmanipulációs alap packagek. |
| Contabo VPS, Ubuntu 24.04.5 LTS, systemd | A szerveren a helyi géptől függetlenül fut a gyűjtés és a napi feldolgozás. |
| Docker Desktop | A helyi PostgreSQL és a tesztadatbázis fut benne. A VPS-en közvetlenül fut a PostgreSQL. |
| Caddy 2.11.7 | A weboldal HTTPS-elérését és a tanúsítvány megújítását intézi. |
| rclone, Google Drive | A nyers fájlokról és az adatbázisról készülő mentéseket másolják a google driveomra (még pár napig, ameddig a kapacitás engedi). Ezek kritikus adatok, és így visszaállíthatóak baj esetén. |
| Healthchecks.io | A külön működésfigyelő kis program jelzéseit fogadja, és hiba esetén emailt küld. |
| VS Code, Git, GitHub, OpenSSH | A fejlesztéshez, verziókezeléshez és a szerver eléréséhez használtam őket. |
| unittest, Ruff | A tesztek futtatására és a kód automatikus ellenőrzésére valók. |

## Beállítások

A [.env.example](.env.example) alapján két helyi titkos fájl kell a saját gyűjtéshez és adatbázishoz.
A kész eredmények megnyitásához ezek nem szükségesek.

| Fájl | Beállítás |
| --- | --- |
| `.env.bkk` | A `BKK_API_KEY` a saját BKK-s apikulcsot tartalmazza. |
| `.env.db` | A `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` és `PGPASSWORD` az adatbázis elérését adja meg. |

## Gyűjtés

A [gyűjtő](gyujto.py) a helyzetadatokat és az indulási adatokat 30, a forgalmi (alert) jelzéseket percenként kéri le. (Hibáknál nem lényeges, hogy "sűrű" ismeretünk legyen)
A menetrendet naponta, az időjárást 15 percenként ellenőrzi, frissíti a rendszer.

```powershell
uv run --locked python proba.py
uv run --locked python gyujto.py --menetrend
uv run --locked python gyujto.py --folyamatos
```

Az első két parancs csak egy egyszeri teszt, a harmadik folyamatos gyűjtést indít.
A nyers válaszok és a lekérések naplói a Gitből kizárt (gitignore) `data/` mappába kerülnek.

## Adatbázis

Új helyi adatbázishoz [Docker](https://www.docker.com/products/docker-desktop/) kell.
Meglévő PostgreSQL esetén új létrehozás helyett annak adatai kerüljenek a `.env.db` fájlba.

```powershell
$env:POSTGRES_PASSWORD = [Net.NetworkCredential]::new("", (Read-Host "Adatbázis jelszó" -AsSecureString)).Password
docker run -d --name kesesfigyelo-db-1 --restart unless-stopped -p 127.0.0.1:5433:5432 -v kesesfigyelo-db:/var/lib/postgresql -e POSTGRES_USER=kesesfigyelo_betolto -e POSTGRES_DB=kesesfigyelo -e POSTGRES_PASSWORD postgres:18.6-bookworm
$env:POSTGRES_PASSWORD = $null
uv run --locked python betolto.py --letrehoz
```

A megadott jelszó kerüljön a `.env.db` fájlba.
A [betöltő](betolto.py) a mentett menetrendet és a `naplo/` alkönyvtárat is tartalmazó adatmappát olvassa.
(Az alsó kódban lévű `MENETREND.zip` és `ADATMAPPA` helyére ezek saját útvonalát kell bmásolni.)
Az öt eredeti választ bemutató kis minta nem teljes napi betöltési anyag. Sajnos csak ez fért fel githubra.

```powershell
uv run --locked python betolto.py --menetrend MENETREND.zip --adatmappa ADATMAPPA --limit 20
uv run --locked python betolto.py --allapot
uv run --locked python napi.py --nap 2026-10-20
```

Az egészet újraindítva a betöltő majd a következő naplókkal folytatja a munkát automatikusan. A napi számításhoz a nap végét követő négy óráig betöltött adatok kellenek, mert vannak járatok (pl a hév, aminél egy járat túlnyúlik éjfélen).

## Működés

A gyűjtés VPS-en fut, a betöltés ötpercenként indul, a [napi feldolgozás](napi.py) pedig 06.15-kor készíti el az előző napot. Ez csak azért van, mert ekkor már biztosan nincs az előző napról túlnyúlt járat.
A [weboldal](app.py) csak az ellenőrzött eredményfájlokat olvassa, semmi nyers adatot nem dolgoz fel már. Az új napokkal az ábrák és a számított mondatba foglalt megállapítások is frissülnek (ezek számai jellemzően).
A mentést és a hibafigyelést a [módszertan](MODSZERTAN.md) írja le részletesebben, de a másik mellékelt docx is hasznos a megértésben.

## Ellenőrzés (mintaadat)

Az adatminta kicsomagolása után a következő parancs újraszámolja a kiválasztott 169E indulásait.
A `data/feldolgozasi-minta/vart-eredmeny.json` tartalmazza viszont már a várt eredményt. A készítés időpontja újraszámoláskor viszont természetesen megváltozik.

```powershell
uv run --locked python elemzes.py --nap 2026-10-20 --minta data/feldolgozasi-minta/minta.json.gz --kimenet data/minta-eredmeny
uv run --locked python gyujto.py --ellenorzes data/mintak-20261016T120719162469Z
uv run --locked --extra web python -m unittest discover -v
```

Az automatizált próbák a [tests](tests/) mappában vannak.
Az adatbázisos próbákhoz a `TEST_DATABASE_CONFIG` változóban külön tesztadatbázis beállításfájlját kell megadni, bemásolni. Enélkül ezek kimaradnak.

## Források

Az adatok a [BKK OpenData](https://opendata.bkk.hu/data-sources) és az [Open-Meteo](https://open-meteo.com/) szolgáltatásából származnak, CC BY 4.0 licenccel.
Az Open-Meteo ingyenes végpontja nem üzleti használatra való.
