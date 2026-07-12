"""
Full-text article extraction using trafilatura.

Goal:
- Given an article URL, extract clean text (no ads/boilerplate) plus title and author.
- Follow simple multi-page pagination (rel=next / next links) and merge text.
- Provide safe fallbacks for feed items without a webpage URL (e.g., podcast episodes).
"""

from __future__ import annotations

import html
import json
import re
import time
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Tuple, List, Set
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from core import utils

from core.i18n import _

LOG = logging.getLogger(__name__)

try:
    import trafilatura
    from trafilatura.metadata import extract_metadata
except Exception:
    trafilatura = None
    extract_metadata = None


class ExtractionError(RuntimeError):
    """Raised when an extraction attempt fails in a way worth surfacing to the UI."""
    pass


@dataclass
class FullArticle:
    url: str
    title: str
    author: str
    text: str


_MEDIA_EXTS = (
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus",
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".pdf",
)

_LEAD_RECOVERY_ALLOWED_NETLOC_SUFFIXES = {
    # Some sites have a meaningful lead/intro in the HTML meta description that trafilatura may
    # skip when running in precision mode.
    "wirtualnemedia.pl",
}

_LEAD_RECOVERY_MIN_PRECISION_LEN = 200
_LEAD_RECOVERY_MIN_DESC_LEN = 60
_LEAD_RECOVERY_DESC_SNIPPET_LEN = 120
_LEAD_RECOVERY_DESC_HIT_SNIPPET_LEN = 80
_LEAD_RECOVERY_MAX_RECALL_NORM_CHARS = 8000
_LEAD_RECOVERY_MAX_SCAN_PARAS = 8
_LEAD_RECOVERY_MIN_PARA_LEN = 40
_LEAD_RECOVERY_MAX_PARA_LEN = 800
_LEAD_RECOVERY_MIN_PUNCT_PARA_LEN = 120
_LEAD_RECOVERY_MAX_INTRO_PARAS = 2

_TITLE_SUFFIX_STRIP_SEPARATORS = (" | ", " — ", " – ")
_META_DESCRIPTION_TAG_ATTRS: List[dict] = [
    {"property": "og:description"},
    {"name": "description"},
    {"name": "twitter:description"},
]
_META_TITLE_TAG_ATTRS: List[dict] = [
    {"property": "og:title"},
    {"name": "twitter:title"},
    {"name": "title"},
]

_JSON_LD_TEXT_FIELDS = ("articleBody", "text")
_JSON_LD_MIN_TEXT_LEN = 120
_BLOOMBERG_VIDEO_DESCRIPTION_MIN_LEN = 80

# Axios (Next.js) ships the canonical article body inside the __NEXT_DATA__ JSON blob
# (props.pageProps.data.story.bodyHtml). Some page variants render no body in the DOM at all,
# so DOM-based extraction only finds related-story cards and the "preferred source on Google"
# promo. The JSON body is present in every variant, so it is the reliable source.
_AXIOS_STORY_MIN_TEXT_LEN = 200
_AXIOS_BODY_HTML_KEYS = ("beforeKeepReading", "afterKeepReading")

# Anti-bot / human-verification interstitials.
#
# These are NOT articles: they are access-control gates (Cloudflare challenges, "you're not a
# robot" / "unusual activity" pages from Bloomberg/Akamai/PerimeterX/DataDome, etc.). We must not
# store the gate text as article content. When we detect one, extraction is treated as a failure so
# the UI degrades cleanly to the feed snippet plus the original link.
#
# We do not attempt to defeat these gates. Detection only exists to fail gracefully.
_BOT_INTERSTITIAL_MARKERS = (
    # Cloudflare challenge / managed challenge pages
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "cf-browser-verification",
    "__cf_chl_",
    "cf_chl_opt",
    "enable javascript and cookies to continue",
    "ddos protection by cloudflare",
    "performance & security by cloudflare",
    # Generic "are you a human/robot" gates (Bloomberg, Reuters, Akamai, PerimeterX, DataDome, ...)
    "we've detected unusual activity from your computer network",
    "let us know you're not a robot",
    "please verify you are a human",
    "verify you are human",
    "press & hold to confirm you",
    "please make sure your browser supports javascript and cookies",
    "block reference id",
    "why have i been blocked",
    "access to this page has been denied",
    "please complete the security check to access",
    "pardon our interruption",
    "as you were browsing, something about your browser made us think you were a bot",
    # Vercel / generic WAF verification page (seen on Neowin, also relayed through read-proxies
    # as markdown: "## Performing security verification ...")
    "performing security verification",
    "uses a security service to protect against malicious bots",
    "while the website verifies you are not a bot",
)

# Block-page bodies are short; a long article that merely mentions one of these phrases should not be
# discarded. Only treat a post-extraction body as a gate when it is small.
_BOT_INTERSTITIAL_MAX_BODY_LEN = 1500

_BLOCKED_INTERSTITIAL_MESSAGE = (
    "This page is behind an anti-bot / human-verification check "
    "(e.g. Cloudflare or a \"you're not a robot\" page), so the full text can't be fetched "
    "automatically. Open the original link in your browser to read it."
)


def _looks_like_bot_interstitial(content: str) -> bool:
    """Return True if `content` (HTML or already-extracted text) is an anti-bot/verification gate."""
    if not content:
        return False
    low = content.replace("’", "'").lower()
    if len(low) < 2000 and "powered and protected by" in low and "akamai" in low:
        return True
    return any(marker in low for marker in _BOT_INTERSTITIAL_MARKERS)


def _lead_recovery_enabled(url: str) -> bool:
    if not url:
        return False
    try:
        host = urlsplit(url).hostname
    except (AttributeError, TypeError, ValueError):
        return False
    if not host or not isinstance(host, str):
        return False
    host = host.lower()
    return any(host == d or host.endswith("." + d) for d in _LEAD_RECOVERY_ALLOWED_NETLOC_SUFFIXES)


def _looks_like_media_url(url: str) -> bool:
    try:
        path = (urlsplit(url).path or "").lower()
        return any(path.endswith(ext) for ext in _MEDIA_EXTS)
    except Exception:
        return False


def _normalize_whitespace(text: str) -> str:
    text = (text or "").replace("\u200b", "").replace("\u2060", "").replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_paragraphs(text: str) -> List[str]:
    t = _normalize_whitespace(text or "")
    if not t:
        return []
    # Split by blank lines first (strong paragraph separator), then by single newlines.
    # This handles mixed separators like "p1\\np2\\n\\np3" without merging p1+p2.
    blocks = re.split(r"\n\s*\n", t)
    return [p.strip() for block in blocks for p in block.split("\n") if p.strip()]


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _strip_trailing_ellipsis(text: str) -> str:
    return re.sub(r"(?:\.\.\.|…)\s*$", "", (text or "").strip()).strip()


