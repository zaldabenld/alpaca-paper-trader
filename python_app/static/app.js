const fields = {
  accountSelect: document.querySelector("#accountSelect"),
  accountName: document.querySelector("#accountName"),
  profile: document.querySelector("#profile"),
  customProfileName: document.querySelector("#customProfileName"),
  apiKey: document.querySelector("#apiKey"),
  secretKey: document.querySelector("#secretKey"),
  remember: document.querySelector("#remember"),
  autoConnect: document.querySelector("#autoConnect"),
  autoStartTrading: document.querySelector("#autoStartTrading"),
  useTopVolumeSymbols: document.querySelector("#useTopVolumeSymbols"),
  symbols: document.querySelector("#symbols"),
  feed: document.querySelector("#feed"),
  useMarketStream: document.querySelector("#useMarketStream"),
  pollSeconds: document.querySelector("#pollSeconds"),
  dryRun: document.querySelector("#dryRun"),
  marketHoursOnly: document.querySelector("#marketHoursOnly"),
  useBracketOrders: document.querySelector("#useBracketOrders"),
  tradeSizeMode: document.querySelector("#tradeSizeMode"),
  maxTradeNotional: document.querySelector("#maxTradeNotional"),
  maxTradePercent: document.querySelector("#maxTradePercent"),
  maxPositionNotional: document.querySelector("#maxPositionNotional"),
  maxPositionPercent: document.querySelector("#maxPositionPercent"),
  dailyLossLimit: document.querySelector("#dailyLossLimit"),
  dailyLossLimitPercent: document.querySelector("#dailyLossLimitPercent"),
  riskPerTradePercent: document.querySelector("#riskPerTradePercent"),
  maxTotalExposurePercent: document.querySelector("#maxTotalExposurePercent"),
  maxOpenPositions: document.querySelector("#maxOpenPositions"),
  shortPeriod: document.querySelector("#shortPeriod"),
  longPeriod: document.querySelector("#longPeriod"),
  rsiPeriod: document.querySelector("#rsiPeriod"),
  buyRsiMin: document.querySelector("#buyRsiMin"),
  buyRsiMax: document.querySelector("#buyRsiMax"),
  minEntryScore: document.querySelector("#minEntryScore"),
  momentumPeriod: document.querySelector("#momentumPeriod"),
  minMomentumPercent: document.querySelector("#minMomentumPercent"),
  minRecentMomentumPercent: document.querySelector("#minRecentMomentumPercent"),
  minLongMomentumPercent: document.querySelector("#minLongMomentumPercent"),
  minSessionChangePercent: document.querySelector("#minSessionChangePercent"),
  minVwapDistancePercent: document.querySelector("#minVwapDistancePercent"),
  maxVwapDistancePercent: document.querySelector("#maxVwapDistancePercent"),
  maxSessionPullbackPercent: document.querySelector("#maxSessionPullbackPercent"),
  maxRecentPullbackPercent: document.querySelector("#maxRecentPullbackPercent"),
  lateMomentumFloorPercent: document.querySelector("#lateMomentumFloorPercent"),
  minSessionPullbackPercent: document.querySelector("#minSessionPullbackPercent"),
  maxEntryRsi: document.querySelector("#maxEntryRsi"),
  entryMode: document.querySelector("#entryMode"),
  orbMinutes: document.querySelector("#orbMinutes"),
  orbMaxBreakoutPercent: document.querySelector("#orbMaxBreakoutPercent"),
  maxEntriesPerSymbolPerDay: document.querySelector("#maxEntriesPerSymbolPerDay"),
  requireRisingPrice: document.querySelector("#requireRisingPrice"),
  maxEntriesPerScan: document.querySelector("#maxEntriesPerScan"),
  entrySpacingSeconds: document.querySelector("#entrySpacingSeconds"),
  dailyLossLimit: document.querySelector("#dailyLossLimit"),
  dailyLossLimitPercent: document.querySelector("#dailyLossLimitPercent"),
  flattenOnDailyLoss: document.querySelector("#flattenOnDailyLoss"),
  flattenBeforeCloseMinutes: document.querySelector("#flattenBeforeCloseMinutes"),
  alertTrades: document.querySelector("#alertTrades"),
  alertProblems: document.querySelector("#alertProblems"),
  smiPeriod: document.querySelector("#smiPeriod"),
  minSmi: document.querySelector("#minSmi"),
  atrPeriod: document.querySelector("#atrPeriod"),
  minBuyVolumeRatio: document.querySelector("#minBuyVolumeRatio"),
  reentryScoreBoost: document.querySelector("#reentryScoreBoost"),
  inverseEtfMode: document.querySelector("#inverseEtfMode"),
  universeMode: document.querySelector("#universeMode"),
  sellRsi: document.querySelector("#sellRsi"),
  volumePeriod: document.querySelector("#volumePeriod"),
  volumeMultiplier: document.querySelector("#volumeMultiplier"),
  minAvgVolume: document.querySelector("#minAvgVolume"),
  takeProfitPercent: document.querySelector("#takeProfitPercent"),
  breakevenAtPercent: document.querySelector("#breakevenAtPercent"),
  profitTrailStartPercent: document.querySelector("#profitTrailStartPercent"),
  profitTrailDropPercent: document.querySelector("#profitTrailDropPercent"),
  stopLossPercent: document.querySelector("#stopLossPercent"),
  stopLossGraceMinutes: document.querySelector("#stopLossGraceMinutes"),
  exitTimeInForce: document.querySelector("#exitTimeInForce"),
  cooldownMinutes: document.querySelector("#cooldownMinutes"),
  entryOpenGuardMinutes: document.querySelector("#entryOpenGuardMinutes"),
  entryCloseGuardMinutes: document.querySelector("#entryCloseGuardMinutes"),
  extensionAtrReferencePercent: document.querySelector("#extensionAtrReferencePercent"),
  scoreWeightRsi: document.querySelector("#scoreWeightRsi"),
  scoreWeightRelativeVolume: document.querySelector("#scoreWeightRelativeVolume"),
  scoreWeightMomentum: document.querySelector("#scoreWeightMomentum"),
  scoreWeightRecentMomentum: document.querySelector("#scoreWeightRecentMomentum"),
  scoreWeightLongMomentum: document.querySelector("#scoreWeightLongMomentum"),
  scoreWeightSessionChange: document.querySelector("#scoreWeightSessionChange"),
  scoreWeightVwap: document.querySelector("#scoreWeightVwap"),
  scoreWeightSmi: document.querySelector("#scoreWeightSmi"),
  scoreWeightVolatility: document.querySelector("#scoreWeightVolatility"),
  scoreWeightLiquidityBonus: document.querySelector("#scoreWeightLiquidityBonus"),
  scoreWeightFlow: document.querySelector("#scoreWeightFlow"),
  scoreWeightPullbackPenalty: document.querySelector("#scoreWeightPullbackPenalty"),
  scoreWeightOverboughtPenalty: document.querySelector("#scoreWeightOverboughtPenalty"),
  scoreWeightVolatilityPenalty: document.querySelector("#scoreWeightVolatilityPenalty"),
  scoreWeightSessionExtensionPenalty: document.querySelector("#scoreWeightSessionExtensionPenalty"),
  scoreWeightVwapExtensionPenalty: document.querySelector("#scoreWeightVwapExtensionPenalty"),
  scoreWeightSessionPullbackPenalty: document.querySelector("#scoreWeightSessionPullbackPenalty"),
  scoreWeightRecentPullbackPenalty: document.querySelector("#scoreWeightRecentPullbackPenalty"),
  scoreWeightSmiOverheatPenalty: document.querySelector("#scoreWeightSmiOverheatPenalty"),
  mostActiveCount: document.querySelector("#mostActiveCount"),
  dailyPickCount: document.querySelector("#dailyPickCount"),
  dailyMaxSymbols: document.querySelector("#dailyMaxSymbols"),
  inverseEtfSymbols: document.querySelector("#inverseEtfSymbols"),
  lookupSymbol: document.querySelector("#lookupSymbol"),
};

const appFields = {
  dailyPickMinutes: document.querySelector("#appDailyPickMinutes"),
  dailyRecheckMinutes: document.querySelector("#appDailyRecheckMinutes"),
  rvolLookbackSessions: document.querySelector("#appRvolLookbackSessions"),
  rvolMinSessions: document.querySelector("#appRvolMinSessions"),
  marketStreamSymbolLimit: document.querySelector("#appMarketStreamSymbolLimit"),
};

const els = {
  dailyUniverseStatus: document.querySelector("#dailyUniverseStatus"),
  statusText: document.querySelector("#statusText"),
  runtimeHealthBanner: document.querySelector("#runtimeHealthBanner"),
  runtimeHealthTitle: document.querySelector("#runtimeHealthTitle"),
  runtimeHealthText: document.querySelector("#runtimeHealthText"),
  runtimeNote: document.querySelector("#runtimeNote"),
  dashboardView: document.querySelector("#dashboardView"),
  accountsView: document.querySelector("#accountsView"),
  navButtons: document.querySelectorAll(".nav-button"),
  pageTitle: document.querySelector("#pageTitle"),
  settingsDrawerButton: document.querySelector("#settingsDrawerButton"),
  settingsDrawerClose: document.querySelector("#settingsDrawerClose"),
  settingsBackdrop: document.querySelector("#settingsBackdrop"),
  tradingStatusStats: document.querySelector("#tradingStatusStats"),
  dashboardMarketStatus: document.querySelector("#dashboardMarketStatus"),
  dashboardMarketStatusText: document.querySelector("#dashboardMarketStatusText"),
  dashboardMarketStatusDetail: document.querySelector("#dashboardMarketStatusDetail"),
  dashboardHaltStatus: document.querySelector("#dashboardHaltStatus"),
  dashboardHaltStatusText: document.querySelector("#dashboardHaltStatusText"),
  dashboardHaltStatusDetail: document.querySelector("#dashboardHaltStatusDetail"),
  dashboardStreamStatus: document.querySelector("#dashboardStreamStatus"),
  dashboardStreamStatusText: document.querySelector("#dashboardStreamStatusText"),
  dashboardStreamStatusDetail: document.querySelector("#dashboardStreamStatusDetail"),
  dashboardTraderStatus: document.querySelector("#dashboardTraderStatus"),
  dashboardTraderStatusText: document.querySelector("#dashboardTraderStatusText"),
  dashboardTraderStatusDetail: document.querySelector("#dashboardTraderStatusDetail"),
  reconnectStreamButton: document.querySelector("#reconnectStreamButton"),
  lookupButton: document.querySelector("#lookupButton"),
  marketOverviewToggle: document.querySelector("#marketOverviewToggle"),
  tickerTrack: document.querySelector("#tickerTrack"),
  indexCharts: document.querySelector("#indexCharts"),
  indexBoxUpdated: document.querySelector("#indexBoxUpdated"),
  newsUpdated: document.querySelector("#newsUpdated"),
  newsFlash: document.querySelector("#newsFlash"),
  newsFlashText: document.querySelector("#newsFlashText"),
  newsList: document.querySelector("#newsList"),
  lookupResult: document.querySelector("#lookupResult"),
  refreshTopVolumeButton: document.querySelector("#refreshTopVolumeButton"),
  topVolumeUpdated: document.querySelector("#topVolumeUpdated"),
  topVolumeRows: document.querySelector("#topVolumeRows"),
  credentialStatus: document.querySelector("#credentialStatus"),
  marketStatus: document.querySelector("#marketStatus"),
  marketStatusText: document.querySelector("#marketStatusText"),
  marketStatusDetail: document.querySelector("#marketStatusDetail"),
  accountCards: document.querySelector("#accountCards"),
  equity: document.querySelector("#equity"),
  dailyPl: document.querySelector("#dailyPl"),
  dailyPlDetail: document.querySelector("#dailyPlDetail"),
  realizedPl: document.querySelector("#realizedPl"),
  realizedPlDetail: document.querySelector("#realizedPlDetail"),
  buyingPower: document.querySelector("#buyingPower"),
  cash: document.querySelector("#cash"),
  cashDetail: document.querySelector("#cashDetail"),
  lastRefresh: document.querySelector("#lastRefresh"),
  strategyRows: document.querySelector("#strategyRows"),
  positionRows: document.querySelector("#positionRows"),
  positionsPercentToggle: document.querySelector("#positionsPercentToggle"),
  tradeHistoryRows: document.querySelector("#tradeHistoryRows"),
  orderRows: document.querySelector("#orderRows"),
  protectionRows: document.querySelector("#protectionRows"),
  intentRows: document.querySelector("#intentRows"),
  replayRows: document.querySelector("#replayRows"),
  replayStatus: document.querySelector("#replayStatus"),
  backtestDays: document.querySelector("#backtestDays"),
  backtestMaxEvents: document.querySelector("#backtestMaxEvents"),
  backtestLatestEvents: document.querySelector("#backtestLatestEvents"),
  runBacktestButton: document.querySelector("#runBacktestButton"),
  backtestRunStatus: document.querySelector("#backtestRunStatus"),
  backtestSummary: document.querySelector("#backtestSummary"),
  backtestDetail: document.querySelector("#backtestDetail"),
  backtestEngine: document.querySelector("#backtestEngine"),
  backtestStrategy: document.querySelector("#backtestStrategy"),
  backtestHarness: document.querySelector("#backtestHarness"),
  backtestEvaluations: document.querySelector("#backtestEvaluations"),
  backtestAccepted: document.querySelector("#backtestAccepted"),
  backtestRejected: document.querySelector("#backtestRejected"),
  backtestSource: document.querySelector("#backtestSource"),
  backtestStatus: document.querySelector("#backtestStatus"),
  backtestCheckRows: document.querySelector("#backtestCheckRows"),
  backtestAcceptedRows: document.querySelector("#backtestAcceptedRows"),
  backtestRejectedRows: document.querySelector("#backtestRejectedRows"),
  logRows: document.querySelector("#logRows"),
  newAccountButton: document.querySelector("#newAccountButton"),
  saveAccountButton: document.querySelector("#saveAccountButton"),
  removeAccountButton: document.querySelector("#removeAccountButton"),
  saveCustomProfileButton: document.querySelector("#saveCustomProfileButton"),
  profileStatus: document.querySelector("#profileStatus"),
  saveAppSettingsButton: document.querySelector("#saveAppSettingsButton"),
  appSettingsStatus: document.querySelector("#appSettingsStatus"),
  applyParametersButton: document.querySelector("#applyParametersButton"),
  parameterStatus: document.querySelector("#parameterStatus"),
  connectButton: document.querySelector("#connectButton"),
  refreshButton: document.querySelector("#refreshButton"),
  tradingToggleButton: document.querySelector("#tradingToggleButton"),
  tradingStatusBar: document.querySelector("#tradingStatusBar"),
  tradingStatusTitle: document.querySelector("#tradingStatusTitle"),
  tradingStatusDetail: document.querySelector("#tradingStatusDetail"),
  credentialKeys: document.querySelector("#credentialKeys"),
  credentialKeysSummary: document.querySelector("#credentialKeysSummary"),
  scannerAllColumnsToggle: document.querySelector("#scannerAllColumnsToggle"),
  scannerTable: document.querySelector("#scannerTable"),
  cancelOrdersButton: document.querySelector("#cancelOrdersButton"),
  purgeAccountButton: document.querySelector("#purgeAccountButton"),
  refreshAllButton: document.querySelector("#refreshAllButton"),
  tradeSizingStatus: document.querySelector("#tradeSizingStatus"),
};

const preferredAppPort = "8765";
let runtimeHealth = null;
let runtimeStale = false;

