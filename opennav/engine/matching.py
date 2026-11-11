"""Map-match a reference route (e.g. Google's polyline) onto our road graph.

Used for calibration and diagnosis: once Google's path is expressed as our
edges, we can compare our modelled time per edge/step against Google's, and
check whether our graph even allows the path Google drives.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from .search import Path, Router


def match_polyline(router: Router, points: list[tuple[float, float]], buffer_m: float = 15.0,
                   off_route_factor: float = 50.0) -> Path:
    g = router.g
    lat0 = float(np.mean([p[0] for p in points]))
    k = np.array([110540.0, 111320.0 * math.cos(math.radians(lat0))])
    P = np.asarray(points) * k
    # densify the reference line, remember the local direction at each point
    pts, dirs = [], []
    for a, b in zip(P[:-1], P[1:]):
        d = float(np.hypot(*(b - a)))
        if d < 1e-6:
            continue
        n = max(1, int(math.ceil(d / 4.0)))
        t = np.arange(n) / n
        pts.append(a + (b - a) * t[:, None])
        dirs.append(np.repeat(((b - a) / d)[None, :], n, axis=0))
    pts = np.concatenate(pts)
    dirs = np.concatenate(dirs)
    tree = cKDTree(pts)
    # candidate edges near the line
    lo = pts.min(0) - 100
    hi = pts.max(0) + 100
    mid = g.geom[(g.geom_off[:-1] + g.geom_off[1:]) // 2] * k
    near = np.nonzero(np.all((mid >= lo) & (mid <= hi), axis=1))[0]
    on = np.zeros(g.n_edges, dtype=bool)
    for e in near:
        geo = g.edge_geom(e) * k
        # sample the edge every ~5 m
        seg = np.diff(geo, axis=0)
        L = np.hypot(seg[:, 0], seg[:, 1])
        samples = [geo[0]]
        for a, s, l in zip(geo[:-1], seg, L):
            n = max(1, int(l // 5))
            samples += [a + s * (j / n) for j in range(1, n + 1)]
        S = np.asarray(samples)
        d, idx = tree.query(S, distance_upper_bound=buffer_m)
        if not np.all(np.isfinite(d)):
            continue
        if len(S) >= 2:
            v = S[-1] - S[0]
            nv = np.hypot(*v)
            if nv > 3:
                cos = float(np.mean(dirs[idx] @ (v / nv)))
                if cos < 0.5:
                    continue
        on[e] = True
    w = router.edge_time.copy()
    w[~on] *= off_route_factor
    w[~on] += 30.0
    src = router.snap(*points[0], allow_highway=True)
    dst = router.snap(*points[-1], allow_highway=True)
    saved = router.edge_time
    try:
        path = router.search(src, dst, None, alternatives=0,
                             override=(w, router.turn_route * 0.01 + w[router.t_out]))[0]
    finally:
        router.edge_time = saved
    path.on_route = on  # type: ignore[attr-defined]
    return path
