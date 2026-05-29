"""Tests for subscribing to YouTube and Rumble search results as feeds."""

import json
import os
import sys
import tempfile
import types
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.discovery as discovery
import core.rumble as rumble


class YoutubeSearchDetectionTests(unittest.TestCase):
    def test_detects_search_url(self):
        self.assertTrue(discovery.is_youtube_search_url("https://www.youtube.com/results?search_query=clownfishtv"))
        self.assertEqual(discovery.youtube_search_query("https://www.youtube.com/results?search_query=clownfishtv"), "clownfishtv")

    def test_non_search_urls(self):
        self.assertFalse(discovery.is_youtube_search_url("https://www.youtube.com/watch?v=abc"))
        self.assertFalse(discovery.is_youtube_search_url("https://www.youtube.com/@ClownfishTV"))
        self.assertFalse(discovery.is_youtube_search_url("https://rumble.com/c/ClownfishTV"))

    def test_search_url_has_no_native_feed(self):
        # Must stay as-is so the search-listing path runs on refresh.
        self.assertIsNone(discovery.get_ytdlp_feed_url("https://www.youtube.com/results?search_query=clownfishtv"))


class FetchYoutubeSearchItemsTests(unittest.TestCase):
    def test_parses_ytdlp_flat_dump(self):
        lines = "\n".join(
            json.dumps(e)
            for e in [
                {"id": "vid1", "title": "Newest Video", "uploader": "Clownfish TV", "upload_date": "20260524"},
                {"id": "vid2", "title": "Older Video", "channel": "Clownfish TV"},
                {"title": "no id, skipped"},
            ]
        )

        def fake_run(cmd, **kwargs):
            # Confirm we request a date-sorted search (sp=CAI%3D) for the query.
            joined = " ".join(str(a) for a in cmd)
            assert "sp=CAI%3D" in joined, cmd
            assert "search_query=clownfishtv" in joined, cmd
            return types.SimpleNamespace(returncode=0, stdout=lines, stderr="")

        orig = discovery.subprocess.run
        discovery.subprocess.run = fake_run
        try:
            title, items = discovery.fetch_youtube_search_items("clownfishtv", max_items=10)
        finally:
            discovery.subprocess.run = orig

        self.assertEqual(title, "YouTube: clownfishtv")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].url, "https://www.youtube.com/watch?v=vid1")
        self.assertEqual(items[0].title, "Newest Video")
        self.assertEqual(items[0].published, "2026-05-24")
        self.assertEqual(items[0].id, "https://www.youtube.com/watch?v=vid1")

    def test_empty_query(self):
        title, items = discovery.fetch_youtube_search_items("", max_items=10)
        self.assertIsNone(title)
        self.assertEqual(items, [])


class RumbleSearchNormalizationTests(unittest.TestCase):
    def test_search_url_sorts_by_date(self):
        out = rumble.normalize_rumble_feed_url("https://rumble.com/search/all?q=technology")
        self.assertIn("q=technology", out)
        self.assertIn("sort=date", out)

    def test_existing_sort_preserved(self):
        out = rumble.normalize_rumble_feed_url("https://rumble.com/search/all?q=technology&sort=views")
        self.assertIn("sort=views", out)
        self.assertNotIn("sort=date", out)

    def test_channel_still_normalizes_to_videos(self):
        out = rumble.normalize_rumble_feed_url("https://rumble.com/c/ClownfishTV")
        self.assertTrue(out.endswith("/c/ClownfishTV/videos"))


class YoutubeSearchRefreshIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import core.db as db
        self.db = db
        self.orig = db.DB_FILE
        db.DB_FILE = os.path.join(self.tmp.name, "rss.db")
        db.init_db()

        from providers.local import LocalProvider
        self.provider = LocalProvider({"providers": {"local": {}}, "feed_timeout_seconds": 5, "feed_retry_attempts": 0})

        self.feed_id = "yt-search-feed"
        self.feed_url = "https://www.youtube.com/results?search_query=clownfishtv"
        conn = db.get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_id, self.feed_url, "YouTube: clownfishtv", "Tests", ""),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.db.DB_FILE = self.orig
        self.tmp.cleanup()

    def test_refresh_inserts_video_articles(self):
        items = [
            discovery.YoutubeSearchItem(url="https://www.youtube.com/watch?v=vid1", title="Newest", author="Clownfish TV"),
            discovery.YoutubeSearchItem(url="https://www.youtube.com/watch?v=vid2", title="Older", author="Clownfish TV"),
        ]
        orig = discovery.fetch_youtube_search_items
        discovery.fetch_youtube_search_items = lambda q, max_items=30, timeout_s=30.0, cookiefile=None: ("YouTube: clownfishtv", items)
        try:
            self.provider.refresh(force=True)
        finally:
            discovery.fetch_youtube_search_items = orig

        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("SELECT title, url, media_url, media_type FROM articles WHERE feed_id = ? ORDER BY url", (self.feed_id,))
        rows = c.fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        for title, url, media_url, media_type in rows:
            self.assertTrue(url.startswith("https://www.youtube.com/watch?v="))
            self.assertEqual(media_url, url)
            self.assertEqual(media_type, "video/youtube")


if __name__ == "__main__":
    unittest.main()