const configKeys = [
  "profile",
  "use_top_volume_symbols",
  "feed",
  "use_market_stream",
  "poll_seconds",
  "dry_run",
  "market_hours_only",
  "use_bracket_orders",
  "trade_size_mode",
  "max_trade_notional",
  "max_trade_percent",
  "max_position_notional",
  "max_position_percent",
  "daily_loss_limit",
  "daily_loss_limit_percent",
  "risk_per_trade_percent",
  "max_total_exposure_percent",
  "max_open_positions",
  "short_period",
  "long_period",
  "rsi_period",
  "buy_rsi_min",
  "buy_rsi_max",
  "min_entry_score",
  "momentum_period",
  "min_momentum_percent",
  "min_recent_momentum_percent",
  "min_long_momentum_percent",
  "min_session_change_percent",
  "min_vwap_distance_percent",
  "max_vwap_distance_percent",
  "max_session_pullback_percent",
  "max_recent_pullback_percent",
  "late_momentum_floor_percent",
  "min_session_pullback_percent",
  "max_entry_rsi",
  "max_entries_per_symbol_per_day",
  "require_rising_price",
  "max_entries_per_scan",
  "entry_spacing_seconds",
  "flatten_on_daily_loss",
  "flatten_before_close_minutes",
  "alert_trades",
  "alert_problems",
  "smi_period",
  "min_smi",
  "atr_period",
  "min_buy_volume_ratio",
  "reentry_score_boost",
  "inverse_etf_mode",
  "universe_mode",
  "entry_mode",
  "orb_minutes",
  "orb_max_breakout_percent",
  "sell_rsi",
  "volume_period",
  "volume_multiplier",
  "min_avg_volume",
  "take_profit_percent",
  "breakeven_at_percent",
  "profit_trail_start_percent",
  "profit_trail_drop_percent",
  "stop_loss_percent",
  "stop_loss_grace_minutes",
  "exit_time_in_force",
  "cooldown_minutes",
  "entry_open_guard_minutes",
  "entry_close_guard_minutes",
  "extension_atr_reference_percent",
  "score_weight_rsi",
  "score_weight_relative_volume",
  "score_weight_momentum",
  "score_weight_recent_momentum",
  "score_weight_long_momentum",
  "score_weight_session_change",
  "score_weight_vwap",
  "score_weight_smi",
  "score_weight_volatility",
  "score_weight_liquidity_bonus",
  "score_weight_flow",
  "score_weight_pullback_penalty",
  "score_weight_overbought_penalty",
  "score_weight_volatility_penalty",
  "score_weight_session_extension_penalty",
  "score_weight_vwap_extension_penalty",
  "score_weight_session_pullback_penalty",
  "score_weight_recent_pullback_penalty",
  "score_weight_smi_overheat_penalty",
  "most_active_count",
  "daily_pick_count",
  "daily_max_symbols",
];

const strategyProfileKeys = new Set([
  "short_period",
  "long_period",
  "rsi_period",
  "buy_rsi_min",
  "buy_rsi_max",
  "min_entry_score",
  "momentum_period",
  "min_momentum_percent",
  "min_recent_momentum_percent",
  "min_long_momentum_percent",
  "min_session_change_percent",
  "min_vwap_distance_percent",
  "max_vwap_distance_percent",
  "max_session_pullback_percent",
  "max_recent_pullback_percent",
  "late_momentum_floor_percent",
  "min_session_pullback_percent",
  "max_entry_rsi",
  "max_entries_per_symbol_per_day",
  "require_rising_price",
  "smi_period",
  "min_smi",
  "atr_period",
  "min_buy_volume_ratio",
  "reentry_score_boost",
  "inverse_etf_mode",
  "universe_mode",
  "entry_mode",
  "orb_minutes",
  "orb_max_breakout_percent",
  "sell_rsi",
  "volume_period",
  "volume_multiplier",
  "min_avg_volume",
  "take_profit_percent",
  "breakeven_at_percent",
  "profit_trail_start_percent",
  "profit_trail_drop_percent",
  "stop_loss_percent",
  "stop_loss_grace_minutes",
  "cooldown_minutes",
  "entry_open_guard_minutes",
  "entry_close_guard_minutes",
  "extension_atr_reference_percent",
  "score_weight_rsi",
  "score_weight_relative_volume",
  "score_weight_momentum",
  "score_weight_recent_momentum",
  "score_weight_long_momentum",
  "score_weight_session_change",
  "score_weight_vwap",
  "score_weight_smi",
  "score_weight_volatility",
  "score_weight_liquidity_bonus",
  "score_weight_flow",
  "score_weight_pullback_penalty",
  "score_weight_overbought_penalty",
  "score_weight_volatility_penalty",
  "score_weight_session_extension_penalty",
  "score_weight_vwap_extension_penalty",
  "score_weight_session_pullback_penalty",
  "score_weight_recent_pullback_penalty",
  "score_weight_smi_overheat_penalty",
  "most_active_count",
  "daily_pick_count",
  "daily_max_symbols",
  "inverse_etf_symbols",
]);

let savedAccounts = [];
let profiles = {};
let selectedAccountId = "";
let isDraftAccount = false;
let selectedTradingEnabled = false;
let selectedConnected = false;
let selectedLiveDryRun = null;
let selectedRisk = {};
let selectedStats = { scanned: 0, positions: 0, protectedCount: 0 };
let credentialKeysCollapsedFor = "";
let accountContextVersion = 0;
let accountTransitionDepth = 0;
const requestChannels = {
  health: { sequence: 0, controller: null },
  state: { sequence: 0, controller: null },
  dashboard: { sequence: 0, controller: null },
};
const sortableTables = {
  topVolumeRows: {
    defaultKey: "rank_raw",
    defaultDirection: "asc",
    columns: [
      "rank_raw",
      "symbol",
      "buy_volume_raw",
      "sell_volume_raw",
      "unclassified_volume_raw",
      "stream_volume_raw",
      "total_volume_raw",
      "trade_count_raw",
      "last_price_raw",
      "last_trade_side",
      "trading_status",
      "halted_raw",
    ],
  },
  strategyRows: {
    defaultKey: "entry_score_raw",
    defaultDirection: "desc",
    columns: [
      "symbol",
      "price",
      "rsi",
      "volume",
      "relative_volume",
      "volatility_raw",
      "momentum_raw",
      "long_momentum_raw",
      "session_change_raw",
      "vwap_distance_raw",
      "smi_raw",
      "atr_raw",
      "volume_ok",
      "entry_score_raw",
      "bars",
      "last_action",
    ],
  },
  positionRows: {
    defaultKey: "unrealized_pl_raw",
    defaultDirection: "desc",
    columns: [
      "symbol",
      "side",
      "qty_raw",
      "avg_entry_raw",
      "cost_basis_raw",
      "current_price_raw",
      "market_value_raw",
      "unrealized_pl_raw",
      "intraday_pl_raw",
      "protection",
    ],
  },
  tradeHistoryRows: {
    defaultKey: "filled",
    defaultDirection: "desc",
    columns: [
      "filled",
      "symbol",
      "side",
      "filled_qty",
      "avg_fill",
      "value_raw",
      "cost_basis_raw",
      "realized_pl_raw",
      "realized_pl_pct_raw",
      "result",
      "exit_reason",
      "status",
      "source",
    ],
  },
  orderRows: {
    defaultKey: "submitted",
    defaultDirection: "desc",
    columns: [
      "symbol",
      "side",
      "type",
      "qty",
      "status",
      "role",
      "time_in_force",
      "order_class",
      "submitted",
      "client_order_id",
    ],
  },
  protectionRows: {
    defaultKey: "unrealized_pl",
    defaultDirection: "desc",
    columns: [
      "symbol",
      "qty",
      "market_value",
      "unrealized_pl",
      "status",
      "protective_orders",
      "strategy_exits",
      "manual_orders",
      "detail",
    ],
  },
  intentRows: {
    defaultKey: "time",
    defaultDirection: "desc",
    columns: ["time", "symbol", "side", "qty", "role", "status", "client_order_id", "order_id", "reason"],
  },
  replayRows: {
    defaultKey: "time",
    defaultDirection: "desc",
    columns: ["time", "kind", "summary"],
  },
  backtestCheckRows: {
    defaultKey: "name",
    defaultDirection: "asc",
    columns: ["name", "status", "detail"],
  },
  backtestAcceptedRows: {
    defaultKey: "score",
    defaultDirection: "desc",
    columns: ["symbol", "score", "entry_price", "qty", "notional"],
  },
  backtestRejectedRows: {
    defaultKey: "symbol",
    defaultDirection: "asc",
    columns: ["symbol", "reason"],
  },
};

function selectedAccountKey(accountId = selectedAccountId) {
  return accountId || "";
}

function beginRequest(channelName, options = {}) {
  const channel = requestChannels[channelName];
  if (!channel) throw new Error(`Unknown request channel ${channelName}`);
  if (options.abortPrevious !== false && channel.controller) {
    channel.controller.abort();
  }
  const controller = typeof AbortController === "undefined" ? null : new AbortController();
  channel.controller = controller;
  channel.sequence += 1;
  return {
    channel,
    sequence: channel.sequence,
    accountId: selectedAccountKey(options.accountId ?? selectedAccountId),
    contextVersion: accountContextVersion,
    allowSelectedAccountChange: Boolean(options.allowSelectedAccountChange),
    requireResponseAccountMatch: options.requireResponseAccountMatch !== false,
    signal: controller?.signal,
    source: options.source || channelName,
  };
}

function abortRequestChannel(channelName) {
  const channel = requestChannels[channelName];
  if (channel?.controller) {
    channel.controller.abort();
    channel.controller = null;
  }
}

function invalidateAccountContext() {
  accountContextVersion += 1;
  abortRequestChannel("state");
  abortRequestChannel("dashboard");
  return accountContextVersion;
}

function isLatestRequest(request) {
  return request?.channel?.sequence === request.sequence;
}

function isCurrentAccountContext(context) {
  if (!context) return true;
  if (context.contextVersion !== accountContextVersion) return false;
  return context.allowSelectedAccountChange || context.accountId === selectedAccountKey();
}

function isCurrentAccountRequest(request) {
  return isLatestRequest(request) && isCurrentAccountContext(request);
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function makeRenderContext(accountId = selectedAccountId, options = {}) {
  return {
    accountId: selectedAccountKey(accountId),
    contextVersion: accountContextVersion,
    allowSelectedAccountChange: Boolean(options.allowSelectedAccountChange),
    requireResponseAccountMatch: options.requireResponseAccountMatch !== false,
  };
}

function responseSelectedAccountId(state = {}) {
  return selectedAccountKey(state.selected_account_id || state.selected?.account_id || "");
}

function stateMatchesRenderContext(state, context) {
  if (!isCurrentAccountContext(context)) return false;
  if (!context?.requireResponseAccountMatch) return true;
  const responseAccountId = responseSelectedAccountId(state);
  return !context.accountId || !responseAccountId || responseAccountId === context.accountId;
}

async function withAccountTransition(callback) {
  const transitionVersion = invalidateAccountContext();
  accountTransitionDepth += 1;
  try {
    return await callback(transitionVersion);
  } finally {
    accountTransitionDepth = Math.max(0, accountTransitionDepth - 1);
  }
}

function isTransitionCurrent(transitionVersion) {
  return transitionVersion === accountContextVersion;
}
const tableSorts = Object.fromEntries(
  Object.entries(sortableTables).map(([tableId, config]) => [
    tableId,
    {
      key: config.defaultKey || config.columns[0],
      direction: config.defaultDirection || defaultSortDirection(config.defaultKey || config.columns[0]),
    },
  ])
);
const tableRenderCache = {};
let currentTopVolumeRows = [];
let currentPositionRows = [];
let currentTradeHistoryRows = [];
let currentSelectedAccount = {};
let showPositionPlPercent = false;
let suppressProfileDirty = false;
let staleInstanceRedirecting = false;
let lastStreamRecoveryAt = 0;
let parameterDirty = false;

setupSortableTables();

els.navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    showView(button.dataset.view);
  });
});

