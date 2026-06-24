from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .currentness import currentness_payload
from .engine import (
    TOP_VOLUME_CACHE_SECONDS,
    AccountPayload,
    AccountSettings,
    AppConfig,
    TraderManager,
    config_from_profile,
    credential_validation_error,
)
from .storage import load_settings, protect_text, save_settings, unprotect_text


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"

app = FastAPI(title="Alpaca Paper Trader")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
manager = TraderManager()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def no_cache_app_shell(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class SettingsPayload(BaseModel):
    selected_account_id: str = ""
    accounts: list[AccountSettings] = Field(default_factory=list)


class SelectAccountPayload(BaseModel):
    account_id: str


class ProfilePayload(BaseModel):
    profile: str
    current: dict[str, Any] | None = None


class CustomProfilePayload(BaseModel):
    name: str
    config: AppConfig


class AccountActionPayload(BaseModel):
    account_id: str | None = None
    force: bool = False


_last_refresh_by_account: dict[str, float] = {}
_last_dashboard_refresh = 0.0
_last_stream_watch = 0.0
_last_trade_backfill = 0.0
_auto_connect_complete = False
_settings_loaded = False


@app.on_event("startup")
async def startup() -> None:
    global _auto_connect_complete
    load_saved_settings_to_manager()
    if os.environ.get("ALPACA_TRADER_DISABLE_AUTO_CONNECT") != "1":
        asyncio.create_task(auto_connect_saved_accounts())
    else:
        _auto_connect_complete = True
    asyncio.create_task(background_refresh_loop())


async def auto_connect_saved_accounts() -> None:
    global _auto_connect_complete
    connected_accounts = []
    auto_start_accounts = []
    auto_start_disabled = os.environ.get("ALPACA_TRADER_DISABLE_AUTO_START", "").lower() in {"1", "true", "yes"}
    try:
        for account_engine in manager.list_engines():
            settings = account_engine.settings(include_keys=True)
            if (
                not settings.get("auto_connect", settings.get("remember", True))
                or not settings.get("remember")
                or not settings.get("api_key")
                or not settings.get("secret_key")
            ):
                continue
            try:
                await asyncio.to_thread(account_engine.connect_saved)
                connected_accounts.append(account_engine)
                if settings.get("auto_start_trading", False) and not auto_start_disabled:
                    auto_start_accounts.append(account_engine)
                elif settings.get("auto_start_trading", False) and auto_start_disabled:
                    account_engine.log("info", "Auto-start trading skipped by launch override.")
            except Exception as exc:
                account_engine.log("error", f"Auto-connect failed: {exc}")
        if connected_accounts:
            source = manager.shared_market_source() or connected_accounts[0]
            await asyncio.to_thread(manager.sync_top_volume_from, source)
            await asyncio.to_thread(manager.ensure_market_data_stream)
            await asyncio.to_thread(manager.backfill_dashboard_recent_trades, "startup trade-volume backfill")
            await asyncio.to_thread(manager.backfill_dashboard_latest_trades, "startup dashboard backfill")
        for account_engine in auto_start_accounts:
            try:
                await asyncio.to_thread(account_engine.start_trading)
            except Exception as exc:
                account_engine.log("error", f"Auto-start trading failed: {exc}")
    finally:
        _auto_connect_complete = True


async def background_refresh_loop() -> None:
    global _last_dashboard_refresh, _last_stream_watch, _last_trade_backfill
    while True:
        try:
            await asyncio.sleep(1)
            now = time.monotonic()
            for account_engine in manager.list_engines():
                state = account_engine.state()
                if not state.get("connected"):
                    continue
                poll_seconds = max(5, int(state.get("config", {}).get("poll_seconds", 5) or 5))
                last = _last_refresh_by_account.get(account_engine.account_id, 0)
                if now - last >= poll_seconds:
                    _last_refresh_by_account[account_engine.account_id] = now
                    try:
                        await asyncio.to_thread(manager.refresh_account, account_engine.account_id)
                    except Exception as exc:
                        record_background_error(account_engine, f"Background refresh failed: {exc}")
            if _auto_connect_complete and now - _last_dashboard_refresh >= TOP_VOLUME_CACHE_SECONDS:
                _last_dashboard_refresh = now
                try:
                    await asyncio.to_thread(manager.refresh_dashboard, None, False)
                except Exception as exc:
                    record_background_error(None, f"Dashboard refresh failed: {exc}")
            if _auto_connect_complete and now - _last_stream_watch >= 10:
                _last_stream_watch = now
                stream = manager.market_stream_state()
                status = str(stream.get("status") or "").lower()
                age = stream.get("last_message_age_seconds")
                stale = isinstance(age, (int, float)) and age > 90
                in_handshake = status in {
                    "starting",
                    "connecting",
                    "authenticating",
                    "connected",
                    "subscription sent",
                    "subscribed",
                    "restarting",
                }
                hard_disconnected = not stream.get("connected") and not in_handshake
                waiting = status == "listening" and str(stream.get("last_message") or "").lower().startswith("waiting")
                if (
                    manager.connected_engines()
                    and status != "connection limit"
                    and (hard_disconnected or stale)
                ):
                    try:
                        await asyncio.to_thread(manager.reconnect_market_data_stream)
                    except Exception as exc:
                        record_background_error(None, f"Market stream reconnect failed: {exc}")
                if (
                    manager.connected_engines()
                    and status != "connection limit"
                    and (waiting or status != "streaming" or stale)
                    and now - _last_trade_backfill >= 20
                ):
                    _last_trade_backfill = now
                    try:
                        await asyncio.to_thread(manager.backfill_dashboard_recent_trades, "market stream trade fallback")
                        await asyncio.to_thread(manager.backfill_dashboard_latest_trades, "market stream watchdog")
                    except Exception as exc:
                        record_background_error(None, f"Market stream backfill failed: {exc}")
        except Exception as exc:
            record_background_error(None, f"Background loop recovered after error: {exc}")
            await asyncio.sleep(5)


def record_background_error(account_engine: Any | None, message: str) -> None:
    targets = [account_engine] if account_engine is not None else manager.connected_engines()
    for engine in targets:
        try:
            engine.log("error", message)
            with engine.lock:
                engine.last_error = message
        except Exception:
            pass


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "alpaca-paper-trader.ico")


