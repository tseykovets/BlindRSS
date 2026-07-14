"""Regression coverage for Google News RSS redirect resolution.

Google News feed items hold a signed JavaScript redirect URL.  These tests keep the resolver fully
offline: the Google page, signed RPC response, publisher page, and consent document are fixtures.
"""

import json

import pytest

import core.article_extractor as article_extractor
import core.utils as utils


TOKEN = "CBMiYV95cUxORGVtb1N0YWJsZVRva2VuX0ZvclRlc3Rz"
GOOGLE_URL = f"https://news.google.com/rss/articles/{TOKEN}?oc=5"
PUBLISHER_URL = "https://publisher.example/news/full-story"
CONSENT_HTML = (
    "<html><title>Before you continue</title><body>"
    "<h1>Before you continue to Google</h1>"
    "<p>We use cookies and data to deliver and maintain Google services.</p>"
    "</body></html>"
)


class _Response:
    def __init__(self, status_code, text, url=""):
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"
        self.url = url


def _signed_google_news_page(token=TOKEN):
    # This mirrors the current c-wiz[data-p] form served for a Google News RSS article page.
    request_context = [
        [
            "en-US",
            "US",
            ["FINANCE_TOP_INDICES", "WEB_TEST_1_0_0"],
            None,
            None,
            1,
            1,
            "US:en",
            None,
            180,
            None,
            None,
            None,
            None,
            None,
            0,
            None,
        ],
        "en-US",
        "US",
        True,
        [3, 5, 9, 19],
        1,
        True,
        "945415507",
        False,
        False,
        None,
        False,
    ]
    rpc_args = [
        "garturlreq",
        request_context,
        token,
        1,
        2,
        None,
        False,
        1783995041,
        "signed-google-request",
    ]
    # Google leaves the `garturlreq` wrapper prefix implicit in data-p.  The production resolver
    # reconstructs it before JSON decoding.
    serialized = json.dumps(rpc_args, separators=(",", ":"))
    data_p = article_extractor._GOOGLE_NEWS_DATA_PREFIX + serialized[len('["garturlreq",'):]
    return f"<html><body><c-wiz data-p='{data_p}'></c-wiz></body></html>"


def _batch_response(url=PUBLISHER_URL):
    rpc_result = json.dumps(["garturlres", url])
    return ")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", rpc_result]])


def test_google_news_resolver_uses_signed_rpc_and_returns_publisher_url(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return _Response(200, _signed_google_news_page(), url)

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return _Response(200, _batch_response(), url)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    monkeypatch.setattr(utils, "safe_requests_post", fake_post)

    resolved = article_extractor._resolve_google_news_article_url(GOOGLE_URL, timeout=60)

    assert resolved == PUBLISHER_URL
    assert calls[0][0] == "get"
    assert "hl=en-US" in calls[0][1]
    assert calls[0][2]["timeout"] == 10.0
    assert calls[1][0] == "post"
    assert calls[1][1] == article_extractor._GOOGLE_NEWS_BATCH_EXECUTE_URL
    assert calls[1][2]["timeout"] == 10.0

    signed_request = json.loads(json.loads(calls[1][2]["data"]["f.req"])[0][0][1])
    assert signed_request[0] == "garturlreq"
    assert signed_request[2] == TOKEN
    assert signed_request[-2:] == [1783995041, "signed-google-request"]


def test_google_news_resolver_rejects_malformed_and_non_google_urls_without_requests(monkeypatch):
    def unexpected_request(*args, **kwargs):
        raise AssertionError("resolver must not request an unrecognized URL")

    monkeypatch.setattr(utils, "safe_requests_get", unexpected_request)
    monkeypatch.setattr(utils, "safe_requests_post", unexpected_request)

    assert article_extractor._resolve_google_news_article_url(
        "https://news.google.com/rss/articles/not a valid token", timeout=5
    ) is None
    assert article_extractor._resolve_google_news_article_url(
        "https://example.com/rss/articles/CBMiYV95cUxORGVtb1N0YWJsZVRva2VuX0ZvclRlc3Rz", timeout=5
    ) is None


def test_google_news_resolver_rejects_consent_page_without_posting(monkeypatch):
    posted = False

    def fake_get(url, **kwargs):
        return _Response(200, CONSENT_HTML, "https://consent.google.com/m")

    def fake_post(*args, **kwargs):
        nonlocal posted
        posted = True
        return _Response(200, _batch_response())

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    monkeypatch.setattr(utils, "safe_requests_post", fake_post)

    assert article_extractor._looks_like_bot_interstitial(CONSENT_HTML) is True
    assert article_extractor._resolve_google_news_article_url(GOOGLE_URL, timeout=5) is None
    assert posted is False


def test_google_news_fulltext_fetches_resolved_publisher_url_instead_of_google(monkeypatch):
    fetched = []
    metadata_calls = []
    publisher_html = "<html><head><title>Publisher story</title></head><body><article>body</article></body></html>"

    monkeypatch.setattr(article_extractor, "trafilatura", object())
    monkeypatch.setattr(article_extractor, "_resolve_google_news_article_url", lambda url, timeout: PUBLISHER_URL)

    def fake_fetch(url, timeout=20):
        fetched.append((url, timeout))
        return article_extractor._FetchResult(html=publisher_html)

    monkeypatch.setattr(article_extractor, "_fetch_page", fake_fetch)
    monkeypatch.setattr(article_extractor, "_extract_title_author_from_meta", lambda html, url: ("Publisher story", "Reporter"))
    monkeypatch.setattr(article_extractor, "_extract_text_any", lambda html, url: "The full publisher article body.")
    monkeypatch.setattr(article_extractor, "_find_next_page", lambda html, url: None)

    article = article_extractor.extract_full_article(
        GOOGLE_URL,
        max_pages=1,
        timeout=7,
        metadata_sink=lambda html, url: metadata_calls.append((html, url)),
    )

    assert fetched == [(PUBLISHER_URL, 7)]
    assert metadata_calls == [(publisher_html, PUBLISHER_URL)]
    assert article.url == GOOGLE_URL
    assert article.title == "Publisher story"
    assert article.text == "The full publisher article body."


def test_google_news_fulltext_fails_closed_for_malformed_redirect(monkeypatch):
    malformed = "https://news.google.com/rss/articles/short"
    monkeypatch.setattr(article_extractor, "trafilatura", object())
    monkeypatch.setattr(
        article_extractor,
        "_fetch_page",
        lambda *args, **kwargs: pytest.fail("must not fetch Google News directly after resolver rejection"),
    )

    with pytest.raises(article_extractor.ExtractionError, match="Google News could not resolve"):
        article_extractor.extract_full_article(malformed, max_pages=1, timeout=5)
