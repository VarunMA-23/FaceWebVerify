"""EVM public-testnet anchor backend (opt-in).

Two anchoring modes, chosen automatically:

* **registry** — if a contract address is configured (``SEPOLIA_CONTRACT_ADDRESS``),
  call ``anchorIfAbsent(bytes32)`` on the deployed ``ContentRegistry.sol``;
  re-verification reads the stored block number back via ``recordBlock`` and the
  ``registered`` mapping. Idempotent at the contract level.
* **calldata** — otherwise send a 0-value self-transaction whose input data is
  ``b"FCV1" || record_hash`` (36 bytes). Re-verification pulls the transaction by
  hash and re-parses the calldata. Works on any EVM chain with zero setup.

Idempotency: a local index file (``evm-<chainid>.index.json``) maps
``record_hash -> tx receipt``; a repeat anchor returns the cached receipt without
broadcasting — saving gas on re-runs.

web3 is imported lazily so the core pipeline never depends on it. The pure
helpers (``encode_calldata`` / ``decode_calldata`` / the index cache / fee
fields) are unit-tested offline; the broadcast path requires a funded testnet
key.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.blockchain.checks import Check
from backend.blockchain.config import (
    evm_configured,
    get_chain_dir,
    get_contract_address,
    get_evm_confirmations,
    get_evm_mode,
    get_private_key,
    get_rpc_url,
)
from backend.blockchain.errors import BackendUnavailableError
from backend.blockchain.models import AnchorReceipt
from backend.blockchain.utils import validate_record_hash

_MAGIC = b"FCV1"


def encode_calldata(record_hash: str) -> bytes:
    return _MAGIC + bytes.fromhex(validate_record_hash(record_hash))


def decode_calldata(data: bytes) -> str | None:
    if len(data) != len(_MAGIC) + 32 or not data.startswith(_MAGIC):
        return None
    return data[len(_MAGIC):].hex()


class _IndexCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text("utf-8"))
        except json.JSONDecodeError:  # pragma: no cover - corrupt cache
            return {}

    def get(self, record_hash: str) -> dict[str, Any] | None:
        return self.load().get(record_hash)

    def put(self, record_hash: str, entry: dict[str, Any]) -> None:
        data = self.load()
        data[record_hash] = entry
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


class EVMAnchor:
    """Ethereum testnet anchor backend (Sepolia by default)."""

    name = "evm"

    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        private_key: str | None = None,
        registry_address: str | None = None,
        mode: str | None = None,
        confirmations: int | None = None,
        cache_dir: str | Path | None = None,
        tx_timeout_s: int = 180,
    ) -> None:
        rpc_url = rpc_url or get_rpc_url()
        private_key = private_key or get_private_key()
        if not rpc_url or not private_key:
            raise BackendUnavailableError(
                "EVM backend needs SEPOLIA_RPC_URL and SEPOLIA_WALLET_PRIVATE_KEY"
            )
        try:
            from web3 import Web3
        except ImportError as exc:
            raise BackendUnavailableError(
                "web3 is not installed; run: pip install -r requirements-evm.txt"
            ) from exc

        self._w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        if not self._w3.is_connected():
            raise BackendUnavailableError(f"cannot reach EVM RPC at {rpc_url}")
        self._acct = self._w3.eth.account.from_key(private_key)
        self._chain_id = int(self._w3.eth.chain_id)
        self._confirmations = int(confirmations or get_evm_confirmations())
        self._tx_timeout_s = tx_timeout_s
        self._registry_address = (
            self._w3.to_checksum_address(registry_address)
            if registry_address
            else (self._w3.to_checksum_address(get_contract_address()) if get_contract_address() else None)
        )
        mode = (mode or get_evm_mode()).lower()
        if mode not in ("auto", "calldata", "registry"):
            raise ValueError(f"Unknown EVM_MODE: {mode}")
        if mode == "registry" and not self._registry_address:
            raise BackendUnavailableError(
                "EVM_MODE=registry requires SEPOLIA_CONTRACT_ADDRESS"
            )
        if not self._registry_address:
            mode = "calldata"
        elif mode == "auto":
            mode = "registry"
        self._mode = mode
        self.network = f"evm:{self._chain_id}:{self._mode}"
        self._cache = _IndexCache(
            Path(cache_dir or get_chain_dir()) / f"evm-{self._chain_id}.index.json"
        )

    @classmethod
    def available(cls) -> bool:
        if not evm_configured():
            return False
        try:
            import web3  # noqa: F401

            return True
        except ImportError:
            return False

    # -- anchor ------------------------------------------------------
    def anchor(self, record_hash: str) -> AnchorReceipt:
        record_hash = validate_record_hash(record_hash)
        cached = self._cache.get(record_hash)
        if isinstance(cached, dict) and cached.get("chain_id") and cached.get("mode"):
            return self._receipt_from_entry(record_hash, cached, idempotent=True)
        # Corrupt/foreign cache entries are ignored and re-anchored cleanly.

        if self._mode == "registry":
            tx_hash = self._send_registry(record_hash)
        else:
            tx_hash = self._send_calldata(record_hash)

        rcpt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self._tx_timeout_s)
        if rcpt["status"] != 1:
            raise BackendUnavailableError(f"anchor tx reverted: {tx_hash.hex()}")

        entry = {
            "tx_hash": rcpt["transactionHash"].hex(),
            "block_number": int(rcpt["blockNumber"]),
            "chain_id": self._chain_id,
            "mode": self._mode,
            "contract": self._registry_address,
            "from": self._acct.address,
            "anchored_epoch": int(time.time()),
        }
        self._cache.put(record_hash, entry)
        return self._receipt_from_entry(record_hash, entry, idempotent=False)

    def _send_calldata(self, record_hash: str) -> Any:
        tx: dict[str, Any] = {
            "chainId": self._chain_id,
            "from": self._acct.address,
            "to": self._acct.address,
            "value": 0,
            "nonce": self._w3.eth.get_transaction_count(self._acct.address),
            "data": "0x" + encode_calldata(record_hash).hex(),
        }
        tx["gas"] = self._w3.eth.estimate_gas(tx)
        tx.update(self._fee_fields())
        signed = self._acct.sign_transaction(tx)
        return self._w3.eth.send_raw_transaction(signed.raw_transaction)

    def _send_registry(self, record_hash: str) -> Any:
        from backend.blockchain.contract import get_contract

        contract = get_contract(
            self._w3, address=self._registry_address
        )
        fn = contract.functions.anchorIfAbsent(bytes.fromhex(record_hash))
        tx = fn.build_transaction(
            {
                "chainId": self._chain_id,
                "from": self._acct.address,
                "nonce": self._w3.eth.get_transaction_count(self._acct.address),
                **self._fee_fields(),
            }
        )
        signed = self._acct.sign_transaction(tx)
        return self._w3.eth.send_raw_transaction(signed.raw_transaction)

    def _fee_fields(self) -> dict[str, Any]:
        try:
            base = self._w3.eth.get_block("latest")["baseFeePerGas"]
            tip = self._w3.eth.max_priority_fee
            return {"maxFeePerGas": base * 2 + tip, "maxPriorityFeePerGas": tip}
        except BackendUnavailableError:
            raise
        except Exception:  # pragma: no cover - pre-EIP-1559 chains
            return {"gasPrice": self._w3.eth.gas_price}

    # -- verify -----------------------------------------------------
    def verify(self, record_hash: str, receipt: AnchorReceipt) -> list[Check]:
        record_hash = validate_record_hash(record_hash)
        checks: list[Check] = []
        tx_hash = receipt.ref.get("tx_hash")
        if not tx_hash:
            checks.append(Check(name="evm.receipt", ok=False, detail="receipt has no tx_hash"))
            return checks

        try:
            tx = self._w3.eth.get_transaction(tx_hash)
            rcpt = self._w3.eth.get_transaction_receipt(tx_hash)
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(name="evm.tx_lookup", ok=False, detail=repr(exc), expected=tx_hash))
            return checks

        checks.append(Check(name="evm.tx_mined", ok=rcpt["status"] == 1, actual=str(rcpt["status"])))
        head = self._w3.eth.block_number
        confs = head - int(rcpt["blockNumber"]) + 1
        checks.append(
            Check(
                name="evm.confirmations",
                ok=confs >= self._confirmations,
                detail=f"{confs} confirmation(s)",
            )
        )

        mode = receipt.ref.get("mode", self._mode)
        if mode == "calldata":
            parsed = decode_calldata(bytes(tx["input"]))
            checks.append(
                Check(
                    name="evm.calldata_matches_record",
                    ok=parsed == record_hash,
                    expected=record_hash,
                    actual=str(parsed),
                )
            )
        else:
            contract_address = receipt.ref.get("contract") or self._registry_address
            from backend.blockchain.contract import get_contract

            if contract_address:
                contract_address = self._w3.to_checksum_address(contract_address)
            contract = get_contract(self._w3, address=contract_address)
            try:
                stored_block = int(
                    contract.functions.recordBlock(bytes.fromhex(record_hash)).call()
                )
            except Exception as exc:  # noqa: BLE001 - unknown record -> revert
                checks.append(
                    Check(
                        name="evm.registry_has_record",
                        ok=False,
                        detail=repr(exc),
                        actual=str(rcpt["blockNumber"]),
                    )
                )
                return checks
            checks.append(
                Check(
                    name="evm.registry_has_record",
                    ok=stored_block > 0,
                    detail="hash is registered on-chain",
                    actual=str(stored_block),
                )
            )
        return checks

    def _receipt_from_entry(
        self, record_hash: str, entry: dict[str, Any], *, idempotent: bool
    ) -> AnchorReceipt:
        return AnchorReceipt(
            backend=self.name,
            network=f"evm:{entry['chain_id']}:{entry['mode']}",
            record_hash=record_hash,
            idempotent_hit=idempotent,
            ref=dict(entry),
            block_index=entry.get("block_number"),
        )