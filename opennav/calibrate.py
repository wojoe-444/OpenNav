"""Fit the cost model to ground truth.

For every stored Google route we map-match its polyline onto our graph, then:

1. Free-flow fit: each Google step gives "static" seconds for a stretch of road.
   Our free-flow time is linear in the parameters (time factor per road group,
   per-km arterial delay, turn/intersection delays), so we solve a bounded,
   ridge-regularised least squares problem pulling towards the defaults.
2. Traffic fit: Google's traffic-aware duration per route vs our traffic
   factor along the same path; a few traffic parameters are tuned with
   Nelder-Mead, with a penalty when our route ordering disagrees with Google's.

With one test case this is mostly a sanity check: the ridge term keeps the
parameters close to physically sensible defaults. Results are saved to
opennav/engine/params.json (committed: parameters, not Google data).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import lsq_linear, minimize
from scipy.spatial import cKDTree

from .cases import Case, latest_truth, list_cases
from .engine import Engine
from .engine.matching import match_polyline
from .engine.profile import CostModel, Params
from .providers import GoogleRoutesProvider


@dataclass
class MatchedRoute:
    case_id: str
    route_index: int
    edges: np.ndarray
    start_frac: float
    end_frac: float
    step_of_edge: np.ndarray
    step_static: np.ndarray
    duration_s: float
    static_s: float
    departure: object


def collect(engine: Engine, case_ids: list[str] | None = None, log=print) -> list[MatchedRoute]:
    out = []
    g, router = engine.graph, engine.router
    router._weights(None, False)
    for cid in case_ids or list_cases():
        found = latest_truth(Case.load(cid), GoogleRoutesProvider())
        if not found:
            continue
        truth = found[0]
        for ri, route in enumerate(truth.routes):
            p = match_polyline(router, route.geometry)
            pts, own = [], []
            for si, s in enumerate(route.steps):
                for q in s.geometry:
                    pts.append(q)
                    own.append(si)
            k = np.array([110540.0, 111320.0 * np.cos(np.radians(np.mean([q[0] for q in pts])))])
            tree = cKDTree(np.asarray(pts) * k)
            mids = np.array([g.edge_geom(e)[len(g.edge_geom(e)) // 2] for e in p.edges])
            _, idx = tree.query(mids * k)
            out.append(MatchedRoute(cid, ri, np.array(p.edges), p.start_frac, p.end_frac, np.asarray(own)[idx],
                                    np.array([s.static_duration_s or 0.0 for s in route.steps]),
                                    route.duration_s, route.static_duration_s or 0.0, truth.request.departure))
            log(f"matched {cid} route {ri}: {len(p.edges)} edges")
    return out


def _route_design(model: CostModel, F: np.ndarray, m: MatchedRoute) -> np.ndarray:
    """Rows = Google steps; columns = edge features + turn components."""
    e = m.edges
    frac = np.ones(len(e))
    frac[0] = 1 - m.start_frac
    frac[-1] = m.end_frac if len(e) > 1 else m.end_frac - m.start_frac
    Fe = F[e] * frac[:, None]
    C = np.zeros((len(e), len(model.TURN_COMPONENTS)))
    if len(e) > 1:
        C[1:] = model.turn_components(e[:-1], e[1:])
    X = np.zeros((len(m.step_static), Fe.shape[1] + C.shape[1]))
    np.add.at(X, m.step_of_edge, np.hstack([Fe, C]))
    return X


def fit_free_flow(engine: Engine, routes: list[MatchedRoute], ridge: float = 1.0, log=print) -> Params:
    model, p = engine.model, engine.model.p
    F = model.features()
    rows, ys, ws = [], [], []
    for m in routes:
        X = _route_design(model, F, m)
        rows.append(X)
        ys.append(m.step_static)
        ws.append(1.0 / np.sqrt(m.step_static + 20.0))
        rows.append(X.sum(0, keepdims=True))  # whole-route row, weighted up
        ys.append(np.array([m.static_s]))
        ws.append(np.array([3.0 / np.sqrt(m.static_s)]))
    X = np.vstack(rows)
    y = np.concatenate(ys)
    w = np.concatenate(ws)
    names = ([f"time_factor.{k}" for k in model.GROUPS] + [f"delay_s_per_km.{k}" for k in model.DELAY_GROUPS]
             + ["parking"] + list(model.TURN_COMPONENTS))
    prior = np.concatenate([model.feature_weights(), [getattr(p, k) for k in model.TURN_COMPONENTS]])
    # parking column is fixed at 1: move it to the right-hand side
    pk = names.index("parking")
    y = y - X[:, pk]
    keep = [i for i in range(len(names)) if i != pk]
    X, names_k, prior_k = X[:, keep], [names[i] for i in keep], prior[keep]
    lb = np.array([0.9 if n.startswith("time_factor") else 0.0 for n in names_k])
    ub = np.array([2.5 if n.startswith("time_factor") else (90.0 if "per_km" in n else 60.0) for n in names_k])
    # only regularise towards the prior; columns with no data stay at the prior
    used = np.abs(X).sum(0) > 0
    scale = np.maximum(np.abs(prior_k), 1.0)
    R = np.diag(ridge / scale)
    A = np.vstack([X * w[:, None], R])
    b = np.concatenate([y * w, ridge * prior_k / scale])
    sol = lsq_linear(A, b, bounds=(lb, ub)).x
    sol = np.where(used, sol, prior_k)
    for n, v, v0 in zip(names_k, sol, prior_k):
        if n.startswith("time_factor."):
            p.time_factor[n.split(".", 1)[1]] = round(float(v), 3)
        elif n.startswith("delay_s_per_km."):
            p.delay_s_per_km[n.split(".", 1)[1]] = round(float(v), 2)
        else:
            setattr(p, n, round(float(v), 2))
        if abs(v - v0) > 1e-3:
            log(f"  {n:28} {v0:8.3f} -> {v:8.3f}")
    model.recompute()
    return p


TRAFFIC_KEYS = ["am_amplitude", "dir_weight", "cw_motorway", "cw_arterial"]


def _apply_traffic(p: Params, x) -> None:
    p.am_amplitude = float(x[0])
    p.dir_weight = float(x[1])
    p.class_weight["motorway"] = p.class_weight["trunk"] = float(x[2])
    for c in ("primary", "secondary", "tertiary"):
        p.class_weight[c] = float(x[3])


def route_time(engine: Engine, m: MatchedRoute, factor: np.ndarray) -> tuple[float, float]:
    model = engine.model
    e = m.edges
    frac = np.ones(len(e))
    frac[0] = 1 - m.start_frac
    frac[-1] = m.end_frac if len(e) > 1 else m.end_frac - m.start_frac
    free = model.free_time[e] * frac
    turns = model.turn_costs(e[:-1], e[1:], routing=False).sum() if len(e) > 1 else 0.0
    return float((free * factor[e]).sum() + turns), float(free.sum() + turns)


def fit_traffic(engine: Engine, routes: list[MatchedRoute], log=print) -> Params:
    p = engine.model.p
    x0 = np.array([p.am_amplitude, p.dir_weight, p.class_weight["motorway"], p.class_weight["primary"]])
    prior = x0.copy()

    def loss(x):
        if np.any(x < 0) or x[1] > 3:
            return 1e9
        _apply_traffic(p, x)
        err, order_pen = 0.0, 0.0
        by_case: dict[str, list[tuple[float, float]]] = {}
        for m in routes:
            f = engine.model.traffic_factor(m.departure)
            t, _ = route_time(engine, m, f)
            # compare the traffic delay ratio, independent of free-flow error
            _, free = route_time(engine, m, np.ones_like(f))
            ours_ratio, g_ratio = t / free, m.duration_s / max(m.static_s, 1)
            err += (ours_ratio - g_ratio) ** 2
            by_case.setdefault(m.case_id, []).append((m.duration_s, t))
        for pairs in by_case.values():
            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    gd = pairs[j][0] - pairs[i][0]
                    od = pairs[j][1] - pairs[i][1]
                    if gd * od < 0:
                        order_pen += (od / 60.0) ** 2
        return err * 100 + order_pen + 0.05 * float(((x - prior) / np.maximum(prior, 0.1)) ** 2 @ np.ones(len(x)))

    res = minimize(loss, x0, method="Nelder-Mead", options={"maxiter": 400, "xatol": 1e-3, "fatol": 1e-4})
    _apply_traffic(p, res.x)
    for k, a, b in zip(TRAFFIC_KEYS, x0, res.x):
        log(f"  {k:28} {a:8.3f} -> {b:8.3f}")
    return p


def calibrate(case_ids: list[str] | None = None, region: str = "atlanta", save: bool = True, log=print) -> Params:
    engine = Engine.load(region)
    engine.model.p = Params.load()
    engine.model.recompute()
    routes = collect(engine, case_ids, log=log)
    if not routes:
        raise ValueError("no ground truth to calibrate against")
    log("free-flow fit:")
    fit_free_flow(engine, routes, log=log)
    log("traffic fit:")
    fit_traffic(engine, routes, log=log)
    for m in routes:
        f = engine.model.traffic_factor(m.departure)
        t, free = route_time(engine, m, f)
        log(f"  {m.case_id} route {m.route_index}: ours {t / 60:5.1f} min (free {free / 60:5.1f})"
            f"  google {m.duration_s / 60:5.1f} min (free {m.static_s / 60:5.1f})")
    if save:
        engine.model.p.save()
        log("saved opennav/engine/params.json")
    return engine.model.p
