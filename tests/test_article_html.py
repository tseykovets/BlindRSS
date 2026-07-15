"""Tests for the embed-preserving rich-reader HTML cleaner (core.article_html)."""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from bs4 import BeautifulSoup

from core import article_html


ARTICLE = """
<html><body>
<header class="site-header"><nav><a href="/">Home</a></nav></header>
<aside class="sidebar"><ul>
<li><a href="/promo1">Trending one</a></li>
<li><a href="/promo2">Trending two</a></li>
</ul></aside>
<article>
<h1>The big story</h1>
<p>This is the opening paragraph with a <a href="/report">relative link</a> and
enough prose to be a real article body worth keeping in the cleaned output.</p>
<figure class="video">
<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?rel=0" allowfullscreen></iframe>
</figure>
<p>Closing paragraph, also with an <img src="/pics/x.jpg" alt="a chart"> image.</p>
<div class="newsletter-signup"><p>Subscribe to our newsletter!</p></div>
</article>
<div class="ticker">Live ticker: markets up ...</div>
<footer class="site-footer">Copyright</footer>
</body></html>
"""


class CleanArticleHtmlTests(unittest.TestCase):
    def setUp(self):
        self.out = article_html.clean_article_html(ARTICLE, "https://news.example.com/story")
        self.soup = BeautifulSoup(self.out, "html.parser")

    def test_keeps_article_prose(self):
        self.assertIn("opening paragraph", self.out)
        self.assertIn("Closing paragraph", self.out)

    def test_drops_sidebar_and_ticker_and_footer(self):
        self.assertNotIn("Trending one", self.out)
        self.assertNotIn("Live ticker", self.out)
        self.assertNotIn("Copyright", self.out)

    def test_drops_chrome_by_class(self):
        self.assertNotIn("newsletter", self.out.lower())

    def test_preserves_youtube_iframe_normalized(self):
        iframe = self.soup.find("iframe")
        self.assertIsNotNone(iframe)
        self.assertEqual(iframe["src"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_absolutizes_relative_link_and_image(self):
        a = self.soup.find("a", string="relative link")
        self.assertEqual(a["href"], "https://news.example.com/report")
        img = self.soup.find("img")
        self.assertEqual(img["src"], "https://news.example.com/pics/x.jpg")

    def test_strips_event_handlers_and_classes(self):
        self.assertNotIn("onclick", self.out.lower())
        self.assertNotIn("class=", self.out.lower())

    def test_empty_input_returns_empty(self):
        self.assertEqual(article_html.clean_article_html("", "u"), "")
        self.assertEqual(article_html.clean_article_html(None, "u"), "")


class EmbedNormalizationTests(unittest.TestCase):
    def test_protocol_relative_and_vimeo(self):
        html = (
            "<article><p>Body text long enough to be kept as the article body here.</p>"
            '<iframe src="//player.vimeo.com/video/12345"></iframe></article>'
        )
        out = article_html.clean_article_html(html, "https://x.example.com/a")
        self.assertIn('src="https://vimeo.com/12345"', out)

    def test_script_tags_removed(self):
        html = (
            "<article><p>Body text that is long enough to be kept as an article.</p>"
            '<script>evil()</script></article>'
        )
        out = article_html.clean_article_html(html, "https://x.example.com/a")
        self.assertNotIn("evil()", out)
        self.assertNotIn("<script", out.lower())


class SocialEmbedTests(unittest.TestCase):
    def _clean(self, body):
        html = f"<article><p>Body prose long enough to be kept as the article.</p>{body}</article>"
        return article_html.clean_article_html(html, "https://news.example.com/a")

    def test_twitter_becomes_platform_iframe(self):
        out = self._clean(
            '<blockquote class="twitter-tweet"><p>hi</p>'
            '<a href="https://twitter.com/jack/status/20">link</a></blockquote>'
        )
        self.assertIn('src="https://platform.twitter.com/embed/Tweet.html?id=20"', out)

    def test_x_domain_link(self):
        out = self._clean(
            '<blockquote class="twitter-tweet">'
            '<a href="https://x.com/user/status/1799999999999999999">t</a></blockquote>'
        )
        self.assertIn("platform.twitter.com/embed/Tweet.html?id=1799999999999999999", out)

    def test_instagram_embed(self):
        out = self._clean(
            '<blockquote class="instagram-media" '
            'data-instgrm-permalink="https://www.instagram.com/p/ABC123/"></blockquote>'
        )
        self.assertIn("instagram.com/p/ABC123/embed", out)

    def test_tiktok_embed(self):
        out = self._clean(
            '<blockquote class="tiktok-embed" '
            'cite="https://www.tiktok.com/@user/video/6718335390845095173"></blockquote>'
        )
        self.assertIn("tiktok.com/embed/v2/6718335390845095173", out)

    def test_bluesky_at_uri_embed(self):
        out = self._clean(
            '<blockquote class="bluesky-embed" '
            'data-bluesky-uri="at://did:plc:abc123/app.bsky.feed.post/xyz789">'
            '<a href="https://bsky.app/profile/user.bsky.social/post/xyz789">p</a></blockquote>'
        )
        self.assertIn("embed.bsky.app/embed/did:plc:abc123/app.bsky.feed.post/xyz789", out)

    def test_facebook_plugin_iframe(self):
        out = self._clean(
            '<div class="fb-post" data-href="https://www.facebook.com/user/posts/12345"></div>'
        )
        self.assertIn("facebook.com/plugins/post.php?href=", out)
        self.assertIn("12345", out)

    def test_mastodon_iframe_kept(self):
        out = self._clean(
            '<iframe src="https://mastodon.social/@user/109999999999999999/embed"></iframe>'
        )
        self.assertIn("mastodon.social/@user/109999999999999999/embed", out)

    def test_bluesky_handle_only_falls_back_to_link(self):
        out = self._clean(
            '<blockquote class="bluesky-embed">'
            '<a href="https://bsky.app/profile/user.bsky.social/post/xyz789">post</a></blockquote>'
        )
        # No DID available, so no iframe — but the permalink stays clickable.
        self.assertNotIn("embed.bsky.app", out)
        self.assertIn('href="https://bsky.app/profile/user.bsky.social/post/xyz789"', out)

    def test_social_wrapper_class_does_not_eat_iframe(self):
        out = self._clean(
            '<div class="social-embed twitter">'
            '<blockquote class="twitter-tweet">'
            '<a href="https://twitter.com/jack/status/20">t</a></blockquote></div>'
        )
        self.assertIn("platform.twitter.com/embed/Tweet.html?id=20", out)


class RenderFullArticleHtmlTests(unittest.TestCase):
    def test_falls_back_to_feed_content_when_no_url(self):
        feed = "<p>Feed body paragraph with enough words to render in the reader.</p>"
        out = article_html.render_full_article_html(
            "", fallback_html=feed, fallback_title="A title"
        )
        self.assertIsNotNone(out)
        self.assertIn("Feed body paragraph", out)
        self.assertIn("<h1>A title</h1>", out)

    def test_returns_none_when_nothing_to_show(self):
        out = article_html.render_full_article_html("", fallback_html="")
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
