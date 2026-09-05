"""Shared blockchain-layer errors."""

from __future__ import annotations


class BackendUnavailableError(Exception):
    """Raised when a requested anchor backend cannot be used (unconfigured,
    missing optional dependency, unreachable network, etc.)."""


class ChainIntegrityError(Exception):
    """Raised when a local Merkle chain fails structural verification.

    ``detail`` pinpoints the first offending block/link.
    """

    def __init__(self, message: str, *, detail: object = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return self.message + (f" ({self.detail})" if self.detail is not None else "")