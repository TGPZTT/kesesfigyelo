"""Naponta csak a legújabb, ellenőrzött eredményt adja át a weboldalnak."""

import os
import re
import shutil
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import elemzes
import napi

MAPPA = re.compile(r"elemzes-[0-9]{8}-[0-9]{8}T[0-9]{12}Z-[a-f0-9]{8}")


def eredmenyek(alap):
    napok = {}
    for mappa in sorted((alap / "data").glob("elemzes-*")):
        if not MAPPA.fullmatch(mappa.name):
            continue
        if mappa.is_symlink() or not mappa.is_dir():
            raise ValueError("Hibás eredménymappa.")
        if any((mappa / nev).is_symlink() for nev in napi.FAJLOK):
            raise ValueError("Hibás eredményfájl.")
        adat = napi.json_olvas(mappa / "indulasok.json")
        # A régi módszer és a részleges próbák nem kerülhetnek vissza a webre.
        if (adat.get("modszer") != elemzes.MODSZER or adat.get("mintamenetek")
                or {s["vonal_id"] for s in adat.get("vonalak", [])} != set(napi.VONALAK)):
            continue
        nap = date.fromisoformat(adat["nap"])
        rang = (adat.get("keszult_utc", ""), mappa.name)
        if nap not in napok or rang > napok[nap][0]:
            napok[nap] = (rang, mappa)
    if not napok:
        raise ValueError("Nincs teljes napi eredmény.")
    return [mappa for _, mappa in napok.values()]


def ellenoriz(mappa):
    adat = napi.json_olvas(mappa / "indulasok.json")
    if adat.get("napi_sema") != 1 or "esemenyek" in adat:
        raise ValueError("Nem kis napi összesítés.")
    napi.ellenoriz(adat, napi.json_olvas(mappa / "adatminoseg.json"),
                  date.fromisoformat(adat["nap"]), napi.VONALAK)


def atad(forras, cel):
    with napi.zar(cel):
        kivalasztott = eredmenyek(forras)
        allapot = napi.tiszta_allapot(napi.json_olvas(forras / ".napi-allapot.json"))
        # Hibás új export esetén a web korábbi fájljaihoz nem nyúlunk.
        for mappa in kivalasztott:
            ellenoriz(mappa)
        adatmappa = cel / "data"
        adatmappa.mkdir(exist_ok=True)
        nevek = {m.name for m in kivalasztott}
        archiv = cel / ("archiv-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
        with tempfile.TemporaryDirectory(dir=cel) as hely:
            for mappa in kivalasztott:
                kesz = adatmappa / mappa.name
                if kesz.is_symlink():
                    raise ValueError("Hibás célmappa.")
                if kesz.exists() and all((kesz / n).read_bytes() == (mappa / n).read_bytes()
                                         for n in napi.FAJLOK):
                    continue
                atmeneti = Path(hely) / mappa.name
                atmeneti.mkdir(mode=0o750)
                for nev in napi.FAJLOK:
                    shutil.copyfile(mappa / nev, atmeneti / nev)
                ellenoriz(atmeneti)
                # Azonos nevű, korábban külön javított exportot is megőrzünk.
                if kesz.exists():
                    archiv.mkdir(exist_ok=True)
                    kesz.rename(archiv / kesz.name)
                try:
                    atmeneti.rename(kesz)
                except OSError:
                    if (archiv / kesz.name).exists():
                        (archiv / kesz.name).rename(kesz)
                    raise
        for mappa in adatmappa.glob("elemzes-*"):
            if MAPPA.fullmatch(mappa.name) and mappa.name not in nevek:
                if mappa.is_symlink() or not mappa.is_dir():
                    raise ValueError("Hibás korábbi eredménymappa.")
                archiv.mkdir(exist_ok=True)
                mappa.rename(archiv / mappa.name)
        napi.json_ir(cel / ".napi-allapot.json", allapot)


def main():
    os.umask(0o027)
    cel = Path("/var/lib/kesesfigyelo-web")
    try:
        atad(Path("/home/ubuntu/kesesfigyelo"), cel)
        print("A webes eredmények átadása sikerült.")
        return 0
    except Exception:  # noqa: BLE001 -- A programhatár nem írhat ki nyers kapcsolatadatot.
        try:
            napi.allapot(cel, None, False, datetime.now(UTC), hiba_kod="fajl")
        except (OSError, ValueError):
            print("A webes állapotfájl mentése sem sikerült.")
        print("A webes eredmények átadása nem sikerült. A korábbi eredmények megmaradtak.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
