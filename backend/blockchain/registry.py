"""Register content hashes on the ContentRegistry contract."""

from __future__ import annotations

from web3 import Web3

from backend.blockchain.contract import (
    evidence_id_to_bytes32,
    get_contract,
    get_private_key,
    get_web3,
    hash_to_bytes32,
)


def register_on_blockchain(
    content_sha256: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> tuple[str, int]:
    """Register a content hash and return (transaction_hash, block_number).

    Requires ``SEPOLIA_WALLET_PRIVATE_KEY`` (or an explicit private key) and a
    funded account on the target network.
    """
    private_key = get_private_key()
    if not private_key:
        raise ValueError("Wallet private key not configured (SEPOLIA_WALLET_PRIVATE_KEY)")

    w3 = get_web3(rpc_url=rpc_url)
    account = w3.eth.account.from_key(private_key)
    contract = get_contract(w3, address=address)

    content_hash_bytes = hash_to_bytes32(content_sha256)

    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.register(content_hash_bytes).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "gas": 80000,
            "gasPrice": w3.eth.gas_price * 12 // 10,
        }
    )

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.get("status") != 1:
        raise ValueError(f"Blockchain transaction reverted/failed: {tx_hash.hex()}")
    return tx_hash.hex(), receipt["blockNumber"]


def register_evidence_on_blockchain(
    evidence_id: str,
    content_sha256: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> tuple[str, int]:
    """Register an evidence ID and content hash on-chain."""
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
    w3 = get_web3(rpc_url=rpc_url)
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return {
        "tx_hash": tx_hash,
        "status": bool(receipt.get("status")),
        "block_number": receipt.get("blockNumber"),
    }
