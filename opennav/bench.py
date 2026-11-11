"""Benchmark our engine against stored ground truth for every case.

    opennav score                   # all cases with a stored Google response
    opennav score smyrna-to-atl -v  # one case, with step-by-step comparison

Reports are written to <data dir>/reports/ (local, never committed).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .cases import Case, data_dir, latest_truth, list_cases
from .models import RouteRequest
from .providers import GoogleRoutesProvider, OpenNavProvider
from .scoring import Score, format_score, score


def _ll(text: str | None):
    if not text:
        return None
    lat, lon = (float(x) for x in text.split(","))
    return lat, lon


def run_case(case: Case, engine_provider: OpenNavProvider | None = None, own_geocoder: bool = False):
    """Returns (ours, truth, Score) or None when the case has no stored ground truth."""
    found = latest_truth(case, GoogleRoutesProvider())
    if found is None:
        return None
    truth, raw, _ = found
    prov = engine_provider or OpenNavProvider()
    req = RouteRequest(origin=case.origin, destination=case.destination, departure=truth.request.departure)
    if own_geocoder:
        o, d = prov.resolve(case.origin), prov.resolve(case.destination)
    else:
        # Score routing on the same endpoints Google used; geocoding is measured separately.
        o, d = _ll(truth.origin_resolved), _ll(truth.destination_resolved)
    eng = prov.engine([o, d])
    ours = prov.route_points(eng, req, o, d)
    return ours, truth, score(ours, truth)


def run_all(case_ids: list[str] | None = None, verbose: bool = False, own_geocoder: bool = False,
            provider: OpenNavProvider | None = None, out=print) -> list[tuple[str, Score]]:
    results = []
    for cid in case_ids or list_cases():
        case = Case.load(cid)
        r = run_case(case, provider, own_geocoder)
        if r is None:
            out(f"{cid}: skipped (no stored Google response; run `opennav case run {cid}` once)")
            continue
        ours, truth, s = r
        out(format_score(cid, s))
        if verbose:
            out(side_by_side(ours, truth))
        results.append((cid, s))
    if results:
        mean = sum(s.total for _, s in results) / len(results)
        out(f"\nmean score over {len(results)} case(s): {mean:.1f} / 100")
        rep = data_dir() / "reports" / f"score__{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text(json.dumps({"mean": mean, "cases": {c: s.to_dict() for c, s in results}}, indent=2))
        out(f"report: {rep}")
    return results


def side_by_side(ours, truth) -> str:
    from .render import fmt_distance, fmt_duration
    lines = ["", "  steps (ours | google):"]
    n = max(len(ours.best.steps), len(truth.best.steps))
    for i in range(n):
        a = ours.best.steps[i] if i < len(ours.best.steps) else None
        b = truth.best.steps[i] if i < len(truth.best.steps) else None
        fa = f"{a.instruction[:52]:52} {fmt_distance(a.distance_m):>8}" if a else " " * 61
        fb = f"{b.instruction[:52]:52} {fmt_distance(b.distance_m):>8}" if b else ""
        lines.append(f"  {i + 1:2}. {fa} | {fb}")
    lines.append("  routes:")
    for tag, res in (("ours", ours), ("google", truth)):
        for i, r in enumerate(res.routes):
            lines.append(f"    {tag:6} {i}: {fmt_duration(r.duration_s):>7} (free {fmt_duration(r.static_duration_s or 0):>7})"
                         f" {r.distance_mi:5.1f} mi  {r.summary}")
    return "\n".join(lines)
