"""Multi-provider search result aggregation and deduplication."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from backend.evidence.source import canonicalize_url, extract_domain
from backend.search.search_models import SearchResponse, SearchResult
from backend.search.visual_search import PROVIDERS, _Provider


@dataclass
class AggregatedResult:
    """A deduplicated search result with provider agreement."""

    url: str
    image_url: str = ""
    title: str = ""
    providers: list[str] = field(default_factory=list)
    provider_count: int = 0
    canonical_url: str = ""
    domain: str = ""
    best_rank: int = 999999


@dataclass
class AggregatedSearchResponse:
    """Combined multi-provider search response."""

    results: list[AggregatedResult] = field(default_factory=list)
    providers_used: list[str] = field(default_factory=list)
    providers_available: int = 0
    provider_errors: dict[str, str] = field(default_factory=dict)
    error: str = ""

    @property
    def has_results(self) -> bool:
        return bool(self.results)

    @property
    def provider(self) -> str:
        if not self.providers_used:
            return ""
        return ",".join(self.providers_used)


def _search_provider(prov: _Provider, image_path: str) -> SearchResponse:
    return prov.search(image_path)


def search_all_providers(image_path: str) -> AggregatedSearchResponse:
    """Run all configured providers in parallel and aggregate results."""
    available = [p for p in PROVIDERS if p.available()]
    if not available:
        return AggregatedSearchResponse(
            error="No search providers configured. Add API keys to .env.",
            providers_available=0,
        )

    responses: dict[str, SearchResponse] = {}
    errors: dict[str, str] = {}

    workers = min(len(available), 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_search_provider, prov, image_path): prov.name
            for prov in available
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                resp = future.result()
                responses[name] = resp
                if resp.error and not resp.has_results:
                    errors[name] = resp.error
            except Exception as exc:  # noqa: BLE001
                errors[name] = str(exc)

    grouped: dict[str, AggregatedResult] = {}
    for provider_name, resp in responses.items():
        if not resp.has_results:
            continue
        for rank, sr in enumerate(resp.results):
            key = canonicalize_url(sr.url) or sr.url
            if key not in grouped:
                grouped[key] = AggregatedResult(
                    url=sr.url,
                    image_url=sr.image_url,
                    title=sr.title,
                    canonical_url=key,
                    domain=extract_domain(sr.url),
                    best_rank=rank,
                )
            entry = grouped[key]
            entry.best_rank = min(entry.best_rank, rank)
            if provider_name not in entry.providers:
                entry.providers.append(provider_name)
            entry.provider_count = len(entry.providers)
            if not entry.image_url and sr.image_url:
                entry.image_url = sr.image_url
            if not entry.title and sr.title:
                entry.title = sr.title

    results = sorted(
        grouped.values(),
        key=lambda r: (-r.provider_count, r.best_rank),
    )

    used = [n for n, r in responses.items() if r.has_results]
    if not results:
        return AggregatedSearchResponse(
            providers_used=list(responses.keys()),
            providers_available=len(available),
            provider_errors=errors,
            error="No configured provider returned results",
        )

    return AggregatedSearchResponse(
        results=results,
        providers_used=used or list(responses.keys()),
        providers_available=len(available),
        provider_errors=errors,
    )


def provider_consensus_label(
    provider_count: int,
    providers_available: int,
) -> str:
    """Truthful consensus label."""
    if providers_available <= 0:
        return "no provider available"
    if providers_available == 1:
        return "1 provider available"
    return f"{provider_count}/{providers_available}"


def to_search_results(aggregated: AggregatedSearchResponse) -> list[SearchResult]:
    """Convert aggregated results back to SearchResult for the matcher."""
    out: list[SearchResult] = []
    for ar in aggregated.results:
        sr = SearchResult(
            url=ar.url,
            image_url=ar.image_url,
            title=ar.title,
            source=",".join(ar.providers),
            providers=list(ar.providers),
            provider_count=ar.provider_count,
            providers_available=aggregated.providers_available,
        )
        out.append(sr)
    return out
