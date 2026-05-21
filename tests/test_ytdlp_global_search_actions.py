import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.dialogs as dialogs


class _Host:
    _get_selected_action_availability = dialogs.YtdlpGlobalSearchDialog._get_selected_action_availability

    def __init__(self, item):
        self._item = item

    def _get_selected_result(self):
        return self._item


class _StatusLabel:
    def __init__(self):
        self.label = ""

    def SetLabel(self, label):
        self.label = label


class _SearchResultsHost:
    _on_site_search_results = dialogs.YtdlpGlobalSearchDialog._on_site_search_results
    _result_key_for_item = dialogs.YtdlpGlobalSearchDialog._result_key_for_item

    def __init__(self):
        self._stop_event = None
        self._completed_sites = 0
        self._total_sites = 0
        self._seen_result_keys = set()
        self._result_arrival_counter = 0
        self._all_results = []
        self._search_generation = 1
        self.status_lbl = _StatusLabel()
        self.refresh_scheduled = False
        self.enrichment_requests = []

    def _schedule_results_refresh(self):
        self.refresh_scheduled = True

    def _queue_title_enrichment(self, item, generation):
        self.enrichment_requests.append((item, generation))


def test_selected_action_availability_when_result_has_play_and_subscribe_targets():
    host = _Host(
        {
            "url": "https://example.com/watch/1",
            "native_subscribe_url": "https://example.com/feed.xml",
            "source_subscribe_url": "",
        }
    )

    assert host._get_selected_action_availability() == (True, True, True)


def test_selected_action_availability_when_nothing_is_selected():
    host = _Host(None)
    assert host._get_selected_action_availability() == (False, False, False)


def test_site_search_results_do_not_auto_queue_title_enrichment():
    host = _SearchResultsHost()
    items = [
        {
            "title": "YouTube video abc123",
            "url": "https://www.youtube.com/watch?v=abc123",
            "site_id": "yvsearch",
            "_title_is_fallback": True,
        }
    ]

    host._on_site_search_results({"id": "yvsearch", "label": "Yahoo Video"}, items, 1, 1)

    assert len(host._all_results) == 1
    assert host.refresh_scheduled is True
    assert host.enrichment_requests == []
