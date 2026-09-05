"""EVM anchor helpers tested offline (no web3/network required)."""

import pytest

from backend.blockchain.evm import _IndexCache, decode_calldata, encode_calldata


def test_calldata_roundtrip():
    record = "ab" * 32
    data = encode_calldata(record)
    assert data[:4] == b"FCV1"
    assert len(data) == 36
    assert decode_calldata(data) == record


def test_decode_rejects_bad_input():
    assert decode_calldata(b"") is None
    assert decode_calldata(b"XYZV" + bytes(32)) is None
    assert decode_calldata(b"FCV1" + bytes(31)) is None


def test_index_cache_roundtrip(tmp_path):
    cache = _IndexCache(tmp_path / "sub" / "evm-1.index.json")
    entry = {"tx_hash": "0xabc", "block_number": 5}
    cache.put("ab" * 32, entry)
    assert cache.get("ab" * 32) == entry
    assert cache.get("cd" * 32) is None
    assert (tmp_path / "sub").is_dir()


def test_index_cache_handles_corrupt(tmp_path):
    path = tmp_path / "evm-1.index.json"
    path.write_text("{not json", encoding="utf-8")
    assert _IndexCache(path).load() == {}


def test_calldata_length_wrong_raises():
    with pytest.raises(ValueError):
        encode_calldata("abcd")