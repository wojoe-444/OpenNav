"""Builds the JSON the viewer shows for one case: the official (ground-truth)
answer, our modeled answer, the score, and where the two paths diverge.

Everything the browser needs is computed here, so new comparisons are added in
Python (add a key to the payload) and shown by adding a panel in static/app.js.

Ground truth is read from the local data dir only (see opennav.cases.data_dir);
nothing here writes into the repo.
"""
from __future__ import annotations

import math
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.spatial import cKDTree

from ..cases import Case, latest_truth, list_cases, stored_payloads
from ..models import METERS_PER_MILE, Route, RouteRequest, RouteResult
from ..providers import GoogleRoutesProvider

PARAMS_PATH = Path(__file__).resolve().parent.parent / "engine" / "params.json"


# ---------------------------------------------------------------- serialisation

def _route_json(r: Route) -> dict[str, Any]:
    return {
        "summary": r.summary,
        "duration_s": r.duration_s,
        "static_duration_s": r.static_duration_s,
        "traffic_delay_s": r.traffic_delay_s,
        "distance_m": r.distance_m,
        "distance_mi": round(r.distance_mi, 2),
        "labels": r.labels,
        "warnings": r.warnings,
        "traffic_note": r.traffic_note,
        "congestion": [asdict(c) for c in r.congestion],
        "geometry": [[round(a, 6), round(b, 6)] for a, b in r.geometry],
        "steps": [{
            "instruction": s.instruction,
            "distance_m": s.distance_m,
            "distance_mi": round(s.distance_m / METERS_PER_MILE, 2),
            "duration_s": s.duration_s,
            "static_duration_s": s.static_duration_s,
            "maneuver": s.maneuver,
            "road": s.road,
            "notes": s.notes,
            "geometry": [[round(a, 6), round(b, 6)] for a, b in s.geometry],
        } for s in r.steps],
    }


def result_json(res: RouteResult) -> dict[str, Any]:
    return {
        "provider": res.provider,
        "departure": res.request.departure.isoformat() if res.request.departure else None,
        "origin_resolved": res.origin_resolved,
        "destination_resolved": res.destination_resolved,
        "fetched_at": res.fetched_at.isoformat() if res.fetched_at else None,
        "comparison_note": res.comparison_note,
        "routes": [_route_json(r) for r in res.routes],
    }


# ---------------------------------------------------------------- divergence

def divergence(a: list[tuple[float, float]], b: list[tuple[float, float]], buffer_m: float = 25.0,
               min_len_m: float = 60.0) -> list[dict[str, Any]]:
    """Stretches of polyline a that are farther than buffer_m from polyline b.

    Returns [{"length_m", "geometry": [[lat, lon], ...]}], longest first. These are
    drawn on the map so a reviewer sees at a glance where the routes split.
    """
    if len(a) < 2 or len(b) < 2:
        return []
    lat0 = float(np.mean([p[0] for p in a]))
    k = np.array([110540.0, 111320.0 * math.cos(math.radians(lat0))])
    pa = _densify(np.asarray(a, dtype=float), k, 10.0)
    pb = _densify(np.asarray(b, dtype=float), k, 5.0)
    d, _ = cKDTree(pb * k).query(pa * k, distance_upper_bound=buffer_m)
    off = ~np.isfinite(d)
    runs, start = [], None
    for i, flag in enumerate(np.append(off, False)):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            seg = pa[max(0, start - 1): i + 1]  # include the last shared point on each side
            length = float(np.hypot(*((np.diff(seg, axis=0) * k).T)).sum())
            if length >= min_len_m:
                runs.append({"length_m": round(length, 1),
                             "geometry": [[round(x, 6), round(y, 6)] for x, y in seg]})
            start = None
    return sorted(runs, key=lambda r: -r["length_m"])


def _densify(ll: np.ndarray, k: np.ndarray, step: float) -> np.ndarray:
    out = [ll[:1]]
    for p, q in zip(ll[:-1], ll[1:]):
        n = max(1, int(math.ceil(float(np.hypot(*((q - p) * k))) / step)))
        t = (np.arange(1, n + 1) / n)[:, None]
        out.append(p + (q - p) * t)
    return np.concatenate(out)


# ---------------------------------------------------------------- models

