"""ABI and web3 connection for the ContentRegistry contract."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

CONTENT_REGISTRY_ABI: list[dict[str, Any]] = [
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
        "inputs": [{"internalType": "bytes32", "name": "contentHash", "type": "bytes32"}],
        "name": "register",
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
        "inputs": [{"internalType": "bytes32", "name": "contentHash", "type": "bytes32"}],
        "name": "verify",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def get_rpc_url() -> str:
    return os.environ.get(
        "SEPOLIA_RPC_URL",
        "https://ethereum-sepolia-rpc.publicnode.com",
    ).strip()


def get_private_key() -> str:
    return os.environ.get("SEPOLIA_WALLET_PRIVATE_KEY", "").strip()


def get_contract_address() -> str:
    return os.environ.get("SEPOLIA_CONTRACT_ADDRESS", "").strip()


def get_web3(rpc_url: str | None = None) -> Web3:
    provider = Web3.HTTPProvider(rpc_url or get_rpc_url())
    w3 = Web3(provider)
    if not w3.is_connected():
        raise ConnectionError(f"Could not connect to RPC: {rpc_url or get_rpc_url()}")
    return w3


def get_contract(w3: Web3 | None = None, address: str | None = None):
    """Return a web3 contract instance for ContentRegistry."""
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