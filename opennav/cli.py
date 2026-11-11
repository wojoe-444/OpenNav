"""Command line entry point.

  opennav route "ORIGIN" "DESTINATION" --depart "wed 08:00" [--provider google|osrm]
  opennav case run smyrna-to-atl [--refresh] [--json out.json] [--geojson out.geojson] [--map out.html]
  opennav case list
  opennav score [CASE ...] [-v]          compare our engine with stored Google responses
  opennav data build [--region atlanta]  download OSM road data (Overture) and build the graph
  opennav serve [--port 8765]            local web app: official vs modeled routes, for visual review
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

    sc = sub.add_parser("score", help="score our engine against stored ground truth")
    sc.add_argument("cases", nargs="*", help="case ids (default: all)")
    sc.add_argument("-v", "--verbose", action="store_true", help="print steps side by side")
    sc.add_argument("--own-geocoder", action="store_true", help="geocode with our geocoder instead of Google's points")
    sc.add_argument("--no-traffic", action="store_true", help="disable the traffic model")

    cal = sub.add_parser("calibrate", help="fit speeds, delays and traffic to stored ground truth")
    cal.add_argument("cases", nargs="*")
    cal.add_argument("--dry-run", action="store_true", help="do not write opennav/engine/params.json")

    dt = sub.add_parser("data", help="road data management")
    dsub = dt.add_subparsers(dest="data_cmd", required=True)
    db = dsub.add_parser("build", help="download (if needed) and build a region's road graph")
    db.add_argument("--region", default="atlanta")
    db.add_argument("--refresh", action="store_true", help="re-download the road data")
    db.add_argument("--addresses", action="store_true", help="also download address points for geocoding")

    sv = sub.add_parser("serve", help="local web viewer: official vs modeled routes")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--host", default="127.0.0.1", help="interface to bind (default: this machine only)")
    sv.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    sv.add_argument("--warm", metavar="CASE", help="run the model for this case at startup")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "serve":
            from .viewer.server import serve
            serve(args.host, args.port, open_browser=not args.no_browser, warm=args.warm)
            return 0

        if args.cmd == "score":
            from .bench import run_all
            from .providers import OpenNavProvider
            res = run_all(args.cases or None, verbose=args.verbose, own_geocoder=args.own_geocoder,
                          provider=OpenNavProvider(traffic_model=not args.no_traffic))
            return 0 if res else 1

        if args.cmd == "calibrate":
            from .calibrate import calibrate
            calibrate(args.cases or None, save=not args.dry_run)
            return 0

        if args.cmd == "data":
            from .data import overture
            from .data.regions import REGIONS, region_dir
            from .engine import ensure_region
            d = region_dir(args.region)
            if args.refresh:
                for f in ("segments.parquet", "graph.pkl"):
                    (d / f).unlink(missing_ok=True)
            print(f"graph ready: {ensure_region(args.region)}")
            if args.addresses:
                overture.fetch_addresses(REGIONS[args.region], d / "addresses.parquet")
            return 0

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
        if path is not None:
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
