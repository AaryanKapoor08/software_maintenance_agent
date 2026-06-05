from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from software_maintaince_agent.agent import SoftwareMaintainceAgent, load_task
from software_maintaince_agent.settings import Settings
from software_maintaince_agent.storage import TraceStore


def list_runs(runs_dir: Path) -> list[dict[str, str]]:
    runs: list[dict[str, str]] = []
    if not runs_dir.exists():
        return runs
    for trace_db in sorted(runs_dir.glob("*/trace.sqlite"), reverse=True):
        run_id = trace_db.parent.name
        store = TraceStore(trace_db)
        run = store.get_run(run_id)
        if run:
            runs.append(run)
    return runs


def load_run_bundle(runs_dir: Path, run_id: str) -> dict[str, object]:
    run_dir = safe_run_dir(runs_dir, run_id)
    trace_db = run_dir / "trace.sqlite"
    if not trace_db.exists():
        raise FileNotFoundError(run_id)
    store = TraceStore(trace_db)
    return {
        "run": store.get_run(run_id),
        "events": store.list_events(run_id),
        "report": read_optional(run_dir / "final_report.md"),
        "patch": read_optional(run_dir / "patch.diff"),
        "selected_files": read_json_optional(run_dir / "selected_files.json"),
        "attempts": read_json_optional(run_dir / "attempts.json"),
        "benchmark": read_optional(run_dir / "benchmark_report.md"),
    }


def safe_run_dir(runs_dir: Path, run_id: str) -> Path:
    if "/" in run_id or "\\" in run_id or run_id.startswith("."):
        raise ValueError("invalid run id")
    run_dir = (runs_dir / run_id).resolve()
    run_dir.relative_to(runs_dir.resolve())
    return run_dir


