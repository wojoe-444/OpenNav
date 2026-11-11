"""Command line entry point.

  opennav route "ORIGIN" "DESTINATION" --depart "wed 08:00" [--provider google|osrm]
  opennav case run smyrna-to-atl [--refresh] [--json out.json] [--geojson out.geojson] [--map out.html]
  opennav case list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import render
from .cases import Case, compare_to_observed, list_cases, run_case
from .models import RouteRequest, RouteResult
from .providers import PROVIDERS, ProviderError, get_provider
from .timeparse import parse_departure


def _provider_kwargs(args) -> dict:
    return {"base_url": args.osrm_url} if args.provider == "osrm" and args.osrm_url else {}


def _emit(result: RouteResult, args) -> None:
    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render.to_text(result, show_steps=not args.no_steps))
    if args.json:
        Path(args.json).write_text(json.dumps(result.to_dict(), indent=2))
    if args.geojson:
        Path(args.geojson).write_text(json.dumps(render.to_geojson(result)))
    if args.map:
        Path(args.map).write_text(render.to_html(result))


def _add_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", default="google", choices=sorted(PROVIDERS))
    p.add_argument("--osrm-url", help="OSRM server base URL (default $OSRM_URL or http://localhost:5000)")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--no-steps", action="store_true")
    p.add_argument("--json", metavar="PATH", help="also write the normalized result as JSON")
    p.add_argument("--geojson", metavar="PATH", help="write route geometries as GeoJSON")
    p.add_argument("--map", metavar="PATH", help="write a standalone HTML map")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opennav", description="Route lookup with pluggable providers.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("route", help="ad-hoc route lookup (always calls the provider)")
    r.add_argument("origin")
    r.add_argument("destination")
    r.add_argument("--depart", default="now", help='"now", "wed 08:00", "2026-11-18T08:00", ...')
    r.add_argument("--tz", default="America/New_York")
    r.add_argument("--no-alternatives", action="store_true")
    _add_output_args(r)

    c = sub.add_parser("case", help="named test cases with stored ground truth")
    csub = c.add_subparsers(dest="case_cmd", required=True)
    csub.add_parser("list")
    cr = csub.add_parser("run")
    cr.add_argument("case_id")
    cr.add_argument("--refresh", action="store_true", help="call the provider even if a stored response exists")
    _add_output_args(cr)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "route":
            req = RouteRequest(
                origin=args.origin,
                destination=args.destination,
                departure=parse_departure(args.depart, args.tz),
                alternatives=not args.no_alternatives,
            )
            _emit(get_provider(args.provider, **_provider_kwargs(args)).route(req), args)
            return 0

        if args.case_cmd == "list":
            print("\n".join(list_cases()))
            return 0

        case = Case.load(args.case_id)
        result, path, fetched = run_case(case, get_provider(args.provider, **_provider_kwargs(args)), refresh=args.refresh)
        print(f"[{'fetched and stored' if fetched else 'using stored'} response: {path}]", file=sys.stderr)
        _emit(result, args)
        if case.observed and args.format == "text":
            print("\nCheck against reference:")
            for name, exp, act, ok in compare_to_observed(result, case.observed):
                print(f"  [{'ok' if ok else 'DIFF'}] {name}: expected {exp!r}, got {act!r}")
        return 0
    except (ProviderError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
