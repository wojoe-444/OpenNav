"""Minimal open geocoder over Overture address points (OpenAddresses and other open sources).

Coverage is uneven: e.g. the City of Atlanta has address points, most of Cobb
County does not yet. When an address is not found, pass "lat,lon" instead.
"""
from __future__ import annotations

import re
from functools import lru_cache

import numpy as np
import pyarrow.parquet as pq

from .data.regions import REGIONS, region_dir

_ABBR = {"st": "street", "ave": "avenue", "rd": "road", "dr": "drive", "pkwy": "parkway", "ct": "court",
         "blvd": "boulevard", "ln": "lane", "pl": "place", "hwy": "highway", "cir": "circle", "trl": "trail",
         "n": "north", "s": "south", "e": "east", "w": "west", "ne": "northeast", "nw": "northwest",
         "se": "southeast", "sw": "southwest"}


def _norm(street: str) -> str:
    toks = re.sub(r"[^a-z0-9 ]", " ", street.lower()).split()
    return " ".join(_ABBR.get(t, t) for t in toks)


class OvertureGeocoder:
    def __init__(self, regions: list[str] | None = None):
        self.regions = regions or list(REGIONS)

    @lru_cache(maxsize=4)
    def _table(self, region: str):
        p = region_dir(region) / "addresses.parquet"
        if not p.exists():
            return None
        t = pq.read_table(p, columns=["number", "street", "postcode", "bbox"]).to_pydict()
        index: dict[tuple[str, str], list[tuple[float, float, str | None]]] = {}
        for num, st, pc, bb in zip(t["number"], t["street"], t["postcode"], t["bbox"]):
            if num and st:
                index.setdefault((num.strip(), _norm(st)), []).append((bb["ymin"], bb["xmin"], pc))
        return index

    def geocode(self, text: str) -> tuple[float, float] | None:
        m = re.match(r"\s*(\d+[A-Za-z]?)\s+([^,]+)(?:,(.*))?", text)
        if not m:
            return None
        num, street, rest = m.group(1), _norm(m.group(2)), m.group(3) or ""
        pc = re.search(r"\b(\d{5})\b", rest)
        for region in self.regions:
            idx = self._table(region)
            if not idx:
                continue
            hits = [h for (n, s), v in idx.items() if n == num and (s == street or s.startswith(street + " "))
                    for h in v]
            if pc:
                hits = [h for h in hits if h[2] == pc.group(1)] or []
            if hits:
                a = np.array([(h[0], h[1]) for h in hits])
                return float(a[:, 0].mean()), float(a[:, 1].mean())
        return None