def _is_reasonable_lead_paragraph(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if len(t) < _LEAD_RECOVERY_MIN_PARA_LEN or len(t) > _LEAD_RECOVERY_MAX_PARA_LEN:
        return False
    if re.search(r"[.!?]", t):
        return True
    return len(t) >= _LEAD_RECOVERY_MIN_PUNCT_PARA_LEN


def _strip_title_suffix(title: str) -> str:
    t = (title or "").strip()
    for sep in _TITLE_SUFFIX_STRIP_SEPARATORS:
        if sep in t:
            # Split from the right and take the longest segment.
            # This tends to drop short site-name suffix/prefix; we intentionally avoid stripping " - "
            # because it's common in legitimate titles.
            return max(t.rsplit(sep, 1), key=len).strip()
    return t


def _extract_meta_content(soup: BeautifulSoup, candidates: List[dict]) -> str:
    for attrs in candidates:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            content = (tag.get("content") or "").strip()
            if content:
                return content
    return ""


def _parse_html_soup(html: Optional[str], *, context: str) -> Optional[BeautifulSoup]:
    if not html:
        return None
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception:
        LOG.debug("Failed to parse HTML for %s", context, exc_info=True)
        return None


def _extract_meta_description(*, html: Optional[str] = None, soup: Optional[BeautifulSoup] = None) -> str:
    if soup is None:
        soup = _parse_html_soup(html, context="meta description")
        if soup is None:
            return ""

    return _extract_meta_content(
        soup,
        _META_DESCRIPTION_TAG_ATTRS,
    )


def _extract_page_title(*, html: Optional[str] = None, soup: Optional[BeautifulSoup] = None) -> str:
    if soup is None:
        soup = _parse_html_soup(html, context="page title")
        if soup is None:
            return ""

    meta_title = _extract_meta_content(
        soup,
        _META_TITLE_TAG_ATTRS,
    )
    if meta_title:
        return meta_title
    t = soup.find("title")
    if t and t.get_text(strip=True):
        return t.get_text(strip=True)
    return ""


def _collect_json_ld_text(obj, out: List[str]) -> None:
    if isinstance(obj, dict):
        for key in _JSON_LD_TEXT_FIELDS:
            val = obj.get(key)
            if isinstance(val, str):
                out.append(val)
            elif isinstance(val, list):
                joined = " ".join(v for v in val if isinstance(v, str))
                if joined:
                    out.append(joined)
        for v in obj.values():
            _collect_json_ld_text(v, out)
        return
    if isinstance(obj, list):
        for v in obj:
            _collect_json_ld_text(v, out)


def _jsonld_types(obj) -> Set[str]:
    raw = obj.get("@type") if isinstance(obj, dict) else None
    values = raw if isinstance(raw, list) else [raw]
    return {str(v or "").strip().lower() for v in values if str(v or "").strip()}


def _collect_bloomberg_video_descriptions(obj, out: List[str]) -> None:
    if isinstance(obj, dict):
        if "videoobject" in _jsonld_types(obj):
            for key in ("description", "transcript", "caption"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    out.append(val)
        for v in obj.values():
            _collect_bloomberg_video_descriptions(v, out)
        return
    if isinstance(obj, list):
        for v in obj:
            _collect_bloomberg_video_descriptions(v, out)


def _extract_json_ld_text(html: str) -> str:
    if not html:
        return ""
    soup = _parse_html_soup(html, context="json-ld")
    if soup is None:
        return ""

    candidates: List[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        _collect_json_ld_text(data, candidates)

    if not candidates:
        return ""

    cleaned: List[str] = []
    for c in candidates:
        first_tag = re.search(r"<[a-z][^>]*>", c, flags=re.I)
        if first_tag:
            # Some publishers (notably Sky News) put the standfirst directly before the first
            # ``<p>`` in articleBody.  Preserve that leading text while stripping the markup.
            prefix = _normalize_whitespace(c[: first_tag.start()])
            fragment_text = _html_fragment_to_text(c[first_tag.start() :])
            c = "\n\n".join(part for part in (prefix, fragment_text) if part)
        t = _normalize_whitespace(c)
        if t:
            cleaned.append(t)

    if not cleaned:
        return ""

    cleaned.sort(key=len, reverse=True)
    best = cleaned[0]
    if len(best) < _JSON_LD_MIN_TEXT_LEN:
        return ""
    return best


def _extract_bloomberg_video_text(html_text: str, url: str) -> str:
    if not html_text or not _is_bloomberg_video_url(url):
        return ""
    soup = _parse_html_soup(html_text, context="bloomberg video")
    if soup is None:
        return ""

    candidates: List[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        _collect_bloomberg_video_descriptions(data, candidates)

    desc = _extract_meta_description(soup=soup)
    if desc:
        candidates.append(desc)

    cleaned: List[str] = []
    for candidate in candidates:
        text = _normalize_whitespace(html.unescape(candidate))
        if len(text) >= _BLOOMBERG_VIDEO_DESCRIPTION_MIN_LEN and not _looks_like_bot_interstitial(text):
            cleaned.append(text)
    if not cleaned:
        return ""
    cleaned.sort(key=len, reverse=True)
    return cleaned[0]


def _host_matches(url: str, domain: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    return host == domain or host.endswith("." + domain)


def _is_bloomberg_url(url: str) -> bool:
    return _host_matches(url, "bloomberg.com")


def _is_bloomberg_video_url(url: str) -> bool:
    if not _is_bloomberg_url(url):
        return False
    try:
        path = (urlsplit(url).path or "").lower()
    except Exception:
        return False
    return "/videos/" in path or "/news/videos/" in path


def _html_fragment_to_text(fragment_html: str) -> str:
    """Convert a trusted CMS HTML body fragment into paragraph text."""
    soup = _parse_html_soup(fragment_html, context="html fragment")
    if soup is None:
        return ""
    blocks = soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"])
    paras: List[str] = []
    for tag in blocks:
        # Skip container blocks (e.g. a blockquote wrapping <p>s); keep the leaf blocks.
        if tag.find(["p", "li"]) is not None:
            continue
        text = _normalize_whitespace(tag.get_text(" ", strip=True))
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if text:
            paras.append(text)
    if paras:
        return "\n\n".join(paras)
    return _normalize_whitespace(soup.get_text("\n", strip=True))


def _extract_axios_story_text(html: str) -> str:
    """Extract the Axios article body from the __NEXT_DATA__ JSON blob (see note at
    _AXIOS_STORY_MIN_TEXT_LEN). Returns "" when the blob or body is missing/too short."""
    if not html or "__NEXT_DATA__" not in html:
        return ""
    soup = _parse_html_soup(html, context="axios next data")
    if soup is None:
        return ""
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None:
        return ""
    raw = tag.string or tag.get_text(strip=True)
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""

    story = data.get("props") or {}
    for key in ("pageProps", "data", "story"):
        if not isinstance(story, dict):
            return ""
        story = story.get(key) or {}
    if not isinstance(story, dict):
        return ""

    body_html = story.get("bodyHtml")
    if isinstance(body_html, dict):
        fragments = [body_html.get(k) for k in _AXIOS_BODY_HTML_KEYS]
    elif isinstance(body_html, str):
        fragments = [body_html]
    else:
        fragments = []

    texts = [_html_fragment_to_text(f) for f in fragments if isinstance(f, str) and f.strip()]
    text = _normalize_whitespace("\n\n".join(t for t in texts if t))
    if len(text) < _AXIOS_STORY_MIN_TEXT_LEN:
        return ""
    return text


_THEREGISTER_MIN_TEXT_LEN = 300
# The Register's article page opens with several teaser/"spotlight" cards (each its own
# <article>) before the story. The real body is the <article> that carries the standfirst +
# many paragraphs, so we pick the <article> with the most paragraph text rather than the first.
_THEREGISTER_DROP_LEADING_LABELS = {
    "security", "ai + ml", "ai and ml", "software", "systems", "networks", "storage",
    "devops", "personal tech", "science", "offbeat", "on-prem", "off-prem", "special features",
    "bootnotes", "emergent tech", "public sector", "legal", "cso", "spotlight",
}


def _extract_theregister_text(html: str) -> str:
    """Extract The Register's story body.

    The generic extractor grabs the "MOST POPULAR" teaser rail instead of the article, so we
    read the paragraphs straight from the story's own <article> element (the one with the most
    paragraph text) and drop the leading one-word section kicker (e.g. "Security").
    """
    soup = _parse_html_soup(html, context="theregister body")
    if soup is None:
        return ""
    best_node = None
    best_len = 0
    for node in soup.find_all("article"):
        para_len = sum(len(p.get_text(" ", strip=True)) for p in node.find_all("p"))
        if para_len > best_len:
            best_len = para_len
            best_node = node
    if best_node is None:
        return ""
    paras: List[str] = []
    for p in best_node.find_all(["p", "li"]):
        if p.find(["p", "li"]) is not None:
            continue
        text = _normalize_whitespace(p.get_text(" ", strip=True))
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if not text:
            continue
        # Drop the leading section kicker ("Security", "AI + ML", ...) that isn't part of the body.
        if not paras and text.strip().lower() in _THEREGISTER_DROP_LEADING_LABELS:
            continue
        paras.append(text)
    text = _normalize_whitespace("\n\n".join(paras))
    if len(text) < _THEREGISTER_MIN_TEXT_LEN:
        return ""
    return text


def _extract_without_dom_boilerplate(html: str, url: str, selectors: Tuple[str, ...]) -> str:
    """Run normal extraction after removing known non-article DOM sections."""
    soup = _parse_html_soup(html, context="site boilerplate removal")
    if soup is None:
        return ""
    removed = False
    for selector in selectors:
        for node in soup.select(selector):
            node.decompose()
            removed = True
    if not removed:
        return ""
    return _trafilatura_extract_text(str(soup), url=url)


def _extract_site_specific_text(html: str, url: str) -> str:
    """Site-specific structured body extraction that outranks generic heuristics."""
    if _is_bloomberg_video_url(url):
        return _extract_bloomberg_video_text(html, url)
    if _host_matches(url, "axios.com"):
        return _extract_axios_story_text(html)
    if _host_matches(url, "theregister.com") or _host_matches(url, "theregister.co.uk"):
        return _extract_theregister_text(html)
    if _host_matches(url, "thepostmillennial.com"):
        return _extract_without_dom_boilerplate(html, url, ("section.contributions-container",))
    if _host_matches(url, "rebelnews.com"):
        return _extract_without_dom_boilerplate(html, url, ("section.posts-profile",))
    return ""


def _extract_allowlisted_lead_from_html(soup: BeautifulSoup, url: str) -> str:
    try:
        host = urlsplit(url).hostname
    except Exception:
        host = None
    if not host or not isinstance(host, str):
        return ""
    host = host.lower()

    if host == "wirtualnemedia.pl" or host.endswith(".wirtualnemedia.pl"):
        node = soup.find("div", class_="wm-article-header-lead")
        if node:
            return (node.get_text(" ", strip=True) or "").strip()

    return ""


def _recover_intro_paragraphs(
    recall_text: str,
    *,
    precision_paras_norm: Set[str],
    page_title_norm: str,
    desc_hit_snippet: str,
) -> List[str]:
    intro: List[str] = []
    desc_hit = False

    for p in _split_paragraphs(recall_text)[:_LEAD_RECOVERY_MAX_SCAN_PARAS]:
        pn = _normalize_for_match(p)
        if not pn:
            continue
        if pn in precision_paras_norm:
            break
        if page_title_norm and pn == page_title_norm:
            continue
        if not _is_reasonable_lead_paragraph(p):
            continue
        if desc_hit_snippet and desc_hit_snippet in pn:
            desc_hit = True
        intro.append(p)
        if len(intro) >= _LEAD_RECOVERY_MAX_INTRO_PARAS:
            break

    if not intro or not desc_hit:
        return []
    return intro


def _attempt_lead_recovery(
    html: str,
    url: str,
    *,
    precision_text: str,
    precision_norm: str,
    do_extract: Callable[[dict], str],
) -> Optional[str]:
    if not _lead_recovery_enabled(url):
        return None

    soup = _parse_html_soup(html, context="lead recovery")
    if soup is None:
        return None

    desc = _strip_trailing_ellipsis(_extract_meta_description(soup=soup))
    desc_norm = _normalize_for_match(desc)
    if not desc_norm or len(desc_norm) < _LEAD_RECOVERY_MIN_DESC_LEN:
        return None

    desc_snippet = desc_norm[:_LEAD_RECOVERY_DESC_SNIPPET_LEN]
    desc_hit_snippet = desc_norm[:_LEAD_RECOVERY_DESC_HIT_SNIPPET_LEN]
    if desc_snippet in precision_norm:
        return None

    def _fallback_prepend_meta_desc() -> Optional[str]:
        # Fallback: when recall extraction fails to capture the meta description, prepend the
        # cleaned meta description itself (allowlist-only). This is intentionally conservative.
        if not _is_reasonable_lead_paragraph(desc):
            return None
        combined = "\n\n".join([desc, precision_text])
        return (combined or "").strip()

    lead_html = _extract_allowlisted_lead_from_html(soup, url)
    lead_html_norm = _normalize_for_match(lead_html)
    if lead_html_norm and desc_hit_snippet and desc_hit_snippet in lead_html_norm and lead_html_norm not in precision_norm:
        if _is_reasonable_lead_paragraph(lead_html):
            combined = "\n\n".join([lead_html, precision_text])
            return (combined or "").strip()

    txt_rec = do_extract({"favor_recall": True})
    rec = (txt_rec or "").strip()
    if not rec:
        return _fallback_prepend_meta_desc()

    rec_head_norm = _normalize_for_match(rec[:_LEAD_RECOVERY_MAX_RECALL_NORM_CHARS])
    if desc_snippet not in rec_head_norm:
        return _fallback_prepend_meta_desc()

    page_title = _strip_title_suffix(_extract_page_title(soup=soup))
    page_title_norm = _normalize_for_match(page_title)

    precision_paras_norm = {_normalize_for_match(p) for p in _split_paragraphs(precision_text)}

    intro = _recover_intro_paragraphs(
        rec,
        precision_paras_norm=precision_paras_norm,
        page_title_norm=page_title_norm,
        desc_hit_snippet=desc_hit_snippet,
    )
    if not intro:
        return _fallback_prepend_meta_desc()

    combined = "\n\n".join(intro + [precision_text])
    return (combined or "").strip()


_ZDNET_BOILERPLATE_PATTERNS: List[re.Pattern] = [
    re.compile(r"^\s*ZDNET\s+Recommends\b", re.I),
    re.compile(r"^\s*What\s+exactly\s+does\s+it\s+mean\?\s*$", re.I),
    re.compile(r"\bZDNET's\s+recommendations\s+are\s+based\s+on\b", re.I),
    re.compile(r"\bhours\s+of\s+testing\b", re.I),
    re.compile(r"\bcomparison\s+shopping\b", re.I),
    re.compile(r"\bvendor\s+and\s+retailer\s+listings\b", re.I),
    re.compile(r"\baffiliate\s+commissions\b", re.I),
    re.compile(r"\bdoes\s+not\s+affect\s+the\s+price\s+you\s+pay\b", re.I),
    re.compile(r"\bstrict\s+guidelines\b", re.I),
    re.compile(r"\beditorial\s+content\b.*\badvertisers\b", re.I),
    re.compile(r"\bOur\s+goal\s+is\s+to\s+deliver\b", re.I),
    re.compile(r"\bfact-?check\b", re.I),
    re.compile(r"\breport\s+the\s+mistake\b", re.I),
    re.compile(r"^\s*Follow\s+ZDNET\b", re.I),
    re.compile(r"\bAdd\s+us\s+as\s+a\s+preferred\s+source\s+on\s+Google\b", re.I),
    re.compile(r"\bpreferred\s+source\s+on\s+Google\b", re.I),
    re.compile(r"\bFollow\s+ZDNET\b", re.I),
]


def _strip_zdnet_recommends_block(text: str) -> str:
    """Backward-compatible name: strip common ZDNET boilerplate paragraphs near the top.

    ZDNET sometimes injects disclosure / recommendation / follow blocks at the start of the extracted text.
    We only remove paragraphs that match known patterns, and only within the first N paragraphs to avoid
    deleting real content.
    """
    paras = _split_paragraphs(text)
    if not paras:
        return ""

    max_scan = min(25, len(paras))
    i = 0
    while i < max_scan:
        p = (paras[i] or "").strip()
        if not p:
            i += 1
            continue

        if any(rx.search(p) for rx in _ZDNET_BOILERPLATE_PATTERNS):
            i += 1
            continue

        # A few pages split disclosure headings into tiny chunks.
        if i < 10 and re.search(r"\bZDNET\b", p, re.I) and (
            re.search(r"\brecommend", p, re.I)
            or re.search(r"\bpreferred\s+source\b", p, re.I)
            or re.search(r"\bfollow\b", p, re.I)
        ):
            i += 1
            continue

        break

    cleaned = "\n\n".join(paras[i:]).strip()
    return cleaned


def _strip_thetyee_boilerplate(text: str) -> str:
    """Remove common The Tyee fundraising boilerplate."""
    t = (text or "").strip()
    
    # 1. Top fundraising block (long text ending in 'Support Us Now')
    # Removed ^ anchor to handle cases where title or other metadata precedes it.
    t = re.sub(
        r"(?si)Our\s+[Jj]ournalism\s+is\s+supported\s+by\s+(?:readers|Tyee\s+Builders)\s+like\s+you.*?\nSupport\s+Us\s+Now\s*",
        "",
        t,
        count=1
    )
    
    # 2. Bottom subscription/privacy footer
    # "Subscribe now... Privacy policy"
    t = re.sub(
        r"(?si)Subscribe\s+now\s+Privacy\s+policy.*?Subscribe\s+now\s+Privacy\s+policy\s*",
        "",
        t
    )
    
    return t.strip()


def _strip_9to5mac_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)FTC:\s*We\s+use\s+income\s+earning\s+auto\s+affiliate\s+links\..*?More\.", "", text)
    t = re.sub(r"(?i)You(?:’|')re\s+reading\s+9to5Mac\s*(?:—|-).*?(?:loop\.|channel)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Check\s+out\s+our\s+exclusive\s+stories,.*?(?:channel|loop\.)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?is)\nWorth\s+checking\s+out\s+on\s+Amazon\b.*$", "", t)
    t = re.sub(r"(?is)\nFollow\s+[A-Z][^:\n]{0,60}:\s*(?:Threads|Bluesky|Instagram|Mastodon)\b.*$", "", t)
    return t


def _strip_9to5google_boilerplate(text: str) -> str:
    return re.sub(r"(?is)\nJoin\s+9to5Google\s+Pro\s+to\s+get\s+more\b.*$", "", text)


def _strip_9to5toys_boilerplate(text: str) -> str:
    return re.sub(r"(?is)\nYou(?:’|')re\s+reading\s+9to5Toys\s*(?:—|-).*$", "", text)


def _strip_postmillennial_boilerplate(text: str) -> str:
    return re.sub(r"(?is)\nJoin\s+and\s+support\s+independent\s+free\s+thinkers!.*$", "", text)

def _strip_globalnews_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)^By\s+Staff\s+The\s+Canadian\s+Press", "", text, flags=re.MULTILINE)
    t = re.sub(r"(?i)^Posted\s+\w+\s+\d+,\s+\d+\s+\d+:\d+\s+[ap]m", "", t, flags=re.MULTILINE)
    t = re.sub(r"(?i)^\d+\s+min\s+read", "", t, flags=re.MULTILINE)
    t = re.sub(r"(?i)If\s+you\s+get\s+Global\s+News\s+from\s+Instagram\s+or\s+Facebook.*?(?:connect\s+with\s+us\.)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Hide\s+message\s+barDescrease\s+article\s+font\s+size\s*Increase\s+article\s+font\s+size", "", t)
    return t

# Al Jazeera embeds a "Recommended Stories" related-articles widget INLINE in the article body,
# which extracts as a "list of N items- list 1 of N<headline>" block followed by newline-separated
# "- list K of N<headline>" lines. It sits mid-article, so it is removed in place (not truncated).
_AJ_RELATED_LIST_RE = re.compile(
    r"(?im)^(?:Recommended\s+Stories\s*\n)?"      # optional widget header on its own line
    r"list\s+of\s+\d+\s+items"                     # "list of N items"
    r"-\s*list\s+\d+\s+of\s+\d+[^\n]*"             # first item, glued to "items" (no newline)
    r"(?:\n-\s*list\s+\d+\s+of\s+\d+[^\n]*)*"      # subsequent "- list K of N ..." items
    r"\n?"
)


def _strip_aljazeera_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)Published\s+On\s+\d+\s+\w+\s+\d+.*?(?:20\d\d)", "", text)
    t = re.sub(r"(?i)Click\s+here\s+to\s+share\s+on\s+social\s+media", "", t)
    t = re.sub(r"(?i)share\d+Save", "", t)
    t = _AJ_RELATED_LIST_RE.sub("\n", t)
    return t

_AXIOS_BOILERPLATE_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?i)^Add\s+Axios\s+as\s+(?:a|your)\s+preferred\s+source\b.*\bGoogle\.?$"),
    # Story-card metadata like "17 mins ago - Politics & Policy"
    re.compile(r"(?i)^(?:\d+\s+(?:mins?|minutes?|hours?|days?)|moments?)\s+ago\s*[-–—]\s*\S"),
    re.compile(r"(?i)^Go\s+deeper(?:\s*\(\s*\d+\s+min(?:\.|utes)?\s+read\s*\))?$"),
]

