"""Runnable end-to-end pipeline for a single input face image.

Usage:
    python run_pipeline.py <image_path> [--limit N] [--match-threshold 0.4]
                              [--evidence-tier all|verified_only]
                              [--hint "Subject Name"]

Runs: face detect -> reverse search (or keyless social fallback) -> tiered
face match (thumbnail + page) -> fingerprint -> (optional) blockchain
register/verify.

Artifacts are written to ``out/case-<timestamp>-<embed>/``.

Evidence tiers:
  - verified  : matched against the real post content image (page crawl)
  - thumbnail : matched against the search thumbnail only (login-walled post)
  - none      : no match

--evidence-tier controls which matches are eligible to become the result:
  - all          (default) retain verified AND thumbnail matches
  - verified_only retain only verified (page-content) matches

--hint seeds the keyless social fallback (Bluesky/Mastodon/Reddit) when no
reverse-image API keys are configured.
"""

from __future__ import annotations

import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from backend.console import banner, cyan, dim, fail, kv, ok, stage, warn
from backend.face.embedder import embed_face
from backend.face.matcher import (
    SIMILARITY_THRESHOLD,
    EvidenceTier,
)
from backend.output import CaseDir
from backend.search.social import social_search
from backend.search.visual_search import search_web
from backend.matching.service import MatcherService
from backend.fingerprint.canonicalizer import EvidenceRecord, image_sha256_from_file
from backend.fingerprint.hasher import fingerprint

STAGES = 6


def _resolve_local_image(service: MatcherService, url: str, tier: EvidenceTier) -> str:
    """Pick the downloaded local image for fingerprinting."""
    cache = service.evidence_cache.get(url)
    if cache is None:
        return ""
    # Prefer the page (verified) image; fall back to the thumbnail.
    if tier == EvidenceTier.VERIFIED:
        return cache.page_local or cache.thumbnail_local
    return cache.thumbnail_local or cache.page_local


