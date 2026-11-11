"""Directed road graph built from Overture (OpenStreetMap-derived) road segments.

Each Overture segment is split at its connectors into pieces; each piece becomes
one or two directed edges depending on one-way rules. Everything is stored in
flat numpy arrays so a metro-sized graph (~1M edges) builds in seconds and
loads instantly from the local cache.
"""
from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

EARTH_R = 6371008.8

# Drivable classes and their integer codes (order = importance, low is bigger).
CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
           "residential", "living_street", "service", "unknown"]
CLASS_CODE = {c: i for i, c in enumerate(CLASSES)}
MOTORWAY, TRUNK, PRIMARY, SECONDARY, TERTIARY, UNCLASSIFIED, RESIDENTIAL, LIVING, SERVICE, UNKNOWN = range(len(CLASSES))

# Edge flags
F_LINK = 1          # ramp / slip road
F_RESTRICTED = 2    # destination-only, private, customers, permit
F_PARKING = 4       # parking aisle / driveway / drive-through
F_TIMED = 8         # closed at certain times (conditional access)
F_TOLL = 16
F_TUNNEL = 32
F_BRIDGE = 64
F_ROUNDABOUT = 128

CAR_MODES = {"motor_vehicle", "car", "vehicle"}
RESTRICTING_USING = {"at_destination", "as_customer", "to_deliver", "to_farm"}
RESTRICTING_RECOGNIZED = {"as_private", "as_permitted", "as_employee", "as_customer"}


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    x = np.sin(dl) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(x, y)) + 360.0) % 360.0


def _wkb_linestring(b: bytes) -> np.ndarray:
    """Parse a 2D WKB LineString into an (n, 2) array of (lon, lat)."""
    if b[0] != 1:
        raise ValueError("big-endian WKB not supported")
    gtype = int.from_bytes(b[1:5], "little")
    dims = 3 if (gtype & 0xFFFF) in (1002,) or gtype & 0x80000000 else 2
    n = int.from_bytes(b[5:9], "little")
    return np.frombuffer(b, dtype="<f8", count=n * dims, offset=9).reshape(n, dims)[:, :2]


def _applies(between, frac: float) -> bool:
    return not between or (between[0] - 1e-9 <= frac <= between[1] + 1e-9)


def _heading_ok(when, direction: str) -> bool:
    h = (when or {}).get("heading")
    return h is None or h == direction


def _car_mode(when) -> bool | None:
    """True if the rule names a car mode, None if it names no mode, False otherwise."""
    modes = (when or {}).get("mode")
    if not modes:
        return None
    return bool(set(modes) & CAR_MODES)


def car_access(rules, frac: float, direction: str) -> tuple[bool, int]:
    """Evaluate Overture access rules for a private car. Returns (allowed, flags)."""
    allowed, flags = True, 0
    for r in rules or []:
        when = r.get("when") or {}
        if not _applies(r.get("between"), frac) or not _heading_ok(when, direction):
            continue
        cm = _car_mode(when)
        if cm is False:
            continue
        if when.get("vehicle"):
            continue  # weight/height limits: assume a passenger car passes
        conditional = bool(when.get("using") or when.get("recognized"))
        if r["access_type"] == "denied":
            if when.get("during"):
                flags |= F_TIMED
                continue
            if not conditional:
                allowed = False
        else:  # allowed / designated
            if conditional:
                using = set(when.get("using") or [])
                rec = set(when.get("recognized") or [])
                if using & RESTRICTING_USING or rec & RESTRICTING_RECOGNIZED:
                    flags |= F_RESTRICTED
                    allowed = True
            elif cm is True:
                allowed = True
    return allowed, flags


def _speed_limit_kph(rules, frac: float, direction: str) -> float:
    best = math.nan
    for r in rules or []:
        when = r.get("when") or {}
        if not _applies(r.get("between"), frac) or not _heading_ok(when, direction):
            continue
        if when.get("during") or when.get("vehicle") or (when.get("mode") and not set(when["mode"]) & CAR_MODES):
            continue
        ms = r.get("max_speed")
        if ms and ms.get("value"):
            v = float(ms["value"]) * (1.609344 if ms.get("unit") == "mph" else 1.0)
            best = v if math.isnan(best) else min(best, v)
    return best


