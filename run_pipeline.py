"""Runnable end-to-end pipeline for a single input face image.

Usage:
    python run_pipeline.py <image_path> [--limit N] [--match-threshold 0.4]
                              [--evidence-tier all|verified_only]

Runs: face detect -> reverse search -> tiered face match (thumbnail + page)
-> fingerprint -> (optional) blockchain register/verify.

Evidence tiers:
  - verified  : matched against the real post content image (page crawl)
  - thumbnail : matched against the search thumbnail only (login-walled post)
  - none      : no match

--evidence-tier controls which matches are eligible to become the result:
  - all          (default) retain verified AND thumbnail matches
  - verified_only retain only verified (page-content) matches
"""

from __future__ import annotations

import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from backend.face.embedder import embed_face
from backend.face.matcher import (
    SIMILARITY_THRESHOLD,
    EvidenceTier,
)
from backend.search.visual_search import search_web
from backend.matching.service import MatcherService
from backend.fingerprint.canonicalizer import ContentRecord, image_sha256_from_file
from backend.fingerprint.hasher import fingerprint


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
    ap.add_argument("--do-blockchain", action="store_true", default=None)
    ap.add_argument("--no-blockchain", action="store_true")
    args = ap.parse_args()

    # 1. Face detection + embedding
    print("== Step 1: face detection + embedding ==")
    face = embed_face(args.image_path)
    if face is None:
        print("ERROR: no face detected in", args.image_path)
        return 1
    print(f"  detected face, confidence={face.confidence:.3f}, embedding={len(face.embedding)}d")

    # 2. Reverse visual search
    print("\n== Step 2: reverse image search ==")
    search = search_web(args.image_path)
    if not search.has_results:
        print("  no results; error:", search.error or "unknown")
        return 2
    print(f"  provider={search.provider}, {len(search.results)} candidates")

    # 3 + 4. Tiered face matching (thumbnail PATH A + page PATH B)
    print("\n== Step 3: tiered face matching (thumbnail + page) ==")
    with MatcherService(threshold=args.match_threshold) as service:
        evid = service.match_candidates(
            face.embedding, search.results[: args.limit]
        )

        matches: list = []
        for ev in evid:
            m = ev.best_match
            if m is None or ev.score == 0.0:
                print(f"  no-face     url={ev.page_url[:60]}")
                continue
            flag = f"MATCH[{m.tier.value}]" if ev.is_match else "no"
            print(
                f"  {flag:<14} score={ev.score:.3f} (thumb={ev.thumbnail_match.score:.3f} "
                f"page={ev.page_match.score if ev.page_match else 0.0:.3f}) url={ev.page_url[:55]}"
            )
            if ev.is_match:
                matches.append(ev)

        # Apply evidence-tier filter.
        if args.evidence_tier == "verified_only":
            matches = [m for m in matches if m.tier == EvidenceTier.VERIFIED]

        if not matches:
            print("\nNo eligible face match found.")
            return 0

        # Sort by score desc + verified-tier priority.
        matches.sort(key=lambda m: (m.tier == EvidenceTier.VERIFIED, m.score), reverse=True)
        best = matches[0]

        # 5. Fingerprint the best match
        print("\n== Step 5: content fingerprinting ==")
        local = _resolve_local_image(service, best.page_url, best.tier)
        if not local:
            print("  no local image available to hash; aborting")
            return 3
        img_sha = image_sha256_from_file(local)
        record = ContentRecord(
            post_url=best.page_url,
            image_sha256=img_sha,
            caption=best.caption,
            platform=best.platform,
            title=best.title,
            evidence=best.tier.value,
        )
        content_hash = fingerprint(record)
        img_label = (
            getattr(best.page_match, "image_url", "")
            or best.image_url
            or best.thumbnail_match.image_url if best.thumbnail_match else best.image_url
        )
        print(f"  image_url={img_label}")
        print(f"  evidence_tier={best.tier.value}  score={best.score:.3f}")
        print(f"  post_url={best.page_url}")
        print(f"  content_sha256={content_hash}")

        # 6. (Optional) blockchain
        do_bc = not args.no_blockchain
        if args.do_blockchain is not None:
            do_bc = args.do_blockchain
        if do_bc:
            print("\n== Step 6: blockchain ==")
            from backend.blockchain.registry import register_on_blockchain
            from backend.blockchain.verifier import verify_on_blockchain

            try:
                tx_hash, block = register_on_blockchain(content_hash)
                print(f"  registered tx={tx_hash[:20]}... block={block}")
                ok = verify_on_blockchain(content_hash)
                print(f"  on-chain verify: {ok}")
            except (ValueError, ConnectionError) as exc:
                print(f"  (skipped) {exc}")
        else:
            print("\n== Step 6: blockchain SKIPPED ==")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
