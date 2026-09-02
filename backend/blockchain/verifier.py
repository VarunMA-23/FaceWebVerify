"""Verify content hashes against the ContentRegistry contract."""

from __future__ import annotations

from backend.blockchain.contract import get_contract, get_web3, hash_to_bytes32


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