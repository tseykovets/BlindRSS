# Fix for Volume Jump on First Adjustment

## Problem Description

When adjusting the volume for the first time after starting playback, the
volume would jump a large amount (typically down) instead of moving one step
from the current audible level. After that first adjustment, everything
behaved normally.

## Root Cause

libvlc **silently drops** `audio_set_volume()` calls made before the audio
output exists, and the audio output is only created once the stream actually
**produces audio**. For a local file that is a few hundred milliseconds after
`play()`; for a podcast stream over HTTP (redirect chains, range-cache proxy
warm-up, `network-caching`) it is routinely **several seconds**.

So the startup sequence was:

```
Config says: volume = 40%
play() called; audio_set_volume(40) -> dropped (no audio output yet)
VLC plays at its own default volume (e.g. 100%)   <- what the user hears
self.volume = 40                                   <- what BlindRSS tracks
First Volume Down: set_volume_percent(40 - 5) -> VLC jumps 100% -> 35%
```

## History

1. First attempt: `_sync_volume_from_vlc()` — 500ms after play, read VLC's
   actual volume and adopt it. Failed because at +500ms the output often
   still didn't exist (readback -1, sync did nothing), and even when it
   worked it surrendered the configured volume to VLC's default.
2. Second attempt: `_apply_volume_when_ready()` — impose the tracked volume
   with readback confirmation, retrying every 250ms **up to 12 attempts
   (~3s)**. Fixed local files, but slow HTTP streams stay in `Opening` past
   3s: the budget expired before the output existed, nothing ever applied
   the volume, and the first adjustment still jumped. This was verified
   empirically by metering the Windows audio session while the real
   `PlayerFrame` played a tone through a deliberately slow local HTTP server:
   all 12 attempts returned -1 and died while the stream was still buffering.

## Current Solution (two layers)

1. **Seed the output modules' startup volume** (`_init_vlc`): pass
   `--directx-volume` / `--mmdevice-volume` (the two audio outputs BlindRSS
   uses) at `vlc.Instance()` creation, derived from the configured volume.
   The audio output then *opens* at the configured level, whenever that
   happens — the first audible sample is already right, even before any
   `audio_set_volume()` can succeed. This also removes the brief
   full-volume blast at the start of the first track (the old code played
   up to ~600ms at VLC's default before the retry loop corrected it —
   audible in the session peak meter as 0.040 vs the expected 0.0026).

2. **No fixed retry budget** (`_apply_volume_when_ready`): retry every 250ms
   for as long as the playback attempt is alive (`Opening`/`Buffering`/
   `Playing`/`Paused`), stopping on `Ended`/`Error`/`Stopped` or after a
   120s safety cap. Each call bumps `_apply_volume_seq`; pending retries
   from an older track load/resume see a newer sequence and abort, so loops
   never stack or fight. Only when the output exists but refuses our volume
   8 times in a row (exotic aout) do we adopt VLC's actual volume so
   adjustments stay relative to what the user hears.

Called from both `_play_url_in_vlc()` (initial playback) and `play()`
(resume) — the resume path also covers volume changed while paused, which
`set_volume_percent` deliberately does not push to VLC (pushing it would
unpause playback). Volume changed while a stream is still buffering is
covered too: the loop is still alive then and imposes the latest
`self.volume` once the output appears.

## Testing

`tests/test_volume_sync.py` covers: applying the configured volume once the
output becomes ready, surviving buffering far past the old 12-attempt budget,
stopping when the playback attempt dies, a newer attempt superseding pending
retries from an older one, the adopt-VLC fallback (bounded), casting
early-return, and exception safety.

Manual check: set volume to 40%, restart, play an episode from a slow feed,
immediately press Volume Down once — the volume should go 40% → 35%, and the
first seconds of audio should already be at 40%, not loud.
