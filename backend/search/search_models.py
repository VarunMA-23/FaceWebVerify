"""Data classes for reverse image search results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    """A candidate discovered by a reverse-visual search."""

    url: str
    image_url: str = ""
    title: str = ""
    source: str = ""  # provider name (bing/serpapi/tineye)

    def __post_init__(self) -> None:
        self.url = (self.url or "").strip()
        self.image_url = (self.image_url or "").strip()
        self.title = (self.title or "").strip()


@dataclass
class SearchResponse:
    """Aggregated result set from a search provider."""

    results: list[SearchResult] = field(default_factory=list)
    provider: str = ""
    error: str = ""

    @property
    def has_results(self) -> bool:
        return bool(self.results)

    @property
    def accessible_urls(self) -> list[str]:
        return [r.url for r in self.results if r.url.startswith(("http://", "https://"))]