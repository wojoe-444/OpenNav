"""OpenNav's own routing engine (OpenStreetMap data via Overture Maps).

    from opennav.engine import Engine
    eng = Engine.load("atlanta")          # builds/fetches the region on first use
    result = eng.route(request)
"""
from __future__ import annotations

from pathlib import Path

from ..data import overture
from ..data.regions import REGIONS, region_dir
from .graph import RoadGraph, build_graph
from .profile import CostModel, Params
from .search import Router

_LOADED: dict[str, "Engine"] = {}


def ensure_region(name: str, log=print) -> Path:
    """Download (if needed) and build the road graph for a region; returns the graph path."""
    d = region_dir(name)
    graph_path = d / "graph.pkl"
    seg_path = d / "segments.parquet"
    if graph_path.exists() and graph_path.stat().st_mtime >= Path(__file__).with_name("graph.py").stat().st_mtime:
        return graph_path
    if not seg_path.exists():
        overture.fetch_segments(REGIONS[name], seg_path, log=log)
    build_graph(seg_path, log=log).save(graph_path)
    return graph_path


class Engine:
    def __init__(self, graph: RoadGraph, params: Params | None = None):
        self.graph = graph
        self.model = CostModel(graph, params)
        self.router = Router(graph, self.model)

    @classmethod
    def load(cls, region: str, log=print) -> "Engine":
        if region not in _LOADED:
            _LOADED[region] = cls(RoadGraph.load(ensure_region(region, log=log)))
        return _LOADED[region]
