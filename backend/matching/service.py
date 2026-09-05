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
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

from backend.crawler.collector import Collector
from backend.crawler.parser import infer_platform
from backend.face.matcher import (
    SIMILARITY_THRESHOLD,
    EvidenceTier,
    FaceMatch,
    best_of,
    match_image_to_embedding,
)

#: Ceiling on how many candidate-image matches may run concurrently. Scaled
#: to the machine's core count (ONNX/InsightFace CPU inference releases the
#: GIL during the forward pass, so worker threads genuinely overlap).
MAX_WORKERS = max(4, int(os.cpu_count() or 4))

#: Minimum available RAM (MiB) below which we still allow parallelism.
#: Below this, fall back to sequential processing to stay smooth on
#: very memory-constrained laptops.
LOW_RAM_MIB = 1024


def _same_image_file(path_a: str, path_b: str) -> bool:
    """Return True when two local image files contain identical bytes.

    Avoids a redundant detect + embed forward pass when a page's content
    image is byte-identical to the search thumbnail already matched.
    """
    if not path_a or not path_b:
        return False
    try:
        if os.path.getsize(path_a) != os.path.getsize(path_b):
            return False
        digest_a = sha256()
        digest_b = sha256()
        with open(path_a, "rb") as fh_a, open(path_b, "rb") as fh_b:
            while True:
                chunk_a = fh_a.read(1 << 20)
                chunk_b = fh_b.read(1 << 20)
                if not chunk_a or not chunk_b:
                    break
                digest_a.update(chunk_a)
                digest_b.update(chunk_b)
        return digest_a.digest() == digest_b.digest()
    except OSError:
        return False