def main() -> int:
    ap = argparse.ArgumentParser(description="Face -> web -> blockchain pipeline")
    ap.add_argument("image_path", help="path to the input face image")
    ap.add_argument("--limit", type=int, default=5, help="max candidates to evaluate")
    ap.add_argument("--match-threshold", type=float, default=SIMILARITY_THRESHOLD)
    ap.add_argument(
        "--evidence-tier",
        choices=("all", "verified_only"),
        default="all",
        help="which match tiers are eligible for the final result",
    )
    ap.add_argument(
        "--hint",
        default="",
        help="text seed for the keyless social fallback (Bluesky/Mastodon/Reddit)",
    )
    ap.add_argument("--do-blockchain", action="store_true", default=None)
    ap.add_argument("--no-blockchain", action="store_true")
    ap.add_argument(
        "--anchor",
        choices=("auto", "local", "evm", "none"),
        default="",
        help="anchor backend: local Merkle ledger, EVM chain, auto, or none",
    )
    ap.add_argument(
        "--chain-dir",
        default="",
        help="chain data directory (default: BLOCKCHAIN_CHAIN_DIR or ./chaindata)",
    )
    ap.add_argument(
        "--difficulty",
        type=int,
        default=-1,
        help="PoW difficulty bits for the local chain (default: config, 0=off)",
    )
    ap.add_argument("--verify", action="store_true", help="also re-verify the digest after anchoring")
    args = ap.parse_args()

    case_dir = CaseDir()
    kv("case dir", str(case_dir.path))

    # ------------------------------------------------------------ stage 1
    stage(1, STAGES, "FACE SCAN")
    face = embed_face(args.image_path)
    if face is None:
        fail(f"no face detected in {args.image_path}")
        return 1
    kv("detector", "insightface buffalo_l")
    kv("embedding", f"{len(face.embedding)}-D ArcFace")
    kv("confidence", f"{face.confidence:.3f}")
    kv("bbox", str([round(v, 1) for v in face.bbox]))
    ok("face encoded")

    # ------------------------------------------------------------ stage 2
    stage(2, STAGES, "WEB / SOCIAL MEDIA SEARCH  (live)")
    search = search_web(args.image_path)

    source = search.provider or "reverse-image"
    if not search.has_results and args.hint:
        warn("keyed providers returned nothing — trying keyless social APIs")
        social = social_search(args.hint)
        if social.has_results:
            search = social
            source = "keyless_social"
            kv("provider", "Bluesky / Mastodon / Reddit (keyless)")
            kv("hint", args.hint)
        else:
            warn(f"keyless social fallback also empty: {social.error}")
    else:
        kv("provider", source)

    if not search.has_results:
        fail(search.error or "Reverse image search returned no candidates.")
        return 2
    kv("candidates", str(len(search.results)))
    kv("sources", ", ".join(search.providers_used or [source]) or source)
    ok(f"{len(search.results)} candidates returned live")

    # ------------------------------------------------------------ stage 3 + 4
    stage(3, STAGES, "FACE VERIFICATION OF CANDIDATES")
    kv("decision rule", f"cosine >= {args.match_threshold} (InsightFace)")
    with MatcherService(threshold=args.match_threshold) as service:
        evid = service.match_candidates(
            face.embedding, search.results[: args.limit]
        )

        matches: list = []
        for ev in evid:
            if ev.best_match is None or ev.score == 0.0:
                print(f"    {dim('no-face')}   {ev.page_url[:60]}")
                continue
            if ev.is_match:
                ok(f"cos={ev.score:.3f}  [{ev.platform}] {ev.page_url[:55]}")
                matches.append(ev)
            else:
                print(f"    {dim('no')}   cos={ev.score:.3f}  {ev.page_url[:55]}")

        # Apply evidence-tier filter.
        if args.evidence_tier == "verified_only":
            matches = [m for m in matches if m.tier == EvidenceTier.VERIFIED]

        if not matches:
            warn("no eligible face match found.")
            banner("NO MATCH")
            return 0

        # Sort by score desc + verified-tier priority.
        matches.sort(key=lambda m: (m.tier == EvidenceTier.VERIFIED, m.score), reverse=True)
        best = matches[0]
        ok(f"identity match confirmed on {cyan(best.platform)} ({best.tier.value})")
        kv("post url", best.page_url)

        # Resolve the local image path while the collector's temp files exist.
        local = _resolve_local_image(service, best.page_url, best.tier)

    # ------------------------------------------------------------ stage 4
    stage(4, STAGES, "EVIDENCE FINGERPRINT")
    if not local:
        fail("no local image available to hash; aborting")
        return 3
    img_sha = image_sha256_from_file(local)
    record = EvidenceRecord(
        evidence_id=f"cli-{img_sha[:16]}",
        source_url=best.page_url,
        canonical_url=best.page_url,
        platform=best.platform,
        source_type="cli",
        face_similarity=best.score,
        image_similarity=best.image_similarity,
        evidence_tier=best.tier.value,
        image_sha256=img_sha,
        caption=best.caption,
        title=best.title,
    )
    content_hash = fingerprint(record)
    kv("evidence tier", best.tier.value)
    kv("score", f"{best.score:.3f}")
    kv("image sha256", img_sha[:16] + "…")
    kv("content sha256", content_hash)
    ok("canonical evidence hashed")

    # ------------------------------------------------------------ stage 5
    stage(5, STAGES, "OUTPUT ARTEFACTS")
    try:
        from backend.face.model import read_image

        raw = read_image(args.image_path)
        if raw is not None:
            with open(args.image_path, "rb") as fh:
                case_dir.save_input(fh.read(), args.image_path)
            case_dir.save_annotated(raw, [face], label="input")
        ok(f"artefacts written -> {dim(str(case_dir.path))}")
    except Exception as exc:  # noqa: BLE001
        warn(f"skipped artefact writing: {exc}")

    # ------------------------------------------------------------ stage 6
    do_bc = not args.no_blockchain
    if args.do_blockchain is not None:
        do_bc = args.do_blockchain
    if args.anchor == "none":
        do_bc = False
    stage(6, STAGES, "BLOCKCHAIN  " + ("(enabled)" if do_bc else "(skipped)"))
    if do_bc:
        import os

        if args.anchor:
            os.environ["BLOCKCHAIN_ANCHOR"] = args.anchor
        if args.chain_dir:
            os.environ["BLOCKCHAIN_CHAIN_DIR"] = args.chain_dir
        if args.difficulty >= 0:
            os.environ["BLOCKCHAIN_DIFFICULTY"] = str(args.difficulty)

        from backend.blockchain.backend import resolve_backend
        from backend.blockchain.checks import checks_to_dicts
        from backend.blockchain.verifier import verify_on_blockchain

        try:
            backend = resolve_backend()
            receipt = backend.anchor(content_hash)
            kv("backend", receipt.backend)
            kv("network", receipt.network or "local-merkle-chain")
            if receipt.ref.get("tx_hash"):
                kv("tx hash", str(receipt.ref["tx_hash"])[:20] + "…")
            if receipt.block_hash:
                kv("block hash", receipt.block_hash[:20] + "…")
            kv("block", str(receipt.block_index or ""))
            kv("merkle root", (receipt.merkle_root or "")[:20] + "…")
            kv("idempotent", str(receipt.idempotent_hit))
            verified = verify_on_blockchain(content_hash, backend_name=receipt.backend)
            kv("on-chain verify", str(verified))
            ok(f"digest anchored on {receipt.backend}")
            if args.verify:
                from backend.blockchain.verifier import verify_record

                checks = verify_record(content_hash, receipt)
                for c in checks:
                    kv(c.name, "PASS" if c.ok else f"FAIL  {c.detail}")
                print("  " + ("ALL CHECKS PASS" if all(c.ok for c in checks) else "CHECK FAILURES"))
                try:
                    case_dir.save_receipt(
                        {
                            "content_hash": content_hash,
                            "backend": receipt.backend,
                            "network": receipt.network,
                            "block_hash": receipt.block_hash,
                            "block_number": receipt.block_index,
                            "merkle_root": receipt.merkle_root,
                            "idempotent": receipt.idempotent_hit,
                            "checks": checks_to_dicts(checks),
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass
        except (ValueError, ConnectionError) as exc:
            fail(str(exc))
    else:
        warn("blockchain skipped (use --do-blockchain)")

    banner("PIPELINE COMPLETE")
    print(f"  post        {best.page_url}")
    print(f"  score       {best.score:.4f}")
    print(f"  digest      {content_hash}")
    print(f"  artefacts   {dim(str(case_dir.path))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
