"""Named map regions: a bbox we extract road data for and build one graph from.

Add a region by adding a line here. Bboxes are (west, south, east, north) and
should leave ~15 km of margin around the trips you care about so that
alternate routes are not clipped.
"""
from __future__ import annotations

from pathlib import Path

from ..cases import data_dir

REGIONS: dict[str, tuple[float, float, float, float]] = {
    "atlanta": (-84.75, 33.50, -84.20, 34.05),
}


def region_dir(name: str) -> Path:
    return data_dir() / "regions" / name


def region_for(points: list[tuple[float, float]]) -> str:
    for name, (w, s, e, n) in REGIONS.items():
        if all(w <= lon <= e and s <= lat <= n for lat, lon in points):
            return name
    raise ValueError(f"no configured region covers {points}; add one to opennav/data/regions.py")