els.positionsPercentToggle.addEventListener("change", () => {
  showPositionPlPercent = els.positionsPercentToggle.checked;
  renderPositionRows();
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}`).classList.add("active");
  });
});

els.settingsDrawerButton?.addEventListener("click", () => setSettingsDrawer(!document.body.classList.contains("settings-open")));
els.settingsDrawerClose?.addEventListener("click", () => {
  setSettingsDrawer(false);
  els.settingsDrawerButton?.focus();
});
els.settingsBackdrop?.addEventListener("click", () => {
  setSettingsDrawer(false);
  els.settingsDrawerButton?.focus();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("settings-open")) {
    setSettingsDrawer(false);
    els.settingsDrawerButton?.focus();
  }
});

// Light / Dark / Auto (follow the system). The choice is remembered per browser profile.
function applyThemeChoice(choice) {
  if (choice === "light" || choice === "dark") {
    document.documentElement.dataset.theme = choice;
  } else {
    delete document.documentElement.dataset.theme;
  }
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    const selected = button.dataset.themeChoice === (choice || "system");
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

let savedThemeChoice = "system";
try {
  savedThemeChoice = localStorage.getItem("apt-theme") || "system";
} catch {
  savedThemeChoice = "system";
}
applyThemeChoice(savedThemeChoice);
document.querySelectorAll("[data-theme-choice]").forEach((button) => {
  button.addEventListener("click", () => {
    const choice = button.dataset.themeChoice;
    try {
      if (choice === "system") localStorage.removeItem("apt-theme");
      else localStorage.setItem("apt-theme", choice);
    } catch {
      // storage unavailable: the choice still applies for this session
    }
    applyThemeChoice(choice);
  });
});

// Details tab sub-panels use their own classes so the .tab handler above never hides them.
document.querySelectorAll("#detailsPanel .subtab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("#detailsPanel .subtab").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll("#detailsPanel .subtab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === button.dataset.subtab);
    });
  });
});

els.scannerAllColumnsToggle?.addEventListener("change", () => {
  els.scannerTable?.classList.toggle("scanner-compact", !els.scannerAllColumnsToggle.checked);
});

fields.dryRun.addEventListener("change", () => renderTradingToggle());

fields.accountSelect.addEventListener("change", async () => {
  await switchToAccount(fields.accountSelect.value);
});

fields.profile.addEventListener("change", async () => {
  await applyProfilePreset();
});

fields.remember.addEventListener("change", syncAutoConnectControl);
fields.autoConnect.addEventListener("change", syncAutoConnectControl);

els.saveCustomProfileButton.addEventListener("click", saveCustomProfile);
els.saveAppSettingsButton.addEventListener("click", saveAppSettings);

configKeys
  .filter((key) => key !== "profile")
  .forEach((key) => {
    const field = fields[toCamel(key)];
    if (!field) return;
    field.addEventListener("input", () => handleConfigFieldChange(key));
    field.addEventListener("change", () => handleConfigFieldChange(key));
  });

fields.inverseEtfSymbols.addEventListener("input", () => handleConfigFieldChange("inverse_etf_symbols"));
fields.inverseEtfSymbols.addEventListener("change", () => handleConfigFieldChange("inverse_etf_symbols"));

els.newAccountButton.addEventListener("click", async () => {
  await switchToAccount("");
});

els.saveAccountButton.addEventListener("click", async () => {
  const context = makeRenderContext(selectedAccountId, {
    allowSelectedAccountChange: !selectedAccountId || isDraftAccount,
  });
  await saveCurrentAccountDraft(true, { guard: () => isCurrentAccountContext(context) });
  parameterDirty = false;
  await loadSettings({ guard: () => isCurrentAccountContext(context) });
  await loadState({ accountId: selectedAccountId, source: "save-account" });
});

els.removeAccountButton.addEventListener("click", async () => {
  if (!selectedAccountId) return;
  const context = makeRenderContext(selectedAccountId, { allowSelectedAccountChange: true });
  const account = findSavedAccount(selectedAccountId);
  const name = account?.name || "this account";
  if (!window.confirm(`Remove ${name} from the app? Connected trading for it will stop.`)) return;
  const removed = await fetchWithRecovery(`/api/accounts/${encodeURIComponent(selectedAccountId)}`, {
    method: "DELETE",
    headers: apiHeaders(),
  });
  if (!removed.ok) await reloadIfTokenRejected(removed);
  await loadSettings({ guard: () => isCurrentAccountContext(context) });
  await loadState({ accountId: selectedAccountId, source: "remove-account" });
});

els.connectButton.addEventListener("click", async () => {
  const context = makeRenderContext(selectedAccountId, {
    allowSelectedAccountChange: !selectedAccountId || isDraftAccount,
  });
  const state = await postJson("/api/connect", readAccountPayload());
  selectedAccountId = state.selected_account_id || state.selected?.account_id || selectedAccountId;
  await loadSettings({ guard: () => isCurrentAccountContext(context) });
  if (renderState(state, context)) {
    await loadDashboard({ accountId: selectedAccountId, source: "connect" });
  }
});

els.refreshButton.addEventListener("click", async () => {
  const context = makeRenderContext();
  await postJson("/api/accounts", readAccountPayload());
  parameterDirty = false;
  const state = await postJson("/api/refresh", { account_id: selectedAccountId || null });
  await loadSettings({ guard: () => isCurrentAccountContext(context) });
  if (renderState(state, context)) {
    await loadDashboard({ accountId: selectedAccountId, source: "refresh" });
  }
});

els.applyParametersButton.addEventListener("click", applyCurrentParameters);

els.refreshAllButton.addEventListener("click", async () => {
  const context = makeRenderContext();
  const state = await postJson("/api/refresh-all", {});
  if (renderState(state, context)) {
    await loadDashboard({ accountId: selectedAccountId, source: "refresh-all" });
  }
});

els.tradingToggleButton.addEventListener("click", async () => {
  const wasTrading = selectedTradingEnabled;
  const previousText = els.tradingToggleButton.textContent;
  els.tradingToggleButton.disabled = true;
  els.tradingToggleButton.textContent = wasTrading ? "Stopping..." : "Starting...";
  try {
    const context = makeRenderContext();
    let state;
    if (wasTrading) {
      state = await postJson("/api/stop", { account_id: selectedAccountId || null });
    } else {
      await postJson("/api/accounts", readAccountPayload());
      parameterDirty = false;
      state = await postJson("/api/start", { account_id: selectedAccountId || null });
      await loadSettings({ guard: () => isCurrentAccountContext(context) });
    }
    if (renderState(state, context)) {
      await loadDashboard({ accountId: selectedAccountId, source: "trading-toggle" });
    }
  } catch (error) {
    const failure = `${wasTrading ? "Stop" : "Start"} failed: ${error.message}`;
    els.parameterStatus.textContent = failure;
    if (els.tradingStatusDetail) els.tradingStatusDetail.textContent = failure;
    els.tradingToggleButton.textContent = previousText;
    els.tradingToggleButton.disabled = !selectedConnected;
  }
});

els.cancelOrdersButton.addEventListener("click", async () => {
  if (!window.confirm("Cancel all open paper orders for the selected account?")) return;
  const context = makeRenderContext();
  const state = await postJson("/api/cancel-orders", { account_id: selectedAccountId || null });
  renderState(state, context);
});

els.purgeAccountButton.addEventListener("click", async () => {
  const account = findSavedAccount(selectedAccountId);
  const name = account?.name || "the selected account";
  const confirmed = window.confirm(
    `Purge ${name}? This stops auto trading, cancels open orders, submits paper market sell orders for every current position, and resets strategy state. Trade history, ledger, replay, logs, and saved settings stay preserved.`
  );
  if (!confirmed) return;
  const context = makeRenderContext();
  const state = await postJson("/api/purge-account", { account_id: selectedAccountId || null });
  if (renderState(state, context)) {
    await loadDashboard({ accountId: selectedAccountId, source: "purge-account" });
  }
});

els.refreshTopVolumeButton.addEventListener("click", async () => {
  const context = makeRenderContext();
  const dashboard = await postJson("/api/dashboard/top-volume", { account_id: context.accountId || null });
  renderDashboard(dashboard, context);
});

els.reconnectStreamButton.addEventListener("click", reconnectDashboardStream);

els.lookupButton.addEventListener("click", lookupSymbol);

fields.lookupSymbol.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  await lookupSymbol();
});

if (els.runBacktestButton) {
  els.runBacktestButton.addEventListener("click", runDayTapeBacktest);
}

function showView(viewId) {
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  const target = document.querySelector(`#${viewId}`);
  if (target) target.classList.add("active");
  els.navButtons.forEach((button) => {
    const active = button.dataset.view === viewId;
    button.classList.toggle("active", active);
    if (active && els.pageTitle) els.pageTitle.textContent = button.textContent.trim();
  });
  if (viewId !== "accountsView") setSettingsDrawer(false);
}

// Account settings live in a slide-out drawer so the tables get the full width.
function setSettingsDrawer(open) {
  document.body.classList.toggle("settings-open", open);
  els.settingsDrawerButton?.setAttribute("aria-expanded", String(open));
  // While open the drawer is modal: the page behind it can't take focus or clicks.
  document
    .querySelectorAll(".side-rail, .topbar, .account-bar, #tradingStatusBar, .workspace, #runtimeHealthBanner, #runtimeNote")
    .forEach((element) => {
      element.inert = open;
    });
  if (open) els.settingsDrawerClose?.focus();
}

let settingsDrawerAutoOpenedFor = null;

// Open the drawer once per account when it still needs API keys (only on the Accounts page).
function autoOpenSettingsForMissingKeys(hasCredentials) {
  const key = selectedAccountId || "draft";
  if (hasCredentials || settingsDrawerAutoOpenedFor === key) return;
  if (!document.querySelector("#accountsView")?.classList.contains("active")) return;
  settingsDrawerAutoOpenedFor = key;
  setSettingsDrawer(true);
}

function readAccountPayload() {
  return {
    account_id: selectedAccountId || null,
    name: fields.accountName.value.trim() || "Paper Account",
    api_key: fields.apiKey.value.trim(),
    secret_key: fields.secretKey.value.trim(),
    remember: fields.remember.checked,
    auto_connect: fields.remember.checked && fields.autoConnect.checked,
    auto_start_trading: fields.remember.checked && fields.autoConnect.checked && fields.autoStartTrading.checked,
    config: readConfig(),
  };
}

function hasAccountFormData() {
  return Boolean(
    fields.accountName.value.trim() ||
      fields.apiKey.value.trim() ||
      fields.secretKey.value.trim() ||
      fields.symbols.value.trim()
  );
}

async function switchToAccount(nextAccountId) {
  const previousAccountId = selectedAccountId;
  await withAccountTransition(async (transitionVersion) => {
    try {
      if (previousAccountId || hasAccountFormData()) {
        await saveCurrentAccountDraft(false, { guard: () => isTransitionCurrent(transitionVersion) });
      }
    } catch (error) {
      if (isTransitionCurrent(transitionVersion)) {
        fields.accountSelect.value = previousAccountId;
      }
      throw error;
    }

    if (!isTransitionCurrent(transitionVersion)) return;

    selectedAccountId = nextAccountId || "";
    fields.accountSelect.value = selectedAccountId;
    if (!selectedAccountId) {
      isDraftAccount = true;
      applyAccount({
        account_id: "",
        name: `Account ${savedAccounts.length + 1}`,
        api_key: "",
        secret_key: "",
        remember: true,
        auto_connect: true,
        auto_start_trading: false,
        config: presetConfig("neutral"),
      });
      els.statusText.textContent = "New account draft";
      return;
    }

    isDraftAccount = false;
    const account = findSavedAccount(selectedAccountId);
    if (account) applyAccount(account);
    await postJson("/api/select-account", { account_id: selectedAccountId });
    if (!isTransitionCurrent(transitionVersion)) return;
    await loadState({ accountId: selectedAccountId, source: "account-switch" });
    await loadDashboard({ accountId: selectedAccountId, source: "account-switch" });
  });
}

async function saveCurrentAccountDraft(applySavedAccount = true, options = {}) {
  const state = await postJson("/api/accounts", readAccountPayload());
  if (options.guard && !options.guard()) return state;
  selectedAccountId = state.selected_account_id || state.selected?.account_id || selectedAccountId;
  isDraftAccount = false;
  parameterDirty = false;
  await loadSettings({ applySelected: applySavedAccount, guard: options.guard });
  return state;
}

function readConfig() {
  const tradeSizeMode = fields.tradeSizeMode.value || "percent";
  const tradeNotional = tradeSizeMode === "notional" ? readNumber("maxTradeNotional", 35) : 0;
  const tradePercent = tradeSizeMode === "percent" ? readNumber("maxTradePercent", 7) : 0;
  return {
    profile: fields.profile.value,
    use_top_volume_symbols: fields.useTopVolumeSymbols.checked,
    symbols: fields.symbols.value
      .split(",")
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean),
    feed: fields.feed.value,
    poll_seconds: readInt("pollSeconds", 5),
    dry_run: fields.dryRun.checked,
    market_hours_only: fields.marketHoursOnly.checked,
    use_market_stream: fields.useMarketStream.checked,
    use_bracket_orders: fields.useBracketOrders.checked,
    trade_size_mode: tradeSizeMode,
    max_trade_notional: tradeNotional,
    max_trade_percent: tradePercent,
    max_position_notional: readNumber("maxPositionNotional", 35),
    max_position_percent: readNumber("maxPositionPercent", 7),
    daily_loss_limit: readNumber("dailyLossLimit", 0),
    daily_loss_limit_percent: readNumber("dailyLossLimitPercent", 0),
    risk_per_trade_percent: readNumber("riskPerTradePercent", 0),
    max_total_exposure_percent: readNumber("maxTotalExposurePercent", 25),
    max_open_positions: readInt("maxOpenPositions", 3),
    short_period: readInt("shortPeriod", 9),
    long_period: readInt("longPeriod", 21),
    rsi_period: readInt("rsiPeriod", 14),
    buy_rsi_min: readNumber("buyRsiMin", 42),
    buy_rsi_max: readNumber("buyRsiMax", 68),
    min_entry_score: readNumber("minEntryScore", 44),
    momentum_period: readInt("momentumPeriod", 6),
    min_momentum_percent: readNumber("minMomentumPercent", 0.08),
    min_recent_momentum_percent: readNumber("minRecentMomentumPercent", 0.05),
    min_long_momentum_percent: readNumber("minLongMomentumPercent", 0.05),
    min_session_change_percent: readNumber("minSessionChangePercent", 1.35),
    min_vwap_distance_percent: readNumber("minVwapDistancePercent", 0.05),
    max_vwap_distance_percent: readNumber("maxVwapDistancePercent", 2.25),
    max_session_pullback_percent: readNumber("maxSessionPullbackPercent", 0.9),
    max_recent_pullback_percent: readNumber("maxRecentPullbackPercent", 0.55),
    late_momentum_floor_percent: readNumber("lateMomentumFloorPercent", 0.5),
    min_session_pullback_percent: readNumber("minSessionPullbackPercent", 0),
    max_entry_rsi: readNumber("maxEntryRsi", 0),
    max_entries_per_symbol_per_day: readInt("maxEntriesPerSymbolPerDay", 0),
    require_rising_price: fields.requireRisingPrice.checked,
    max_entries_per_scan: readInt("maxEntriesPerScan", 2),
    entry_spacing_seconds: readInt("entrySpacingSeconds", 0),
    flatten_on_daily_loss: fields.flattenOnDailyLoss.checked,
    flatten_before_close_minutes: readInt("flattenBeforeCloseMinutes", 0),
    alert_trades: fields.alertTrades.checked,
    alert_problems: fields.alertProblems.checked,
    smi_period: readInt("smiPeriod", 10),
    min_smi: readNumber("minSmi", 40),
    atr_period: readInt("atrPeriod", 14),
    min_buy_volume_ratio: readNumber("minBuyVolumeRatio", 0.5),
    reentry_score_boost: readNumber("reentryScoreBoost", 12),
    inverse_etf_mode: fields.inverseEtfMode.value,
    universe_mode: fields.universeMode.value,
    entry_mode: fields.entryMode.value,
    orb_minutes: readInt("orbMinutes", 15),
    orb_max_breakout_percent: readNumber("orbMaxBreakoutPercent", 1),
    sell_rsi: readNumber("sellRsi", 72),
    volume_period: readInt("volumePeriod", 20),
    volume_multiplier: readNumber("volumeMultiplier", 1.5),
    min_avg_volume: readNumber("minAvgVolume", 0),
    take_profit_percent: readNumber("takeProfitPercent", 2.5),
    breakeven_at_percent: readNumber("breakevenAtPercent", 0),
    profit_trail_start_percent: readNumber("profitTrailStartPercent", 0),
    profit_trail_drop_percent: readNumber("profitTrailDropPercent", 0),
    stop_loss_percent: readNumber("stopLossPercent", 1.25),
    stop_loss_grace_minutes: readInt("stopLossGraceMinutes", 0),
    exit_time_in_force: fields.exitTimeInForce.value,
    cooldown_minutes: readInt("cooldownMinutes", 0),
    entry_open_guard_minutes: readInt("entryOpenGuardMinutes", 15),
    entry_close_guard_minutes: readInt("entryCloseGuardMinutes", 15),
    extension_atr_reference_percent: readNumber("extensionAtrReferencePercent", 0),
    score_weight_rsi: readNumber("scoreWeightRsi", 5),
    score_weight_relative_volume: readNumber("scoreWeightRelativeVolume", 13),
    score_weight_momentum: readNumber("scoreWeightMomentum", 14),
    score_weight_recent_momentum: readNumber("scoreWeightRecentMomentum", 8),
    score_weight_long_momentum: readNumber("scoreWeightLongMomentum", 14),
    score_weight_session_change: readNumber("scoreWeightSessionChange", 16),
    score_weight_vwap: readNumber("scoreWeightVwap", 14),
    score_weight_smi: readNumber("scoreWeightSmi", 7),
    score_weight_volatility: readNumber("scoreWeightVolatility", 0),
    score_weight_liquidity_bonus: readNumber("scoreWeightLiquidityBonus", 1.5),
    score_weight_flow: readNumber("scoreWeightFlow", 3),
    score_weight_pullback_penalty: readNumber("scoreWeightPullbackPenalty", 0),
    score_weight_overbought_penalty: readNumber("scoreWeightOverboughtPenalty", 0),
    score_weight_volatility_penalty: readNumber("scoreWeightVolatilityPenalty", 4),
    score_weight_session_extension_penalty: readNumber("scoreWeightSessionExtensionPenalty", 4),
    score_weight_vwap_extension_penalty: readNumber("scoreWeightVwapExtensionPenalty", 10),
    score_weight_session_pullback_penalty: readNumber("scoreWeightSessionPullbackPenalty", 9),
    score_weight_recent_pullback_penalty: readNumber("scoreWeightRecentPullbackPenalty", 6),
    score_weight_smi_overheat_penalty: readNumber("scoreWeightSmiOverheatPenalty", 4),
    most_active_count: readInt("mostActiveCount", 100),
    daily_pick_count: readInt("dailyPickCount", 25),
    daily_max_symbols: readInt("dailyMaxSymbols", 40),
    inverse_etf_symbols: fields.inverseEtfSymbols.value
      .split(/[\s,]+/)
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean),
  };
}

