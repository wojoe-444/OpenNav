# OpenNav

Open source routing and traffic analysis. The first building block is a route
lookup tool: give it an origin, a destination and a departure day/time, and it
returns what a maps app shows for that trip:

- total duration (with traffic) and distance
- the main roads used ("via I-75 S and I-85 S")
- a traffic note (delay vs free flow, where the slowdowns are, what the route avoids)
- warnings, such as restricted or private roads
- step-by-step directions with time and distance per step
- alternate routes
- route geometry (encoded polyline, GeoJSON, or an HTML map)

## Design

```
opennav/
  models.py          provider-neutral types: RouteRequest, Route, Step, RouteResult
  providers/
    base.py          RoutingProvider: fetch_raw() (network) + parse() (pure)
    google_routes.py Google Routes API, used as ground truth while piloting
    osrm.py          OSRM (OpenStreetMap), the first open source backend
  traffic.py         congestion by road, per-step delay estimates, route comparison notes
  cases.py           named test cases + stored provider responses + reference checks
  render.py          text panel, GeoJSON, standalone Leaflet map
  cli.py             `opennav` command
cases/               test case definitions (committed)
```

Every backend maps its answer into the same model, so adding Valhalla,
GraphHopper or our own traffic model means writing one provider class.
Fetching and parsing are separate: a paid API is called once per test case,
the raw response is saved locally, and later runs re-parse it.

Raw provider responses are **never committed**. They live in your app data
folder, under `ground_truth/<case_id>/`:

| OS      | Default location                                  |
|---------|---------------------------------------------------|
| Windows | `%APPDATA%\opennav\ground_truth`                  |
| macOS   | `~/Library/Application Support/opennav/ground_truth` |
| Linux   | `~/.local/share/opennav/ground_truth`             |

Set `OPENNAV_DATA_DIR` to use a different folder (for example a separate
private repo).

## Usage

```bash
pip install -e '.[dev]'
export GOOGLE_MAPS_API_KEY=...        # key with the Routes API enabled

# Pilot test case (calls Google once, then reuses the stored response)
opennav case run smyrna-to-atl --map out/route.html --geojson out/route.geojson
opennav case run smyrna-to-atl --refresh     # force a new API call
opennav case run smyrna-to-atl --format json

# Ad-hoc lookup (always calls the provider)
opennav route "46 Rumson Ct, Smyrna, GA 30080" "6000 S Terminal Pkwy, Atlanta, GA 30337" --depart "wed 08:00"

# Open source backend (needs coordinates until a geocoder is plugged in)
opennav route "33.8790,-84.5000" "33.6407,-84.4277" --provider osrm --osrm-url http://localhost:5000
```

Departure accepts `now`, `wed 08:00`, `friday 5:30pm`, `9am`, or an ISO time
like `2026-11-18T08:00` (local to `--tz`, default `America/New_York`).
Google only models traffic for departures in the future.

## Notes and limits

- Google's Routes API gives traffic-aware time for the whole route but only
  free-flow time per step. Per-step times are estimated by spreading the
  traffic delay over the congested steps (`traffic.distribute_delay`).
- Google Maps' web UI groups steps into 3 or 4 high-level legs; the API returns
  the detailed turn list. The grouped legs from the reference screenshot are
  recorded in the case file for later comparison.
- OSRM has no live traffic and no geocoder; durations are free-flow.

## Tests

```bash
python -m pytest
```

Tests run offline against payloads in the real response shapes.