def _strip_axios_boilerplate(text: str) -> str:
    paras = _split_paragraphs(text)
    if not paras:
        return ""
    kept = [p for p in paras if not any(rx.search(p) for rx in _AXIOS_BOILERPLATE_PATTERNS)]
    return "\n\n".join(kept).strip()

def _strip_bbc_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)ShareSave", "", text)
    return t

def _strip_wsj_boilerplate(text: str) -> str:
    # Dow Jones appends a copyright line and an opaque tracking hash to article bodies
    # (e.g. "Copyright ©2026 Dow Jones & Company, Inc. All Rights Reserved. 87990cbe...").
    t = re.sub(
        r"(?is)\s*Copyright\s*©?\s*\d{4}\s*Dow\s+Jones\s*&\s*Company.*?All\s+Rights\s+Reserved\.\s*[0-9a-f]{16,}\s*$",
        "",
        text,
    )
    return t.strip()

# TechRadar (and other Future sites) append a fixed trailing block after the article body:
# a "Follow ... on Google News" / "Sign up for breaking news ..." promo, then the author's bio
# paragraph, then a two-line comment-gate notice ("You must confirm your public display name
# before commenting" / "Please logout and then login again ...").
#
# The comment-gate notice is the only DEFINITIVE end-of-article marker: it is always present and
# always trailing. The "Sign up for breaking news ..." line is NOT a safe truncation anchor because
# TechRadar also drops it inline as a newsletter widget mid-article (verified: one article had it at
# ~29% of the body). So we anchor on the comment gate, drop the author bio paragraph directly above
# it, and drop a promo/sign-up line directly above the bio; separately we remove promo/newsletter
# widget lines (exact boilerplate sentences) wherever they appear in the kept body.
_TECHRADAR_GATE_RE = re.compile(r"(?i)^You\s+must\s+confirm\s+your\s+public\s+display\s+name\s+before\s+commenting\b")
_TECHRADAR_FOLLOW_RE = re.compile(r"(?i)^Follow\s+TechRadar\b.*\b(?:Google\s+News|preferred\s+source)\b")
_TECHRADAR_SIGNUP_RE = re.compile(r"(?i)^Sign\s+up\s+for\s+breaking\s+news\b.*\btop\s+tech\s+deals\b")


