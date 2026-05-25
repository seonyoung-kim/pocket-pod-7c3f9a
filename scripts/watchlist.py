from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Defaults:
    lookback_days: int = 7
    top_k: int = 5


@dataclass
class ChannelEntry:
    url: str
    alias: str | None = None
    lookback_days: int | None = None
    top_k: int | None = None


@dataclass(frozen=True)
class EffectiveConfig:
    lookback_days: int
    top_k: int


@dataclass
class Watchlist:
    defaults: Defaults = field(default_factory=Defaults)
    channels: list[ChannelEntry] = field(default_factory=list)

    def effective(self, ch: ChannelEntry) -> EffectiveConfig:
        return EffectiveConfig(
            lookback_days=ch.lookback_days or self.defaults.lookback_days,
            top_k=ch.top_k or self.defaults.top_k,
        )

    def add_channel(self, ch: ChannelEntry) -> None:
        if any(c.url == ch.url for c in self.channels):
            return
        self.channels.append(ch)

    def remove_channel(self, url: str) -> None:
        self.channels = [c for c in self.channels if c.url != url]

    def to_dict(self) -> dict:
        return {
            "defaults": {
                "lookback_days": self.defaults.lookback_days,
                "top_k": self.defaults.top_k,
            },
            "channels": [
                {k: v for k, v in {
                    "url": c.url,
                    "alias": c.alias,
                    "lookback_days": c.lookback_days,
                    "top_k": c.top_k,
                }.items() if v is not None}
                for c in self.channels
            ],
        }


def load_watchlist(path: Path) -> Watchlist:
    if not path.exists():
        return Watchlist()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    d = raw.get("defaults") or {}
    defaults = Defaults(
        lookback_days=int(d.get("lookback_days", 7)),
        top_k=int(d.get("top_k", 5)),
    )
    channels = [
        ChannelEntry(
            url=c["url"],
            alias=c.get("alias"),
            lookback_days=c.get("lookback_days"),
            top_k=c.get("top_k"),
        )
        for c in (raw.get("channels") or [])
    ]
    return Watchlist(defaults=defaults, channels=channels)


def save_watchlist(path: Path, wl: Watchlist) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(wl.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)
