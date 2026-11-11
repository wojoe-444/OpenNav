"""Output formats: a Maps-style text panel, GeoJSON, and a standalone HTML map."""

from __future__ import annotations

import json

from .models import METERS_PER_MILE, Route, RouteResult


def fmt_duration(seconds: float) -> str:
    mins = round(seconds / 60)
    if mins < 60:
        return f"{mins} min"
    h, m = divmod(mins, 60)
    return f"{h} hr {m} min" if m else f"{h} hr"


def fmt_distance(meters: float) -> str:
    mi = meters / METERS_PER_MILE
    if mi < 0.1:
        return f"{round(meters * 3.28084 / 10) * 10:.0f} ft"
    return f"{mi:.1f} mi"


def _route_header(r: Route) -> list[str]:
    lines = [f"{fmt_duration(r.duration_s)} ({r.distance_mi:.1f} miles)"]
    if r.summary:
        lines.append(f"via {r.summary}")
    if r.traffic_note:
        lines.append(r.traffic_note)
    for w in r.warnings:
        lines.append(f"! {w}")
    return lines


def to_text(result: RouteResult, show_steps: bool = True) -> str:
    req = result.request
    when = req.departure.strftime("%a %b %d %Y, %I:%M %p %Z") if req.departure else "now"
    out = [
        f"From: {req.origin}",
        f"To:   {req.destination}",
        f"Depart: {when}   [provider: {result.provider}]",
        "",
    ]
    out += _route_header(result.best)
    if result.comparison_note:
        out.append(result.comparison_note)
    if show_steps:
        out.append("")
        out.append("Directions:")
        for i, s in enumerate(result.best.steps, 1):
            out.append(f"  {i:>2}. {s.instruction}")
            for n in s.notes:
                out.append(f"      ({n})")
            out.append(f"      {fmt_duration(s.duration_s)} ({fmt_distance(s.distance_m)})")
    if result.alternates:
        out.append("")
        out.append("Alternate routes:")
        for i, r in enumerate(result.alternates, 1):
            hdr = _route_header(r)
            out.append(f"  {i}. " + hdr[0])
            out += [f"     {h}" for h in hdr[1:]]
    return "\n".join(out)


def to_geojson(result: RouteResult) -> dict:
    feats = []
    for i, r in enumerate(result.routes):
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "rank": i,
                    "role": "best" if i == 0 else "alternate",
                    "summary": r.summary,
                    "duration_s": r.duration_s,
                    "static_duration_s": r.static_duration_s,
                    "distance_m": r.distance_m,
                    "labels": r.labels,
                },
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in r.geometry]},
            }
        )
    return {"type": "FeatureCollection", "features": feats}


_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>OpenNav route</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{margin:0;display:flex;font:14px system-ui,sans-serif}#side{width:380px;height:100vh;overflow:auto;padding:12px;box-sizing:border-box;white-space:pre-wrap}#map{flex:1;height:100vh}</style>
</head><body><div id="side"></div><div id="map"></div>
<script>
const gj = __GEOJSON__;
document.getElementById('side').textContent = __TEXT__;
const map = L.map('map');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
const layer = L.geoJSON(gj, {style: f => f.properties.role === 'best'
  ? {color: '#3b2fd6', weight: 6} : {color: '#8fa3ff', weight: 4, opacity: 0.8},
  onEachFeature: (f, l) => l.bindTooltip(f.properties.summary + ' - ' + Math.round(f.properties.duration_s/60) + ' min')});
layer.addTo(map); map.fitBounds(layer.getBounds());
</script></body></html>
"""


def to_html(result: RouteResult) -> str:
    # Alternates drawn first so the best route sits on top.
    gj = to_geojson(result)
    gj["features"].reverse()
    return _HTML.replace("__GEOJSON__", json.dumps(gj)).replace("__TEXT__", json.dumps(to_text(result)))
