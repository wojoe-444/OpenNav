from .base import ProviderError, RoutingProvider
from .google_routes import GoogleRoutesProvider
from .osrm import OSRMProvider

PROVIDERS: dict[str, type[RoutingProvider]] = {
    GoogleRoutesProvider.name: GoogleRoutesProvider,
    OSRMProvider.name: OSRMProvider,
}


def get_provider(name: str, **kwargs) -> RoutingProvider:
    try:
        return PROVIDERS[name](**kwargs)
    except KeyError:
        raise ProviderError(f"Unknown provider {name!r}; choose from {sorted(PROVIDERS)}") from None


__all__ = ["PROVIDERS", "ProviderError", "RoutingProvider", "get_provider", "GoogleRoutesProvider", "OSRMProvider"]
