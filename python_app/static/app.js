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
  smiPeriod: document.querySelector("#smiPeriod"),
  minSmi: document.querySelector("#minSmi"),
  atrPeriod: document.querySelector("#atrPeriod"),
  minBuyVolumeRatio: document.querySelector("#minBuyVolumeRatio"),
  reentryScoreBoost: document.querySelector("#reentryScoreBoost"),
  inverseEtfMode: document.querySelector("#inverseEtfMode"),
  sellRsi: document.querySelector("#sellRsi"),
  volumePeriod: document.querySelector("#volumePeriod"),
  volumeMultiplier: document.querySelector("#volumeMultiplier"),
  minAvgVolume: document.querySelector("#minAvgVolume"),
  takeProfitPercent: document.querySelector("#takeProfitPercent"),
  profitTrailStartPercent: document.querySelector("#profitTrailStartPercent"),
  profitTrailDropPercent: document.querySelector("#profitTrailDropPercent"),
  stopLossPercent: document.querySelector("#stopLossPercent"),
  stopLossGraceMinutes: document.querySelector("#stopLossGraceMinutes"),
  exitTimeInForce: document.querySelector("#exitTimeInForce"),
  cooldownMinutes: document.querySelector("#cooldownMinutes"),
  entryOpenGuardMinutes: document.querySelector("#entryOpenGuardMinutes"),
  entryCloseGuardMinutes: document.querySelector("#entryCloseGuardMinutes"),
  lookupSymbol: document.querySelector("#lookupSymbol"),
};

const els = {
  statusText: document.querySelector("#statusText"),
  runtimeHealthBanner: document.querySelector("#runtimeHealthBanner"),
  runtimeHealthText: document.querySelector("#runtimeHealthText"),
  dashboardView: document.querySelector("#dashboardView"),
  accountsView: document.querySelector("#accountsView"),
  navButtons: document.querySelectorAll(".nav-button"),
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
  realizedPl: document.querySelector("#realizedPl"),
  realizedPercentToggle: document.querySelector("#realizedPercentToggle"),
  buyingPower: document.querySelector("#buyingPower"),
  cash: document.querySelector("#cash"),
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
  logRows: document.querySelector("#logRows"),
  newAccountButton: document.querySelector("#newAccountButton"),
  saveAccountButton: document.querySelector("#saveAccountButton"),
  removeAccountButton: document.querySelector("#removeAccountButton"),
  saveCustomProfileButton: document.querySelector("#saveCustomProfileButton"),
  profileStatus: document.querySelector("#profileStatus"),
  applyParametersButton: document.querySelector("#applyParametersButton"),
  parameterStatus: document.querySelector("#parameterStatus"),
  connectButton: document.querySelector("#connectButton"),
  refreshButton: document.querySelector("#refreshButton"),
  tradingToggleButton: document.querySelector("#tradingToggleButton"),
  cancelOrdersButton: document.querySelector("#cancelOrdersButton"),
  purgeAccountButton: document.querySelector("#purgeAccountButton"),
  refreshAllButton: document.querySelector("#refreshAllButton"),
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
  "smi_period",
  "min_smi",
  "atr_period",
  "min_buy_volume_ratio",
  "reentry_score_boost",
  "inverse_etf_mode",
  "sell_rsi",
  "volume_period",
  "volume_multiplier",
  "min_avg_volume",
  "take_profit_percent",
  "profit_trail_start_percent",
  "profit_trail_drop_percent",
  "stop_loss_percent",
  "stop_loss_grace_minutes",
  "exit_time_in_force",
  "cooldown_minutes",
  "entry_open_guard_minutes",
  "entry_close_guard_minutes",
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
  "smi_period",
  "min_smi",
  "atr_period",
  "min_buy_volume_ratio",
  "reentry_score_boost",
  "inverse_etf_mode",
  "sell_rsi",
  "volume_period",
  "volume_multiplier",
  "min_avg_volume",
  "take_profit_percent",
  "profit_trail_start_percent",
  "profit_trail_drop_percent",
  "stop_loss_percent",
  "stop_loss_grace_minutes",
  "cooldown_minutes",
  "entry_open_guard_minutes",
  "entry_close_guard_minutes",
]);

