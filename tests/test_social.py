"""Tests for keyless social search fallback."""

import pytest

from backend.search import social
from backend.search.social import (
    _is_social,
    _search_bluesky,
    _search_mastodon,
    _search_reddit,
    social_search,
)


def test_is_social():
    assert _is_social("https://www.reddit.com/r/x/comments/1/")
    assert _is_social("https://bsky.app/profile/user/post/abc")
    assert _is_social("https://mastodon.social/@user/123")
    assert not _is_social("https://en.wikipedia.org/wiki/Foo")
    assert not _is_social("https://example.com/page")


def test_social_search_requires_hint():
    resp = social_search("")
    assert not resp.has_results
    assert "hint" in (resp.error or "").lower()


class _FakeGet:
    """Replacement for requests.get that returns canned JSON per URL."""

    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for key, payload in self._responses:
            if key in url:
                return _FakeResp(payload)
        return _FakeResp({})


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_search_mastodon_account_timeline(monkeypatch):
    payloads = [
        (
            "/api/v1/accounts/lookup",
            {"id": "123", "acct": "user", "avatar": "https://x/a.jpg", "display_name": "User", "url": "https://mastodon.social/@user"},
        ),
        (
            "/api/v1/accounts/123/statuses",
            [
                {
                    "id": "1",
                    "url": "https://mastodon.social/@user/1",
                    "content": "<p>hello world</p>",
                    "media_attachments": [{"type": "image", "url": "https://x/media.jpg"}],
                }
            ],
        ),
    ]
    monkeypatch.setattr(social.requests, "get", _FakeGet(payloads))
    results, stats = _search_mastodon("user", limit=10)
    assert any(r.url == "https://mastodon.social/@user/1" for r in results)
    assert any(r.image_url == "https://x/media.jpg" for r in results)


def test_search_bluesky_actors_and_posts(monkeypatch):
    payloads = [
        (
            "/app.bsky.actor.searchActors",
            {"actors": [{"handle": "user.bsky.social", "avatar": "https://x/av.jpg", "displayName": "User"}]},
        ),
        (
            "/app.bsky.feed.getAuthorFeed",
            {
                "feed": [
                    {
                        "post": {
                            "uri": "at://did:plc:x/app.bsky.feed.post/abc",
                            "record": {"text": "a post"},
                            "author": {"handle": "user.bsky.social"},
                            "embed": {"images": [{"fullsize": "https://x/img.jpg"}]},
                        }
                    }
                ]
            },
        ),
    ]
    monkeypatch.setattr(social.requests, "get", _FakeGet(payloads))
    results, stats = _search_bluesky("user", limit=10)
    assert any("post/abc" in r.url for r in results)
    assert any(r.url == "https://bsky.app/profile/user.bsky.social/post/abc" for r in results)


def test_search_reddit(monkeypatch):
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "A post",
                        "permalink": "/r/sub/comments/abc/title/",
                        "post_hint": "image",
                        "url_overridden_by_dest": "https://i.redd.it/x.jpg",
                    }
                }
            ]
        }
    }
    monkeypatch.setattr(
        social.requests, "get", _FakeGet([("search.json", payload)])
    )
    results, _stats = _search_reddit("hint", limit=10)
    assert any(r.url == "https://www.reddit.com/r/sub/comments/abc/title/" for r in results)
    assert results[0].image_url == "https://i.redd.it/x.jpg"


def test_social_search_merges_and_deduplicates(monkeypatch):
    # Same post URL appears from two providers; must be deduped.
    payloads = [
        (
            "/app.bsky.actor.searchActors",
            {"actors": [{"handle": "u", "avatar": ""}]},
        ),
        (
            "/app.bsky.feed.getAuthorFeed",
            {"feed": []},
        ),
        (
            "/app.bsky.feed.searchPosts",
            {"posts": []},
        ),
        (
            "/api/v1/accounts/lookup",
            {"id": "1", "acct": "u", "avatar": ""},
        ),
        (
            "/api/v1/accounts/1/statuses",
            [],
        ),
        (
            "/api/v1/timelines/public",
            [
                {
                    "url": "https://mastodon.social/@u/1",
                    "content": "x",
                    "media_attachments": [{"type": "image", "url": "https://x/m.jpg"}],
                }
            ],
        ),
    ]
    monkeypatch.setattr(social.requests, "get", _FakeGet(payloads))
    resp = social_search("hint", max_results=10)
    assert resp.has_results
    assert resp.provider == "keyless_social"
    assert resp.providers_used


def test_social_search_empty_on_no_results(monkeypatch):
    monkeypatch.setattr(social.requests, "get", _FakeGet([]))
    resp = social_search("nonexistent")
    assert not resp.has_results
    assert resp.error
