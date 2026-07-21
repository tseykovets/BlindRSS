"""Shared test-suite guards.

The full-text and feed paths both escalate to `core.browser_feed`, which starts a
real (serialized, several-second) Chromium session. A unit test that mocks HTTP
would otherwise sail past its mock into that launch and hit the live network, so
the escalation is disabled for the whole suite. Tests that exercise the browser
fallback deliberately can monkeypatch `core.browser_feed` themselves.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_real_browser_launch(monkeypatch):
    try:
        from core import browser_feed
    except Exception:
        return
    monkeypatch.setattr(
        browser_feed,
        "_fetch_browser_document",
        lambda *args, **kwargs: None,
        raising=False,
    )
