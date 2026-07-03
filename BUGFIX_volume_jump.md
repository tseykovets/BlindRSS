# Fix for Volume Jump on First Adjustment

## Problem Description

When adjusting the volume for the first time after starting playback, the
volume would jump a large amount (typically down) instead of moving one step
from the current audible level. After that first adjustment, everything
behaved normally.

## Root Cause

libvlc **silently drops** `audio_set_volume()` calls made before the audio
output exists. Playback start is exactly that window: `play()` returns
immediately, the audio output is created asynchronously a moment later.

So the startup sequence was:

```
Config says: volume = 40%
play() called; audio_set_volume(40) -> dropped (no audio output yet)
VLC plays at its own default volume (e.g. 100%)   <- what the user hears
self.volume = 40                                   <- what BlindRSS tracks
First Volume Down: set_volume_percent(40 - 5) -> VLC jumps 100% -> 35%
```

## History

A first fix attempt added `_sync_volume_from_vlc()`: 500ms after play, read
VLC's actual volume and adopt it as the tracked value. That had two flaws:

1. At +500ms the audio output often *still* doesn't exist —
   `audio_get_volume()` returns -1 and the sync silently does nothing,
   leaving the mismatch in place (the reported bug).
2. Even when it worked, it surrendered: the configured volume was thrown
   away and VLC's default won.

## Current Solution

`_apply_volume_when_ready()` (gui/player.py) **imposes** the tracked volume
instead of adopting VLC's:

1. Try `audio_set_volume(self.volume)` and confirm via `audio_get_volume()`.
2. If the output isn't ready (set rejected or readback mismatch), retry every
   250ms, up to 12 attempts (~3s).
3. Only if the volume never sticks (exotic audio output), adopt VLC's actual
   volume as the tracked value so adjustments stay relative to what the user
   hears.

Called from both `_play_url_in_vlc()` (initial playback) and `play()`
(resume) — the resume path also covers volume changed while paused, which
`set_volume_percent` deliberately does not push to VLC (pushing it would
unpause playback).

## Testing

`tests/test_volume_sync.py` covers: applying the configured volume once the
output becomes ready after several failed attempts, the immediate-success
path, the adopt-VLC fallback, casting early-return, and exception safety.

Manual check: set volume to 40%, restart, play an episode, immediately press
Volume Down once — the volume should go 40% → 35%, not jump from loud.
