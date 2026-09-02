"""End-to-end pipeline runner shared by the CLI and the API.

Given an input face image, runs:
    face detect -> reverse search -> tiered match -> fingerprint ->
    (optional) blockchain register

and persists the outcome to the database. This is the single orchestrator
used by both ``run_pipeline.py`` and the FastAPI layer so behaviour stays
consistent.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from backend.face.embedder import embed_face
from backend.search.visual_search import search_web
from backend.matching.service import MatcherService, CandidateEvidence
from backend.fingerprint.canonicalizer import ContentRecord, image_sha256_from_file
from backend.fingerprint.hasher import fingerprint


@dataclass
class MatchEvidence:
    """A single discovered candidate, whether or not it matched."""

    page_url: str
    image_url: str
    platform: str = ""
    title: str = ""
    caption: str = ""
    score: float = 0.0
    evidence_tier: str = ""
    is_match: bool = False
    content_hash: str = ""
    image_sha256: str = ""
    matched_image_url: str = ""
    local_image_path: str = ""


@dataclass
class PipelineResult:
    """Aggregated result of a full pipeline run."""

    job_id: str = ""
    status: str = "processing"
    provider: str = ""
    face_detected: bool = False
    face_confidence: float = 0.0
    candidates_seen: int = 0
    best: MatchEvidence | None = None
    blockchain: dict = field(default_factory=dict)
    error: str = ""


class PipelineRunner:
    """Runs the pipeline for an input image and persists results."""

    def __init__(
        self,
        db,
        limit: int = 5,
        threshold: float = 0.4,
        evidence_tier: str = "all",
        do_blockchain: bool = False,
        temp_dir: str | None = None,
    ) -> None:
        self.db = db
        self.limit = limit
        self.threshold = threshold
        self.evidence_tier = evidence_tier
        self.do_blockchain = do_blockchain
        self.temp_dir = temp_dir

    # ------------------------------------------------------------ public
    def run(
        self,
        image_data: bytes,
        filename: str = "upload.jpg",
        job_id: str | None = None,
    ) -> PipelineResult:
        job_id = job_id or uuid.uuid4().hex
        tmpdir = self.temp_dir or tempfile.mkdtemp(prefix="pipeline_")
        saved = self._save_image(job_id, tmpdir, image_data, filename)
        self.db.create_job(job_id, saved)

        result = PipelineResult(job_id=job_id, status="processing")
        try:
            self._execute(job_id, saved, result)
            result.status = "complete"
            self.db.update_job_status(job_id, "complete")
        except Exception as exc:  # noqa: BLE001
            result.status = "failed"
            result.error = str(exc)
            self.db.update_job_status(job_id, "failed")
        finally:
            self._cleanup(tmpdir)
        return result

    # ----------------------------------------------------------- private
    def _save_image(self, job_id: str, tmpdir: str, data: bytes, filename: str) -> str:
        safe = Path(filename).name or "upload.jpg"
        dest = Path(tmpdir) / f"{job_id[:8]}_{safe}"
        dest.write_bytes(data)
        return str(dest)

    def _cleanup(self, tmpdir: str) -> None:
        if not self.temp_dir and Path(tmpdir).exists():
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _execute(
        self,
        job_id: str,
        image_path: str,
        result: PipelineResult,
    ) -> None:
        # 1. Face detection + embedding
        face = embed_face(image_path)
        if face is None:
            result.error = "No face detected in the uploaded image."
            result.status = "failed"
            self.db.update_job_status(job_id, "failed")
            return
        result.face_detected = True
        result.face_confidence = float(face.confidence)

        # 2. Reverse search
        search = search_web(image_path)
        result.provider = search.provider
        if not search.has_results:
            result.error = search.error or "No search results returned."
            result.status = "failed"
            self.db.update_job_status(job_id, "failed")
            return

        # 3 + 4. Tiered match
        with MatcherService(threshold=self.threshold) as service:
            evidence = service.match_candidates(
                face.embedding, search.results[: self.limit]
            )
            result.candidates_seen = len(evidence)
            candidates = self._build_candidates(job_id, service, evidence)
            self._persist_candidates(job_id, candidates)

        matches = [c for c in candidates if c.is_match]
        if self.evidence_tier == "verified_only":
            matches = [c for c in matches if c.evidence_tier == "verified"]
        if matches:
            best = self._pick_best(matches)
            # 5. Fingerprint
            best.content_hash, best.image_sha256 = self._fingerprint(best)
            result.best = best
            # 6. Optional blockchain
            if self.do_blockchain:
                result.blockchain = self._register(job_id, best.content_hash)
        else:
            result.best = None

        self.db.update_job_status(job_id, "complete")

    def _build_candidates(
        self,
        job_id: str,
        service: MatcherService,
        evidence: list[CandidateEvidence],
    ) -> list[MatchEvidence]:
        out: list[MatchEvidence] = []
        for ev in evidence:
            m = ev.best_match
            cache = service.evidence_cache.get(ev.page_url)
            local = (
                cache.page_local or cache.thumbnail_local
                if cache is not None else ""
            )
            matched_image_url = self._matched_image_url(ev, m)
            out.append(
                MatchEvidence(
                    page_url=ev.page_url,
                    image_url=ev.image_url,
                    platform=ev.platform or "web",
                    title=ev.title,
                    caption=ev.caption,
                    score=ev.score,
                    evidence_tier=ev.tier.value,
                    is_match=ev.is_match,
                    matched_image_url=matched_image_url,
                    local_image_path=local,
                )
            )
        return out

    @staticmethod
    def _matched_image_url(ev: CandidateEvidence, m) -> str:
        if m is None:
            return ev.image_url
        return m.image_url or ev.image_url

    def _persist_candidates(
        self,
        job_id: str,
        candidates: list[MatchEvidence],
    ) -> None:
        for c in candidates:
            self.db.add_post(
                job_id=job_id,
                post_url=c.page_url,
                image_url=c.image_url,
                platform=c.platform,
                caption=c.caption or "",
                title=c.title or "",
                face_similarity=c.score,
                evidence_tier=c.evidence_tier,
            )

    def _pick_best(self, matches: list[MatchEvidence]) -> MatchEvidence:
        return max(
            matches,
            key=lambda c: (c.evidence_tier == "verified", c.score),
        )

    def _fingerprint(self, c: MatchEvidence) -> tuple[str, str]:
        img_sha = ""
        if c.local_image_path and Path(c.local_image_path).exists():
            img_sha = image_sha256_from_file(c.local_image_path)
        record = ContentRecord(
            post_url=c.page_url,
            image_sha256=img_sha,
            caption=c.caption or "",
            platform=c.platform,
            title=c.title or "",
            evidence=c.evidence_tier,
        )
        return fingerprint(record), img_sha

    def _register(self, job_id: str, content_hash: str) -> dict:
        from backend.blockchain.registry import register_on_blockchain
        from backend.blockchain.verifier import verify_on_blockchain

        try:
            tx_hash, block = register_on_blockchain(content_hash)
            self.db.add_blockchain_record(
                job_id, content_hash, tx_hash, block
            )
            verified = verify_on_blockchain(content_hash)
            return {
                "content_hash": content_hash,
                "tx_hash": tx_hash,
                "block_number": block,
                "verified": verified,
            }
        except (ValueError, ConnectionError) as exc:
            return {"error": str(exc)}
