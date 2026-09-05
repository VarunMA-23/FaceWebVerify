"""Merkle tree tests: roots, inclusion proofs, tamper detection."""

import hashlib

import pytest

from backend.blockchain.merkle import (  # noqa: F401
    leaf_hash,
    merkle_proof,
    merkle_root,
    verify_merkle_proof,
)
from backend.blockchain.models import MerkleProofStep


def _leaves(hashes: list[str]):
    return [leaf_hash(bytes.fromhex(h)) for h in hashes]


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 16])
def test_proof_verifies_for_any_leaf(count):
    raw = [hashlib.sha256(f"record-{i}".encode()).hexdigest() for i in range(count)]
    leaves = _leaves(raw)
    root = merkle_root(leaves)
    for idx in range(count):
        proof = merkle_proof(leaves, idx)
        assert isinstance(proof[0], MerkleProofStep) if proof else True
        assert verify_merkle_proof(leaves[idx], proof, root) is True


def test_proof_rejects_wrong_root():
    raw = [hashlib.sha256(f"w-{i}".encode()).hexdigest() for i in range(3)]
    leaves = _leaves(raw)
    proof = merkle_proof(leaves, 0)
    other_root = merkle_root(_leaves([hashlib.sha256(b"other").hexdigest()]))
    assert verify_merkle_proof(leaves[0], proof, other_root) is False


def test_proof_rejects_wrong_leaf():
    raw = [hashlib.sha256(f"m-{i}".encode()).hexdigest() for i in range(4)]
    leaves = _leaves(raw)
    root = merkle_root(leaves)
    wrong = leaf_hash(hashlib.sha256(b"not in the tree").digest())
    assert verify_merkle_proof(wrong, merkle_proof(leaves, 0), root) is False


def test_empty_root_is_defined_and_stable():
    assert merkle_root([]) == merkle_root([])


def test_single_leaf_root_is_the_leaf():
    one = leaf_hash(b"x")
    assert merkle_root([one]) == one


def test_node_order_matters():
    a, b = leaf_hash(b"a"), leaf_hash(b"b")
    assert merkle_root([a, b]) != merkle_root([b, a])


def test_odd_level_duplicates_last():
    a, b, c = leaf_hash(b"a"), leaf_hash(b"b"), leaf_hash(b"c")
    # treet(a,b,c) must be the same as a tree of (a,b,c,c)
    assert merkle_root([a, b, c]) == merkle_root([a, b, c, c])


def test_proof_out_of_range_raises():
    leaves = _leaves([hashlib.sha256(b"x").hexdigest()])
    with pytest.raises(IndexError):
        merkle_proof(leaves, 5)