@app.get("/api/health")
async def get_health(request: Request) -> dict[str, Any]:
    runtime_url = str(getattr(app.state, "runtime_url", "") or "").rstrip("/")
    if not runtime_url:
        runtime_url = str(request.base_url).rstrip("/")
    return currentness_payload(url=runtime_url)


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    load_saved_settings_to_manager()
    return manager.settings(include_keys=False)


@app.post("/api/settings")
async def post_settings(payload: SettingsPayload) -> dict[str, str]:
    manager.replace_from_settings(preserve_credentials(payload.accounts), payload.selected_account_id)
    save_manager_settings()
    return {"status": "saved"}


@app.post("/api/profile")
async def profile_config(payload: ProfilePayload) -> dict[str, Any]:
    try:
        return manager.config_from_profile(payload.profile, payload.current).model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/custom-profile")
async def save_custom_profile(payload: CustomProfilePayload) -> dict[str, Any]:
    try:
        profile_key, config = manager.save_custom_profile(payload.name, payload.config)
        save_manager_settings()
        return {
            "profile": profile_key,
            "config": config,
            "profiles": manager.profile_presets(),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/accounts")
async def save_account(payload: AccountPayload) -> dict[str, Any]:
    try:
        engine = manager.upsert_payload(payload)
        engine.configure_payload(payload)
        save_manager_settings()
        return manager.state(engine.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/apply-parameters")
async def apply_parameters(payload: AccountPayload) -> dict[str, Any]:
    try:
        engine = manager.upsert_payload(payload)
        engine.configure_payload(payload)
        save_manager_settings()
        if engine.connected:
            await asyncio.to_thread(manager.refresh_account, engine.account_id)
        return manager.state(engine.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str) -> dict[str, Any]:
    try:
        manager.remove(account_id)
        save_manager_settings()
        return manager.state()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/select-account")
async def select_account(payload: SelectAccountPayload) -> dict[str, Any]:
    try:
        manager.set_selected(payload.account_id)
        save_manager_settings()
        return manager.state(payload.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/connect")
async def connect(payload: AccountPayload) -> dict[str, Any]:
    try:
        engine = manager.upsert_payload(payload)
        await asyncio.to_thread(engine.connect, payload.model_copy(update={"account_id": engine.account_id}))
        await asyncio.to_thread(manager.sync_top_volume_from, engine)
        await asyncio.to_thread(manager.ensure_market_data_stream)
        await asyncio.to_thread(manager.backfill_dashboard_recent_trades, "connect trade-volume backfill")
        await asyncio.to_thread(manager.backfill_dashboard_latest_trades, "connect dashboard backfill")
        save_manager_settings()
        return manager.state(engine.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/start")
async def start_trading(payload: AccountActionPayload) -> dict[str, Any]:
    try:
        engine = manager.get(payload.account_id)
        await asyncio.to_thread(engine.start_trading)
        return manager.state(engine.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/stop")
async def stop_trading(payload: AccountActionPayload) -> dict[str, Any]:
    try:
        engine = manager.get(payload.account_id)
        engine.stop_trading()
        return manager.state(engine.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/refresh")
async def refresh(payload: AccountActionPayload) -> dict[str, Any]:
    try:
        engine = manager.get(payload.account_id)
        await asyncio.to_thread(manager.refresh_account, engine.account_id, False)
        return manager.state(engine.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/refresh-all")
async def refresh_all() -> dict[str, Any]:
    await asyncio.to_thread(manager.refresh_all)
    return manager.state()


@app.get("/api/dashboard")
async def get_dashboard(account_id: str | None = None) -> dict[str, Any]:
    return manager.dashboard_state(account_id)


@app.post("/api/dashboard/top-volume")
async def refresh_top_volume(payload: AccountActionPayload) -> dict[str, Any]:
    try:
        await asyncio.to_thread(manager.refresh_dashboard, payload.account_id, True)
        return manager.dashboard_state(payload.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/dashboard/reconnect-stream")
async def reconnect_dashboard_stream(payload: AccountActionPayload) -> dict[str, Any]:
    try:
        stream = manager.market_stream_state()
        status = str(stream.get("status") or "").lower()
        age = stream.get("last_message_age_seconds")
        stale = isinstance(age, (int, float)) and age > 90
        in_handshake = status in {
            "starting",
            "connecting",
            "authenticating",
            "connected",
            "subscription sent",
            "subscribed",
            "listening",
            "restarting",
            "retrying",
            "stopping previous stream",
        }
        if not payload.force and (in_handshake or (stream.get("connected") and not stale)):
            return manager.dashboard_state(payload.account_id)
        await asyncio.to_thread(manager.refresh_dashboard, payload.account_id, True)
        await asyncio.to_thread(manager.reconnect_market_data_stream)
        await asyncio.to_thread(manager.backfill_dashboard_recent_trades, "manual dashboard trade backfill")
        await asyncio.to_thread(manager.backfill_dashboard_latest_trades, "manual dashboard reconnect")
        return manager.dashboard_state(payload.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/lookup")
async def lookup_symbol(symbol: str, account_id: str | None = None) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(manager.lookup_symbol, symbol, account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cancel-orders")
async def cancel_orders(payload: AccountActionPayload) -> dict[str, Any]:
    try:
        engine = manager.get(payload.account_id)
        await asyncio.to_thread(engine.cancel_orders)
        return manager.state(engine.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/purge-account")
async def purge_account(payload: AccountActionPayload) -> dict[str, Any]:
    try:
        engine = manager.get(payload.account_id)
        await asyncio.to_thread(engine.purge_account)
        return manager.state(engine.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/state")
async def get_state(account_id: str | None = None) -> dict[str, Any]:
    return manager.state(account_id)


def load_saved_settings_to_manager() -> None:
    global _settings_loaded
    if _settings_loaded:
        return

    raw = load_settings()
    selected_account_id = str(raw.get("selected_account_id") or "")
    if isinstance(raw.get("custom_profiles"), dict):
        manager.set_custom_profiles(raw.get("custom_profiles") or {})
    account_settings: list[AccountSettings] = []

    if isinstance(raw.get("accounts"), list):
        for item in raw["accounts"]:
            try:
                remember = bool(item.get("remember", False))
                auto_connect = bool(item.get("auto_connect", remember))
                auto_start_trading = bool(item.get("auto_start_trading", False))
                api_key = ""
                secret_key = ""
                if remember:
                    api_key = unprotect_text(str(item.get("api_key", "")))
                    secret_key = unprotect_text(str(item.get("secret_key", "")))
                account_settings.append(
                    AccountSettings(
                        account_id=str(item.get("account_id") or ""),
                        name=str(item.get("name") or "Paper Account"),
                        api_key=api_key,
                        secret_key=secret_key,
                        remember=remember,
                        auto_connect=auto_connect,
                        auto_start_trading=auto_start_trading,
                        config=AppConfig(**(item.get("config") or {})),
                    )
                )
            except Exception:
                continue
    elif raw:
        # Migration path from the original single-account settings format.
        remember = bool(raw.get("remember", False))
        auto_connect = bool(raw.get("auto_connect", remember))
        auto_start_trading = bool(raw.get("auto_start_trading", False))
        api_key = ""
        secret_key = ""
        if remember:
            try:
                api_key = unprotect_text(str(raw.get("api_key", "")))
                secret_key = unprotect_text(str(raw.get("secret_key", "")))
            except Exception:
                api_key = ""
                secret_key = ""
        account_settings.append(
            AccountSettings(
                account_id=str(raw.get("account_id") or "default"),
                name=str(raw.get("name") or "Account 1"),
                api_key=api_key,
                secret_key=secret_key,
                remember=remember,
                auto_connect=auto_connect,
                auto_start_trading=auto_start_trading,
                config=AppConfig(**(raw.get("config") or {})),
            )
        )

    if account_settings:
        account_settings = [
            item.model_copy(update={"account_id": item.account_id or f"account-{index + 1}"})
            for index, item in enumerate(account_settings)
        ]
        manager.replace_from_settings(account_settings, selected_account_id)

    _settings_loaded = True


def preserve_credentials(accounts: list[AccountSettings]) -> list[AccountSettings]:
    raw_settings = load_settings()
    encrypted_by_id = {
        str(item.get("account_id") or ""): item
        for item in raw_settings.get("accounts", [])
        if isinstance(item, dict)
    }
    preserved: list[AccountSettings] = []
    for item in accounts:
        api_key = item.api_key
        secret_key = item.secret_key
        provided_error = credential_validation_error(api_key, secret_key, require_pair=False)
        if provided_error:
            raise RuntimeError(provided_error)
        try:
            existing = manager.get(item.account_id)
            existing_settings = existing.settings(include_keys=True)
            api_key = api_key or str(existing_settings.get("api_key", ""))
            secret_key = secret_key or str(existing_settings.get("secret_key", ""))
        except Exception:
            pass
        encrypted = encrypted_by_id.get(item.account_id, {})
        if item.remember and not api_key and encrypted.get("api_key"):
            try:
                api_key = unprotect_text(str(encrypted.get("api_key", "")))
            except Exception:
                api_key = ""
        if item.remember and not secret_key and encrypted.get("secret_key"):
            try:
                secret_key = unprotect_text(str(encrypted.get("secret_key", "")))
            except Exception:
                secret_key = ""
        preserved.append(item.model_copy(update={"api_key": api_key, "secret_key": secret_key}))
    return preserved


def save_manager_settings() -> None:
    snapshot = manager.settings(include_keys=True)
    existing_raw = load_settings()
    existing_by_id = {
        str(item.get("account_id") or ""): item
        for item in existing_raw.get("accounts", [])
        if isinstance(item, dict)
    }
    accounts = []
    for item in snapshot["accounts"]:
        remember = bool(item.get("remember", False))
        existing = existing_by_id.get(str(item.get("account_id", "")), {})
        api_key = str(item.get("api_key", ""))
        secret_key = str(item.get("secret_key", ""))
        encrypted_api_key = protect_text(api_key) if remember and api_key else str(existing.get("api_key", ""))
        encrypted_secret_key = protect_text(secret_key) if remember and secret_key else str(existing.get("secret_key", ""))
        accounts.append(
            {
                "account_id": item.get("account_id", ""),
                "name": item.get("name", "Paper Account"),
                "remember": remember,
                "auto_connect": bool(item.get("auto_connect", remember)),
                "auto_start_trading": bool(item.get("auto_start_trading", False)),
                "api_key": encrypted_api_key if remember else "",
                "secret_key": encrypted_secret_key if remember else "",
                "config": item.get("config", AppConfig().model_dump(mode="json")),
            }
        )
    save_settings(
        {
            "selected_account_id": snapshot.get("selected_account_id", ""),
            "accounts": accounts,
            "custom_profiles": snapshot.get("custom_profiles", {}),
        }
    )
