"""End-to-end pipeline runner shared by the CLI and the API."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from backend.evidence.explain import build_explanation
from backend.evidence.models import ScoredCandidate
from backend.evidence.passport import build_passport
from backend.evidence.scorer import build_provider_consensus, compute_evidence_score
from backend.evidence.source import build_source_info, extract_social_handle, is_social_source
from backend.evidence.timeline import TimelineTracker
from backend.face.embedder import embed_face
from backend.fingerprint.canonicalizer import EvidenceRecord, image_sha256_from_file
from backend.fingerprint.hasher import fingerprint
from backend.matching.service import MatcherService, CandidateEvidence
from backend.output import CaseDir
from backend.search.social import social_search
from backend.search.visual_search import search_web


@dataclass
class MatchEvidence:
    """A single discovered candidate enriched with evidence metadata."""

    page_url: str
    image_url: str = ""
    platform: str = ""
    source_type: str = ""
    domain: str = ""
    canonical_url: str = ""
    title: str = ""
    caption: str = ""
    score: float = 0.0
    evidence_tier: str = ""
    evidence_score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    is_match: bool = False
    content_hash: str = ""
    image_sha256: str = ""
    image_similarity: float | None = None
    matched_image_url: str = ""
    local_image_path: str = ""
    providers: list[str] = field(default_factory=list)
    provider_count: int = 0
    provider_consensus: str = ""
    providers_available: int = 0
    explanation: list[str] = field(default_factory=list)
    page_retrieved: bool = False
    image_retrieved: bool = False
    rank: int = 0


@dataclass
class PipelineResult:
    """Aggregated result of a full pipeline run."""

    job_id: str = ""
    status: str = "processing"
    provider: str = ""
    providers_used: list[str] = field(default_factory=list)
    providers_available: int = 0
    provider_errors: dict = field(default_factory=dict)
    face_detected: bool = False
    face_confidence: float = 0.0
    candidates_seen: int = 0
    best: MatchEvidence | None = None
    passport: dict = field(default_factory=dict)
    timeline: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    blockchain: dict = field(default_factory=dict)
    case_dir: str = ""
    error: str = ""


def _blockchain_enabled(explicit: bool) -> bool:
    return bool(explicit)


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
        hint: str = "",
    ) -> None:
        self.db = db
        self.limit = limit
        self.threshold = threshold
        self.evidence_tier = evidence_tier
        self.do_blockchain = _blockchain_enabled(do_blockchain)
        self.temp_dir = temp_dir
        self.hint = hint

    def _sync_progress(
        self,
        job_id: str,
        timeline: TimelineTracker,
        result: PipelineResult,
        *,
        phase: str = "processing",
    ) -> None:
        """Persist timeline + partial results so the UI can poll live progress."""
        result.timeline = timeline.to_list()
        self.db.update_job_metadata(
            job_id,
            {
                "timeline": result.timeline,
                "phase": phase,
                "summary": result.summary,
                "passport": result.passport,
                "providers_used": result.providers_used,
                "providers_available": result.providers_available,
                "provider_errors": result.provider_errors,
                "provider": result.provider,
                "face_confidence": result.face_confidence,
                "face_detected": result.face_detected,
                "candidates_seen": result.candidates_seen,
                "error": result.error,
                "case_dir": result.case_dir,
            },
        )

    def run(
        self,
        image_data: bytes,
        filename: str = "upload.jpg",
        job_id: str | None = None,
        hint: str | None = None,
    ) -> PipelineResult:
        job_id = job_id or uuid.uuid4().hex
        if hint is not None:
            self.hint = hint
        tmpdir = self.temp_dir or tempfile.mkdtemp(prefix="pipeline_")
        saved = self._save_image(job_id, tmpdir, image_data, filename)
        self.db.create_job(job_id, saved)

        result = PipelineResult(job_id=job_id, status="processing")
        timeline = TimelineTracker()
        try:
            self.limit = max(1, int(self.limit or 1))
            self._execute(job_id, saved, result, timeline)
        except Exception as exc:  # noqa: BLE001
            result.status = "failed"
            result.error = str(exc)
            self.db.update_job_status(job_id, "failed")
        finally:
            result.timeline = timeline.to_list()
            self.db.update_job_metadata(
                job_id,
                {
                    "timeline": result.timeline,
                    "phase": "complete" if result.status == "complete" else "failed",
                    "summary": result.summary,
                    "passport": result.passport,
                    "providers_used": result.providers_used,
                    "providers_available": result.providers_available,
                    "provider_errors": result.provider_errors,
                    "provider": result.provider,
                    "face_confidence": result.face_confidence,
                    "face_detected": result.face_detected,
                    "candidates_seen": result.candidates_seen,
                    "error": result.error,
                    "case_dir": result.case_dir,
                },
            )
            self._cleanup(tmpdir)
        return result

    def _save_image(self, job_id: str, tmpdir: str, data: bytes, filename: str) -> str:
        safe = Path(filename).name or "upload.jpg"
        dest = Path(tmpdir) / f"{job_id[:8]}_{safe}"
        dest.write_bytes(data)
        return str(dest)

    def _crop_for_search(
        self,
        image_path: str,
        face,
        case_dir: CaseDir,
    ) -> str:
        """Crop the input image to the detected face for search providers.

        Respects the ``CROP_TO_FACE`` env toggle (default on). Returns the
        path of a cropped copy, or the original path when cropping is disabled
        or unavailable. The crop is persisted to the case dir as an artifact.
        """
        import os

        if os.environ.get("CROP_TO_FACE", "").strip().lower() in {
            "0", "false", "no", "off",
        }:
            return image_path
        if face is None or len(getattr(face, "bbox", []) or []) < 4:
            return image_path
        try:
            from backend.face.crop import crop_to_face
            from backend.face.model import read_image

            raw_img = read_image(image_path)
            cropped = crop_to_face(raw_img, face)
            output = case_dir.save_crop(cropped)
            return str(output)
        except Exception:  # noqa: BLE001
            return image_path

    def _cleanup(self, tmpdir: str) -> None:
        if not self.temp_dir and Path(tmpdir).exists():
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _execute(
        self,
        job_id: str,
        image_path: str,
        result: PipelineResult,
        timeline: TimelineTracker,
    ) -> None:
        case_dir = CaseDir()
        result.case_dir = str(case_dir.path)

        # 1. Face detection
        timeline.start("face", "Analyzing uploaded image…")
        self._sync_progress(job_id, timeline, result, phase="face_detection")
        face = embed_face(image_path)
        if face is None:
            result.error = "No face detected in the uploaded image."
            result.status = "failed"
            timeline.fail("face", "No face detected")
            self._sync_progress(job_id, timeline, result, phase="failed")
            self.db.update_job_status(job_id, "failed")
            return
        result.face_detected = True
        result.face_confidence = float(face.confidence)
        timeline.succeed("face", f"Confidence {result.face_confidence:.3f}")
        timeline.succeed("embedding", "512-D ArcFace embedding generated")
        self._sync_progress(job_id, timeline, result, phase="face_complete")

        # 1b. Persist input + annotated artefacts (non-essential; best effort)
        try:
            from backend.face.model import read_image

            raw_img = read_image(image_path)
            case_dir.save_input(Path(image_path).read_bytes(), Path(image_path).name)
            case_dir.save_annotated(raw_img, [face], label="input")
        except Exception:  # noqa: BLE001
            pass

        # 1c. Crop the image to the detected primary face so reverse-image
        # providers search the subject rather than the whole photo (reduces
        # noise from background / group shots). Best effort.
        search_image = self._crop_for_search(image_path, face, case_dir)

        # 2. Reverse search (multi-provider when configured)
        from backend.search.visual_search import PROVIDERS

        available = [p.name for p in PROVIDERS if p.available()]
        provider_hint = ", ".join(available) if available else "none configured"
        timeline.start("search", f"Querying {len(available)} provider(s): {provider_hint}")
        self._sync_progress(job_id, timeline, result, phase="searching")
        search = search_web(search_image, precropped=search_image)

        # 2b. Keyless social fallback when keyed providers return nothing
        if not search.has_results and self.hint:
            timeline.start(
                "search",
                f"Keyed providers: {provider_hint or 'none configured'} — falling back to keyless social APIs",
            )
            self._sync_progress(job_id, timeline, result, phase="searching_social")
            social = social_search(self.hint)
            result.provider_errors = dict(social.provider_errors or {})
            if social.has_results:
                search = social

        result.provider = search.provider
        result.providers_used = list(search.providers_used or [])
        result.providers_available = search.providers_available or len(result.providers_used)
        provider_errors = getattr(search, "provider_errors", None) or {}
        result.provider_errors = dict(provider_errors)
        if not search.has_results:
            result.error = search.error or "Reverse image search returned no candidates."
            result.status = "failed"
            timeline.fail("search", result.error)
            self._sync_progress(job_id, timeline, result, phase="failed")
            self.db.update_job_status(job_id, "failed")
            return
        timeline.succeed(
            "search",
            f"{len(search.results)} hits from {result.provider or provider_hint}",
        )
        timeline.succeed("discover", f"{len(search.results)} unique sources discovered")
        self._sync_progress(job_id, timeline, result, phase="search_complete")

        # 3 + 4. Match + verify sources — process in batches, stop on first match
        total_results = len(search.results)
        timeline.start("verify", f"Verifying up to {total_results} candidates (batch size {self.limit})…")
        timeline.start("match", "Comparing face embeddings…")
        self._sync_progress(job_id, timeline, result, phase="matching")
        with MatcherService(threshold=self.threshold) as service:
            all_candidates: list[MatchEvidence] = []
            remaining = list(search.results)
            batch_num = 0
            found_match = False

            while remaining:
                batch_num += 1
                batch = remaining[: self.limit]
                remaining = remaining[self.limit:]
                checked = len(all_candidates)

                timeline.start(
                    "match",
                    f"Batch {batch_num}: candidates {checked + 1}–{checked + len(batch)} of {total_results}…",
                )
                self._sync_progress(job_id, timeline, result, phase="matching")

                batch_evidence = service.match_candidates(face.embedding, batch)
                batch_candidates = self._build_candidates(
                    service, batch_evidence, search.providers_available
                )
                all_candidates.extend(batch_candidates)

                has_match = any(c.is_match for c in batch_candidates)
                if has_match:
                    timeline.succeed("match", f"Match found in batch {batch_num}")
                    found_match = True
                    break

                if remaining:
                    timeline.start(
                        "match",
                        f"No match in batch {batch_num} — trying next {len(remaining)} candidates…",
                    )
                    self._sync_progress(job_id, timeline, result, phase="matching")

            if not found_match:
                timeline.warn("match", f"No match across {len(all_candidates)} candidates checked")

            candidates = all_candidates
            result.candidates_seen = len(candidates)
            candidates.sort(
                key=lambda c: (
                    c.is_match,
                    c.evidence_tier == "verified",
                    c.score,
                    c.evidence_score,
                    c.provider_count,
                ),
                reverse=True,
            )
            for i, c in enumerate(candidates):
                c.rank = i + 1
            self._persist_candidates(job_id, candidates)

        verified_count = sum(1 for c in candidates if c.evidence_tier == "verified")
        social_count = sum(1 for c in candidates if c.source_type == "social")
        match_count = sum(1 for c in candidates if c.is_match)
        timeline.succeed("verify", f"{verified_count} source pages verified")
        timeline.succeed("match", f"{match_count} face matches")
        timeline.start("score", "Computing evidence scores…")
        timeline.succeed("score", "Evidence scores computed")
        self._sync_progress(job_id, timeline, result, phase="scoring")

        result.summary = {
            "candidates_found": len(candidates),
            "face_matches": match_count,
            "verified_sources": verified_count,
            "social_sources": social_count,
            "providers_used": result.providers_used,
            "providers_available": result.providers_available,
            "provider_errors": result.provider_errors,
            "provider_consensus": (
                f"{max((c.provider_count for c in candidates), default=0)}/{result.providers_available}"
                if result.providers_available > 1
                else "1 provider available"
            ),
            "best_evidence_score": candidates[0].evidence_score if candidates else 0,
        }

        matches = [c for c in candidates if c.is_match]
        if self.evidence_tier == "verified_only":
            matches = [c for c in matches if c.evidence_tier == "verified"]

        if matches:
            best = self._pick_best(matches)
            timeline.succeed("select", f"Best: {best.platform} ({best.evidence_tier})")

            # 4b. Persist match artifacts (matched image + annotations)
            try:
                self._save_match_artifacts(case_dir, best)
            except Exception:  # noqa: BLE001
                pass

            timeline.start("fingerprint", "Building canonical evidence record…")
            self._sync_progress(job_id, timeline, result, phase="fingerprinting")
            fp_result = self._fingerprint(best)
            best.content_hash = fp_result[0]
            best.image_sha256 = fp_result[1]
            canonical_json = fp_result[2]
            evidence_id = fp_result[3]
            evidence_record = fp_result[4]
            timeline.succeed("fingerprint", best.content_hash[:16] + "…")
            result.best = best

            # Persist the exact canonical evidence bundle to the case directory
            try:
                import json as _json

                bundle = _json.loads(canonical_json) if isinstance(canonical_json, str) else canonical_json
                if isinstance(bundle, dict):
                    bundle["case_dir"] = str(case_dir.path)
                case_dir.save_evidence(bundle)
            except Exception:  # noqa: BLE001
                pass

            scored = self._to_scored(best)
            passport = build_passport(
                scored, evidence_id=evidence_id, content_hash=best.content_hash
            )
            result.passport = passport.to_dict()
            result.passport["canonical_json"] = canonical_json
            result.passport["image_sha256"] = best.image_sha256
            result.passport["evidence_record"] = evidence_record

            if self.do_blockchain:
                timeline.start("blockchain", "Anchoring evidence digest…")
                self._sync_progress(job_id, timeline, result, phase="blockchain")
                result.blockchain = self._register(
                    job_id,
                    best.content_hash,
                    result.passport["evidence_record"]["evidence_id"],
                )
                if result.blockchain.get("content_hash"):
                    passport.blockchain_network = (
                        result.blockchain.get("network")
                        or result.blockchain.get("backend")
                        or "local-merkle-chain"
                    )
                    passport.tx_hash = result.blockchain.get("tx_hash") or ""
                    passport.block_number = result.blockchain.get("block_number")
                    passport.registered_at = result.blockchain.get("registered_at", "")
                    passport.integrity_status = "attested"
                    timeline.succeed(
                        "blockchain",
                        f"{result.blockchain.get('backend')} · "
                        f"{best.content_hash[:16]}…",
                    )
                    try:
                        case_dir.save_receipt(result.blockchain)
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    timeline.warn(
                        "blockchain",
                        result.blockchain.get("error", "Blockchain registration unavailable"),
                    )
            else:
                timeline.warn("blockchain", "Blockchain registration skipped (not configured)")
                passport.integrity_status = "fingerprinted"

            result.passport = passport.to_dict()
            # Restore the rich evidence bundle (canonical_json / image_sha256 /
            # evidence_record) that isn't part of the passport dataclass.
            result.passport["canonical_json"] = canonical_json
            result.passport["image_sha256"] = best.image_sha256
            result.passport["evidence_record"] = evidence_record
        else:
            result.best = None
            timeline.warn("select", "No candidates met match threshold")
            timeline.warn("fingerprint", "Skipped — no qualifying match")
            timeline.warn("blockchain", "Skipped — no evidence to attest")

        result.status = "complete"
        self.db.update_job_status(job_id, "complete")

    def _build_candidates(
        self,
        service: MatcherService,
        evidence: list[CandidateEvidence],
        providers_available: int,
    ) -> list[MatchEvidence]:
        out: list[MatchEvidence] = []
        for ev in evidence:
            m = ev.best_match
            cache = service.evidence_cache.get(ev.page_url)
            if cache is None:
                local = ""
            else:
                # Use the local image of the evidence tier that actually won,
                # so the fingerprinted image matches the claimed tier.
                if ev.tier.value == "verified":
                    local = cache.page_local or cache.thumbnail_local
                else:
                    local = cache.thumbnail_local or cache.page_local
            source = build_source_info(
                ev.page_url,
                page_retrieved=ev.page_retrieved,
                image_retrieved=ev.image_retrieved,
                platform=ev.platform,
            )
            consensus = build_provider_consensus(
                ev.providers,
                ev.providers_available or providers_available,
            )
            score_obj = compute_evidence_score(
                face_similarity=ev.score,
                image_similarity=ev.image_similarity,
                evidence_tier=ev.tier.value,
                source=source,
                consensus=consensus,
                has_title=bool(ev.title),
                has_caption=bool(ev.caption),
            )
            explanation = build_explanation(
                face_similarity=ev.score,
                threshold=self.threshold,
                evidence_tier=ev.tier.value,
                source=source,
                consensus=consensus,
                is_match=ev.is_match,
                image_similarity=ev.image_similarity,
            )
            out.append(
                MatchEvidence(
                    page_url=ev.page_url,
                    image_url=ev.image_url,
                    platform=source.platform,
                    source_type=source.source_type,
                    domain=source.domain,
                    canonical_url=source.canonical_url,
                    title=ev.title,
                    caption=ev.caption,
                    score=ev.score,
                    evidence_tier=ev.tier.value,
                    evidence_score=score_obj.total,
                    score_breakdown=score_obj.breakdown,
                    is_match=ev.is_match,
                    matched_image_url=self._matched_image_url(ev, m),
                    local_image_path=local,
                    image_similarity=ev.image_similarity,
                    providers=consensus.providers,
                    provider_count=consensus.provider_count,
                    provider_consensus=consensus.provider_consensus,
                    providers_available=consensus.providers_available,
                    explanation=explanation.reasons,
                    page_retrieved=ev.page_retrieved,
                    image_retrieved=ev.image_retrieved,
                )
            )
        return out

    @staticmethod
    def _to_scored(c: MatchEvidence) -> ScoredCandidate:
        from backend.evidence.models import EvidenceScore, MatchExplanation, ProviderConsensus, SourceInfo

        return ScoredCandidate(
            source=SourceInfo(
                source_url=c.page_url,
                canonical_url=c.canonical_url,
                domain=c.domain,
                platform=c.platform,
                source_type=c.source_type,
                page_retrieved=c.page_retrieved,
                image_retrieved=c.image_retrieved,
            ),
            consensus=ProviderConsensus(
                providers=c.providers,
                provider_count=c.provider_count,
                providers_available=c.providers_available,
                provider_consensus=c.provider_consensus,
            ),
            face_similarity=c.score,
            image_similarity=c.image_similarity,
            evidence_tier=c.evidence_tier,
            evidence_score=EvidenceScore(total=c.evidence_score, breakdown=c.score_breakdown),
            explanation=MatchExplanation(reasons=c.explanation),
            title=c.title,
            caption=c.caption,
            image_url=c.image_url,
            is_match=c.is_match,
            rank=c.rank,
        )

    @staticmethod
    def _matched_image_url(ev: CandidateEvidence, m) -> str:
        if m is None:
            return ev.image_url
        return m.image_url or ev.image_url

    def _save_match_artifacts(
        self,
        case_dir: CaseDir,
        best: MatchEvidence,
    ) -> None:
        """Save the matched image bytes and its annotation."""
        if not best.local_image_path or not Path(best.local_image_path).exists():
            return
        from backend.face.detector import detect_faces

        best_img = cv2.imread(best.local_image_path)
        if best_img is None:
            return

        # Save the raw downloaded image bytes
        case_dir.save_match_bytes(Path(best.local_image_path).read_bytes())

        # Detect faces for annotation
        faces = detect_faces(best_img)
        case_dir.save_match_annotated(best_img, faces)

    def _persist_candidates(self, job_id: str, candidates: list[MatchEvidence]) -> None:
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
                source_type=c.source_type,
                domain=c.domain,
                evidence_score=c.evidence_score,
                provider_count=c.provider_count,
                providers=c.providers,
                explanation=c.explanation,
                metadata={
                    "score_breakdown": c.score_breakdown,
                    "provider_consensus": c.provider_consensus,
                    "image_similarity": c.image_similarity,
                    "canonical_url": c.canonical_url,
                    "page_retrieved": c.page_retrieved,
                    "image_retrieved": c.image_retrieved,
                    "is_social": is_social_source(c.source_type, c.platform),
                    "social_handle": extract_social_handle(c.page_url, c.platform) or "",
                    "rank": c.rank,
                },
            )

    def _pick_best(self, matches: list[MatchEvidence]) -> MatchEvidence:
        return max(
            matches,
            key=lambda c: (
                c.evidence_tier == "verified",
                c.score,
                c.source_type == "social",
                c.evidence_score,
            ),
        )

    def _fingerprint(self, c: MatchEvidence) -> tuple[str, str, str, str, dict]:
        img_sha = ""
        if c.local_image_path and Path(c.local_image_path).exists():
            img_sha = image_sha256_from_file(c.local_image_path)
        # Deterministic evidence ID derived from the evidence content, so
        # re-running the same input re-produces the same record (idempotent
        # anchoring) instead of generating a fresh random ID every run.
        seed = "\x1f".join(
            [c.page_url, c.canonical_url, img_sha, c.caption or "", c.title or ""]
        )
        evidence_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        record = EvidenceRecord(
            evidence_id=evidence_id,
            source_url=c.page_url,
            canonical_url=c.canonical_url,
            platform=c.platform,
            source_type=c.source_type,
            face_similarity=c.score,
            image_similarity=c.image_similarity,
            evidence_tier=c.evidence_tier,
            image_sha256=img_sha,
            caption=c.caption or "",
            title=c.title or "",
            providers=c.providers,
            provider_consensus=c.provider_consensus,
            evidence_score=c.evidence_score,
            verification_reasons=c.explanation,
        )
        content_hash = fingerprint(record)
        return content_hash, img_sha, record.canonical_json(), evidence_id, record.display_dict()

    def _register(self, job_id: str, content_hash: str, evidence_id: str) -> dict:
        """Anchor the content hash on the active backend and persist records."""
        from dataclasses import asdict
        from datetime import datetime, timezone

        from backend.blockchain.backend import resolve_backend
        from backend.blockchain.checks import checks_to_dicts
        from backend.blockchain.errors import BackendUnavailableError
        from backend.blockchain.verifier import verify_record

        try:
            backend = resolve_backend()
            receipt = backend.anchor(content_hash)
            ref = dict(receipt.ref or {})
            checks = verify_record(content_hash, receipt)
            verified = bool(checks) and all(c.ok for c in checks)

            self.db.add_blockchain_record(
                job_id,
                content_hash,
                transaction_hash=ref.get("tx_hash") or "",
                block_number=receipt.block_index,
                backend=receipt.backend,
                network=receipt.network,
                block_hash=receipt.block_hash,
                merkle_root=receipt.merkle_root,
                leaf_index=receipt.leaf_index,
                merkle_proof=[asdict(s) for s in receipt.merkle_proof],
                idempotent=receipt.idempotent_hit,
                checks=checks_to_dicts(checks),
                chain_root=ref.get("chain_root") or "",
            )

            # EVM registry mode additionally attests the evidence mapping on-chain.
            if receipt.backend == "evm" and ref.get("mode") == "registry":
                from backend.blockchain.registry import register_evidence_on_blockchain

                ev_tx_hash, ev_block = register_evidence_on_blockchain(
                    evidence_id, content_hash
                )
                self.db.add_blockchain_record(
                    job_id,
                    content_hash,
                    ev_tx_hash,
                    ev_block,
                    evidence_id=evidence_id,
                    record_type="evidence_attestation",
                    backend=receipt.backend,
                    network=receipt.network,
                )

            return {
                "content_hash": content_hash,
                "backend": receipt.backend,
                "network": receipt.network,
                "tx_hash": ref.get("tx_hash"),
                "block_hash": receipt.block_hash,
                "block_number": receipt.block_index,
                "merkle_root": receipt.merkle_root,
                "idempotent": receipt.idempotent_hit,
                "verified": verified,
                "checks": checks_to_dicts(checks),
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }
        except (ValueError, ConnectionError) as exc:
            return {"error": str(exc)}
        except BackendUnavailableError as exc:
            # Anchoring is an optional subsystem: a disabled/unconfigured
            # backend must degrade the run gracefully, not fail the job.
            return {"error": str(exc)}
