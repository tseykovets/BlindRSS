import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _Config:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


class _StopAfterTick:
    def __init__(self, wait_results=None):
        self.wait_results = list(wait_results or [True])
        self.wait_intervals = []

    def is_set(self):
        return False

    def wait(self, interval):
        self.wait_intervals.append(interval)
        if self.wait_results:
            return self.wait_results.pop(0)
        return True


class _TickProvider:
    """Provider stub exposing only scheduled_refresh_tick."""

    def __init__(self, tick=None):
        self._tick = tick

    def scheduled_refresh_tick(self, global_interval_s):
        return self._tick if self._tick is not None else global_interval_s


class _RefreshLoopHost:
    refresh_loop = mainframe.MainFrame.refresh_loop
    _scheduled_refresh_tick_seconds = mainframe.MainFrame._scheduled_refresh_tick_seconds

    def __init__(self, *, refresh_on_startup=True, interval=30, wait_results=None, provider_tick=None):
        self.config_manager = _Config(
            {
                "refresh_on_startup": refresh_on_startup,
                "refresh_interval": interval,
            }
        )
        self.stop_event = _StopAfterTick(wait_results)
        self.refresh_calls = []
        self.provider = _TickProvider(provider_tick)

    def _run_refresh(self, block, force=False, scheduled=False):
        self.refresh_calls.append(
            {"block": bool(block), "force": bool(force), "scheduled": bool(scheduled)}
        )
        return True


def test_refresh_loop_runs_startup_refresh_without_force_when_enabled():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=30, wait_results=[True])

    host.refresh_loop()

    assert host.refresh_calls == [{"block": False, "force": False, "scheduled": False}]


def test_refresh_loop_periodic_refresh_is_not_forced_after_startup():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=30, wait_results=[False, True])

    host.refresh_loop()

    assert host.refresh_calls == [
        {"block": False, "force": False, "scheduled": False},
        {"block": False, "force": False, "scheduled": True},
    ]


def test_refresh_loop_startup_disabled_waits_then_uses_normal_refresh():
    host = _RefreshLoopHost(refresh_on_startup=False, interval=30, wait_results=[False, True])

    host.refresh_loop()

    assert host.stop_event.wait_intervals[0] == 30
    # Startup refresh was skipped, so the first actual refresh is an ordinary
    # scheduled tick (per-feed intervals apply; a fresh provider has no
    # recorded attempts, so every feed is due anyway).
    assert host.refresh_calls == [{"block": False, "force": False, "scheduled": True}]


def test_refresh_loop_uses_provider_tick_for_sleep_interval():
    # A per-feed override shorter than the global interval shortens the loop tick.
    host = _RefreshLoopHost(
        refresh_on_startup=True, interval=300, wait_results=[False, True], provider_tick=60
    )

    host.refresh_loop()

    assert host.stop_event.wait_intervals == [60, 60]


def test_refresh_loop_falls_back_to_global_interval_without_provider_support():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=45, wait_results=[True])
    host.provider = object()  # no scheduled_refresh_tick

    host.refresh_loop()

    assert host.stop_event.wait_intervals == [45]
