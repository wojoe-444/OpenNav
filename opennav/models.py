"""Provider-neutral data model for a routing query and its answer.

Every routing backend (Google Routes API today, OSRM / Valhalla / GraphHopper
later) maps its response into these types, so rendering, comparison and
traffic analysis never depend on a specific provider.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

METERS_PER_MILE = 1609.344


@dataclass
class RouteRequest:
    origin: str  # free-text address or "lat,lon"
    destination: str
    departure: datetime | None = None  # timezone-aware; None means "now"
    alternatives: bool = True


@dataclass
class Step:
    instruction: str
    distance_m: float
    duration_s: float  # best estimate for this step (traffic-scaled when available)
    static_duration_s: float | None = None  # free-flow duration, if provider gives it
    maneuver: str | None = None
    road: str | None = None
    notes: list[str] = field(default_factory=list)  # extra lines, e.g. "Restricted usage road"
    geometry: list[tuple[float, float]] = field(default_factory=list)  # (lat, lon)


@dataclass
class CongestedSegment:
    road: str | None
    level: str  # "SLOW" or "TRAFFIC_JAM"
    distance_m: float


@dataclass
class Route:
    duration_s: float  # with traffic, when the provider models it
    distance_m: float
    summary: str  # main roads used, e.g. "I-75 S and I-85 S"
    static_duration_s: float | None = None  # free-flow duration
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    geometry: list[tuple[float, float]] = field(default_factory=list)
    congestion: list[CongestedSegment] = field(default_factory=list)
    traffic_note: str | None = None

    @property
    def traffic_delay_s(self) -> float | None:
        if self.static_duration_s is None:
            return None
        return max(0.0, self.duration_s - self.static_duration_s)

    @property
    def distance_mi(self) -> float:
        return self.distance_m / METERS_PER_MILE


@dataclass
class RouteResult:
    request: RouteRequest
    provider: str
    routes: list[Route]  # routes[0] is the recommended route, the rest are alternates
    origin_resolved: str | None = None
    destination_resolved: str | None = None
    fetched_at: datetime | None = None
    comparison_note: str | None = None  # e.g. "Fastest of 3 routes; avoids slowdown on I-285 S"

    @property
    def best(self) -> Route:
        return self.routes[0]

    @property
    def alternates(self) -> list[Route]:
        return self.routes[1:]

    def to_dict(self, include_geometry: bool = True) -> dict[str, Any]:
        from . import polyline

        def route_dict(r: Route) -> dict[str, Any]:
            d = asdict(r)
            d["distance_mi"] = round(r.distance_mi, 2)
            d["traffic_delay_s"] = r.traffic_delay_s
            for s in d["steps"]:
                s["distance_mi"] = round(s["distance_m"] / METERS_PER_MILE, 2)
                s.pop("geometry")
            d.pop("geometry")
            if include_geometry:
                d["encoded_polyline"] = polyline.encode(r.geometry)
            return d

        req = asdict(self.request)
        req["departure"] = self.request.departure.isoformat() if self.request.departure else None
        return {
            "provider": self.provider,
            "request": req,
            "origin_resolved": self.origin_resolved,
            "destination_resolved": self.destination_resolved,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "comparison_note": self.comparison_note,
            "routes": [route_dict(r) for r in self.routes],
        }
