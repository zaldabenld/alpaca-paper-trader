from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "manual"
JOB_DIR = REPORT_DIR / "dashboard-jobs"
HUB_SCRIPT = ROOT / "scripts" / "strategy_simulation_hub.py"
DASHBOARD_VERSION = "2026.06.18-controls-v2"


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Strategy Simulation Hub</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fb;
      --panel: #ffffff;
      --text: #1b2430;
      --muted: #5d6978;
      --line: #d9e0ea;
      --accent: #0f766e;
      --accent-dark: #0b5f59;
      --danger: #b42318;
      --ok: #067647;
      --warn: #9a6700;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Segoe UI, system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
    }
    header {
      background: #ffffff;
      border-bottom: 1px solid var(--line);
      padding: 16px 22px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    h1 { font-size: 20px; margin: 0; }
    main {
      display: grid;
      grid-template-columns: minmax(420px, 560px) minmax(0, 1fr);
      min-height: calc(100vh - 66px);
    }
    aside {
      background: var(--panel);
      border-right: 1px solid var(--line);
      padding: 18px;
      overflow: auto;
    }
    section {
      padding: 18px;
      overflow: auto;
    }
    label {
      display: block;
      margin: 0 0 12px;
      color: var(--muted);
      font-weight: 600;
    }
    input, select, textarea {
      width: 100%;
      margin-top: 5px;
      border: 1px solid #c5cfdc;
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      background: #fff;
      color: var(--text);
    }
    textarea { min-height: 64px; resize: vertical; }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .checks {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px 12px;
      margin: 8px 0 14px;
    }
    .checks label {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0;
      font-weight: 500;
    }
    .checks input { width: auto; margin: 0; }
    button {
      border: 0;
      border-radius: 6px;
      padding: 10px 13px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }
    button:hover { background: var(--accent-dark); }
    button.secondary {
      background: #eef2f6;
      color: var(--text);
      border: 1px solid var(--line);
    }
    button.secondary:hover { background: #e2e8f0; }
    .toolbar {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 8px 0 16px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 16px;
      overflow: hidden;
    }
    .panel h2 {
      margin: 0;
      padding: 12px 14px;
      font-size: 16px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    th {
      font-size: 12px;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: .02em;
      background: #fbfcfe;
    }
    tr:hover td { background: #f8fafc; }
    .pill {
      display: inline-block;
      padding: 2px 7px;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-size: 12px;
      color: var(--muted);
      background: #fff;
    }
    .running { color: var(--warn); font-weight: 700; }
    .done { color: var(--ok); font-weight: 700; }
    .failed { color: var(--danger); font-weight: 700; }
    pre {
      margin: 0;
      padding: 14px;
      background: #101828;
      color: #e6edf3;
      overflow: auto;
      max-height: 48vh;
      white-space: pre-wrap;
    }
    .muted { color: var(--muted); }
    .summary {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      margin: -2px 0 12px;
      background: #fbfcfe;
      color: var(--muted);
      line-height: 1.4;
    }
    .summary strong { color: var(--text); }
    .inline-check {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0;
      color: var(--text);
      font-weight: 700;
    }
    .inline-check input { width: auto; margin: 0; }
    .editor {
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 0 0 14px;
      background: #fff;
      overflow: hidden;
    }
    .editor-head {
      padding: 10px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      background: #fbfcfe;
      border-bottom: 1px solid var(--line);
    }
    .editor-body { padding: 10px 12px 12px; }
    details.editor-group {
      border-top: 1px solid var(--line);
      padding: 10px 0 0;
      margin-top: 10px;
    }
    details.editor-group:first-child {
      border-top: 0;
      margin-top: 0;
      padding-top: 0;
    }
    details.editor-group summary {
      cursor: pointer;
      font-weight: 800;
      color: var(--text);
      margin-bottom: 10px;
    }
    .control-row {
      display: grid;
      grid-template-columns: 22px minmax(110px, 1fr) minmax(88px, 110px);
      gap: 8px;
      align-items: center;
      margin-bottom: 8px;
    }
    .weight-row {
      grid-template-columns: 22px minmax(110px, 1fr) minmax(80px, 95px) minmax(110px, 1fr);
    }
    .control-row input[type="checkbox"] { width: auto; margin: 0; }
    .control-row input[type="number"],
    .control-row select {
      margin: 0;
      padding: 6px 8px;
      min-height: 34px;
    }
    .control-row input[type="range"] {
      margin: 0;
      padding: 0;
      width: 100%;
    }
    .control-label {
      color: var(--text);
      font-weight: 650;
      line-height: 1.2;
    }
    .control-help {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 500;
      margin-top: 2px;
    }
    .empty-editor {
      color: var(--muted);
      padding: 12px;
      border: 1px dashed var(--line);
      border-radius: 6px;
      background: #fbfcfe;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Strategy Simulation Hub</h1>
      <div class="muted">Replay only. Fixed 20-position assumptions by default. No live account changes.</div>
    </div>
    <div class="header-actions">
      <span id="refreshStatus" class="muted"></span>
      <button class="secondary" onclick="refresh()">Refresh</button>
    </div>
  </header>
  <main>
    <aside>
      <form id="runForm">
        <label>Config
          <select id="config"></select>
        </label>
        <div class="grid">
          <label>Strategy
            <select id="strategySelect"></select>
          </label>
          <label>Exit
            <select id="exitSelect"></select>
          </label>
        </div>
        <div id="strategySummary" class="summary">No strategy config loaded.</div>
        <div class="editor">
          <div class="editor-head">
            <label class="inline-check"><input id="useEditedStrategy" type="checkbox" checked /> Use edited controls</label>
            <button class="secondary" type="button" onclick="resetEditor()">Reset</button>
          </div>
          <div class="editor-body">
            <div id="editorEmpty" class="empty-editor">Choose one strategy to edit thresholds, weights, and exits.</div>
            <div id="editorControls" hidden>
              <details class="editor-group" open>
                <summary>Entry Thresholds</summary>
                <div id="entryFields"></div>
              </details>
              <details class="editor-group" open>
                <summary>Selection Weights</summary>
                <div id="weightFields"></div>
              </details>
              <details class="editor-group" open>
                <summary>Exit Settings</summary>
                <div id="exitFields"></div>
              </details>
            </div>
          </div>
        </div>
        <label>Run name
          <input id="runName" value="manual-dashboard-run" />
        </label>
        <div class="grid">
          <label>Days
            <input id="days" type="number" min="1" step="1" value="3" />
          </label>
          <label>End date
            <input id="endDate" placeholder="YYYYMMDD" />
          </label>
        </div>
        <div class="grid">
          <label>Price source
            <select id="priceSource">
              <option value="bars">bars</option>
              <option value="trades">trades</option>
            </select>
          </label>
          <label>Slippage bps
            <input id="slippage" value="10" />
          </label>
        </div>
        <label>Bucket contains
          <input id="bucketContains" placeholder="profile=aggressive, max_trade=50" />
        </label>
        <label>Candidate filter
          <input id="candidateContains" placeholder="h2-relative-strength-vwap|fixed_2.5_1.25" />
        </label>
        <div class="grid">
          <label>Top rows
            <input id="top" type="number" min="1" step="1" value="8" />
          </label>
          <label>Scan interval sec
            <input id="scanInterval" type="number" min="0" step="1" value="15" />
          </label>
        </div>
        <div class="checks">
          <label><input id="allowPartial" type="checkbox" /> Partial tape</label>
          <label><input id="collectTrades" type="checkbox" /> Trade ledger</label>
        </div>
        <div class="toolbar">
          <button type="submit">Run Simulation</button>
          <button class="secondary" type="button" onclick="presetScreen()">Bar Screen</button>
          <button class="secondary" type="button" onclick="presetValidate()">Trade Validate</button>
        </div>
      </form>
      <div class="muted">
        Heavy trade-price runs can take several minutes. Use bar screens to shortlist, then trade validate survivors.
      </div>
    </aside>
    <section>
      <div class="panel">
        <h2>Jobs</h2>
        <table>
          <thead><tr><th style="width: 18%">Status</th><th>Run</th><th style="width: 20%">Started</th><th style="width: 12%">Log</th></tr></thead>
          <tbody id="jobs"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>Reports</h2>
        <table>
          <thead><tr><th>Name</th><th style="width: 16%">Size</th><th style="width: 22%">Modified</th></tr></thead>
          <tbody id="reports"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2 id="logTitle">Log</h2>
        <pre id="log">No job selected.</pre>
      </div>
    </section>
  </main>
  <script>
    let state = {};
    const ENTRY_FIELDS = [
      {key: "min_entry_score", label: "Min score", help: "Higher is stricter", min: 0, max: 100, step: 1, off: 0},
      {key: "rsi_min", label: "RSI min", help: "Lower bull-range bound", min: 0, max: 100, step: 1, off: 0},
      {key: "rsi_max", label: "RSI max", help: "Upper bull-range bound", min: 0, max: 100, step: 1, off: 100},
      {key: "min_momentum", label: "Min momentum", help: "Short momentum %", min: -2, max: 3, step: 0.01, off: 0},
      {key: "min_recent_momentum", label: "Recent momentum", help: "Fresh move %", min: -2, max: 3, step: 0.01, off: 0},
      {key: "min_long_momentum", label: "Long momentum", help: "Longer trend %", min: -2, max: 5, step: 0.01, off: 0},
      {key: "min_session_change", label: "Session change", help: "Same-day direction %", min: -5, max: 8, step: 0.01, off: 0},
      {key: "min_vwap_distance", label: "VWAP min", help: "Avoid below-VWAP buys", min: -5, max: 5, step: 0.01, off: 0},
      {key: "max_vwap_distance", label: "VWAP max", help: "Avoid overextension", min: 0, max: 20, step: 0.05, off: 99},
      {key: "max_session_pullback", label: "Session pullback max", help: "Reject fading symbols", min: 0, max: 10, step: 0.05, off: 99},
      {key: "max_recent_pullback", label: "Recent pullback max", help: "Reject short-term fade", min: 0, max: 10, step: 0.05, off: 99},
      {key: "min_smi", label: "SMI min", help: "Momentum oscillator gate", min: -100, max: 100, step: 1, off: -100},
      {key: "min_relative_volume", label: "Relative volume min", help: "Activity confirmation", min: 0, max: 10, step: 0.05, off: 0},
      {key: "min_price", label: "Min price", help: "Avoid tiny stocks", min: 0, max: 50, step: 0.25, off: 0},
      {key: "max_price", label: "Max price", help: "0 disables cap", min: 0, max: 500, step: 1, off: 0},
      {key: "max_relative_volume", label: "Relative volume cap", help: "0 disables cap", min: 0, max: 25, step: 0.1, off: 0},
      {key: "max_atr_percent", label: "ATR cap", help: "0 disables cap", min: 0, max: 10, step: 0.05, off: 0},
      {key: "max_volatility_percent", label: "Volatility cap", help: "0 disables cap", min: 0, max: 10, step: 0.05, off: 0}
    ];
    const WEIGHT_FIELDS = [
      {key: "momentum", label: "Momentum", help: "Short move rank", min: -20, max: 30, step: 1},
      {key: "recent_momentum", label: "Recent momentum", help: "Freshness rank", min: -20, max: 30, step: 1},
      {key: "long_momentum", label: "Long momentum", help: "Trend persistence", min: -20, max: 30, step: 1},
      {key: "session_change", label: "Session direction", help: "Intraday trend", min: -20, max: 30, step: 1},
      {key: "relative_volume", label: "Relative volume", help: "Participation rank", min: -20, max: 30, step: 1},
      {key: "vwap_distance", label: "VWAP distance", help: "Above-VWAP strength", min: -20, max: 30, step: 1},
      {key: "smi", label: "SMI", help: "Oscillator rank", min: -20, max: 30, step: 1},
      {key: "rsi_fit", label: "RSI fit", help: "Bull-range fit", min: -20, max: 30, step: 1},
      {key: "buy_flow", label: "Buy flow", help: "Classified trade pressure", min: -20, max: 30, step: 1},
      {key: "volatility", label: "Volatility bonus", help: "Reward movement", min: -20, max: 30, step: 1},
      {key: "volatility_penalty", label: "Volatility penalty", help: "Punish chop", min: 0, max: 30, step: 1},
      {key: "session_pullback_penalty", label: "Session pullback penalty", help: "Punish fade", min: 0, max: 30, step: 1},
      {key: "recent_pullback_penalty", label: "Recent pullback penalty", help: "Punish short fade", min: 0, max: 30, step: 1},
      {key: "vwap_extension_penalty", label: "VWAP extension penalty", help: "Punish chasing", min: 0, max: 30, step: 1},
      {key: "session_extension_penalty", label: "Session extension penalty", help: "Punish overextension", min: 0, max: 30, step: 1},
      {key: "smi_overheat_penalty", label: "SMI overheat penalty", help: "Punish stretched SMI", min: 0, max: 30, step: 1}
    ];
    const EXIT_FIELDS = [
      {key: "take_profit_percent", label: "Take profit %", help: "Fixed target", min: 0, max: 10, step: 0.05},
      {key: "stop_loss_percent", label: "Stop loss %", help: "Protective stop", min: 0, max: 10, step: 0.05},
      {key: "reentry_score_boost", label: "Re-entry boost", help: "Higher score needed after exit", min: 0, max: 40, step: 1},
      {key: "trail_activation_percent", label: "Trail activation %", help: "For trail/lock exits", min: 0, max: 10, step: 0.05},
      {key: "trail_distance_percent", label: "Trail distance %", help: "For trailing exit", min: 0, max: 10, step: 0.05},
      {key: "profit_lock_percent", label: "Profit lock %", help: "For lock exit", min: 0, max: 10, step: 0.05}
    ];
    function fmtTime(value) {
      if (!value) return "";
      const d = new Date(value * 1000);
      return d.toLocaleString();
    }
    async function api(path, options) {
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }
    async function refresh() {
      state = await api("/api/state");
      populateConfigs();
      populateStrategyControls({preserve: true});
      renderJobs();
      renderReports();
      document.querySelector("#refreshStatus").textContent = `Updated ${new Date().toLocaleTimeString()}`;
    }
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[ch]));
    }
    function selectedConfigItem() {
      const config = document.querySelector("#config");
      return (state.configs || []).find(item => item.path === config.value) || null;
    }
    function selectedStrategyItem() {
      const item = selectedConfigItem();
      const selected = document.querySelector("#strategySelect").value;
      if (!item || !selected) return null;
      return (item.strategies || []).find(strategy => strategy.name === selected) || null;
    }
    function selectedExitItem() {
      const strategy = selectedStrategyItem();
      const selected = document.querySelector("#exitSelect").value;
      if (!strategy || !selected) return null;
      return (strategy.exits || []).find(exit => exit.name === selected) || null;
    }
    function numericValue(value, fallback = 0) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }
    function controlId(section, key, suffix = "value") {
      return `${section}_${key}_${suffix}`.replace(/[^a-zA-Z0-9_]/g, "_");
    }
    function fieldSourceValue(source, field) {
      if (source && Object.prototype.hasOwnProperty.call(source, field.key)) {
        return numericValue(source[field.key], field.off ?? 0);
      }
      return numericValue(field.off ?? 0);
    }
    function makeLabel(field) {
      return `<span class="control-label">${escapeHtml(field.label)}<span class="control-help">${escapeHtml(field.help || field.key)}</span></span>`;
    }
    function renderNumericControls(container, fields, values, section, withToggle) {
      container.innerHTML = "";
      for (const field of fields) {
        const value = fieldSourceValue(values, field);
        const checked = !withToggle || value !== numericValue(field.off ?? 0);
        const row = document.createElement("div");
        row.className = "control-row";
        const checkId = controlId(section, field.key, "enabled");
        const valueId = controlId(section, field.key, "value");
        row.innerHTML = `
          <input id="${checkId}" type="checkbox" ${checked ? "checked" : ""} ${withToggle ? "" : "hidden"}>
          ${makeLabel(field)}
          <input id="${valueId}" type="number" min="${field.min}" max="${field.max}" step="${field.step}" value="${value}">
        `;
        const checkbox = row.querySelector(`#${checkId}`);
        const input = row.querySelector(`#${valueId}`);
        if (withToggle) {
          checkbox.addEventListener("change", () => {
            input.disabled = !checkbox.checked;
            if (!checkbox.checked) input.value = field.off ?? 0;
          });
          input.disabled = !checkbox.checked;
        }
        container.appendChild(row);
      }
    }
    function renderWeightControls(container, values) {
      container.innerHTML = "";
      for (const field of WEIGHT_FIELDS) {
        const value = fieldSourceValue(values, {...field, off: 0});
        const checked = value !== 0;
        const row = document.createElement("div");
        row.className = "control-row weight-row";
        const checkId = controlId("weight", field.key, "enabled");
        const valueId = controlId("weight", field.key, "value");
        const sliderId = controlId("weight", field.key, "slider");
        row.innerHTML = `
          <input id="${checkId}" type="checkbox" ${checked ? "checked" : ""}>
          ${makeLabel(field)}
          <input id="${valueId}" type="number" min="${field.min}" max="${field.max}" step="${field.step}" value="${value}">
          <input id="${sliderId}" type="range" min="${field.min}" max="${field.max}" step="${field.step}" value="${value}">
        `;
        const checkbox = row.querySelector(`#${checkId}`);
        const input = row.querySelector(`#${valueId}`);
        const slider = row.querySelector(`#${sliderId}`);
        function syncDisabled() {
          input.disabled = !checkbox.checked;
          slider.disabled = !checkbox.checked;
          if (!checkbox.checked) {
            input.value = "0";
            slider.value = "0";
          }
        }
        checkbox.addEventListener("change", syncDisabled);
        input.addEventListener("input", () => {
          slider.value = input.value || "0";
        });
        slider.addEventListener("input", () => {
          input.value = slider.value;
        });
        syncDisabled();
        container.appendChild(row);
      }
    }
    function renderExitControls(container, exit) {
      container.innerHTML = "";
      if (!exit) {
        container.innerHTML = `<div class="empty-editor">Select one exit to edit exit settings, or leave All exits to compare the selected strategy across its saved exits.</div>`;
        return;
      }
      const styleRow = document.createElement("div");
      styleRow.className = "control-row";
      styleRow.innerHTML = `
        <span></span>
        <span class="control-label">Exit style<span class="control-help">fixed, trail, or lock</span></span>
        <select id="exit_exit_style_value">
          <option value="fixed">fixed</option>
          <option value="trail">trail</option>
          <option value="lock">lock</option>
        </select>
      `;
      container.appendChild(styleRow);
      styleRow.querySelector("select").value = exit.exit_style || "fixed";
      renderNumericControls(container, EXIT_FIELDS, exit, "exit", false);
      container.insertBefore(styleRow, container.firstChild);
    }
    function resetEditor() {
      renderEditor();
    }
    function renderEditor() {
      const strategy = selectedStrategyItem();
      const empty = document.querySelector("#editorEmpty");
      const controls = document.querySelector("#editorControls");
      if (!strategy) {
        empty.hidden = false;
        controls.hidden = true;
        return;
      }
      empty.hidden = true;
      controls.hidden = false;
      renderNumericControls(document.querySelector("#entryFields"), ENTRY_FIELDS, strategy.entry || {}, "entry", true);
      renderWeightControls(document.querySelector("#weightFields"), strategy.score_weights || {});
      renderExitControls(document.querySelector("#exitFields"), selectedExitItem());
    }
    function collectNumericFields(fields, section, fallback, withToggle) {
      const result = {};
      for (const field of fields) {
        const valueId = controlId(section, field.key, "value");
        const checkId = controlId(section, field.key, "enabled");
        const valueInput = document.querySelector(`#${valueId}`);
        if (!valueInput) continue;
        let value = numericValue(valueInput.value, fieldSourceValue(fallback, field));
        if (withToggle) {
          const checkbox = document.querySelector(`#${checkId}`);
          if (checkbox && !checkbox.checked) value = numericValue(field.off ?? 0);
        }
        result[field.key] = value;
      }
      return result;
    }
    function collectWeightFields(fallback) {
      const result = {};
      for (const field of WEIGHT_FIELDS) {
        const valueInput = document.querySelector(`#${controlId("weight", field.key, "value")}`);
        const checkbox = document.querySelector(`#${controlId("weight", field.key, "enabled")}`);
        if (!valueInput) continue;
        result[field.key] = checkbox && !checkbox.checked ? 0 : numericValue(valueInput.value, fieldSourceValue(fallback, {...field, off: 0}));
      }
      return result;
    }
    function collectExitFields(exit) {
      const result = {...(exit || {})};
      const style = document.querySelector("#exit_exit_style_value");
      result.exit_style = style ? style.value : (exit ? exit.exit_style : "fixed");
      Object.assign(result, collectNumericFields(EXIT_FIELDS, "exit", exit || {}, false));
      result.name = exit && exit.name ? exit.name : `${result.exit_style || "fixed"}_custom`;
      return result;
    }
    function editedStrategyPayload() {
      const strategy = selectedStrategyItem();
      if (!strategy || !document.querySelector("#useEditedStrategy").checked) return null;
      const selectedExit = selectedExitItem();
      return {
        source_name: strategy.name,
        name: strategy.name,
        entry: collectNumericFields(ENTRY_FIELDS, "entry", strategy.entry || {}, true),
        score_weights: collectWeightFields(strategy.score_weights || {}),
        exits: selectedExit ? [collectExitFields(selectedExit)] : (strategy.exits || []).map(exit => ({...exit}))
      };
    }
    function populateConfigs() {
      const config = document.querySelector("#config");
      const previous = config.value;
      config.innerHTML = "";
      const configs = state.configs || [];
      const fallback = configs.find(item => item.name === "researched-weighted-strategies.json") || configs[0];
      let selected = previous && configs.some(item => item.path === previous) ? previous : (fallback ? fallback.path : "");
      for (const item of configs) {
        const opt = document.createElement("option");
        opt.value = item.path;
        opt.textContent = `${item.name} (${item.candidate_count || 0})`;
        if (item.path === selected) opt.selected = true;
        config.appendChild(opt);
      }
    }
    function populateStrategyControls(options = {}) {
      const preserve = options.preserve !== false;
      const strategySelect = document.querySelector("#strategySelect");
      const previous = preserve ? strategySelect.value : "";
      const item = selectedConfigItem();
      strategySelect.innerHTML = "";
      const all = document.createElement("option");
      all.value = "";
      all.textContent = item ? `All strategies (${item.strategy_count || 0})` : "All strategies";
      strategySelect.appendChild(all);
      for (const strategy of (item ? item.strategies || [] : [])) {
        const opt = document.createElement("option");
        opt.value = strategy.name;
        opt.textContent = `${strategy.name} (${(strategy.exits || strategy.exit_names || []).length} exits)`;
        strategySelect.appendChild(opt);
      }
      if (previous && Array.from(strategySelect.options).some(opt => opt.value === previous)) {
        strategySelect.value = previous;
      }
      populateExitControls(preserve ? document.querySelector("#exitSelect").value : "");
      renderStrategySummary();
      renderEditor();
    }
    function populateExitControls(preferred = "") {
      const exitSelect = document.querySelector("#exitSelect");
      const item = selectedConfigItem();
      const strategy = selectedStrategyItem();
      const exitNames = new Set();
      if (strategy) {
        for (const exit of strategy.exits || []) exitNames.add(exit.name);
        for (const name of strategy.exit_names || []) exitNames.add(name);
      } else if (item) {
        for (const rawStrategy of item.strategies || []) {
          for (const exit of rawStrategy.exits || []) exitNames.add(exit.name);
          for (const name of rawStrategy.exit_names || []) exitNames.add(name);
        }
      }
      exitSelect.innerHTML = "";
      const all = document.createElement("option");
      all.value = "";
      all.textContent = `All exits (${exitNames.size})`;
      exitSelect.appendChild(all);
      for (const name of Array.from(exitNames).sort()) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        exitSelect.appendChild(opt);
      }
      if (preferred && Array.from(exitSelect.options).some(opt => opt.value === preferred)) {
        exitSelect.value = preferred;
      }
    }
    function candidateFromMenus() {
      const strategy = document.querySelector("#strategySelect").value;
      const exit = document.querySelector("#exitSelect").value;
      if (strategy && exit) return `${strategy}|${exit}`;
      if (strategy) return strategy;
      if (exit) return `|${exit}`;
      return "";
    }
    function syncCandidateFromMenus() {
      document.querySelector("#candidateContains").value = candidateFromMenus();
    }
    function renderStrategySummary() {
      const el = document.querySelector("#strategySummary");
      const item = selectedConfigItem();
      const strategy = selectedStrategyItem();
      if (!item) {
        el.textContent = "No strategy config loaded.";
        return;
      }
      if (!strategy) {
        el.innerHTML = `<strong>${escapeHtml(item.name)}</strong><br>${item.strategy_count || 0} strategies, ${item.candidate_count || 0} candidate/exit combinations.`;
        return;
      }
      const entry = strategy.entry || {};
      const weights = Object.entries(strategy.score_weights || {})
        .sort((a, b) => Math.abs(Number(b[1] || 0)) - Math.abs(Number(a[1] || 0)))
        .slice(0, 5)
        .map(([key, value]) => `${key} ${value}`)
        .join(", ");
      const parts = [
        `score ${entry.min_entry_score ?? ""}`,
        `RSI ${entry.rsi_min ?? ""}-${entry.rsi_max ?? ""}`,
        `mom ${entry.min_momentum ?? ""}`,
        `recent ${entry.min_recent_momentum ?? ""}`,
        `session ${entry.min_session_change ?? ""}`,
        `VWAP ${entry.min_vwap_distance ?? ""}-${entry.max_vwap_distance ?? ""}`,
        `SMI ${entry.min_smi ?? ""}`,
        `rel vol ${entry.min_relative_volume ?? ""}`
      ].filter(part => !part.endsWith(" "));
      el.innerHTML = `<strong>${escapeHtml(strategy.name)}</strong><br>${escapeHtml(parts.join(" | "))}<br>Top weights: ${escapeHtml(weights || "none")}`;
    }
    function statusClass(status) {
      if (status === "running") return "running";
      if (status === "done") return "done";
      return "failed";
    }
    function renderJobs() {
      const body = document.querySelector("#jobs");
      body.innerHTML = "";
      for (const job of state.jobs) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td><span class="${statusClass(job.status)}">${job.status}</span></td>
          <td>${job.run_name || job.id}<br><span class="muted">${job.id}</span></td>
          <td>${fmtTime(job.started_at)}</td>
          <td><button class="secondary" type="button">View</button></td>`;
        tr.querySelector("button").onclick = () => viewLog(job.id);
        body.appendChild(tr);
      }
      if (!state.jobs.length) body.innerHTML = `<tr><td colspan="4" class="muted">No dashboard jobs yet.</td></tr>`;
    }
    function renderReports() {
      const body = document.querySelector("#reports");
      body.innerHTML = "";
      for (const report of state.reports) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${report.name}<br><span class="muted">${report.path}</span></td>
          <td>${report.size_kb} KB</td><td>${fmtTime(report.modified_at)}</td>`;
        body.appendChild(tr);
      }
      if (!state.reports.length) body.innerHTML = `<tr><td colspan="3" class="muted">No reports yet.</td></tr>`;
    }
    async function viewLog(id) {
      const data = await api(`/api/jobs/${id}/log`);
      document.querySelector("#logTitle").textContent = `Log: ${id}`;
      document.querySelector("#log").textContent = data.log || "(empty)";
    }
    function payload() {
      return {
        config: document.querySelector("#config").value,
        run_name: document.querySelector("#runName").value,
        days: Number(document.querySelector("#days").value || 3),
        end_date: document.querySelector("#endDate").value,
        price_source: document.querySelector("#priceSource").value,
        slippage_bps_list: document.querySelector("#slippage").value,
        bucket_contains: document.querySelector("#bucketContains").value,
        candidate_contains: document.querySelector("#candidateContains").value,
        top: Number(document.querySelector("#top").value || 8),
        scan_interval_seconds: Number(document.querySelector("#scanInterval").value || 15),
        allow_partial: document.querySelector("#allowPartial").checked,
        collect_trades: document.querySelector("#collectTrades").checked,
        custom_strategy: editedStrategyPayload()
      };
    }
    function presetScreen() {
      document.querySelector("#priceSource").value = "bars";
      document.querySelector("#slippage").value = "10";
      document.querySelector("#strategySelect").value = "";
      populateExitControls("");
      document.querySelector("#exitSelect").value = "";
      document.querySelector("#candidateContains").value = "";
      document.querySelector("#collectTrades").checked = false;
      document.querySelector("#runName").value = "dashboard-bars-screen";
      renderStrategySummary();
      renderEditor();
    }
    function presetValidate() {
      document.querySelector("#priceSource").value = "trades";
      document.querySelector("#slippage").value = "5,10,15";
      const strategySelect = document.querySelector("#strategySelect");
      if (Array.from(strategySelect.options).some(opt => opt.value === "h2-relative-strength-vwap")) {
        strategySelect.value = "h2-relative-strength-vwap";
        populateExitControls("");
        document.querySelector("#exitSelect").value = "";
        syncCandidateFromMenus();
      } else {
        document.querySelector("#candidateContains").value = "h2-relative-strength-vwap";
      }
      document.querySelector("#collectTrades").checked = false;
      document.querySelector("#runName").value = "dashboard-trade-validate";
      renderStrategySummary();
      renderEditor();
    }
    document.querySelector("#config").addEventListener("change", () => {
      populateStrategyControls({preserve: false});
      syncCandidateFromMenus();
      renderEditor();
    });
    document.querySelector("#strategySelect").addEventListener("change", () => {
      populateExitControls("");
      syncCandidateFromMenus();
      renderStrategySummary();
      renderEditor();
    });
    document.querySelector("#exitSelect").addEventListener("change", () => {
      syncCandidateFromMenus();
      renderStrategySummary();
      renderEditor();
    });
    document.querySelector("#runForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const job = await api("/api/run", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload())
      });
      await refresh();
      await viewLog(job.id);
    });
    setInterval(refresh, 10000);
    refresh().catch(err => {
      document.querySelector("#log").textContent = err.stack || String(err);
    });
  </script>
