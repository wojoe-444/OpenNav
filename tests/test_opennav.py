import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from opennav import cases, polyline, render
from opennav.models import RouteRequest
from opennav.providers import GoogleRoutesProvider, OSRMProvider, ProviderError
from opennav.timeparse import parse_departure

ET = ZoneInfo("America/New_York")


# ---------- polyline ----------

def test_polyline_known_vector():
    # Example from Google's polyline algorithm documentation.
    pts = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert polyline.encode(pts) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    assert polyline.decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == pts


def test_polyline6_roundtrip():
    pts = [(33.879123, -84.512345), (33.640111, -84.443333)]
    assert polyline.decode(polyline.encode(pts, 6), 6) == pts


# ---------- departure parsing ----------

NOW = datetime(2026, 11, 11, 13, 50, tzinfo=ET)  # a Wednesday


def test_parse_now():
    assert parse_departure("now") is None


def test_parse_weekday_next_occurrence():
    assert parse_departure("wed 08:00", now=NOW) == datetime(2026, 11, 18, 8, 0, tzinfo=ET)
    assert parse_departure("wednesday 5pm", now=NOW) == datetime(2026, 11, 11, 17, 0, tzinfo=ET)
    assert parse_departure("fri 7:30am", now=NOW) == datetime(2026, 11, 13, 7, 30, tzinfo=ET)


def test_parse_iso_and_clock():
    assert parse_departure("2026-12-01T08:15", now=NOW) == datetime(2026, 12, 1, 8, 15, tzinfo=ET)
    assert parse_departure("9am", now=NOW) == datetime(2026, 11, 12, 9, 0, tzinfo=ET)


def test_parse_bad():
    with pytest.raises(ValueError):
        parse_departure("someday", now=NOW)


# ---------- Google provider (offline, synthetic payload in the real response shape) ----------

def _line(a, b, n=10):
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


def _route(points_per_step, instructions, duration, static, description, intervals, warnings=(), labels=("DEFAULT_ROUTE",)):
    steps, full = [], []
    for pts, text in zip(points_per_step, instructions):
        full += pts if not full else pts[1:]
        steps.append(
            {
                "distanceMeters": round(polyline.length_m(pts)),
                "staticDuration": f"{round(polyline.length_m(pts) / 25)}s",
                "polyline": {"encodedPolyline": polyline.encode(pts)},
                "navigationInstruction": {"maneuver": "STRAIGHT", "instructions": text},
            }
        )
    return {
        "distanceMeters": round(polyline.length_m(full)),
        "duration": f"{duration}s",
        "staticDuration": f"{static}s",
        "description": description,
        "warnings": list(warnings),
        "routeLabels": list(labels),
        "polyline": {"encodedPolyline": polyline.encode(full)},
        "travelAdvisory": {"speedReadingIntervals": intervals},
        "legs": [
            {
                "startLocation": {"latLng": {"latitude": full[0][0], "longitude": full[0][1]}},
                "endLocation": {"latLng": {"latitude": full[-1][0], "longitude": full[-1][1]}},
                "steps": steps,
            }
        ],
    }


HOME, I75, AIRPORT_EXIT, AIRPORT = (33.880, -84.500), (33.870, -84.460), (33.660, -84.430), (33.641, -84.444)
I285_W = (33.760, -84.560)


@pytest.fixture
def google_payload():
    best = _route(
        [_line(HOME, I75), _line(I75, AIRPORT_EXIT, 40), _line(AIRPORT_EXIT, AIRPORT)],
        [
            "Turn right onto Lake Park Dr",
            "Merge onto I-75 S\nContinue onto I-85 S",
            "Take exit 72 toward Airport Blvd",
        ],
        duration=2400,
        static=1980,
        description="I-75 S and I-85 S",
        intervals=[
            {"endPolylinePointIndex": 15, "speed": "NORMAL"},
            {"startPolylinePointIndex": 15, "endPolylinePointIndex": 25, "speed": "SLOW"},
            {"startPolylinePointIndex": 25, "endPolylinePointIndex": 60, "speed": "NORMAL"},
        ],
        warnings=["This route has restricted usage or private roads."],
    )
    alt = _route(
        [_line(HOME, I285_W), _line(I285_W, AIRPORT, 40)],
        ["Head west on Cobb Pkwy", "Merge onto I-285 S"],
        duration=2760,
        static=2100,
        description="I-285 S",
        intervals=[
            {"endPolylinePointIndex": 15, "speed": "NORMAL"},
            {"startPolylinePointIndex": 15, "endPolylinePointIndex": 35, "speed": "TRAFFIC_JAM"},
            {"startPolylinePointIndex": 35, "endPolylinePointIndex": 50, "speed": "NORMAL"},
        ],
        labels=("DEFAULT_ROUTE_ALTERNATE",),
    )
    return {"provider": "google", "fetched_at": "2026-11-11T18:55:00+00:00", "departure": "2026-11-18T08:00:00-05:00",
            "response": {"routes": [best, alt]}}


REQ = RouteRequest("46 Rumson Ct, Smyrna, GA 30080", "6000 S Terminal Pkwy, Atlanta, GA 30337",
                   datetime(2026, 11, 18, 8, 0, tzinfo=ET))