def _route_ref(network: str | None, ref: str | None) -> str | None:
    if not ref:
        return None
    net = (network or "").upper()
    if net == "US:I" or net.startswith("US:I:"):
        return f"I-{ref}"
    if net == "US:US" or net.startswith("US:US:"):
        return f"US-{ref}"
    if net.startswith("US:") and len(net) == 5:  # US:GA etc.
        return f"{net[3:]}-{ref}"
    return None  # county roads and the like are rarely signed in instructions


def _ref_rank(ref: str) -> tuple:
    kind = {"I": 0, "US": 1}.get(ref.split("-")[0], 2)
    num = "".join(ch for ch in ref.split("-", 1)[-1] if ch.isdigit())
    return (kind, int(num) if num else 0)


@dataclass
class RoadGraph:
    # nodes
    node_lat: np.ndarray
    node_lon: np.ndarray
    # directed edges
    src: np.ndarray
    dst: np.ndarray
    length_m: np.ndarray
    cls: np.ndarray
    flags: np.ndarray
    speed_limit_kph: np.ndarray  # NaN when unknown
    name_idx: np.ndarray         # -1 = unnamed
    ref_idx: np.ndarray          # -1 = no signed route
    seg_idx: np.ndarray          # Overture segment index
    piece_idx: np.ndarray        # piece number within segment
    forward: np.ndarray          # True if edge runs along the segment's digitized direction
    geom_off: np.ndarray         # offsets into geom (len = n_edges + 1)
    geom: np.ndarray             # (k, 2) lat, lon, edge geometry in travel direction
    bearing_start: np.ndarray
    bearing_end: np.ndarray
    names: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    seg_ids: list[str] = field(default_factory=list)
    # destination signs: (from_edge, to_edge) -> label text
    signs: dict = field(default_factory=dict)
    # prohibited single-hop transitions: set of (from_edge, to_edge)
    banned: set = field(default_factory=set)
    meta: dict = field(default_factory=dict)

    @property
    def n_nodes(self) -> int:
        return len(self.node_lat)

    @property
    def n_edges(self) -> int:
        return len(self.src)

    def edge_geom(self, e: int) -> np.ndarray:
        return self.geom[self.geom_off[e]:self.geom_off[e + 1]]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def load(path: Path) -> "RoadGraph":
        with open(path, "rb") as f:
            return pickle.load(f)


def _split_line(coords: np.ndarray, cum: np.ndarray, fracs: list[float]) -> list[np.ndarray]:
    """Split a polyline (lon, lat) at length fractions; returns pieces between consecutive fracs."""
    total = cum[-1]
    pieces = []
    for a, b in zip(fracs[:-1], fracs[1:]):
        da, db = a * total, b * total
        ia = int(np.searchsorted(cum, da, side="right"))
        ib = int(np.searchsorted(cum, db, side="left"))

        def interp(d):
            i = int(np.clip(np.searchsorted(cum, d, side="right") - 1, 0, len(cum) - 2))
            seg = cum[i + 1] - cum[i]
            t = 0.0 if seg <= 0 else (d - cum[i]) / seg
            return coords[i] + t * (coords[i + 1] - coords[i])

        pts = [interp(da)] + [coords[i] for i in range(ia, ib)] + [interp(db)]
        pieces.append(np.array(pts))
    return pieces