</body>
</html>
"""


def now_ts() -> float:
    return time.time()


def python_executable() -> Path:
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return candidate
    return Path(sys.executable)


def safe_child_path(base: Path, value: str) -> Path:
    raw = Path(str(value or ""))
    path = raw if raw.is_absolute() else ROOT / raw
    path = path.resolve()
    base = base.resolve()
    if path != base and base not in path.parents:
        raise ValueError(f"path is outside {base}: {path}")
    return path


def file_item(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path.relative_to(ROOT)),
        "size_kb": round(stat.st_size / 1024, 1),
        "modified_at": stat.st_mtime,
    }


def scalar_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, raw in value.items():
        if isinstance(raw, (str, int, float, bool)) or raw is None:
            result[str(key)] = raw
    return result


def config_strategy_items(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    strategies = payload.get("strategies")
    if not isinstance(strategies, list):
        return []
    items: list[dict[str, Any]] = []
    for raw_strategy in strategies:
        if not isinstance(raw_strategy, dict):
            continue
        entry = raw_strategy.get("entry") if isinstance(raw_strategy.get("entry"), dict) else {}
        name = str(raw_strategy.get("name") or entry.get("name") or "manual")
        exits = raw_strategy.get("exits")
        exit_names: list[str] = []
        exit_items: list[dict[str, Any]] = []
        if isinstance(exits, list):
            for raw_exit in exits:
                if isinstance(raw_exit, dict):
                    exit_item = scalar_map(raw_exit)
                    exit_item["name"] = str(raw_exit.get("name") or "manual_exit")
                    exit_items.append(exit_item)
                    exit_names.append(str(exit_item["name"]))
        items.append(
            {
                "name": name,
                "entry": scalar_map(entry),
                "score_weights": scalar_map(raw_strategy.get("score_weights")),
                "exit_names": exit_names or ["manual_exit"],
                "exits": exit_items or [{"name": "manual_exit", "exit_style": "fixed"}],
            }
        )
    return items


def list_configs() -> list[dict[str, Any]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in REPORT_DIR.glob("*.json"):
        if "T" in path.stem:
            continue
        item = file_item(path)
        strategies = config_strategy_items(path)
        item["strategies"] = strategies
        item["strategy_count"] = len(strategies)
        item["candidate_count"] = sum(len(strategy["exit_names"]) for strategy in strategies)
        items.append(item)
    return sorted(items, key=lambda item: item["name"].lower())


def list_reports() -> list[dict[str, Any]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = [
        file_item(path)
        for path in REPORT_DIR.glob("*.json")
        if "T" in path.stem or path.name.startswith("20")
    ]
    reports.extend(file_item(path) for path in (ROOT / "reports").glob("*strategy-status*.md"))
    return sorted(reports, key=lambda item: item["modified_at"], reverse=True)[:60]


def job_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.json"


def job_log_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.log"


def read_job(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_job(job: dict[str, Any]) -> None:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    job_path(str(job["id"])).write_text(json.dumps(job, indent=2), encoding="utf-8")


def list_jobs() -> list[dict[str, Any]]:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [job for path in JOB_DIR.glob("*.json") if (job := read_job(path))]
    return sorted(jobs, key=lambda item: item.get("started_at", 0), reverse=True)[:40]


def add_optional(argv: list[str], flag: str, value: Any) -> None:
    if value in (None, ""):
        return
    argv.extend([flag, str(value)])


def clean_custom_strategy(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or value.get("source_name") or "dashboard-custom")
    exits: list[dict[str, Any]] = []
    raw_exits = value.get("exits")
    if isinstance(raw_exits, list):
        for raw_exit in raw_exits:
            if not isinstance(raw_exit, dict):
                continue
            exit_item = scalar_map(raw_exit)
            exit_item["name"] = str(raw_exit.get("name") or "dashboard_exit")
            exit_item["exit_style"] = str(raw_exit.get("exit_style") or exit_item.get("exit_style") or "fixed")
            exits.append(exit_item)
    if not exits:
        exits.append(
            {
                "name": "dashboard_fixed",
                "exit_style": "fixed",
                "take_profit_percent": 2.5,
                "stop_loss_percent": 1.25,
                "reentry_score_boost": 12,
            }
        )
    return {
        "name": name,
        "entry": scalar_map(value.get("entry")),
        "score_weights": scalar_map(value.get("score_weights")),
        "exits": exits,
    }


def write_dashboard_config(base_config: Path, payload: dict[str, Any], job_id: str) -> Path | None:
    strategy = clean_custom_strategy(payload.get("custom_strategy"))
    if not strategy:
        return None
    try:
        config = json.loads(base_config.read_text(encoding="utf-8"))
    except Exception:
        config = {}
    if not isinstance(config, dict):
        config = {}
    config["run_name"] = str(payload.get("run_name") or f"dashboard-custom-{job_id}")
    config["notes"] = "Dashboard-generated replay config. Source config is unchanged."
    config["strategies"] = [strategy]
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = JOB_DIR / f"{job_id}-config.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def build_command(payload: dict[str, Any], job_id: str) -> list[str]:
    config = safe_child_path(REPORT_DIR, str(payload.get("config") or "reports/manual/researched-weighted-strategies.json"))
    custom_config = write_dashboard_config(config, payload, job_id)
    if custom_config is not None:
        config = custom_config
    argv = [str(python_executable()), str(HUB_SCRIPT), "--config", str(config)]
    add_optional(argv, "--run-name", payload.get("run_name"))
    add_optional(argv, "--days", int(payload.get("days") or 3))
    add_optional(argv, "--end-date", payload.get("end_date"))
    add_optional(argv, "--price-source", payload.get("price_source") or "bars")
    add_optional(argv, "--slippage-bps-list", payload.get("slippage_bps_list") or "10")
    add_optional(argv, "--bucket-contains", payload.get("bucket_contains"))
    if custom_config is None:
        add_optional(argv, "--candidate-contains", payload.get("candidate_contains"))
    add_optional(argv, "--top", int(payload.get("top") or 8))
    add_optional(argv, "--scan-interval-seconds", int(payload.get("scan_interval_seconds") or 15))
    if payload.get("allow_partial"):
        argv.append("--allow-partial")
    if payload.get("collect_trades"):
        argv.append("--collect-trades")
    return argv


def run_job(job: dict[str, Any], argv: list[str]) -> None:
    log_path = job_log_path(str(job["id"]))
    job["status"] = "running"
    job["command"] = argv
    write_job(job)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"Started {datetime.now().isoformat(timespec='seconds')}\n")
            log.write("Command: " + " ".join(argv) + "\n\n")
            process = subprocess.Popen(
                argv,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            job["pid"] = process.pid
            write_job(job)
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                log.flush()
            return_code = process.wait()
        job["return_code"] = return_code
        job["status"] = "done" if return_code == 0 else "failed"
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\nDashboard job error: {exc}\n")
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = now_ts()
        write_job(job)


class Handler(BaseHTTPRequestHandler):
    server_version = "StrategySimulationDashboard/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_text(self, text: str, content_type: str = "text/html; charset=utf-8") -> None:
        raw = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_text(INDEX_HTML)
            return
        if parsed.path == "/api/state":
            self.send_json(
                {
                    "ui_version": DASHBOARD_VERSION,
                    "configs": list_configs(),
                    "reports": list_reports(),
                    "jobs": list_jobs(),
                }
            )
            return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/log"):
            job_id = parsed.path.split("/")[3]
            log_path = job_log_path(job_id)
            text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            self.send_json({"id": job_id, "log": text})
            return
        if parsed.path == "/api/report":
            params = parse_qs(parsed.query)
            try:
                path = safe_child_path(ROOT / "reports", params.get("path", [""])[0])
                self.send_json(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        self.send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path != "/api/run":
            self.send_json({"error": "not found"}, status=404)
            return
        try:
            payload = self.read_json()
            job_id = uuid.uuid4().hex[:12]
            argv = build_command(payload, job_id)
            job = {
                "id": job_id,
                "status": "queued",
                "run_name": str(payload.get("run_name") or "dashboard-run"),
                "started_at": now_ts(),
                "payload": payload,
            }
            write_job(job)
            thread = threading.Thread(target=run_job, args=(job, argv), daemon=True)
            thread.start()
            self.send_json(job)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local dashboard for manual strategy replay simulations.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser.")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Strategy Simulation Dashboard: {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
