"""Data classes for reverse image search results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    """A candidate discovered by a reverse-visual search."""

    url: str
    image_url: str = ""
    title: str = ""
    source: str = ""  # provider name(s) comma-separated
    providers: list[str] = field(default_factory=list)
    provider_count: int = 0
    providers_available: int = 0

    def __post_init__(self) -> None:
        self.url = (self.url or "").strip()
        self.image_url = (self.image_url or "").strip()
        self.title = (self.title or "").strip()
        if not self.providers and self.source:
            self.providers = [p.strip() for p in self.source.split(",") if p.strip()]
        if self.provider_count == 0 and self.providers:
            self.provider_count = len(self.providers)


@dataclass
class SearchResponse:
    """Aggregated result set from a search provider."""

    results: list[SearchResult] = field(default_factory=list)
    provider: str = ""
    error: str = ""
    providers_used: list[str] = field(default_factory=list)
    providers_available: int = 0
    provider_errors: dict[str, str] = field(default_factory=dict)

    @property
    def has_results(self) -> bool:
        return bool(self.results)

    @property
    def accessible_urls(self) -> list[str]:
        return [r.url for r in self.results if r.url.startswith(("http://", "https://"))]