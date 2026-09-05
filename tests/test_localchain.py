"""Local Merkle ledger tests: genesis, anchoring, idempotency, tamper checks."""

import hashlib
import json

import pytest

from backend.blockchain.errors import ChainIntegrityError
from backend.blockchain.localchain import LocalChain, compute_block_hash


@pytest.fixture
def chain(tmp_path):
    return LocalChain(tmp_path / "chain", difficulty_bits=0)


def _hash(n: str) -> str:
    return hashlib.sha256(n.encode()).hexdigest()


def test_genesis_is_reproducible(tmp_path):
    a = LocalChain(tmp_path / "a", clock=lambda: 0.0)
    b = LocalChain(tmp_path / "b", clock=lambda: 0.0)
    ah = a.blocks()[0]["hash"]
    bh = b.blocks()[0]["hash"]
    assert ah == bh
    assert a.blocks()[0]["prev_hash"] == "0" * 64
    assert a.blocks()[0]["index"] == 0


def test_anchor_appends_one_record_block(chain):
    head_before = chain.head()["index"]
    rcpt = chain.anchor(_hash("r1"))
    assert rcpt.block_index == head_before + 1
    assert rcpt.merkle_root
    leaf = chain.blocks()[-1]
    assert leaf["records"] == [_hash("r1")]


def test_anchor_is_idempotent_and_returns_same_proof(chain):
    h = _hash("r1")
    first = chain.anchor(h)
    second = chain.anchor(h)
    assert first.idempotent_hit is False
    assert second.idempotent_hit is True
    assert second.block_index == first.block_index
    assert [s.sibling for s in second.merkle_proof] == [s.sibling for s in first.merkle_proof]


def test_find_record(chain):
    h = _hash("r1")
    chain.anchor(h)
    block, idx = chain.find_record(h)
    assert block["records"][idx] == h
    assert chain.find_record(_hash("nope")) is None


def test_verify_chain_rejects_tampered_records(chain):
    h = _hash("r1")
    chain.anchor(h)
    ledger = chain.path
    lines = ledger.read_text(encoding="utf-8").splitlines()
    bad = json.loads(lines[-1])
    bad["records"] = [_hash("tampered")]
    lines[-1] = json.dumps(bad, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ChainIntegrityError):
        chain.verify_chain()


def test_verify_chain_rejects_broken_link(chain):
    chain.anchor(_hash("r1"))
    ledger = chain.path
    lines = ledger.read_text(encoding="utf-8").splitlines()
    bad = json.loads(lines[-1])
    bad["prev_hash"] = "0" * 64
    lines[-1] = json.dumps(bad, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ChainIntegrityError):
        chain.verify_chain()


def test_pow_difficulty_enforced(tmp_path):
    pow_chain = LocalChain(tmp_path / "pow", difficulty_bits=4)
    pow_chain.anchor(_hash("r1"))
    assert pow_chain.verify_chain() is None  # passes


def test_multiple_records_in_sequence(chain):
    for i in range(5):
        chain.anchor(_hash(f"r{i}"))
    chain.verify_chain()
    assert len(chain.blocks()) == 6  # genesis + 5


def test_block_hash_deterministic():
    block = {
        "index": 1,
        "timestamp": "2020-01-01T00:00:00Z",
        "prev_hash": "0" * 64,
        "merkle_root": "ab" * 32,
        "difficulty": 0,
        "records": [_hash("r1")],
        "nonce": 0,
    }
    assert compute_block_hash(block) == compute_block_hash(dict(block))