def build_graph(segments_parquet: Path, log=print) -> RoadGraph:
    cols = ["id", "names", "class", "subclass", "connectors", "road_flags", "access_restrictions",
            "speed_limits", "prohibited_transitions", "routes", "destinations", "geometry"]
    table = pq.read_table(segments_parquet, columns=cols)
    rows = table.to_pylist()
    log(f"building graph from {len(rows)} segments")

    node_index: dict[str, int] = {}
    node_ll: list[tuple[float, float]] = []
    names: list[str] = []
    name_ix: dict[str, int] = {}
    refs: list[str] = []
    ref_ix: dict[str, int] = {}
    seg_ids: list[str] = []

    E = {k: [] for k in ["src", "dst", "len", "cls", "flags", "spd", "name", "ref", "seg", "piece", "fwd"]}
    geoms: list[np.ndarray] = []
    # (seg_idx, connector_id) -> list of (edge, is_incoming)
    seg_conn_edges: dict[tuple[int, str], list[tuple[int, bool]]] = {}
    pending_dest = []
    pending_ban = []

    def intern(table_, ix, s):
        if s is None:
            return -1
        if s not in ix:
            ix[s] = len(table_)
            table_.append(s)
        return ix[s]

    for r in rows:
        c = r["class"]
        if c not in CLASS_CODE:
            continue
        conns = r["connectors"] or []
        if len(conns) < 2:
            continue
        try:
            coords = _wkb_linestring(r["geometry"])
        except ValueError:
            continue
        if len(coords) < 2:
            continue
        seg_i = len(seg_ids)
        seg_ids.append(r["id"])
        sub = r["subclass"]
        base_flags = 0
        if sub == "link":
            base_flags |= F_LINK
        if sub in ("parking_aisle", "driveway", "drive_through"):
            base_flags |= F_PARKING
        seglen = haversine(coords[:-1, 1], coords[:-1, 0], coords[1:, 1], coords[1:, 0])
        cum = np.concatenate([[0.0], np.cumsum(seglen)])
        conns = sorted(conns, key=lambda x: x["at"])
        fracs = [float(x["at"]) for x in conns]
        pieces = _split_line(coords, cum, fracs)
        name = (r["names"] or {}).get("primary")
        rr = []
        for rt in r["routes"] or []:
            x = _route_ref(rt.get("network"), rt.get("ref"))
            if x and x not in rr:
                rr.append(x)
        rr.sort(key=_ref_rank)
        ref = "/".join(rr) or None
        n_i = intern(names, name_ix, name)
        r_i = intern(refs, ref_ix, ref)
        for pi, piece in enumerate(pieces):
            a, b = conns[pi]["connector_id"], conns[pi + 1]["connector_id"]
            if a == b:
                continue
            mid = 0.5 * (fracs[pi] + fracs[pi + 1])
            flags = base_flags
            for rf in r["road_flags"] or []:
                if _applies(rf.get("between"), mid):
                    v = set(rf.get("values") or [])
                    if "is_tunnel" in v:
                        flags |= F_TUNNEL
                    if "is_bridge" in v:
                        flags |= F_BRIDGE
            plen = float(haversine(piece[:-1, 1], piece[:-1, 0], piece[1:, 1], piece[1:, 0]).sum())
            if plen <= 0.01:
                continue
            for u_id, v_id in ((a, b),):
                if u_id not in node_index:
                    node_index[u_id] = len(node_ll)
                    node_ll.append((piece[0, 1], piece[0, 0]))
                if v_id not in node_index:
                    node_index[v_id] = len(node_ll)
                    node_ll.append((piece[-1, 1], piece[-1, 0]))
            for direction, (u_id, v_id), g in (("forward", (a, b), piece), ("backward", (b, a), piece[::-1])):
                ok, aflags = car_access(r["access_restrictions"], mid, direction)
                if not ok:
                    continue
                e = len(E["src"])
                E["src"].append(node_index[u_id])
                E["dst"].append(node_index[v_id])
                E["len"].append(plen)
                E["cls"].append(CLASS_CODE[c])
                E["flags"].append(flags | aflags)
                E["spd"].append(_speed_limit_kph(r["speed_limits"], mid, direction))
                E["name"].append(n_i)
                E["ref"].append(r_i)
                E["seg"].append(seg_i)
                E["piece"].append(pi)
                E["fwd"].append(direction == "forward")
                geoms.append(np.ascontiguousarray(g[:, ::-1]))  # -> (lat, lon)
                seg_conn_edges.setdefault((seg_i, u_id), []).append((e, False))
                seg_conn_edges.setdefault((seg_i, v_id), []).append((e, True))
        for d in r["destinations"] or []:
            pending_dest.append((seg_i, d))
        for pt in r["prohibited_transitions"] or []:
            pending_ban.append((seg_i, pt))

    seg_lookup = {s: i for i, s in enumerate(seg_ids)}

    def edges_at(seg_i, conn, incoming: bool):
        return [e for e, inc in seg_conn_edges.get((seg_i, conn), []) if inc == incoming]

    signs = {}
    for seg_i, d in pending_dest:
        to_seg = seg_lookup.get(d.get("to_segment_id"))
        if to_seg is None:
            continue
        labels = d.get("labels") or []
        text = _sign_text(labels)
        if not text:
            continue
        fc, tc = d.get("from_connector_id"), d.get("to_connector_id")
        for fe in edges_at(seg_i, fc, True):
            for te in edges_at(to_seg, tc, False):
                signs[(fe, te)] = text
    banned = set()
    for seg_i, pt in pending_ban:
        seq = pt.get("sequence") or []
        if len(seq) != 1 or (pt.get("when") or {}).get("during"):
            continue
        cm = _car_mode(pt.get("when"))
        if cm is False:
            continue
        hop = seq[0]
        to_seg = seg_lookup.get(hop.get("segment_id"))
        if to_seg is None:
            continue
        heading = (pt.get("when") or {}).get("heading")
        for fe in edges_at(seg_i, hop.get("connector_id"), True):
            if heading and (heading == "forward") != bool(E["fwd"][fe]):
                continue
            for te in edges_at(to_seg, hop.get("connector_id"), False):
                fh = pt.get("final_heading")
                if fh and (fh == "forward") != bool(E["fwd"][te]):
                    continue
                banned.add((fe, te))

    off = np.zeros(len(geoms) + 1, dtype=np.int64)
    off[1:] = np.cumsum([len(g) for g in geoms])
    geom = np.concatenate(geoms) if geoms else np.zeros((0, 2))
    starts = geom[off[:-1]]
    seconds = geom[off[:-1] + 1]
    lasts = geom[off[1:] - 1]
    pens = geom[off[1:] - 2]
    nl = np.array(node_ll)
    g = RoadGraph(
        node_lat=nl[:, 0], node_lon=nl[:, 1],
        src=np.array(E["src"], dtype=np.int32), dst=np.array(E["dst"], dtype=np.int32),
        length_m=np.array(E["len"]), cls=np.array(E["cls"], dtype=np.int8),
        flags=np.array(E["flags"], dtype=np.int32), speed_limit_kph=np.array(E["spd"]),
        name_idx=np.array(E["name"], dtype=np.int32), ref_idx=np.array(E["ref"], dtype=np.int32),
        seg_idx=np.array(E["seg"], dtype=np.int32), piece_idx=np.array(E["piece"], dtype=np.int16),
        forward=np.array(E["fwd"], dtype=bool), geom_off=off, geom=geom,
        bearing_start=bearing(starts[:, 0], starts[:, 1], seconds[:, 0], seconds[:, 1]),
        bearing_end=bearing(pens[:, 0], pens[:, 1], lasts[:, 0], lasts[:, 1]),
        names=names, refs=refs, seg_ids=seg_ids, signs=signs, banned=banned,
        meta=dict(table.schema.metadata and {k.decode(): v.decode() for k, v in table.schema.metadata.items()
                                             if k.startswith(b"opennav")} or {}),
    )
    log(f"graph: {g.n_nodes} nodes, {g.n_edges} directed edges, {len(signs)} signed transitions, "
        f"{len(banned)} turn restrictions")
    return g


def _sign_text(labels) -> str | None:
    refs, towards, places = [], [], []
    for lab in labels:
        v = (lab.get("value") or "").strip()
        if not v:
            continue
        t = lab.get("type")
        if t == "route_ref":
            refs.append(_format_sign_ref(v))
        elif t == "toward_route_ref":
            towards.append(_format_sign_ref(v))
        else:
            places.append(v)
    parts = []
    if refs:
        parts.append("/".join(refs))
    tow = towards + places
    if tow:
        parts.append("toward " + "/".join(tow))
    return " ".join(parts) or None


_DIRS = {"north": "N", "south": "S", "east": "E", "west": "W"}


def _format_sign_ref(v: str) -> str:
    """'I 85 South' -> 'I-85 S', 'US 41' -> 'US-41', 'GA 139' -> 'GA-139'."""
    toks = v.replace("-", " ").split()
    if len(toks) >= 2 and toks[1][:1].isdigit():
        out = f"{toks[0]}-{toks[1]}"
        if len(toks) >= 3 and toks[2].lower() in _DIRS:
            out += " " + _DIRS[toks[2].lower()]
        return out
    return v
