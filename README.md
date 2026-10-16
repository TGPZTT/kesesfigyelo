# Késésfigyelő

BKK-adatokból késések vizsgálata.

Beállítás: `uv sync --locked`

A kulcs a helyi `.env.bkk` fájlba kerül: `BKK_API_KEY=...`
Ehhez a `.env.example` ad üres mintát; a valódi kulcs és a `data/` nincs a Gitben.

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

Tesztek: `uv run --locked python -m unittest -v test_gyujto`

Folyamatos mód csak külön indítással: `uv run --locked python gyujto.py --folyamatos`.
VP/TU 30, Alerts 60 másodpercenként, a menetrend naponta ellenőrződik;
legalább 10 másodperc telik el két kérés kezdete között. Újrainduláskor nincs pótló kérésroham.
Az időjárást három térségre, egy közös kérésben, 15 percenként menti.
Az egyszeri módok is betartják a naplózott várakozást; az időjárásnál ez legalább 15 perc.
Leállítás: Ctrl+C. VPS-telepítés és automatikus újraindítás külön lépés.

A nyers fájlok, a naplók és az órás összesítések a `data/` alatt vannak.
Az eredeti válaszok tömörítve, tartalomazonosítóval maradnak meg; a napló minden próbát külön őriz.
A működés és az értelmezés korlátai: [MODSZERTAN.md](MODSZERTAN.md).

Adatok forrása: BKK Zrt., CC BY 4.0. Időjárás: [Open-Meteo](https://open-meteo.com/), CC BY 4.0; az ingyenes API nem üzleti használatra való.