def _strip_techradar_boilerplate(text: str) -> str:
    paras = _split_paragraphs(text)
    if not paras:
        return ""

    def _is_promo(p: str) -> bool:
        return bool(_TECHRADAR_FOLLOW_RE.search(p) or _TECHRADAR_SIGNUP_RE.search(p))

    cut = len(paras)
    for i, p in enumerate(paras):
        if _TECHRADAR_GATE_RE.search(p):
            cut = i
            # The author bio sits directly above the comment gate; drop it.
            if cut - 1 >= 0:
                cut -= 1
            # A promo / sign-up line sits directly above the bio; drop it too.
            if cut - 1 >= 0 and _is_promo(paras[cut - 1]):
                cut -= 1
            break
    else:
        # No comment gate: fall back to the always-trailing "Follow ... Google News" promo, which
        # (unlike the sign-up line) never appears inline.
        for i, p in enumerate(paras):
            if _TECHRADAR_FOLLOW_RE.search(p):
                cut = i
                break

    kept = [p for p in paras[:cut] if not _is_promo(p)]
    return "\n\n".join(kept).strip()

def _strip_canada_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)Advertisement\s+\d+", "", text)
    t = re.sub(r"(?i)This\s+advertisement\s+has\s+not\s+loaded\s+yet.*?(?:continues\s+below\.)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Author\s+of\s+the\s+article:.*?(?:read)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Join\s+the\s+conversation", "", t)
    t = re.sub(r"(?i)Read\s+More.*?(?:Article\s+content)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Share\s+this\s+article\s+in\s+your\s+social\s+network", "", t)
    t = re.sub(r"(?i)Trending\s+Latest\s+National\s+Stories", "", t)
    return t

def _strip_slashdot_boilerplate(text: str) -> str:
    """Truncate at Slashdot's trailing OneTrust privacy-choices footer.

    The footer normally never reaches extraction (it lives on a separate
    OneTrust page that was only pulled in via the bogus "next story" link,
    now excluded from pagination-following), but a whole-page markdown
    fallback (e.g. Jina) can still include it, always as the trailing block.
    """
    t = re.sub(
        r"(?is)\n*#*\s*YOUR\s+PRIVACY\s+CHOICES\s*\(DO\s+NOT\s+SELL/SHARE/TARGET\).*$",
        "",
        text or "",
    )
    return t.strip()


def _strip_castanet_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)-\s+.*?\s+-\s+\d+:\d+\s+[ap]m", "", text)
    return t


def _strip_bloomberg_boilerplate(text: str) -> str:
    """Remove Bloomberg page chrome/footer when extraction falls back to page markdown."""
    original = _normalize_whitespace(text or "")
    paras = _split_paragraphs(original)
    if not paras:
        return ""

    def _is_author_line(p: str) -> bool:
        p = (p or "").strip()
        if re.match(r"(?i)^By\s+\[[^\]]+\]\(", p):
            return True
        # Bloomberg sometimes emits plain author text (e.g., "By Bloomberg News")
        return bool(re.match(r"(?i)^By\s+[A-Z][A-Za-z .,'’\\-]{1,100}$", p))

    def _is_bloomberg_meta_or_control(p: str) -> bool:
        p = (p or "").strip()
        if not p:
            return True
        if re.match(r"(?i)^(Gift this article|Add us on Google|Save|Translate|Listen)$", p):
            return True
        if re.match(r"(?i)^(Updated on|Published on)$", p):
            return True
        if re.match(r"(?i)^[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s+[AP]M\s+UTC$", p):
            return True
        if p.startswith("[Contact us: Provide news feedback or report an error]("):
            return True
        if p.startswith("[Confidential tip? Send a tip to our reporters]("):
            return True
        if p.startswith("[Site feedback: Take our Survey]("):
            return True
        if p.startswith("### **Takeaways** by Bloomberg AI") or p.startswith("### Takeaways by Bloomberg AI"):
            return True
        if p.startswith("Takeaways by Bloomberg AI"):
            return True
        return False

    def _is_bloomberg_end_marker(p: str) -> bool:
        p = (p or "").strip()
        if not p:
            return False
        if p.startswith("[Before it's here, it's on the Bloomberg Terminal"):
            return True
        if p.startswith("### More From Bloomberg") or p.startswith("### Top Reads"):
            return True
        if p.startswith("[Home](https://www.bloomberg.com/)[BTV+]"):
            return True
        if p.startswith("[Terms of Service]("):
            return True
        if "Bloomberg L.P. All Rights Reserved" in p:
            return True
        if p.startswith("Explore live news and interviews"):
            return True
        if p.startswith("Get unlimited access for just"):
            return True
        if p.startswith("By accepting, you agree to our updated [Terms of Service"):
            return True
        return False

    def _is_bloomberg_header_line(p: str) -> bool:
        return _is_author_line(p) or _is_bloomberg_meta_or_control(p)

    start = 0
    header_anchor_idx = None
    for i, p in enumerate(paras):
        if _is_author_line(p):
            header_anchor_idx = i
            break
    if header_anchor_idx is None:
        for i, p in enumerate(paras):
            if _is_bloomberg_meta_or_control(p):
                header_anchor_idx = i
                break

    if header_anchor_idx is not None:
        seq_start = header_anchor_idx
        while seq_start > 0 and _is_bloomberg_header_line(paras[seq_start - 1]):
            seq_start -= 1

        i = seq_start
        while i < len(paras) and _is_bloomberg_header_line(paras[i]):
            i += 1
        if i < len(paras):
            start = i

    end = len(paras)
    for i in range(start, len(paras)):
        if _is_bloomberg_end_marker(paras[i]):
            end = i
            break

    cleaned = "\n\n".join(paras[start:end]).strip()
    return cleaned or original


