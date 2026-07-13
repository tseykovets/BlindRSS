import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gui.dialogs as dialogs


class _Host:
    _SOURCE_ALL = dialogs.FeedSearchDialog._SOURCE_ALL
    _SOURCE_ALL_PODCAST = dialogs.FeedSearchDialog._SOURCE_ALL_PODCAST
    _SOURCE_ALL_RSS = dialogs.FeedSearchDialog._SOURCE_ALL_RSS
    _PODCAST_SOURCE_KEYS = dialogs.FeedSearchDialog._PODCAST_SOURCE_KEYS
    _RSS_SOURCE_KEYS = dialogs.FeedSearchDialog._RSS_SOURCE_KEYS
    _build_search_targets = dialogs.FeedSearchDialog._build_search_targets
    _is_url_like_term = staticmethod(dialogs.FeedSearchDialog._is_url_like_term)

    def _search_itunes(self, term, queue):
        _ = (term, queue)

    def _search_gpodder(self, term, queue):
        _ = (term, queue)

    def _search_fyyd(self, term, queue):
        _ = (term, queue)

    def _search_podverse(self, term, queue):
        _ = (term, queue)

    def _search_feedly(self, term, queue):
        _ = (term, queue)

    def _search_feedspot(self, term, queue):
        _ = (term, queue)

    def _search_googlenews(self, term, queue):
        _ = (term, queue)

    def _search_bingnews(self, term, queue):
        _ = (term, queue)

    def _search_youtube_channels(self, term, queue):
        _ = (term, queue)

    def _search_soundcloud(self, term, queue):
        _ = (term, queue)

    def _search_mixcloud(self, term, queue):
        _ = (term, queue)

    def _search_newsblur(self, term, queue):
        _ = (term, queue)

    def _search_reddit(self, term, queue):
        _ = (term, queue)

    def _search_fediverse(self, term, queue):
        _ = (term, queue)

    def _search_feedsearch(self, term, queue):
        _ = (term, queue)

    def _search_blindrss(self, term, queue):
        _ = (term, queue)

    def _search_mastodon(self, term, queue):
        _ = (term, queue)

    def _search_bluesky(self, term, queue):
        _ = (term, queue)

    def _search_piefed(self, term, queue):
        _ = (term, queue)

    def _search_lemmy(self, term, queue):
        _ = (term, queue)


def _target_names(targets):
    return [name for name, _ in targets]


def test_feed_search_all_sources_excludes_url_only_targets_for_keyword():
    host = _Host()
    targets = host._build_search_targets("blue sky", host._SOURCE_ALL)

    assert _target_names(targets) == [
        "iTunes",
        "gPodder",
        "fyyd",
        "Podverse",
        "Feedly",
        "Feedspot",
        "Google News",
        "Bing News",
        "YouTube",
        "SoundCloud",
        "Mixcloud",
        "NewsBlur",
        "Reddit",
        "Fediverse",
    ]


def test_feed_search_all_sources_includes_url_only_targets_for_url_like_terms():
    host = _Host()
    targets = host._build_search_targets("example.com", host._SOURCE_ALL)

    assert _target_names(targets) == [
        "iTunes",
        "gPodder",
        "fyyd",
        "Podverse",
        "Feedly",
        "Feedspot",
        "Google News",
        "Bing News",
        "YouTube",
        "SoundCloud",
        "Mixcloud",
        "NewsBlur",
        "Reddit",
        "Fediverse",
        "Feedsearch",
        "BlindRSS",
    ]


def test_feed_search_all_podcast_sources_group():
    host = _Host()
    targets = host._build_search_targets("history", host._SOURCE_ALL_PODCAST)

    assert _target_names(targets) == ["iTunes", "gPodder", "fyyd", "Podverse", "SoundCloud", "Mixcloud"]


def test_feed_search_all_rss_sources_group_excludes_url_only_targets_for_keyword():
    host = _Host()
    targets = host._build_search_targets("tech news", host._SOURCE_ALL_RSS)

    assert _target_names(targets) == [
        "Feedly",
        "Feedspot",
        "Google News",
        "Bing News",
        "YouTube",
        "SoundCloud",
        "Mixcloud",
        "NewsBlur",
        "Reddit",
        "Fediverse",
    ]


def test_feed_search_all_rss_sources_group_includes_url_only_targets_for_url_like_terms():
    host = _Host()
    targets = host._build_search_targets("example.com", host._SOURCE_ALL_RSS)

    assert _target_names(targets) == [
        "Feedly",
        "Feedspot",
        "Google News",
        "Bing News",
        "YouTube",
        "SoundCloud",
        "Mixcloud",
        "NewsBlur",
        "Reddit",
        "Fediverse",
        "Feedsearch",
        "BlindRSS",
    ]


def test_feed_search_bluesky_only_source_is_supported():
    host = _Host()
    targets = host._build_search_targets("tech", "bluesky")

    assert _target_names(targets) == ["Bluesky"]


def test_feed_search_explicit_feedsearch_selection_runs_for_keyword():
    # Explicitly picking a website-scan source must always run it: the source
    # itself guesses "<term>.com" for bare site names (the "techspot" case).
    host = _Host()
    targets = host._build_search_targets("keyword", "feedsearch")

    assert _target_names(targets) == ["Feedsearch"]


def test_feed_search_explicit_blindrss_selection_runs_for_keyword():
    host = _Host()
    targets = host._build_search_targets("techspot", "blindrss")

    assert _target_names(targets) == ["BlindRSS"]


def test_feed_search_all_sources_single_word_includes_local_site_scan():
    # A single-word term ("techspot") runs the local website scan (which tries
    # techspot.com) but keeps the external Feedsearch service URL-gated.
    host = _Host()
    targets = host._build_search_targets("techspot", host._SOURCE_ALL)

    names = _target_names(targets)
    assert "BlindRSS" in names
    assert "Feedsearch" not in names


def test_feed_search_all_rss_single_word_includes_local_site_scan():
    host = _Host()
    targets = host._build_search_targets("techspot", host._SOURCE_ALL_RSS)

    names = _target_names(targets)
    assert "BlindRSS" in names
    assert "Feedsearch" not in names


def test_site_scan_targets_normalization():
    fn = dialogs.FeedSearchDialog._site_scan_targets

    assert fn("https://www.techspot.com") == ["https://www.techspot.com"]
    assert fn("techspot.com") == ["https://techspot.com"]
    assert fn("techspot") == ["https://techspot.com"]
    assert fn("TechSpot") == ["https://techspot.com"]
    assert fn("blue sky") == []
    assert fn("") == []
