"""Provider-neutral traffic analysis: congestion on roads, and plain-English notes."""

from __future__ import annotations

import re

from .models import CongestedSegment, Route, RouteResult
from .polyline import haversine_m, length_m

# "I-285 S", "US-41 S", "GA-280", "SR 3", "I-75 N/I-85 N"
_ROAD_RE = re.compile(r"\b(?:I|US|GA|SR|State Route)[- ]\d+[A-Z]?(?:\s(?:N|S|E|W)\b)?")
# "onto Lake Park Dr", "on Airport Blvd", "toward Cobb Pkwy"
_ONTO_RE = re.compile(r"\b(?:onto|on|Continue on|Merge onto)\s+([A-Z0-9][\w .'-]+?)(?:$|,|\.| toward| for| to\b)")

_TOWARD_RE = re.compile(r"\btoward\s+([A-Z0-9][\w .'-]+?)(?:$|,|/|\.)")


def road_from_instruction(text: str) -> str | None:
    """Best-effort main road name for a turn instruction."""
    m = _ROAD_RE.search(text)
    if m:
        return m.group(0)
    m = _ONTO_RE.search(text) or _TOWARD_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _nearest_step(route: Route, point: tuple[float, float]) -> int | None:
    best, best_d = None, float("inf")
    for i, step in enumerate(route.steps):
        for p in step.geometry[:: max(1, len(step.geometry) // 50)] + step.geometry[-1:]:
            d = haversine_m(p, point)
            if d < best_d:
                best, best_d = i, d
    return best


def assign_intervals(route: Route, intervals: list[tuple[int, int, str]]) -> list[tuple[int | None, str, float]]:
    """Map congested (start_point_idx, end_point_idx, level) intervals on route.geometry to steps.

    Returns (step_index, level, distance_m) for every SLOW / TRAFFIC_JAM interval.
    """
    out = []
    for start, end, level in intervals:
        if level not in ("SLOW", "TRAFFIC_JAM") or end <= start:
            continue
        pts = route.geometry[start : end + 1]
        out.append((_nearest_step(route, pts[len(pts) // 2]), level, length_m(pts)))
    return out


def congestion_from_intervals(route: Route, intervals: list[tuple[int, int, str]]) -> list[CongestedSegment]:
    """Named congested segments; adjacent segments on the same road and level are merged."""
    segs: list[CongestedSegment] = []
    for idx, level, dist in assign_intervals(route, intervals):
        road = route.steps[idx].road if idx is not None else None
        if segs and segs[-1].road == road and segs[-1].level == level:
            segs[-1].distance_m += dist
        else:
            segs.append(CongestedSegment(road=road, level=level, distance_m=dist))
    return segs


def distribute_delay(route: Route, intervals: list[tuple[int, int, str]]) -> None:
    """Estimate per-step traffic durations.

    Providers like Google give traffic-aware time only for the whole route; steps get
    free-flow times. We spread the route's traffic delay over steps in proportion to
    their congested distance (jams weigh 3x slowdowns), falling back to proportional
    scaling when no congestion data exists.
    """
    delay = route.traffic_delay_s
    if not delay or not route.steps:
        return
    weights = [0.0] * len(route.steps)
    for idx, level, dist in assign_intervals(route, intervals):
        if idx is not None:
            weights[idx] += dist * (3.0 if level == "TRAFFIC_JAM" else 1.0)
    if sum(weights) == 0:
        weights = [s.static_duration_s or 0.0 for s in route.steps]
    total = sum(weights) or 1.0
    # Step free-flow times rarely sum exactly to the route's; normalize so steps add up.
    step_static = sum(s.static_duration_s or 0.0 for s in route.steps)
    norm = (route.static_duration_s / step_static) if step_static and route.static_duration_s else 1.0
    for s, w in zip(route.steps, weights):
        s.duration_s = (s.static_duration_s or 0.0) * norm + delay * w / total


def _mi(m: float) -> str:
    return f"{m / 1609.344:.1f} mi"


def describe_route_traffic(route: Route) -> str | None:
    parts = []
    delay = route.traffic_delay_s
    if delay is not None:
        mins = round(delay / 60)
        parts.append("Traffic is light, no notable delay." if mins < 1 else f"Traffic adds about {mins} min vs free flow.")
    by_road: dict[tuple[str, str], float] = {}
    for c in route.congestion:
        key = (c.road or "unnamed road", c.level)
        by_road[key] = by_road.get(key, 0.0) + c.distance_m
    worst = sorted(by_road.items(), key=lambda kv: (kv[0][1] != "TRAFFIC_JAM", -kv[1]))[:3]
    if worst:
        desc = ", ".join(f"{'heavy traffic' if lvl == 'TRAFFIC_JAM' else 'slowdown'} on {road} ({_mi(d)})" for (road, lvl), d in worst)
        parts.append(desc[0].upper() + desc[1:] + ".")
    return " ".join(parts) or None


def compare_routes(result: RouteResult) -> str | None:
    """Explain why the recommended route won, e.g. "Fastest of 3 routes; avoids slowdown on I-285 S"."""
    if not result.routes:
        return None
    best = result.best
    if not result.alternates:
        return "Only one route returned."
    best_roads = {c.road for c in best.congestion}
    fastest = min(result.routes, key=lambda r: r.duration_s)
    head = f"Fastest of {len(result.routes)} routes" if fastest is best else f"Recommended of {len(result.routes)} routes"
    avoided: list[str] = []
    alt_bits = []
    for alt in result.alternates:
        diff = round((alt.duration_s - best.duration_s) / 60)
        alt_bits.append(f"via {alt.summary or 'alternate'} is {abs(diff)} min {'slower' if diff >= 0 else 'faster'}")
        for c in alt.congestion:
            if c.road and c.road not in best_roads and c.road not in avoided:
                avoided.append(c.road)
    note = head
    if avoided:
        note += f"; avoids slowdown on {', '.join(avoided[:2])}"
    return note + ". Alternates: " + "; ".join(alt_bits) + "."


def annotate(result: RouteResult) -> RouteResult:
    for r in result.routes:
        r.traffic_note = describe_route_traffic(r)
    result.comparison_note = compare_routes(result)
    return result
