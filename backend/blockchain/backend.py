"""Anchor backend protocol + factory.

Backends implement the ``AnchorBackend`` protocol:

* :class:`LocalChain` — the DEFAULT: a hash-linked Merkle ledger on disk.
* :class:`EVMAnchor` — OPTIONAL: a real public EVM testnet (Sepolia).

Selection is driven by environment (``BLOCKCHAIN_ANCHOR``), overridable by an
explicit argument. The ``DO_BLOCKCHAIN`` master switch disables anchoring.
"""

from __future__ import annotations

from typing import Protocol

from backend.blockchain import config
from backend.blockchain.checks import Check
from backend.blockchain.errors import BackendUnavailableError
from backend.blockchain.models import AnchorReceipt


class AnchorBackend(Protocol):
    name: str
    network: str

    def available(self) -> bool: ...

    def anchor(self, record_hash: str) -> AnchorReceipt: ...

    def verify(self, record_hash: str, receipt: AnchorReceipt) -> list[Check]: ...


class DisabledAnchor:
    """No-op backend used when anchoring is switched off."""

    name = "none"
    network = "disabled"

    def available(self) -> bool:
        return True

    def anchor(self, record_hash: str) -> AnchorReceipt:
        raise BackendUnavailableError("blockchain anchoring is disabled")

    def verify(self, record_hash: str, receipt: AnchorReceipt) -> list[Check]:
        return [
            Check(
                name="none.disabled",
                ok=False,
                detail="blockchain anchoring is disabled",
            )
        ]


def resolve_backend(anchor: str | None = None) -> AnchorBackend:
    """Resolve the active anchor backend.

    Priority: explicit ``anchor`` argument » ``BLOCKCHAIN_ANCHOR`` env. The
    ``DO_BLOCKCHAIN`` master switch (any of 0/false/no/off/none) disables
    anchoring entirely and returns a :class:`DisabledAnchor`.
    """
    mode = (anchor or config.get_anchor_mode() or "local").lower()
    if not config.do_blockchain_enabled() or mode == "none":
        return DisabledAnchor()
    if mode == "evm":
        from backend.blockchain.evm import EVMAnchor

        if not EVMAnchor.available():
            raise BackendUnavailableError(
                "EVM anchor requested but not configured; set SEPOLIA_WALLET_PRIVATE_KEY "
                "(and optionally SEPOLIA_CONTRACT_ADDRESS), or use BLOCKCHAIN_ANCHOR=local"
            )
        return EVMAnchor()
    if mode == "local":
        from backend.blockchain.localchain import LocalChain

        return LocalChain(
            config.get_chain_dir() / "local",
            difficulty_bits=config.get_difficulty(),
        )
    raise ValueError(f"Unknown BLOCKCHAIN_ANCHOR: {mode}")