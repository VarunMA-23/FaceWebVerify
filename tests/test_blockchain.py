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
    """EVM evidence registration without a configured key must raise clearly."""
    from backend.blockchain.registry import register_evidence_on_blockchain

    with pytest.raises(ValueError, match="private key"):
        register_evidence_on_blockchain("ev-1", content_hash)


def test_register_on_null_backend_returns_dict(content_hash, monkeypatch, tmp_path):
    """The generic register surface resolves the backend and returns a dict."""
    from backend.blockchain.registry import register_on_blockchain

    monkeypatch.setenv("BLOCKCHAIN_ANCHOR", "local")
    monkeypatch.setenv("BLOCKCHAIN_CHAIN_DIR", str(tmp_path))
    receipt_dict = register_on_blockchain(content_hash)
    assert receipt_dict["backend"] == "local"
    assert receipt_dict["record_hash"] == content_hash
    assert receipt_dict["block_number"] > 0
    assert isinstance(receipt_dict["merkle_root"], str) and len(receipt_dict["merkle_root"]) == 64


def test_local_chain_and_verify(content_hash, monkeypatch, tmp_path):
    """Local Merkle ledger: anchor -> idempotent -> verify -> tamper detected."""
    from backend.blockchain.localchain import LocalChain
    from backend.blockchain.verifier import verify_on_blockchain, verify_record

    monkeypatch.setenv("BLOCKCHAIN_CHAIN_DIR", str(tmp_path))
    chain = LocalChain(tmp_path / "local", difficulty_bits=0)
    receipt = chain.anchor(content_hash)
    assert receipt.backend == "local"
    assert receipt.block_index == 1  # genesis + one record block

    repeat = chain.anchor(content_hash)
    assert repeat.idempotent_hit is True
    assert repeat.block_index == receipt.block_index

    assert verify_on_blockchain(content_hash, backend_name="local") is True
    assert all(c.ok for c in verify_record(content_hash, receipt))

    # Tampering with the ledger is detected by structural verification.
    import json

    ledger = chain.path
    lines = ledger.read_text(encoding="utf-8").splitlines()
    bad = json.loads(lines[-1])
    bad["records"] = [hashlib.sha256(b"tampered").hexdigest()]
    lines[-1] = json.dumps(bad, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert verify_on_blockchain(content_hash, backend_name="local") is False
    assert not all(c.ok for c in verify_record(content_hash, receipt))


@pytest.mark.skipif(
    not __import__("os").environ.get("SEPOLIA_WALLET_PRIVATE_KEY")
    or not __import__("os").environ.get("SEPOLIA_CONTRACT_ADDRESS"),
    reason="Sepolia wallet/contract not configured in .env",
)
def test_live_sepolia_register_and_verify(content_hash):
    """Full integration against Sepolia (funded wallet required)."""
    from backend.blockchain.registry import register_on_blockchain

    receipt_dict = register_on_blockchain(content_hash, anchor="evm")
    assert receipt_dict["backend"] == "evm"
    assert (receipt_dict["tx_hash"] or "").startswith("0x")
    assert isinstance(receipt_dict["block_number"], int) and receipt_dict["block_number"] > 0
    assert verify_on_blockchain(content_hash) is True