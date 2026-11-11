"""Car cost model: free-flow speeds, intersection/turn delays and a time-of-day traffic model.

Every number lives in `Params` so the calibration step (`opennav calibrate`)
can fit them against ground truth and save them to `opennav/engine/params.json`.

Traffic model (no live feed yet): a historical-style congestion factor per edge,

    factor = 1 + peak(hour, weekday) * class_weight[cls] * urban(edge) * (1 + dir_weight * radial(edge, hour))

- peak(): weekday AM/PM rush-hour bumps, small midday/weekend level
- urban(): how deep the edge is in the metro (road density around it,
  normalised so the densest area of the graph is 1)
- radial(): +1 when the edge heads toward the metro core in the morning
  (or away from it in the evening), -1 for the opposite direction, 0 for
  circumferential roads. This is the classic commuter tidal flow.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .graph import (CLASSES, F_LINK, F_PARKING, F_RESTRICTED, LIVING, MOTORWAY, PRIMARY, RESIDENTIAL,
                    SECONDARY, SERVICE, TERTIARY, TRUNK, UNCLASSIFIED, UNKNOWN, RoadGraph, bearing, haversine)

PARAMS_PATH = Path(__file__).with_name("params.json")


@dataclass
class Params:
    # default speed limits (km/h) when the map has none, by class
    default_limit_kph: dict = field(default_factory=lambda: {
        "motorway": 104.6, "trunk": 88.5, "primary": 72.4, "secondary": 64.4, "tertiary": 56.3,
        "unclassified": 48.3, "residential": 40.2, "living_street": 24.1, "service": 24.1, "unknown": 32.2})
    # time multiplier on "length / speed limit", by edge group (1 / fraction of the limit driven).
    # Groups are the road classes plus "link" (ramps) and "restricted" (gated/private roads).
    time_factor: dict = field(default_factory=lambda: {
        "motorway": 1.05, "trunk": 1.1, "primary": 1.2, "secondary": 1.2, "tertiary": 1.2,
        "unclassified": 1.25, "residential": 1.35, "living_street": 1.4, "service": 1.6, "unknown": 1.6,
        "link": 1.3, "restricted": 1.6})
    # extra seconds per km on arterials: signals and driveways spread along the road
    delay_s_per_km: dict = field(default_factory=lambda: {
        "trunk": 10.0, "primary": 25.0, "secondary": 25.0, "tertiary": 15.0})
    link_limit_kph: float = 72.0        # ramps without a posted limit
    parking_speed_kph: float = 12.0
    restricted_penalty_s: float = 60.0  # discourage through-traffic on private/destination roads
    # intersection delays (seconds)
    signal_delay_s: float = 18.0        # expected wait at a likely signal (major x major)
    minor_cross_delay_s: float = 3.0    # crossing / passing a minor road
    stop_delay_s: float = 8.0           # minor road entering a major road
    turn_left_s: float = 12.0
    turn_right_s: float = 5.0
    turn_sharp_s: float = 6.0
    uturn_s: float = 60.0
    merge_s: float = 2.0
    # traffic
    am_peak_hour: float = 8.0
    pm_peak_hour: float = 17.5
    peak_width_h: float = 1.4
    am_amplitude: float = 1.0
    pm_amplitude: float = 1.1
    offpeak_level: float = 0.15
    weekend_scale: float = 0.35
    class_weight: dict = field(default_factory=lambda: {
        "motorway": 0.35, "trunk": 0.3, "primary": 0.25, "secondary": 0.2, "tertiary": 0.15,
        "unclassified": 0.05, "residential": 0.03, "living_street": 0.0, "service": 0.0, "unknown": 0.05})
    dir_weight: float = 0.6
    urban_radius_m: float = 1500.0
    urban_gamma: float = 1.0
    core_falloff_km: float = 25.0

    @classmethod
    def load(cls, path: Path = PARAMS_PATH) -> "Params":
        if path.exists():
            data = json.loads(path.read_text())
            p = cls()
            for k, v in data.items():
                if hasattr(p, k):
                    if isinstance(getattr(p, k), dict):
                        getattr(p, k).update(v)
                    else:
                        setattr(p, k, v)
            return p
        return cls()

    def save(self, path: Path = PARAMS_PATH) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")


MAJOR = {MOTORWAY, TRUNK, PRIMARY, SECONDARY, TERTIARY}
ARTERIAL = {TRUNK, PRIMARY, SECONDARY, TERTIARY}


def _vec(d: dict, default: float = 0.0) -> np.ndarray:
    return np.array([float(d.get(c, default)) for c in CLASSES])


class CostModel:
    """Precomputes per-edge free-flow times and per-node context for a graph."""

    def __init__(self, g: RoadGraph, params: Params | None = None):
        self.g = g
        self.p = params or Params.load()
        self._urban = None
        self._core = None
        self.recompute()

    def recompute(self) -> None:
        g, p = self.g, self.p
        F = self.features()
        self.free_time = F @ self.feature_weights()
        self.speed_mps = g.length_m / self.free_time
        self._node_context()

    GROUPS = CLASSES + ["link", "restricted"]
    DELAY_GROUPS = ["trunk", "primary", "secondary", "tertiary"]

    def edge_group(self) -> np.ndarray:
        g = self.g
        grp = g.cls.astype(np.int64).copy()
        grp[(g.flags & F_LINK) > 0] = len(CLASSES)
        grp[(g.flags & F_RESTRICTED) > 0] = len(CLASSES) + 1
        return grp

    def features(self) -> np.ndarray:
        """Linear features of free-flow edge time: seconds at the limit per group, km per delay group,
        and parking-aisle seconds. free_time = features @ feature_weights."""
        g, p = self.g, self.p
        link = (g.flags & F_LINK) > 0
        limit = np.where(np.isnan(g.speed_limit_kph), _vec(p.default_limit_kph)[g.cls], g.speed_limit_kph)
        limit = np.where(link & np.isnan(g.speed_limit_kph), p.link_limit_kph, limit)
        t_limit = g.length_m / (limit / 3.6)
        grp = self.edge_group()
        parking = (g.flags & F_PARKING) > 0
        n = g.n_edges
        F = np.zeros((n, len(self.GROUPS) + len(self.DELAY_GROUPS) + 1))
        F[np.arange(n), grp] = np.where(parking, 0.0, t_limit)
        for j, c in enumerate(self.DELAY_GROUPS):
            m = (g.cls == CLASSES.index(c)) & ~link
            F[m, len(self.GROUPS) + j] = g.length_m[m] / 1000.0
        F[:, -1] = np.where(parking, g.length_m / (p.parking_speed_kph / 3.6), 0.0)
        return F

    def feature_weights(self) -> np.ndarray:
        p = self.p
        return np.array([p.time_factor[k] for k in self.GROUPS]
                        + [p.delay_s_per_km.get(k, 0.0) for k in self.DELAY_GROUPS] + [1.0])

    # ---- node context: degree and road importance, for intersection delays
    def _node_context(self) -> None:
        """Per node: number of distinct roads (by name/ref, excluding driveways and
        parking aisles) and number of distinct arterial roads meeting there."""
        g = self.g
        n = g.n_nodes
        ident = np.where(g.name_idx >= 0, g.name_idx, np.where(g.ref_idx >= 0, 10_000_000 + g.ref_idx,
                                                               20_000_000 + g.seg_idx)).astype(np.int64)
        real = (g.cls <= LIVING) | ((g.cls == SERVICE) & ((g.flags & F_PARKING) == 0) & (g.name_idx >= 0))
        real &= (g.flags & F_LINK) == 0
        arterial = real & (g.cls <= TERTIARY) & (g.cls != MOTORWAY)
        nodes = np.concatenate([g.src, g.dst]).astype(np.int64)
        ids = np.concatenate([ident, ident])
        def count(mask2):
            pairs = np.unique(nodes[mask2] * 40_000_000 + ids[mask2])
            return np.bincount((pairs // 40_000_000).astype(np.int64), minlength=n)
        self.node_roads = count(np.concatenate([real, real]))
        self.node_arterials = count(np.concatenate([arterial, arterial]))
        # links meeting non-link roads count as a road too (ramp terminals)
        link = (g.flags & F_LINK) > 0
        lk = np.zeros(n, dtype=np.int64)
        np.add.at(lk, g.src[link], 1)
        np.add.at(lk, g.dst[link], 1)
        self.node_roads = self.node_roads + (lk > 0)
        self.node_arterials = self.node_arterials + ((lk > 0) & (self.node_arterials >= 1))

    # ---- urban intensity and core, for the traffic model
    def urban(self) -> np.ndarray:
        if self._urban is None:
            g, p = self.g, self.p
            mid = g.geom[(g.geom_off[:-1] + g.geom_off[1:]) // 2]
            lat0 = float(np.median(g.node_lat))
            kx = 111320.0 * math.cos(math.radians(lat0))
            ky = 110540.0
            cell = p.urban_radius_m
            # density of major-road length on a grid
            major = np.isin(g.cls, list(MAJOR))
            gx = np.floor(mid[:, 1] * kx / cell).astype(np.int64)
            gy = np.floor(mid[:, 0] * ky / cell).astype(np.int64)
            dens = {}
            for x, y, L in zip(gx[major], gy[major], g.length_m[major]):
                dens[(x, y)] = dens.get((x, y), 0.0) + L
            # 3x3 smoothing
            sm = {}
            for (x, y) in dens:
                sm[(x, y)] = sum(dens.get((x + dx, y + dy), 0.0) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            top = max(sm.values())
            vals = np.array([sm.get((x, y), 0.0) for x, y in zip(gx, gy)]) / top
            self._urban = np.clip(vals, 0, 1) ** p.urban_gamma
            (cx, cy) = max(sm, key=sm.get)
            self._core = ((cy + 0.5) * cell / ky, (cx + 0.5) * cell / kx)
        return self._urban

    @property
    def core(self) -> tuple[float, float]:
        self.urban()
        return self._core

    def peak(self, when: datetime | None) -> tuple[float, float]:
        """(am_level, pm_level) congestion intensities for a departure time."""
        p = self.p
        if when is None:
            when = datetime.now()
        h = when.hour + when.minute / 60.0
        am = p.am_amplitude * math.exp(-0.5 * ((h - p.am_peak_hour) / p.peak_width_h) ** 2)
        pm = p.pm_amplitude * math.exp(-0.5 * ((h - p.pm_peak_hour) / p.peak_width_h) ** 2)
        scale = p.weekend_scale if when.weekday() >= 5 else 1.0
        return scale * (am + p.offpeak_level), scale * pm

    def traffic_factor(self, when: datetime | None) -> np.ndarray:
        g, p = self.g, self.p
        am, pm = self.peak(when)
        urban = self.urban()
        if getattr(self, "_geo_cache", None) is None:
            clat, clon = self.core
            mid = g.geom[(g.geom_off[:-1] + g.geom_off[1:]) // 2]
            to_core = bearing(mid[:, 0], mid[:, 1], clat, clon)
            heading = bearing(g.geom[g.geom_off[:-1], 0], g.geom[g.geom_off[:-1], 1],
                              g.geom[g.geom_off[1:] - 1, 0], g.geom[g.geom_off[1:] - 1, 1])
            self._geo_cache = (np.cos(np.radians(heading - to_core)),
                               haversine(mid[:, 0], mid[:, 1], clat, clon) / 1000.0)
        inbound, dist_core = self._geo_cache
        falloff = np.exp(-dist_core / p.core_falloff_km)
        radial = (am * inbound - pm * inbound)  # AM inbound positive, PM outbound positive
        level = am + pm
        cw = _vec(p.class_weight)[g.cls]
        f = 1.0 + cw * urban * (level + p.dir_weight * radial * falloff)
        return np.clip(f, 0.8, 4.0)

    def edge_times(self, when: datetime | None, traffic: bool = True) -> np.ndarray:
        t = self.free_time.copy()
        if traffic:
            t = t * self.traffic_factor(when)
        return t

    # ---- turn / intersection cost between consecutive edges at node v
    TURN_COMPONENTS = ("turn_left_s", "turn_right_s", "turn_sharp_s", "uturn_s", "signal_delay_s",
                       "stop_delay_s", "minor_cross_delay_s", "merge_s")

    def turn_components(self, e_in: np.ndarray, e_out: np.ndarray) -> np.ndarray:
        """0/1 matrix (n, len(TURN_COMPONENTS)): which delay types apply to each turn."""
        g = self.g
        ang = (g.bearing_start[e_out] - g.bearing_end[e_in] + 540.0) % 360.0 - 180.0  # + = right
        a = np.abs(ang)
        v = g.dst[e_in]
        cin, cout = g.cls[e_in], g.cls[e_out]
        lin = (g.flags[e_in] & F_LINK) > 0
        lout = (g.flags[e_out] & F_LINK) > 0
        roads = self.node_roads[v]
        art = self.node_arterials[v]
        is_int = roads >= 2
        first = g.length_m[e_in] > 15.0  # second node of a divided-road crossing does not count again
        C = np.zeros((len(e_in), len(self.TURN_COMPONENTS)))
        C[:, 0] = is_int & (ang < -45) & (a < 150)
        C[:, 1] = is_int & (ang > 45) & (a < 150)
        C[:, 2] = is_int & (a >= 120) & (a < 170)
        C[:, 3] = a >= 170
        free = (cin == MOTORWAY) | (cout == MOTORWAY) | (lin & lout) | (lin & (a < 45))
        arterial_in = (cin <= TERTIARY) & ~lin
        arterial_out = (cout <= TERTIARY) & ~lout
        signal = ~free & first & (art >= 2) & (arterial_in | arterial_out | lin)
        C[:, 4] = signal
        stop = ~free & ~signal & is_int & (cin > TERTIARY) & arterial_out
        C[:, 5] = stop
        C[:, 6] = ~free & ~signal & ~stop & is_int & first
        C[:, 7] = lin & (cout == MOTORWAY) & ~lout
        return C

    def turn_costs(self, e_in: np.ndarray, e_out: np.ndarray, routing: bool = True) -> np.ndarray:
        """Seconds spent at the node between e_in and e_out. routing=True adds
        avoidance penalties that steer the search but are not real time."""
        g, p = self.g, self.p
        w = np.array([getattr(p, k) for k in self.TURN_COMPONENTS])
        cost = self.turn_components(e_in, e_out) @ w
        if routing:
            cost += np.where(((g.flags[e_out] & F_RESTRICTED) > 0) & ((g.flags[e_in] & F_RESTRICTED) == 0),
                             p.restricted_penalty_s, 0.0)
        return cost
