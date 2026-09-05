"""Environment-based configuration for the blockchain/anchoring layer.

The local hash-linked Merkle chain is the default backend and requires no
configuration. EVM (Sepolia) anchoring is optional and only engaged when the
user opts in via ``BLOCKCHAIN_ANCHOR=evm``.

No web3 import here — this module must stay importable in the web3-free core.
"""

from __future__ import annotations

import os
from pathlib import Path

import dotenv

dotenv.load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_DEFAULT_RPC_URL = "https://ethereum-sepolia-rpc.publicnode.com"


def get_anchor_mode() -> str:
    """Active anchor backend: local (default) | evm | none."""
    return os.environ.get("BLOCKCHAIN_ANCHOR", "local").strip().lower()


def do_blockchain_enabled() -> bool:
    """Master kill-switch (kept for backward compat with ``DO_BLOCKCHAIN``)."""
    value = os.environ.get("DO_BLOCKCHAIN", "auto").strip().lower()
    return value not in ("0", "false", "no", "off", "none")


def get_chain_dir() -> Path:
    """Root directory for chain state (local ledger + evm idempotency cache)."""
    raw = os.environ.get("BLOCKCHAIN_CHAIN_DIR", "").strip()
    return Path(raw) if raw else PROJECT_ROOT / "chaindata"


def get_difficulty() -> int:
    """Local-chain proof-of-work difficulty in leading zero bits."""
    raw = os.environ.get("BLOCKCHAIN_DIFFICULTY", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def get_rpc_url() -> str:
    return os.environ.get("SEPOLIA_RPC_URL", _DEFAULT_RPC_URL).strip()


def get_private_key() -> str:
    return os.environ.get("SEPOLIA_WALLET_PRIVATE_KEY", "").strip()


def get_contract_address() -> str:
    return os.environ.get("SEPOLIA_CONTRACT_ADDRESS", "").strip()


def get_evm_mode() -> str:
    """EVM anchoring mode: auto | calldata | registry."""
    return os.environ.get("EVM_MODE", "auto").strip().lower()


def get_evm_confirmations() -> int:
    raw = os.environ.get("EVM_CONFIRMATIONS", "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def evm_configured() -> bool:
    """True when a funded RPC endpoint + signing key are available."""
    return bool(get_rpc_url() and get_private_key())