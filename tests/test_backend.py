"""Backend selection + helper tests (web3-free)."""

import os

import pytest

from backend.blockchain.backend import DisabledAnchor, resolve_backend
from backend.blockchain.errors import BackendUnavailableError
from backend.blockchain.utils import validate_record_hash
from backend.blockchain import config


def test_validate_record_hash_accepts_64_hex():
    digest = "ab" * 32
    assert validate_record_hash(digest) == digest


def test_validate_record_hash_rejects_wrong_shape():
    with pytest.raises(ValueError):
        validate_record_hash("abc")
    with pytest.raises(ValueError):
        validate_record_hash("z" * 64)


def test_disable_switch_returns_disabled(monkeypatch):
    monkeypatch.setenv("BLOCKCHAIN_ANCHOR", "local")
    monkeypatch.setenv("DO_BLOCKCHAIN", "false")
    assert isinstance(resolve_backend(), DisabledAnchor)
    monkeypatch.setenv("DO_BLOCKCHAIN", "0")
    assert isinstance(resolve_backend(), DisabledAnchor)


def test_resolve_local_default(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOCKCHAIN_ANCHOR", "local")
    monkeypatch.setenv("BLOCKCHAIN_CHAIN_DIR", str(tmp_path))
    backend = resolve_backend()
    assert backend.name == "local"


def test_resolve_none_explicit():
    assert isinstance(resolve_backend("none"), DisabledAnchor)


def test_resolve_evm_without_config_raises(monkeypatch):
    monkeypatch.delenv("SEPOLIA_WALLET_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("SEPOLIA_CONTRACT_ADDRESS", raising=False)
    monkeypatch.setenv("BLOCKCHAIN_ANCHOR", "evm")
    with pytest.raises(BackendUnavailableError):
        resolve_backend()


def test_unknown_mode_raises(monkeypatch):
    monkeypatch.setenv("BLOCKCHAIN_ANCHOR", "quantum")
    with pytest.raises(ValueError):
        resolve_backend()


def test_config_helpers(monkeypatch):
    monkeypatch.setenv("BLOCKCHAIN_DIFFICULTY", "6")
    assert config.get_difficulty() == 6
    monkeypatch.setenv("BLOCKCHAIN_DIFFICULTY", "not-a-number")
    assert config.get_difficulty() == 0
    assert config.get_anchor_mode() == "local" or config.get_anchor_mode() in (
        "local",
        "evm",
        "none",
    )