function applyAccount(account) {
  selectedAccountId = account.account_id || "";
  isDraftAccount = !selectedAccountId;
  parameterDirty = false;
  fields.accountName.value = account.name || "Paper Account";
  fields.apiKey.value = "";
  fields.secretKey.value = "";
  fields.remember.checked = account.remember !== false;
  fields.autoConnect.checked = account.auto_connect !== false;
  fields.autoStartTrading.checked = Boolean(account.auto_start_trading);
  syncAutoConnectControl();
  if (credentialKeysCollapsedFor !== (selectedAccountId || "draft")) credentialKeysCollapsedFor = "";
  renderCredentialStatus(account);
  applyConfig(account.config || presetConfig("neutral"));
}

function inferTradeSizeMode(config = {}) {
  if (config.trade_size_mode) return config.trade_size_mode;
  const notional = Number(config.max_trade_notional || 0);
  const percent = Number(config.max_trade_percent || 0);
  if (Number.isFinite(notional) && notional > 0 && (!Number.isFinite(percent) || percent <= 0)) return "notional";
  if (Number.isFinite(percent) && percent > 0) return "percent";
  return "exposure_slot";
}

function tradeSizeLabel(config = {}) {
  const mode = config.trade_size_mode || inferTradeSizeMode(config);
  if (mode === "notional") return `$${Number(config.max_trade_notional || 0).toLocaleString()} per entry`;
  if (mode === "exposure_slot") return "exposure slot";
  return `${config.max_trade_percent || 0}% equity`;
}

function syncTradeSizeModeControl(config = readConfig()) {
  const mode = fields.tradeSizeMode.value || config.trade_size_mode || "percent";
  fields.maxTradeNotional.disabled = mode !== "notional";
  fields.maxTradePercent.disabled = mode !== "percent";
  if (els.tradeSizingStatus) {
    els.tradeSizingStatus.textContent =
      mode === "notional"
        ? "Fixed dollar amount is active; the percent field is ignored."
        : mode === "exposure_slot"
          ? "Each trade gets an equal share of the exposure limit; both fields are ignored."
          : "Percent of account is active; the dollar field is ignored.";
  }
}

function syncAutoConnectControl() {
  fields.autoConnect.disabled = !fields.remember.checked;
  fields.autoStartTrading.disabled = !fields.remember.checked || !fields.autoConnect.checked;
  if (!fields.remember.checked) {
    fields.autoConnect.checked = false;
  }
  if (fields.autoStartTrading.disabled) {
    fields.autoStartTrading.checked = false;
  }
}

function renderCredentialStatus(account = {}) {
  const sessionCredentials = Boolean(
    account.credentials_loaded || account.connected || (account.has_api_key && account.has_secret_key)
  );
  const savedCredentials = Boolean(account.credentials_saved);
  els.credentialStatus.textContent = savedCredentials
    ? "API keys saved on this computer. Leave the key fields blank to keep them."
    : sessionCredentials
      ? "API keys loaded for this session only. Tick \"Remember keys\" to connect automatically next launch."
      : "No API keys yet. Enter this account's Alpaca paper keys.";
  const hasCredentials = savedCredentials || sessionCredentials;
  els.credentialStatus.classList.toggle("saved", hasCredentials);
  if (els.credentialKeys) {
    if (!hasCredentials) {
      els.credentialKeys.open = true;
      credentialKeysCollapsedFor = "";
    } else if (credentialKeysCollapsedFor !== (selectedAccountId || "draft")) {
      els.credentialKeys.open = false;
      credentialKeysCollapsedFor = selectedAccountId || "draft";
    }
  }
  if (els.credentialKeysSummary) {
    els.credentialKeysSummary.textContent = hasCredentials ? "Keys saved \u2713 \u00b7 Change keys" : "Enter API keys";
  }
  autoOpenSettingsForMissingKeys(hasCredentials);
  const placeholderPrefix = savedCredentials ? "Saved encrypted" : "Session credential";
  fields.apiKey.placeholder = hasCredentials ? `${placeholderPrefix} - enter new key to replace` : "Enter API key";
  fields.secretKey.placeholder = hasCredentials ? `${placeholderPrefix} - enter new secret to replace` : "Enter secret key";
}

function applyConfig(config) {
  if (!config) return;
  suppressProfileDirty = true;
  const normalizedConfig = {
    ...config,
    trade_size_mode: config.trade_size_mode || inferTradeSizeMode(config),
  };
  ensureProfileOption(config.profile || "custom", profileLabel(config.profile || "custom", config));
  fields.symbols.value = (normalizedConfig.symbols || ["SPY", "QQQ"]).join(",");
  fields.inverseEtfSymbols.value = (normalizedConfig.inverse_etf_symbols || ["SQQQ", "SPXU", "SDS", "SH", "TZA"]).join(", ");
  configKeys.forEach((key) => {
    const camel = toCamel(key);
    const field = fields[camel];
    if (!field || normalizedConfig[key] === undefined || normalizedConfig[key] === null) return;
    if (field.type === "checkbox") {
      field.checked = Boolean(normalizedConfig[key]);
    } else {
      field.value = normalizedConfig[key];
    }
  });
  syncTradeSizeModeControl(normalizedConfig);
  suppressProfileDirty = false;
  renderProfileStatus();
}

async function applyProfilePreset() {
  const context = makeRenderContext();
  const config = await postJson("/api/profile", {
    profile: fields.profile.value,
    current: readConfig(),
  });
  if (!isCurrentAccountContext(context)) return;
  applyConfig(config);
  parameterDirty = true;
  renderParameterStatus(null);
}

async function applyCurrentParameters() {
  const previousText = els.applyParametersButton.textContent;
  els.applyParametersButton.disabled = true;
  els.applyParametersButton.textContent = "Applying...";
  els.parameterStatus.textContent = "Applying current setup to the selected account...";
  try {
    const context = makeRenderContext(selectedAccountId, {
      allowSelectedAccountChange: !selectedAccountId || isDraftAccount,
    });
    const state = await postJson("/api/apply-parameters", readAccountPayload());
    selectedAccountId = state.selected_account_id || state.selected?.account_id || selectedAccountId;
    isDraftAccount = false;
    parameterDirty = false;
    await loadSettings({ applySelected: false, guard: () => isCurrentAccountContext(context) });
    if (renderState(state, context)) {
      await loadDashboard({ accountId: selectedAccountId, source: "apply-parameters" });
    }
  } catch (error) {
    els.parameterStatus.textContent = `Apply failed: ${error.message}`;
  } finally {
    els.applyParametersButton.disabled = false;
    els.applyParametersButton.textContent = previousText;
  }
}

async function saveCustomProfile() {
  const context = makeRenderContext();
  const name = fields.customProfileName.value.trim() || "Custom Profile";
  const payload = await postJson("/api/custom-profile", {
    name,
    config: { ...readConfig(), profile: "custom" },
  });
  if (!isCurrentAccountContext(context)) return;
  profiles = payload.profiles || profiles;
  renderProfileSelect(payload.profile);
  applyConfig(payload.config);
  els.profileStatus.textContent = `Saved ${profileLabel(payload.profile, payload.config)}.`;
  await saveCurrentAccountDraft(false, { guard: () => isCurrentAccountContext(context) });
}

function handleConfigFieldChange(key) {
  if (suppressProfileDirty) return;
  if (key === "trade_size_mode") syncTradeSizeModeControl();
  parameterDirty = true;
  renderParameterStatus(null);
  if (strategyProfileKeys.has(key)) renderProfileStatus();
}

function configsEquivalent(current, preset) {
  return [...strategyProfileKeys]
    .every((key) => normalizeConfigValue(current[key]) === normalizeConfigValue(preset[key]));
}

function normalizeConfigValue(value) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim().toUpperCase()).join(",");
  if (typeof value === "boolean") return value ? "true" : "false";
  const numeric = Number(value);
  if (Number.isFinite(numeric) && value !== "" && value !== null) return String(numeric);
  return String(value ?? "").trim().toLowerCase();
}

function renderProfileStatus() {
  const key = fields.profile.value || "neutral";
  const selectedPreset = profiles[key];
  const label = profileLabel(key, selectedPreset || {});
  if (key === "custom") {
    els.profileStatus.textContent = "Custom strategy unsaved.";
  } else if (profiles[key]?.profile_label) {
    els.profileStatus.textContent = "Saved custom strategy.";
  } else if (selectedPreset && !configsEquivalent(readConfig(), selectedPreset)) {
    els.profileStatus.textContent = `${label} strategy edited. Save custom to name this variant.`;
  } else {
    els.profileStatus.textContent = `${label} strategy defaults.`;
  }
}

function appPickTimeLabel() {
  // Before an account is connected there is no server meta yet; show the saved app-wide pick time.
  const minutes = 9 * 60 + 30 + readAppInt("appDailyPickMinutes", 15);
  const hour = Math.floor(minutes / 60);
  return `${((hour + 11) % 12) + 1}:${String(minutes % 60).padStart(2, "0")} ${hour < 12 ? "AM" : "PM"} ET`;
}

function renderDailyUniverseStatus(selected) {
  const el = els.dailyUniverseStatus;
  if (!el) return;
  const config = selected?.config || {};
  // Same condition as the engine: the daily list needs most-active trading and is overridden by inverse-only.
  if (config.universe_mode !== "daily_rvol" || !config.use_top_volume_symbols || config.inverse_etf_mode === "inverse_only") {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  const daily = selected?.daily_universe || {};
  if (daily.status === "picked") {
    const symbols = Array.isArray(daily.symbols) ? daily.symbols : [];
    el.textContent = `Daily list: ${symbols.length} stocks (${daily.picked_count ?? 0} picked at ${daily.picked_at || "-"}, +${daily.added_count ?? 0} added since)`;
  } else {
    el.textContent = `Daily list: waiting for the ${daily.pick_time || appPickTimeLabel()} pick (only inverse ETFs and held positions until then)`;
  }
  el.hidden = false;
}

function renderParameterStatus(selected = null) {
  if (!els.parameterStatus) return;
  const liveConfig = selected?.config || null;
  const uiConfig = readConfig();
  const liveMinScore = liveConfig?.min_entry_score ?? uiConfig.min_entry_score ?? 38;
  if (parameterDirty) {
    const livePart = liveConfig
      ? ` Live block still uses ${tradeSizeLabel(liveConfig)}, ${liveConfig.max_total_exposure_percent}% exposure, ${liveConfig.max_open_positions} max pos, min score ${liveMinScore}.`
      : "";
    els.parameterStatus.textContent = `Pending changes: strategy ${profileLabel(uiConfig.profile, profiles[uiConfig.profile] || {})}, trade ${tradeSizeLabel(uiConfig)}, exposure ${uiConfig.max_total_exposure_percent}%, max pos ${uiConfig.max_open_positions}, min score ${uiConfig.min_entry_score}.${livePart} Click Apply Changes to make it live.`;
    return;
  }
  if (!liveConfig) {
    els.parameterStatus.textContent = "Live parameters load after selecting an account.";
    return;
  }
  const profile = profileLabel(liveConfig.profile || "custom", liveConfig);
  els.parameterStatus.textContent = `Live: strategy ${profile}, trade ${tradeSizeLabel(liveConfig)}, exposure ${liveConfig.max_total_exposure_percent}%, max pos ${liveConfig.max_open_positions}, min score ${liveMinScore}.`;
}

function renderProfileSelect(selected = fields.profile.value || "neutral") {
  fields.profile.innerHTML = "";
  ["conservative", "neutral", "aggressive"].forEach((key) => {
    if (profiles[key]) appendProfileOption(key, profileLabel(key, profiles[key]));
  });
  Object.keys(profiles)
    .filter((key) => !["conservative", "neutral", "aggressive"].includes(key))
    .sort((left, right) => profileLabel(left, profiles[left]).localeCompare(profileLabel(right, profiles[right])))
    .forEach((key) => appendProfileOption(key, profileLabel(key, profiles[key])));
  ensureProfileOption("custom", "Custom");
  fields.profile.value = profiles[selected] || selected === "custom" ? selected : "neutral";
  renderProfileStatus();
}

function appendProfileOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  fields.profile.appendChild(option);
}

function ensureProfileOption(value, label) {
  if ([...fields.profile.options].some((option) => option.value === value)) return;
  appendProfileOption(value, label);
}

function profileLabel(key, config = {}) {
  if (config.profile_label) return config.profile_label;
  return String(key || "custom")
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ") || "Custom";
}

function accountStrategyLabel(account = {}) {
  const saved = findSavedAccount(account.account_id);
  const config = saved?.config || {};
  const key = config.profile || account.profile || "neutral";
  return profileLabel(key, profiles[key] || config);
}

function presetConfig(profile) {
  return profiles[profile] || {
    profile,
    use_top_volume_symbols: true,
    symbols: ["SPY", "QQQ"],
    feed: "iex",
    poll_seconds: 5,
    dry_run: true,
    market_hours_only: true,
    use_market_stream: true,
    use_bracket_orders: true,
    trade_size_mode: "percent",
    max_trade_notional: 0,
    max_trade_percent: 7,
    max_position_notional: 35,
    max_position_percent: 7,
    daily_loss_limit: 0,
    daily_loss_limit_percent: 0,
    risk_per_trade_percent: 0,
    max_total_exposure_percent: 25,
    max_open_positions: 3,
    short_period: 9,
    long_period: 21,
    rsi_period: 14,
    buy_rsi_min: 42,
    buy_rsi_max: 68,
    min_entry_score: 44,
    momentum_period: 6,
    min_momentum_percent: 0.08,
    min_recent_momentum_percent: 0.05,
    min_long_momentum_percent: 0.05,
    min_session_change_percent: 1.35,
    min_vwap_distance_percent: 0.05,
    max_vwap_distance_percent: 2.25,
    max_session_pullback_percent: 0.9,
    max_recent_pullback_percent: 0.55,
    late_momentum_floor_percent: 0.5,
    min_session_pullback_percent: 0,
    max_entry_rsi: 0,
    max_entries_per_symbol_per_day: 0,
    require_rising_price: true,
    max_entries_per_scan: 2,
    entry_spacing_seconds: 0,
    flatten_on_daily_loss: false,
    flatten_before_close_minutes: 0,
    alert_trades: true,
    alert_problems: true,
    smi_period: 10,
    min_smi: 40,
    atr_period: 14,
    min_buy_volume_ratio: 0.5,
    reentry_score_boost: 12,
    inverse_etf_mode: "allow",
    universe_mode: "most_active",
    entry_mode: "momentum",
    orb_minutes: 15,
    orb_max_breakout_percent: 1,
    sell_rsi: 72,
    volume_period: 20,
    volume_multiplier: 1.5,
    min_avg_volume: 0,
    take_profit_percent: 2.5,
    breakeven_at_percent: 0,
    profit_trail_start_percent: 0,
    profit_trail_drop_percent: 0,
    stop_loss_percent: 1.25,
    stop_loss_grace_minutes: 0,
    exit_time_in_force: "day",
    cooldown_minutes: 0,
    entry_open_guard_minutes: 15,
    entry_close_guard_minutes: 15,
    extension_atr_reference_percent: 0,
    score_weight_rsi: 5,
    score_weight_relative_volume: 13,
    score_weight_momentum: 14,
    score_weight_recent_momentum: 8,
    score_weight_long_momentum: 14,
    score_weight_session_change: 16,
    score_weight_vwap: 14,
    score_weight_smi: 7,
    score_weight_volatility: 0,
    score_weight_liquidity_bonus: 1.5,
    score_weight_flow: 3,
    score_weight_pullback_penalty: 0,
    score_weight_overbought_penalty: 0,
    score_weight_volatility_penalty: 4,
    score_weight_session_extension_penalty: 4,
    score_weight_vwap_extension_penalty: 10,
    score_weight_session_pullback_penalty: 9,
    score_weight_recent_pullback_penalty: 6,
    score_weight_smi_overheat_penalty: 4,
    most_active_count: 100,
    daily_pick_count: 25,
    daily_max_symbols: 40,
    inverse_etf_symbols: ["SQQQ", "SPXU", "SDS", "SH", "TZA"],
  };
}

