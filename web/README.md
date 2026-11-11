# OpenNav web app

The review UI that `opennav serve` hosts on localhost. It is built like
MonoRail's `apps/command-hub` (wojoe-444/MonoRail) and reuses its UI: React 19,
Vite, TypeScript, Tailwind CSS v4 and shadcn/ui, with MonoRail's drawer, top
bar, color schemes (Settings > Appearance) and module registry.

## Run it

```bash
# terminal 1: the API (and the last built UI) on http://localhost:8765
opennav serve --no-browser

# terminal 2: the UI with hot reload on http://localhost:5173 (proxies /api to 8765)
cd web
npm install
npm run dev
```

`npm run build` type-checks and writes the bundle to `../opennav/viewer/static/`,
which is committed so that running the viewer needs only Python. Rebuild and
commit it with every UI change. `npm run lint` runs oxlint.

## Layout

| Path | What it is |
| --- | --- |
| `src/App.tsx` | Shell: drawer, top bar, the current module's page |
| `src/modules/registry.ts` | Every module, in nav order |
| `src/modules/<id>/` | One module: `index.ts` (its `ModuleDefinition`) and its page |
| `src/modules/compare/panels/` | Tabs of the Official vs modeled page |
| `src/modules/client.ts` | `useQuery`: loads API data, keeps old data while refetching |
| `src/lib/api.ts` | Typed calls to the Python API; shapes mirror `opennav/viewer/compare.py` |
| `src/components/map/RouteMap.tsx` | Leaflet map of polylines and pins (OpenStreetMap tiles, dimmed in dark mode) |
| `src/components/ui/`, `layout/`, `theme/`, `src/lib/` | Taken from MonoRail |

## Adding a view

- **A new tab on the compare page:** write a component that takes `PanelProps`
  (the comparison payload, the focused route or step, `zoomTo`) and add it to
  `PANELS` in `src/modules/compare/panels/index.ts`.
- **A new page:** create `src/modules/<id>/index.ts` exporting a
  `ModuleDefinition` (title, icon, path, nav section, lazy page) and add it to
  `src/modules/registry.ts`. The nav and top bar pick it up.
- **New data:** compute it in Python. Add a key to the payload in
  `opennav/viewer/compare.py`, or a new endpoint in `opennav/viewer/server.py`
  (a method on `Api` plus a line in `ROUTES`), then type it in `src/lib/api.ts`.
- **Another model to compare against:** add an entry to `MODELS` in
  `opennav/viewer/compare.py`.

Ground truth stays in the local data dir. Never put official responses in
this folder or in the built bundle.