let savedAccounts = [];
let profiles = {};
let selectedAccountId = "";
let isDraftAccount = false;
let selectedTradingEnabled = false;
let selectedConnected = false;
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
};
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
let showRealizedPlPercent = false;
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

els.realizedPercentToggle.addEventListener("change", () => {
  showRealizedPlPercent = els.realizedPercentToggle.checked;
  renderRealizedPlMetric();
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}`).classList.add("active");
  });
});

fields.accountSelect.addEventListener("change", async () => {
  const nextAccountId = fields.accountSelect.value;
  const previousAccountId = selectedAccountId;
  try {
    if (previousAccountId || hasAccountFormData()) {
      await saveCurrentAccountDraft(false);
    }
  } catch (error) {
    fields.accountSelect.value = previousAccountId;
    throw error;
  }

  selectedAccountId = nextAccountId;
  fields.accountSelect.value = nextAccountId;
  if (!nextAccountId) {
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
  const account = findSavedAccount(nextAccountId);
  if (account) applyAccount(account);
  await postJson("/api/select-account", { account_id: nextAccountId });
  await loadState();
  await loadDashboard();
});

fields.profile.addEventListener("change", async () => {
  await applyProfilePreset();
});

fields.remember.addEventListener("change", syncAutoConnectControl);
fields.autoConnect.addEventListener("change", syncAutoConnectControl);

els.saveCustomProfileButton.addEventListener("click", saveCustomProfile);

configKeys
  .filter((key) => key !== "profile")
  .forEach((key) => {
    const field = fields[toCamel(key)];
    if (!field) return;
    field.addEventListener("input", () => handleConfigFieldChange(key));
    field.addEventListener("change", () => handleConfigFieldChange(key));
  });

els.newAccountButton.addEventListener("click", async () => {
  if (selectedAccountId || hasAccountFormData()) {
    await saveCurrentAccountDraft(false);
  }
  selectedAccountId = "";
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
  fields.accountSelect.value = "";
  els.statusText.textContent = "New account draft";
});

els.saveAccountButton.addEventListener("click", async () => {
  await saveCurrentAccountDraft(true);
  parameterDirty = false;
  await loadSettings();
  await loadState();
});

els.removeAccountButton.addEventListener("click", async () => {
  if (!selectedAccountId) return;
  const account = findSavedAccount(selectedAccountId);
  const name = account?.name || "this account";
  if (!window.confirm(`Remove ${name} from the app? Connected trading for it will stop.`)) return;
  await fetchWithRecovery(`/api/accounts/${encodeURIComponent(selectedAccountId)}`, { method: "DELETE" });
  await loadSettings();
  await loadState();
});

els.connectButton.addEventListener("click", async () => {
  const state = await postJson("/api/connect", readAccountPayload());
  selectedAccountId = state.selected_account_id || state.selected?.account_id || selectedAccountId;
  await loadSettings();
  renderState(state);
  await loadDashboard();
});

els.refreshButton.addEventListener("click", async () => {
  await postJson("/api/accounts", readAccountPayload());
  parameterDirty = false;
  const state = await postJson("/api/refresh", { account_id: selectedAccountId || null });
  await loadSettings();
  renderState(state);
  await loadDashboard();
});

els.applyParametersButton.addEventListener("click", applyCurrentParameters);

els.refreshAllButton.addEventListener("click", async () => {
  const state = await postJson("/api/refresh-all", {});
  renderState(state);
  await loadDashboard();
});

els.tradingToggleButton.addEventListener("click", async () => {
  const wasTrading = selectedTradingEnabled;
  const previousText = els.tradingToggleButton.textContent;
  els.tradingToggleButton.disabled = true;
  els.tradingToggleButton.textContent = wasTrading ? "Stopping..." : "Starting...";
  try {
    let state;
    if (wasTrading) {
      state = await postJson("/api/stop", { account_id: selectedAccountId || null });
    } else {
      await postJson("/api/accounts", readAccountPayload());
      parameterDirty = false;
      state = await postJson("/api/start", { account_id: selectedAccountId || null });
      await loadSettings();
    }
    renderState(state);
    await loadDashboard();
  } catch (error) {
    els.parameterStatus.textContent = `${wasTrading ? "Stop" : "Start"} failed: ${error.message}`;
    els.tradingToggleButton.textContent = previousText;
    els.tradingToggleButton.disabled = !selectedConnected;
  }
});

els.cancelOrdersButton.addEventListener("click", async () => {
  if (!window.confirm("Cancel all open paper orders for the selected account?")) return;
  const state = await postJson("/api/cancel-orders", { account_id: selectedAccountId || null });
  renderState(state);
});

els.purgeAccountButton.addEventListener("click", async () => {
  const account = findSavedAccount(selectedAccountId);
  const name = account?.name || "the selected account";
  const confirmed = window.confirm(
    `Purge ${name}? This stops auto trading, cancels open orders, submits paper market sell orders for every current position, and resets strategy state. Trade history, ledger, replay, logs, and saved settings stay preserved.`
  );
  if (!confirmed) return;
  const state = await postJson("/api/purge-account", { account_id: selectedAccountId || null });
  renderState(state);
  await loadDashboard();
});

els.refreshTopVolumeButton.addEventListener("click", async () => {
  const dashboard = await postJson("/api/dashboard/top-volume", { account_id: selectedAccountId || null });
  renderDashboard(dashboard);
});

els.reconnectStreamButton.addEventListener("click", reconnectDashboardStream);

els.lookupButton.addEventListener("click", lookupSymbol);

fields.lookupSymbol.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  await lookupSymbol();
});

function showView(viewId) {
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  const target = document.querySelector(`#${viewId}`);
  if (target) target.classList.add("active");
  els.navButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewId);
  });
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

