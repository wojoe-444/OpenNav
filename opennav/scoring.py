"""Score a routing result against ground truth (e.g. a stored Google Routes response).

Every metric is in [0, 1] (1 = identical) and the case score is a weighted
average scaled to 0-100. Metrics are chosen to reflect what a user sees:

  route_overlap   share of Google's recommended path that ours also drives (F1 of
                  both directions, 25 m buffer)
  duration        traffic-aware travel time, full marks within 2 %, zero at 25 % off
  static_duration free-flow time, same scale
  distance        full marks within 1 %, zero at 10 % off
  summary         road summary ("I-285 W"), token match after normalisation
  steps           sequence similarity of the roads named in the step list,
                  blended with maneuver agreement and step-count ratio
  warnings        Jaccard of route warnings (highway, restricted roads)
  alternates      for every Google route, best overlap with any of our routes
  ranking         did we pick the same route as best, and order alternates alike

Adding a case = adding cases/<id>.json and storing one Google response for it.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import numpy as np
from scipy.spatial import cKDTree

from .models import Route, RouteResult

WEIGHTS = {
    "route_overlap": 20,
    "duration": 20,
    "static_duration": 5,
    "distance": 10,
    "summary": 10,
    "steps": 15,
    "warnings": 5,
    "alternates": 10,
    "ranking": 5,
}


def _xy(points: list[tuple[float, float]]) -> np.ndarray:
    if not points:
        return np.zeros((0, 2))
    a = np.asarray(points, dtype=float)
    lat0 = float(a[:, 0].mean())
    return np.c_[a[:, 0] * 110540.0, a[:, 1] * 111320.0 * math.cos(math.radians(lat0))]


def _densify(xy: np.ndarray, step: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Points every `step` metres along a polyline, plus the length each point stands for."""
    if len(xy) < 2:
        return xy, np.ones(len(xy))
    pts, w = [], []
    for a, b in zip(xy[:-1], xy[1:]):
        d = float(np.hypot(*(b - a)))
        n = max(1, int(math.ceil(d / step)))
        t = (np.arange(n) + 0.5) / n
        pts.append(a + (b - a) * t[:, None])
        w.append(np.full(n, d / n))
    return np.concatenate(pts), np.concatenate(w)