def _available_ram_mib() -> int:
    """Best-effort estimate of currently available system RAM in MiB.

    Returns -1 when the platform cannot be determined (treated as unlimited).
    """
    try:
        # python 3.13
        import psutil

        return int(psutil.virtual_memory().available // (1024 * 1024))
    except Exception:  # noqa: BLE001
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        except Exception:  # noqa: BLE001
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                return int(stat.ullAvailPhys // (1024 * 1024))
            except Exception:  # noqa: BLE001
                return -1


def adapt_candidate_limit(requested: int) -> int:
    """Reduce the candidate count when the machine has little free RAM.

    On constrained machines we process fewer candidates (still in parallel)
    so the pipeline stays responsive and does not thrash memory.
    """
    if requested <= 1:
        return requested
    avail = _available_ram_mib()
    if avail < 0:  # unknown -> leave unchanged
        return requested
    if avail < 512:  # very tight: only a few candidates
        return max(1, min(requested, 2))
    if avail < LOW_RAM_MIB:  # tight: about half the candidates
        return max(1, min(requested, 3))
    return requested


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
        self.page_retrieved: bool = False
        self.image_retrieved: bool = False
        self.image_similarity: float | None = None
        self.providers: list[str] = []
        self.provider_count: int = 0
        self.providers_available: int = 0

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
        self.evidence_cache[source_url].image_retrieved = True
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
        ev: CandidateEvidence | None = None,
    ) -> FaceMatch | None:
        """PATH B: crawl the page and match its best content image.

        Uses the page's *own* content image only (never re-uses the search
        thumbnail). If the page yields no own content image (e.g. a login
        wall), no verified evidence is produced.

        If the page's content image is byte-identical to the thumbnail that
        was already matched (passed via ``ev``), the thumbnail result is
        reused to skip a redundant detect + embed forward pass.
        """
        page = self.collector.fetch_page(source_url)
        if page is None:
            return None
        cache = self.evidence_cache[source_url]
        cache.page_retrieved = True
        if page.title:
            cache.title = page.title
        if page.caption:
            cache.caption = page.caption
        if page.platform:
            cache.platform = page.platform
        target = page.primary_image or ""
        if not target:
            return None
        local = self.collector.download_image(target)
        if not local:
            return None
        self.evidence_cache[source_url].page_local = local
        # Reuse the thumbnail match when the page image is byte-identical to
        # the thumbnail, avoiding a second full inference pass. The result is
        # re-tiered to VERIFIED because the page itself was successfully
        # fetched and carries the same content image.
        if (
            ev is not None
            and ev.thumbnail_match is not None
            and ev.thumbnail_local
            and _same_image_file(ev.thumbnail_local, local)
        ):
            tm = ev.thumbnail_match
            return FaceMatch(
                is_match=tm.is_match,
                score=tm.score,
                face=tm.face,
                tier=EvidenceTier.VERIFIED,
                source="page",
                image_url=target,
                page_url=page.url,
            )
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

    def _match_one(
        self,
        reference_embedding: object,
        candidate: object,
        index: int,
    ) -> None:
        """Match a single candidate (thumbnail + page) and store the result.

        Called from a worker thread; the per-candidate ``CandidateEvidence``
        object is shared across threads only for its own slice of state, so
        there is no cross-candidate race.
        """
        url = getattr(candidate, "url", "")
        plat = infer_platform(url)
        ev = CandidateEvidence(
            page_url=url,
            image_url=getattr(candidate, "image_url", ""),
            platform=plat,
            title=getattr(candidate, "title", ""),
        )
        ev.providers = list(getattr(candidate, "providers", []) or [])
        ev.provider_count = int(getattr(candidate, "provider_count", 0) or len(ev.providers))
        ev.providers_available = int(getattr(candidate, "providers_available", 0) or 0)
        self.evidence_cache[url] = ev

        # PATH A: thumbnail first (works for login-walled posts).
        ev.thumbnail_match = self._match_thumbnail(
            reference_embedding, ev.image_url, url, ev.platform
        )
        # PATH B: real page content.
        ev.page_match = self._match_page(
            reference_embedding, url, ev.image_url, ev.platform, ev
        )
        ev.combine(reference_embedding, self.threshold)
        # Image similarity: compare thumbnail vs page image hashes or dual face match scores
        cache = self.evidence_cache[url]
        if cache.thumbnail_local and cache.page_local:
            try:
                from backend.fingerprint.canonicalizer import image_sha256_from_file

                t_hash = image_sha256_from_file(cache.thumbnail_local)
                p_hash = image_sha256_from_file(cache.page_local)
                if t_hash == p_hash:
                    cache.image_similarity = 1.0
                elif ev.thumbnail_match and ev.page_match and ev.thumbnail_match.is_match and ev.page_match.is_match:
                    cache.image_similarity = round(float(min(ev.thumbnail_match.score, ev.page_match.score)), 3)
                else:
                    cache.image_similarity = None
            except Exception:  # noqa: BLE001
                cache.image_similarity = None
        self._results[index] = ev

    def match_candidates(
        self,
        reference_embedding: object,
        candidates: list,
    ) -> list[CandidateEvidence]:
        """Match a reference face against a list of search candidates.

        ``candidates`` items must have ``.url`` and ``.image_url`` attributes
        (e.g. :class:`SearchResult`).

        Candidates are matched concurrently with a bounded thread pool. On
        machines with little free RAM the pool is sized down (and on very
        constrained systems the candidate count itself is reduced) so the
        pipeline stays responsive on low-RAM laptops.
        """
        self.evidence_cache: dict[str, CandidateEvidence] = {}

        candidates = candidates[: adapt_candidate_limit(len(candidates))]
        # Keep the original order in the returned list regardless of how
        # quickly individual candidates finish.
        self._results: list[CandidateEvidence] = [None] * len(candidates)  # type: ignore[list-item]

        workers = max(1, min(MAX_WORKERS, len(candidates)))
        if workers == 1:
            for i, sr in enumerate(candidates):
                self._match_one(reference_embedding, sr, i)
            return [r for r in self._results if r is not None]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(self._match_one, reference_embedding, sr, i)
                for i, sr in enumerate(candidates)
            ]
            for f in futures:
                f.result()

        # Trim back to the actual size (adapt_candidate_limit may have reduced it).
        return [r for r in self._results if r is not None]


def match_reference_to_search_results(
    reference_embedding: object,
    search_results: list,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[CandidateEvidence]:
    """Convenience wrapper: match a reference embedding to search results."""
    with MatcherService(threshold=threshold) as service:
        return service.match_candidates(reference_embedding, search_results)