async function saveCurrentAccountDraft(applySavedAccount = true) {
  const state = await postJson("/api/accounts", readAccountPayload());
  selectedAccountId = state.selected_account_id || state.selected?.account_id || selectedAccountId;
  isDraftAccount = false;
  parameterDirty = false;
  await loadSettings({ applySelected: applySavedAccount });
  return state;
}

function readConfig() {
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
    max_trade_notional: readNumber("maxTradeNotional", 35),
    max_trade_percent: readNumber("maxTradePercent", 7),
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
    smi_period: readInt("smiPeriod", 10),
    min_smi: readNumber("minSmi", 40),
    atr_period: readInt("atrPeriod", 14),
    min_buy_volume_ratio: readNumber("minBuyVolumeRatio", 0.5),
    reentry_score_boost: readNumber("reentryScoreBoost", 12),
    inverse_etf_mode: fields.inverseEtfMode.value,
    sell_rsi: readNumber("sellRsi", 72),
    volume_period: readInt("volumePeriod", 20),
    volume_multiplier: readNumber("volumeMultiplier", 1.5),
    min_avg_volume: readNumber("minAvgVolume", 0),
    take_profit_percent: readNumber("takeProfitPercent", 2.5),
    profit_trail_start_percent: readNumber("profitTrailStartPercent", 0),
    profit_trail_drop_percent: readNumber("profitTrailDropPercent", 0),
    stop_loss_percent: readNumber("stopLossPercent", 1.25),
    stop_loss_grace_minutes: readInt("stopLossGraceMinutes", 0),
    exit_time_in_force: fields.exitTimeInForce.value,
    cooldown_minutes: readInt("cooldownMinutes", 0),
    entry_open_guard_minutes: readInt("entryOpenGuardMinutes", 15),
    entry_close_guard_minutes: readInt("entryCloseGuardMinutes", 15),
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
  renderCredentialStatus(account);
  applyConfig(account.config || presetConfig("neutral"));
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
    ? "Credentials saved encrypted. Fields are blank unless you replace them."
    : sessionCredentials
      ? "Credentials loaded for this session. Check store encrypted to auto-connect next launch."
      : "No credentials loaded";
  const hasCredentials = savedCredentials || sessionCredentials;
  els.credentialStatus.classList.toggle("saved", hasCredentials);
  const placeholderPrefix = savedCredentials ? "Saved encrypted" : "Session credential";
  fields.apiKey.placeholder = hasCredentials ? `${placeholderPrefix} - enter new key to replace` : "Enter API key";
  fields.secretKey.placeholder = hasCredentials ? `${placeholderPrefix} - enter new secret to replace` : "Enter secret key";
}

