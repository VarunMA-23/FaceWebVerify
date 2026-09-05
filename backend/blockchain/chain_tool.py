"""CLI for the local Merkle chain: show / verify / tamper.

Usage::

    python -m backend.blockchain.chain_tool show [--chain-dir DIR]
    python -m backend.blockchain.chain_tool verify [--chain-dir DIR]
    python -m backend.blockchain.chain_tool tamper [--chain-dir DIR]

``tamper`` deliberately corrupts one block so you can watch ``verify`` catch it
(demo only).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.blockchain.config import get_chain_dir, get_difficulty
from backend.blockchain.errors import ChainIntegrityError
from backend.blockchain.localchain import LocalChain


def _get_chain(args: argparse.Namespace) -> LocalChain:
    chain_dir = Path(args.chain_dir or get_chain_dir()) / "local"
    difficulty = get_difficulty()
    if args.difficulty is not None:
        difficulty = max(0, int(args.difficulty))
    return LocalChain(chain_dir, difficulty_bits=difficulty)


def _show(args: argparse.Namespace) -> int:
    chain = _get_chain(args)
    print(f"chain dir : {chain.path}")
    print(f"network   : {chain.network}")
    for block in chain.blocks():
        print(json.dumps(block, indent=1, sort_keys=True))
    return 0


def _verify(args: argparse.Namespace) -> int:
    chain = _get_chain(args)
    try:
        chain.verify_chain()
        print("CHAIN INTEGRITY: OK")
        return 0
    except ChainIntegrityError as exc:
        print(f"CHAIN INTEGRITY: FAILED -- {exc}")
        return 1


def _tamper(args: argparse.Namespace) -> int:
    chain = _get_chain(args)
    blocks = chain.blocks()
    if len(blocks) < 2:
        print("nothing to tamper with: only the genesis block exists")
        return 1
    victim = blocks[-1]
    idx = victim["index"]
    mutated = dict(victim)
    # Corrupt the Merkle root so the block hash no longer matches.
    root = mutated["merkle_root"]
    flipped = ("1" if root[0] in ("0", "f") else "0") + root[1:]
    mutated["merkle_root"] = flipped
    lines = chain.path.read_text(encoding="utf-8").splitlines()
    lines[idx] = json.dumps(mutated, sort_keys=True, separators=(",", ":"))
    chain.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"tampered block {idx}: merkle_root {root[:16]}… -> {flipped[:16]}…")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="local Merkle chain tool")
    ap.add_argument("--chain-dir", default=None, help="override BLOCKCHAIN_CHAIN_DIR")
    ap.add_argument("--difficulty", default=None, type=int, help="PoW bits (0 = none)")
    sub = ap.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show", help="print every block")
    p_show.set_defaults(func=_show)

    p_verify = sub.add_parser("verify", help="full structural integrity check")
    p_verify.set_defaults(func=_verify)

    p_tamper = sub.add_parser("tamper", help="corrupt one block (demo)")
    p_tamper.set_defaults(func=_tamper)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())