def coverage(a: list[tuple[float, float]], b: list[tuple[float, float]], buffer_m: float = 25.0) -> float:
    """Share of polyline a's length lying within buffer_m of polyline b."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    lat0 = np.mean([p[0] for p in a])
    k = (110540.0, 111320.0 * math.cos(math.radians(lat0)))
    xa = np.asarray(a) * k
    xb = np.asarray(b) * k
    pa, wa = _densify(xa)
    pb, _ = _densify(xb, step=5.0)
    d, _ = cKDTree(pb).query(pa, distance_upper_bound=buffer_m)
    return float(wa[np.isfinite(d)].sum() / wa.sum())


def overlap(a: Route, b: Route) -> float:
    """Symmetric path overlap (F1 of the two coverages)."""
    ca, cb = coverage(a.geometry, b.geometry), coverage(b.geometry, a.geometry)
    return 0.0 if ca + cb == 0 else 2 * ca * cb / (ca + cb)


def rel_score(actual: float, expected: float, full: float, zero: float) -> float:
    if not expected:
        return 0.0
    err = abs(actual - expected) / expected
    if err <= full:
        return 1.0
    return max(0.0, 1.0 - (err - full) / (zero - full))


_DIRS = {"n", "s", "e", "w", "ne", "nw", "se", "sw", "north", "south", "east", "west",
         "northeast", "northwest", "southeast", "southwest"}
_ABBR = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "parkway": "pkwy", "court": "ct",
         "boulevard": "blvd", "lane": "ln", "place": "pl", "highway": "hwy", "freeway": "fwy", "circle": "cir"}


def norm_road(text: str | None) -> str:
    """'US-41 S/Cobb Pkwy' -> 'us-41 cobb pkwy'; 'Hillsdale Parkway Southeast' -> 'hillsdale pkwy'."""
    if not text:
        return ""
    t = text.lower().replace("/", " ").replace(",", " ")
    toks = [_ABBR.get(w, w) for w in t.split()]
    # drop cardinal suffixes and route directions, keep leading directional names ("s terminal pkwy")
    out = [w for i, w in enumerate(toks) if not (w in _DIRS and i > 0)]
    return " ".join(out)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9\-\.]+", norm_road(text)))


def summary_score(a: str, b: str) -> float:
    ta, tb = _tokens(a) - {"and"}, _tokens(b) - {"and"}
    if not ta and not tb:
        return 1.0
    if norm_road(a) == norm_road(b):
        return 1.0
    return len(ta & tb) / len(ta | tb)


def step_roads(route: Route) -> list[str]:
    from .traffic import road_from_instruction
    out = []
    for s in route.steps:
        road = s.road or road_from_instruction(s.instruction) or ""
        n = norm_road(road)
        if n and (not out or out[-1] != n):
            out.append(n)
    return out


def _road_match(a: str, b: str) -> bool:
    ta, tb = set(a.split()), set(b.split())
    return bool(ta & tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def steps_score(ours: Route, truth: Route) -> dict[str, float]:
    ra, rb = step_roads(ours), step_roads(truth)
    # fuzzy LCS over road sequences
    n, m = len(ra), len(rb)
    dp = np.zeros((n + 1, m + 1))
    for i in range(n):
        for j in range(m):
            dp[i + 1, j + 1] = dp[i, j] + 1 if _road_match(ra[i], rb[j]) else max(dp[i, j + 1], dp[i + 1, j])
    road_seq = 2 * dp[n, m] / (n + m) if n + m else 1.0
    count = min(len(ours.steps), len(truth.steps)) / max(len(ours.steps), len(truth.steps), 1)
    ma = [_man_family(s.maneuver) for s in ours.steps]
    mb = [_man_family(s.maneuver) for s in truth.steps]
    man = SequenceMatcher(a=ma, b=mb, autojunk=False).ratio()
    return {"steps_roads": road_seq, "steps_count": count, "steps_maneuvers": man,
            "steps": 0.6 * road_seq + 0.2 * count + 0.2 * man}


def _man_family(m: str | None) -> str:
    m = (m or "").upper()
    for k in ("RAMP", "MERGE", "FORK", "UTURN", "ROUNDABOUT", "DEPART"):
        if k in m:
            return k
    if "LEFT" in m:
        return "LEFT"
    if "RIGHT" in m:
        return "RIGHT"
    return "STRAIGHT"


def jaccard(a: list[str], b: list[str]) -> float:
    sa = {x.lower().rstrip(".") for x in a}
    sb = {x.lower().rstrip(".") for x in b}
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class RouteMatch:
    truth_index: int
    ours_index: int | None
    overlap: float
    duration_err: float | None
    truth_summary: str
    ours_summary: str | None


@dataclass
class Score:
    total: float
    metrics: dict[str, float]
    details: dict = field(default_factory=dict)
    matches: list[RouteMatch] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"total": round(self.total, 1), "metrics": {k: round(v, 3) for k, v in self.metrics.items()},
                "details": self.details,
                "matches": [m.__dict__ for m in self.matches]}


def score(ours: RouteResult, truth: RouteResult) -> Score:
    ob, tb = ours.best, truth.best
    m: dict[str, float] = {}
    m["route_overlap"] = overlap(ob, tb)
    m["duration"] = rel_score(ob.duration_s, tb.duration_s, 0.02, 0.25)
    m["static_duration"] = (rel_score(ob.static_duration_s, tb.static_duration_s, 0.02, 0.25)
                            if ob.static_duration_s and tb.static_duration_s else 0.0)
    m["distance"] = rel_score(ob.distance_m, tb.distance_m, 0.01, 0.10)
    m["summary"] = summary_score(ob.summary, tb.summary)
    m.update(steps_score(ob, tb))
    m["warnings"] = jaccard(ob.warnings, tb.warnings)

    # match every truth route to our most-overlapping route
    matches = []
    ov = np.array([[overlap(o, t) for o in ours.routes] for t in truth.routes])
    for ti, t in enumerate(truth.routes):
        oi = int(np.argmax(ov[ti])) if len(ours.routes) else None
        o = ours.routes[oi] if oi is not None else None
        matches.append(RouteMatch(ti, oi if o and ov[ti, oi] >= 0.5 else None, float(ov[ti, oi]) if o else 0.0,
                                  (o.duration_s - t.duration_s) / t.duration_s if o else None,
                                  t.summary, o.summary if o else None))
    m["alternates"] = float(np.mean([x.overlap for x in matches])) if matches else 0.0
    # ranking: best-route agreement plus order agreement of matched routes
    same_best = 1.0 if matches and matches[0].ours_index == 0 else 0.0
    order = [x.ours_index for x in matches if x.ours_index is not None]
    pairs = [(i, j) for i in range(len(order)) for j in range(i + 1, len(order))]
    concord = (sum(order[i] < order[j] for i, j in pairs) / len(pairs)) if pairs else 1.0
    m["ranking"] = 0.7 * same_best + 0.3 * concord
    total = 100 * sum(WEIGHTS[k] * m[k] for k in WEIGHTS) / sum(WEIGHTS.values())
    details = {
        "duration_min": [round(ob.duration_s / 60, 1), round(tb.duration_s / 60, 1)],
        "static_min": [round((ob.static_duration_s or 0) / 60, 1), round((tb.static_duration_s or 0) / 60, 1)],
        "distance_mi": [round(ob.distance_mi, 2), round(tb.distance_mi, 2)],
        "summary": [ob.summary, tb.summary],
        "steps": [len(ob.steps), len(tb.steps)],
        "routes": [len(ours.routes), len(truth.routes)],
    }
    return Score(total=total, metrics=m, details=details, matches=matches)


def format_score(case_id: str, s: Score) -> str:
    lines = [f"{case_id}: {s.total:.1f} / 100"]
    d = s.details
    lines.append(f"  duration   ours {d['duration_min'][0]} min  vs google {d['duration_min'][1]} min"
                 f"   (free-flow {d['static_min'][0]} vs {d['static_min'][1]})")
    lines.append(f"  distance   ours {d['distance_mi'][0]} mi  vs google {d['distance_mi'][1]} mi")
    lines.append(f"  summary    ours {d['summary'][0]!r}  vs google {d['summary'][1]!r}")
    lines.append(f"  steps      ours {d['steps'][0]}  vs google {d['steps'][1]};  routes ours {d['routes'][0]} vs google {d['routes'][1]}")
    lines.append("  metrics    " + ", ".join(f"{k} {v:.2f}" for k, v in s.metrics.items()))
    for mt in s.matches:
        tag = "best" if mt.truth_index == 0 else f"alt {mt.truth_index}"
        if mt.ours_index is None:
            lines.append(f"  google {tag} ({mt.truth_summary}): not found (best overlap {mt.overlap:.0%})")
        else:
            otag = "best" if mt.ours_index == 0 else f"alt {mt.ours_index}"
            lines.append(f"  google {tag} ({mt.truth_summary}) -> ours {otag} ({mt.ours_summary}), "
                         f"overlap {mt.overlap:.0%}, time {mt.duration_err:+.0%}")
    return "\n".join(lines)
