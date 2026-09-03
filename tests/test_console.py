"""Tests for console output utilities."""

import sys

import pytest

from backend import console


@pytest.fixture(autouse=True)
def _force_tty(monkeypatch):
    """Pretend stdout is a TTY so colour codes are emitted and testable."""
    class _Fake:
        def isatty(self):
            return True

    monkeypatch.setattr(console.sys, "stdout", _Fake(), raising=False)
    monkeypatch.setattr(console, "_is_tty", True, raising=False)


def test_banner_wraps_title(capsys):
    console.banner("HELLO")
    out = capsys.readouterr().out
    assert "HELLO" in out
    assert "=" in out


def test_stage_prints_progress(capsys):
    console.stage(1, 5, "STEP")
    out = capsys.readouterr().out
    assert "[1/5]" in out
    assert "STEP" in out


def test_kv_aligns_values(capsys):
    console.kv("key", "value")
    out = capsys.readouterr().out
    assert "key" in out
    assert "value" in out


def test_ok_fail_warn(capsys):
    console.ok("done")
    console.fail("bad")
    console.warn("careful")
    out = capsys.readouterr().out
    assert "OK" in out
    assert "FAIL" in out
    assert "WARN" in out


def test_colour_wrappers():
    assert "text" in console.bold("text")
    assert "text" in console.dim("text")
    assert "text" in console.cyan("text")
    assert "text" in console.red("text")
    assert "text" in console.green("text")
    assert "text" in console.yellow("text")


def test_no_color_when_not_tty(monkeypatch):
    monkeypatch.setattr(console, "_is_tty", False, raising=False)
    assert console.bold("x") == "x"
    assert console.dim("x") == "x"
