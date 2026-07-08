from core.config import DEFAULT_CONFIG
from core.vlc_options import build_vlc_instance_args


def test_default_preferred_soundcard_is_system_default():
    assert DEFAULT_CONFIG.get("preferred_soundcard", None) == ""


def test_shared_instance_uses_wasapi_not_directsound():
    """set_rate() on the directsound aout drained/rebuilt the output, silencing
    audio for 0.2-3s on every playback-speed step; mmdevice measured gapless
    for small steps. Keep the shared instance on WASAPI."""
    from core import vlc_instance

    class _Cfg:
        def get(self, key, default=None):
            return default

    args = vlc_instance._build_args(_Cfg())
    assert "--aout=mmdevice" in args
    assert not any(a.startswith("--aout=directsound") for a in args)


def test_vlc_instance_args_disable_plugin_cache():
    args = build_vlc_instance_args("--no-video", "--no-video", "--aout=directsound")

    assert args[0] == "--no-plugins-cache"
    assert args.count("--no-plugins-cache") == 1
    assert args.count("--no-video") == 1
    assert "--aout=directsound" in args
