"""A BKK nyilvános jármű- és menetrendi kiegészítéseinek protobuf-leírása.

Forrás https://opendata.bkk.hu/docs/gtfs-realtime-realcity.proto
Az ajtójel állapot, külön eseményidő nélkül. A hiányzó érték nem hamis.
"""

from google.protobuf import descriptor_pb2, descriptor_pool
from google.transit import gtfs_realtime_pb2


def _regisztral():
    pool = descriptor_pool.Default()
    nev = "kesesfigyelo_bkk.vehicle"
    try:
        return pool.FindExtensionByName(nev)
    except KeyError:
        pass
    leiras = descriptor_pb2.FileDescriptorProto(
        name="kesesfigyelo-bkk.proto", package="kesesfigyelo_bkk", syntax="proto2")
    leiras.dependency.append(gtfs_realtime_pb2.DESCRIPTOR.name)
    uzenet = leiras.message_type.add(name="VehicleDescriptor")
    for mezo, szam, tipus in (("vehicle_model", 1, 9), ("deviated", 2, 8),
                              ("vehicle_type", 3, 5), ("door_open", 4, 8), ("stop_distance", 5, 5)):
        uzenet.field.add(name=mezo, number=szam, type=tipus, label=1)
    leiras.extension.add(name="vehicle", number=1006, type=11, label=1,
                         extendee=".transit_realtime.VehicleDescriptor",
                         type_name=".kesesfigyelo_bkk.VehicleDescriptor")
    pool.Add(leiras)
    return pool.FindExtensionByName(nev)


JARMU_BOVITES = _regisztral()


def _megallo_regisztral():
    pool = descriptor_pool.Default()
    nev = "kesesfigyelo_bkk.stop_time_update"
    try:
        return pool.FindExtensionByName(nev)
    except KeyError:
        pass
    leiras = descriptor_pb2.FileDescriptorProto(
        name="kesesfigyelo-bkk-megallo.proto", package="kesesfigyelo_bkk", syntax="proto2")
    leiras.dependency.append(gtfs_realtime_pb2.DESCRIPTOR.name)
    uzenet = leiras.message_type.add(name="StopTimeUpdate")
    for nev, szam in (("scheduled_arrival", 1), ("scheduled_departure", 2)):
        uzenet.field.add(name=nev, number=szam, type=11, label=1,
                         type_name=".transit_realtime.TripUpdate.StopTimeEvent")
    leiras.extension.add(name="stop_time_update", number=1006, type=11, label=1,
                         extendee=".transit_realtime.TripUpdate.StopTimeUpdate",
                         type_name=".kesesfigyelo_bkk.StopTimeUpdate")
    pool.Add(leiras)
    return pool.FindExtensionByName("kesesfigyelo_bkk.stop_time_update")


MEGALLO_BOVITES = _megallo_regisztral()


def jarmu_bovites(jarmu):
    if not jarmu.HasExtension(JARMU_BOVITES):
        return {"ajto_nyitva": None, "megallo_tavolsag": None, "letert": None}
    adat = jarmu.Extensions[JARMU_BOVITES]
    return {nev: getattr(adat, mezo) if adat.HasField(mezo) else None
            for nev, mezo in (("ajto_nyitva", "door_open"), ("megallo_tavolsag", "stop_distance"),
                              ("letert", "deviated"))}


def megallo_bovites(megallo):
    """Az élő feed külön menetrendi ideje. Ez nem az indulási becslés."""
    adat = megallo.Extensions[MEGALLO_BOVITES] if megallo.HasExtension(MEGALLO_BOVITES) else None
    return {nev: getattr(adat, mezo).time if adat is not None and getattr(adat, mezo).HasField("time") else None
            for nev, mezo in (("forras_tervezett_erkezes", "scheduled_arrival"),
                              ("forras_tervezett_indulas", "scheduled_departure"))}
