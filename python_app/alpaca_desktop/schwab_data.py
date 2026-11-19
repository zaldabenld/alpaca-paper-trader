"""Schwab market data, read only, logged next to the Alpaca IEX snapshot so the two can be compared.

Nothing here can place an order. The Schwab app is a Market Data Production app, and this module
only calls Schwab's login (OAuth) endpoints and the quotes endpoint. Nothing in the trade engine
reads the comparison log: stock ranking, entries, exits and sizing still use Alpaca data only.

Saved state lives in `schwab-credentials.json` in the app folder. The app key, secret and both
tokens are DPAPI-protected on Windows the same way the Alpaca keys are (storage.protect_text); the
callback URL and expiry times are plain (on Linux there is no DPAPI: values are base64 in an
owner-only file, like the Alpaca keys). Keys and login are entered in the app's settings screen
(App-wide, "Schwab market data"). Schwab access tokens last 30 minutes and are refreshed here; the
refresh token lasts 7 days, after which the login has to be done again from that screen.

Each comparison is one JSON line in `schwab_compare/<session date>.jsonl`, written only while the
Alpaca market clock says the market is open, at most once per COMPARE_INTERVAL_SECONDS.
"""

from __future__ import annotations

import base64
import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import storage

AUTHORIZE_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
QUOTES_URL = "https://api.schwabapi.com/marketdata/v1/quotes"
DEFAULT_CALLBACK_URL = "https://127.0.0.1"
CREDENTIALS_FILE = "schwab-credentials.json"
COMPARE_DIR_NAME = "schwab_compare"
FILE_VERSION = 1
QUOTE_BATCH_SIZE = 50
ACCESS_REFRESH_MARGIN_SECONDS = 120
REFRESH_TOKEN_LIFETIME_SECONDS = 7 * 24 * 60 * 60
COMPARE_INTERVAL_SECONDS = 55
HTTP_TIMEOUT_SECONDS = 15
MARKET_TIMEZONE = ZoneInfo("America/New_York")

HttpFunc = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]


class SchwabError(RuntimeError):
    pass


class SchwabLoginNeeded(SchwabError):
    """No saved login, or the 7-day refresh token has expired or been revoked."""


def credentials_path() -> Path:
    return storage.APP_DIR / CREDENTIALS_FILE


def compare_dir() -> Path:
    return storage.APP_DIR / COMPARE_DIR_NAME


def _urllib_http(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https URLs
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"raw": raw[:200].decode("utf-8", "replace")}
    return status, payload


def _failure(prefix: str, status: int, payload: Any) -> str:
    detail = _error_text(payload)
    return f"{prefix} ({status}: {detail})." if detail else f"{prefix} ({status})."


def _error_text(payload: Any) -> str:
    # Schwab error bodies name the problem ("invalid_grant", "unsupported_token_type"); never echo
    # anything that could be a token.
    if isinstance(payload, dict):
        for key in ("error_description", "error", "message", "errors"):
            value = payload.get(key)
            if value:
                return str(value)[:200]
    return ""