function applyConfig(config) {
  if (!config) return;
  suppressProfileDirty = true;
  ensureProfileOption(config.profile || "custom", profileLabel(config.profile || "custom", config));
  fields.symbols.value = (config.symbols || ["SPY", "QQQ"]).join(",");
  configKeys.forEach((key) => {
    const camel = toCamel(key);
    const field = fields[camel];
    if (!field || config[key] === undefined || config[key] === null) return;
    if (field.type === "checkbox") {
      field.checked = Boolean(config[key]);
    } else {
      field.value = config[key];
    }
  });
  suppressProfileDirty = false;
  renderProfileStatus();
}

async function applyProfilePreset() {
  const config = await postJson("/api/profile", {
    profile: fields.profile.value,
    current: readConfig(),
  });
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
    const state = await postJson("/api/apply-parameters", readAccountPayload());
    selectedAccountId = state.selected_account_id || state.selected?.account_id || selectedAccountId;
    isDraftAccount = false;
    parameterDirty = false;
    await loadSettings({ applySelected: false });
    renderState(state);
    await loadDashboard();
  } catch (error) {
    els.parameterStatus.textContent = `Apply failed: ${error.message}`;
  } finally {
    els.applyParametersButton.disabled = false;
    els.applyParametersButton.textContent = previousText;
  }
}

async function saveCustomProfile() {
  const name = fields.customProfileName.value.trim() || "Custom Profile";
  const payload = await postJson("/api/custom-profile", {
    name,
    config: { ...readConfig(), profile: "custom" },
  });
  profiles = payload.profiles || profiles;
  renderProfileSelect(payload.profile);
  applyConfig(payload.config);
  els.profileStatus.textContent = `Saved ${profileLabel(payload.profile, payload.config)}.`;
  await saveCurrentAccountDraft(false);
}