_NING_ACTIVITY_ACTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?i)^posted\s+a\s+\w[\w -]*$"),
    re.compile(r"(?i)^posted\s+blog\s+posts?$"),
    re.compile(r"(?i)^updated\s+their$"),
    re.compile(r"(?i)^replied(?:\s+to)?$"),
    re.compile(r"(?i)^commented(?:\s+on)?$"),
    re.compile(r"(?i)^liked$"),
    re.compile(r"(?i)^shared$"),
]


def _strip_ning_activity_noise(text: str) -> str:
    """Trim wrapper text emitted by Ning activity feed HTML fragments.

    Keep the real story title / excerpt / reply text, but drop small action wrappers
    like "posted a video" and "1 more…".
    """
    original = _normalize_whitespace(text or "")
    paras = _split_paragraphs(original)
    if not paras:
        return ""

    def _is_more_link_line(p: str) -> bool:
        s = (p or "").strip()
        if not s:
            return True
        if re.fullmatch(r"(?i)see\s+more", s):
            return True
        if re.fullmatch(r"(?i)\d+\s+more(?:\.{3}|…)?", s):
            return True
        return False

    def _is_action_line(p: str) -> bool:
        s = (p or "").strip()
        return any(rx.fullmatch(s) for rx in _NING_ACTIVITY_ACTION_PATTERNS)

    def _looks_like_actor_name(p: str) -> bool:
        s = (p or "").strip()
        if not s or len(s) > 120:
            return False
        low = s.lower()
        # Avoid matching actual content/excerpts.
        if any(tok in low for tok in ("http://", "https://", "posted ", "replied", "commented", "updated ")):
            return False
        # Mostly name-ish text: letters/numbers/basic punctuation.
        return bool(re.fullmatch(r"[\w .,'’()&+\-†]+", s))

    cleaned = [p for p in paras if not _is_more_link_line(p)]

    # Remove a common Ning wrapper prefix:
    #   <actor name>
    #   posted a video / posted blog posts / updated their / ...
    # only when there is meaningful content after it.
    if len(cleaned) >= 4 and _looks_like_actor_name(cleaned[0]) and _is_action_line(cleaned[1]):
        # For profile updates with no real excerpt, keep the small text.
        tail = cleaned[2:]
        meaningful_tail = [p for p in tail if len((p or "").strip()) >= 12]
        if len(meaningful_tail) >= 2 or any(len((p or "").strip()) >= 40 for p in meaningful_tail):
            cleaned = tail

    # If the resulting first line is just "profile" and there is other content, drop it.
    if len(cleaned) > 1 and str(cleaned[0] or "").strip().lower() == "profile":
        cleaned = cleaned[1:]

    out = "\n\n".join(cleaned).strip()
    return out or original


def _postprocess_extracted_text(text: str, url: str) -> str:
    t = _normalize_whitespace(text or "")
    if not t:
        return ""

    netloc = ""
    try:
        netloc = (urlsplit(url or "").netloc or "").lower()
    except Exception:
        netloc = ""

    if netloc.endswith("zdnet.com"):
        t = _strip_zdnet_recommends_block(t)
    elif netloc.endswith("thetyee.ca"):
        t = _strip_thetyee_boilerplate(t)
    elif "9to5mac.com" in netloc:
        t = _strip_9to5mac_boilerplate(t)
    elif "9to5google.com" in netloc:
        t = _strip_9to5google_boilerplate(t)
    elif "9to5toys.com" in netloc:
        t = _strip_9to5toys_boilerplate(t)
    elif "thepostmillennial.com" in netloc:
        t = _strip_postmillennial_boilerplate(t)
    elif "globalnews.ca" in netloc:
        t = _strip_globalnews_boilerplate(t)
    elif "aljazeera.com" in netloc:
        t = _strip_aljazeera_boilerplate(t)
    elif "axios.com" in netloc:
        t = _strip_axios_boilerplate(t)
    elif "bbc.com" in netloc or "bbc.co.uk" in netloc:
        t = _strip_bbc_boilerplate(t)
    elif "wsj.com" in netloc:
        t = _strip_wsj_boilerplate(t)
    elif "techradar.com" in netloc:
        t = _strip_techradar_boilerplate(t)
    elif "o.canada.com" in netloc or "canada.com" in netloc:
        t = _strip_canada_boilerplate(t)
    elif "castanet.net" in netloc:
        t = _strip_castanet_boilerplate(t)
    elif "slashdot.org" in netloc:
        t = _strip_slashdot_boilerplate(t)
    elif "bloomberg.com" in netloc:
        t = _strip_bloomberg_boilerplate(t)
    elif netloc.endswith(".ning.com") or netloc == "ning.com":
        t = _strip_ning_activity_noise(t)

    return _normalize_whitespace(t)


@dataclass
class _FetchResult:
    """Outcome of fetching a page.

    `blocked` is True when the only response we could obtain was an anti-bot/verification
    interstitial. It is distinct from a plain download failure (offline, DNS, timeout) so the caller
    can surface a clearer "open in browser" message.
    """
    html: Optional[str] = None
    blocked: bool = False


def _download_via_jina(target_url: str, timeout: int) -> Optional[str]:
    try:
        target = re.sub(r"^https?://", "", (target_url or "").strip())
        if not target:
            return None
        jina_url = f"https://r.jina.ai/http://{target}"
        headers = {
            "Accept": "text/plain, text/markdown, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = utils.safe_requests_get(jina_url, timeout=timeout, headers=headers, allow_redirects=True)
        if 200 <= r.status_code < 400 and r.text:
            text = r.text
            marker = "Markdown Content:"
            if marker in text:
                text = text.split(marker, 1)[1].strip()
            return text
    except Exception:
        return None
    return None


# Fallback fetchers (full-text extraction should survive dead links and hard blocks).
#
# Live sources first (impersonated refetch, Jina, Smry) because the user wants the CURRENT page
# text, not a stale copy; the Wayback Machine is the last resort for dead links and older
# articles. See _fetch_page for the exact order. Services that were evaluated and DON'T work
# programmatically (verified 2026-07): Archive.today serves its own CAPTCHA to non-browser
# clients even with TLS impersonation; Google Cache was discontinued in 2024; 12ft.io is dead.
# Do not re-add them without re-verifying.
#
# Wayback Machine: the availability API returns the closest snapshot; the `id_` timestamp flag
# requests the raw original HTML without the Wayback toolbar/rewriting, which extracts much
# cleaner. Smry.ai: the SSE endpoint streams a Readability-style JSON article (its own upstream
# fetch can be bot-blocked too, so it is best-effort like everything here) — never raise.
_WAYBACK_SNAPSHOT_RE = re.compile(r"^(https?://web\.archive\.org/web/\d{4,14})(?:id_)?/(.+)$")

_SMRY_STREAM_API = "https://smry.ai/api/article/auto/stream?url={quoted}&uiLocale=en"
_SMRY_MIN_TEXT_LEN = 300
_SMRY_DATA_LINE_RE = re.compile(r"^data:\s*(\{.*)$", re.M)

_HTML_ACCEPT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _response_text(r) -> str:
    """Read a response body as text, tolerating curl_cffi's read-once encoding rule.

    curl_cffi raises ``ValueError`` if ``r.encoding`` is set after ``r.text`` has been accessed,
    so we set the encoding first (best-effort) and never touch it again. Returns "" on any error.
    """
    if r is None:
        return ""
    try:
        if not getattr(r, "encoding", None):
            try:
                r.encoding = "utf-8"
            except Exception:
                pass
        return r.text or ""
    except Exception:
        return ""


def _wayback_raw_url(snapshot_url: str) -> str:
    """Rewrite a Wayback snapshot URL to the raw (`id_`) form that skips the archive toolbar."""
    m = _WAYBACK_SNAPSHOT_RE.match((snapshot_url or "").strip())
    if not m:
        return snapshot_url
    return f"{m.group(1)}id_/{m.group(2)}"


def _download_via_wayback(target_url: str, timeout: int) -> Optional[str]:
    """Fetch the closest Internet Archive (Wayback Machine) snapshot of `target_url`."""
    try:
        api = "https://archive.org/wayback/available?url=" + quote(target_url, safe="")
        r = utils.safe_requests_get(api, timeout=timeout, allow_redirects=True)
        api_body = _response_text(r)
        if not (200 <= r.status_code < 300) or not api_body:
            return None
        data = json.loads(api_body)
        closest = ((data.get("archived_snapshots") or {}).get("closest") or {})
        snap = (closest.get("url") or "").strip()
        if not snap or not closest.get("available"):
            return None
        if snap.startswith("http://"):
            snap = "https://" + snap[len("http://"):]
        for candidate in (_wayback_raw_url(snap), snap):
            try:
                r2 = utils.safe_requests_get(
                    candidate, timeout=timeout, headers=dict(_HTML_ACCEPT_HEADERS), allow_redirects=True
                )
            except Exception:
                continue
            body = _response_text(r2)
            if 200 <= r2.status_code < 400 and body and not _looks_like_bot_interstitial(body):
                return body
    except Exception:
        return None
    return None


# Fingerprints for the impersonated live refetch, in order. Chrome first (the known-good
# target for feed WAFs, issue #29); Safari second because some Cloudflare-managed challenges
# 403 curl_cffi's Chrome/Firefox TLS hellos but pass its Safari one (verified live on
# neowin.net 2026-07: every chrome*/firefox* target got the challenge page, safari184 got
# the full article).
_IMPERSONATE_TARGETS = (None, "safari184")


def _download_via_impersonation(target_url: str, timeout: int) -> Optional[str]:
    """Refetch the LIVE page with a real-browser TLS/HTTP fingerprint (curl_cffi, issue #29).

    Many WAF gates (Neowin's "Performing security verification", Cloudflare, ...) only trigger on
    non-browser fingerprints, so this is the cheapest way to get the current page text.
    Degrades to a plain request when curl_cffi is unavailable (see utils.safe_requests_get).
    """
    # Without curl_cffi every target degrades to the same plain request; send it once only.
    targets = _IMPERSONATE_TARGETS if getattr(utils, "CURL_CFFI_AVAILABLE", False) else (None,)
    for target in targets:
        try:
            r = utils.safe_requests_get(
                target_url,
                timeout=timeout,
                headers=dict(_HTML_ACCEPT_HEADERS),
                allow_redirects=True,
                impersonate=True,
                impersonate_target=target,
            )
        except Exception:
            continue
        body = _response_text(r)
        if 200 <= r.status_code < 400 and body and not _looks_like_bot_interstitial(body):
            return body
    return None


def _download_via_smry(target_url: str, timeout: int) -> Optional[str]:
    """Fetch article content through Smry.ai's public reader endpoint.

    The endpoint answers with a server-sent-event stream; a successful extraction arrives as an
    `event: article` whose data line is a JSON object with a Readability-style `article` payload
    (title / byline / content HTML). Errors arrive as `event: error` — treated as failure.
    """
    try:
        api = _SMRY_STREAM_API.format(quoted=quote(target_url, safe=""))
        r = utils.safe_requests_get(
            api,
            timeout=timeout,
            headers={"Accept": "text/event-stream, application/json;q=0.9, */*;q=0.8"},
            allow_redirects=True,
        )
        sse = _response_text(r)
        if not (200 <= r.status_code < 300) or not sse:
            return None
        article = None
        for m in _SMRY_DATA_LINE_RE.finditer(sse):
            try:
                payload = json.loads(m.group(1))
            except Exception:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("article"), dict):
                article = payload["article"]
                break
        if not article:
            return None
        content = article.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        text_content = article.get("textContent")
        plain = text_content if isinstance(text_content, str) else re.sub(r"<[^>]+>", " ", content)
        if len(_normalize_whitespace(plain)) < _SMRY_MIN_TEXT_LEN:
            # Too short to be an article: likely a teaser, consent page, or extraction miss.
            return None
        title = article.get("title") if isinstance(article.get("title"), str) else ""
        byline = article.get("byline") if isinstance(article.get("byline"), str) else ""
        return (
            "<html><head>"
            f"<title>{html.escape(title)}</title>"
            f"<meta name=\"author\" content=\"{html.escape(byline)}\">"
            f"</head><body><article>{content}</article></body></html>"
        )
    except Exception:
        return None
    return None


