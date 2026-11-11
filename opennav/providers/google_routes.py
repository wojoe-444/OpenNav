"""Google Maps Platform Routes API (computeRoutes) provider.

Used as ground truth while piloting. Docs:
https://developers.google.com/maps/documentation/routes/compute_route_directions
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from .. import polyline, traffic
from ..models import Route, RouteRequest, RouteResult, Step
from .base import ProviderError, RoutingProvider

ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"

FIELD_MASK = ",".join(
    [
        "routes.duration",
        "routes.staticDuration",
        "routes.distanceMeters",
        "routes.description",
        "routes.warnings",
        "routes.routeLabels",
        "routes.polyline.encodedPolyline",
        "routes.travelAdvisory",
        "routes.legs.startLocation",
        "routes.legs.endLocation",
        "routes.legs.steps.distanceMeters",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.navigationInstruction",
        "routes.legs.steps.polyline.encodedPolyline",
        "geocodingResults",
    ]
)


def _seconds(value: str | None) -> float | None:
    return float(value.rstrip("s")) if value else None


def _waypoint(text: str) -> dict[str, Any]:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            return {"location": {"latLng": {"latitude": lat, "longitude": lon}}}
        except ValueError:
            pass
    return {"address": text}


class GoogleRoutesProvider(RoutingProvider):
    name = "google"

    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
        self.session = session or requests.Session()

    def build_body(self, request: RouteRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "origin": _waypoint(request.origin),
            "destination": _waypoint(request.destination),
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
            "computeAlternativeRoutes": request.alternatives,
            "extraComputations": ["TRAFFIC_ON_POLYLINE"],
            "polylineQuality": "HIGH_QUALITY",
            "languageCode": "en-US",
            "units": "IMPERIAL",
        }
        if request.departure is not None:
            body["departureTime"] = request.departure.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return body

    def fetch_raw(self, request: RouteRequest) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("Set GOOGLE_MAPS_API_KEY (a key with the Routes API enabled).")
        body = self.build_body(request)
        resp = self.session.post(
            ENDPOINT,
            json=body,
            headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK},
            timeout=30,
        )
        if resp.status_code != 200:
            raise ProviderError(f"Routes API HTTP {resp.status_code}: {resp.text[:500]}")
        return {
            "provider": self.name,
            "endpoint": ENDPOINT,
            "field_mask": FIELD_MASK,
            "request_body": body,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "response": resp.json(),
        }

    def parse(self, request: RouteRequest, raw: dict[str, Any]) -> RouteResult:
        data = raw["response"]
        routes = [self._parse_route(r) for r in data.get("routes", [])]
        if not routes:
            raise ProviderError("Routes API returned no routes.")
        first_leg = data["routes"][0].get("legs", [{}])[0]

        def ll(loc: dict | None) -> str | None:
            if not loc:
                return None
            p = loc["latLng"]
            return f"{p['latitude']:.6f},{p['longitude']:.6f}"

        result = RouteResult(
            request=request,
            provider=self.name,
            routes=routes,
            origin_resolved=ll(first_leg.get("startLocation")),
            destination_resolved=ll(first_leg.get("endLocation")),
            fetched_at=datetime.fromisoformat(raw["fetched_at"]) if raw.get("fetched_at") else None,
        )
        return traffic.annotate(result)

    def _parse_route(self, r: dict[str, Any]) -> Route:
        geometry = polyline.decode(r.get("polyline", {}).get("encodedPolyline", ""))
        steps: list[Step] = []
        for leg in r.get("legs", []):
            for s in leg.get("steps", []):
                nav = s.get("navigationInstruction", {})
                # First line is the instruction; later lines are notes such as
                # "Restricted usage road" or "Destination will be on the right".
                lines = [ln.strip() for ln in nav.get("instructions", "").split("\n") if ln.strip()]
                text = lines[0] if lines else ""
                static = _seconds(s.get("staticDuration")) or 0.0
                steps.append(
                    Step(
                        instruction=text,
                        distance_m=float(s.get("distanceMeters", 0)),
                        duration_s=static,
                        static_duration_s=static,
                        maneuver=nav.get("maneuver"),
                        road=traffic.road_from_instruction(text),
                        notes=lines[1:],
                        geometry=polyline.decode(s.get("polyline", {}).get("encodedPolyline", "")),
                    )
                )
        route = Route(
            duration_s=_seconds(r.get("duration")) or 0.0,
            static_duration_s=_seconds(r.get("staticDuration")),
            distance_m=float(r.get("distanceMeters", 0)),
            summary=r.get("description", ""),
            labels=r.get("routeLabels", []),
            warnings=r.get("warnings", []),
            steps=steps,
            geometry=geometry,
        )
        intervals = [
            (int(i.get("startPolylinePointIndex", 0)), int(i.get("endPolylinePointIndex", 0)), i.get("speed", "NORMAL"))
            for i in r.get("travelAdvisory", {}).get("speedReadingIntervals", [])
        ]
        route.congestion = traffic.congestion_from_intervals(route, intervals)
        traffic.distribute_delay(route, intervals)
        return route
