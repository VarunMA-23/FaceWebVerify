"""Pipeline timeline tracking."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.evidence.models import TimelineEvent

PIPELINE_STEPS = [
    ("face", "Face Detection"),
    ("embedding", "Embedding Generated"),
    ("search", "Reverse Search Started"),
    ("discover", "Candidates Discovered"),
    ("verify", "Sources Verified"),
    ("match", "Face Matching"),
    ("score", "Evidence Scoring"),
    ("select", "Best Evidence Selected"),
    ("fingerprint", "Fingerprint Generated"),
    ("blockchain", "Blockchain Attestation"),
]


class TimelineTracker:
    """Records pipeline stage events with timestamps."""

    def __init__(self) -> None:
        self.events: list[TimelineEvent] = []
        for step, label in PIPELINE_STEPS:
            self.events.append(TimelineEvent(step=step, label=label, status="waiting"))

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _find(self, step: str) -> TimelineEvent | None:
        for ev in self.events:
            if ev.step == step:
                return ev
        return None

    def start(self, step: str, detail: str = "") -> None:
        ev = self._find(step)
        if ev:
            ev.status = "processing"
            ev.timestamp = self._now()
            ev.detail = detail

    def succeed(self, step: str, detail: str = "") -> None:
        ev = self._find(step)
        if ev:
            ev.status = "success"
            if not ev.timestamp:
                ev.timestamp = self._now()
            ev.detail = detail

    def warn(self, step: str, detail: str = "") -> None:
        ev = self._find(step)
        if ev:
            ev.status = "warning"
            if not ev.timestamp:
                ev.timestamp = self._now()
            ev.detail = detail

    def fail(self, step: str, detail: str = "") -> None:
        ev = self._find(step)
        if ev:
            ev.status = "failed"
            if not ev.timestamp:
                ev.timestamp = self._now()
            ev.detail = detail

    def to_list(self) -> list[dict]:
        return [
            {
                "step": e.step,
                "label": e.label,
                "status": e.status,
                "timestamp": e.timestamp,
                "detail": e.detail,
            }
            for e in self.events
        ]
