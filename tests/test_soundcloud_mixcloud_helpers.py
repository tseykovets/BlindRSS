"""Offline tests for SoundCloud/Mixcloud URL classifiers and site registration."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import discovery as d


def test_soundcloud_url_and_kind():
    assert d.is_soundcloud_url("https://soundcloud.com/lofi_girl") is True
    assert d.is_soundcloud_url("https://m.soundcloud.com/x") is True
    assert d.is_soundcloud_url("https://example.com/x") is False

    assert d.soundcloud_listing_kind("https://soundcloud.com/lofi_girl") == "user"
    assert d.soundcloud_listing_kind("https://soundcloud.com/lofi_girl/sets/chill") == "playlist"
    assert d.soundcloud_listing_kind("https://soundcloud.com/lofi_girl/some-track") == "track"
    # Reserved sections are not user profiles.
    assert d.soundcloud_listing_kind("https://soundcloud.com/discover") == ""
    assert d.soundcloud_listing_kind("https://soundcloud.com/you") == ""


def test_mixcloud_url_and_kind():
    assert d.is_mixcloud_url("https://www.mixcloud.com/8ballradio/") is True
    assert d.is_mixcloud_url("https://example.com/") is False

    assert d.mixcloud_listing_kind("https://www.mixcloud.com/8ballradio/") == "user"
    assert d.mixcloud_listing_kind("https://www.mixcloud.com/8ballradio/playlists/mix/") == "playlist"
    assert d.mixcloud_listing_kind("https://www.mixcloud.com/8ballradio/some-show/") == "cloudcast"


def test_mixcloud_registered_as_search_site_and_dispatches(monkeypatch):
    sites = d.get_ytdlp_searchable_sites(include_adult=False)
    ids = {s["id"] for s in sites}
    assert "mixcloud" in ids
    mix = next(s for s in sites if s["id"] == "mixcloud")
    assert mix.get("search_provider") == "mixcloud"

    called = {}

    def _fake(term, limit=30, timeout=15):
        called["term"] = term
        return [{"title": "x", "url": "https://www.mixcloud.com/u/c/", "site": "Mixcloud",
                 "site_id": "mixcloud", "kind": "media", "play_count": None,
                 "_title_is_fallback": False, "native_subscribe_url": "", "source_subscribe_url": ""}]

    monkeypatch.setattr(d, "search_mixcloud_media", _fake)
    out = d.search_ytdlp_site("cats", mix, limit=5, timeout=10)
    assert called.get("term") == "cats"
    assert len(out) == 1 and out[0]["site_id"] == "mixcloud"


def test_soundcloud_client_id_cached(monkeypatch):
    calls = {"n": 0}

    def _fake_fetch(timeout=15.0):
        calls["n"] += 1
        return "CID_ABC"

    monkeypatch.setattr(d, "_fetch_soundcloud_client_id", _fake_fetch)
    monkeypatch.setattr(d, "_SOUNDCLOUD_CLIENT_ID", None)
    a = d._get_soundcloud_client_id()
    b = d._get_soundcloud_client_id()
    assert a == b == "CID_ABC"
    assert calls["n"] == 1  # cached after first fetch
