"""Pure helpers for the media-player equalizer config.

The libVLC calls live in the GUI/player layer; this module only normalizes and
clamps the persisted config so it stays testable without vlc.

Config shape (stored in config.json under "equalizer"):

    {
        "enabled": bool,
        "preamp": float,          # dB, clamped to [AMP_MIN, AMP_MAX]
        "bands": [float, ...],    # BAND_COUNT gains in dB, each clamped
        "preset": str | None,     # name of the last applied preset, for the UI
    }
"""
from __future__ import annotations

from typing import Dict, List, Optional

# libVLC's equalizer exposes a fixed 10-band graphic EQ. Amps clamp to VLC's
# documented [-20, +20] dB range.
BAND_COUNT = 10
AMP_MIN = -20.0
AMP_MAX = 20.0

# The center frequencies libVLC uses for its 10 bands (Hz), for display only.
BAND_FREQUENCIES = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000]


def clamp_amp(value) -> float:
    try:
        v = float(value)
    except Exception:
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(AMP_MIN, min(AMP_MAX, round(v, 1)))


def flat_config() -> Dict:
    return {
        "enabled": False,
        "preamp": 0.0,
        "bands": [0.0] * BAND_COUNT,
        "preset": None,
    }


def normalize_config(cfg: Optional[Dict]) -> Dict:
    """Coerce arbitrary input into a well-formed, clamped equalizer config."""
    if not isinstance(cfg, dict):
        return flat_config()

    bands_in = cfg.get("bands")
    bands: List[float] = []
    if isinstance(bands_in, (list, tuple)):
        for v in bands_in[:BAND_COUNT]:
            bands.append(clamp_amp(v))
    while len(bands) < BAND_COUNT:
        bands.append(0.0)

    preset = cfg.get("preset")
    preset = str(preset) if isinstance(preset, str) and preset.strip() else None

    return {
        "enabled": bool(cfg.get("enabled", False)),
        "preamp": clamp_amp(cfg.get("preamp", 0.0)),
        "bands": bands,
        "preset": preset,
    }


def is_flat(cfg: Optional[Dict]) -> bool:
    c = normalize_config(cfg)
    return c["preamp"] == 0.0 and all(b == 0.0 for b in c["bands"])
