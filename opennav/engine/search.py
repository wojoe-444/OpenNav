"""Edge-based shortest paths with turn costs, plus alternative routes.

The search runs on the line graph: one search node per directed road edge, one
arc per allowed turn (edge -> next edge at the shared intersection). Arc weight
= intersection/turn cost + travel time of the next edge, so turn restrictions
and turn penalties are exact. scipy's C Dijkstra does the heavy lifting.

Alternatives use the via-node method (as in OSRM / the "choice routing"
literature): run a forward search from the origin and a backward search from
the destination; every edge v gives the best route through v with cost
d_f(v) + d_b(v). We take the cheapest such routes that are not too much
longer than the best, share little with it, and are locally optimal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from .graph import F_LINK, MOTORWAY, TRUNK, RoadGraph
from .profile import CostModel


@dataclass
class Snap:
    lat: float
    lon: float
    dist_m: float
    edges: list[tuple[int, float]]  # (edge, fraction along edge where the point projects)


@dataclass
class Path:
    edges: list[int]
    cost: float          # routing cost (includes avoidance penalties)
    start_frac: float
    end_frac: float


class Router:
    def __init__(self, g: RoadGraph, model: CostModel | None = None):
        self.g = g
        self.model = model or CostModel(g)
        self._build_turns()
        self._build_snap_index()
        self._cache_key = None

    # ---- static structure
    def _build_turns(self) -> None:
        g = self.g
        order = np.argsort(g.src, kind="stable")
        counts = np.bincount(g.src, minlength=g.n_nodes)
        start = np.concatenate([[0], np.cumsum(counts)])
        e_in = np.arange(g.n_edges)
        v = g.dst[e_in]
        k = counts[v]
        rep_in = np.repeat(e_in, k)
        base = np.repeat(start[v], k)
        offs = np.arange(len(rep_in)) - np.repeat(np.cumsum(k) - k, k)
        rep_out = order[base + offs]
        # drop u-turns onto the same piece unless the node is a dead end
        same_piece = (g.seg_idx[rep_in] == g.seg_idx[rep_out]) & (g.piece_idx[rep_in] == g.piece_idx[rep_out])
        dead_end = np.repeat(k, k) <= 1
        keep = ~same_piece | dead_end
        if g.banned:
            banned = np.array(sorted(g.banned), dtype=np.int64)
            key = rep_in.astype(np.int64) * (g.n_edges + 1) + rep_out
            bkey = banned[:, 0] * (g.n_edges + 1) + banned[:, 1]
            keep &= ~np.isin(key, bkey)
        self.t_in = rep_in[keep].astype(np.int64)
        self.t_out = rep_out[keep].astype(np.int64)
        self.turn_route = self.model.turn_costs(self.t_in, self.t_out, routing=True)

    def _build_snap_index(self) -> None:
        g = self.g
        lat0 = float(np.median(g.node_lat))
        self._k = (110540.0, 111320.0 * np.cos(np.radians(lat0)))
        # vertices of every edge, tagged with edge and vertex index (densified to <= 25 m)
        pts, owner = [], []
        for e in range(g.n_edges):
            geo = g.edge_geom(e)
            if g.length_m[e] > 50 * (len(geo) - 1):  # sparse vertices: add points every ~25 m
                n = int(g.length_m[e] // 25) + 2
                t = np.linspace(0, 1, n)
                d = np.r_[0, np.cumsum(np.hypot(*np.diff(geo, axis=0).T))]
                d = d / max(d[-1], 1e-12)
                geo = np.c_[np.interp(t, d, geo[:, 0]), np.interp(t, d, geo[:, 1])]
            pts.append(geo)
            owner.append(np.full(len(geo), e))
        self._snap_pts = np.concatenate(pts)
        self._snap_owner = np.concatenate(owner)
        xy = np.c_[self._snap_pts[:, 0] * self._k[0], self._snap_pts[:, 1] * self._k[1]]
        self._tree = cKDTree(xy)

    def snap(self, lat: float, lon: float, allow_highway: bool = False, k: int = 64) -> Snap:
        g = self.g
        q = np.array([lat * self._k[0], lon * self._k[1]])
        _, idx = self._tree.query(q, k=min(k, len(self._snap_owner)))
        idx = np.atleast_1d(idx)
        cands = np.unique(self._snap_owner[idx])
        best = None
        for e in cands:
            if not allow_highway and (g.cls[e] <= TRUNK or (g.flags[e] & F_LINK)):
                continue
            geo = g.edge_geom(e)
            xy = np.c_[geo[:, 0] * self._k[0], geo[:, 1] * self._k[1]]
            a, b = xy[:-1], xy[1:]
            ab = b - a
            L2 = np.maximum((ab ** 2).sum(1), 1e-9)
            t = np.clip(((q - a) * ab).sum(1) / L2, 0, 1)
            proj = a + ab * t[:, None]
            d = np.sqrt(((proj - q) ** 2).sum(1))
            i = int(np.argmin(d))
            seglens = np.sqrt(L2)
            along = seglens[:i].sum() + t[i] * seglens[i]
            frac = float(along / max(seglens.sum(), 1e-9))
            p = proj[i]
            key = (round(float(d[i]), 1), g.seg_idx[e], g.piece_idx[e])
            if best is None or d[i] < best[0] - 0.05:
                best = (float(d[i]), g.seg_idx[e], g.piece_idx[e], p)
        if best is None:
            raise ValueError(f"no drivable road near {lat},{lon}")
        dist, seg, piece, p = best
        edges = []
        for e in cands:
            if g.seg_idx[e] == seg and g.piece_idx[e] == piece:
                edges.append(int(e))
        out = []
        for e in edges:
            geo = g.edge_geom(e)
            xy = np.c_[geo[:, 0] * self._k[0], geo[:, 1] * self._k[1]]
            seglens = np.sqrt((np.diff(xy, axis=0) ** 2).sum(1))
            ab = np.diff(xy, axis=0)
            L2 = np.maximum((ab ** 2).sum(1), 1e-9)
            t = np.clip(((p - xy[:-1]) * ab).sum(1) / L2, 0, 1)
            d = np.sqrt(((xy[:-1] + ab * t[:, None] - p) ** 2).sum(1))
            i = int(np.argmin(d))
            frac = float((seglens[:i].sum() + t[i] * seglens[i]) / max(seglens.sum(), 1e-9))
            out.append((e, frac))
        return Snap(lat=float(p[0] / self._k[0]), lon=float(p[1] / self._k[1]), dist_m=dist, edges=out)

    # ---- per-query weights
    def _weights(self, when: datetime | None, traffic: bool) -> np.ndarray:
        key = (when.replace(minute=(when.minute // 15) * 15, second=0, microsecond=0) if when else None, traffic)
        if key != self._cache_key:
            self.edge_time = self.model.edge_times(when, traffic=traffic)
            self.arc_w = self.turn_route + self.edge_time[self.t_out]
            self._cache_key = key
        return self.arc_w

    def search(self, src: Snap, dst: Snap, when: datetime | None, traffic: bool = True,
               alternatives: int = 2, max_stretch: float = 0.3, max_share: float = 0.7,
               override: tuple[np.ndarray, np.ndarray] | None = None):
        """override=(edge_time, arc_weight) replaces the model weights (used by map matching)."""
        g = self.g
        if override is None:
            w = self._weights(when, traffic)
        else:
            self.edge_time, w = override
            self._cache_key = None
        n = g.n_edges
        S, T = n, n + 1
        t = self.edge_time
        rows = [self.t_in, np.full(len(src.edges), S), np.array([e for e, _ in dst.edges])]
        cols = [self.t_out, np.array([e for e, _ in src.edges]), np.full(len(dst.edges), T)]
        offset = float(max(t[e] for e, _ in dst.edges)) + 1.0
        wts = [w,
               np.array([(1 - f) * t[e] for e, f in src.edges]),
               np.array([offset - (1 - f) * t[e] for e, f in dst.edges])]
        r = np.concatenate(rows)
        c = np.concatenate(cols)
        ww = np.maximum(np.concatenate(wts), 1e-6)  # scipy treats 0 as "no arc"
        A = csr_matrix((ww, (r, c)), shape=(n + 2, n + 2))
        df, pf = dijkstra(A, directed=True, indices=S, return_predecessors=True)
        if not np.isfinite(df[T]):
            raise ValueError("no route found between origin and destination")
        best_cost = df[T] - offset
        best = self._trace(pf, S, T)
        frac_s = dict(src.edges)
        frac_t = dict(dst.edges)
        paths = [Path(best, best_cost, frac_s[best[0]], frac_t[best[-1]])]
        if alternatives <= 0:
            return paths
        db, pb = dijkstra(A.T.tocsr(), directed=True, indices=T, return_predecessors=True)
        total = df[:n] + db[:n] - offset
        ok = np.isfinite(total) & (total <= best_cost * (1 + max_stretch))
        cand = np.nonzero(ok)[0]
        cand = cand[np.argsort(total[cand])]
        L = g.length_m
        covered = np.zeros(n, dtype=bool)
        covered[best] = True
        best_len = L[best].sum()
        chosen_sets = [set(best)]
        for v in cand:
            if covered[v]:
                continue
            # via path: S..v forward, v..T backward
            head = self._trace(pf, S, v)
            tail = self._trace(pb, T, v)[::-1][1:]  # pb is a tree towards T on the transpose
            p = head + tail
            covered[p] = True
            if not p or p[0] not in frac_s or p[-1] not in frac_t:
                continue
            if len(set(p)) != len(p):
                continue
            pl = L[p].sum()
            share_best = L[list(set(p) & chosen_sets[0])].sum() / min(pl, best_len)
            if share_best > max_share:
                continue
            if any(L[list(set(p) & s)].sum() / pl > 0.9 for s in chosen_sets[1:]):
                continue
            if not self._locally_optimal(p, df, db, total[v], best_cost):
                continue
            paths.append(Path(p, float(total[v]), frac_s[p[0]], frac_t[p[-1]]))
            chosen_sets.append(set(p))
            if len(paths) > alternatives:
                break
        return paths

    def _locally_optimal(self, p, df, db, cost, best_cost, frac: float = 0.25) -> bool:
        """T-test: the detour around the via point must itself be a shortest path.

        Checks that a stretch of ~frac*best_cost on both sides of the via node is
        optimal by comparing forward distances, which rules out silly loops.
        """
        dfp = df[p]
        if not np.all(np.isfinite(dfp)):
            return False
        # accumulated cost along the path vs optimal distance to each edge
        acc = np.concatenate([[dfp[0]], dfp[0] + np.cumsum(self._step_costs(p))])
        excess = acc - dfp
        window = frac * best_cost
        # allow small slack (2 percent of the window); excess must grow only after the plateau
        mid = int(np.argmax(acc >= acc[-1] / 2)) if len(acc) else 0
        lo = int(np.searchsorted(acc, acc[mid] - window))
        return float(excess[mid] - excess[lo]) <= 0.02 * window + 1.0

    def _step_costs(self, p) -> np.ndarray:
        if len(p) < 2:
            return np.zeros(0)
        e_in = np.array(p[:-1])
        e_out = np.array(p[1:])
        return self.model.turn_costs(e_in, e_out, routing=True) + self.edge_time[e_out]

    @staticmethod
    def _trace(pred, s: int, t: int) -> list[int]:
        out = []
        v = t
        while v != s and v >= 0:
            out.append(int(v))
            v = pred[v]
        out = out[::-1]
        return [e for e in out if e < len(pred) - 2]

    # ---- reporting
    def path_times(self, p: Path) -> tuple[np.ndarray, np.ndarray]:
        """Per-edge travel seconds and the turn seconds spent entering each edge (real time, no penalties)."""
        e = np.array(p.edges)
        t = self.edge_time[e].copy()
        t[0] *= (1 - p.start_frac)
        t[-1] *= p.end_frac if len(e) > 1 else (p.end_frac - p.start_frac)
        turns = np.zeros(len(e))
        if len(e) > 1:
            turns[1:] = self.model.turn_costs(e[:-1], e[1:], routing=False)
        return t, turns

    def path_free_times(self, p: Path) -> np.ndarray:
        e = np.array(p.edges)
        t = self.model.free_time[e].copy()
        t[0] *= (1 - p.start_frac)
        t[-1] *= p.end_frac if len(e) > 1 else (p.end_frac - p.start_frac)
        return t
