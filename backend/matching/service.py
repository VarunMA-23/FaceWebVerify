"""Tiered face-matching service.

For a single candidate, this combines two independent evidence paths:

- ``PATH A`` — match the reference face against the search-engine thumbnail
  (works for login-walled posts; thumbnails are CDN-served and public).
- ``PATH B`` — crawl the real post page, download its best content image and
  match against that (works for open posts).

The best score wins; the overall evidence tier reflects the strongest
evidence source that produced a match (verified > thumbnail > none).
"""

from __future__ import annotations

import os

from backend.crawler.collector import Collector
from backend.face.embedder import embed_face
from backend.face.matcher import (
    SIMILARITY_THRESHOLD,
    EvidenceTier,
    FaceMatch,
    best_of,
    match_image_to_embedding,
)


class CandidateEvidence:
    """Aggregated matching result for one candidate."""

    def __init__(
        self,
        page_url: str,
        image_url: str,
        platform: str = "",
        title: str = "",
        caption: str = "",
    ) -> None:
        self.page_url = page_url
        self.image_url = image_url
        self.platform = platform
        self.title = title
        self.caption = caption
        self.thumbnail_match: FaceMatch | None = None
        self.page_match: FaceMatch | None = None
        self.best_match: FaceMatch | None = None
        self.thumbnail_local: str = ""
        self.page_local: str = ""

    def combine(
        self,
        reference: object,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> FaceMatch:
        """Compute the best (thumbnail vs page) match for this candidate."""
        matches: list[FaceMatch] = []
        if self.thumbnail_match is not None:
            matches.append(self.thumbnail_match)
        if self.page_match is not None:
            matches.append(self.page_match)
        self.best_match = best_of(matches, threshold)
        return self.best_match

    @property
    def tier(self) -> EvidenceTier:
        return self.best_match.tier if self.best_match else EvidenceTier.NONE

    @property
    def score(self) -> float:
        return self.best_match.score if self.best_match else 0.0

    @property
    def is_match(self) -> bool:
        return bool(self.best_match and self.best_match.is_match)


class MatcherService:
    """Runs tiered matching across a list of search candidates."""

    def __init__(self, threshold: float = SIMILARITY_THRESHOLD) -> None:
        self.threshold = threshold
        self.collector = Collector()

    def cleanup(self) -> None:
        self.collector.cleanup()

    def __enter__(self) -> "MatcherService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()

    def _match_thumbnail(
        self,
        reference,
        image_url: str,
        source_url: str,
        platform: str,
    ) -> FaceMatch | None:
        """PATH A: download + match the search thumbnail."""
        if not image_url:
            return None
        local = self.collector.download_image(image_url)
        if not local:
            return None
        self.evidence_cache[source_url].thumbnail_local = local
        try:
            return match_image_to_embedding(
                reference,
                local,
                threshold=self.threshold,
                tier=EvidenceTier.THUMBNAIL,
                source="thumbnail",
                image_url=image_url,
                page_url=source_url,
            )
        except Exception:  # noqa: BLE001
            return None

    def _match_page(
        self,
        reference,
        source_url: str,
        image_url: str,
        platform: str,
    ) -> FaceMatch | None:
        """PATH B: crawl the page and match its best content image.

        Uses the page's *own* content image only (never re-uses the search
        thumbnail). If the page yields no own content image (e.g. a login
        wall), no verified evidence is produced.
        """
        page = self.collector.fetch_page(source_url)
        if page is None:
            return None
        target = page.primary_image or ""
        if not target:
            return None
        local = self.collector.download_image(target)
        if not local:
            return None
        self.evidence_cache[source_url].page_local = local
        try:
            return match_image_to_embedding(
                reference,
                local,
                threshold=self.threshold,
                tier=EvidenceTier.VERIFIED,
                source="page",
                image_url=target,
                page_url=page.url,
            )
        except Exception:  # noqa: BLE001
            return None

    def match_candidates(
        self,
        reference_embedding: object,
        candidates: list,
    ) -> list[CandidateEvidence]:
        """Match a reference face against a list of search candidates.

        ``candidates`` items must have ``.url`` and ``.image_url`` attributes
        (e.g. :class:`SearchResult`).
        """
        self.evidence_cache: dict[str, CandidateEvidence] = {}
        results: list[CandidateEvidence] = []

        for sr in candidates:
            ev = CandidateEvidence(
                page_url=sr.url,
                image_url=getattr(sr, "image_url", ""),
                platform=getattr(sr, "source", "web"),
                title=getattr(sr, "title", ""),
            )
            self.evidence_cache[sr.url] = ev
            results.append(ev)

            # PATH A: thumbnail first (works for login-walled posts).
            ev.thumbnail_match = self._match_thumbnail(
                reference_embedding, ev.image_url, sr.url, ev.platform
            )
            # PATH B: real page content.
            ev.page_match = self._match_page(
                reference_embedding, sr.url, ev.image_url, ev.platform
            )
            ev.combine(reference_embedding, self.threshold)

        return results


def match_reference_to_search_results(
    reference_embedding: object,
    search_results: list,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[CandidateEvidence]:
    """Convenience wrapper: match a reference embedding to search results."""
    with MatcherService(threshold=threshold) as service:
        return service.match_candidates(reference_embedding, search_results)