class SchwabClient:
    """Saved Schwab login plus the two calls this app makes: token refresh and quotes."""

    def __init__(self, http: HttpFunc | None = None, now: Callable[[], float] | None = None) -> None:
        self.http = http or _urllib_http
        self.now = now or time.time
        self.lock = threading.Lock()

    # Saved state -----------------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        path = credentials_path()
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SchwabError(f"{path.name} is not a JSON object.")
        return {
            "app_key": storage.unprotect_text(str(raw.get("app_key") or "")),
            "app_secret": storage.unprotect_text(str(raw.get("app_secret") or "")),
            "callback_url": str(raw.get("callback_url") or DEFAULT_CALLBACK_URL),
            "access_token": storage.unprotect_text(str(raw.get("access_token") or "")),
            "refresh_token": storage.unprotect_text(str(raw.get("refresh_token") or "")),
            "access_expires_at": float(raw.get("access_expires_at") or 0),
            "refresh_issued_at": float(raw.get("refresh_issued_at") or 0),
        }

    def save(self, state: dict[str, Any]) -> None:
        storage.write_private_json(
            credentials_path(),
            {
                "version": FILE_VERSION,
                "app_key": storage.protect_text(str(state.get("app_key") or "")),
                "app_secret": storage.protect_text(str(state.get("app_secret") or "")),
                "callback_url": str(state.get("callback_url") or DEFAULT_CALLBACK_URL),
                "access_token": storage.protect_text(str(state.get("access_token") or "")),
                "refresh_token": storage.protect_text(str(state.get("refresh_token") or "")),
                "access_expires_at": float(state.get("access_expires_at") or 0),
                "refresh_issued_at": float(state.get("refresh_issued_at") or 0),
            },
        )

    def configured(self) -> bool:
        return credentials_path().exists()

    def status(self) -> dict[str, Any]:
        """What is saved, without any secret values."""
        state = self.load()
        now = self.now()
        refresh_expires_at = state.get("refresh_issued_at", 0) + REFRESH_TOKEN_LIFETIME_SECONDS if state else 0
        return {
            "saved": bool(state),
            "has_app_key": bool(state.get("app_key")),
            "has_app_secret": bool(state.get("app_secret")),
            "callback_url": state.get("callback_url", ""),
            "logged_in": bool(state.get("refresh_token")) and refresh_expires_at > now,
            "login_expires_at": (
                datetime.fromtimestamp(refresh_expires_at, timezone.utc).isoformat() if state.get("refresh_token") else ""
            ),
        }

    # Login -----------------------------------------------------------------------------------

    @staticmethod
    def authorize_url(app_key: str, callback_url: str) -> str:
        query = urllib.parse.urlencode({"client_id": app_key, "redirect_uri": callback_url})
        return f"{AUTHORIZE_URL}?{query}"

    @staticmethod
    def code_from_redirect(received_url: str) -> str:
        """The `code` Schwab put on the callback URL (parse_qs undoes its %40 encoding)."""
        query = urllib.parse.urlparse(received_url.strip()).query
        codes = urllib.parse.parse_qs(query).get("code") or []
        if not codes or not codes[0]:
            raise SchwabError("That URL has no code= in it. Copy the whole address bar after Schwab redirects.")
        return codes[0]

    def _basic_auth(self, state: dict[str, Any]) -> str:
        pair = f"{state['app_key']}:{state['app_secret']}".encode("utf-8")
        return "Basic " + base64.b64encode(pair).decode("ascii")

    def _token_request(self, state: dict[str, Any], form: dict[str, str]) -> dict[str, Any]:
        status, payload = self.http(
            "POST",
            TOKEN_URL,
            {
                "Authorization": self._basic_auth(state),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            urllib.parse.urlencode(form).encode("ascii"),
        )
        if status in (400, 401):
            raise SchwabLoginNeeded(_failure("Schwab refused the login", status, payload))
        if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            raise SchwabError(_failure("Schwab token request failed", status, payload))
        return payload

    def _store_tokens(self, state: dict[str, Any], payload: dict[str, Any], new_login: bool) -> dict[str, Any]:
        now = self.now()
        state = dict(state)
        state["access_token"] = str(payload["access_token"])
        state["access_expires_at"] = now + float(payload.get("expires_in") or 1800)
        if payload.get("refresh_token"):
            state["refresh_token"] = str(payload["refresh_token"])
        if new_login:
            state["refresh_issued_at"] = now
        self.save(state)
        return state

    def save_keys(self, app_key: str, app_secret: str, callback_url: str) -> None:
        """Save the App Key, Secret and callback URL. A blank key or secret keeps the saved one.
        Changing the key or callback drops the old login, since its tokens belong to the old app."""
        with self.lock:
            state = self.load()
            new_key = app_key.strip() or state.get("app_key", "")
            new_secret = app_secret.strip() or state.get("app_secret", "")
            new_callback = callback_url.strip() or state.get("callback_url") or DEFAULT_CALLBACK_URL
            if not new_key or not new_secret:
                raise SchwabError("Enter both the Schwab App Key and Secret.")
            if not new_callback.startswith("https://"):
                raise SchwabError("The callback URL must start with https:// and match the Schwab app exactly.")
            if new_key != state.get("app_key") or new_callback != state.get("callback_url"):
                state = {}
            state.update({"app_key": new_key, "app_secret": new_secret, "callback_url": new_callback})
            self.save(state)

    def saved_authorize_url(self) -> str:
        state = self.load()
        if not state.get("app_key"):
            raise SchwabError("Save the Schwab App Key and Secret first.")
        return self.authorize_url(str(state["app_key"]), str(state["callback_url"]))

    def login(self, received_url: str) -> None:
        """Finish the login with the address Schwab redirected the browser to."""
        code = self.code_from_redirect(received_url)
        with self.lock:
            state = self.load()
            if not state.get("app_key") or not state.get("app_secret"):
                raise SchwabError("Save the Schwab App Key and Secret first.")
            payload = self._token_request(
                state,
                {"grant_type": "authorization_code", "code": code, "redirect_uri": str(state["callback_url"])},
            )
            self._store_tokens(state, payload, new_login=True)

    def access_token(self) -> str:
        with self.lock:
            state = self.load()
            if not state.get("refresh_token"):
                raise SchwabLoginNeeded("Not logged in to Schwab.")
            if state.get("access_token") and state.get("access_expires_at", 0) - ACCESS_REFRESH_MARGIN_SECONDS > self.now():
                return str(state["access_token"])
            payload = self._token_request(
                state, {"grant_type": "refresh_token", "refresh_token": str(state["refresh_token"])}
            )
            return str(self._store_tokens(state, payload, new_login=False)["access_token"])

    # Data ------------------------------------------------------------------------------------

    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        quotes: dict[str, Any] = {}
        clean = [symbol for symbol in dict.fromkeys(s.strip().upper() for s in symbols) if symbol]
        for start in range(0, len(clean), QUOTE_BATCH_SIZE):
            batch = clean[start : start + QUOTE_BATCH_SIZE]
            query = urllib.parse.urlencode({"symbols": ",".join(batch), "fields": "quote", "indicative": "false"})
            status, payload = self.http(
                "GET",
                f"{QUOTES_URL}?{query}",
                {"Authorization": f"Bearer {self.access_token()}", "Accept": "application/json"},
                None,
            )
            if status == 401:
                raise SchwabLoginNeeded("Schwab rejected the access token (401).")
            if status != 200 or not isinstance(payload, dict):
                raise SchwabError(_failure("Schwab quotes request failed", status, payload))
            quotes.update(payload)
        return quotes


# Comparison ------------------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drop NaN


def _epoch_ms_iso(value: Any) -> str:
    number = _number(value)
    if not number:
        return ""
    return datetime.fromtimestamp(number / 1000, timezone.utc).isoformat()


def _pct_diff(value: float | None, reference: float | None) -> float | None:
    if value is None or not reference:
        return None
    return round((value - reference) / reference * 100, 4)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 4)


