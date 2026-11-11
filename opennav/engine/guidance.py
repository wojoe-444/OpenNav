"""Turn a path (list of directed edges) into maps-app style guidance.

Produces Google-like steps ("Turn right onto US-41 S/Cobb Pkwy", "Merge onto
I-285 W", "Take the exit toward Domestic Airport"), a short road summary
("I-75 S and I-85 S"), warnings and per-step notes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from ..models import Step
from .graph import (F_LINK, F_RESTRICTED, F_TIMED, MOTORWAY, SECONDARY, TRUNK, RoadGraph, bearing, haversine)

_SUFFIX = {
    "street": "St", "avenue": "Ave", "road": "Rd", "drive": "Dr", "parkway": "Pkwy", "court": "Ct",
    "boulevard": "Blvd", "lane": "Ln", "place": "Pl", "highway": "Hwy", "circle": "Cir", "trail": "Trl",
    "terrace": "Ter", "freeway": "Fwy", "expressway": "Expy", "square": "Sq", "point": "Pt",
    "crossing": "Xing", "connector": "Connector", "pike": "Pike", "run": "Run", "way": "Way",
}
_DIRWORD = {"north": "N", "south": "S", "east": "E", "west": "W", "northeast": "NE", "northwest": "NW",
            "southeast": "SE", "southwest": "SW"}
CARDINALS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def abbreviate(name: str, keep_dir_suffix: bool = True) -> str:
    words = name.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in _DIRWORD and (i == 0 or i == len(words) - 1) and len(words) > 1:
            if i == len(words) - 1 and not keep_dir_suffix:
                continue
            out.append(_DIRWORD[lw])
        elif lw in _SUFFIX and i >= 1 and (i == len(words) - 1 or words[i + 1].lower() in _DIRWORD):
            out.append(_SUFFIX[lw])
        else:
            out.append(w)
    return " ".join(out)


def display_refs(ref: str | None) -> list[str]:
    if not ref:
        return []
    refs = ref.split("/")
    for prefix in ("I-", "US-"):
        sel = [r for r in refs if r.startswith(prefix)]
        if sel:
            return sel
    return refs[:1]


def ref_direction(ref: str, brg: float) -> str:
    """Cardinal letter for a signed route given the travel bearing (degrees)."""
    num = int(re.sub(r"\D", "", ref) or 0)
    ns = abs(np.cos(np.radians(brg)))
    ew = abs(np.sin(np.radians(brg)))
    if abs(ns - ew) < 0.25 and num:  # ambiguous diagonal: use US numbering convention
        use_ns = num % 2 == 1
    else:
        use_ns = ns > ew
    if use_ns:
        return "N" if np.cos(np.radians(brg)) > 0 else "S"
    return "E" if np.sin(np.radians(brg)) > 0 else "W"


@dataclass
class Run:
    """Consecutive edges travelled on the same road."""
    edges: list[int]
    key: str            # identity used to detect road changes
    label: str          # display name, e.g. "US-41 S/Cobb Pkwy"
    refs: list[str]     # e.g. ["I-75 S", "I-85 S"]
    name: str | None
    is_link: bool
    cls: int
    length: float = 0.0
    time: float = 0.0
    sign: str | None = None
    notes: list[str] = field(default_factory=list)
    entry: int = 0      # edges before this index are a slip lane leading onto the road


def _cardinal(brg: float) -> str:
    return CARDINALS[int(((brg + 22.5) % 360) // 45)]


class Guidance:
    def __init__(self, g: RoadGraph):
        self.g = g

    def _edge_key(self, e: int) -> tuple[str | None, str | None, bool]:
        g = self.g
        ref = g.refs[g.ref_idx[e]] if g.ref_idx[e] >= 0 else None
        name = g.names[g.name_idx[e]] if g.name_idx[e] >= 0 else None
        return ref, name, bool(g.flags[e] & F_LINK)

    def _stretch_bearing(self, edges: list[int], max_m: float = 3000.0) -> float:
        g = self.g
        acc, pts = 0.0, []
        for e in edges:
            geo = g.edge_geom(e)
            pts.append(geo)
            acc += g.length_m[e]
            if acc >= max_m:
                break
        pts = np.concatenate(pts)
        return float(bearing(pts[0, 0], pts[0, 1], pts[-1, 0], pts[-1, 1]))

    def runs(self, edges: list[int], times: np.ndarray, lengths: np.ndarray) -> list[Run]:
        g = self.g
        runs: list[Run] = []
        for i, e in enumerate(edges):
            ref, name, link = self._edge_key(e)
            # a signed route keeps its identity even when the street name varies along it
            key = f"R:{ref}|{int(link)}" if ref and not link else f"N:{name or ''}|{int(link)}"
            # unnamed non-link pieces (e.g. a short connector) continue the current run
            if runs and not ref and not name and not link and lengths[i] < 120:
                key = runs[-1].key
            if runs and runs[-1].key == key and not self._is_turn(edges[i - 1], e):
                r = runs[-1]
            else:
                r = Run(edges=[], key=key, label="", refs=[], name=name, is_link=link, cls=int(g.cls[e]))
                runs.append(r)
            r.edges.append(e)
            r.length += float(lengths[i])
            r.time += float(times[i])
        return runs

    def label_runs(self, runs: list[Run]) -> None:
        g = self.g
        for k, r in enumerate(runs):
            core = [e for e in r.edges if not (g.flags[e] & F_LINK)] or r.edges
            # dominant name/ref by length
            by_name: dict = {}
            for e in core:
                by_name[self._edge_key(e)[1]] = by_name.get(self._edge_key(e)[1], 0.0) + g.length_m[e]
            name = max(by_name, key=by_name.get) if by_name else None
            ref = self._edge_key(core[0])[0]
            r.cls = int(min(g.cls[e] for e in core))
            r.is_link = all(g.flags[e] & F_LINK for e in r.edges)
            brg = self._stretch_bearing(core)
            signed = self._signed_directions(runs, k)
            refs = []
            for x in display_refs(ref):
                d = signed.get(x) or ref_direction(x, brg)
                refs.append(f"{x} {d}")
            nm = abbreviate(name, keep_dir_suffix=r.cls == SECONDARY) if name else None
            r.refs = refs
            r.name = nm
            if r.cls == MOTORWAY and refs:
                r.label = "/".join(refs)
            elif refs and nm:
                r.label = "/".join(refs) + "/" + nm
            else:
                r.label = "/".join(refs) or nm or ""
            r.notes = []
            restricted = sum(g.length_m[e] for e in r.edges if g.flags[e] & F_RESTRICTED)
            if restricted > 0.5 * sum(g.length_m[e] for e in r.edges):
                r.notes.append("Restricted usage road")
            if any(g.flags[e] & F_TIMED for e in r.edges):
                r.notes.append("Parts of this road may be closed at certain times or days")

    def _signed_directions(self, runs: list[Run], k: int) -> dict[str, str]:
        """Directions printed on the signs that lead onto run k ('I-285' -> 'W')."""
        g = self.g
        out: dict[str, str] = {}
        r = runs[k]
        lead = []
        if k > 0:
            prev = runs[k - 1]
            lead = prev.edges[-8:] + r.edges[:3]
        else:
            lead = r.edges[:3]
        for a, b in zip(lead[:-1], lead[1:]):
            s = g.signs.get((a, b))
            if not s:
                continue
            for m in re.finditer(r"\b((?:I|US|[A-Z]{2})-\d+[A-Z]?) ([NSEW])\b", s):
                out.setdefault(m.group(1), m.group(2))
        return out

    def _turn_angle(self, e_in: int, e_out: int) -> float:
        g = self.g
        return float((g.bearing_start[e_out] - g.bearing_end[e_in] + 540.0) % 360.0 - 180.0)

    def _is_turn(self, e_in: int, e_out: int) -> bool:
        """A sharp direction change at a real intersection splits a run even on the same road."""
        g = self.g
        if g.seg_idx[e_in] == g.seg_idx[e_out]:
            return False
        a = abs(self._turn_angle(e_in, e_out))
        return a > 60 and self._out_degree(g.dst[e_in]) > 1

    def _out_degree(self, node: int) -> int:
        if not hasattr(self, "_outdeg"):
            self._outdeg = np.bincount(self.g.src, minlength=self.g.n_nodes)
        return int(self._outdeg[node])

    def _alt_angles(self, e_in: int, e_out: int) -> list[float]:
        """Angles of the other drivable exits at the intersection (for keep/fork wording)."""
        g = self.g
        node = g.dst[e_in]
        if not hasattr(self, "_out_by_node"):
            order = np.argsort(g.src, kind="stable")
            counts = np.bincount(g.src, minlength=g.n_nodes)
            self._out_start = np.concatenate([[0], np.cumsum(counts)])
            self._out_order = order
        outs = self._out_order[self._out_start[node]:self._out_start[node + 1]]
        res = []
        for o in outs:
            if o == e_out or (g.seg_idx[o] == g.seg_idx[e_in] and g.piece_idx[o] == g.piece_idx[e_in]):
                continue
            res.append(self._turn_angle(e_in, int(o)))
        return res

    # ---- steps
    def steps(self, edges: list[int], times: np.ndarray, static_times: np.ndarray, lengths: np.ndarray,
              dest_side: str | None = None) -> list[Step]:
        g = self.g
        runs = self._merge_runs(self.runs(edges, times, lengths))
        self.label_runs(runs)
        self.last_runs = runs  # needed by _filter_sign
        steps: list[Step] = []
        st_by_edge = dict(zip(edges, static_times))
        for i, r in enumerate(runs):
            if i == 0:
                brg = self._stretch_bearing(r.edges, 200)
                instr = f"Head {_cardinal(brg)}" + (f" on {r.label}" if r.label else "")
                man = "DEPART"
            else:
                instr, man = self._maneuver(runs[i - 1], r)
            notes = list(r.notes)
            if i == len(runs) - 1 and dest_side:
                notes.append(f"Destination will be on the {dest_side}")
            geo = np.concatenate([g.edge_geom(e) for e in r.edges])
            steps.append(Step(
                instruction=instr, distance_m=r.length, duration_s=r.time,
                static_duration_s=float(sum(st_by_edge[e] for e in r.edges)),
                maneuver=man, road=r.label or None, notes=notes,
                geometry=[(float(a), float(b)) for a, b in geo],
            ))
        return steps

    def _merge_runs(self, runs: list[Run]) -> list[Run]:
        """Fold short unnamed pieces into neighbours, join ramp chains, and treat short
        slip lanes between ordinary streets as part of the turn onto the next street."""
        g = self.g

        def absorb(dst: Run, src: Run, front: bool = False) -> None:
            dst.edges = src.edges + dst.edges if front else dst.edges + src.edges
            dst.length += src.length
            dst.time += src.time

        out: list[Run] = []
        for r in runs:
            if out and r.is_link and out[-1].is_link:
                absorb(out[-1], r)
                continue
            if out and not r.key.startswith("R:") and r.key.startswith("N:|") and not r.is_link and r.length < 60:
                absorb(out[-1], r)
                continue
            out.append(r)
        # slip lanes: a short link between two non-highway runs belongs to the next run
        res: list[Run] = []
        i = 0
        while i < len(out):
            r = out[i]
            if (r.is_link and r.length < 250 and 0 < i < len(out) - 1 and r.cls > TRUNK
                    and out[i - 1].cls > TRUNK and out[i + 1].cls > TRUNK and not out[i + 1].is_link):
                nxt = out[i + 1]
                absorb(nxt, r, front=True)
                nxt.entry = len(r.edges)  # index of the first edge of the street itself
                i += 1
                continue
            res.append(r)
            i += 1
        # merge consecutive runs that ended up on the same signed road / name
        final: list[Run] = []
        for r in res:
            if final and final[-1].key == r.key and not r.is_link:
                absorb(final[-1], r)
                continue
            final.append(r)
        return final

    def _sign_between(self, a: Run, b: Run) -> str | None:
        g = self.g
        s = g.signs.get((a.edges[-1], b.edges[0]))
        if s:
            return s
        for k in range(min(len(b.edges) - 1, 6)):
            s = g.signs.get((b.edges[k], b.edges[k + 1]))
            if s:
                return s
        return None

    def _filter_sign(self, sign: str, link: Run) -> str:
        """An exit sign often lists both directions ('I-85 N/I-85 S toward ...'); keep the one we take."""
        runs = self.last_runs if hasattr(self, "last_runs") else []
        nxt = None
        for k, r in enumerate(runs):
            if r is link and k + 1 < len(runs):
                nxt = runs[k + 1]
        if nxt is None or not nxt.refs:
            return sign
        head, sep, tail = sign.partition(" toward ")
        if head.startswith("toward"):
            return sign
        refs = head.split("/")
        keep = [r for r in refs if r in nxt.refs] or [r for r in refs if r.split()[0] in {x.split()[0] for x in nxt.refs}]
        if keep and len(keep) < len(refs):
            head = "/".join(keep)
        return head + (sep + tail if sep else "")

    def _maneuver(self, prev: Run, cur: Run) -> tuple[str, str]:
        entry = cur.edges[min(cur.entry, len(cur.edges) - 1)]
        if cur.entry:
            g = self.g
            ang = float((g.bearing_start[entry] - g.bearing_end[prev.edges[-1]] + 540.0) % 360.0 - 180.0)
        else:
            ang = self._turn_angle(prev.edges[-1], cur.edges[0])
        others = self._alt_angles(prev.edges[-1], cur.edges[0])
        a = abs(ang)
        side = "right" if ang > 0 else "left"
        sign = self._sign_between(prev, cur)
        label = cur.label
        prev_mw = prev.cls <= TRUNK and not prev.is_link

        if cur.is_link and sign:
            sign = self._filter_sign(sign, cur)
        if cur.is_link:
            toward = f" {sign}" if sign and sign.startswith("toward") else (f" for {sign}" if sign else "")
            if prev_mw:
                return (f"Take the exit{toward}", f"RAMP_{side.upper()}" if a > 5 else "RAMP_RIGHT")
            if prev.is_link:
                fork_side = "left" if all(o > ang for o in others) else "right"
                return (f"Keep {fork_side}" + (f", follow signs{toward}" if sign else ""), f"FORK_{fork_side.upper()}")
            if a < 30:
                return (f"Slight {side}" + (f" (signs{toward})" if sign else ""), f"TURN_SLIGHT_{side.upper()}")
            if cur.refs or sign:
                tgt = sign or "/".join(cur.refs)
                return (f"Take the ramp{toward}" if sign else f"Turn {side} onto the {tgt} ramp", f"RAMP_{side.upper()}")
            return (f"Turn {side}", f"TURN_{side.upper()}")

        if prev.is_link and cur.cls <= TRUNK:
            return (f"Merge onto {label}", "MERGE")

        same = bool(prev.refs and set(prev.refs) & set(cur.refs)) or (prev.name and prev.name == cur.name)
        if a < 20 and not others:
            if same:
                return (f"Continue on {label}", "STRAIGHT")
            return (f"Continue onto {label}", "NAME_CHANGE")
        if a < 30 and others:
            keep = "left" if all(o > ang for o in others) else ("right" if all(o < ang for o in others) else None)
            if keep:
                if same:
                    return (f"Keep {keep} to stay on {label}", f"FORK_{keep.upper()}")
                return (f"Keep {keep}" + (f" onto {label}" if label else ""), f"FORK_{keep.upper()}")
            if same:
                return (f"Continue on {label}", "STRAIGHT")
            return (f"Continue onto {label}" if label else "Continue straight", "NAME_CHANGE")
        if a < 45:
            return (f"Slight {side}" + (f" onto {label}" if label else ""), f"TURN_SLIGHT_{side.upper()}")
        if a < 135:
            if same:
                return (f"Turn {side} to stay on {label}", f"TURN_{side.upper()}")
            return (f"Turn {side}" + (f" onto {label}" if label else ""), f"TURN_{side.upper()}")
        if a < 170:
            return (f"Sharp {side}" + (f" onto {label}" if label else ""), f"TURN_SHARP_{side.upper()}")
        return ("Make a U-turn" + (f" onto {label}" if label else ""), f"UTURN_{side.upper()}")

    # ---- route-level text
    @staticmethod
    def summary_keys(run: Run) -> list[str]:
        """Names a run contributes to the route summary (each concurrent interstate counts)."""
        if run.cls <= TRUNK and run.refs:
            return list(run.refs)
        if run.name:
            return [run.name]
        return run.refs[:1]

    def summary(self, runs: list[Run], total_m: float, min_share: float = 0.25) -> tuple[str, dict[str, float]]:
        acc: dict[str, list] = {}
        for i, r in enumerate(runs):
            if r.is_link:
                continue
            for k in self.summary_keys(r):
                acc.setdefault(k, [0.0, i])[0] += r.length
        major = [(k, v[0], v[1]) for k, v in acc.items() if v[0] >= min_share * total_m]
        if not major and acc:
            k = max(acc, key=lambda k: acc[k][0])
            major = [(k, *acc[k])]
        major = sorted(sorted(major, key=lambda x: -x[1])[:2], key=lambda x: x[2])
        return " and ".join(k for k, _, _ in major), {k: v[0] for k, v in acc.items()}


def warnings_for(g: RoadGraph, edges: list[int]) -> list[str]:
    out = []
    e = np.array(edges)
    if np.any(g.cls[e] == MOTORWAY):
        out.append("This route includes a highway.")
    if np.any(g.flags[e] & F_RESTRICTED):
        out.append("This route has restricted usage or private roads.")
    return out


def destination_side(g: RoadGraph, last_edge: int, lat: float, lon: float, snap_lat: float, snap_lon: float) -> str | None:
    if haversine(lat, lon, snap_lat, snap_lon) < 3:
        return None
    brg = float(g.bearing_end[last_edge])
    to_pt = float(bearing(snap_lat, snap_lon, lat, lon))
    d = (to_pt - brg + 540) % 360 - 180
    return "right" if d > 0 else "left"
