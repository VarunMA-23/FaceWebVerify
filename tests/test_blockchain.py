"""Tests for the blockchain registry (Modules 7 + 8)."""

import hashlib

import pytest

from backend.blockchain.contract import CONTENT_REGISTRY_ABI, hash_to_bytes32
from backend.blockchain.registry import register_on_blockchain
from backend.blockchain.verifier import verify_on_blockchain


class MockRegistry:
    """In-memory stand-in for the ContentRegistry smart contract."""

    def __init__(self) -> None:
        self._registered: set[bytes] = set()

    def register(self, content_hash: bytes) -> None:
        self._registered.add(content_hash)

    def verify(self, content_hash: bytes) -> bool:
        return content_hash in self._registered


@pytest.fixture
def content_hash() -> str:
    return hashlib.sha256(b"canonical content record").hexdigest()


def test_hash_to_bytes32_conversion(content_hash):
    b = hash_to_bytes32(content_hash)
    assert len(b) == 32
    assert b.hex() == content_hash


def test_hash_to_bytes32_rejects_bad_length():
    with pytest.raises(ValueError):
        hash_to_bytes32("abcd")


def test_abi_contains_register_and_verify():
    names = {f["name"] for f in CONTENT_REGISTRY_ABI if f.get("type") == "function"}
    assert {"register", "verify"} <= names


def test_mock_register_then_verify(content_hash):
    """Simulated on-chain flow: register -> verify succeeds."""
    registry = MockRegistry()
    content_hash_bytes = hash_to_bytes32(content_hash)
    registry.register(content_hash_bytes)
    assert registry.verify(content_hash_bytes) is True


def test_mock_unregistered_hash_verify_fails():
    registry = MockRegistry()
    unregistered = hash_to_bytes32(hashlib.sha256(b"never seen").hexdigest())
    assert registry.verify(unregistered) is False


def test_tampering_demo():
    """Tamper with content -> new hash -> verify fails on the original chain."""
    registry = MockRegistry()
    original = hashlib.sha256(b"original post content").hexdigest()
    tampered = hashlib.sha256(b"tampered post content").hexdigest()

    registry.register(hash_to_bytes32(original))
    assert registry.verify(hash_to_bytes32(original)) is True
    assert registry.verify(hash_to_bytes32(tampered)) is False


def test_register_requires_private_key(content_hash):
    """Without a configured private key, register must raise a clear error."""
    with pytest.raises(ValueError, match="private key"):
        register_on_blockchain(content_hash)


@pytest.mark.skipif(
    not __import__("os").environ.get("SEPOLIA_WALLET_PRIVATE_KEY")
    or not __import__("os").environ.get("SEPOLIA_CONTRACT_ADDRESS"),
    reason="Sepolia wallet/contract not configured in .env",
)
def test_live_sepolia_register_and_verify(content_hash):
    """Full integration against Sepolia (funded wallet required)."""
    tx_hash, block_number = register_on_blockchain(content_hash)
    assert tx_hash.startswith("0x")
    assert isinstance(block_number, int) and block_number > 0
    assert verify_on_blockchain(content_hash) is True