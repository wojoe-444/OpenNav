"""Offline tests for the OpenNav engine on a tiny synthetic Overture-shaped network."""
from __future__ import annotations

import struct
from datetime import datetime
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from opennav.engine.graph import F_RESTRICTED, build_graph, car_access
from opennav.engine.guidance import abbreviate, ref_direction
from opennav.engine.profile import CostModel, Params
from opennav.engine.search import Router
from opennav.models import Route, RouteRequest, RouteResult, Step
from opennav.providers.opennav_local import OpenNavProvider
from opennav.scoring import coverage, norm_road, score, summary_score


def wkb(coords):
    return struct.pack("<BII", 1, 2, len(coords)) + b"".join(struct.pack("<dd", x, y) for x, y in coords)


def seg(id_, coords, conns, cls="residential", name=None, access=None, routes=None, speed=None, subclass=None):
    return {
        "id": id_, "names": {"primary": name} if name else None, "class": cls, "subclass": subclass,
        "connectors": [{"connector_id": c, "at": a} for c, a in conns], "road_flags": None,
        "access_restrictions": access, "speed_limits": speed, "prohibited_transitions": None,
        "routes": routes, "destinations": None, "geometry": wkb(coords),
    }


# A 3x2 grid (lon, lat). Bottom row is a fast primary road "Main Street" (US-41),
# top row a residential street, plus a private shortcut in the middle.
#   A(0,1) -- B(1,1) -- C(2,1)
#   |          |         |
#   D(0,0) -- E(1,0) -- F(2,0)
S = 0.01  # ~1 km


def network(tmp_path):
    P = {"A": (0, S), "B": (S, S), "C": (2 * S, S), "D": (0, 0), "E": (S, 0), "F": (2 * S, 0)}
    rows = [
        seg("AB", [P["A"], P["B"]], [("A", 0), ("B", 1)], name="Oak Lane"),
        seg("BC", [P["B"], P["C"]], [("B", 0), ("C", 1)], name="Oak Lane"),
        seg("DE", [P["D"], P["E"]], [("D", 0), ("E", 1)], cls="primary", name="Main Street",
            routes=[{"network": "US:US", "ref": "41"}], speed=[{"max_speed": {"value": 45, "unit": "mph"}}]),
        seg("EF", [P["E"], P["F"]], [("E", 0), ("F", 1)], cls="primary", name="Main Street",
            routes=[{"network": "US:US", "ref": "41"}], speed=[{"max_speed": {"value": 45, "unit": "mph"}}]),
        seg("AD", [P["A"], P["D"]], [("A", 0), ("D", 1)], name="First Avenue"),
        seg("BE", [P["B"], P["E"]], [("B", 0), ("E", 1)], name="Gate Road",
            access=[{"access_type": "allowed", "when": {"using": ["at_destination"]}, "between": None}]),
        seg("CF", [P["C"], P["F"]], [("C", 0), ("F", 1)], name="Third Avenue",
            access=[{"access_type": "denied", "when": {"heading": "backward"}, "between": None}]),  # one-way C->F
        seg("FOOT", [P["A"], P["F"]], [("A", 0), ("F", 1)], cls="footway"),
    ]
    path = tmp_path / "segments.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    return build_graph(path, log=lambda *_: None)


@pytest.fixture()
def engine(tmp_path):
    g = network(tmp_path)
    p = Params()
    model = CostModel(g, p)
    return g, model, Router(g, model)


def test_graph_access_rules(engine):
    g, _, _ = engine
    names = {g.seg_ids[s] for s in g.seg_idx}
    assert "FOOT" not in names  # footways are not drivable
    cf = [e for e in range(g.n_edges) if g.seg_ids[g.seg_idx[e]] == "CF"]
    assert len(cf) == 1 and g.forward[cf[0]]  # one-way
    be = [e for e in range(g.n_edges) if g.seg_ids[g.seg_idx[e]] == "BE"]
    assert len(be) == 2 and all(g.flags[e] & F_RESTRICTED for e in be)
    assert g.refs[g.ref_idx[cf[0]]] if g.ref_idx[cf[0]] >= 0 else True