def _download_sky_via_google_translate(target_url: str, timeout: int) -> Optional[str]:
    """Fetch a current Sky News article through Google's browser-facing web proxy.

    Sky's Akamai edge commonly returns a tiny 403 ``Access Denied`` page to plain requests and
    curl_cffi browser fingerprints even though the same article opens normally in Chrome.  The
    English-to-English Google Translate route fetches the live page (not a cached copy) and keeps
    the original article markup readable by the normal extraction pipeline.
    """
    try:
        parts = urlsplit((target_url or "").strip())
        if (parts.hostname or "").lower() != "news.sky.com":
            return None
        path = parts.path or "/"
        query = parts.query + ("&" if parts.query else "")
        query += "_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en"
        proxy_url = f"https://news-sky-com.translate.goog{path}?{query}"
        r = utils.safe_requests_get(
            proxy_url,
            timeout=timeout,
            headers=dict(_HTML_ACCEPT_HEADERS),
            allow_redirects=True,
        )
        body = _response_text(r)
        if 200 <= r.status_code < 400 and body and not _looks_like_bot_interstitial(body):
            return body
    except Exception:
        return None
    return None


def _fetch_page(url: str, timeout: int = 20) -> _FetchResult:
    """Fetch a page, treating anti-bot/verification interstitials as a (recoverable) block.

    Note: some gates (e.g. Bloomberg's "unusual activity" page) are served with HTTP 200, so the
    response body must be inspected even on a successful status code.

    Fallback chain when the direct fetch fails (live sources first — the user wants the CURRENT
    page text; the possibly-stale Wayback snapshot is the last resort):
    1. Sky News' live Google Translate route (Sky only);
    2. impersonated refetch of the live page (real-browser TLS fingerprint, beats most WAF gates);
    3. Jina read-proxy (live; gates only);
    4. Smry.ai reader (live);
    5. Wayback Machine snapshot.
    """
    if not url:
        return _FetchResult()

    is_bloomberg = _is_bloomberg_url(url)
    is_bloomberg_video = _is_bloomberg_video_url(url)
    tried_impersonation_first = False

    def _try_fallbacks(*, gate_seen: bool) -> _FetchResult:
        if is_bloomberg_video and gate_seen:
            return _FetchResult(blocked=True)
        # Every fallback body is re-checked for interstitials so a gate served by the fallback
        # itself (or archived by it) is never stored as article text.
        candidates: List[Callable[[], Optional[str]]] = []
        if (urlsplit(url).hostname or "").lower() == "news.sky.com":
            candidates.append(lambda: _download_sky_via_google_translate(url, timeout))
        if not tried_impersonation_first:
            candidates.append(lambda: _download_via_impersonation(url, timeout))
        if gate_seen:
            candidates.append(lambda: _download_via_jina(url, timeout))
        candidates.append(lambda: _download_via_smry(url, timeout))
        candidates.append(lambda: _download_via_wayback(url, timeout))
        for fetch in candidates:
            alt = fetch()
            if alt and not _looks_like_bot_interstitial(alt):
                return _FetchResult(html=alt)
        return _FetchResult(blocked=True) if gate_seen else _FetchResult()

    try:
        if is_bloomberg:
            tried_impersonation_first = True
            body = _download_via_impersonation(url, timeout)
            if body:
                return _FetchResult(html=body)

        r = utils.safe_requests_get(
            url, timeout=timeout, headers=dict(_HTML_ACCEPT_HEADERS), allow_redirects=True
        )
        if 200 <= r.status_code < 400:
            r.encoding = r.encoding or "utf-8"
            body = r.text or ""
            if _looks_like_bot_interstitial(body):
                return _try_fallbacks(gate_seen=True)
            return _FetchResult(html=body)
        try:
            if r is not None and (r.status_code in (403, 503) or _looks_like_bot_interstitial(r.text or "")):
                return _try_fallbacks(gate_seen=True)
        except Exception:
            pass
        return _try_fallbacks(gate_seen=False)
    except Exception:
        return _try_fallbacks(gate_seen=False)


def _download_html(url: str, timeout: int = 20) -> Optional[str]:
    """Download a URL and return HTML as text (None on failure or block)."""
    return _fetch_page(url, timeout=timeout).html


def _extract_title_author_from_meta(html: str, url: str) -> Tuple[str, str]:
    title = ""
    author = ""

    if trafilatura is not None and extract_metadata is not None and html:
        try:
            meta = extract_metadata(html, url=url)
            if meta:
                title = (meta.title or "") if hasattr(meta, "title") else ""
                author = (meta.author or "") if hasattr(meta, "author") else ""
        except Exception:
            pass

    if not title:
        try:
            soup = BeautifulSoup(html, "html.parser")
            t = soup.find("title")
            if t and t.get_text(strip=True):
                title = t.get_text(strip=True)
        except Exception:
            pass

    return (title or "").strip(), (author or "").strip()


def _trafilatura_extract_text(html: str, url: str = "") -> str:
    """Try to get the main article text using trafilatura.

    CPU considerations:
    - Prefer precision-first extraction to reduce boilerplate.
    - Only fall back to recall mode when the precision result is clearly too short.
    - For some sites, precision extraction may skip a lead/intro; in that case, try recall and
      prepend the missing intro paragraphs to the precision result.
    """
    if not html or trafilatura is None:
        return ""

    base_kwargs = dict(
        output_format="txt",
        include_comments=False,
        include_images=False,
        include_links=False,
        include_tables=False,
        deduplicate=True,
    )

    def _do_extract(extra_kwargs):
        try:
            return trafilatura.extract(
                html,
                url=url or None,
                **base_kwargs,
                **extra_kwargs,
            )
        except TypeError:
            # Older/newer trafilatura versions may not support all kwargs.
            safe_kwargs = dict(base_kwargs)
            safe_kwargs.update(extra_kwargs)
            for k in list(safe_kwargs.keys()):
                if k not in ("output_format", "include_comments", "include_images", "include_links", "include_tables", "deduplicate", "favor_recall", "favor_precision"):
                    safe_kwargs.pop(k, None)
            return trafilatura.extract(html, url=url or None, **safe_kwargs)
        except Exception:
            return ""

    # Precision-first
    txt_prec = _do_extract({"favor_precision": True, "favor_recall": False})
    prec = (txt_prec or "").strip()
    if prec and len(prec) >= _LEAD_RECOVERY_MIN_PRECISION_LEN:
        prec_norm = _normalize_for_match(prec)
        recovered = _attempt_lead_recovery(
            html,
            url,
            precision_text=prec,
            precision_norm=prec_norm,
            do_extract=_do_extract,
        )
        if recovered:
            return recovered

        return prec

    # Recall fallback (only when precision is empty/too short)
    txt_rec = _do_extract({"favor_recall": True})
    return (txt_rec or "").strip()