def read_optional(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_json_optional(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def render_dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>software_maintaince agent Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-muted: #f8fafc;
      --border: #d8dee7;
      --border-strong: #b8c2cf;
      --text: #151b23;
      --muted: #667085;
      --muted-strong: #475467;
      --accent: #22577a;
      --accent-strong: #16435f;
      --accent-soft: #e6f1f6;
      --danger: #b42318;
      --danger-soft: #fef3f2;
      --ok: #067647;
      --ok-soft: #ecfdf3;
      --warn: #b54708;
      --warn-soft: #fffaeb;
      --code-bg: #0f172a;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.06), 0 8px 24px rgba(16, 24, 40, 0.06);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.45;
    }
    header {
      min-height: 76px;
      padding: 16px 28px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.94);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 2;
      backdrop-filter: blur(10px);
    }
    h1 { margin: 0; font-size: 19px; line-height: 1.2; letter-spacing: 0; }
    h2 { margin: 0; font-size: 13px; line-height: 1.2; letter-spacing: 0; }
    p { margin: 0; }
    ul { margin: 8px 0 0; padding-left: 18px; }
    li + li { margin-top: 4px; }
    main {
      display: grid;
      grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
      min-height: calc(100vh - 76px);
    }
    aside {
      border-right: 1px solid var(--border);
      background: var(--surface-muted);
      padding: 20px;
      overflow: auto;
    }
    section {
      padding: 22px 26px 28px;
      overflow: auto;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      background: linear-gradient(135deg, #22577a, #38a3a5);
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.45);
      flex: 0 0 auto;
      position: relative;
    }
    .mark::after {
      content: "";
      width: 14px;
      height: 14px;
      border: 2px solid rgba(255, 255, 255, 0.94);
      border-left-color: transparent;
      border-radius: 50%;
      position: absolute;
      left: 12px;
      top: 12px;
    }
    .eyebrow {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
      margin-bottom: 16px;
    }
    .panel-header {
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
      margin-bottom: 12px;
    }
    .panel-kicker {
      color: var(--muted);
      font-size: 12px;
      margin-top: 3px;
    }
    label {
      display: block;
      font-size: 12px;
      color: var(--muted-strong);
      margin: 12px 0 6px;
      font-weight: 650;
    }
    input, select, button {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    input:focus, select:focus, button:focus-visible {
      outline: 3px solid rgba(34, 87, 122, 0.18);
      outline-offset: 1px;
      border-color: var(--accent);
    }
    button {
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      font-weight: 650;
      margin-top: 12px;
      transition: background 120ms ease, border-color 120ms ease, transform 120ms ease;
    }
    button:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
    button:active { transform: translateY(1px); }
    button.secondary {
      background: #fff;
      color: var(--text);
      border-color: var(--border-strong);
      margin-top: 0;
      width: auto;
      min-width: 108px;
    }
    button.secondary:hover { background: var(--surface-muted); border-color: var(--accent); }
    .stack { display: grid; gap: 12px; }
    .run {
      border: 1px solid var(--border);
      background: #fff;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 8px;
      cursor: pointer;
      transition: border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease;
    }
    .run:hover, .run.active {
      border-color: var(--accent);
      box-shadow: 0 8px 20px rgba(34, 87, 122, 0.09);
      transform: translateY(-1px);
    }
    .run-top {
      align-items: start;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: space-between;
    }
    .run strong {
      display: block;
      font-size: 13px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .run span {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-top: 5px;
      overflow-wrap: anywhere;
    }
    .status {
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 999px;
      display: inline-flex;
      font-size: 11px;
      font-weight: 750;
      line-height: 1;
      min-height: 24px;
      padding: 4px 8px;
      white-space: nowrap;
      max-width: 100%;
    }
    .ok { background: var(--ok-soft); border-color: #abefc6; color: var(--ok); }
    .failed { background: var(--danger-soft); border-color: #fecdca; color: var(--danger); }
    .blocked { background: var(--warn-soft); border-color: #fedf89; color: var(--warn); }
    .pending { background: var(--accent-soft); border-color: #b9dce8; color: var(--accent-strong); }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
    .metric {
      min-height: 112px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .metric-value {
      font-size: 13px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .metric-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 8px;
      overflow-wrap: anywhere;
    }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      background: var(--code-bg);
      color: #e2e8f0;
      border-radius: 8px;
      padding: 16px;
      font-size: 12px;
      line-height: 1.45;
      max-height: 46vh;
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--border);
      padding: 10px 8px;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      background: var(--surface-muted);
    }
    tbody tr:hover { background: #fbfcfe; }
    .empty {
      color: var(--muted);
      font-size: 13px;
      padding: 10px 0;
    }
    .fine-print {
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }
    .table-wrap {
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: auto;
      max-height: 48vh;
    }
    .table-wrap table th { position: sticky; top: 0; z-index: 1; }
    .hidden { display: none; }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--border); }
      .grid { grid-template-columns: 1fr; }
      header { align-items: flex-start; padding: 14px 18px; }
      section, aside { padding: 16px; }
    }
    @media (max-width: 520px) {
      header { flex-wrap: wrap; }
      .toolbar { width: 100%; }
      button.secondary { width: 100%; }
      .run { overflow: hidden; }
      .run-top {
        display: grid;
        justify-content: start;
        justify-items: start;
      }
      .run .status {
        white-space: normal;
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="mark" aria-hidden="true"></div>
      <div>
        <h1>software_maintaince agent</h1>
        <p class="eyebrow">Maintenance runs, traces, reports, and patch review.</p>
      </div>
    </div>
    <div class="toolbar">
      <button class="secondary" onclick="refreshRuns()">Refresh</button>
    </div>
  </header>
  <main>
    <aside>
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Run Fixture</h2>
            <p class="panel-kicker">Start a controlled maintenance run.</p>
          </div>
        </div>
        <div class="stack">
          <div>
            <label for="task">Task</label>
            <select id="task">
              <option value="examples/tasks/python_email_empty.json">Email empty fixture</option>
              <option value="examples/tasks/python_email_repair.json">Repair-loop fixture</option>
            </select>
          </div>
          <div>
            <label for="sandbox">Sandbox</label>
            <select id="sandbox">
              <option value="local">Local trusted fixture</option>
              <option value="e2b">E2B blocker proof</option>
            </select>
          </div>
        </div>
        <button onclick="runTask()">Run fixture</button>
        <div id="run-status" class="empty"></div>
      </div>
      <div class="panel-header">
        <div>
          <h2>Runs</h2>
          <p class="panel-kicker" id="run-count">Loading...</p>
        </div>
      </div>
      <div id="runs"></div>
    </aside>
    <section>
      <div class="grid">
        <div class="panel metric">
          <div class="panel-header"><h2>Status</h2></div>
          <div id="status" class="empty">Select a run.</div>
        </div>
        <div class="panel metric">
          <div class="panel-header"><h2>Selected Files</h2></div>
          <div id="selected" class="empty">No run selected.</div>
        </div>
        <div class="panel metric">
          <div class="panel-header"><h2>Attempts</h2></div>
          <div id="attempts" class="empty">No run selected.</div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Trace Events</h2>
            <p class="panel-kicker" id="event-count"></p>
          </div>
        </div>
        <div id="events" class="empty">No run selected.</div>
      </div>
      <div class="panel">
        <div class="panel-header"><h2>Final Report</h2></div>
        <pre id="report">No run selected.</pre>
      </div>
      <div class="panel">
        <div class="panel-header"><h2>Patch Diff</h2></div>
        <pre id="patch">No run selected.</pre>
      </div>
    </section>
  </main>
  <script>
    let activeRunId = '';

    async function refreshRuns() {
      const box = document.getElementById('runs');
      try {
        const res = await fetch('/api/runs');
        if (!res.ok) throw new Error('Unable to load runs.');
        const runs = await res.json();
        document.getElementById('run-count').textContent = `${runs.length} ${runs.length === 1 ? 'run' : 'runs'}`;
        if (!runs.length) {
          box.innerHTML = '<div class="empty">No runs yet.</div>';
          return;
        }
        box.innerHTML = runs.map(run => {
          const runId = escapeHtml(String(run.run_id || ''));
          const taskId = escapeHtml(String(run.task_id || 'Unknown task'));
          const status = escapeHtml(String(run.status || 'PENDING'));
          const activeClass = run.run_id === activeRunId ? ' active' : '';
          const runValue = escapeHtml(String(run.run_id || ''));
          return `
          <div class="run${activeClass}" data-run-id="${runValue}">
            <div class="run-top">
              <strong>${taskId}</strong>
              <span class="status ${statusClass(run.status)}">${status}</span>
            </div>
            <span>${runId}</span>
          </div>`;
        }).join('');
        box.querySelectorAll('.run').forEach(card => {
          card.addEventListener('click', () => loadRun(card.dataset.runId || ''));
        });
      } catch (error) {
        document.getElementById('run-count').textContent = 'Unavailable';
        box.innerHTML = `<div class="empty">${escapeHtml(error.message || 'Unable to load runs.')}</div>`;
      }
    }

    async function runTask() {
      const status = document.getElementById('run-status');
      status.textContent = 'Running...';
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          task: document.getElementById('task').value,
          sandbox: document.getElementById('sandbox').value
        })
      });
      const data = await res.json();
      status.textContent = data.status + (data.report_path ? ' - ' + data.report_path : '');
      await refreshRuns();
      if (data.run_id) await loadRun(data.run_id);
    }

    async function loadRun(id) {
      activeRunId = id;
      const res = await fetch('/api/runs/' + encodeURIComponent(id));
      const data = await res.json();
      if (data.error) {
        document.getElementById('status').innerHTML = `<div class="empty">${escapeHtml(data.error)}</div>`;
        return;
      }
      const run = data.run || {};
      const selected = (data.selected_files || []).map(item => item.path || item);
      const attempts = (data.attempts || []).map(item => `attempt ${item.attempt}: ${item.result}`);
      const events = data.events || [];
      document.getElementById('status').innerHTML = `
        <div class="metric-value">${escapeHtml(String(run.run_id || 'Unknown run'))}</div>
        <div class="metric-meta">${escapeHtml(String(run.task_id || 'Unknown task'))}</div>
        <div class="fine-print">
          <span class="status ${statusClass(run.status)}">${escapeHtml(String(run.status || 'PENDING'))}</span>
        </div>`;
      document.getElementById('selected').innerHTML = renderList(selected);
      document.getElementById('attempts').innerHTML = renderList(attempts);
      document.getElementById('event-count').textContent = `${events.length} ${events.length === 1 ? 'event' : 'events'}`;
      document.getElementById('events').innerHTML = renderEvents(events);
      document.getElementById('report').textContent = data.report || 'No report.';
      document.getElementById('patch').textContent = data.patch || 'No patch.';
      await refreshRuns();
    }

    function renderList(items) {
      if (!items.length) return '<div class="empty">None</div>';
      return '<ul>' + items.map(item => `<li>${escapeHtml(String(item))}</li>`).join('') + '</ul>';
    }

    function renderEvents(events) {
      if (!events.length) return '<div class="empty">None</div>';
      return `<div class="table-wrap">
        <table><thead><tr><th>Time</th><th>State</th><th>Kind</th><th>Message</th></tr></thead><tbody>
        ${events.map(e => {
          const time = String(e.timestamp || '').split('T').pop().slice(0,8);
          return `<tr>
            <td>${escapeHtml(time)}</td>
            <td>${escapeHtml(e.state || '')}</td>
            <td>${escapeHtml(e.kind || '')}</td>
            <td>${escapeHtml(e.message || '')}</td>
          </tr>`;
        }).join('')}
      </tbody></table></div>`;
    }

    function statusClass(status) {
      if ((status || '').includes('SUCCESS')) return 'ok';
      if ((status || '').includes('FAILED')) return 'failed';
      if ((status || '').includes('ESCALATED') || (status || '').includes('blocked')) return 'blocked';
      return 'pending';
    }

    function escapeHtml(value) {
      return value.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    }

    refreshRuns();
  </script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    settings = Settings.from_env()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.respond_text(render_dashboard_html(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/runs":
            self.respond_json(list_runs(self.settings.runs_dir))
            return
        if parsed.path.startswith("/api/runs/"):
            run_id = unquote(parsed.path.removeprefix("/api/runs/"))
            try:
                self.respond_json(load_run_bundle(self.settings.runs_dir, run_id))
            except (FileNotFoundError, ValueError):
                self.respond_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
            return
        self.respond_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self.respond_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        payload = self.read_payload()
        task_path = Path(str(payload.get("task", "examples/tasks/python_email_empty.json")))
        sandbox = str(payload.get("sandbox", "local"))
        try:
            task = load_task(task_path)
            report = SoftwareMaintainceAgent(self.settings).run_task(task, sandbox_kind=sandbox)
            run_id = Path(report.report_path or "").parent.name if report.report_path else ""
            self.respond_json(
                {
                    "status": report.status,
                    "risk": report.risk_level,
                    "run_id": run_id,
                    "report_path": report.report_path,
                    "patch_path": report.patch_path,
                }
            )
        except Exception as exc:  # noqa: BLE001 - local dashboard should return visible diagnostics.
            self.respond_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_payload(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return json.loads(raw or "{}")
        return {key: values[-1] for key, values in parse_qs(raw).items()}

    def respond_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_text(
        self,
        body: str,
        content_type: str | None = None,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type or mimetypes.types_map.get(".txt", "text/plain"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve_dashboard(host: str = "127.0.0.1", port: int = 8765, runs_dir: Path = Path("runs")) -> None:
    DashboardHandler.settings = Settings.from_env()
    DashboardHandler.settings = Settings(
        database_url=DashboardHandler.settings.database_url,
        llm_provider=DashboardHandler.settings.llm_provider,
        max_attempts=DashboardHandler.settings.max_attempts,
        max_changed_files=DashboardHandler.settings.max_changed_files,
        max_diff_lines=DashboardHandler.settings.max_diff_lines,
        default_sandbox=DashboardHandler.settings.default_sandbox,
        runs_dir=runs_dir,
    )
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"software_maintaince agent dashboard running at http://{host}:{port}")
    server.serve_forever()