def _ll(text: str | None):
    if not text:
        return None
    lat, lon = (float(x) for x in text.split(","))
    return lat, lon


def run_opennav(case: Case, truth: RouteResult | None) -> RouteResult:
    """Our engine. With ground truth: on Google's resolved endpoints and departure,
    as `opennav score` does. Without: on the case's own points (origin_point /
    destination_point, else our geocoder) at the case's departure."""
    from ..providers import OpenNavProvider
    prov = OpenNavProvider()
    if truth is not None:
        o, d = _ll(truth.origin_resolved), _ll(truth.destination_resolved)
        departure = truth.request.departure
    else:
        o = _ll(case.origin_point) or prov.resolve(case.origin)
        d = _ll(case.destination_point) or prov.resolve(case.destination)
        departure = case.request().departure
    req = RouteRequest(origin=case.origin, destination=case.destination, departure=departure)
    return prov.route_points(prov.engine([o, d]), req, o, d)


# Modeled sources the viewer can compare against the official answer. Add an
# entry to compare another engine or configuration; the UI lists them all.
MODELS: dict[str, Callable[[Case, RouteResult | None], RouteResult]] = {
    "opennav": run_opennav,
}


# ---------------------------------------------------------------- comparison

class Comparer:
    """Caches modeled runs per (case, model, ground-truth file, params version)."""

    def __init__(self):
        self._cache: dict[tuple, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _key(self, case_id: str, model: str) -> tuple:
        files = stored_payloads(case_id, GoogleRoutesProvider.name)
        params_v = PARAMS_PATH.stat().st_mtime if PARAMS_PATH.exists() else 0
        return case_id, model, str(files[-1]) if files else None, params_v

    def cases(self) -> list[dict[str, Any]]:
        out = []
        for cid in list_cases():
            case = Case.load(cid)
            files = stored_payloads(cid, GoogleRoutesProvider.name)
            cached = {m: self._cache.get(self._key(cid, m)) for m in MODELS}
            out.append({
                "id": cid, "origin": case.origin, "destination": case.destination,
                "departure": case.departure, "has_truth": bool(files),
                "truth_files": [p.name for p in files],
                "scores": {m: (c or {}).get("score", {}).get("total") if c else None for m, c in cached.items()},
            })
        return out

    def compare(self, case_id: str, model: str = "opennav", rerun: bool = False) -> dict[str, Any]:
        if case_id not in list_cases():
            raise KeyError(case_id)
        if model not in MODELS:
            raise KeyError(model)
        key = self._key(case_id, model)
        with self._lock:  # one engine run at a time; the graph is shared
            if not rerun and key in self._cache:
                return self._cache[key]
            payload = self._build(case_id, model)
            self._cache[key] = payload
            return payload

    def _build(self, case_id: str, model: str) -> dict[str, Any]:
        from ..scoring import WEIGHTS, score as score_fn
        case = Case.load(case_id)
        payload: dict[str, Any] = {"case": asdict(case), "model": model, "models": list(MODELS)}
        found = latest_truth(case, GoogleRoutesProvider())
        truth = None
        if found is None:
            # Still run the model, so its routes can be reviewed on their own.
            payload["official"] = None
            payload["official_error"] = (f"No stored Google response for this case, so there is no score. Run "
                                         f"`opennav case run {case_id}` once, or copy the file into the data dir's "
                                         f"ground_truth/{case_id}/.")
        else:
            truth, _, path = found
            payload["official"] = result_json(truth)
            payload["official_file"] = path.name
        t0 = time.perf_counter()
        try:
            ours = MODELS[model](case, truth)
        except Exception as e:  # show the official side even if the model can't run
            payload["modeled"] = None
            payload["modeled_error"] = f"{type(e).__name__}: {e}"
            payload["modeled_traceback"] = traceback.format_exc()
            return payload
        payload["model_seconds"] = round(time.perf_counter() - t0, 2)
        payload["modeled"] = result_json(ours)
        if truth is None:
            return payload
        payload["score"] = score_fn(ours, truth).to_dict()
        payload["score_weights"] = WEIGHTS
        payload["divergence"] = {
            "modeled_only": divergence(ours.best.geometry, truth.best.geometry),
            "official_only": divergence(truth.best.geometry, ours.best.geometry),
        }
        return payload
