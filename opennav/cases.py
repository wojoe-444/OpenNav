"""Test cases: a named origin/destination/departure plus stored provider responses.

Layout:
  cases/<case_id>.json                       case definition (+ optional observed values)
  ground_truth/<case_id>/<provider>__<UTC timestamp>.json   raw provider payloads

Running a case reuses the newest stored payload for that provider unless
refresh=True, so a paid API is called once per case, not once per run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RouteRequest, RouteResult
from .providers import RoutingProvider
from .timeparse import parse_departure

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "cases"
TRUTH_DIR = ROOT / "ground_truth"


@dataclass
class Case:
    id: str
    origin: str
    destination: str
    departure: str = "now"
    timezone: str = "America/New_York"
    notes: str = ""
    observed: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, case_id_or_path: str) -> "Case":
        p = Path(case_id_or_path)
        if not p.suffix:
            p = CASES_DIR / f"{case_id_or_path}.json"
        data = json.loads(p.read_text())
        return cls(**data)

    def request(self, now: datetime | None = None) -> RouteRequest:
        return RouteRequest(
            origin=self.origin,
            destination=self.destination,
            departure=parse_departure(self.departure, self.timezone, now=now),
        )


def list_cases() -> list[str]:
    return sorted(p.stem for p in CASES_DIR.glob("*.json"))


def stored_payloads(case_id: str, provider: str) -> list[Path]:
    return sorted((TRUTH_DIR / case_id).glob(f"{provider}__*.json"))


def _request_from_payload(case: Case, raw: dict[str, Any]) -> RouteRequest:
    """Rebuild the request actually sent, so a cached answer is labelled with its real departure time."""
    dep = raw.get("departure")
    return RouteRequest(
        origin=case.origin,
        destination=case.destination,
        departure=datetime.fromisoformat(dep) if dep else None,
    )


def run_case(case: Case, provider: RoutingProvider, refresh: bool = False) -> tuple[RouteResult, Path, bool]:
    """Returns (result, payload_path, fetched_now)."""
    existing = stored_payloads(case.id, provider.name)
    if existing and not refresh:
        path = existing[-1]
        raw = json.loads(path.read_text())
        return provider.parse(_request_from_payload(case, raw), raw), path, False

    req = case.request()
    raw = provider.fetch_raw(req)
    raw["case_id"] = case.id
    raw["departure"] = req.departure.isoformat() if req.departure else None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = TRUTH_DIR / case.id / f"{provider.name}__{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2))
    return provider.parse(req, raw), path, True


def compare_to_observed(result: RouteResult, observed: dict[str, Any]) -> list[tuple[str, Any, Any, bool]]:
    """Check a result against values read off a reference (e.g. a Maps screenshot).

    Returns rows of (field, expected, actual, ok). Tolerances are loose on purpose:
    traffic differs between when the screenshot was taken and when we query.
    """
    rows: list[tuple[str, Any, Any, bool]] = []
    best = result.best
    if "distance_mi" in observed:
        exp, act = observed["distance_mi"], round(best.distance_mi, 1)
        rows.append(("distance_mi", exp, act, abs(exp - act) <= max(0.5, 0.05 * exp)))
    if "duration_min" in observed:
        exp, act = observed["duration_min"], round(best.duration_s / 60)
        rows.append(("duration_min", exp, act, abs(exp - act) <= max(5, 0.25 * exp)))
    if "summary" in observed:
        exp, act = observed["summary"], best.summary
        rows.append(("summary", exp, act, exp.lower() in act.lower() or act.lower() in exp.lower()))
    for w in observed.get("warnings", []):
        act = any(w.lower().rstrip(".") in x.lower() for x in best.warnings)
        rows.append(("warning", w, best.warnings, act))
    if "min_alternates" in observed:
        exp, act = observed["min_alternates"], len(result.alternates)
        rows.append(("alternates", f">= {exp}", act, act >= exp))
    return rows