def schwab_quote_fields(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("quote"), dict):
        return None
    quote = entry["quote"]
    return {
        "last": _number(quote.get("lastPrice")),
        "bid": _number(quote.get("bidPrice")),
        "ask": _number(quote.get("askPrice")),
        "volume": _number(quote.get("totalVolume")),
        "prev_close": _number(quote.get("closePrice")),
        "change_pct": _number(quote.get("netPercentChange")),
        "trade_time": _epoch_ms_iso(quote.get("tradeTime")),
        "quote_time": _epoch_ms_iso(quote.get("quoteTime")),
        "security_status": str(quote.get("securityStatus") or ""),
        "realtime": entry.get("realtime"),
        "quote_type": str(entry.get("quoteType") or ""),
    }


def build_compare_record(alpaca_rows: list[dict[str, Any]], quotes: dict[str, Any], feed: str, now: datetime) -> dict[str, Any]:
    """One comparison: every Alpaca dashboard symbol beside Schwab's quote, plus the differences.

    `iex_volume_share` is the Alpaca feed's day volume as a share of Schwab's consolidated volume
    (how much of the market the IEX feed sees). `screener_volume_ratio` checks Alpaca's most-active
    volume against Schwab's. Price differences are Alpaca minus Schwab, as a percent of Schwab.
    """
    symbols: list[dict[str, Any]] = []
    missing: list[str] = []
    for row in alpaca_rows:
        symbol = str(row.get("symbol") or "")
        alpaca = {key: row.get(key) for key in (
            "last", "bid", "ask", "feed_volume", "screener_volume", "prev_close", "change_pct", "trade_time"
        )}
        schwab = schwab_quote_fields(quotes.get(symbol))
        if schwab is None:
            missing.append(symbol)
            symbols.append({"symbol": symbol, "alpaca": alpaca, "schwab": None, "diff": None})
            continue
        a_bid, a_ask = _number(alpaca["bid"]), _number(alpaca["ask"])
        s_bid, s_ask = schwab["bid"], schwab["ask"]
        a_mid = (a_bid + a_ask) / 2 if a_bid and a_ask else None
        s_mid = (s_bid + s_ask) / 2 if s_bid and s_ask else None
        a_change, s_change = _number(alpaca["change_pct"]), schwab["change_pct"]
        diff = {
            "last_pct": _pct_diff(_number(alpaca["last"]), schwab["last"]),
            "mid_pct": _pct_diff(a_mid, s_mid),
            "prev_close_pct": _pct_diff(_number(alpaca["prev_close"]), schwab["prev_close"]),
            "change_pct_points": round(a_change - s_change, 4) if a_change is not None and s_change is not None else None,
            "iex_volume_share": _ratio(_number(alpaca["feed_volume"]), schwab["volume"]),
            "screener_volume_ratio": _ratio(_number(alpaca["screener_volume"]), schwab["volume"]),
        }
        symbols.append({"symbol": symbol, "alpaca": alpaca, "schwab": schwab, "diff": diff})

    def median_abs(key: str) -> float | None:
        values = [abs(item["diff"][key]) for item in symbols if item["diff"] and item["diff"][key] is not None]
        return round(statistics.median(values), 4) if values else None

    def median(key: str) -> float | None:
        values = [item["diff"][key] for item in symbols if item["diff"] and item["diff"][key] is not None]
        return round(statistics.median(values), 4) if values else None

    return {
        "type": "schwab_compare",
        "at": now.astimezone(timezone.utc).isoformat(),
        "alpaca_feed": feed,
        "summary": {
            "symbols": len(symbols),
            "missing_at_schwab": missing,
            "median_abs_last_pct": median_abs("last_pct"),
            "median_abs_mid_pct": median_abs("mid_pct"),
            "median_abs_change_pct_points": median_abs("change_pct_points"),
            "median_iex_volume_share": median("iex_volume_share"),
            "median_screener_volume_ratio": median("screener_volume_ratio"),
        },
        "symbols": symbols,
    }


