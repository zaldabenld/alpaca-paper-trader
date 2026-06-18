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
    h1 { font-size: 20px; margin: 0; }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 430px) minmax(0, 1fr);
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
    <button class="secondary" onclick="refresh()">Refresh</button>
  </header>
  <main>
    <aside>
      <form id="runForm">
        <label>Config
          <select id="config"></select>
        </label>
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
        <label>Candidate contains
          <input id="candidateContains" placeholder="h2-relative-strength-vwap" />
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
      const config = document.querySelector("#config");
      config.innerHTML = "";
      for (const item of state.configs) {
        const opt = document.createElement("option");
        opt.value = item.path;
        opt.textContent = item.name;
        if (item.name === "researched-weighted-strategies.json") opt.selected = true;
        config.appendChild(opt);
      }
      renderJobs();
      renderReports();
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
        collect_trades: document.querySelector("#collectTrades").checked
      };
    }
    function presetScreen() {
      document.querySelector("#priceSource").value = "bars";
      document.querySelector("#slippage").value = "10";
      document.querySelector("#candidateContains").value = "";
      document.querySelector("#collectTrades").checked = false;
      document.querySelector("#runName").value = "dashboard-bars-screen";
    }
    function presetValidate() {
      document.querySelector("#priceSource").value = "trades";
      document.querySelector("#slippage").value = "5,10,15";
      document.querySelector("#candidateContains").value = "h2-relative-strength-vwap";
      document.querySelector("#collectTrades").checked = false;
      document.querySelector("#runName").value = "dashboard-trade-validate";
    }
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


def list_configs() -> list[dict[str, Any]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        [file_item(path) for path in REPORT_DIR.glob("*.json") if "T" not in path.stem],
        key=lambda item: item["name"].lower(),
    )


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


def build_command(payload: dict[str, Any]) -> list[str]:
    config = safe_child_path(REPORT_DIR, str(payload.get("config") or "reports/manual/researched-weighted-strategies.json"))
    argv = [str(python_executable()), str(HUB_SCRIPT), "--config", str(config)]
    add_optional(argv, "--run-name", payload.get("run_name"))
    add_optional(argv, "--days", int(payload.get("days") or 3))
    add_optional(argv, "--end-date", payload.get("end_date"))
    add_optional(argv, "--price-source", payload.get("price_source") or "bars")
    add_optional(argv, "--slippage-bps-list", payload.get("slippage_bps_list") or "10")
    add_optional(argv, "--bucket-contains", payload.get("bucket_contains"))
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
            self.send_json({"configs": list_configs(), "reports": list_reports(), "jobs": list_jobs()})
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
            argv = build_command(payload)
            job_id = uuid.uuid4().hex[:12]
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
