"""Interactive, guided CLI for the Face → Web → Blockchain pipeline.

Usage:
    python run_pipeline.py                        # interactive wizard
    python run_pipeline.py <image_path> [options] # batch / scripted run
    python run_pipeline.py --interactive <image_path>

Runs: face detect → reverse search (or keyless social fallback) → tiered
face match (thumbnail + page) → fingerprint → (optional) blockchain
register/verify.

Artifacts are written to ``out/case-<timestamp>-<embed>/``.

Evidence tiers:
  - verified  : matched against the real post content image (page crawl)
  - thumbnail : matched against the search thumbnail only (login-walled post)
  - none      : no match

``--evidence-tier`` controls which matches are eligible to become the result:
  - all          (default) retain verified AND thumbnail matches
  - verified_only retain only verified (page-content) matches

``--hint`` seeds the keyless social fallback (Bluesky/Mastodon/Reddit) when no
reverse-image API keys are configured.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

if os.name == "nt":
    os.system("")  # enable VT processing so ANSI colour works on legacy Windows

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from backend.face.embedder import embed_face
from backend.face.matcher import SIMILARITY_THRESHOLD, EvidenceTier
from backend.fingerprint.canonicalizer import EvidenceRecord, image_sha256_from_file
from backend.fingerprint.hasher import fingerprint
from backend.matching.service import MatcherService
from backend.output import CaseDir
from backend.search.visual_search import PROVIDERS, search_web

STAGES = 6
console = Console()

APP_TITLE = r"""
   __                                             __
  / _|                                             | |
 | |_  __ _  ___ _ __   ___ _ ____      ____ _ _ __| |_ ___ _ __
 |  _|/ _` |/ _ \ '_ \ / _ \ '__\ \ /\ / / _` | '__| __/ _ \ '__|
 | | | (_| |  __/ | | |  __/ |   \ V  V / (_| | |  | ||  __/ |
 |_|  \__,_|\___|_| |_|\___|_|    \_/\_/ \__,_|_|   \__\___|_|
"""


class _Quit(Exception):
    """Raised when the user aborts the interactive wizard."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RunConfig:
    image_path: str = ""
    limit: int = 5
    threshold: float = SIMILARITY_THRESHOLD
    evidence_tier: str = "all"
    hint: str = ""
    provider: str = "auto"
    anchor: str = ""
    chain_dir: str = ""
    difficulty: int = -1
    verify: bool = False
    do_blockchain: bool | None = None
    no_blockchain: bool = False

    @property
    def effective_blockchain(self) -> bool:
        if self.anchor == "none":
            return False
        if self.do_blockchain is not None:
            return self.do_blockchain
        return not self.no_blockchain


# ---------------------------------------------------------------------------
# Small rich output helpers
# ---------------------------------------------------------------------------


def stage_header(num: int, title: str, subtitle: str = "") -> None:
    console.print()
    label = f"[bold cyan]STAGE {num}/{STAGES}[/]  [bold]{title}[/]"
    if subtitle:
        label += f"  [dim]· {subtitle}[/]"
    console.print(Rule(label))


def ok(msg: str) -> None:
    console.print(f"  [bold green]✓[/] {msg}")


def info(msg: str) -> None:
    console.print(f"  [dim]·[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"  [bold yellow]⚠[/] {msg}")


def fail(msg: str) -> None:
    console.print(f"  [bold red]✗[/] {msg}")


def kv(key: str, value: str) -> None:
    console.print(f"  [dim]{key:<22}[/] {value}")


def _digest(hex_str: str) -> str:
    return f"{hex_str[:16]}…" if hex_str else ""


# ---------------------------------------------------------------------------
# Interactive wizard (questionary)
# ---------------------------------------------------------------------------


def _qa() -> object:
    import questionary

    return questionary


def _can_browse() -> bool:
    try:
        import tkinter  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _browse_dialog() -> str:
    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="Choose a face image",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.webp *.bmp"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        return path or ""
    except Exception:  # noqa: BLE001
        return ""


def _pick_image(prefilled: str = "") -> str:
    q = _qa()
    if prefilled and os.path.isfile(prefilled):
        use = q.confirm(f"Use image: {prefilled}", default=True).ask()
        if use:
            return prefilled

    choices = [
        q.Choice("Type or drag & drop a file path", "type"),
        *([q.Choice("Open a file browser…", "browse")] if _can_browse() else []),
        q.Choice("Quit", "quit"),
    ]
    while True:
        pick = q.select("How would you like to provide the face image?", choices=choices).ask()
        if pick == "quit":
            raise _Quit()
        path = _browse_dialog() if pick == "browse" else q.text(
            "Image path (drag & drop works)",
            instruction="e.g. C:\\Users\\me\\Downloads\\face.jpg or ./data/lena.jpg",
        ).ask()
        if path and os.path.isfile(path):
            return path
        warn("That path does not exist — please try again.")


def _pick_threshold() -> float:
    q = _qa()
    value = q.select(
        "Face-match similarity threshold",
        choices=[
            q.Choice("0.40 — Default (InsightFace convention)", 0.40),
            q.Choice("0.25 — Relaxed (more matches)", 0.25),
            q.Choice("0.55 — Moderate", 0.55),
            q.Choice("0.65 — Strict", 0.65),
            q.Choice("Custom value…", "custom"),
        ],
    ).ask()
    if value != "custom":
        return float(value)
    while True:
        raw = q.text("Threshold value (0.0 – 1.0)", default="0.40").ask()
        try:
            value = float(raw)
        except (TypeError, ValueError):
            warn("That is not a number — try again.")
            continue
        if 0.0 <= value <= 1.0:
            return value
        warn("Must be between 0.0 and 1.0.")


def _pick_provider() -> str:
    q = _qa()
    available = [p for p in PROVIDERS if p.available()]
    choices = [q.Choice("Auto — run all configured providers and merge results", "auto")]
    choices += [
        q.Choice(f"{p.name} only — {p.endpoint}", p.name) for p in available
    ]
    choices.append(
        q.Choice(
            "Keyless social — Bluesky / Mastodon / Reddit (needs a hint)", "keyless"
        )
    )
    provider = q.select("Reverse image search provider", choices=choices).ask()
    if provider == "keyless" and not available:
        warn("No search API keys configured — keyless social it is.")
    return provider or "auto"


def _pick_anchor() -> str:
    q = _qa()
    return q.select(
        "Blockchain anchor",
        choices=[
            q.Choice("Local Merkle ledger — default, zero setup", "local"),
            q.Choice("Auto — decide from environment (BLOCKCHAIN_ANCHOR)", "auto"),
            q.Choice("EVM (Sepolia) — requires wallet key + contract", "evm"),
            q.Choice("None — skip anchoring", "none"),
        ],
    ).ask() or "local"


def interactive_wizard(prefilled_image: str = "") -> RunConfig:
    q = _qa()
    console.print(Panel(APP_TITLE, box=box.ROUNDED, style="bold cyan"))
    console.print(
        Panel(
            "[cyan]Face → Web → Blockchain[/] · I'll guide you through a live "
            "investigation, step by step. Press [bold]Ctrl+C[/] at any time to quit.",
            box=box.SIMPLE,
        )
    )

    image_path = _pick_image(prefilled_image)
    hint = q.text(
        "Optional text hint (e.g. the person's name)",
        default="",
        instruction="Only used by the keyless social fallback. Leave empty to skip.",
    ).ask() or ""
    threshold = _pick_threshold()
    tier = q.select(
        "Eligible evidence tiers",
        choices=[
            q.Choice("All matches — verified + thumbnail", "all"),
            q.Choice("Verified only — real post page content", "verified_only"),
        ],
    ).ask() or "all"
    provider = _pick_provider()
    limit = _pick_limit()
    anchor = _pick_anchor()

    cfg = RunConfig(
        image_path=image_path,
        limit=limit,
        threshold=threshold,
        evidence_tier=tier,
        hint=hint,
        provider=provider,
        anchor=anchor,
    )
    if provider == "keyless" and not hint:
        warn("Keyless social search needs a hint — add one on the next screen.")
        hint = q.text("Text hint for social search", default="").ask() or ""
        cfg.hint = hint

    _show_config_panel(cfg)
    if not q.confirm("Everything look right? Start the investigation?", default=True).ask():
        raise _Quit()
    return cfg


def _pick_limit() -> int:
    q = _qa()
    choice = q.select(
        "How many search candidates to evaluate",
        choices=[
            q.Choice("5 candidates (default)", 5),
            q.Choice("10 candidates", 10),
            q.Choice("20 candidates", 20),
            q.Choice("50 candidates", 50),
            q.Choice("Custom…", "custom"),
        ],
    ).ask()
    if choice != "custom":
        return int(choice)
    while True:
        raw = q.text("How many candidates?", default="10").ask()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            warn("That is not a whole number.")
            continue
        if value >= 1:
            return value
        warn("Must be at least 1.")


def _show_config_panel(cfg: RunConfig) -> None:
    lines = [
        f"  [dim]Image      [/] {cfg.image_path}",
        f"  [dim]Provider   [/] {cfg.provider}",
        f"  [dim]Candidates [/] {cfg.limit}",
        f"  [dim]Threshold  [/] {cfg.threshold:.2f}",
        f"  [dim]Tier       [/] {cfg.evidence_tier}",
        f"  [dim]Hint       [/] {cfg.hint or '—'}",
        f"  [dim]Anchor     [/] {cfg.anchor}",
    ]
    console.print(Panel("\n".join(lines), title="Run configuration", box=box.ROUNDED))


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


def _resolve_local_image(service: MatcherService, url: str, tier: EvidenceTier) -> str:
    cache = service.evidence_cache.get(url)
    if cache is None:
        return ""
    if tier == EvidenceTier.VERIFIED:
        return cache.page_local or cache.thumbnail_local
    return cache.thumbnail_local or cache.page_local


def _persist_input_artifacts(case_dir: CaseDir, image_path: str, face) -> bool:
    try:
        from backend.face.model import read_image

        raw = read_image(image_path)
        if raw is None:
            return False
        with open(image_path, "rb") as fh:
            case_dir.save_input(fh.read(), image_path)
        case_dir.save_annotated(raw, [face], label="input")
        return True
    except Exception:  # noqa: BLE001
        return False


def _persist_match_artifacts(case_dir: CaseDir, local: str) -> bool:
    if not local or not os.path.exists(local):
        return False
    try:
        import cv2

        from backend.face.detector import detect_faces

        case_dir.save_match_bytes(Path(local).read_bytes())
        img = cv2.imread(local)
        if img is not None:
            case_dir.save_match_annotated(img, detect_faces(img))
        return True
    except Exception:  # noqa: BLE001
        return False


def _render_candidates(evid: list) -> None:
    if not evid:
        return
    table = Table(box=box.SIMPLE_HEAD, expand=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Platform")
    table.add_column("Tier")
    table.add_column("Cos.", justify="right")
    table.add_column("URL", max_width=52)
    for i, ev in enumerate(evid, 1):
        style = "bold green" if ev.is_match else "dim"
        table.add_row(
            str(i),
            ev.platform or "—",
            ev.tier.value,
            f"{ev.score:.3f}",
            ev.page_url[:60],
            style=style,
        )
    console.print(table)


def _render_matches(matches: list) -> None:
    """Render every accepted match, with the attested best one flagged."""
    if not matches:
        return
    table = Table(box=box.SIMPLE_HEAD, expand=False)
    table.add_column("Rank", justify="right", style="dim")
    table.add_column("Platform")
    table.add_column("Tier")
    table.add_column("Cos.", justify="right")
    table.add_column("URL", max_width=52)
    for rank, ev in enumerate(matches, 1):
        is_best = rank == 1
        style = "bold yellow" if is_best else ""
        table.add_row(
            f"{rank}{' ★' if is_best else ''}",
            ev.platform or "—",
            ev.tier.value,
            f"{ev.score:.3f}",
            ev.page_url[:60],
            style=style,
        )
    console.print(table)
    if matches:
        console.print("[dim]★ = attested best match[/]")


def _render_report(
    best,
    matches: list,
    content_hash: str,
    img_sha: str,
    case_dir: CaseDir,
    blockchain: dict | None,
) -> None:
    lines: list[str] = [f"  [bold underline]Accepted matches ({len(matches)})[/]"]
    for i, m in enumerate(matches, 1):
        star = "★" if m is best else " "
        lines.append(
            f"  {star}{i:>2}. [{m.tier.value}] {m.platform or '—'}  "
            f"cos={m.score:.4f}  [dim]{m.page_url[:72]}[/]"
        )
    lines += [
        "",
        f"  [bold]Attested post[/]  {best.page_url}",
        f"  [bold]Image SHA-256[/]  {_digest(img_sha)}",
        f"  [bold]Content hash[/]   {content_hash}",
        f"  [bold]Artefacts[/]      {case_dir.path}",
    ]
    if blockchain:
        lines += [
            "",
            f"  [bold]Anchor[/]        {blockchain.get('backend', '—')}",
            f"  [bold]Network[/]       {blockchain.get('network') or '—'}",
            f"  [bold]Block[/]         {blockchain.get('block_number') or '—'}",
            f"  [bold]Merkle root[/]   {_digest(blockchain.get('merkle_root') or '')}",
            f"  [bold]On-chain[/]      "
            + ("✓ verified" if blockchain.get("verified") else "not verified"),
        ]
    console.print(Panel("\n".join(lines), title="Case report", box=box.ROUNDED, style="bold"))


def run_blockchain(cfg: RunConfig, content_hash: str, case_dir: CaseDir) -> dict | None:
    if cfg.anchor:
        os.environ["BLOCKCHAIN_ANCHOR"] = cfg.anchor
    if cfg.chain_dir:
        os.environ["BLOCKCHAIN_CHAIN_DIR"] = cfg.chain_dir
    if cfg.difficulty >= 0:
        os.environ["BLOCKCHAIN_DIFFICULTY"] = str(cfg.difficulty)

    from backend.blockchain.backend import resolve_backend
    from backend.blockchain.checks import checks_to_dicts
    from backend.blockchain.errors import BackendUnavailableError
    from backend.blockchain.verifier import verify_on_blockchain

    try:
        with console.status("Anchoring evidence digest…", spinner="dots"):
            receipt = resolve_backend().anchor(content_hash)
        ref = dict(receipt.ref or {})
        kv("backend", receipt.backend)
        kv("network", receipt.network or "local-merkle-chain")
        if ref.get("tx_hash"):
            kv("tx hash", str(ref["tx_hash"])[:24] + "…")
        if receipt.block_hash:
            kv("block hash", receipt.block_hash[:24] + "…")
        kv("block", str(receipt.block_index or ""))
        kv("merkle root", _digest(receipt.merkle_root or ""))
        kv("idempotent", str(receipt.idempotent_hit))
        verified = verify_on_blockchain(content_hash, backend_name=receipt.backend)
        kv("on-chain verify", str(verified))
        ok(f"digest anchored on {receipt.backend}")

        report = {
            "content_hash": content_hash,
            "backend": receipt.backend,
            "network": receipt.network,
            "tx_hash": ref.get("tx_hash"),
            "block_hash": receipt.block_hash,
            "block_number": receipt.block_index,
            "merkle_root": receipt.merkle_root,
            "idempotent": receipt.idempotent_hit,
            "verified": bool(verified),
        }

        if cfg.verify:
            from backend.blockchain.verifier import verify_record

            with console.status("Running verification checks…", spinner="dots"):
                checks = verify_record(content_hash, receipt)
            for c in checks:
                kv(c.name, "PASS" if c.ok else f"FAIL  {c.detail}")
            console.print("  " + (
                "[bold green]ALL CHECKS PASS[/]" if all(c.ok for c in checks)
                else "[bold red]CHECK FAILURES[/]"
            ))
            report["checks"] = checks_to_dicts(checks)

        try:
            case_dir.save_receipt(report)
        except Exception:  # noqa: BLE001
            pass
        return report
    except (ValueError, ConnectionError, BackendUnavailableError) as exc:
        fail(str(exc))
        return None


def run_case(cfg: RunConfig) -> int:
    case_dir = CaseDir()

    # ------------------------------------------------------------ stage 1
    stage_header(1, "FACE SCAN", "InsightFace buffalo_l")
    with console.status("Detecting face…", spinner="dots"):
        face = embed_face(cfg.image_path)
    if face is None:
        fail(f"no face detected in {cfg.image_path}")
        return 1
    ok(f"face detected — confidence {face.confidence:.3f}")
    kv("detector", "insightface buffalo_l")
    kv("embedding", f"{len(face.embedding)}-D ArcFace")
    kv("bbox", str([round(v, 1) for v in face.bbox]))

    # ------------------------------------------------------------ stage 2
    stage_header(2, "WEB / SOCIAL MEDIA SEARCH", "live")
    search = None
    source = cfg.provider
    if cfg.provider == "keyless":
        with console.status("Querying keyless social APIs (Bluesky / Mastodon / Reddit)…", spinner="dots"):
            search = social_search(cfg.hint)
        source = "keyless_social"
    else:
        with console.status(f"Reverse image search ({_provider_label(cfg.provider)})…", spinner="dots"):
            search = search_web(cfg.image_path, provider=cfg.provider)
        source = search.provider or "reverse-image"
        if not search.has_results and cfg.hint:
            warn("keyed providers returned nothing — trying keyless social APIs")
            with console.status("Querying Bluesky / Mastodon / Reddit…", spinner="dots"):
                social = social_search(cfg.hint)
            if social.has_results:
                search = social
                source = "keyless_social"
                info(f"hint: {cfg.hint}")

    if not search.has_results:
        fail(search.error or "Reverse image search returned no candidates.")
        return 2
    ok(f"{len(search.results)} candidates returned live")
    kv("provider", source)
    kv("sources", ", ".join(search.providers_used or [source]) or source)

    # ------------------------------------------------ stages 3 + 4
    with MatcherService(threshold=cfg.threshold) as service:
        stage_header(
            3,
            "FACE VERIFICATION OF CANDIDATES",
            f"cosine ≥ {cfg.threshold:.2f}",
        )
        candidates = search.results[: cfg.limit]
        with console.status(
            f"Comparing embeddings across up to {len(candidates)} candidates…",
            spinner="dots",
        ):
            evid = service.match_candidates(face.embedding, candidates)

        matches: list = []
        for ev in evid:
            if ev.best_match is None or ev.score == 0.0:
                continue
            if ev.is_match:
                ok(f"cos={ev.score:.3f}  [{ev.platform or '?'}] {ev.page_url[:55]}")
                matches.append(ev)
            else:
                info(f"no   cos={ev.score:.3f}  {ev.page_url[:55]}")

        if cfg.evidence_tier == "verified_only":
            matches = [m for m in matches if m.tier == EvidenceTier.VERIFIED]

        if not matches:
            warn("no eligible face match found.")
            console.print(Panel("[bold red]NO MATCH[/]", box=box.ROUNDED, style="bold red"))
            return 0

        matches.sort(
            key=lambda m: (m.tier == EvidenceTier.VERIFIED, m.score), reverse=True
        )
        best = matches[0]
        _render_candidates(evid)
        _render_matches(matches)

        # Resolve the local image while the collector's temp files exist.
        local = _resolve_local_image(service, best.page_url, best.tier)

        # ------------------------------------------------------------ stage 4
        stage_header(4, "EVIDENCE FINGERPRINT")
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
        kv("image sha256", _digest(img_sha))
        kv("content sha256", content_hash)
        ok("canonical evidence hashed")
        ok(f"identity match confirmed on {best.platform or '?'} ({best.tier.value})")

        # Persist the matched image bytes (still on disk inside this context).
        if _persist_match_artifacts(case_dir, local):
            info(f"match artifacts → {case_dir.path / 'match.jpg'}")

    # ------------------------------------------------------------ stage 5
    stage_header(5, "OUTPUT ARTEFACTS")
    if _persist_input_artifacts(case_dir, cfg.image_path, face):
        ok(f"artefacts written → {case_dir.path}")
    else:
        warn("skipped artefact writing")

    # ------------------------------------------------------------ stage 6
    label = "enabled" if cfg.effective_blockchain else "skipped"
    stage_header(6, "BLOCKCHAIN", label)
    blockchain: dict | None = None
    if cfg.effective_blockchain:
        blockchain = run_blockchain(cfg, content_hash, case_dir)
    else:
        if cfg.no_blockchain or cfg.anchor == "none":
            warn("blockchain skipped (--no-blockchain / anchor=none)")
        else:
            warn("blockchain skipped (use --do-blockchain)")

    _render_report(best, matches, content_hash, img_sha, case_dir, blockchain)

    console.print()
    console.print(Panel("[bold green]PIPELINE COMPLETE[/]", box=box.SQUARE))
    for i, m in enumerate(matches, 1):
        star = "★" if m is best else " "
        console.print(f"  {star}{i}. [{m.tier.value}] {m.score:.4f}  {m.page_url}")
    console.print(f"  attested digest {content_hash}")
    console.print(f"  artefacts       {case_dir.path}")
    return 0


def _provider_label(provider: str) -> str:
    if not provider or provider == "auto":
        return "all configured providers"
    return provider


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Face → web → blockchain pipeline (interactive by default)"
    )
    ap.add_argument("image_path", nargs="?", help="path to the input face image")
    ap.add_argument("--interactive", action="store_true", help="force the guided wizard")
    ap.add_argument("--limit", type=int, default=5, help="max candidates to evaluate")
    ap.add_argument("--match-threshold", type=float, default=SIMILARITY_THRESHOLD)
    ap.add_argument(
        "--evidence-tier",
        choices=("all", "verified_only"),
        default="all",
        help="which match tiers are eligible for the final result",
    )
    ap.add_argument(
        "--provider",
        default="auto",
        help="search provider: auto, openwebninja, serpapi, tineye, or keyless",
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
    ap.add_argument(
        "--verify", action="store_true", help="also re-verify the digest after anchoring"
    )
    return ap


def main() -> int:
    from backend.search.social import social_search

    args = _build_parser().parse_args()
    interactive = args.interactive or not args.image_path

    if interactive:
        if not sys.stdin.isatty():
            console.print(
                "[red]Interactive mode needs a terminal. Run:[/] "
                "[bold]python run_pipeline.py <image_path> [options][/]"
            )
            return 2
        try:
            cfg = interactive_wizard(prefilled_image=args.image_path or "")
        except _Quit:
            console.print("[dim]Aborted by the user.[/]")
            return 0
        while True:
            code = run_case(cfg)
            from questionary import confirm

            again = confirm("Run another investigation?", default=False).ask()
            if not again:
                break
            try:
                cfg = interactive_wizard(prefilled_image=args.image_path or "")
            except _Quit:
                break
        console.print("[bold green]Until next time. Stay curious![/]")
        return code

    cfg = RunConfig(
        image_path=args.image_path,
        limit=args.limit,
        threshold=args.match_threshold,
        evidence_tier=args.evidence_tier,
        hint=args.hint,
        provider=args.provider,
        anchor=args.anchor,
        chain_dir=args.chain_dir,
        difficulty=args.difficulty,
        verify=args.verify,
        do_blockchain=args.do_blockchain,
        no_blockchain=args.no_blockchain,
    )
    return run_case(cfg)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
        sys.exit(130)