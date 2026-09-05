"""Verify content hashes against the active anchor backend.

Read-side verification dispatches on the backend that anchored the record
(stored in the ``blockchain_records.backend`` column during the run):
``local`` re-checks the Merkle ledger, ``evm`` calls the contract's ``registered``
mapping. Deep per-check verification lives in :func:`verify_record` and powers
the ``/reverify`` endpoint.
"""

from __future__ import annotations

from backend.blockchain import config
from backend.blockchain.checks import Check
from backend.blockchain.models import AnchorReceipt


def _local_chain():
    from backend.blockchain.localchain import LocalChain

    return LocalChain(
        config.get_chain_dir() / "local",
        difficulty_bits=config.get_difficulty(),
    )


def verify_on_blockchain(
    content_sha256: str,
    backend_name: str = "auto",
    rpc_url: str | None = None,
    address: str | None = None,
) -> bool:
    """Return True if the content hash is registered on the given backend.

    ``backend_name`` defaults to ``auto`` (resolve from env). Callers that know
    which backend anchored a record should pass it explicitly (e.g. the stored
    ``backend`` column) so verification does not depend on current settings.
    """
    backend_name = (backend_name or "auto").lower()
    if backend_name == "auto":
        from backend.blockchain.backend import resolve_backend

        backend_name = resolve_backend().name
    if backend_name == "none":
        return False
    if backend_name == "local":
        try:
            return _local_chain().find_record(content_sha256) is not None
        except Exception:  # noqa: BLE001 - chain unavailable -> not on chain
            return False
    if backend_name in ("evm", ""):
        try:
            return _evm_registered(content_sha256, rpc_url=rpc_url, address=address)
        except Exception:  # noqa: BLE001 - offline/unconfigured -> not verifiable
            return False
    return False


def _evm_registered(content_sha256: str, rpc_url: str | None = None, address: str | None = None) -> bool:
    from backend.blockchain.contract import get_contract, get_web3, hash_to_bytes32

    contract = get_contract(get_web3(rpc_url=rpc_url), address=address)
    return bool(contract.functions.verify(hash_to_bytes32(content_sha256)).call())


def is_registered(content_sha256: str, backend_name: str = "auto", **kwargs) -> bool:
    """Alias for :func:`verify_on_blockchain`."""
    return verify_on_blockchain(content_sha256, backend_name=backend_name, **kwargs)


def verify_record(content_sha256: str, receipt: AnchorReceipt | dict) -> list[Check]:
    """Re-run the active backend's per-check verification for a record.

    ``receipt`` may be an :class:`AnchorReceipt` or a dict (e.g. reconstructed
    from the database). Returns a list of named PASS/FAIL checks.
    """
    if isinstance(receipt, dict):
        receipt = AnchorReceipt.from_dict(receipt)
    if receipt is None or not receipt.backend:
        return [Check(name="verify.receipt", ok=False, detail="no receipt available")]
    backend_name = receipt.backend.lower()
    try:
        if backend_name == "local":
            from backend.blockchain.localchain import LocalChain

            chain_root = (receipt.ref or {}).get("chain_root") or config.get_chain_dir() / "local"
            return LocalChain(chain_root).verify(content_sha256, receipt)
        if backend_name == "evm":
            from backend.blockchain.evm import EVMAnchor

            return EVMAnchor().verify(content_sha256, receipt)
    except Exception as exc:  # noqa: BLE001
        return [
            Check(
                name=f"{backend_name}.verify",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            )
        ]
    return [
        Check(name=f"{backend_name}.unavailable", ok=False, detail="unknown backend")
    ]


def get_evidence_from_blockchain(
    evidence_id: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> dict:
    """Return the richer on-chain evidence attestation (EVM registry mode)."""
    from backend.blockchain.contract import (
        evidence_id_to_bytes32,
        get_contract,
        get_web3,
    )

    w3 = get_web3(rpc_url=rpc_url)
    contract = get_contract(w3, address=address)
    evidence_id_bytes = evidence_id_to_bytes32(evidence_id)
    content_hash, issuer, timestamp, status = contract.functions.getEvidence(
        evidence_id_bytes
    ).call()
    content_hash_bytes = bytes(content_hash)
    if content_hash_bytes == bytes(32):
        raise ValueError(f"Evidence is not registered: {evidence_id}")
    status_value = int(status)
    if status_value == 0:
        status_name = "active"
    elif status_value == 1:
        status_name = "revoked"
    else:
        raise ValueError(f"Unknown evidence status: {status_value}")
    return {
        "content_hash": "0x" + content_hash_bytes.hex(),
        "issuer": issuer,
        "timestamp": int(timestamp),
        "status": status_name,
    }


def verify_evidence_on_blockchain(
    evidence_id: str,
    content_sha256: str,
    rpc_url: str | None = None,
    address: str | None = None,
) -> bool:
    """Return whether an evidence ID maps to the expected content hash on-chain."""
    evidence = get_evidence_from_blockchain(evidence_id, rpc_url=rpc_url, address=address)
    from backend.blockchain.contract import hash_to_bytes32

    expected_hash = "0x" + hash_to_bytes32(content_sha256).hex()
    return evidence["status"] == "active" and evidence["content_hash"] == expected_hash