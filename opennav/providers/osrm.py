"""OSRM provider (OpenStreetMap-based, open source).

Works against any OSRM server, e.g. a local `osrm-routed` built from a Georgia
extract. OSRM has no live traffic and no geocoder, so:
  * origin/destination must be "lat,lon" for now (geocoding is a future plug-in);
  * duration is free-flow, and static_duration_s equals duration_s.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from .. import polyline, traffic
from ..models import Route, RouteRequest, RouteResult, Step
from .base import ProviderError, RoutingProvider


def _latlon(text: str) -> tuple[float, float]:
    try:
        lat, lon = (float(p) for p in text.split(","))
        return lat, lon
    except ValueError:
        raise ProviderError(f"OSRM needs 'lat,lon' coordinates (no geocoder yet), got {text!r}") from None


def _instruction(step: dict[str, Any]) -> str:
    m = step.get("maneuver", {})
    kind, mod = m.get("type", ""), m.get("modifier", "")
    road = step.get("ref") or step.get("name") or ""
    onto = f" onto {road}" if road else ""
    if kind == "depart":
        return f"Head {m.get('modifier') or 'out'}{' on ' + road if road else ''}"
    if kind == "arrive":
        return "Arrive at destination"
    if kind in ("on ramp", "off ramp"):
        return f"Take the ramp{' ' + mod if mod else ''}{onto}"
    if kind == "merge":
        return f"Merge{' ' + mod if mod else ''}{onto}"
    if kind in ("roundabout", "rotary"):
        return f"At the roundabout take exit {m.get('exit', '')}{onto}".replace("  ", " ")
    if kind in ("continue", "new name"):
        return f"Continue{onto}"
    if kind == "fork":
        return f"Keep {mod}{onto}"
    return f"{'Turn ' + mod if mod else kind.capitalize()}{onto}"


class OSRMProvider(RoutingProvider):
    name = "osrm"

    def __init__(self, base_url: str | None = None, profile: str = "driving", session: requests.Session | None = None):
        self.base_url = (base_url or os.environ.get("OSRM_URL") or "http://localhost:5000").rstrip("/")
        self.profile = profile
        self.session = session or requests.Session()

    def fetch_raw(self, request: RouteRequest) -> dict[str, Any]:
        (alat, alon), (blat, blon) = _latlon(request.origin), _latlon(request.destination)
        url = f"{self.base_url}/route/v1/{self.profile}/{alon},{alat};{blon},{blat}"
        params = {
            "alternatives": "true" if request.alternatives else "false",
            "steps": "true",
            "overview": "full",
            "geometries": "polyline6",
        }
        resp = self.session.get(url, params=params, timeout=30)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code != 200 or data.get("code") != "Ok":
            raise ProviderError(f"OSRM error {resp.status_code}: {data.get('message') or resp.text[:300]}")
        return {
            "provider": self.name,
            "url": url,
            "params": params,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "response": data,
        }

    def parse(self, request: RouteRequest, raw: dict[str, Any]) -> RouteResult:
        data = raw["response"]
        routes = []
        for r in data.get("routes", []):
            steps = []
            for leg in r.get("legs", []):
                for s in leg.get("steps", []):
                    text = _instruction(s)
                    steps.append(
                        Step(
                            instruction=text,
                            distance_m=float(s.get("distance", 0)),
                            duration_s=float(s.get("duration", 0)),
                            static_duration_s=float(s.get("duration", 0)),
                            maneuver=s.get("maneuver", {}).get("type"),
                            road=s.get("ref") or s.get("name") or None,
                            geometry=polyline.decode(s.get("geometry", ""), precision=6),
                        )
                    )
            summary = " and ".join(leg.get("summary", "") for leg in r.get("legs", []) if leg.get("summary"))
            routes.append(
                Route(
                    duration_s=float(r["duration"]),
                    static_duration_s=float(r["duration"]),
                    distance_m=float(r["distance"]),
                    summary=summary.replace(", ", " and "),
                    steps=steps,
                    geometry=polyline.decode(r.get("geometry", ""), precision=6),
                    warnings=["No live traffic: durations are free-flow estimates."],
                )
            )
        if not routes:
            raise ProviderError("OSRM returned no routes.")
        wps = data.get("waypoints", [])

        def wp(i: int) -> str | None:
            if len(wps) <= i:
                return None
            lon, lat = wps[i]["location"]
            name = wps[i].get("name")
            return f"{lat:.6f},{lon:.6f}" + (f" ({name})" if name else "")

        result = RouteResult(
            request=request,
            provider=self.name,
            routes=routes,
            origin_resolved=wp(0),
            destination_resolved=wp(1),
            fetched_at=datetime.fromisoformat(raw["fetched_at"]) if raw.get("fetched_at") else None,
        )
        return traffic.annotate(result)
