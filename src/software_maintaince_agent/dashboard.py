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
      --bg: #f7f8fa;
      --panel: #ffffff;
      --border: #d7dce2;
      --text: #18212f;
      --muted: #637083;
      --accent: #0f766e;
      --danger: #b42318;
      --ok: #067647;
      --warn: #b54708;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); }
    header {
      min-height: 72px;
      padding: 18px 28px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }
    h1 { margin: 0; font-size: 24px; line-height: 1.15; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 16px; letter-spacing: 0; }
    main {
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      min-height: calc(100vh - 72px);
    }
    aside {
      border-right: 1px solid var(--border);
      background: #eef2f6;
      padding: 18px;
      overflow: auto;
    }
    section { padding: 20px 24px; overflow: auto; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 16px;
    }
    label { display: block; font-size: 12px; color: var(--muted); margin: 10px 0 5px; }
    input, select, button {
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 7px 9px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    button {
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      font-weight: 650;
      margin-top: 12px;
    }
    button.secondary { background: #fff; color: var(--text); border-color: var(--border); }
    .run {
      border: 1px solid var(--border);
      background: #fff;
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 8px;
      cursor: pointer;
    }
    .run:hover { border-color: var(--accent); }
    .run strong { display: block; font-size: 13px; overflow-wrap: anywhere; }
    .run span { display: block; font-size: 12px; color: var(--muted); margin-top: 4px; }
    .status { font-weight: 700; }
    .ok { color: var(--ok); }
    .failed { color: var(--danger); }
    .blocked { color: var(--warn); }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      background: #101828;
      color: #eef2f6;
      border-radius: 8px;
      padding: 14px;
      font-size: 12px;
      line-height: 1.45;
      max-height: 48vh;
      overflow: auto;
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; border-bottom: 1px solid var(--border); padding: 8px; vertical-align: top; }
    th { color: var(--muted); font-weight: 650; }
    .empty { color: var(--muted); padding: 16px 0; }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--border); }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>software_maintaince agent</h1>
      <div class="empty">CI failure to tested maintenance patch</div>
    </div>
    <button class="secondary" style="max-width: 140px" onclick="refreshRuns()">Refresh</button>
  </header>
  <main>
    <aside>
      <div class="panel">
        <h2>Run Fixture</h2>
        <label for="task">Task</label>
        <select id="task">
          <option value="examples/tasks/python_email_empty.json">Email empty fixture</option>
          <option value="examples/tasks/python_email_repair.json">Repair-loop fixture</option>
        </select>
        <label for="sandbox">Sandbox</label>
        <select id="sandbox">
          <option value="local">local trusted fixture</option>
          <option value="e2b">e2b blocker proof</option>
        </select>
        <button onclick="runTask()">Run</button>
        <div id="run-status" class="empty"></div>
      </div>
      <h2>Runs</h2>
      <div id="runs"></div>
    </aside>
    <section>
      <div class="grid">
        <div class="panel"><h2>Status</h2><div id="status" class="empty">Select a run.</div></div>
        <div class="panel"><h2>Selected Files</h2><div id="selected" class="empty">No run selected.</div></div>
        <div class="panel"><h2>Attempts</h2><div id="attempts" class="empty">No run selected.</div></div>
      </div>
      <div class="panel">
        <h2>Trace Events</h2>
        <div id="events" class="empty">No run selected.</div>
      </div>
      <div class="panel">
        <h2>Final Report</h2>
        <pre id="report">No run selected.</pre>
      </div>
      <div class="panel">
        <h2>Patch Diff</h2>
        <pre id="patch">No run selected.</pre>
      </div>
    </section>
  </main>
  <script>
    async function refreshRuns() {
      const res = await fetch('/api/runs');
      const runs = await res.json();
      const box = document.getElementById('runs');
      if (!runs.length) {
        box.innerHTML = '<div class="empty">No runs yet.</div>';
        return;
      }
      box.innerHTML = runs.map(run => `
        <div class="run" onclick="loadRun('${run.run_id}')">
          <strong>${run.run_id}</strong>
          <span>${run.task_id}</span>
          <span class="status ${statusClass(run.status)}">${run.status}</span>
        </div>`).join('');
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
      const res = await fetch('/api/runs/' + encodeURIComponent(id));
      const data = await res.json();
      document.getElementById('status').innerHTML = `
        <div><strong>${data.run.run_id}</strong></div>
        <div>${data.run.task_id}</div>
        <div class="status ${statusClass(data.run.status)}">${data.run.status}</div>`;
      document.getElementById('selected').innerHTML = renderList((data.selected_files || []).map(item => item.path || item));
      const attempts = (data.attempts || []).map(item => {
        return `attempt ${item.attempt}: ${item.result}`;
      });
      document.getElementById('attempts').innerHTML = renderList(attempts);
      document.getElementById('events').innerHTML = renderEvents(data.events || []);
      document.getElementById('report').textContent = data.report || 'No report.';
      document.getElementById('patch').textContent = data.patch || 'No patch.';
    }
    function renderList(items) {
      if (!items.length) return '<div class="empty">None</div>';
      return '<ul>' + items.map(item => `<li>${escapeHtml(String(item))}</li>`).join('') + '</ul>';
    }
    function renderEvents(events) {
      if (!events.length) return '<div class="empty">None</div>';
      return `<table><thead><tr><th>Time</th><th>State</th><th>Kind</th><th>Message</th></tr></thead><tbody>
        ${events.map(e => {
          const time = e.timestamp.split('T').pop().slice(0,8);
          return `<tr><td>${time}</td><td>${e.state || ''}</td><td>${e.kind}</td><td>${escapeHtml(e.message)}</td></tr>`;
        }).join('')}
      </tbody></table>`;
    }
    function statusClass(status) {
      if ((status || '').includes('SUCCESS')) return 'ok';
      if ((status || '').includes('FAILED')) return 'failed';
      if ((status || '').includes('ESCALATED') || (status || '').includes('blocked')) return 'blocked';
      return '';
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
