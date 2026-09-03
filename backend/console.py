"""Styled console output utilities for CLI pipeline runs.

Provides stage banners, key-value formatting, and coloured status indicators
that make the pipeline output scannable during live demos and debugging.
All colour is automatically disabled when stdout is not a TTY.
"""

from __future__ import annotations

import os
import sys

_is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

# Enable ANSI escape codes on Windows terminals (10+)
if os.name == "nt" and _is_tty:
    os.system("")  # noqa: S605


def _code(name: str) -> str:
    if not _is_tty:
        return ""
    return {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "cyan": "\033[36m",
    }.get(name, "")


def dim(text: str) -> str:
    return f"{_code('dim')}{text}{_code('reset')}"


def bold(text: str) -> str:
    return f"{_code('bold')}{text}{_code('reset')}"


def cyan(text: str) -> str:
    return f"{_code('cyan')}{text}{_code('reset')}"


def red(text: str) -> str:
    return f"{_code('red')}{text}{_code('reset')}"


def green(text: str) -> str:
    return f"{_code('green')}{text}{_code('reset')}"


def yellow(text: str) -> str:
    return f"{_code('yellow')}{text}{_code('reset')}"


_KV_WIDTH = 22  # column width for keys


def banner(text: str) -> None:
    """Print a prominent banner line."""
    bar = "=" * (len(text) + 4)
    print(f"\n  {bold(bar)}")
    print(f"  {bold(text)}")
    print(f"  {bold(bar)}\n")


def stage(n: int, total: int, text: str) -> None:
    """Print a stage header like ``[1/5] STAGE NAME``."""
    prefix = bold(f"[{n}/{total}]")
    print(f"\n  {prefix} {bold(text)}")
    print(f"  {'-' * 50}")


def kv(key: str, value: str, indent: int = 4) -> None:
    """Print a left-aligned key-value pair."""
    pad = " " * indent
    print(f"{pad}{dim(key):<{_KV_WIDTH + 8}} {value}")


def ok(msg: str) -> None:
    """Print a success indicator."""
    print(f"  {green('OK')}  {msg}")


def fail(msg: str) -> None:
    """Print a failure indicator."""
    print(f"  {red('FAIL')}  {msg}")


def warn(msg: str) -> None:
    """Print a warning indicator."""
    print(f"  {yellow('WARN')}  {msg}")
