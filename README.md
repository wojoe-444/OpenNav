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

## OpenNav engine (our own router)

`--provider opennav` is our own routing engine, built to match Google's answers
as closely as possible using only open data:

- **Road data:** OpenStreetMap, via the Overture Maps transportation layer
  (GeoParquet on a public S3 bucket, ODbL). We read only the Parquet row groups
  that cover the region, over plain HTTPS, so no OSM mirror or Overpass access is
  needed. `opennav data build --region atlanta` downloads ~450 MB once and builds
  a ~1M-edge graph in under a minute.
- **Graph:** one-ways, car access rules (private / destination-only roads are
  allowed but flagged), turn restrictions, speed limits, route refs (I-285,
  US-41) and exit signs ("I-85 S toward Columbus").
- **Routing:** edge-based Dijkstra on the turn graph (exact turn costs and
  restrictions), via-node alternatives (as in OSRM) filtered for stretch,
  overlap and local optimality.
- **Cost model** (`engine/profile.py`): time at the speed limit x factor per road
  group, per-km arterial delay, turn and intersection delays, and a time-of-day
  traffic model (rush-hour peaks, metro density, inbound/outbound tidal flow).
  Parameters are fitted to ground truth by `opennav calibrate` (map-matches each
  Google route onto our graph and fits per-step free-flow times, then traffic).
- **Guidance:** Google-style steps ("Turn right onto US-41 S/Cobb Pkwy",
  "Merge onto I-285 W", "Take the exit for I-85 N toward Airport Domestic"),
  road summary with Google's disambiguation of alternates, highway and
  restricted-road warnings.

```bash
opennav data build --region atlanta     # one time, data goes to the local data dir
opennav route "33.8976,-84.4945" "33.6392,-84.4430" --provider opennav --depart "wed 08:00"
opennav score -v                        # compare with every stored Google response
opennav calibrate                       # refit engine/params.json to all stored cases
```

## Visual review: `opennav serve`

```bash
opennav serve                 # http://localhost:8765, opens a browser tab
opennav serve --warm smyrna-to-atl --port 9000 --no-browser
```

A local web app for comparing the official (Google) answer with our model,
case by case. The **Official vs modeled** page draws both answers and their
alternates on one map (or on two synced maps side by side), marks where the
recommended paths split, and has tabs for the numbers (time, free-flow time,
distance, roads, warnings, traffic notes), every route and how they pair up,
the turn-by-turn steps in two columns (click a step to see it on the map),
and the score metric by metric. **Re-run model** recomputes our side after an
engine or params change. The URL keeps the page state
(`#/compare?case=smyrna-to-atl&tab=steps&map=split`).

It binds to 127.0.0.1 only and reads ground truth from the local data dir, so
nothing leaves the machine. Only Python is needed to run it: the built web app
ships in `opennav/viewer/static/`. The source is the React app in `web/`
(see [web/README.md](web/README.md)); it is structured like
[MonoRail](https://github.com/wojoe-444/MonoRail) and adding a view is a new
module or panel.

### Scoring against ground truth

`opennav score` runs our engine on every case that has a stored Google response
(same endpoints and departure time) and scores 0-100 on: path overlap with
Google's route, duration with traffic, free-flow duration, distance, road
summary, steps (roads named, maneuvers, count), warnings, alternates found, and
route ranking. Reports go to `<data dir>/reports/`. To add a test case, add
`cases/<id>.json` and run `opennav case run <id>` once to store Google's answer
locally.

Geocoding: the scorer uses Google's resolved endpoints so routing is measured
on its own. `opennav/geocode.py` covers addresses present in Overture's
address points (City of Atlanta yes, most of Cobb County not yet).

## Design

```
opennav/
  models.py          provider-neutral types: RouteRequest, Route, Step, RouteResult
  providers/
    base.py          RoutingProvider: fetch_raw() (network) + parse() (pure)
    google_routes.py Google Routes API, used as ground truth while piloting
    osrm.py          OSRM (OpenStreetMap), needs an OSRM server
    opennav_local.py our own engine as a provider
  engine/            graph builder, cost/traffic model, search, guidance, map matching
  data/              Overture download over HTTPS, region registry
  scoring.py         metrics vs ground truth; bench.py runs all cases
  calibrate.py       fits engine/params.json to ground truth
  traffic.py         congestion by road, per-step delay estimates, route comparison notes
  cases.py           named test cases + stored provider responses + reference checks
  render.py          text panel, GeoJSON, standalone Leaflet map
  viewer/            `opennav serve`: comparison payloads, local HTTP + JSON API, built web app
  cli.py             `opennav` command
web/                 React review app (Vite, Tailwind, shadcn/ui), builds into opennav/viewer/static
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
