"""Forum-thread (FluxBB / audiogames.net) full-text and rich-view regressions.

A thread page is a flat list of sibling `div.post` blocks with no single node
holding the conversation, so generic extraction picked one post and discarded the
rest: a 20-reply topic came back as one short reply, and the rich reader showed
only the last poster's signature.
"""

from bs4 import BeautifulSoup

import core.article_extractor as article_extractor
import core.article_html as article_html


FORUM_URL = "https://forum.audiogames.net/topic/59794/what-apps-do-you-guys-use/new/posts/"


def _post(num, byline, when, body, *, sig=""):
    return (
        '<div class="post odd">'
        f'<div class="posthead" id="p{num}"><h3 class="hn post-ident">'
        f'<span class="post-num"><a class="permalink" href="#p{num}">#{num}</a></span>'
        f'<span class="post-byline"><span>{byline} by</span> '
        f'<a href="https://forum.audiogames.net/user/1/">{when[0]}</a></span>'
        f'<span class="post-link">{when[1]}</span>'
        "</h3></div>"
        '<div class="postbody">'
        '<div class="post-author"><ul class="author-ident">'
        f'<li class="username"><a href="#">{when[0]}</a></li>'
        '<li class="usertitle"><span>hero caller</span></li></ul>'
        '<ul class="author-info"><li><span>Registered: <strong>2014-05-25</strong></span></li>'
        '<li><span>Posts: <strong>302</strong></span></li></ul></div>'
        '<div class="post-entry"><div class="entry-content">'
        f"<p>{body}</p>"
        + (f'<div class="sig-content"><span class="sig-line"></span>{sig}</div>' if sig else "")
        + "</div></div></div>"
        '<div class="postfoot"><div class="post-options"><p class="post-actions">'
        '<span class="report-post"><a href="#">Quote<span>Post 1</span></a></span>'
        "</p></div></div>"
        "</div>"
    )


THREAD_HTML = (
    '<html lang="en"><head><title>What apps do you guys use? (Page 1) — AudioGames.net Forum</title>'
    "</head><body>"
    '<div id="brd-navlinks"><ul><li><a href="/">Index</a></li>'
    '<li><a href="/search/">Search</a></li></ul></div>'
    '<div id="brd-main">'
    '<p class="paging"><span class="pages">Pages</span> <strong>1</strong></p>'
    '<p class="posting">You must <a href="/login/">login</a> or '
    '<a href="/register/">register</a> to post a reply</p>'
    + _post(1, "Topic", ("Zayed", "2026-07-19 13:12:20"), "Which delivery apps do you use?")
    + _post(2, "Reply", ("Minionslayer", "2026-07-19 13:34:07"), "Deliveroo on iOS is my pick.")
    + _post(
        3,
        "Reply",
        ("Cornettoking", "Yesterday 18:24:00"),
        "It is called Lieferando here.",
        sig="Visit my soundcloud page where I upload silly songs.",
    )
    + "</div></body></html>"
)

# A single-post "here are the links" thread: FluxBB shortens the visible link text
# but keeps the href intact.
AMAZON_HREF = "https://www.amazon.com/dp/B0CKB9WK3F?ref_=ppx_hzsearch_conn_dt_b_fed_asin_title_1"
LINK_THREAD_HTML = (
    '<html lang="en"><head><title>Looking to sell a gaming headset — AudioGames.net Forum</title>'
    "</head><body><div id=\"brd-main\">"
    + _post(
        1,
        "Topic",
        ("austingrace", "Yesterday 18:50:34"),
        "Hello everyone. I am selling a headset and a fight stick. Here are amazon links."
        "<br>The controller<br>"
        f'<a href="{AMAZON_HREF}">https://www.amazon.com/dp/B0CKB9WK3F?re … in_title_1</a>'
        "<br>Thank you all for reading.",
    )
    + "</div></body></html>"
)


def test_every_post_is_extracted_with_attribution():
    text = article_extractor._extract_site_specific_text(THREAD_HTML, FORUM_URL)

    assert "#1 Topic by Zayed — 2026-07-19 13:12:20" in text
    assert "#2 Reply by Minionslayer — 2026-07-19 13:34:07" in text
    assert "#3 Reply by Cornettoking — Yesterday 18:24:00" in text
    for body in (
        "Which delivery apps do you use?",
        "Deliveroo on iOS is my pick.",
        "It is called Lieferando here.",
    ):
        assert body in text


def test_signatures_and_forum_chrome_are_dropped():
    text = article_extractor._extract_site_specific_text(THREAD_HTML, FORUM_URL)

    # A per-user signature repeats under every post that user makes.
    assert "soundcloud" not in text
    # Page furniture that framed the thread.
    assert "Pages" not in text
    assert "login" not in text
    assert "Registered" not in text
    assert "Quote" not in text


def test_truncated_link_text_is_replaced_with_the_real_url():
    text = article_extractor._extract_site_specific_text(LINK_THREAD_HTML, FORUM_URL)

    assert AMAZON_HREF in text
    assert "…" not in text


def test_short_link_heavy_thread_is_not_rejected_as_a_link_list():
    # The post header is short and punctuation-free by design; counting it as
    # evidence would tip a "here are the links" post over the rejection ratio.
    text = article_extractor._extract_site_specific_text(LINK_THREAD_HTML, FORUM_URL)

    assert article_extractor._looks_like_link_list(text) is False


def test_non_forum_page_falls_through_to_generic_extraction():
    # The handler must fail open on a forum index or error page.
    assert (
        article_extractor._extract_forum_thread_text(
            "<html><body><p>No posts here.</p></body></html>", FORUM_URL
        )
        == ""
    )


def test_rich_view_renders_every_post_under_its_own_heading():
    body = article_html.clean_article_html(THREAD_HTML, FORUM_URL)
    soup = BeautifulSoup(body, "html.parser")

    headings = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]
    assert headings == [
        "#1 Topic by Zayed — 2026-07-19 13:12:20",
        "#2 Reply by Minionslayer — 2026-07-19 13:34:07",
        "#3 Reply by Cornettoking — Yesterday 18:24:00",
    ]
    assert "Deliveroo on iOS is my pick." in body


def test_rich_view_keeps_links_and_expands_truncated_text():
    body = article_html.clean_article_html(LINK_THREAD_HTML, FORUM_URL)
    soup = BeautifulSoup(body, "html.parser")

    anchors = [a for a in soup.find_all("a") if a.get("href") == AMAZON_HREF]
    assert anchors, "the amazon link must stay clickable in the rich reader"
    assert anchors[0].get_text(strip=True) == AMAZON_HREF