def _soup_extract_text(html: str) -> str:
    """Fallback: crude visible text extraction using BeautifulSoup."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        # remove obvious junk
        for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
            tag.decompose()
        # prefer main-ish containers
        main = soup.find("article") or soup.find("main")
        node = main if main else soup.body if soup.body else soup
        text = node.get_text("\n", strip=True)
        return (text or "").strip()
    except Exception:
        return ""


def _extract_article_paragraph_text(html: str) -> str:
    """Return visible article paragraphs suitable for JSON-LD lead comparison."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        node = soup.find("article") or soup.find("main")
        if node is None:
            return ""
        paras: List[str] = []
        for p in node.find_all("p"):
            text = _normalize_whitespace(p.get_text(" ", strip=True))
            text = re.sub(r"\s+([,.;:!?])", r"\1", text)
            if text:
                paras.append(text)
        return "\n\n".join(paras)
    except Exception:
        return ""


_LEAD_PATCH_MAX_SCAN_PARAS = 4
_LEAD_PATCH_MAX_LEAD_PARAS = 2
_LEAD_PATCH_ALIGN_SNIPPET_LEN = 60
_LEAD_PATCH_BASE_HEAD_CHARS = 400


def _prepend_missing_lead(base: str, alt: str) -> str:
    """Prepend lead paragraph(s) that only `alt` captured to `base`.

    `base` is the text we decided to keep (e.g. JSON-LD articleBody) and `alt` is the
    competing extraction (e.g. trafilatura). When `alt` opens with a couple of paragraphs
    that `base` lacks anywhere and then lines up with the very start of `base`, those
    opening paragraphs are a lede that `base`'s source dropped; re-attach them.
    """
    base_norm = _normalize_for_match(base)
    if not base_norm:
        return base
    base_head = base_norm[:_LEAD_PATCH_BASE_HEAD_CHARS]

    leads: List[str] = []
    aligned = False
    for p in _split_paragraphs(alt)[:_LEAD_PATCH_MAX_SCAN_PARAS]:
        pn = _normalize_for_match(p)
        if not pn:
            continue
        if pn[:_LEAD_PATCH_ALIGN_SNIPPET_LEN] in base_head:
            aligned = True
            break
        if pn in base_norm:
            # Present deeper in base, so base isn't simply missing its head; don't guess.
            break
        if len(leads) >= _LEAD_PATCH_MAX_LEAD_PARAS:
            break
        if not _is_reasonable_lead_paragraph(p):
            break
        leads.append(p)

    if not aligned or not leads:
        return base
    return _normalize_whitespace("\n\n".join(leads + [base]))


def _patch_json_ld_missing_lead(json_text: str, *alts: str) -> str:
    patched = _normalize_whitespace(json_text)
    for alt in alts:
        if alt:
            patched = _prepend_missing_lead(patched, _normalize_whitespace(alt))
    return patched


def _extract_text_any(html: str, url: str = "") -> str:
    # 0. Site-specific structured body (e.g. Axios __NEXT_DATA__). Some Axios page variants
    # ship no article body in the DOM, so trafilatura only finds related-story cards and the
    # "Add Axios as your preferred source ... on Google" promo; the CMS JSON always has the
    # real body, so it wins outright when present.
    site_txt = _extract_site_specific_text(html, url)
    if site_txt:
        return site_txt

    # 1. JSON-LD articleBody (often high quality on major sites), but never trusted alone:
    # some CMSes omit paragraphs from articleBody. Wired/Conde Nast drops the entire first
    # paragraph whenever the lede uses styled lead-in markup, so trafilatura always runs
    # and gets to supply a lede that JSON-LD is missing.
    json_txt = _extract_json_ld_text(html)

    # 2. Try Trafilatura
    txt = _trafilatura_extract_text(html, url=url)

    if txt and json_txt:
        txt_norm = _normalize_whitespace(txt)
        json_norm = _normalize_whitespace(json_txt)
        # If JSON-LD is significantly longer, prefer it, but re-attach any lead
        # paragraphs that only trafilatura captured.
        if len(json_norm) > len(txt_norm) * 1.1:
            return _patch_json_ld_missing_lead(
                json_norm,
                txt_norm,
                _extract_article_paragraph_text(html),
            )
        return txt_norm

    if json_txt:
        return _patch_json_ld_missing_lead(json_txt, _extract_article_paragraph_text(html))
    if txt:
        return _normalize_whitespace(txt)
    
    # 3. Last resort fallback
    txt = _soup_extract_text(html)
    return _normalize_whitespace(txt)


# Next-STORY navigation (a different article, not page 2 of this one). News sites mark these
# in anchor text ("Next Story"), classes, aria-labels, or data-* attributes — e.g. MacRumors
# uses data-track="next-article" on its next-article teaser.
_NEXT_STORY_NAV_RE = re.compile(r"next[\s_-]*(?:stor(?:y|ies)|articles?|posts?|read|up)\b")

# A genuine pagination control is a SHORT label ("Next", "Next Page", "Older", "Next »"...),
# never a full headline. Matching "next" as a substring anywhere in the anchor text made any
# next-story teaser whose headline contains "Next" (e.g. "Next Year's iPhone Air 2 to Feature
# Four Key Upgrades") look like pagination, merging an unrelated article into this one.
_PAGINATION_LABEL_RE = re.compile(r"(?:next|older)(?:\s+(?:page|pages|entries))?\s*(?:[›»>]+)?")


# Hosts where a single article is never truly paginated and "next" points at another story.
#   - slashdot.org: every story page has a "next story" button (?sdsrc=nextbtmnext) that points
#     at a DIFFERENT story — following it appended an unrelated article to every extraction, and
#     the newest story's button points at a malformed firehose.pl URL whose fallback fetch
#     returned the site's "YOUR PRIVACY CHOICES" OneTrust page as the final "page".
_NO_PAGINATION_FOLLOW_HOSTS = ("wired.com", "ning.com", "neowin.net", "bloomberg.com", "slashdot.org")


def _find_next_page(html: str, base_url: str) -> Optional[str]:
    """Return absolute next-page URL if present, else None."""
    if not html:
        return None

    try:
        # Hosts whose articles are single-page and whose "next" controls point at a DIFFERENT
        # story (not a continuation of this one), so following them merges unrelated text:
        #   - wired.com: "Next" links usually point to the next story.
        #   - ning.com: "next/older" controls navigate activity/thread listings.
        #   - neowin.net: abuses <link rel="next"> to point at the next article (verified: an Xbox
        #     report's rel=next pointed to an unrelated display-resolution science piece).
        try:
            host = (urlsplit(base_url).hostname or "").lower()
            if any(host == d or host.endswith("." + d) for d in _NO_PAGINATION_FOLLOW_HOSTS):
                return None
        except Exception:
            pass

        soup = BeautifulSoup(html, "html.parser")

        # 1) <link rel="next" href="...">
        link = soup.find("link", attrs={"rel": lambda v: v and "next" in (v if isinstance(v, list) else [v])})
        if link and link.get("href"):
            href = link.get("href").strip()
            if href:
                return urljoin(base_url, href)

        # 2) <a rel="next" href="...">
        a = soup.find("a", attrs={"rel": lambda v: v and "next" in (v if isinstance(v, list) else [v])})
        if a and a.get("href"):
            href = a.get("href").strip()
            if href:
                return urljoin(base_url, href)

        # 3) common "next" anchors/buttons
        for tag in soup.find_all("a", href=True):
            href = (tag.get("href") or "").strip()
            if not href:
                continue
            text = (tag.get_text(" ", strip=True) or "").lower()
            cls = " ".join(tag.get("class") or []).lower()
            aria = (tag.get("aria-label") or "").lower()

            # Avoid "Next Story"/"Next Article"/"Next Post" navigation, common on news
            # sites: the target is a DIFFERENT article. The marker can live in the text,
            # class, aria-label, or a data-* attribute (MacRumors: data-track="next-article").
            data_attrs = " ".join(
                " ".join(v) if isinstance(v, (list, tuple)) else str(v)
                for k, v in (tag.attrs or {}).items()
                if isinstance(k, str) and k.startswith("data-")
            ).lower()
            if _NEXT_STORY_NAV_RE.search(" ".join((text, cls, aria, data_attrs))):
                continue

            if (
                _PAGINATION_LABEL_RE.fullmatch(text)
                or text in (">", ">>", "›", "»")
                or "next" in cls
                or aria.startswith("next")
            ):
                absu = urljoin(base_url, href)
                # avoid obvious comment/share links
                if any(x in absu.lower() for x in ("facebook.com", "twitter.com", "x.com", "linkedin.com", "pinterest.com")):
                    continue
                return absu
    except Exception:
        return None

    return None


