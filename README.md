# Késésfigyelő

BKK-adatokból késések vizsgálata.

Beállítás: `uv sync --locked`

A kulcs a helyi `.env.bkk` fájlba kerül: `BKK_API_KEY=...`
Ehhez a `.env.example` ad üres mintát; a valódi kulcs és a `data/` nincs a Gitben.

Adatforrás-próba: `uv run --locked python proba.py`

Gyűjtő súgója: `uv run --locked python gyujto.py --help`

Mentett minták offline ellenőrzése: `uv run --locked python gyujto.py --ellenorzes MINTAMAPPA`
Ez alapból a `data/teszt` mappába dolgozik, nem indít internetes kérést.

Véges élő próbakör (három kérés): `uv run --locked python gyujto.py --egyszer`
Statikus menetrend egyszeri mentése: `uv run --locked python gyujto.py --menetrend`
Helyi óránkénti összesítés: `uv run --locked python gyujto.py --minoseg`

Tesztek: `uv run --locked python -m unittest -v test_gyujto`

Folyamatos mód csak külön indítással: `uv run --locked python gyujto.py --folyamatos`.
VP/TU 30, Alerts 60 másodpercenként, a menetrend naponta ellenőrződik;
legalább 10 másodperc telik el két kérés kezdete között. Újrainduláskor nincs pótló kérésroham.
Leállítás: Ctrl+C. VPS-telepítés és automatikus újraindítás külön lépés.

A nyers fájlok, a naplók és az órás összesítések a `data/` alatt vannak.
Az eredeti válaszok tömörítve, tartalomazonosítóval maradnak meg; a napló minden próbát külön őriz.
A működés és az értelmezés korlátai: [MODSZERTAN.md](MODSZERTAN.md).

Data source: BKK Zrt., CC BY 4.0