function toCamel(value) {
  return value.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
}

function readNumber(id, fallback) {
  const value = Number(fields[id].value);
  return Number.isFinite(value) ? value : fallback;
}

function readInt(id, fallback) {
  const value = parseInt(fields[id].value, 10);
  return Number.isFinite(value) ? value : fallback;
}

function readAppInt(id, fallback) {
  const value = parseInt(document.querySelector(`#${id}`).value, 10);
  return Number.isFinite(value) ? value : fallback;
}

const appSettingKeys = {
  dailyPickMinutes: "daily_pick_minutes_after_open",
  dailyRecheckMinutes: "daily_recheck_minutes",
  rvolLookbackSessions: "rvol_lookback_sessions",
  rvolMinSessions: "rvol_min_sessions",
  marketStreamSymbolLimit: "market_stream_symbol_limit",
};
let appSettingsDirty = false;

function applyAppSettings(settings, { force = false } = {}) {
  // Unsaved edits survive settings reloads (Apply Changes, account switches) until saved.
  if (!settings || (appSettingsDirty && !force)) return;
  Object.entries(appSettingKeys).forEach(([name, key]) => {
    if (settings[key] !== undefined && settings[key] !== null) appFields[name].value = settings[key];
  });
  appSettingsDirty = false;
}

Object.values(appFields).forEach((field) => field.addEventListener("input", () => {
  appSettingsDirty = true;
}));

function readAppSettings() {
  return {
    daily_pick_minutes_after_open: readAppInt("appDailyPickMinutes", 15),
    daily_recheck_minutes: readAppInt("appDailyRecheckMinutes", 30),
    rvol_lookback_sessions: readAppInt("appRvolLookbackSessions", 20),
    rvol_min_sessions: readAppInt("appRvolMinSessions", 5),
    market_stream_symbol_limit: readAppInt("appMarketStreamSymbolLimit", 30),
  };
}

async function saveAppSettings() {
  try {
    const result = await postJson("/api/app-settings", readAppSettings());
    applyAppSettings(result.app_settings, { force: true });
    els.appSettingsStatus.textContent = "App settings saved.";
  } catch (error) {
    els.appSettingsStatus.textContent = error.message || String(error);
  }
}

// Per-launch token the server writes into this page; required on every state-changing request.
const API_TOKEN = document.querySelector('meta[name="apt-api-token"]')?.content || "";

function apiHeaders(extra = {}) {
  return { ...extra, "X-APT-Token": API_TOKEN };
}

async function reloadIfTokenRejected(response) {
  if (response.status !== 403) return;
  const payload = await response.clone().json().catch(() => ({}));
  // The backend restarted with a new token; reload to pick it up.
  if (payload.detail === "invalid api token") window.location.reload();
}

async function postJson(url, body) {
  const response = await fetchWithRecovery(url, {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    await reloadIfTokenRejected(response);
    const payload = await response.json().catch(() => ({}));
    throw new Error(errorDetailText(payload.detail) || response.statusText);
  }
  return response.json();
}

function errorDetailText(detail) {
  // Validation errors (422) arrive as a list of {loc, msg}; show their messages, not "[object Object]".
  if (Array.isArray(detail)) return detail.map((item) => String(item?.msg ?? item).replace(/^Value error, /, "")).join("; ");
  return detail;
}

async function fetchRuntimeHealth(baseUrl = "") {
  const response = await fetch(`${baseUrl}/api/health`, {
    cache: "no-store",
    mode: baseUrl ? "cors" : "same-origin",
  });
  if (!response.ok) throw new Error(`Runtime health check failed: ${response.statusText}`);
  return response.json();
}

function healthSummary(health = {}) {
  const pid = health.pid || "unknown";
  const sourceStamp = health.source_stamp || "unknown";
  const expectedStamp = health.expected_source_stamp || "unknown";
  const sourcePath = health.source_path || "unknown source path";
  const reason = health.stale_reason || "Runtime health did not match the current app source.";
  return `${reason} PID ${pid}. Source ${sourcePath}. Running stamp ${sourceStamp}; expected ${expectedStamp}. Close the stale backend process or relaunch from the current folder.`;
}

function settingsDiagnosticsSummary(diagnostics = {}) {
  const errors = diagnostics.errors || [];
  if (!errors.length) return "";
  return errors
    .map((item) => {
      const account = item.account_name || item.account_id || item.source || "settings";
      return `${account}: ${item.message || "settings load error"}`;
    })
    .join(" ");
}

function runtimeDiagnosticsSummary(diagnostics = {}) {
  const entries = diagnostics.entries || [];
  if (!entries.length) return "";
  return entries
    .slice(-3)
    .map((item) => {
      const area = item.area || item.source || "runtime";
      const detail = item.detail ? `: ${item.detail}` : "";
      return `${area}: ${item.message || "runtime warning"}${detail}`;
    })
    .join(" ");
}

const RUNTIME_ERROR_BANNER_MS = 30 * 60 * 1000;

// Only recent errors earn the red banner; info/warning notes (e.g. a skipped CVR symbol)
// and older errors are shown as a quiet one-line note instead.
function isActiveRuntimeError(item) {
  if (item?.severity !== "error") return false;
  const when = Date.parse(item.time || "");
  return Number.isNaN(when) || Date.now() - when <= RUNTIME_ERROR_BANNER_MS;
}

function renderRuntimeNote(text) {
  if (!els.runtimeNote) return;
  els.runtimeNote.textContent = text;
  els.runtimeNote.title = text;
  els.runtimeNote.hidden = !text;
}

function renderRuntimeHealth(health) {
  runtimeHealth = health || null;
  runtimeStale = Boolean(health && health.current === false);
  if (!els.runtimeHealthBanner || !els.runtimeHealthText) return;
  const settingsWarning = settingsDiagnosticsSummary(health?.settings_diagnostics || {});
  const entries = health?.runtime_diagnostics?.entries || [];
  const activeErrors = entries.filter(isActiveRuntimeError);
  const runtimeWarning = runtimeDiagnosticsSummary({ entries: activeErrors });
  renderRuntimeNote(runtimeDiagnosticsSummary({ entries: entries.filter((item) => !activeErrors.includes(item)) }));
  if (!health || (health.current === true && !settingsWarning && !runtimeWarning)) {
    els.runtimeHealthBanner.hidden = true;
    if (els.runtimeHealthTitle) els.runtimeHealthTitle.textContent = "Runtime warning";
    els.runtimeHealthText.textContent = "";
    return;
  }
  const title = health.current === false
    ? "Stale runtime warning"
    : (settingsWarning ? "Settings warning" : "Runtime error");
  if (els.runtimeHealthTitle) els.runtimeHealthTitle.textContent = title;
  els.runtimeHealthText.textContent = health.current === false ? healthSummary(health) : (settingsWarning || runtimeWarning);
  els.runtimeHealthBanner.hidden = false;
  els.statusText.textContent = title;
}

function renderRuntimeHealthError(message) {
  runtimeStale = true;
  if (els.runtimeHealthBanner && els.runtimeHealthText) {
    if (els.runtimeHealthTitle) els.runtimeHealthTitle.textContent = "Runtime health unavailable";
    els.runtimeHealthText.textContent = message;
    els.runtimeHealthBanner.hidden = false;
  }
  els.statusText.textContent = "Runtime health unavailable";
}

function renderSettingsDiagnostics(diagnostics = {}) {
  const hasSettingsWarning = Boolean((diagnostics.errors || []).length);
  if (!hasSettingsWarning && runtimeStale && !runtimeHealth) return;
  const health = {
    ...(runtimeHealth || { current: true }),
    settings_diagnostics: diagnostics,
  };
  renderRuntimeHealth(health);
}

async function checkRuntimeHealth() {
  const request = beginRequest("health", { abortPrevious: false });
  try {
    const health = await fetchRuntimeHealth();
    if (isLatestRequest(request)) {
      renderRuntimeHealth(health);
    }
    return health;
  } catch (error) {
    if (isLatestRequest(request)) {
      renderRuntimeHealthError(error.message || "Runtime health check failed.");
    }
    return null;
  }
}

async function fetchWithRecovery(url, options) {
  try {
    return await fetch(url, options);
  } catch (error) {
    if (isAbortError(error)) throw error;
    await recoverStaleInstance(error);
    throw error;
  }
}

async function recoverStaleInstance(error) {
  if (
    staleInstanceRedirecting ||
    !["127.0.0.1", "localhost"].includes(window.location.hostname)
  ) {
    return false;
  }

  const target = `http://127.0.0.1:${preferredAppPort}`;
  try {
    const health = await fetchRuntimeHealth(target);
    if (health.current !== true) {
      renderRuntimeHealth(health);
      els.topVolumeUpdated.textContent = "A stale backend is responding on the preferred app port.";
      return false;
    }
    if (window.location.port === preferredAppPort) {
      renderRuntimeHealth(health);
      return false;
    }
    staleInstanceRedirecting = true;
    els.statusText.textContent = "Opening active app instance...";
    els.topVolumeUpdated.textContent = `Opening ${target}...`;
    window.location.assign(`${target}/?v=stable-port`);
    return true;
  } catch {
    const message = error?.message || "This app instance is not responding.";
    renderRuntimeHealthError(message);
    els.topVolumeUpdated.textContent = message;
    return false;
  }
}

async function loadSettings(options = {}) {
  const { applySelected = true, guard = null } = options;
  const response = await fetchWithRecovery("/api/settings");
  if (!response.ok) throw new Error(response.statusText);
  const payload = await response.json();
  if (guard && !guard()) return null;
  profiles = payload.profiles || {};
  applyAppSettings(payload.app_settings);
  savedAccounts = payload.accounts || [];
  renderSettingsDiagnostics(payload.settings_diagnostics || {});
  selectedAccountId = payload.selected_account_id || savedAccounts[0]?.account_id || "";
  const account = findSavedAccount(selectedAccountId) || savedAccounts[0];
  renderProfileSelect(account?.config?.profile || fields.profile.value || "neutral");
  renderAccountSelect();
  if (applySelected && account) applyAccount(account);
}

function renderAccountSelect() {
  fields.accountSelect.innerHTML = "";
  savedAccounts.forEach((account) => {
    const option = document.createElement("option");
    option.value = account.account_id;
    option.textContent = account.name || "Paper Account";
    fields.accountSelect.appendChild(option);
  });
  const draft = document.createElement("option");
  draft.value = "";
  draft.textContent = "New account draft";
  fields.accountSelect.appendChild(draft);
  fields.accountSelect.value = selectedAccountId;
}

function findSavedAccount(accountId) {
  return savedAccounts.find((account) => account.account_id === accountId);
}

async function loadState(options = {}) {
  if (options.source === "poll" && accountTransitionDepth > 0) return false;
  const request = beginRequest("state", {
    accountId: options.accountId ?? selectedAccountId,
    source: options.source || "state",
  });
  try {
    await checkRuntimeHealth();
    if (!isCurrentAccountRequest(request)) return false;
    const suffix = request.accountId ? `?account_id=${encodeURIComponent(request.accountId)}` : "";
    const response = await fetchWithRecovery(`/api/state${suffix}`, {
      cache: "no-store",
      signal: request.signal,
    });
    if (!response.ok) throw new Error(response.statusText);
    const state = await response.json();
    if (!isCurrentAccountRequest(request)) return false;
    return renderState(state, request);
  } catch (error) {
    if (isAbortError(error) || !isLatestRequest(request)) return false;
    if (await recoverStaleInstance(error)) return;
    els.statusText.textContent = error.message;
    return false;
  }
}

async function loadDashboard(options = {}) {
  if (options.source === "poll" && accountTransitionDepth > 0) return false;
  const request = beginRequest("dashboard", {
    accountId: options.accountId ?? selectedAccountId,
    source: options.source || "dashboard",
  });
  try {
    await checkRuntimeHealth();
    if (!isCurrentAccountRequest(request)) return false;
    const suffix = request.accountId ? `?account_id=${encodeURIComponent(request.accountId)}` : "";
    const response = await fetchWithRecovery(`/api/dashboard${suffix}`, {
      cache: "no-store",
      signal: request.signal,
    });
    if (!response.ok) throw new Error(response.statusText);
    const dashboard = await response.json();
    if (!isCurrentAccountRequest(request)) return false;
    if (!renderDashboard(dashboard, request)) return false;
    await maybeRecoverDashboardStream(dashboard, request);
    return true;
  } catch (error) {
    if (isAbortError(error) || !isLatestRequest(request)) return false;
    if (await recoverStaleInstance(error)) return;
    els.topVolumeUpdated.textContent = error.message;
    return false;
  }
}

function renderDashboard(dashboard, context) {
  if (!isCurrentAccountContext(context)) return false;
  renderMarketClockInto(
    dashboard.market_clock,
    els.dashboardMarketStatus,
    els.dashboardMarketStatusText,
    els.dashboardMarketStatusDetail,
    "Connect an account on the Accounts page."
  );

  const halt = dashboard.halt_summary || {};
  const haltCount = Number(halt.count || 0);
  els.dashboardHaltStatusText.textContent = halt.status || "No active halts detected";
  els.dashboardHaltStatusDetail.textContent = halt.detail || "Subscribed dashboard symbols.";
  els.dashboardHaltStatus.classList.toggle("halted", haltCount > 0);

  renderMarketStream(dashboard.market_stream || {});
  renderDashboardTrader(dashboard);

  const rows = dashboard.top_volume || [];
  currentTopVolumeRows = rows;
  if (!dashboard.connected) {
    els.topVolumeUpdated.textContent = "Connect an account on the Accounts page to populate the dashboard.";
  } else if (dashboard.top_volume_error) {
    els.topVolumeUpdated.textContent = dashboard.top_volume_error;
  } else {
    const refreshed = dashboard.top_volume_updated || "waiting for first refresh";
    const stream = dashboard.market_stream || {};
    const live = stream.last_message
      ? `Live ${stream.last_message}${stream.last_message_age ? `, ${stream.last_message_age}` : ""}`
      : "Live waiting for tick";
    els.topVolumeUpdated.textContent = `${dashboard.account_name || "Connected account"} | list ${refreshed} | ${live}`;
  }
  renderTopVolumeRows(rows);
  return true;
}

function renderDashboardTrader(dashboard) {
  const running = Boolean(dashboard.trading_enabled);
  const connected = Boolean(dashboard.connected);
  els.dashboardTraderStatusText.textContent = running ? "Running" : connected ? "Connected" : "Stopped";
  const profile = dashboard.profile ? `${profileLabel(dashboard.profile)} profile` : "No profile";
  const scan = dashboard.last_refresh ? `Last scan ${dashboard.last_refresh}` : "No scan yet";
  const status = dashboard.status || "No account running.";
  els.dashboardTraderStatusDetail.textContent = `${profile}. ${scan}. ${status}`;
  els.dashboardTraderStatus.classList.toggle("open", running);
  els.dashboardTraderStatus.classList.toggle("closed", connected && !running);
}

async function maybeRecoverDashboardStream(dashboard, context) {
  if (!isCurrentAccountContext(context)) return;
  const stream = dashboard.market_stream || {};
  const status = String(stream.status || "").toLowerCase();
  const age = Number(stream.last_message_age_seconds);
  const stale = Number.isFinite(age) && age > 90;
  const inHandshake = [
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
  ].includes(status);
  if (!dashboard.connected || status === "connection limit" || inHandshake) return;
  if (stream.connected && !stale) return;
  if (Date.now() - lastStreamRecoveryAt < 30000) return;
  lastStreamRecoveryAt = Date.now();
  try {
    const recovered = await postJson("/api/dashboard/reconnect-stream", { account_id: context?.accountId || selectedAccountId || null });
    renderDashboard(recovered, context);
  } catch (error) {
    els.dashboardStreamStatusText.textContent = "Recovery failed";
    els.dashboardStreamStatusDetail.textContent = error.message;
  }
}

function renderMarketStream(stream) {
  const status = stream.status || "Stopped";
  const message =
    status === "Listening" && stream.last_message === "Waiting for market data"
      ? "Subscribed; waiting for market data"
      : stream.last_message
        ? `Last ${stream.last_message}`
        : "No messages yet";
  const age = stream.last_message_age ? `, ${stream.last_message_age}` : "";
  const counts = `${stream.dashboard_symbols || 0} dashboard / ${stream.bar_symbols || 0} bar symbols`;
  const reconnects = Number(stream.reconnect_count || 0);
  const error = stream.last_error ? ` | ${stream.last_error}` : "";
  els.dashboardStreamStatusText.textContent = status;
  els.dashboardStreamStatusDetail.textContent = `${counts}. ${message}${age}. Reconnects: ${reconnects}${error}`;
  els.dashboardStreamStatus.classList.toggle("open", Boolean(stream.connected));
  els.dashboardStreamStatus.classList.toggle("closed", !stream.connected && status !== "Stopped");
}

function renderTopVolumeRows(rows) {
  els.topVolumeRows.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = 12;
    td.textContent = "No top-volume rows loaded.";
    tr.appendChild(td);
    els.topVolumeRows.appendChild(tr);
    return;
  }

  sortRowsForTable("topVolumeRows", rows).forEach((row) => {
    const tr = document.createElement("tr");
    if (row.halted) tr.classList.add("halted-row");
    [
      row.rank,
      row.symbol,
      row.buy_volume,
      row.sell_volume,
      row.unclassified_volume,
      row.stream_volume,
      row.total_volume || row.daily_volume,
      row.trade_count,
      row.last_price,
      row.last_trade_side,
      row.trading_status,
      row.halted ? "Halted" : "Clear",
    ].forEach((value, index) => {
      const td = document.createElement("td");
      td.textContent = value ?? "";
      if (index === 2) td.className = "positive";
      if (index === 3) td.className = "negative";
      if (index === 11) td.className = row.halted ? "negative" : "positive";
      tr.appendChild(td);
    });
    els.topVolumeRows.appendChild(tr);
  });
}

