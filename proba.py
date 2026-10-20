from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


# Egy adatforrás kipróbálása.
def api_proba(forras, kulcs):
    alapcim = "https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full"
    parameterek = urlencode({"key": kulcs})
    cim = alapcim + "/" + forras + ".pb?" + parameterek

    try:
        with urlopen(cim, timeout=20) as valasz:
            adat = valasz.read()
            print(forras + ": HTTP " + str(valasz.status) + ", " + str(len(adat)) + " bájt")
    except HTTPError as hiba:
        print(forras + ": HTTP-hiba " + str(hiba.code))
        raise SystemExit(1)
    except OSError:
        print(forras + ": nem sikerült kapcsolódni.")
        raise SystemExit(1)


# A helyi fájl egy sora: BKK_API_KEY=...
mappa = Path(__file__).resolve().parent
beallitas = (mappa / ".env.bkk").read_text(encoding="utf-8").strip()
kulcs = beallitas.removeprefix("BKK_API_KEY=").strip()

# Egy-egy kérés, ebben a sorrendben. Hibánál a következő forrás már nem indul el.
for forras in ("VehiclePositions", "TripUpdates", "Alerts"):
    api_proba(forras, kulcs)