def test_google_request_body():
    body = GoogleRoutesProvider(api_key="x").build_body(REQ)
    assert body["departureTime"] == "2026-11-18T13:00:00Z"
    assert body["routingPreference"] == "TRAFFIC_AWARE_OPTIMAL"
    assert body["computeAlternativeRoutes"] is True
    assert body["origin"] == {"address": REQ.origin}
    assert GoogleRoutesProvider(api_key="x").build_body(RouteRequest("33.1,-84.2", "x"))["origin"] == {
        "location": {"latLng": {"latitude": 33.1, "longitude": -84.2}}
    }


def test_google_parse(google_payload):
    res = GoogleRoutesProvider(api_key="x").parse(REQ, google_payload)
    best = res.best
    assert best.duration_s == 2400 and best.static_duration_s == 1980
    assert best.traffic_delay_s == 420
    assert best.summary == "I-75 S and I-85 S"
    assert best.warnings == ["This route has restricted usage or private roads."]
    assert len(best.steps) == 3
    assert [s.road for s in best.steps] == ["Lake Park Dr", "I-75 S", "Airport Blvd"]
    # Delay goes to the congested step; step times add up to the route's traffic time.
    assert sum(s.duration_s for s in best.steps) == pytest.approx(2400)
    assert best.steps[0].duration_s < best.steps[1].duration_s - 420
    assert best.congestion and best.congestion[0].road == "I-75 S" and best.congestion[0].level == "SLOW"
    assert "Traffic adds about 7 min" in best.traffic_note
    assert len(res.alternates) == 1
    assert res.alternates[0].congestion[0].level == "TRAFFIC_JAM"
    assert "avoids slowdown on I-285 S" in res.comparison_note
    assert "6 min slower" in res.comparison_note
    assert len(best.geometry) == 61


def test_google_requires_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        GoogleRoutesProvider().fetch_raw(REQ)


def test_renderers(google_payload):
    res = GoogleRoutesProvider(api_key="x").parse(REQ, google_payload)
    text = render.to_text(res)
    assert "40 min" in text and "via I-75 S and I-85 S" in text
    assert "restricted usage" in text and "Alternate routes:" in text
    gj = render.to_geojson(res)
    assert gj["features"][0]["geometry"]["coordinates"][0] == [HOME[1], HOME[0]]
    d = res.to_dict()
    assert polyline.decode(d["routes"][0]["encoded_polyline"])[0] == HOME
    json.dumps(d)  # serializable
    assert "L.geoJSON" in render.to_html(res)


# ---------- OSRM provider (offline) ----------

def test_osrm_parse():
    geo = polyline.encode(_line(HOME, AIRPORT), 6)
    raw = {
        "fetched_at": "2026-11-11T18:55:00+00:00",
        "response": {
            "code": "Ok",
            "routes": [
                {
                    "duration": 1900.0,
                    "distance": 39000.0,
                    "geometry": geo,
                    "legs": [
                        {
                            "summary": "I 75, I 85",
                            "steps": [
                                {"distance": 100, "duration": 20, "name": "Rumson Ct", "geometry": geo,
                                 "maneuver": {"type": "depart", "modifier": "left"}},
                                {"distance": 38900, "duration": 1880, "name": "", "ref": "I 75", "geometry": geo,
                                 "maneuver": {"type": "merge", "modifier": "slight right"}},
                            ],
                        }
                    ],
                }
            ],
            "waypoints": [{"location": [HOME[1], HOME[0]], "name": "Rumson Ct"}, {"location": [AIRPORT[1], AIRPORT[0]]}],
        },
    }
    req = RouteRequest(f"{HOME[0]},{HOME[1]}", f"{AIRPORT[0]},{AIRPORT[1]}")
    res = OSRMProvider().parse(req, raw)
    assert res.best.summary == "I 75 and I 85"
    assert res.best.steps[1].instruction == "Merge slight right onto I 75"
    assert res.best.traffic_delay_s == 0
    assert res.origin_resolved.endswith("(Rumson Ct)")


def test_osrm_rejects_addresses():
    with pytest.raises(ProviderError):
        OSRMProvider().fetch_raw(REQ)


# ---------- cases ----------

def test_pilot_case_loads():
    case = cases.Case.load("smyrna-to-atl")
    assert "Rumson" in case.origin
    req = case.request(now=NOW)
    assert req.departure == datetime(2026, 11, 18, 8, 0, tzinfo=ET)


def test_run_case_uses_stored_payload(tmp_path, monkeypatch, google_payload):
    monkeypatch.setattr(cases, "TRUTH_DIR", tmp_path)
    case = cases.Case.load("smyrna-to-atl")
    stored = tmp_path / case.id / "google__20261111T185500Z.json"
    stored.parent.mkdir(parents=True)
    stored.write_text(json.dumps(google_payload))

    class NoNetwork(GoogleRoutesProvider):
        def fetch_raw(self, request):
            raise AssertionError("should not call the API when a stored response exists")

    res, path, fetched = cases.run_case(case, NoNetwork(api_key="x"))
    assert path == stored and not fetched
    assert res.request.departure == datetime(2026, 11, 18, 8, 0, tzinfo=ET)
    rows = {name: ok for name, _, _, ok in cases.compare_to_observed(res, case.observed)}
    assert rows["duration_min"] and rows["summary"] and rows["warning"] and rows["alternates"]