function renderPositionRows() {
  const columns = [
    "symbol",
    "side",
    "qty",
    "avg_entry",
    "cost_basis",
    "current_price",
    "market_value",
    showPositionPlPercent ? "unrealized_pl_pct" : "unrealized_pl",
    showPositionPlPercent ? "intraday_pl_pct" : "intraday_pl",
    "protection",
  ];
  const sorted = sortRowsForTable("positionRows", currentPositionRows);
  els.positionRows.innerHTML = "";
  if (!sorted.length) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = columns.length;
    td.textContent = "No rows";
    tr.appendChild(td);
    els.positionRows.appendChild(tr);
    return;
  }

  sorted.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((key) => {
      const td = document.createElement("td");
      td.textContent = row[key] ?? "";
      if (key === "unrealized_pl" || key === "unrealized_pl_pct") {
        td.className = Number(row.unrealized_pl_raw || 0) >= 0 ? "positive" : "negative";
      }
      if (key === "intraday_pl" || key === "intraday_pl_pct") {
        td.className = Number(row.intraday_pl_raw || 0) >= 0 ? "positive" : "negative";
      }
      if (key === "protection") {
        const value = String(row.protection || "");
        td.className = value === "Protected" ? "positive" : value.startsWith("Unprotected") ? "negative" : "muted-cell";
      }
      tr.appendChild(td);
    });
    els.positionRows.appendChild(tr);
  });
}

function renderTradeHistoryRows(rows) {
  const columns = [
    "filled",
    "symbol",
    "side",
    "filled_qty",
    "avg_fill",
    "value",
    "cost_basis",
    "realized_pl",
    "realized_pl_pct",
    "result",
    "exit_reason",
    "status",
    "source",
  ];
  tableRenderCache.tradeHistoryRows = { tbody: els.tradeHistoryRows, rows, keys: columns };
  const sorted = sortRowsForTable("tradeHistoryRows", rows);
  els.tradeHistoryRows.innerHTML = "";
  if (!sorted.length) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = columns.length;
    td.textContent = "No rows";
    tr.appendChild(td);
    els.tradeHistoryRows.appendChild(tr);
    return;
  }

  sorted.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((key) => {
      const td = document.createElement("td");
      td.textContent = row[key] ?? "";
      if (key === "realized_pl" || key === "realized_pl_pct") {
        const value = Number(row.realized_pl_raw || 0);
        if (row.side === "sell") td.className = value >= 0 ? "positive" : "negative";
      }
      if (key === "result") {
        if (row.result === "Winner") td.className = "positive";
        if (row.result === "Loser") td.className = "negative";
      }
      if (key === "exit_reason") {
        if (String(row.exit_reason || "").startsWith("Gain")) td.className = "positive";
        if (String(row.exit_reason || "").startsWith("Loss")) td.className = "negative";
        if (row.exit_reason_detail && row.exit_reason_detail !== "-") {
          td.title = row.exit_reason_detail;
        }
      }
      tr.appendChild(td);
    });
    els.tradeHistoryRows.appendChild(tr);
  });
}

function setupSortableTables() {
  Object.entries(sortableTables).forEach(([tableId, config]) => {
    const tbody = document.querySelector(`#${tableId}`);
    const table = tbody?.closest("table");
    if (!table) return;

    const headers = [...table.querySelectorAll("thead th")];
    headers.forEach((header, index) => {
      const sortKey = config.columns[index];
      if (!sortKey) return;

      header.classList.add("sortable-header");
      let button = header.querySelector("button");
      if (!button) {
        button = document.createElement("button");
        button.type = "button";
        button.textContent = header.textContent.trim();
        header.textContent = "";
        header.appendChild(button);
      }

      button.classList.add("table-sort-button");
      button.dataset.tableSort = tableId;
      button.dataset.sort = button.dataset.sort || sortKey;
      button.title = `Sort by ${button.textContent.trim()}`;
      button.addEventListener("click", () => {
        setTableSort(tableId, button.dataset.sort);
      });
    });
  });
}

function setTableSort(tableId, key) {
  const current = tableSorts[tableId];
  if (!current || !key) return;

  if (current.key === key) {
    current.direction = current.direction === "asc" ? "desc" : "asc";
  } else {
    current.key = key;
    current.direction = defaultSortDirection(key);
  }

  updateTableSortButtons(tableId);
  rerenderSortedTable(tableId);
}

function rerenderSortedTable(tableId) {
  if (tableId === "topVolumeRows") {
    renderTopVolumeRows(currentTopVolumeRows);
    return;
  }
  if (tableId === "positionRows") {
    renderPositionRows();
    return;
  }
  if (tableId === "tradeHistoryRows") {
    renderTradeHistoryRows(currentTradeHistoryRows);
    return;
  }

  const cache = tableRenderCache[tableId];
  if (!cache) return;
  renderRows(cache.tbody, cache.rows, cache.keys);
}

function sortRowsForTable(tableId, rows) {
  const sort = tableSorts[tableId];
  if (!sort) return [...rows];

  const key = activeTableSortKey(tableId, sort.key);
  return [...rows].sort((left, right) =>
    compareSortValues(resolveSortValue(left, key), resolveSortValue(right, key), sort.direction)
  );
}

function activeTableSortKey(tableId, key) {
  if (tableId === "positionRows" && showPositionPlPercent && key === "unrealized_pl_raw") {
    return "unrealized_pl_pct_raw";
  }
  if (tableId === "positionRows" && showPositionPlPercent && key === "intraday_pl_raw") {
    return "intraday_pl_pct_raw";
  }
  return key;
}

function resolveSortValue(row, key) {
  if (!row || !key) return "";
  if (Object.prototype.hasOwnProperty.call(row, key)) return row[key];
  if (key.endsWith("_raw")) {
    const displayKey = key.slice(0, -4);
    if (Object.prototype.hasOwnProperty.call(row, displayKey)) return row[displayKey];
  }
  if (key === "halted_raw") return row.halted ? 1 : 0;
  return "";
}

function compareSortValues(left, right, direction = "asc") {
  const leftValue = normalizeSortValue(left);
  const rightValue = normalizeSortValue(right);
  if (leftValue.empty && rightValue.empty) return 0;
  if (leftValue.empty) return 1;
  if (rightValue.empty) return -1;

  let comparison = 0;
  if (leftValue.type === "number" && rightValue.type === "number") {
    comparison = leftValue.value - rightValue.value;
  } else {
    comparison = String(leftValue.value).localeCompare(String(rightValue.value), undefined, {
      numeric: true,
      sensitivity: "base",
    });
  }

  return direction === "desc" ? comparison * -1 : comparison;
}

function normalizeSortValue(value) {
  if (value === null || value === undefined) return { empty: true, type: "text", value: "" };
  if (typeof value === "boolean") return { empty: false, type: "number", value: value ? 1 : 0 };
  if (typeof value === "number") {
    return Number.isFinite(value) ? { empty: false, type: "number", value } : { empty: true, type: "text", value: "" };
  }

  const text = String(value).trim();
  if (!text || text === "-" || text.toLowerCase() === "n/a") return { empty: true, type: "text", value: "" };

  const numericText = text
    .replace(/[$,%+]/g, "")
    .replace(/,/g, "")
    .replace(/\s*x$/i, "")
    .trim();
  if (/^-?(?:\d+\.?\d*|\.\d+)$/.test(numericText)) {
    return { empty: false, type: "number", value: Number(numericText) };
  }

  const parsedDate = Date.parse(text);
  if (!Number.isNaN(parsedDate) && /\d/.test(text) && /[:/\-TZ]|am|pm/i.test(text)) {
    return { empty: false, type: "number", value: parsedDate };
  }

  return { empty: false, type: "text", value: text.toLowerCase() };
}

function defaultSortDirection(key = "") {
  const lowerKey = String(key).toLowerCase();
  if (
    lowerKey === "symbol" ||
    lowerKey === "side" ||
    lowerKey === "protection" ||
    lowerKey === "status" ||
    lowerKey.includes("status") ||
    lowerKey.includes("role") ||
    lowerKey.includes("source") ||
    lowerKey.includes("kind") ||
    lowerKey.includes("type") ||
    lowerKey.includes("bias") ||
    lowerKey.includes("class") ||
    lowerKey.includes("id") ||
    lowerKey.includes("reason") ||
    lowerKey.includes("detail")
  ) {
    return "asc";
  }
  if (lowerKey.includes("time") || lowerKey.includes("submitted") || lowerKey.includes("filled")) return "desc";
  return "desc";
}

function updateTableSortButtons(tableId) {
  const sort = tableSorts[tableId];
  if (!sort) return;

  document.querySelectorAll(`[data-table-sort="${tableId}"]`).forEach((button) => {
    const active = button.dataset.sort === sort.key;
    button.classList.toggle("active", active);
    button.dataset.direction = active ? sort.direction : "";
    button.closest("th")?.setAttribute("aria-sort", active ? (sort.direction === "asc" ? "ascending" : "descending") : "none");
  });
}

function updateAllTableSortButtons() {
  Object.keys(sortableTables).forEach(updateTableSortButtons);
}

async function reconnectDashboardStream() {
  const buttons = [els.reconnectStreamButton, els.refreshTopVolumeButton].filter(Boolean);
  buttons.forEach((button) => {
    button.disabled = true;
  });
  els.dashboardStreamStatusText.textContent = "Restarting";
  els.dashboardStreamStatusDetail.textContent = "Refreshing top-volume data and reconnecting the shared websocket.";
  try {
    const context = makeRenderContext();
    const dashboard = await postJson("/api/dashboard/reconnect-stream", { account_id: context.accountId || null, force: true });
    if (renderDashboard(dashboard, context)) {
      await loadState({ accountId: context.accountId, source: "dashboard-reconnect" });
    }
  } catch (error) {
    els.dashboardStreamStatusText.textContent = "Reconnect failed";
    els.dashboardStreamStatusDetail.textContent = error.message;
  } finally {
    buttons.forEach((button) => {
      button.disabled = false;
    });
  }
}

