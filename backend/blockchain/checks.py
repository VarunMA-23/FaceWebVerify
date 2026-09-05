"""Per-check PASS/FAIL result used by independent re-verification."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Check:
    """A single named verification check."""

    name: str
    ok: bool
    detail: str = ""
    expected: str | None = None
    actual: str | None = None


def checks_to_dicts(checks: list[Check]) -> list[dict]:
    from dataclasses import asdict

    return [asdict(c) for c in checks]


def dicts_to_checks(items: list | None) -> list[Check]:
    if not items:
        return []
    out: list[Check] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            Check(
                name=str(item.get("name", "")),
                ok=bool(item.get("ok", False)),
                detail=str(item.get("detail", "") or ""),
                expected=item.get("expected"),
                actual=item.get("actual"),
            )
        )
    return out