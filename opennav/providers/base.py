from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import RouteRequest, RouteResult


class ProviderError(RuntimeError):
    pass


class RoutingProvider(ABC):
    """A routing backend.

    Split into fetch (network, returns the raw provider payload) and parse
    (pure function of the payload). That lets us store one raw response per
    test case as ground truth and re-parse it offline as the model evolves.
    """

    name: str = "base"

    @abstractmethod
    def fetch_raw(self, request: RouteRequest) -> dict[str, Any]:
        """Call the backend; return a JSON-serializable payload including the request sent."""

    @abstractmethod
    def parse(self, request: RouteRequest, raw: dict[str, Any]) -> RouteResult:
        """Convert a raw payload into the provider-neutral model."""

    def route(self, request: RouteRequest) -> RouteResult:
        return self.parse(request, self.fetch_raw(request))
