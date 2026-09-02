"""Temporary public image hosting for URL-based search providers.

Reverse image search providers such as OpenWeb Ninja require a publicly
reachable image URL. This module publishes local image files to free
no-auth anonymous hosts, trying each in order until one succeeds.
"""

from __future__ import annotations

import requests

TIMEOUT = 30


def _host_0x0(image_path: str) -> str:
    with open(image_path, "rb") as fh:
        resp = requests.post(
            "https://0x0.st",
            files={"file": fh},
            timeout=TIMEOUT,
        )
    resp.raise_for_status()
    url = resp.text.strip()
    return url if url.startswith("http://") or url.startswith("https://") else ""


def _host_tmpfiles(image_path: str) -> str:
    import re

    with open(image_path, "rb") as fh:
        resp = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": fh},
            timeout=TIMEOUT,
        )
    resp.raise_for_status()
    page_url = resp.json().get("data", {}).get("url", "")
    if not page_url:
        return ""
    if not page_url.startswith(("http://", "https://")):
        page_url = "https://" + page_url
    # The page serves a direct-download URL under /dl/<numeric>/<id>/<file>.
    # That numeric form is the raw bytes URL; the short form is an HTML page.
    page = requests.get(page_url, timeout=TIMEOUT)
    page.raise_for_status()
    match = re.search(r"(https://tmpfiles\.org/dl/[^\"'\s<>]+)", page.text)
    return match.group(1) if match else page_url


def _host_pomf(image_path: str) -> str:
    with open(image_path, "rb") as fh:
        resp = requests.post(
            "https://pomf2.lain.la/upload.php",
            files={"files[]": fh},
            timeout=TIMEOUT,
        )
    resp.raise_for_status()
    data = resp.json()
    if data.get("success") and data.get("files"):
        return data["files"][0].get("url", "")
    return ""


HOSTS = [
    _host_0x0,
    _host_tmpfiles,
    _host_pomf,
]


def host_image(image_path: str) -> str:
    """Publish a local image to a public URL.

    Tries each host in order; returns the first public URL obtained, or an
    empty string if every host fails.
    """
    for host in HOSTS:
        try:
            url = host(image_path)
        except (requests.RequestException, ValueError, KeyError, IndexError):
            continue
        if url:
            return url
    return ""