async function lookupSymbol() {
  const symbol = fields.lookupSymbol.value.trim().toUpperCase();
  if (!symbol) return;

  els.lookupButton.disabled = true;
  els.lookupResult.textContent = "Loading snapshot...";
  try {
    const account = selectedAccountId ? `&account_id=${encodeURIComponent(selectedAccountId)}` : "";
    const response = await fetchWithRecovery(`/api/lookup?symbol=${encodeURIComponent(symbol)}${account}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || response.statusText);
    }
    renderLookup(await response.json());
  } catch (error) {
    els.lookupResult.textContent = error.message;
  } finally {
    els.lookupButton.disabled = false;
  }
}

function renderLookup(payload) {
  const trade = payload.latest_trade || {};
  const quote = payload.latest_quote || {};
  const minute = payload.minute_bar || {};
  const daily = payload.daily_bar || {};
  els.lookupResult.innerHTML = `
    <div class="lookup-heading">
      <strong>${escapeHtml(payload.symbol || "")}</strong>
      <span>${escapeHtml(payload.feed || "")} | ${escapeHtml(payload.fetched_at || "")}</span>
    </div>
    <div class="lookup-metrics">
      <div><span>Last Trade</span><strong>${escapeHtml(trade.price || "-")}</strong><small>${escapeHtml(trade.size || "-")} shares</small></div>
      <div><span>Bid / Ask</span><strong>${escapeHtml(quote.bid || "-")} / ${escapeHtml(quote.ask || "-")}</strong><small>Spread ${escapeHtml(quote.spread || "-")}</small></div>
      <div><span>Minute Vol</span><strong>${escapeHtml(minute.volume || "-")}</strong><small>Close ${escapeHtml(minute.close || "-")}</small></div>
      <div><span>Daily Vol</span><strong>${escapeHtml(daily.volume || "-")}</strong><small>${escapeHtml(payload.daily_change || "-")}</small></div>
    </div>
  `;
}

function renderState(state, context) {
  if (!stateMatchesRenderContext(state, context)) return false;
  renderSettingsDiagnostics(state.settings_diagnostics || {});
  if (isDraftAccount) {
    selectedConnected = false;
    selectedTradingEnabled = false;
    selectedLiveDryRun = null;
    selectedRisk = {};
    renderAccountCards(state.accounts || []);
    renderMarketClock(null);
    renderMarketStream(state.market_stream || {});
    renderReplay(state.replay || {});
    renderParameterStatus(null);
    els.statusText.textContent = "New account draft";
    renderTradingToggle();
    els.cancelOrdersButton.disabled = true;
    els.purgeAccountButton.disabled = true;
    return true;
  }

  selectedAccountId = state.selected_account_id || state.selected?.account_id || selectedAccountId;
  renderAccountCards(state.accounts || []);
  fields.accountSelect.value = selectedAccountId;

  const selected = state.selected || {};
  const config = selected.config || {};
  selectedConnected = Boolean(selected.connected);
  selectedTradingEnabled = Boolean(selected.trading_enabled);
  selectedLiveDryRun = config.dry_run === undefined ? null : Boolean(config.dry_run);
  selectedRisk = selected.risk || {};
  const protectionRows = (selected.protection || []).filter((row) => row.status !== "No market price");
  selectedStats = {
    scanned: (selected.strategy || []).length,
    positions: protectionRows.length,
    protectedCount: protectionRows.filter((row) => row.status === "Protected").length,
  };
  if (selected.account_id === selectedAccountId) {
    const saved = findSavedAccount(selectedAccountId);
    if (!saved || saved.config?.profile !== config.profile) {
      applyConfig(config);
    }
  }

  els.statusText.textContent = selected.name ? `${selected.name}: ${selected.status}` : selected.status || "Not connected";
  renderCredentialStatus({
    ...(findSavedAccount(selectedAccountId) || {}),
    connected: selected.connected,
    credentials_loaded: selected.credentials_loaded,
    credentials_saved: selected.credentials_saved,
  });
  renderMarketClock(selected.market_clock);
  renderMarketStream(state.market_stream || {});
  renderReplay(state.replay || {});
  renderParameterStatus(selected);
  renderDailyUniverseStatus(selected);
  renderTradingToggle();
  els.cancelOrdersButton.disabled = !selected.connected;
  els.purgeAccountButton.disabled = !selected.connected;

  const account = selected.account || {};
  currentSelectedAccount = account;
  els.equity.textContent = account.equity_display || "$0.00";
  els.dailyPl.textContent = dailyPlDisplay(account);
  els.dailyPl.className = metricPolarityClass(account.daily_pl_raw);
  if (els.dailyPlDetail) els.dailyPlDetail.textContent = metricSessionDetail(account.daily_pl_session_date);
  renderRealizedPlMetric(account);
  els.buyingPower.textContent = account.buying_power_display || "$0.00";
  els.cash.textContent = account.cash_display || "$0.00";
  if (els.cashDetail) {
    els.cashDetail.textContent = account.cash_percent_display ? `${account.cash_percent_display} of equity liquid` : "";
  }
  els.lastRefresh.textContent = selected.last_refresh || "-";

  renderRows(els.strategyRows, selected.strategy || [], [
    "symbol",
    "price",
    "rsi",
    "volume",
    "relative_volume",
    "volatility",
    "momentum",
    "long_momentum",
    "session_change",
    "vwap_distance",
    "smi",
    "atr",
    "volume_ok",
    "entry_score",
    "bars",
    "last_action",
  ]);

  const protectionBySymbol = Object.fromEntries((selected.protection || []).map((row) => [row.symbol, row.status]));
  currentPositionRows = (selected.positions || []).map((row) => ({
    ...row,
    protection: protectionBySymbol[String(row.symbol || "").toUpperCase()] || "",
  }));
  renderPositionRows();

  currentTradeHistoryRows = selected.trade_history || [];
  renderTradeHistoryRows(currentTradeHistoryRows);

  renderRows(els.orderRows, selected.orders || [], [
    "symbol",
    "side",
    "type",
    "qty",
    "status",
    "role",
    "time_in_force",
    "order_class",
    "submitted",
    "client_order_id",
  ]);

  renderRows(els.protectionRows, selected.protection || [], [
    "symbol",
    "qty",
    "market_value",
    "unrealized_pl",
    "status",
    "protective_orders",
    "strategy_exits",
    "manual_orders",
    "detail",
  ]);

  renderRows(els.intentRows, selected.order_intents || [], [
    "time",
    "symbol",
    "side",
    "qty",
    "role",
    "status",
    "client_order_id",
    "order_id",
    "reason",
  ]);

  els.logRows.innerHTML = "";
  (selected.logs || []).forEach((entry) => {
    const line = document.createElement("div");
    line.className = `log-line ${entry.level || "info"}`;
    line.textContent = `[${entry.time}] [${(entry.level || "info").toUpperCase()}] ${entry.message}`;
    els.logRows.appendChild(line);
  });
  els.logRows.scrollTop = els.logRows.scrollHeight;
  return true;
}

function renderTradingToggle() {
  if (!els.tradingToggleButton) return;
  els.tradingToggleButton.disabled = !selectedConnected;
  els.tradingToggleButton.classList.toggle("danger", selectedTradingEnabled);
  els.tradingToggleButton.textContent = selectedTradingEnabled ? "Stop Trading" : "Start Trading";
  renderTradingStatus();
}

// The status comes from the running account's config (selectedLiveDryRun), not the form,
// so it never claims orders are being sent when they are not.
function renderTradingStatus() {
  if (!els.tradingStatusBar) return;
  const practice = selectedLiveDryRun ?? fields.dryRun.checked;
  let state = "stopped";
  let title = "Stopped";
  let detail = "";
  if (!selectedConnected) {
    title = "Not connected";
    detail = "Connect this account to see its trading status.";
  } else if (practice) {
    state = "practice";
    title = "Practice mode \u2014 no orders are sent";
    detail = selectedTradingEnabled
      ? "The bot is running and picking trades, but nothing is sent to Alpaca."
      : "The bot is stopped. Start Trading runs it in practice mode.";
  } else if (selectedTradingEnabled) {
    state = "live";
    title = "Paper trading live";
    detail = "The bot is running and sending paper orders to Alpaca.";
  } else {
    title = "New buys stopped";
    detail = selectedRisk.exits_managed_when_stopped
      ? "Stop-losses and exits on open positions are still managed. Start Trading resumes buying."
      : "Practice mode is off, so Start Trading will send paper orders.";
  }
  if (selectedConnected && selectedRisk.daily_loss_breached) {
    state = "stopped";
    title = "Daily loss limit hit";
    detail = `${selectedRisk.daily_loss_detail || "No new buys until the next session."} Stops and exits are still managed.`;
  }
  if (selectedConnected && selectedLiveDryRun !== null && fields.dryRun.checked !== selectedLiveDryRun) {
    detail += ` Practice mode will turn ${fields.dryRun.checked ? "on" : "off"} when you click Save, Apply Changes, or Start Trading.`;
  }
  els.tradingStatusBar.classList.remove("stopped", "practice", "live");
  els.tradingStatusBar.classList.add(state);
  els.tradingStatusTitle.textContent = title;
  els.tradingStatusDetail.textContent = detail;
  if (els.tradingStatusStats) {
    const parts = [];
    if (selectedConnected && selectedStats.scanned) parts.push(`Scanning ${selectedStats.scanned} stocks`);
    if (selectedConnected && selectedStats.positions) {
      parts.push(`${selectedStats.protectedCount} of ${selectedStats.positions} positions protected`);
    }
    els.tradingStatusStats.textContent = parts.join(" · ");
  }
}

function renderRealizedPlMetric(account = currentSelectedAccount) {
  const rawText = account.realized_pl_raw ?? account.realized_pl ?? "";
  const display = account.realized_pl_display || "Unavailable";
  els.realizedPl.textContent = display;
  els.realizedPl.className = metricPolarityClass(rawText);
  if (els.realizedPlDetail) els.realizedPlDetail.textContent = metricSessionDetail(account.realized_pl_session_date);
}

function metricPolarityClass(rawValue) {
  if (rawValue === undefined || rawValue === null || String(rawValue).trim() === "") return "";
  return Number(rawValue) >= 0 ? "positive" : "negative";
}

function dailyPlDisplay(account = {}) {
  const amount = account.daily_pl_display || account.daily_pl || "Unavailable";
  const pct = account.daily_pl_pct_display || "";
  if (amount === "Unavailable" || pct === "Unavailable" || !pct) return amount;
  return `${amount} (${pct})`;
}

function metricSessionDetail(sessionDate) {
  return sessionDate ? `Session ${sessionDate}` : "";
}

function boundedIntegerInput(input, fallback, min, max) {
  const value = parseInt(input?.value ?? "", 10);
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

function formatCount(value) {
  const numberValue = Number(value || 0);
  return Number.isFinite(numberValue) ? numberValue.toLocaleString() : "0";
}

function backtestNumber(id, fallback) {
  const input = document.querySelector(`#${id}`);
  const value = Number(input?.value ?? "");
  return Number.isFinite(value) ? value : fallback;
}

function backtestString(id, fallback) {
  const input = document.querySelector(`#${id}`);
  return String(input?.value || fallback);
}

function readBacktestPayload() {
  return {
    days: boundedIntegerInput(els.backtestDays, 1, 1, 30),
    max_events: boundedIntegerInput(els.backtestMaxEvents, 20000, 0, 500000),
    latest_events: Boolean(els.backtestLatestEvents?.checked),
    strategy_overrides: {
      min_entry_score: backtestNumber("backtestMinEntryScore", 44),
      min_session_change_percent: backtestNumber("backtestMinSessionChange", 1.35),
      min_recent_momentum_percent: backtestNumber("backtestMinRecentMomentum", 0.05),
      min_long_momentum_percent: backtestNumber("backtestMinLongMomentum", 0.05),
      min_vwap_distance_percent: backtestNumber("backtestMinVwapDistance", 0.05),
      max_vwap_distance_percent: backtestNumber("backtestMaxVwapDistance", 2.25),
      max_session_pullback_percent: backtestNumber("backtestMaxSessionPullback", 0.9),
      max_recent_pullback_percent: backtestNumber("backtestMaxRecentPullback", 0.55),
      buy_rsi_min: backtestNumber("backtestBuyRsiMin", 42),
      buy_rsi_max: backtestNumber("backtestBuyRsiMax", 68),
      min_smi: backtestNumber("backtestMinSmi", 40),
      volume_multiplier: backtestNumber("backtestVolumeMultiplier", 1.5),
      min_avg_volume: backtestNumber("backtestMinAvgVolume", 0),
      take_profit_percent: backtestNumber("backtestTakeProfit", 2.5),
      stop_loss_percent: backtestNumber("backtestStopLoss", 1.25),
      inverse_etf_mode: backtestString("backtestInverseEtfMode", "allow"),
      score_weight_rsi: backtestNumber("backtestWeightRsi", 5),
      score_weight_relative_volume: backtestNumber("backtestWeightRelativeVolume", 13),
      score_weight_momentum: backtestNumber("backtestWeightMomentum", 14),
      score_weight_recent_momentum: backtestNumber("backtestWeightRecentMomentum", 8),
      score_weight_long_momentum: backtestNumber("backtestWeightLongMomentum", 14),
      score_weight_session_change: backtestNumber("backtestWeightSessionChange", 16),
      score_weight_vwap: backtestNumber("backtestWeightVwap", 14),
      score_weight_smi: backtestNumber("backtestWeightSmi", 7),
      score_weight_volatility: backtestNumber("backtestWeightVolatility", 0),
      score_weight_flow: backtestNumber("backtestWeightFlow", 3),
      score_weight_pullback_penalty: 0,
      score_weight_overbought_penalty: 0,
      score_weight_volatility_penalty: backtestNumber("backtestWeightVolatilityPenalty", 4),
      score_weight_session_extension_penalty: backtestNumber("backtestWeightSessionExtensionPenalty", 4),
      score_weight_vwap_extension_penalty: backtestNumber("backtestWeightVwapExtensionPenalty", 10),
      score_weight_session_pullback_penalty: backtestNumber("backtestWeightSessionPullbackPenalty", 9),
      score_weight_recent_pullback_penalty: backtestNumber("backtestWeightRecentPullbackPenalty", 6),
      score_weight_smi_overheat_penalty: backtestNumber("backtestWeightSmiOverheatPenalty", 4),
    },
    sizing_overrides: {
      starting_equity: backtestNumber("backtestStartingEquity", 1000),
      starting_cash: backtestNumber("backtestStartingCash", 1000),
      trade_size_mode: backtestString("backtestTradeSizeMode", "percent"),
      trade_percent: backtestNumber("backtestTradePercent", 5),
      trade_notional: backtestNumber("backtestTradeNotional", 0),
      max_positions: backtestNumber("backtestMaxPositions", 20),
      total_exposure_percent: backtestNumber("backtestTotalExposure", 100),
    },
  };
}

async function runDayTapeBacktest() {
  if (!els.runBacktestButton) return;
  const previousText = els.runBacktestButton.textContent;
  els.runBacktestButton.disabled = true;
  els.runBacktestButton.textContent = "Running";
  els.backtestRunStatus.textContent = "Reading day tape";
  try {
    const report = await postJson("/api/backtest/day-tape", readBacktestPayload());
    renderBacktestReport(report);
  } catch (error) {
    els.backtestRunStatus.textContent = `Backtest failed: ${error.message}`;
  } finally {
    els.runBacktestButton.disabled = false;
    els.runBacktestButton.textContent = previousText;
  }
}

function renderBacktestReport(report = {}) {
  const summary = report.summary || {};
  const counts = summary.counts || {};
  const expectedSource = summary.expected_top_volume_source || "alpaca_most_actives_volume";
  const evaluationsBySource = summary.evaluations_by_top_volume_source || {};
  const sourceEvaluations = evaluationsBySource[expectedSource] || 0;
  const statusText = report.ok ? "Pass" : report.pending ? "Pending" : "Review";

  els.backtestSummary.hidden = false;
  els.backtestDetail.hidden = false;
  els.backtestEngine.textContent = summary.selection_engine || "-";
  const strategyOverrides = summary.strategy_overrides || {};
  const harness = summary.sizing_harness || {};
  els.backtestStrategy.textContent = `${Object.keys(strategyOverrides).length} override(s)`;
  els.backtestHarness.textContent = `${harness.trade_size_mode || "-"} ${harness.max_positions || "-"} pos`;
  els.backtestEvaluations.textContent = formatCount(counts.evaluations);
  els.backtestAccepted.textContent = formatCount(counts.accepted_trades);
  els.backtestRejected.textContent = formatCount(counts.rejected_candidates);
  els.backtestSource.textContent = `${expectedSource}: ${formatCount(sourceEvaluations)}`;
  els.backtestStatus.textContent = statusText;
  els.backtestStatus.className = report.ok ? "positive" : "negative";
  els.backtestRunStatus.textContent = report.pending || `Files: ${(report.files || []).join(", ") || "none"}`;

  const checkRows = (report.checks || []).map((item) => ({
    name: item.name || "",
    status: item.ok ? "OK" : "Review",
    detail: item.detail || "",
  }));
  renderRows(els.backtestCheckRows, checkRows, ["name", "status", "detail"]);

  const acceptedRows = (summary.accepted_trades || []).slice(0, 50).map((trade) => ({
    symbol: trade.symbol || "",
    score: trade.score || "",
    entry_price: trade.entry_price || "",
    qty: trade.qty || "",
    notional: trade.notional || "",
  }));
  renderRows(els.backtestAcceptedRows, acceptedRows, ["symbol", "score", "entry_price", "qty", "notional"]);

  const rejectedRows = (summary.rejected_candidates_sample || []).slice(0, 50).map((row) => ({
    symbol: row.symbol || "",
    reason: row.reason || "",
  }));
  renderRows(els.backtestRejectedRows, rejectedRows, ["symbol", "reason"]);
}

function renderReplay(replay) {
  const path = replay.path || "";
  els.replayStatus.textContent = path ? `Writing replay/debug events to ${path}` : "Replay file not initialized.";
  renderRows(els.replayRows, replay.events || [], ["time", "kind", "summary"]);
}

function renderMarketClock(clock) {
  renderMarketClockInto(
    clock,
    els.marketStatus,
    els.marketStatusText,
    els.marketStatusDetail,
    "Connect an account to read Alpaca market hours."
  );
}

function renderMarketClockInto(clock, box, statusEl, detailEl, disconnectedDetail) {
  const status = clock?.status || "Not connected";
  const detail = clock?.detail || disconnectedDetail;
  statusEl.textContent = status;
  detailEl.textContent = detail;
  box.classList.toggle("open", Boolean(clock?.is_open));
  box.classList.toggle("closed", Boolean(clock && !clock.is_open && status !== "Not connected"));
}

function renderAccountCards(accounts) {
  els.accountCards.innerHTML = "";
  if (!accounts.length) {
    els.accountCards.innerHTML = '<article class="account-card muted-card">No accounts yet</article>';
    return;
  }

  accounts.forEach((account) => {
    const card = document.createElement("button");
    card.className = `account-card ${account.account_id === selectedAccountId ? "active" : ""}`;
    card.type = "button";
    card.dataset.accountId = account.account_id;
    const strategyLabel = accountStrategyLabel(account);
    const equityText = account.connected && account.equity ? String(account.equity) : "—";
    const dotState = account.trading_enabled ? "live" : account.connected ? "idle" : "off";
    card.title = account.status || "Not connected";
    card.innerHTML = `
      <span class="pill-dot ${dotState}" aria-hidden="true"></span>
      <span class="pill-name">${escapeHtml(account.name || "Paper Account")}</span>
      <strong>${escapeHtml(equityText)}</strong>
      <small>${escapeHtml(strategyLabel)}</small>
      <em class="${Number(account.daily_pl_raw || 0) >= 0 ? "positive" : "negative"}">${escapeHtml(dailyPlDisplay(account))}</em>
    `;
    card.addEventListener("click", async () => {
      await switchToAccount(account.account_id);
    });
    els.accountCards.appendChild(card);
  });
}

function renderRows(tbody, rows, keys) {
  tableRenderCache[tbody.id] = { tbody, rows, keys };
  tbody.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = keys.length;
    td.textContent = "No rows";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  sortRowsForTable(tbody.id, rows).forEach((row) => {
    const tr = document.createElement("tr");
    keys.forEach((key) => {
      const td = document.createElement("td");
      td.textContent = row[key] ?? "";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

window.addEventListener("unhandledrejection", (event) => {
  els.statusText.textContent = event.reason?.message || String(event.reason);
});

// Market overview: index ETF charts, a top-movers ticker tape, and headlines. The server caches
// it for a minute (about three market-data calls a minute), so polling every 30s stays cheap.
const MARKET_OVERVIEW_POLL_MS = 30000;
const NEWS_FLASH_MS = 15000;
const NEWS_FLASH_MAX_AGE_MS = 30 * 60 * 1000;
const SVG_NS = "http://www.w3.org/2000/svg";
const MARKET_TIME_ZONE = "America/New_York";
let seenNewsIds = null;
let newsFlashTimer = 0;
let tickerSymbolsSignature = "";

function makeEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function makeSvg(tag, attributes = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

function formatQuotePrice(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  const digits = number < 1 ? 4 : 2;
  return `$${number.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function formatSignedPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function formatSignedMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return `${number > 0 ? "+" : number < 0 ? "-" : ""}$${Math.abs(number).toFixed(2)}`;
}

function directionClass(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "flat";
  return number > 0 ? "up" : "down";
}

function marketTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: MARKET_TIME_ZONE });
}

function sessionLabel(isoDate) {
  if (!isoDate) return "";
  const date = new Date(`${isoDate}T12:00:00Z`);
  return date.toLocaleDateString([], { month: "short", day: "numeric", timeZone: "UTC" });
}

function timeAgo(iso) {
  const time = new Date(iso).getTime();
  if (!Number.isFinite(time)) return "";
  const minutes = Math.max(0, Math.round((Date.now() - time) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
}

function openSymbolLookup(symbol) {
  showView("dashboardView");
  fields.lookupSymbol.value = symbol;
  lookupSymbol();
  fields.lookupSymbol.closest(".lookup-card")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function loadMarketOverview() {
  if (document.body.classList.contains("market-overview-hidden")) return;
  try {
    const response = await fetchWithRecovery("/api/market-overview", { cache: "no-store" });
    if (!response.ok) throw new Error(response.statusText);
    renderMarketOverview(await response.json());
  } catch (error) {
    if (isAbortError(error)) return;
    els.indexBoxUpdated.textContent = `Market overview unavailable: ${error.message}`;
  }
}

function renderMarketOverview(payload = {}) {
  if (!payload.connected) {
    els.indexBoxUpdated.textContent = "Connect an account to load the index charts.";
    els.newsUpdated.textContent = "Connect an account to load headlines.";
    renderIndexCharts([]);
    renderTickerTape({});
    renderNews([]);
    return;
  }
  const indexes = payload.indexes || [];
  const session = sessionLabel(indexes.find((card) => card.session_date)?.session_date);
  const updated = payload.updated_at ? marketTime(payload.updated_at) : "";
  const errors = (payload.errors || []).join(" ");
  els.indexBoxUpdated.textContent = [
    session ? `${session} session` : "",
    updated ? `updated ${updated} ET` : "",
    errors,
  ].filter(Boolean).join(" · ");
  renderIndexCharts(indexes);
  renderTickerTape(payload.movers || {});
  renderNews(payload.news || []);
}

function renderIndexCharts(cards) {
  els.indexCharts.replaceChildren();
  if (!cards.length) {
    els.indexCharts.appendChild(makeEl("p", "market-empty", "No index data yet."));
    return;
  }
  cards.forEach((card) => els.indexCharts.appendChild(indexChartCard(card)));
}

function indexChartCard(card) {
  const direction = directionClass(card.change);
  const article = makeEl("article", `index-card ${direction}`);
  const head = makeEl("header", "index-card-head");
  const title = makeEl("div", "index-card-title");
  title.append(makeEl("strong", "", card.name || card.symbol), makeEl("span", "", card.symbol));
  const change = makeEl("span", `index-card-change ${direction}`, formatSignedPercent(card.change_pct));
  head.append(title, change);
  const quote = makeEl("div", "index-card-quote");
  const price = makeEl("strong", "", formatQuotePrice(card.price));
  const detail = makeEl("span", `index-card-detail ${direction}`, formatSignedMoney(card.change));
  quote.append(price, detail);
  const readout = makeEl("span", "index-card-readout");
  readout.setAttribute("aria-live", "polite");
  article.append(head, quote, indexChartSvg(card, readout, price, detail), readout);
  return article;
}

function indexChartSvg(card, readout, priceEl, detailEl) {
  const width = 240;
  const height = 80;
  const pad = 3;
  const svg = makeSvg("svg", { viewBox: `0 0 ${width} ${height}`, class: "index-chart", role: "img" });
  const points = (card.points || []).map((point) => ({ t: new Date(point.t).getTime(), c: Number(point.c) }))
    .filter((point) => Number.isFinite(point.t) && Number.isFinite(point.c));
  const previous = Number(card.previous_close);
  svg.setAttribute(
    "aria-label",
    `${card.name || card.symbol} today: ${formatQuotePrice(card.price)}, ${formatSignedPercent(card.change_pct)} from the previous close`
  );
  if (!points.length) {
    const empty = makeSvg("text", { x: width / 2, y: height / 2, class: "index-chart-empty", "text-anchor": "middle" });
    empty.textContent = "No bars yet";
    svg.appendChild(empty);
    return svg;
  }
  const start = new Date(card.session_start).getTime() || points[0].t;
  const end = new Date(card.session_end).getTime() || points[points.length - 1].t;
  const values = points.map((point) => point.c).concat(Number.isFinite(previous) && previous > 0 ? [previous] : []);
  let low = Math.min(...values);
  let high = Math.max(...values);
  const span = high - low || high * 0.001 || 1;
  low -= span * 0.08;
  high += span * 0.08;
  const x = (time) => pad + ((time - start) / Math.max(1, end - start)) * (width - pad * 2);
  const y = (value) => pad + (1 - (value - low) / (high - low)) * (height - pad * 2);
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(point.t).toFixed(1)},${y(point.c).toFixed(1)}`).join(" ");
  const lastX = x(points[points.length - 1].t).toFixed(1);
  const firstX = x(points[0].t).toFixed(1);
  svg.appendChild(makeSvg("path", { d: `${line} L${lastX},${height} L${firstX},${height} Z`, class: "index-chart-area" }));
  if (Number.isFinite(previous) && previous > 0) {
    const baseline = y(previous).toFixed(1);
    svg.appendChild(makeSvg("line", { x1: pad, x2: width - pad, y1: baseline, y2: baseline, class: "index-chart-baseline" }));
  }
  svg.appendChild(makeSvg("path", { d: line, class: "index-chart-line" }));
  const marker = makeSvg("circle", { r: 3, class: "index-chart-marker", visibility: "hidden" });
  svg.appendChild(marker);

  const resetReadout = () => {
    marker.setAttribute("visibility", "hidden");
    readout.textContent = `Prev close ${formatQuotePrice(previous)}`;
  };
  const showPoint = (clientX) => {
    const box = svg.getBoundingClientRect();
    const time = start + ((clientX - box.left) / Math.max(1, box.width)) * (end - start);
    let nearest = points[0];
    points.forEach((point) => {
      if (Math.abs(point.t - time) < Math.abs(nearest.t - time)) nearest = point;
    });
    marker.setAttribute("cx", x(nearest.t).toFixed(1));
    marker.setAttribute("cy", y(nearest.c).toFixed(1));
    marker.setAttribute("visibility", "visible");
    const pct = Number.isFinite(previous) && previous > 0 ? (nearest.c / previous - 1) * 100 : NaN;
    readout.textContent = `${marketTime(new Date(nearest.t).toISOString())} ET · ${formatQuotePrice(nearest.c)} · ${formatSignedPercent(pct)}`;
  };
  svg.addEventListener("pointermove", (event) => showPoint(event.clientX));
  svg.addEventListener("pointerleave", resetReadout);
  resetReadout();
  return svg;
}

function tickerItem(item) {
  const direction = directionClass(item.change_pct);
  const button = makeEl("button", `ticker-item ${direction}`);
  button.type = "button";
  button.dataset.symbol = item.symbol;
  button.title = `Look up ${item.symbol}`;
  button.append(
    makeEl("strong", "", item.symbol),
    makeEl("span", "ticker-price", formatQuotePrice(item.price)),
    makeEl("span", "ticker-change", `${direction === "up" ? "▲" : direction === "down" ? "▼" : ""} ${formatSignedPercent(item.change_pct)}`)
  );
  button.addEventListener("click", () => openSymbolLookup(item.symbol));
  return button;
}

function tickerGroup(gainers, losers, duplicate) {
  const group = makeEl("div", "ticker-group");
  if (duplicate) {
    group.setAttribute("aria-hidden", "true");
    group.inert = true;
  }
  if (gainers.length) {
    group.appendChild(makeEl("span", "ticker-label up", "Top gainers"));
    gainers.forEach((item) => group.appendChild(tickerItem(item)));
  }
  if (losers.length) {
    group.appendChild(makeEl("span", "ticker-label down", "Top losers"));
    losers.forEach((item) => group.appendChild(tickerItem(item)));
  }
  return group;
}

function renderTickerTape(movers) {
  const gainers = movers.gainers || [];
  const losers = movers.losers || [];
  const signature = gainers.concat(losers).map((item) => item.symbol).join(",");
  if (signature && signature === tickerSymbolsSignature) {
    // Same symbols: update the numbers in place so the scroll doesn't restart.
    gainers.concat(losers).forEach((item) => {
      els.tickerTrack.querySelectorAll(`[data-symbol="${CSS.escape(item.symbol)}"]`).forEach((button) => {
        const direction = directionClass(item.change_pct);
        button.className = `ticker-item ${direction}`;
        button.querySelector(".ticker-price").textContent = formatQuotePrice(item.price);
        button.querySelector(".ticker-change").textContent =
          `${direction === "up" ? "▲" : direction === "down" ? "▼" : ""} ${formatSignedPercent(item.change_pct)}`;
      });
    });
    return;
  }
  tickerSymbolsSignature = signature;
  els.tickerTrack.replaceChildren();
  if (!signature) {
    els.tickerTrack.classList.remove("scrolling");
    els.tickerTrack.appendChild(makeEl("span", "ticker-empty", "Top movers load once an account is connected."));
    return;
  }
  const first = tickerGroup(gainers, losers, false);
  els.tickerTrack.append(first, tickerGroup(gainers, losers, true));
  // About 50px a second whatever the content width.
  els.tickerTrack.style.setProperty("--ticker-duration", `${Math.max(30, Math.round(first.scrollWidth / 50))}s`);
  els.tickerTrack.classList.add("scrolling");
}

function renderNews(items) {
  els.newsList.replaceChildren();
  if (!items.length) {
    els.newsList.appendChild(makeEl("li", "market-empty", "No headlines yet."));
  }
  const fresh = [];
  items.forEach((item) => {
    const isNew = seenNewsIds !== null && !seenNewsIds.has(item.id);
    if (isNew && Date.now() - new Date(item.created_at).getTime() < NEWS_FLASH_MAX_AGE_MS) fresh.push(item);
    const li = makeEl("li", isNew ? "news-item is-new" : "news-item");
    const link = makeEl("a", "news-headline", item.headline);
    if (item.url) {
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
    const meta = makeEl("div", "news-meta");
    meta.appendChild(makeEl("span", "", [timeAgo(item.created_at), item.source].filter(Boolean).join(" · ")));
    (item.symbols || []).forEach((symbol) => {
      const chip = makeEl("button", "news-symbol", symbol);
      chip.type = "button";
      chip.title = `Look up ${symbol}`;
      chip.addEventListener("click", () => openSymbolLookup(symbol));
      meta.appendChild(chip);
    });
    li.append(link, meta);
    els.newsList.appendChild(li);
  });
  seenNewsIds = new Set([...(seenNewsIds || []), ...items.map((item) => item.id)]);
  els.newsUpdated.textContent = items.length
    ? `Latest ${items.length} headlines for the indexes and the stocks you hold or watch.`
    : "Headlines for the indexes and the stocks you hold or watch.";
  if (fresh.length) flashNews(fresh[0]);
}

function flashNews(item) {
  els.newsFlashText.textContent = item.headline;
  if (item.url) els.newsFlash.href = item.url;
  else els.newsFlash.removeAttribute("href");
  els.newsFlash.hidden = false;
  els.newsFlash.classList.remove("flashing");
  void els.newsFlash.offsetWidth; // restart the highlight animation
  els.newsFlash.classList.add("flashing");
  clearTimeout(newsFlashTimer);
  newsFlashTimer = setTimeout(() => {
    els.newsFlash.hidden = true;
  }, NEWS_FLASH_MS);
}

function setMarketOverviewHidden(hidden) {
  document.body.classList.toggle("market-overview-hidden", hidden);
  els.marketOverviewToggle.setAttribute("aria-pressed", String(!hidden));
  try {
    if (hidden) localStorage.setItem("apt-market-overview", "hidden");
    else localStorage.removeItem("apt-market-overview");
  } catch {
    // storage unavailable: the choice still applies for this session
  }
  if (!hidden) loadMarketOverview();
}

let marketOverviewHidden = false;
try {
  marketOverviewHidden = localStorage.getItem("apt-market-overview") === "hidden";
} catch {
  marketOverviewHidden = false;
}
document.body.classList.toggle("market-overview-hidden", marketOverviewHidden);
els.marketOverviewToggle.setAttribute("aria-pressed", String(!marketOverviewHidden));
els.marketOverviewToggle.addEventListener("click", () =>
  setMarketOverviewHidden(!document.body.classList.contains("market-overview-hidden"))
);

checkRuntimeHealth().then(() => loadSettings()).then(async () => {
  updateAllTableSortButtons();
  await loadState({ accountId: selectedAccountId, source: "startup" });
  await loadDashboard({ accountId: selectedAccountId, source: "startup" });
  loadMarketOverview();
}).catch(async (error) => {
  if (await recoverStaleInstance(error)) return;
  els.statusText.textContent = error.message;
  els.topVolumeUpdated.textContent = "This app instance is not responding.";
});
setInterval(() => loadState({ source: "poll" }), 2000);
setInterval(() => loadDashboard({ source: "poll" }), 5000);
setInterval(loadMarketOverview, MARKET_OVERVIEW_POLL_MS);
