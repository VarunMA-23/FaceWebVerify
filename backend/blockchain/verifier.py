"""Verify content hashes against the ContentRegistry contract."""

from __future__ import annotations

from backend.blockchain.contract import (
    evidence_id_to_bytes32,
    get_contract,
    get_web3,
    hash_to_bytes32,
)


def verify_on_blockchain(
    content_sha256: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> bool:
    """Return True if the content hash is registered on-chain."""
    contract = get_contract(get_web3(rpc_url=rpc_url), address=address)
    content_hash_bytes = hash_to_bytes32(content_sha256)
    return bool(contract.functions.verify(content_hash_bytes).call())


def is_registered(content_sha256: str, rpc_url: str | None = None, address: str | None = None) -> bool:
    """Alias for ``verify_on_blockchain`` (reads the public mapping)."""
    return verify_on_blockchain(content_sha256, rpc_url=rpc_url, address=address)


def verify_evidence_on_blockchain(
    evidence_id: str,
    content_sha256: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> bool:
    """Return whether an evidence ID maps to the expected content hash on-chain."""
    evidence = get_evidence_from_blockchain(
        evidence_id,
        rpc_url=rpc_url,
        address=address,
    )
    expected_hash = "0x" + hash_to_bytes32(content_sha256).hex()
    return evidence["status"] == "active" and evidence["content_hash"] == expected_hash


def get_evidence_from_blockchain(
    evidence_id: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> dict:
    """Return the richer on-chain evidence attestation."""
    w3 = get_web3(rpc_url=rpc_url)
    contract = get_contract(w3, address=address)
    evidence_id_bytes = evidence_id_to_bytes32(evidence_id)
    content_hash, issuer, timestamp, status = contract.functions.getEvidence(
        evidence_id_bytes
    ).call()
    content_hash_bytes = bytes(content_hash)
    if content_hash_bytes == bytes(32):
        raise ValueError(f"Evidence is not registered: {evidence_id}")
    status_value = int(status)
    if status_value == 0:
        status_name = "active"
    elif status_value == 1:
        status_name = "revoked"
    else:
        raise ValueError(f"Unknown evidence status: {status_value}")
    return {
        "content_hash": "0x" + content_hash_bytes.hex(),
        "issuer": issuer,
        "timestamp": int(timestamp),
        "status": status_name,
    }