"""What a ticker is: company name, exchange and trading flags from the broker's asset record.

The dashboard shows this in the ticker lookup and when the mouse rests on a symbol. This module
is pure logic; the TraderManager owns fetching and caching.
"""
from __future__ import annotations

from typing import Any

FOUND_CACHE_SECONDS = 12 * 60 * 60
MISSING_CACHE_SECONDS = 5 * 60
CACHE_LIMIT = 2000

EXCHANGE_NAMES = {
    "NASDAQ": "Nasdaq",
    "NYSE": "NYSE",
    "ARCA": "NYSE Arca",
    "AMEX": "NYSE American",
    "BATS": "Cboe BZX",
    "OTC": "OTC",
    "CRYPTO": "Crypto",
}
ASSET_CLASS_NAMES = {"us_equity": "US equity", "us_option": "US option", "crypto": "Crypto"}


def missing(symbol: str) -> dict[str, Any]:
    return {"symbol": symbol, "found": False, "name": "", "exchange": "", "tags": [], "summary": ""}


def asset_summary(symbol: str, raw: dict[str, Any]) -> dict[str, Any]:
    """The display fields for one asset record. Leaves out the record's ids."""
    name = str(raw.get("name") or "").strip()
    exchange_code = str(raw.get("exchange") or "").strip().upper()
    exchange = EXCHANGE_NAMES.get(exchange_code, exchange_code)
    asset_class = ASSET_CLASS_NAMES.get(str(raw.get("asset_class") or raw.get("class") or "").strip().lower(), "")
    status = str(raw.get("status") or "").strip().lower()
    attributes = {str(item).strip().lower() for item in (raw.get("attributes") or [])}

    tags: list[str] = []
    if status and status != "active":
        tags.append(status.capitalize())
    if raw.get("tradable") is False:
        tags.append("Not tradable")
    if raw.get("fractionable") is True:
        tags.append("Fractionable")
    elif raw.get("fractionable") is False:
        tags.append("Whole shares only")
    if raw.get("shortable") is True:
        tags.append("Shortable")
    if raw.get("marginable") is True:
        tags.append("Marginable")
    if "has_options" in attributes or "options_enabled" in attributes:
        tags.append("Has options")

    return {
        "symbol": symbol,
        "found": bool(name or exchange),
        "name": name,
        "exchange": exchange,
        "asset_class": asset_class,
        "tags": tags,
        "summary": " · ".join(part for part in (exchange, asset_class) if part),
    }