function handleConfigFieldChange(key) {
  if (suppressProfileDirty) return;
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

function renderParameterStatus(selected = null) {
  if (!els.parameterStatus) return;
  const liveConfig = selected?.config || null;
  const uiConfig = readConfig();
  const liveMinScore = liveConfig?.min_entry_score ?? uiConfig.min_entry_score ?? 38;
  if (parameterDirty) {
    const livePart = liveConfig
      ? ` Live block still uses ${liveConfig.max_trade_percent}% equity, ${liveConfig.max_total_exposure_percent}% exposure, ${liveConfig.max_open_positions} max pos, min score ${liveMinScore}.`
      : "";
    els.parameterStatus.textContent = `Pending changes: strategy ${profileLabel(uiConfig.profile, profiles[uiConfig.profile] || {})}, trade ${uiConfig.max_trade_percent}% equity, exposure ${uiConfig.max_total_exposure_percent}%, max pos ${uiConfig.max_open_positions}, min score ${uiConfig.min_entry_score}.${livePart} Click Apply Changes to make it live.`;
    return;
  }
  if (!liveConfig) {
    els.parameterStatus.textContent = "Live parameters load after selecting an account.";
    return;
  }
  const profile = profileLabel(liveConfig.profile || "custom", liveConfig);
  els.parameterStatus.textContent = `Live: strategy ${profile}, trade ${liveConfig.max_trade_percent}% equity, exposure ${liveConfig.max_total_exposure_percent}%, max pos ${liveConfig.max_open_positions}, min score ${liveMinScore}.`;
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
    max_trade_notional: 35,
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
    smi_period: 10,
    min_smi: 40,
    atr_period: 14,
    min_buy_volume_ratio: 0.5,
    reentry_score_boost: 12,
    inverse_etf_mode: "allow",
    sell_rsi: 72,
    volume_period: 20,
    volume_multiplier: 1.5,
    min_avg_volume: 0,
    take_profit_percent: 2.5,
    profit_trail_start_percent: 0,
    profit_trail_drop_percent: 0,
    stop_loss_percent: 1.25,
    stop_loss_grace_minutes: 0,
    exit_time_in_force: "day",
    cooldown_minutes: 0,
    entry_open_guard_minutes: 15,
    entry_close_guard_minutes: 15,
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

async function postJson(url, body) {
  const response = await fetchWithRecovery(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail || response.statusText;
    throw new Error(detail);
  }
  return response.json();
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

function renderRuntimeHealth(health) {
  runtimeHealth = health || null;
  runtimeStale = Boolean(health && health.current === false);
  if (!els.runtimeHealthBanner || !els.runtimeHealthText) return;
  if (!health || health.current === true) {
    els.runtimeHealthBanner.hidden = true;
    els.runtimeHealthText.textContent = "";
    return;
  }
  els.runtimeHealthText.textContent = healthSummary(health);
  els.runtimeHealthBanner.hidden = false;
  els.statusText.textContent = "Stale runtime warning";
}

function renderRuntimeHealthError(message) {
  runtimeStale = true;
  if (els.runtimeHealthBanner && els.runtimeHealthText) {
    els.runtimeHealthText.textContent = message;
    els.runtimeHealthBanner.hidden = false;
  }
  els.statusText.textContent = "Runtime health unavailable";
}

async function checkRuntimeHealth() {
  try {
    const health = await fetchRuntimeHealth();
    renderRuntimeHealth(health);
    return health;
  } catch (error) {
    renderRuntimeHealthError(error.message || "Runtime health check failed.");
    return null;
  }
}

async function fetchWithRecovery(url, options) {
  try {
    return await fetch(url, options);
  } catch (error) {
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
  const { applySelected = true } = options;
  const response = await fetchWithRecovery("/api/settings");
  if (!response.ok) throw new Error(response.statusText);
  const payload = await response.json();
  profiles = payload.profiles || {};
  savedAccounts = payload.accounts || [];
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

async function loadState() {
  try {
    await checkRuntimeHealth();
    const suffix = selectedAccountId ? `?account_id=${encodeURIComponent(selectedAccountId)}` : "";
    const response = await fetchWithRecovery(`/api/state${suffix}`);
    if (!response.ok) throw new Error(response.statusText);
    const state = await response.json();
    renderState(state);
  } catch (error) {
    if (await recoverStaleInstance(error)) return;
    els.statusText.textContent = error.message;
  }
}

async function loadDashboard() {
  try {
    await checkRuntimeHealth();
    const suffix = selectedAccountId ? `?account_id=${encodeURIComponent(selectedAccountId)}` : "";
    const response = await fetchWithRecovery(`/api/dashboard${suffix}`);
    if (!response.ok) throw new Error(response.statusText);
    const dashboard = await response.json();
    renderDashboard(dashboard);
    await maybeRecoverDashboardStream(dashboard);
  } catch (error) {
    if (await recoverStaleInstance(error)) return;
    els.topVolumeUpdated.textContent = error.message;
  }
}

function renderDashboard(dashboard) {
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

async function maybeRecoverDashboardStream(dashboard) {
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
    const recovered = await postJson("/api/dashboard/reconnect-stream", { account_id: selectedAccountId || null });
    renderDashboard(recovered);
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
    const dashboard = await postJson("/api/dashboard/reconnect-stream", { account_id: selectedAccountId || null, force: true });
    renderDashboard(dashboard);
    await loadState();
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

function renderState(state) {
  if (isDraftAccount) {
    selectedConnected = false;
    selectedTradingEnabled = false;
    renderAccountCards(state.accounts || []);
    renderMarketClock(null);
    renderMarketStream(state.market_stream || {});
    renderReplay(state.replay || {});
    renderParameterStatus(null);
    els.statusText.textContent = "New account draft";
    renderTradingToggle();
    els.cancelOrdersButton.disabled = true;
    els.purgeAccountButton.disabled = true;
    return;
  }

  selectedAccountId = state.selected_account_id || state.selected?.account_id || selectedAccountId;
  renderAccountCards(state.accounts || []);
  fields.accountSelect.value = selectedAccountId;

  const selected = state.selected || {};
  const config = selected.config || {};
  selectedConnected = Boolean(selected.connected);
  selectedTradingEnabled = Boolean(selected.trading_enabled);
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
  renderTradingToggle();
  els.cancelOrdersButton.disabled = !selected.connected;
  els.purgeAccountButton.disabled = !selected.connected;

  const account = selected.account || {};
  currentSelectedAccount = account;
  els.equity.textContent = account.equity_display || "$0.00";
  els.dailyPl.textContent = account.daily_pl_display || "$0.00";
  els.dailyPl.className = Number(account.daily_pl || 0) >= 0 ? "positive" : "negative";
  renderRealizedPlMetric(account);
  els.buyingPower.textContent = account.buying_power_display || "$0.00";
  els.cash.textContent = account.cash_display || "$0.00";
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

  currentPositionRows = selected.positions || [];
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
}

function renderTradingToggle() {
  if (!els.tradingToggleButton) return;
  els.tradingToggleButton.disabled = !selectedConnected;
  els.tradingToggleButton.classList.toggle("danger", selectedTradingEnabled);
  els.tradingToggleButton.textContent = selectedTradingEnabled ? "Stop Trading" : "Start Trading";
}

function renderRealizedPlMetric(account = currentSelectedAccount) {
  const rawValue = Number(account.realized_pl || 0);
  const display = showRealizedPlPercent
    ? account.realized_pl_pct_display || "0.00%"
    : account.realized_pl_display || "$0.00";
  els.realizedPl.textContent = display;
  els.realizedPl.className = rawValue >= 0 ? "positive" : "negative";
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
    card.innerHTML = `
      <span>${escapeHtml(account.name || "Paper Account")}</span>
      <strong>${escapeHtml(strategyLabel)}</strong>
      <small>${escapeHtml(account.status || "Not connected")}</small>
      <em class="${Number(account.daily_pl_raw || 0) >= 0 ? "positive" : "negative"}">${escapeHtml(account.daily_pl || "$0.00")}</em>
    `;
    card.addEventListener("click", async () => {
      if (selectedAccountId || isDraftAccount) {
        await saveCurrentAccountDraft(false);
      }
      selectedAccountId = account.account_id;
      isDraftAccount = false;
      const saved = findSavedAccount(selectedAccountId);
      if (saved) applyAccount(saved);
      fields.accountSelect.value = selectedAccountId;
      await postJson("/api/select-account", { account_id: selectedAccountId });
      await loadState();
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

checkRuntimeHealth().then(() => loadSettings()).then(async () => {
  updateAllTableSortButtons();
  await loadState();
  await loadDashboard();
}).catch(async (error) => {
  if (await recoverStaleInstance(error)) return;
  els.statusText.textContent = error.message;
  els.topVolumeUpdated.textContent = "This app instance is not responding.";
});
setInterval(loadState, 2000);
setInterval(loadDashboard, 5000);
