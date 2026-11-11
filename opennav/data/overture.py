"""Extract Overture Maps transportation data (OpenStreetMap-derived, ODbL) for a bbox.

Overture publishes the OSM road network as GeoParquet on a public S3 bucket.
We read Parquet footers over HTTPS, keep only row groups whose bbox statistics
intersect the area we need, and save the road segments to a local cache
(not committed). See `opennav data fetch`.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .s3http import HTTPRangeFile, list_objects, list_prefixes

BUCKET = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"

SEGMENT_COLUMNS = [
    "id", "names", "subtype", "class", "subclass", "subclass_rules", "connectors",
    "road_surface", "road_flags", "level_rules", "access_restrictions", "speed_limits",
    "prohibited_transitions", "routes", "destinations", "geometry", "bbox",
]


def latest_release() -> str:
    rels = [p.rstrip("/").split("/")[-1] for p in list_prefixes(BUCKET, "release/")]
    return sorted(rels)[-1]


def _rg_stats(md, rg: int) -> dict[str, tuple[float, float]]:
    out = {}
    g = md.row_group(rg)
    for i in range(g.num_columns):
        c = g.column(i)
        if c.path_in_schema.startswith("bbox.") and c.statistics is not None and c.statistics.has_min_max:
            out[c.path_in_schema[5:]] = (c.statistics.min, c.statistics.max)
    return out


def _intersects(st, bbox) -> bool:
    w, s, e, n = bbox
    if not st:
        return True
    return not (st["xmin"][0] > e or st["xmax"][1] < w or st["ymin"][0] > n or st["ymax"][1] < s)


def _scan_file(key: str, size: int, bbox, columns):
    f = HTTPRangeFile(f"{BUCKET}/{key}", size)
    pf = pq.ParquetFile(f)
    md = pf.metadata
    keep = [i for i in range(md.num_row_groups) if _intersects(_rg_stats(md, i), bbox)]
    if not keep:
        return None, f.bytes_fetched
    tables = []
    w, s, e, n = bbox
    for rg in keep:
        t = pf.read_row_group(rg, columns=columns)
        b = t.column("bbox")
        mask = pc.and_(
            pc.and_(pc.less_equal(pc.struct_field(b, "xmin"), e), pc.greater_equal(pc.struct_field(b, "xmax"), w)),
            pc.and_(pc.less_equal(pc.struct_field(b, "ymin"), n), pc.greater_equal(pc.struct_field(b, "ymax"), s)),
        )
        t = t.filter(mask)
        if "subtype" in t.column_names:
            t = t.filter(pc.equal(t.column("subtype"), "road"))
        if t.num_rows:
            tables.append(t)
    return (pa.concat_tables(tables) if tables else None), f.bytes_fetched


ADDRESS_COLUMNS = ["id", "number", "street", "unit", "postcode", "postal_city", "address_levels", "country",
                   "geometry", "bbox"]


def fetch_segments(bbox: tuple[float, float, float, float], out: Path, release: str | None = None,
                   log=print) -> Path:
    """Download road segments intersecting bbox=(west, south, east, north) to a Parquet file."""
    return fetch("transportation", "segment", SEGMENT_COLUMNS, bbox, out, release, log)


def fetch_addresses(bbox: tuple[float, float, float, float], out: Path, release: str | None = None,
                    log=print) -> Path:
    """Download address points (for geocoding) intersecting bbox to a Parquet file."""
    return fetch("addresses", "address", ADDRESS_COLUMNS, bbox, out, release, log)


def fetch(theme: str, type_: str, columns: list[str], bbox, out: Path, release: str | None = None,
          log=print) -> Path:
    release = release or latest_release()
    objs = list_objects(BUCKET, f"release/{release}/theme={theme}/type={type_}/")
    log(f"Overture {release}: scanning {len(objs)} {type_} files for bbox {bbox}")
    tables, fetched = [], 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        for t, nbytes in ex.map(lambda o: _scan_file(o[0], o[1], bbox, columns), objs):
            fetched += nbytes
            if t is not None:
                tables.append(t)
    table = pa.concat_tables(tables, promote_options="permissive")
    table = table.replace_schema_metadata({**(table.schema.metadata or {}),
                                           b"opennav_release": release.encode(),
                                           b"opennav_bbox": ",".join(map(str, bbox)).encode()})
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd")
    log(f"saved {table.num_rows} {type_} rows to {out} ({fetched / 1e6:.0f} MB downloaded)")
    return out
