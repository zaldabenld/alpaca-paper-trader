from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
QTY_PLACES = Decimal("0.0001")
MONEY_PLACES = Decimal("0.01")
PRICE_RE = re.compile(
    r"(?:^|[;\s,])(?P<key>order_ref|price|limit|stop)="
    r"(?P<value>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def default_tape_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader" / "day-tape"


def tape_file_date(path: Path) -> str:
    name = path.name
    if name.startswith("tape-") and name.endswith(".jsonl"):
        return name[5:13]
    return ""


def selected_files(path: Path, days: int, end_date: str = "") -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(path.glob("tape-*.jsonl"), key=lambda item: item.name)
    if end_date:
        files = [item for item in files if tape_file_date(item) <= end_date]
    return files[-max(1, days) :]


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value).strip().replace("$", "").replace(",", "").replace("%", ""))
    except (InvalidOperation, ValueError):
        return default


def money(value: Decimal) -> str:
    return f"${value.quantize(MONEY_PLACES):,.2f}"


def percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"


def qty_text(value: Decimal) -> str:
    return str(value.quantize(QTY_PLACES).normalize())


def payload_dict(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def iter_events(files: Iterable[Path]) -> Iterable[tuple[Path, int, dict[str, Any] | None]]:
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    yield path, line_number, json.loads(line)
                except json.JSONDecodeError:
                    yield path, line_number, None


def bucket_key(payload: dict[str, Any]) -> str:
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    profile = str(config.get("profile") or "unknown")
    max_trade = str(config.get("max_trade_notional") or "?")
    max_positions = str(config.get("max_open_positions") or "?")
    top_volume = str(config.get("use_top_volume_symbols"))
    dry_run = str(config.get("dry_run"))
    return (
        f"profile={profile}, max_trade={max_trade}, max_positions={max_positions}, "
        f"top_volume={top_volume}, dry_run={dry_run}"
    )


def event_price(kind: str, payload: dict[str, Any]) -> tuple[str, Decimal] | None:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    if kind == "market_trade":
        price = parse_decimal(payload.get("price"))
    elif kind == "market_bar":
        price = parse_decimal(payload.get("close"))
    elif kind == "market_quote":
        bid = parse_decimal(payload.get("bid_price"))
        ask = parse_decimal(payload.get("ask_price"))
        if bid > ZERO and ask > ZERO:
            price = (bid + ask) / Decimal("2")
        else:
            price = ask if ask > ZERO else bid
    else:
        return None
    if price <= ZERO:
        return None
    return symbol, price


def reason_prices(reason: Any) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for match in PRICE_RE.finditer(str(reason or "")):
        price = parse_decimal(match.group("value"))
        if price > ZERO:
            prices[match.group("key").lower()] = price
    return prices


@dataclass
class Lot:
    qty: Decimal
    price: Decimal


@dataclass
class Position:
    symbol: str
    lots: list[Lot] = field(default_factory=list)
    last_price: Decimal = ZERO

    @property
    def qty(self) -> Decimal:
        return sum((lot.qty for lot in self.lots), ZERO)

    @property
    def cost_basis(self) -> Decimal:
        return sum((lot.qty * lot.price for lot in self.lots), ZERO)

    @property
    def market_value(self) -> Decimal:
        mark = self.last_price if self.last_price > ZERO else self.average_price
        return self.qty * mark

    @property
    def average_price(self) -> Decimal:
        qty = self.qty
        if qty <= ZERO:
            return ZERO
        return self.cost_basis / qty

    def buy(self, qty: Decimal, price: Decimal) -> None:
        if qty <= ZERO or price <= ZERO:
            return
        self.lots.append(Lot(qty=qty, price=price))
        self.last_price = price

    def sell(self, qty: Decimal) -> tuple[Decimal, Decimal]:
        remaining = min(qty, self.qty)
        sold = remaining
        cost = ZERO
        new_lots: list[Lot] = []
        for lot in self.lots:
            if remaining <= ZERO:
                new_lots.append(lot)
                continue
            used = min(lot.qty, remaining)
            cost += used * lot.price
            remaining -= used
            leftover = lot.qty - used
            if leftover > ZERO:
                new_lots.append(Lot(qty=leftover, price=lot.price))
        self.lots = new_lots
        return sold, cost


@dataclass
class SimOrder:
    client_order_id: str
    symbol: str
    side: str
    qty: Decimal
    role: str
    order_type: str
    submitted_at: datetime | None
    reference_price: Decimal = ZERO
    limit_price: Decimal = ZERO
    stop_price: Decimal = ZERO
    reason: str = ""


@dataclass
class Fill:
    time: datetime | None
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    role: str
    realized_pl: Decimal = ZERO


@dataclass
class BucketMeta:
    key: str
    first_time: datetime | None = None
    latest_time: datetime | None = None
    first_payload: dict[str, Any] = field(default_factory=dict)
    latest_payload: dict[str, Any] = field(default_factory=dict)
    source_keys: list[str] = field(default_factory=list)


@dataclass
class AccountSim:
    key: str
    starting_equity: Decimal
    cash: Decimal
    buying_power: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    open_orders: dict[str, SimOrder] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    counters: Counter[str] = field(default_factory=Counter)
    realized_pl: Decimal = ZERO
    equity_peak: Decimal = ZERO
    max_drawdown: Decimal = ZERO
    latest_equity: Decimal = ZERO
    latest_actual_equity: Decimal = ZERO
    latest_actual_cash: Decimal = ZERO

    def __post_init__(self) -> None:
        self.latest_equity = self.starting_equity
        self.equity_peak = self.starting_equity

    def seed_position(self, raw: dict[str, Any]) -> None:
        symbol = str(raw.get("symbol") or "").strip().upper()
        qty = abs(parse_decimal(raw.get("qty")))
        if not symbol or qty <= ZERO:
            return
        cost_basis = parse_decimal(raw.get("cost_basis"))
        avg_price = parse_decimal(raw.get("avg_entry_price"))
        if cost_basis > ZERO:
            avg_price = cost_basis / qty
        if avg_price <= ZERO:
            return
        current_price = parse_decimal(raw.get("current_price"), avg_price)
        position = self.positions.setdefault(symbol, Position(symbol=symbol))
        position.buy(qty, avg_price)
        position.last_price = current_price

    def equity(self) -> Decimal:
        return self.cash + sum((position.market_value for position in self.positions.values()), ZERO)

    def record_equity(self) -> None:
        self.latest_equity = self.equity()
        if self.latest_equity > self.equity_peak:
            self.equity_peak = self.latest_equity
        drawdown = self.equity_peak - self.latest_equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def update_price(self, symbol: str, price: Decimal) -> None:
        position = self.positions.get(symbol)
        if position:
            position.last_price = price
            self.record_equity()

    def apply_slippage(self, side: str, price: Decimal, slippage_bps: Decimal) -> Decimal:
        if slippage_bps <= ZERO:
            return price
        adjustment = price * slippage_bps / BPS
        if side == "buy":
            return price + adjustment
        return max(ZERO, price - adjustment)

    def fill_order(self, order: SimOrder, price: Decimal, when: datetime | None, slippage_bps: Decimal) -> None:
        price = self.apply_slippage(order.side, price, slippage_bps)
        if price <= ZERO or order.qty <= ZERO:
            self.counters["invalid_fills"] += 1
            return
        if order.side == "buy":
            self.fill_buy(order, price, when)
        elif order.side == "sell":
            self.fill_sell(order, price, when)
        self.record_equity()

    def fill_buy(self, order: SimOrder, price: Decimal, when: datetime | None) -> None:
        cost = order.qty * price
        available = max(self.cash, self.buying_power)
        if cost > available:
            self.counters["rejected_insufficient_buying_power"] += 1
            return
        position = self.positions.setdefault(order.symbol, Position(symbol=order.symbol))
        position.buy(order.qty, price)
        self.cash -= cost
        self.buying_power = max(ZERO, self.buying_power - cost)
        self.fills.append(Fill(when, order.symbol, "buy", order.qty, price, order.role))
        self.counters["buy_fills"] += 1

    def fill_sell(self, order: SimOrder, price: Decimal, when: datetime | None) -> None:
        position = self.positions.get(order.symbol)
        if not position or position.qty <= ZERO:
            self.counters["sell_without_position"] += 1
            return
        sold_qty, cost_basis = position.sell(order.qty)
        if sold_qty <= ZERO:
            self.counters["sell_without_position"] += 1
            return
        proceeds = sold_qty * price
        realized = proceeds - cost_basis
        self.cash += proceeds
        self.buying_power += proceeds
        self.realized_pl += realized
        self.fills.append(Fill(when, order.symbol, "sell", sold_qty, price, order.role, realized))
        self.counters["sell_fills"] += 1
        if realized > ZERO:
            self.counters["winning_exits"] += 1
        elif realized < ZERO:
            self.counters["losing_exits"] += 1
        else:
            self.counters["flat_exits"] += 1
        if position.qty <= ZERO:
            self.positions.pop(order.symbol, None)


class DayTapeSimulator:
    def __init__(self, files: list[Path], slippage_bps: Decimal = ZERO) -> None:
        self.files = files
        self.slippage_bps = slippage_bps
        self.metas: dict[str, BucketMeta] = {}
        self.bucket_aliases: dict[str, str] = {}
        self.order_to_bucket: dict[str, str] = {}
        self.accounts: dict[str, AccountSim] = {}
        self.last_prices: dict[str, Decimal] = {}
        self.market_open = False
        self.counters: Counter[str] = Counter()
        self.total_events = 0
        self.first_time: datetime | None = None
        self.latest_time: datetime | None = None

    def build_metadata(self) -> None:
        for _path, _line_number, event in iter_events(self.files):
            if event is None:
                continue
            if event.get("kind") != "strategy_scan":
                continue
            payload = payload_dict(event)
            key = bucket_key(payload)
            event_time = parse_time(event.get("time"))
            meta = self.metas.setdefault(key, BucketMeta(key=key))
            if not meta.first_payload:
                meta.first_payload = payload
                meta.first_time = event_time
                meta.source_keys = [key]
            meta.latest_payload = payload
            meta.latest_time = event_time
            for group in ("open_orders", "closed_orders"):
                orders = payload.get(group)
                if not isinstance(orders, list):
                    continue
                for order in orders:
                    if not isinstance(order, dict):
                        continue
                    client_order_id = str(order.get("client_order_id") or "").strip()
                    if client_order_id:
                        self.order_to_bucket[client_order_id] = key
        self.stitch_config_handoffs()
        self.order_to_bucket = {
            order_id: self.bucket_aliases.get(key, key)
            for order_id, key in self.order_to_bucket.items()
        }

    def stitch_config_handoffs(self) -> None:
        parent = {key: key for key in self.metas}

        def find(key: str) -> str:
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        def union(old_key: str, new_key: str) -> None:
            parent[find(old_key)] = find(new_key)

        ordered = sorted(
            self.metas.values(),
            key=lambda item: item.first_time or datetime.min,
        )
        for earlier in ordered:
            for later in ordered:
                if earlier.key == later.key:
                    continue
                if self.is_config_handoff(earlier, later):
                    union(earlier.key, later.key)

        groups: dict[str, list[BucketMeta]] = {}
        for key, meta in self.metas.items():
            groups.setdefault(find(key), []).append(meta)

        merged: dict[str, BucketMeta] = {}
        aliases: dict[str, str] = {}
        for canonical, items in groups.items():
            ordered_items = sorted(items, key=lambda item: item.first_time or datetime.min)
            latest_items = sorted(items, key=lambda item: item.latest_time or datetime.min)
            first = ordered_items[0]
            latest = latest_items[-1]
            source_keys = [item.key for item in ordered_items]
            display_key = canonical
            if len(source_keys) > 1:
                display_key = f"{canonical} (stitched {len(source_keys)} configs)"
                self.counters["stitched_config_handoffs"] += len(source_keys) - 1
            merged_meta = BucketMeta(
                key=display_key,
                first_time=first.first_time,
                latest_time=latest.latest_time,
                first_payload=first.first_payload,
                latest_payload=latest.latest_payload,
                source_keys=source_keys,
            )
            merged[canonical] = merged_meta
            for source_key in source_keys:
                aliases[source_key] = canonical
        self.metas = merged
        self.bucket_aliases = aliases

    def is_config_handoff(self, earlier: BucketMeta, later: BucketMeta) -> bool:
        if earlier.latest_time is None or later.first_time is None:
            return False
        gap = (later.first_time - earlier.latest_time).total_seconds()
        if gap < 0 or gap > 15 * 60:
            return False
        earlier_config = earlier.latest_payload.get("config") if isinstance(earlier.latest_payload.get("config"), dict) else {}
        later_config = later.first_payload.get("config") if isinstance(later.first_payload.get("config"), dict) else {}
        for key in ("profile", "max_trade_notional", "use_top_volume_symbols", "dry_run"):
            if str(earlier_config.get(key)) != str(later_config.get(key)):
                return False
        earlier_account = earlier.latest_payload.get("account") if isinstance(earlier.latest_payload.get("account"), dict) else {}
        later_account = later.first_payload.get("account") if isinstance(later.first_payload.get("account"), dict) else {}
        earlier_equity = parse_decimal(earlier_account.get("equity"))
        later_equity = parse_decimal(later_account.get("equity"))
        earlier_cash = parse_decimal(earlier_account.get("cash"))
        later_cash = parse_decimal(later_account.get("cash"))
        if earlier_equity <= ZERO or later_equity <= ZERO:
            return False
        equity_tolerance = max(Decimal("2"), earlier_equity.copy_abs() * Decimal("0.005"))
        cash_tolerance = max(Decimal("2"), earlier_cash.copy_abs() * Decimal("0.005"))
        return (
            abs(earlier_equity - later_equity) <= equity_tolerance
            and abs(earlier_cash - later_cash) <= cash_tolerance
        )

    def initialize_accounts(self) -> None:
        for canonical_key, meta in self.metas.items():
            payload = meta.first_payload
            account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
            starting_equity = parse_decimal(account.get("equity"))
            starting_cash = parse_decimal(account.get("cash"))
            buying_power = parse_decimal(account.get("buying_power"), starting_cash)
            if starting_cash <= ZERO and starting_equity > ZERO:
                positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
                market_value = sum((parse_decimal(item.get("market_value")) for item in positions if isinstance(item, dict)), ZERO)
                starting_cash = starting_equity - market_value
            sim = AccountSim(
                key=meta.key,
                starting_equity=starting_equity,
                cash=starting_cash,
                buying_power=buying_power,
            )
            positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
            for position in positions:
                if isinstance(position, dict):
                    sim.seed_position(position)
            latest_account = meta.latest_payload.get("account") if isinstance(meta.latest_payload.get("account"), dict) else {}
            sim.latest_actual_equity = parse_decimal(latest_account.get("equity"))
            sim.latest_actual_cash = parse_decimal(latest_account.get("cash"))
            sim.record_equity()
            self.accounts[canonical_key] = sim

    def run(self) -> None:
        self.build_metadata()
        self.initialize_accounts()
        start = time.perf_counter()
        previous_market_open = self.market_open

        for _path, _line_number, event in iter_events(self.files):
            if event is None:
                self.counters["parse_errors"] += 1
                continue
            kind = str(event.get("kind") or "")
            payload = payload_dict(event)
            event_time = parse_time(event.get("time"))
            self.total_events += 1
            self.first_time = self.first_time or event_time
            self.latest_time = event_time or self.latest_time
            self.counters[kind] += 1

            if kind == "strategy_scan":
                clock = payload.get("market_clock") if isinstance(payload.get("market_clock"), dict) else {}
                self.market_open = bool(clock.get("is_open"))
                if previous_market_open and not self.market_open:
                    self.expire_day_orders()
                previous_market_open = self.market_open

            price_item = event_price(kind, payload)
            if price_item:
                symbol, price = price_item
                self.last_prices[symbol] = price
                for account in self.accounts.values():
                    account.update_price(symbol, price)
                if self.market_open:
                    self.try_fill_resting_orders(symbol, price, event_time)

            if kind == "order_intent":
                self.handle_order_intent(payload, event_time)

        self.expire_day_orders()
        self.counters["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
        for account in self.accounts.values():
            account.record_equity()

    def expire_day_orders(self) -> None:
        for account in self.accounts.values():
            if account.open_orders:
                account.counters["expired_day_orders"] += len(account.open_orders)
                account.open_orders.clear()

    def handle_order_intent(self, payload: dict[str, Any], event_time: datetime | None) -> None:
        status = str(payload.get("status") or "").strip().lower()
        if status != "submitted":
            self.counters[f"order_intent_{status or 'unknown'}"] += 1
            return
        client_order_id = str(payload.get("client_order_id") or "").strip()
        bucket = self.order_to_bucket.get(client_order_id)
        if not bucket:
            self.counters["unmatched_submitted_order_intents"] += 1
            return
        account = self.accounts.get(bucket)
        if account is None:
            self.counters["missing_account_for_order"] += 1
            return
        order = self.order_from_intent(payload, event_time)
        if order.qty <= ZERO or not order.symbol:
            self.counters["invalid_order_intents"] += 1
            return
        if order.order_type == "market":
            price = self.last_prices.get(order.symbol, ZERO) or order.reference_price
            if price <= ZERO:
                self.counters["market_orders_without_price"] += 1
                return
            account.fill_order(order, price, event_time, self.slippage_bps)
            return
        account.open_orders[order.client_order_id] = order
        account.counters[f"opened_{order.order_type}_orders"] += 1
        price = self.last_prices.get(order.symbol, ZERO)
        if price > ZERO and self.market_open:
            self.try_fill_one_resting_order(account, order, price, event_time)

    def order_from_intent(self, payload: dict[str, Any], event_time: datetime | None) -> SimOrder:
        reason = str(payload.get("reason") or "")
        prices = reason_prices(reason)
        role = str(payload.get("role") or "")
        side = str(payload.get("side") or "").strip().lower()
        order_type = "market"
        if prices.get("stop") and side == "sell":
            order_type = "stop"
        elif prices.get("limit"):
            order_type = "limit"
        elif "limit" in reason.lower() and prices.get("price"):
            order_type = "limit"
        reference = prices.get("order_ref") or prices.get("price") or ZERO
        return SimOrder(
            client_order_id=str(payload.get("client_order_id") or "").strip(),
            symbol=str(payload.get("symbol") or "").strip().upper(),
            side=side,
            qty=abs(parse_decimal(payload.get("qty"))),
            role=role,
            order_type=order_type,
            submitted_at=event_time,
            reference_price=reference,
            limit_price=prices.get("limit") or ZERO,
            stop_price=prices.get("stop") or ZERO,
            reason=reason,
        )

    def try_fill_resting_orders(self, symbol: str, price: Decimal, when: datetime | None) -> None:
        for account in self.accounts.values():
            for order in list(account.open_orders.values()):
                if order.symbol == symbol:
                    self.try_fill_one_resting_order(account, order, price, when)

    def try_fill_one_resting_order(
        self,
        account: AccountSim,
        order: SimOrder,
        price: Decimal,
        when: datetime | None,
    ) -> None:
        fill_price = ZERO
        if order.order_type == "stop":
            if order.side == "sell" and order.stop_price > ZERO and price <= order.stop_price:
                fill_price = price
            elif order.side == "buy" and order.stop_price > ZERO and price >= order.stop_price:
                fill_price = price
        elif order.order_type == "limit":
            if order.side == "sell" and order.limit_price > ZERO and price >= order.limit_price:
                fill_price = order.limit_price
            elif order.side == "buy" and order.limit_price > ZERO and price <= order.limit_price:
                fill_price = order.limit_price
        if fill_price <= ZERO:
            return
        account.fill_order(order, fill_price, when, self.slippage_bps)
        account.open_orders.pop(order.client_order_id, None)

    def report(self) -> int:
        print("Day Tape Replay Simulator")
        print(f"Files: {len(self.files)}")
        print(f"Events processed: {self.total_events:,}")
        if self.first_time and self.latest_time:
            hours = max((self.latest_time - self.first_time).total_seconds(), 0) / 3600
            print(f"Span: {self.first_time.isoformat()} -> {self.latest_time.isoformat()} ({hours:.2f} hours)")
        print(f"Runtime: {self.counters.get('elapsed_ms', 0) / 1000:.2f}s")
        print()
        print("Assumptions")
        print("  Mode: submitted order-intent replay with a local fake broker.")
        print("  Market orders: fill at latest tape price, falling back to order_ref/price from the intent reason.")
        print("  Sell stops: trigger at or below stop, then fill at the trigger tick price.")
        print("  Sell limits: trigger at or above limit, then fill at the limit price.")
        print("  DAY exits: expire when tape market_clock moves from open to closed, and at replay end.")
        print(f"  Slippage: {self.slippage_bps} bps per fill.")
        print()
        print("Tape Counts")
        for name in (
            "market_trade",
            "market_bar",
            "market_quote",
            "strategy_scan",
            "order_intent",
            "parse_errors",
            "order_intent_error",
            "unmatched_submitted_order_intents",
            "market_orders_without_price",
            "stitched_config_handoffs",
        ):
            value = self.counters.get(name, 0)
            if value:
                print(f"  {name}: {value:,}")
        print()
        print("Accounts")
        for index, key in enumerate(sorted(self.accounts), start=1):
            account = self.accounts[key]
            sells = [fill for fill in account.fills if fill.side == "sell"]
            realized_values = [fill.realized_pl for fill in sells]
            wins = [value for value in realized_values if value > ZERO]
            losses = [value for value in realized_values if value < ZERO]
            gross_profit = sum(wins, ZERO)
            gross_loss = abs(sum(losses, ZERO))
            profit_factor = gross_profit / gross_loss if gross_loss > ZERO else None
            closed_count = len(wins) + len(losses)
            win_rate = (Decimal(len(wins)) / Decimal(closed_count) * Decimal("100")) if closed_count else ZERO
            expectancy = (sum(realized_values, ZERO) / Decimal(len(realized_values))) if realized_values else ZERO
            ending = account.equity()
            actual_delta = ending - account.latest_actual_equity if account.latest_actual_equity > ZERO else ZERO
            unrealized = sum((position.market_value - position.cost_basis for position in account.positions.values()), ZERO)
            market_value = sum((position.market_value for position in account.positions.values()), ZERO)
            exposure = (market_value / ending * Decimal("100")) if ending > ZERO else ZERO
            pnl = ending - account.starting_equity
            pnl_pct = (pnl / account.starting_equity * Decimal("100")) if account.starting_equity > ZERO else ZERO
            dd_pct = (account.max_drawdown / account.equity_peak * Decimal("100")) if account.equity_peak > ZERO else ZERO
            print(f"  Account {index}: {key}")
            print(
                "    "
                f"start={money(account.starting_equity)} sim_end={money(ending)} "
                f"sim_pnl={money(pnl)} ({percent(pnl_pct)})"
            )
            if account.latest_actual_equity > ZERO:
                print(
                    "    "
                    f"actual_latest={money(account.latest_actual_equity)} "
                    f"sim_minus_actual={money(actual_delta)}"
                )
            print(
                "    "
                f"realized={money(account.realized_pl)} unrealized={money(unrealized)} "
                f"cash={money(account.cash)} exposure={money(market_value)} ({percent(exposure)})"
            )
            print(
                "    "
                f"fills={len(account.fills)} buys={account.counters.get('buy_fills', 0)} "
                f"sells={account.counters.get('sell_fills', 0)} open_positions={len(account.positions)} "
                f"open_orders={len(account.open_orders)}"
            )
            pf_text = f"{profit_factor:.2f}" if profit_factor is not None else "n/a"
            print(
                "    "
                f"wins={len(wins)} losses={len(losses)} win_rate={percent(win_rate)} "
                f"expectancy={money(expectancy)} profit_factor={pf_text} "
                f"max_drawdown={money(account.max_drawdown)} ({percent(dd_pct)})"
            )
            notable = Counter(account.counters)
            if notable:
                print(
                    "    "
                    + "counters="
                    + ", ".join(f"{name}={count}" for name, count in sorted(notable.items()) if count)
                )
            worst_positions = sorted(
                account.positions.values(),
                key=lambda item: item.market_value - item.cost_basis,
            )[:5]
            if worst_positions:
                print(
                    "    worst_open="
                    + ", ".join(
                        f"{position.symbol}:{money(position.market_value - position.cost_basis)}"
                        for position in worst_positions
                    )
                )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay day-tape order intents through a local fake broker.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=2, help="Most-recent tape files to replay when --path is a directory.")
    parser.add_argument(
        "--end-date",
        default="",
        help="Latest tape date to include as YYYYMMDD. Useful for excluding the current partial tape.",
    )
    parser.add_argument(
        "--slippage-bps",
        type=Decimal,
        default=Decimal("0"),
        help="Per-fill slippage in basis points. Default 0 keeps the baseline explainable.",
    )
    args = parser.parse_args()

    files = selected_files(args.path, args.days, args.end_date.strip())
    if not files:
        print(f"No day-tape files found in {args.path}")
        return 0
    simulator = DayTapeSimulator(files, slippage_bps=max(ZERO, args.slippage_bps))
    simulator.run()
    return simulator.report()


if __name__ == "__main__":
    raise SystemExit(main())
