"""Encoded polyline format (Google / OSRM), plus small geometry helpers."""

from __future__ import annotations

import math


def decode(encoded: str, precision: int = 5) -> list[tuple[float, float]]:
    factor = 10**precision
    coords: list[tuple[float, float]] = []
    index = lat = lon = 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        coords.append((lat / factor, lon / factor))
    return coords


def encode(coords: list[tuple[float, float]], precision: int = 5) -> str:
    factor = 10**precision
    out: list[str] = []
    prev_lat = prev_lon = 0
    for lat, lon in coords:
        ilat, ilon = round(lat * factor), round(lon * factor)
        for delta in (ilat - prev_lat, ilon - prev_lon):
            v = ~(delta << 1) if delta < 0 else delta << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lon = ilat, ilon
    return "".join(out)


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371008.8
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def length_m(coords: list[tuple[float, float]]) -> float:
    return sum(haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1))