def append_compare_record(record: dict[str, Any], session_date: str) -> Path:
    storage.ensure_private_app_dir()
    folder = compare_dir()
    folder.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(folder, 0o700)
    path = folder / f"{session_date}.jsonl"
    line = json.dumps(record, separators=(",", ":")) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(line)
    return path


class CompareWorker:
    """Runs a comparison in the background so a slow Schwab call never delays an Alpaca scan."""

    def __init__(self, client: SchwabClient | None = None) -> None:
        self.client = client or SchwabClient()
        self.lock = threading.Lock()
        self.running = False
        self.last_started = 0.0
        self.last_status = ""
        self.last_message = ""
        self.last_finished_at = ""

    def submit(self, alpaca_rows: list[dict[str, Any]], feed: str, log: Callable[[str, str], None]) -> bool:
        """Start one comparison unless Schwab is not set up, one is running, or one ran recently."""
        if not alpaca_rows or not self.client.configured():
            return False
        with self.lock:
            now = time.monotonic()
            if self.running or (self.last_started and now - self.last_started < COMPARE_INTERVAL_SECONDS):
                return False
            self.running = True
            self.last_started = now
        thread = threading.Thread(
            target=self._run, args=(list(alpaca_rows), feed, log), name="schwab-compare", daemon=True
        )
        thread.start()
        return True

    def _report(self, status: str, level: str, message: str, log: Callable[[str, str], None]) -> None:
        # Log once per change of state, not on every minute's comparison.
        self.last_message = message
        self.last_finished_at = datetime.now(timezone.utc).isoformat()
        if status != self.last_status:
            self.last_status = status
            log(level, message)

    def _run(self, alpaca_rows: list[dict[str, Any]], feed: str, log: Callable[[str, str], None]) -> None:
        try:
            quotes = self.client.get_quotes([str(row.get("symbol") or "") for row in alpaca_rows])
            now = datetime.now(timezone.utc)
            record = build_compare_record(alpaca_rows, quotes, feed, now)
            path = append_compare_record(record, now.astimezone(MARKET_TIMEZONE).date().isoformat())
            self._report("ok", "info", f"Schwab comparison logging to {path.name} (data only; no effect on trades).", log)
        except SchwabLoginNeeded as exc:
            self._report(
                "login", "error", f"Schwab comparison paused: {exc} Log in again under App-wide settings.", log
            )
        except Exception as exc:  # the comparison must never disturb the trading loop
            self._report(f"error:{exc.__class__.__name__}", "error", f"Schwab comparison failed: {exc}", log)
        finally:
            with self.lock:
                self.running = False


    def status(self) -> dict[str, Any]:
        return {"comparison": self.last_message, "comparison_at": self.last_finished_at}


COMPARE = CompareWorker()
