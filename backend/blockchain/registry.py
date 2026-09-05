"""Anchoring entry points (Modules 7 + 8).

The primary API is backend-agnostic: :func:`anchor_on_blockchain` resolves the
active backend (local Merkle chain by default, EVM optional) and anchors the
content hash, returning an :class:`AnchorReceipt`.

The EVM-only registration/revocation functions (``registerEvidence`` /
``revokeEvidence`` / evidence attestation) are retained for the blockchain
evidence subsystem used by the ``/evidence/*`` endpoints.
"""

from __future__ import annotations

from backend.blockchain.backend import resolve_backend
from backend.blockchain.errors import BackendUnavailableError
from backend.blockchain.models import AnchorReceipt
from backend.blockchain.utils import validate_record_hash


def anchor_on_blockchain(content_sha256: str, anchor: str | None = None) -> AnchorReceipt:
    """Anchor a content hash on the active backend and return its receipt."""
    record_hash = validate_record_hash(content_sha256)
    backend = resolve_backend(anchor)
    return backend.anchor(record_hash)


def register_on_blockchain(content_sha256: str, anchor: str | None = None) -> dict:
    """Register content on the active backend (compat surface).

    Returns a JSON-serializable dict describing the receipt.
    """
    receipt = anchor_on_blockchain(content_sha256, anchor=anchor)
    return {
        "backend": receipt.backend,
        "network": receipt.network,
        "record_hash": receipt.record_hash,
        "tx_hash": (receipt.ref or {}).get("tx_hash"),
        "block_hash": receipt.block_hash,
        "block_number": receipt.block_index,
        "merkle_root": receipt.merkle_root,
        "idempotent_hit": receipt.idempotent_hit,
        "ref": dict(receipt.ref or {}),
    }


def register_evidence_on_blockchain(
    evidence_id: str,
    content_sha256: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> tuple[str, int]:
    """Register an evidence ID and content hash on-chain (EVM registry mode)."""
    from backend.blockchain.contract import (
        evidence_id_to_bytes32,
        get_contract,
        get_web3,
        hash_to_bytes32,
    )

    private_key = None
    from backend.blockchain.config import get_private_key

    private_key = get_private_key()
    if not private_key:
        raise ValueError("Wallet private key not configured (SEPOLIA_WALLET_PRIVATE_KEY)")

    w3 = get_web3(rpc_url=rpc_url)
    account = w3.eth.account.from_key(private_key)
    contract = get_contract(w3, address=address)

    evidence_id_bytes = evidence_id_to_bytes32(evidence_id)
    content_hash_bytes = hash_to_bytes32(content_sha256)

    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.registerEvidence(evidence_id_bytes, content_hash_bytes).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "gas": 120000,
            "gasPrice": w3.eth.gas_price * 12 // 10,
        }
    )

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.get("status") != 1:
        raise ValueError(f"Blockchain transaction reverted/failed: {tx_hash.hex()}")
    return tx_hash.hex(), receipt["blockNumber"]


def revoke_evidence_on_blockchain(
    evidence_id: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> tuple[str, int]:
    """Revoke an evidence attestation and return its transaction details."""
    from backend.blockchain.config import get_private_key
    from backend.blockchain.contract import (
        evidence_id_to_bytes32,
        get_contract,
        get_web3,
    )

    private_key = get_private_key()
    if not private_key:
        raise ValueError("Wallet private key not configured (SEPOLIA_WALLET_PRIVATE_KEY)")

    w3 = get_web3(rpc_url=rpc_url)
    account = w3.eth.account.from_key(private_key)
    contract = get_contract(w3, address=address)

    evidence_id_bytes = evidence_id_to_bytes32(evidence_id)

    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.revokeEvidence(evidence_id_bytes).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "gas": 60000,
            "gasPrice": w3.eth.gas_price * 12 // 10,
        }
    )

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.get("status") != 1:
        raise ValueError(f"Blockchain transaction reverted/failed: {tx_hash.hex()}")
    return tx_hash.hex(), receipt["blockNumber"]


def transaction_status(tx_hash: str, rpc_url: str | None = None) -> dict:
    """Fetch status for an existing transaction."""
    from backend.blockchain.contract import get_web3

    w3 = get_web3(rpc_url=rpc_url)
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return {
        "tx_hash": tx_hash,
        "status": bool(receipt.get("status")),
        "block_number": receipt.get("blockNumber"),
    }


__all__ = [
    "anchor_on_blockchain",
    "register_on_blockchain",
    "register_evidence_on_blockchain",
    "revoke_evidence_on_blockchain",
    "transaction_status",
    "BackendUnavailableError",
]