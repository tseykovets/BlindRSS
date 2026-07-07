from core import equalizer as eq


def test_flat_config_shape():
    c = eq.flat_config()
    assert c["enabled"] is False
    assert c["preamp"] == 0.0
    assert len(c["bands"]) == eq.BAND_COUNT
    assert all(b == 0.0 for b in c["bands"])
    assert eq.is_flat(c)


def test_normalize_clamps_and_pads():
    c = eq.normalize_config({"enabled": 1, "preamp": 99, "bands": [50, -50, 3]})
    assert c["enabled"] is True
    assert c["preamp"] == eq.AMP_MAX
    assert c["bands"][0] == eq.AMP_MAX
    assert c["bands"][1] == eq.AMP_MIN
    assert c["bands"][2] == 3.0
    # padded to full band count with zeros
    assert len(c["bands"]) == eq.BAND_COUNT
    assert c["bands"][3] == 0.0


def test_normalize_bad_input():
    c = eq.normalize_config(None)
    assert c == eq.flat_config()
    c2 = eq.normalize_config({"bands": "nonsense", "preamp": "x"})
    assert c2["preamp"] == 0.0
    assert len(c2["bands"]) == eq.BAND_COUNT


def test_extra_bands_truncated():
    c = eq.normalize_config({"bands": list(range(20))})
    assert len(c["bands"]) == eq.BAND_COUNT


def test_is_flat_detects_nonflat():
    assert not eq.is_flat({"bands": [0, 0, 5, 0, 0, 0, 0, 0, 0, 0]})
    assert not eq.is_flat({"preamp": 2.0})