def test_car_access_variants():
    assert car_access([{"access_type": "denied", "when": None}], 0.5, "forward") == (False, 0)
    assert car_access([{"access_type": "denied", "when": {"mode": ["hgv"]}}], 0.5, "forward")[0]
    ok, fl = car_access([{"access_type": "allowed", "when": {"recognized": ["as_private"]}}], 0.5, "forward")
    assert ok and fl & F_RESTRICTED


def test_route_prefers_main_road_and_avoids_private(engine):
    g, model, router = engine
    src = router.snap(S * 0.98, 0.0005)  # near A on First Avenue
    dst = router.snap(0.0002, 2 * S - 0.0005)  # near F on Main Street
    paths = router.search(src, dst, None, traffic=False, alternatives=2)
    used = [g.seg_ids[g.seg_idx[e]] for e in paths[0].edges]
    assert "BE" not in used  # restricted shortcut not used as a through route
    assert used[-1] == "EF"


def test_provider_end_to_end(engine):
    g, model, router = engine

    class Eng:
        pass

    eng = Eng()
    eng.graph, eng.model, eng.router = g, model, router
    req = RouteRequest("x", "y", departure=datetime(2026, 11, 18, 8, tzinfo=ZoneInfo("America/New_York")))
    res = OpenNavProvider(traffic_model=True).route_points(eng, req, (S * 0.5, 0.0001), (0.0002, 2 * S - 0.0005))
    best = res.best
    assert best.steps[0].maneuver == "DEPART"
    assert best.steps[0].instruction.startswith("Head south on First Ave")
    assert any("US-41 E/Main St" == s.road for s in best.steps)
    assert best.duration_s >= best.static_duration_s > 0
    assert "Main St" in best.summary or "US-41" in best.summary
    # round trip through the stored-dict form
    again = RouteResult.from_dict(res.to_dict())
    assert again.best.summary == best.summary and len(again.best.steps) == len(best.steps)


def test_abbreviations_and_directions():
    assert abbreviate("Hillsdale Parkway Southeast", keep_dir_suffix=False) == "Hillsdale Pkwy"
    assert abbreviate("Windy Hill Road Southeast") == "Windy Hill Rd SE"
    assert abbreviate("South Terminal Parkway") == "S Terminal Pkwy"
    assert ref_direction("I-85", 200) == "S"
    assert ref_direction("I-20", 265) == "W"


def _route(points, minutes, summary, steps=()):
    return Route(duration_s=minutes * 60, distance_m=1000.0 * len(points), summary=summary,
                 static_duration_s=minutes * 55, geometry=points,
                 steps=[Step(instruction=t, distance_m=100, duration_s=10, road=r, maneuver=m) for t, r, m in steps])


def test_scoring_identical_and_different():
    a = [(33.0 + i * 0.001, -84.0) for i in range(50)]
    b = [(33.0, -84.0 + i * 0.001) for i in range(50)]
    assert coverage(a, a) == pytest.approx(1.0)
    assert coverage(a, b) < 0.1
    steps = [("Head north on Oak Ln", "Oak Ln", "DEPART"), ("Merge onto I-285 W", "I-285 W", "MERGE")]
    req = RouteRequest("o", "d")
    truth = RouteResult(req, "google", [_route(a, 30, "I-285 W", steps), _route(b, 33, "I-75 S")])
    same = RouteResult(req, "opennav", [_route(a, 30, "I-285 S", steps), _route(b, 33, "I-75 S")])
    s = score(same, truth)
    assert s.total > 95
    swapped = RouteResult(req, "opennav", [_route(b, 30, "I-75 S"), _route(a, 33, "I-285 W", steps)])
    assert score(swapped, truth).metrics["ranking"] < 0.5
    assert norm_road("Hillsdale Parkway Southeast") == "hillsdale pkwy"
    assert summary_score("I-75 S and I-85 S", "I-75 S and I-85 S") == 1.0
