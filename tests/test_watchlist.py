from __future__ import annotations
from pathlib import Path

from scripts.watchlist import (
    ChannelEntry, Defaults, Watchlist, EffectiveConfig,
    load_watchlist, save_watchlist,
)


def test_empty_yaml_returns_baseline_defaults(tmp_path: Path):
    p = tmp_path / "watchlist.yaml"
    p.write_text("")
    wl = load_watchlist(p)
    assert wl.defaults == Defaults(lookback_days=7, top_k=5)
    assert wl.channels == []


def test_load_with_channels_and_overrides(tmp_path: Path):
    p = tmp_path / "watchlist.yaml"
    p.write_text(
        "defaults:\n"
        "  lookback_days: 10\n"
        "  top_k: 3\n"
        "channels:\n"
        "  - url: https://www.youtube.com/@a\n"
        "    alias: ay\n"
        "  - url: https://www.youtube.com/@b\n"
        "    lookback_days: 14\n"
    )
    wl = load_watchlist(p)
    assert wl.defaults.lookback_days == 10
    assert wl.defaults.top_k == 3
    assert len(wl.channels) == 2
    assert wl.channels[0].alias == "ay"
    assert wl.channels[1].lookback_days == 14


def test_effective_config_uses_defaults_when_unset(tmp_path: Path):
    wl = Watchlist(
        defaults=Defaults(lookback_days=7, top_k=5),
        channels=[
            ChannelEntry(url="u1", alias=None, lookback_days=None, top_k=None),
            ChannelEntry(url="u2", alias="b", lookback_days=14, top_k=3),
        ],
    )
    assert wl.effective(wl.channels[0]) == EffectiveConfig(lookback_days=7, top_k=5)
    assert wl.effective(wl.channels[1]) == EffectiveConfig(lookback_days=14, top_k=3)


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "watchlist.yaml"
    original = Watchlist(
        defaults=Defaults(lookback_days=14, top_k=4),
        channels=[
            ChannelEntry(url="https://www.youtube.com/@x", alias="X",
                         lookback_days=None, top_k=None),
            ChannelEntry(url="https://www.youtube.com/@y", alias=None,
                         lookback_days=21, top_k=2),
        ],
    )
    save_watchlist(p, original)
    assert load_watchlist(p) == original


def test_add_remove_channel(tmp_path: Path):
    wl = Watchlist(defaults=Defaults(), channels=[])
    wl.add_channel(ChannelEntry(url="https://www.youtube.com/@a", alias=None,
                                lookback_days=None, top_k=None))
    assert len(wl.channels) == 1
    wl.add_channel(ChannelEntry(url="https://www.youtube.com/@a", alias="dup",
                                lookback_days=None, top_k=None))
    assert len(wl.channels) == 1  # 중복 URL은 무시 (no-op)
    wl.remove_channel("https://www.youtube.com/@a")
    assert wl.channels == []
