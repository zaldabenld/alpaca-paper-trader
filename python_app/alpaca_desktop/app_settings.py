"""App-wide settings shared by every account (the daily list's timing and lookback, the stream size)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from . import universe as rvol_universe

DEFAULT_MARKET_STREAM_SYMBOL_LIMIT = 30  # free IEX plan maximum


class AppWideSettings(BaseModel):
    daily_pick_minutes_after_open: int = rvol_universe.PICK_AFTER_OPEN_MINUTES
    daily_recheck_minutes: int = rvol_universe.RECHECK_SECONDS // 60
    rvol_lookback_sessions: int = rvol_universe.LOOKBACK_SESSIONS
    rvol_min_sessions: int = rvol_universe.MIN_SESSIONS
    market_stream_symbol_limit: int = DEFAULT_MARKET_STREAM_SYMBOL_LIMIT

    def model_post_init(self, __context: Any) -> None:
        self.daily_pick_minutes_after_open = min(max(int(self.daily_pick_minutes_after_open), 1), 120)
        self.daily_recheck_minutes = min(max(int(self.daily_recheck_minutes), 5), 240)
        self.rvol_lookback_sessions = min(max(int(self.rvol_lookback_sessions), 5), 60)
        self.rvol_min_sessions = min(max(int(self.rvol_min_sessions), 1), self.rvol_lookback_sessions)
        self.market_stream_symbol_limit = min(max(int(self.market_stream_symbol_limit), 1), 500)

    def list_params(self) -> dict[str, int]:
        return {
            "pick_minutes_after_open": self.daily_pick_minutes_after_open,
            "recheck_seconds": self.daily_recheck_minutes * 60,
            "lookback_sessions": self.rvol_lookback_sessions,
            "min_sessions": self.rvol_min_sessions,
        }
