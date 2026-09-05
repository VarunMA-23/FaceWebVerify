"""ABI and web3 connection for the ContentRegistry contract.

web3 is an OPTIONAL dependency: it is imported lazily, only on call paths that
actually talk to an EVM chain (never in the web3-free core path). All pure
helpers (hash conversion, validation) work without web3 installed.
"""

from __future__ import annotations

from typing import Any

from backend.blockchain.config import (
    get_contract_address,
    get_private_key,
    get_rpc_url,
)

CONTENT_REGISTRY_ABI: list[dict[str, Any]] = [
    # --- events ---
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "contentHash", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "registrar", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "name": "ContentRegistered",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "recordHash", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "submitter", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "name": "Anchored",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "evidenceId", "type": "bytes32"},
            {"indexed": True, "internalType": "bytes32", "name": "contentHash", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "registrar", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "name": "EvidenceRegistered",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "evidenceId", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "revoker", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "name": "EvidenceRevoked",
        "type": "event",
    },
    # --- functions ---
    {
        "inputs": [{"internalType": "bytes32", "name": "recordHash", "type": "bytes32"}],
        "name": "anchor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "recordHash", "type": "bytes32"}],
        "name": "anchorIfAbsent",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "recordHash", "type": "bytes32"}],
        "name": "isAnchored",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "recordHash", "type": "bytes32"}],
        "name": "recordBlock",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "recordHash", "type": "bytes32"}],
        "name": "recordTimestamp",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "contentHash", "type": "bytes32"}],
        "name": "register",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "evidenceId", "type": "bytes32"},
            {"internalType": "bytes32", "name": "contentHash", "type": "bytes32"},
        ],
        "name": "registerEvidence",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "evidenceId", "type": "bytes32"}],
        "name": "revokeEvidence",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "registered",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "registeredAt",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "registeredBlock",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "evidenceContentHash",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "evidenceId", "type": "bytes32"}],
        "name": "getEvidence",
        "outputs": [
            {"internalType": "bytes32", "name": "contentHash", "type": "bytes32"},
            {"internalType": "address", "name": "issuer", "type": "address"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
            {"internalType": "uint8", "name": "status", "type": "uint8"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "contentHash", "type": "bytes32"}],
        "name": "verify",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def get_web3(rpc_url: str | None = None):
    """Return a connected Web3 instance (lazy web3 import)."""
    from backend.blockchain.errors import BackendUnavailableError

    try:
        from web3 import Web3
    except ImportError as exc:
        raise BackendUnavailableError(
            "web3 is not installed; run: pip install -r requirements-evm.txt"
        ) from exc

    url = rpc_url or get_rpc_url()
    provider = Web3.HTTPProvider(url)
    w3 = Web3(provider)
    if not w3.is_connected():
        raise ConnectionError(f"Could not connect to RPC: {url}")
    return w3


def get_contract(w3=None, address: str | None = None):
    """Return a web3 contract instance for ContentRegistry."""
    from web3 import Web3

    addr = address or get_contract_address()
    if not addr:
        raise ValueError("Contract address not configured (SEPOLIA_CONTRACT_ADDRESS)")
    w3 = w3 or get_web3()
    return w3.eth.contract(address=Web3.to_checksum_address(addr), abi=CONTENT_REGISTRY_ABI)


def hash_to_bytes32(content_sha256: str) -> bytes:
    """Convert a 64-char SHA-256 hex digest to a 32-byte value."""
    raw = bytes.fromhex(content_sha256)
    if len(raw) != 32:
        raise ValueError(f"Expected 32-byte (64 hex) SHA-256 digest, got {len(raw) * 2} hex chars")
    return raw


def evidence_id_to_bytes32(evidence_id: str) -> bytes:
    """Convert an application evidence ID to an Ethereum bytes32 value."""
    if not isinstance(evidence_id, str) or not evidence_id:
        raise ValueError("Evidence ID must be a non-empty string")
    try:
        from web3 import Web3
    except ImportError as exc:
        from backend.blockchain.errors import BackendUnavailableError

        raise BackendUnavailableError(
            "web3 is not installed; run: pip install -r requirements-evm.txt"
        ) from exc
    return bytes(Web3.keccak(text=evidence_id))


__all__ = [
    "CONTENT_REGISTRY_ABI",
    "get_web3",
    "get_contract",
    "hash_to_bytes32",
    "evidence_id_to_bytes32",
    "get_rpc_url",
    "get_private_key",
    "get_contract_address",
]