def _merge_texts(texts: List[str]) -> str:
    """Merge multiple page texts while de-duplicating repeated blocks."""
    seen: Set[str] = set()
    out: List[str] = []

    for t in texts:
        t = (t or "").strip()
        if not t:
            continue

        # de-dupe paragraph by paragraph
        paras = [p.strip() for p in t.split("\n") if p.strip()]
        merged_paras: List[str] = []
        for p in paras:
            key = re.sub(r"\s+", " ", p).strip().lower()
            if len(key) < 25:
                continue
            if key in seen:
                continue
            seen.add(key)
            merged_paras.append(p)

        if merged_paras:
            out.append("\n".join(merged_paras))

    return _normalize_whitespace("\n\n".join(out))


def extract_full_article(
    url: str, max_pages: int = 6, timeout: int = 20, metadata_sink=None
) -> Optional[FullArticle]:
    """
    Extract full article text from a URL. Attempts to follow pagination for multi-page articles.

    Returns FullArticle or None on unsupported/empty.
    Raises ExtractionError for download/extraction failures that should be shown to the user.

    ``metadata_sink``, when given, is called once with ``(html, page_url)`` of
    the FIRST successfully downloaded page so callers can harvest structured
    metadata (see core.metadata_enrich) from HTML we already paid to fetch.
    Sink errors are swallowed — they must never affect extraction.
    """
    url = (url or "").strip()
    if not url or _looks_like_media_url(url):
        return None
    if trafilatura is None:
        raise ExtractionError("trafilatura is not installed or failed to import. Reinstall requirements.")

    visited: Set[str] = set()
    page_texts: List[str] = []

    current = url
    title = ""
    author = ""

    downloaded_any = False
    blocked = False

    for _ in range(max_pages):
        if not current or current in visited:
            break
        visited.add(current)

        res = _fetch_page(current, timeout=timeout)
        if res.blocked:
            blocked = True
            break
        html = res.html
        if not html:
            break
        if not downloaded_any and metadata_sink is not None:
            try:
                metadata_sink(html, current)
            except Exception:
                pass
        downloaded_any = True

        if not title or not author:
            t, a = _extract_title_author_from_meta(html, current)
            if not title:
                title = t
            if not author:
                author = a

        page_texts.append(_extract_text_any(html, current))

        next_url = _find_next_page(html, current)
        if not next_url or next_url in visited:
            break
        current = next_url
        time.sleep(0.15)

    if not downloaded_any:
        if blocked:
            raise ExtractionError(_BLOCKED_INTERSTITIAL_MESSAGE)
        raise ExtractionError("Download failed (site blocked, offline, or connection problem).")

    merged = _merge_texts(page_texts)
    merged = _postprocess_extracted_text(merged, url)
    # Guard against gate text that slipped through extraction (e.g. a short verification body).
    if merged and len(merged) < _BOT_INTERSTITIAL_MAX_BODY_LEN and _looks_like_bot_interstitial(merged):
        raise ExtractionError(_BLOCKED_INTERSTITIAL_MESSAGE)
    if not merged:
        raise ExtractionError("Downloaded page, but could not extract readable text (empty result).")

    return FullArticle(url=url, title=title or "", author=author or "", text=merged)


def extract_from_html(html: str, source_url: str = "", title: str = "", author: str = "") -> Optional[FullArticle]:
    """
    Extract readable text from HTML already available in the feed item (fallback when no webpage URL exists).
    """
    html = (html or "").strip()
    if not html:
        return None
    text = _extract_text_any(html, source_url or "")
    text = _postprocess_extracted_text(text, source_url or "")
    if not text:
        return None

    # Prefer metadata extracted from HTML if present.
    t2, a2 = _extract_title_author_from_meta(html, source_url or "")
    final_title = (title or t2 or "").strip()
    final_author = (author or a2 or "").strip()

    return FullArticle(url=source_url or "", title=final_title, author=final_author, text=text)


def render_full_article(
    url: str,
    *,
    fallback_html: str = "",
    fallback_title: str = "",
    fallback_author: str = "",
    prefer_feed_content: bool = True,
    max_pages: int = 6,
    timeout: int = 20,
    metadata_sink=None,
) -> Optional[str]:
    """
    Render a full article into a single plain-text string (Title/Author/Text).

    Behavior:
    - If url is missing or looks like media, try fallback_html (feed content) and return that.
    - If url extraction fails, try fallback_html; if still fails, raise ExtractionError.
    - ``metadata_sink`` is forwarded to extract_full_article (first fetched
      page's HTML, for structured-metadata enrichment); it never affects output.
    """
    url = (url or "").strip()

    def _render(art: FullArticle) -> str:
        parts: List[str] = []
        parts.append(_("Title:") + f" {art.title.strip() or '(unknown)'}")
        parts.append(_("Author:") + f" {art.author.strip() or '(unknown)'}")
        parts.append("")
        body = _postprocess_extracted_text(art.text or "", url)
        parts.append(body.strip())
        return (_normalize_whitespace("\n".join(parts)) + "\n")

    # No usable URL: fall back to feed content.
    if not url or _looks_like_media_url(url):
        art = extract_from_html(fallback_html, "", title=fallback_title, author=fallback_author)
        if art:
            return _render(art)
        return None

    # Optimization: prefer feed content for known sites or if it looks complete
    if prefer_feed_content and _should_prefer_feed_content(url, fallback_html):
        art = extract_from_html(fallback_html, url, title=fallback_title, author=fallback_author)
        if art:
            return _render(art)

    # Try webpage extraction.
    extraction_error: Optional[ExtractionError] = None
    try:
        # Pass metadata_sink only when set: keeps compatibility with callers
        # (and tests) that substitute extract_full_article without the kwarg.
        if metadata_sink is not None:
            art = extract_full_article(url, max_pages=max_pages, timeout=timeout, metadata_sink=metadata_sink)
        else:
            art = extract_full_article(url, max_pages=max_pages, timeout=timeout)
        if art:
            if fallback_title and not art.title:
                art.title = fallback_title
            if fallback_author and not art.author:
                art.author = fallback_author
            return _render(art)
    except ExtractionError as e:
        # Remember why so we can surface it if there's no usable feed fallback either.
        extraction_error = e
    except Exception as e:
        raise ExtractionError(str(e) or "Unknown extraction error")

    # If URL extraction returned None, try fallback content.
    art = extract_from_html(fallback_html, url, title=fallback_title, author=fallback_author)
    if art:
        return _render(art)

    if extraction_error is not None:
        raise extraction_error
    raise ExtractionError("Could not extract full text from the webpage or from feed content.")


def _should_prefer_feed_content(url: str, html: str) -> bool:
    """Return True if we should use the feed content instead of scraping."""
    if not html:
        return False

    low = html.lower()
    if "unable to retrieve full-text content" in low:
        return False

    # Ning activity feeds often contain the only useful human-readable description/excerpt
    # (e.g. "posted a video", discussion reply text, etc.). Scraping the target page can
    # return generic profile/site boilerplate instead, especially for profile activity items.
    try:
        host = urlsplit(url).hostname or ""
        host = host.lower()
        if host.endswith(".ning.com") or host == "ning.com":
            # Most Ning RSS activity entries are HTML fragments (not full pages) containing
            # the only useful summary/reply text. If we scrape the linked page instead, we may
            # get profile/site boilerplate and lose the activity description entirely.
            if "<html" not in low and "<body" not in low:
                if low.count("<a ") >= 1 and any(
                    marker in low
                    for marker in (
                        "/forum/topics/",
                        "/xn/detail/",
                        "/members/",
                        "posted a ",
                        "posted blog posts",
                        "replied",
                        "updated their",
                        "commentid=",
                        "xg_source=activity",
                    )
                ):
                    return True
            if any(
                marker in low
                for marker in (
                    "xg_source=activity",
                    "feed-string",
                    "feed-story-title",
                    "feed-more",
                    "rich-excerpt",
                )
            ):
                return True
    except Exception:
        pass
    
    # 1. Known sites where scraping is slow/blocked but feed is good
    try:
        host = urlsplit(url).hostname
        if host:
            host = host.lower()
            if host == "wired.com" or host.endswith(".wired.com"):
                # Wired feeds are usually decent summaries or full text
                if len(html) > 300:
                    return True
            # These publishers expose a shortened webpage body while placing the
            # complete syndicated story/newsletter in RSS.
            if host == "fraservalleytoday.ca" or host.endswith(".fraservalleytoday.ca"):
                return len(html) > 500
            if host == "fvcurrent.com" or host.endswith(".fvcurrent.com"):
                return len(html) > 500
    except Exception:
        pass

    # 2. General heuristic: if the feed content is very long, it's likely full text.
    if len(html) > 2500:
        return True
    
    return False
