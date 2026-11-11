"""OpenNav's own router as a provider: OpenStreetMap roads (via Overture Maps),
turn-aware routing, a time-of-day traffic model, Google-style guidance.

Origin/destination: "lat,lon", or an address resolved by `opennav.geocode`
(Overture address points). Road data is downloaded and built once per region
into the local data dir (see `opennav data build`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from .. import polyline, traffic
from ..models import CongestedSegment, Route, RouteRequest, RouteResult, Step
from .base import ProviderError, RoutingProvider


def parse_latlon(text: str) -> tuple[float, float] | None:
    try:
        lat, lon = (float(p) for p in text.split(","))
        return lat, lon
    except ValueError:
        return None


class OpenNavProvider(RoutingProvider):
    name = "opennav"
    stores_responses = False  # our own answers are recomputed, never stored as ground truth

    def __init__(self, region: str | None = None, alternatives: int = 2, traffic_model: bool = True,
                 params=None, geocoder=None):
        self.region = region
        self.n_alternatives = alternatives
        self.traffic_model = traffic_model
        self.params = params
        self._geocoder = geocoder

    # ---- geocoding
    def resolve(self, text: str) -> tuple[float, float]:
        ll = parse_latlon(text)
        if ll:
            return ll
        if self._geocoder is None:
            from ..geocode import OvertureGeocoder
            self._geocoder = OvertureGeocoder()
        hit = self._geocoder.geocode(text)
        if hit is None:
            raise ProviderError(f"could not geocode {text!r}; pass 'lat,lon' instead")
        return hit

    def engine(self, points):
        from ..data.regions import region_for
        from ..engine import Engine
        eng = Engine.load(self.region or region_for(points))
        if self.params is not None and eng.model.p is not self.params:
            eng.model.p = self.params
            eng.model.recompute()
            eng.router.turn_route = eng.model.turn_costs(eng.router.t_in, eng.router.t_out, routing=True)
            eng.router._cache_key = None
        return eng

    # ---- RoutingProvider
    def fetch_raw(self, request: RouteRequest) -> dict[str, Any]:
        result = self.route(request)
        return {"provider": self.name, "fetched_at": datetime.now(timezone.utc).isoformat(),
                "result": result.to_dict()}

    def parse(self, request: RouteRequest, raw: dict[str, Any]) -> RouteResult:
        return RouteResult.from_dict(raw["result"], request=request)

    def route(self, request: RouteRequest) -> RouteResult:
        o = self.resolve(request.origin)
        d = self.resolve(request.destination)
        eng = self.engine([o, d])
        return self.route_points(eng, request, o, d)

    def route_points(self, eng, request: RouteRequest, o, d) -> RouteResult:
        from ..engine.guidance import Guidance, destination_side, warnings_for
        g, router = eng.graph, eng.router
        try:
            s = router.snap(*o)
            t = router.snap(*d)
        except ValueError as e:
            raise ProviderError(str(e)) from None
        n_alt = self.n_alternatives if request.alternatives else 0
        try:
            paths = router.search(s, t, request.departure, traffic=self.traffic_model, alternatives=n_alt)
        except ValueError as e:
            raise ProviderError(str(e)) from None
        guide = Guidance(g)
        factor = eng.model.traffic_factor(request.departure) if self.traffic_model else None
        routes, run_lists = [], []
        for p in paths:
            times, turns = router.path_times(p)
            free = router.path_free_times(p)
            lengths = g.length_m[p.edges].copy()
            lengths[0] *= (1 - p.start_frac)
            lengths[-1] *= p.end_frac if len(p.edges) > 1 else (p.end_frac - p.start_frac)
            edge_t = times + turns
            edge_static = free + turns
            side = destination_side(g, p.edges[-1], d[0], d[1], t.lat, t.lon)
            steps = guide.steps(p.edges, edge_t, edge_static, lengths, dest_side=side)
            runs = guide.last_runs
            total = float(lengths.sum())
            summary, shares = guide.summary(runs, total)
            geom = [(s.lat, s.lon)]
            for e in p.edges:
                geom += [(float(a), float(b)) for a, b in g.edge_geom(e)]
            geom.append((t.lat, t.lon))
            r = Route(
                duration_s=float(edge_t.sum()), static_duration_s=float(edge_static.sum()),
                distance_m=total, summary=summary, warnings=warnings_for(g, p.edges),
                steps=steps, geometry=geom,
            )
            if factor is not None:
                r.congestion = _congestion(g, p.edges, factor, guide, runs)
            routes.append(r)
            run_lists.append(shares)
        order = sorted(range(len(routes)), key=lambda i: routes[i].duration_s)
        routes = [routes[i] for i in order]
        run_lists = [run_lists[i] for i in order]
        _disambiguate(routes, run_lists)
        for i, r in enumerate(routes):
            r.labels = ["DEFAULT_ROUTE"] if i == 0 else ["DEFAULT_ROUTE_ALTERNATE"]
        result = RouteResult(
            request=request, provider=self.name, routes=routes,
            origin_resolved=f"{o[0]:.6f},{o[1]:.6f}", destination_resolved=f"{d[0]:.6f},{d[1]:.6f}",
            fetched_at=datetime.now(timezone.utc),
        )
        return traffic.annotate(result)


def _congestion(g, edges, factor, guide, runs) -> list[CongestedSegment]:
    out = []
    road_of = {}
    for r in runs:
        for e in r.edges:
            road_of[e] = r.label or None
    for e in edges:
        f = factor[e]
        level = "TRAFFIC_JAM" if f >= 1.8 else ("SLOW" if f >= 1.3 else None)
        if level is None:
            continue
        road = road_of.get(e)
        if out and out[-1].road == road and out[-1].level == level:
            out[-1].distance_m += float(g.length_m[e])
        else:
            out.append(CongestedSegment(road=road, level=level, distance_m=float(g.length_m[e])))
    return [c for c in out if c.distance_m >= 400]


def _disambiguate(routes: list[Route], shares: list[dict[str, float]]) -> None:
    """Google names alternates by what sets them apart: if two summaries collide,
    prefix the longest road that this route uses and the other does not."""
    for i, r in enumerate(routes):
        clash = [j for j in range(len(routes)) if j != i and routes[j].summary == r.summary]
        if not clash:
            continue
        if i == min([i] + clash):
            continue  # the faster route keeps the plain name
        others = set().union(*(shares[j].keys() for j in clash))
        own = [(k, v) for k, v in shares[i].items() if k not in others and k not in r.summary]
        if own:
            k = max(own, key=lambda kv: kv[1])[0]
            r.summary = f"{k}, {r.summary}"
