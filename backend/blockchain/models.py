"""Data models for the blockchain/anchoring layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MerkleProofStep:
    """One sibling step in a Merkle inclusion proof.

    ``position`` is the sibling's position relative to the current digest:
    ``"left"`` means the sibling precedes the accumulator, ``"right"`` follows it.
    """

    sibling: str
    position: str  # "left" | "right"


@dataclass
class AnchorReceipt:
    """Proof of anchoring a record hash on a backend.

    Uniform across backends so the pipeline/API can treat ``local`` and ``evm``
    identically. ``ref`` holds backend-specific, JSON-serializable detail
    (e.g. tx_hash/contract/mode for evm; genesis/prev hash for local).
    """

    backend: str
    network: str
    record_hash: str
    idempotent_hit: bool = False
    ref: dict = field(default_factory=dict)
    block_index: int | None = None
    block_hash: str = ""
    merkle_root: str = ""
    leaf_index: int | None = None
    merkle_proof: list[MerkleProofStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "AnchorReceipt | None":
        if not data:
            return None
        merkleraw = data.get("merkle_proof") or []
        proof = [
            MerkleProofStep(
                sibling=str(s.get("sibling", "")),
                position=str(s.get("position", "right")),
            )
            for s in merkleraw
            if isinstance(s, dict)
        ]
        return cls(
            backend=str(data.get("backend", "")),
            network=str(data.get("network", "")),
            record_hash=str(data.get("record_hash", "")),
            idempotent_hit=bool(data.get("idempotent_hit")),
            ref=dict(data.get("ref") or {}),
            block_index=data.get("block_index"),
            block_hash=str(data.get("block_hash", "")),
            merkle_root=str(data.get("merkle_root", "")),
            leaf_index=data.get("leaf_index"),
            merkle_proof=proof,
        )