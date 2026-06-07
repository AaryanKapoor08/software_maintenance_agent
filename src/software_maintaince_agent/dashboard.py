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
  <title>Maintenance Agent</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #ffffff;
      --subtle: #fafafa;
      --panel: #ffffff;
      --border: #ececec;
      --border-strong: #e0e0e0;
      --text: #0a0a0a;
      --muted: #707070;
      --muted-soft: #999999;
      --accent: #0a0a0a;
      --accent-hover: #2a2a2a;
      --focus: rgba(10, 10, 10, 0.12);
      --ok: #137333;
      --failed: #c5221f;
      --blocked: #b06000;
      --pending: #5f6368;
      --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Code", Menlo, Consolas, monospace;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-family: var(--sans);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-size: 13px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    a { color: inherit; }
    p { margin: 0; }
    ::selection { background: rgba(10, 10, 10, 0.1); }

    /* ---- top bar ---- */
    header {
      height: 56px;
      padding: 0 24px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.8);
      backdrop-filter: saturate(180%) blur(8px);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .brand { display: flex; align-items: center; gap: 11px; min-width: 0; }
    .mark {
      width: 26px; height: 26px;
      border-radius: 7px;
      background: var(--text);
      color: #fff;
      display: grid; place-items: center;
      flex: 0 0 auto;
    }
    .mark svg { width: 15px; height: 15px; display: block; }
    .brand h1 {
      margin: 0;
      font-size: 13.5px;
      font-weight: 600;
      letter-spacing: -0.01em;
      white-space: nowrap;
    }
    .brand .tag {
      font-size: 11px;
      color: var(--muted);
      border-left: 1px solid var(--border-strong);
      padding-left: 11px;
      white-space: nowrap;
    }
    .toolbar { display: flex; align-items: center; gap: 8px; }

    /* ---- buttons ---- */
    button {
      font: inherit;
      cursor: pointer;
      border-radius: 7px;
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #fff;
      font-weight: 500;
      font-size: 12.5px;
      padding: 0 14px;
      height: 34px;
      transition: background 120ms ease, border-color 120ms ease, opacity 120ms ease;
    }
    button:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
    button:disabled { opacity: 0.55; cursor: default; }
    button:focus-visible { outline: 3px solid var(--focus); outline-offset: 1px; }
    button.ghost {
      background: transparent;
      color: var(--text);
      border-color: var(--border-strong);
    }
    button.ghost:hover { background: var(--subtle); border-color: var(--muted-soft); }
    button.block { width: 100%; }

    /* ---- layout ---- */
    main {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      min-height: calc(100vh - 56px);
    }
    aside {
      border-right: 1px solid var(--border);
      background: var(--subtle);
      padding: 18px 16px;
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 22px;
    }
    section { padding: 24px 28px 40px; overflow: auto; min-width: 0; }
    .content { max-width: 1080px; margin: 0 auto; display: grid; gap: 16px; }

    .eyebrow {
      font-size: 10.5px;
      font-weight: 600;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      color: var(--muted-soft);
    }

    /* ---- form ---- */
    .field { display: grid; gap: 6px; }
    label { font-size: 12px; font-weight: 500; color: var(--text); }
    select, input {
      width: 100%;
      height: 34px;
      border: 1px solid var(--border-strong);
      border-radius: 7px;
      padding: 0 10px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 12.5px;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 10px center;
      padding-right: 28px;
    }
    select:focus, input:focus { outline: 3px solid var(--focus); outline-offset: 0; border-color: var(--muted-soft); }
    .stack { display: grid; gap: 12px; }

    .side-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
    .count { font-size: 11px; color: var(--muted-soft); font-variant-numeric: tabular-nums; }
    .run-hint { font-size: 11.5px; color: var(--muted); min-height: 16px; }

    /* ---- run list ---- */
    .runs { display: grid; gap: 6px; }
    .run {
      border: 1px solid transparent;
      background: transparent;
      border-radius: 8px;
      padding: 9px 10px;
      cursor: pointer;
      transition: background 110ms ease, border-color 110ms ease;
    }
    .run:hover { background: #fff; border-color: var(--border); }
    .run.active { background: #fff; border-color: var(--border-strong); }
    .run-top { display: flex; align-items: center; gap: 8px; justify-content: space-between; }
    .run-task { font-size: 12.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .run-id { display: block; font-family: var(--mono); font-size: 10.5px; color: var(--muted-soft); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    /* ---- status dot ---- */
    .status { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 500; white-space: nowrap; color: var(--muted); }
    .status::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--pending); flex: 0 0 auto; }
    .status.ok { color: var(--ok); } .status.ok::before { background: var(--ok); }
    .status.failed { color: var(--failed); } .status.failed::before { background: var(--failed); }
    .status.blocked { color: var(--blocked); } .status.blocked::before { background: var(--blocked); }
    .status.pending { color: var(--pending); } .status.pending::before { background: var(--pending); }
    .dot-only { gap: 0; } .dot-only::before { margin: 0; }

    /* ---- panels / cards ---- */
    .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
    .panel > .ph { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 13px 16px; border-bottom: 1px solid var(--border); }
    .panel > .ph h2 { margin: 0; font-size: 12.5px; font-weight: 600; letter-spacing: -0.005em; }
    .panel > .ph .count { font-size: 11px; }
    .panel > .pb { padding: 16px; }

    /* ---- run header strip ---- */
    .run-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
    .run-head .title { display: grid; gap: 4px; min-width: 0; }
    .run-head .title .id { font-family: var(--mono); font-size: 15px; font-weight: 600; letter-spacing: -0.01em; overflow-wrap: anywhere; }
    .run-head .title .task { font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }

    /* ---- metric cards ---- */
    .cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px 15px; display: grid; gap: 9px; align-content: start; min-height: 120px; }
    .card .eyebrow { margin: 0; }
    .card .big { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
    .card ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 5px; }
    .card li { font-family: var(--mono); font-size: 11.5px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .card li.muted { color: var(--muted); }

    /* ---- code blocks ---- */
    pre {
      margin: 0;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.55;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      max-height: 440px;
      overflow: auto;
      color: var(--text);
    }
    .diff-line { display: block; }
    .diff-add { color: #137333; background: rgba(19, 115, 51, 0.07); }
    .diff-del { color: #c5221f; background: rgba(197, 34, 31, 0.07); }
    .diff-hunk { color: #6639ba; }
    .diff-meta { color: var(--muted); }

    /* ---- table ---- */
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    thead th {
      text-align: left;
      font-size: 10.5px;
      font-weight: 600;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: var(--muted-soft);
      padding: 9px 14px;
      background: var(--subtle);
      border-bottom: 1px solid var(--border);
      position: sticky; top: 0; z-index: 1;
    }
    tbody td { padding: 9px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
    tbody tr:last-child td { border-bottom: 0; }
    tbody tr:hover { background: var(--subtle); }
    td.t-time { font-family: var(--mono); color: var(--muted); white-space: nowrap; font-size: 11px; }
    td.t-state, td.t-kind { font-family: var(--mono); font-size: 11px; color: var(--muted); white-space: nowrap; }
    td.t-msg { color: var(--text); overflow-wrap: anywhere; }
    .table-scroll { max-height: 440px; overflow: auto; }

    .empty { color: var(--muted-soft); font-size: 12px; padding: 4px 0; }
    .panel .empty, .card .empty { padding: 0; }
    .hidden { display: none; }

    @media (max-width: 880px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--border); }
      .cards { grid-template-columns: 1fr; }
      section { padding: 18px 16px 32px; }
      .brand .tag { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span class="mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
      </span>
      <h1>Maintenance Agent</h1>
      <span class="tag">Runs &amp; patch review</span>
    </div>
    <div class="toolbar">
      <button class="ghost" onclick="refreshRuns()">Refresh</button>
    </div>
  </header>
  <main>
    <aside>
      <div>
        <div class="side-head">
          <span class="eyebrow">New run</span>
        </div>
        <div class="stack">
          <div class="field">
            <label for="task">Task</label>
            <select id="task">
              <option value="examples/tasks/python_email_empty.json">Email empty fixture</option>
              <option value="examples/tasks/python_email_repair.json">Repair-loop fixture</option>
            </select>
          </div>
          <div class="field">
            <label for="sandbox">Sandbox</label>
            <select id="sandbox">
              <option value="local">Local trusted fixture</option>
              <option value="e2b">E2B blocker proof</option>
            </select>
          </div>
          <button id="run-btn" class="block" onclick="runTask()">Run fixture</button>
          <div id="run-status" class="run-hint"></div>
        </div>
      </div>
      <div>
        <div class="side-head">
          <span class="eyebrow">Runs</span>
          <span class="count" id="run-count">…</span>
        </div>
        <div id="runs" class="runs"></div>
      </div>
    </aside>
    <section>
      <div class="content">
        <div class="panel">
          <div class="pb">
            <div class="run-head" id="run-head">
              <div class="title">
                <span class="id" id="rh-id">No run selected</span>
                <span class="task" id="rh-task">Pick a run from the left, or start a new fixture run.</span>
              </div>
              <span class="status pending" id="rh-status" style="display:none"></span>
            </div>
          </div>
        </div>
        <div class="cards">
          <div class="card">
            <span class="eyebrow">Status</span>
            <div id="status"><span class="empty">—</span></div>
          </div>
          <div class="card">
            <span class="eyebrow">Selected files</span>
            <div id="selected"><span class="empty">—</span></div>
          </div>
          <div class="card">
            <span class="eyebrow">Attempts</span>
            <div id="attempts"><span class="empty">—</span></div>
          </div>
        </div>
        <div class="panel">
          <div class="ph"><h2>Trace events</h2><span class="count" id="event-count"></span></div>
          <div id="events"><div class="pb"><span class="empty">No run selected.</span></div></div>
        </div>
        <div class="panel">
          <div class="ph"><h2>Final report</h2></div>
          <div class="pb"><pre id="report"><span class="empty">No run selected.</span></pre></div>
        </div>
        <div class="panel">
          <div class="ph"><h2>Patch diff</h2></div>
          <div class="pb"><pre id="patch"><span class="empty">No run selected.</span></pre></div>
        </div>
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
        document.getElementById('run-count').textContent = String(runs.length);
        if (!runs.length) {
          box.innerHTML = '<div class="empty">No runs yet.</div>';
          return;
        }
        box.innerHTML = runs.map(run => {
          const runId = escapeHtml(String(run.run_id || ''));
          const taskId = escapeHtml(String(run.task_id || 'Unknown task'));
          const activeClass = run.run_id === activeRunId ? ' active' : '';
          return `
          <div class="run${activeClass}" data-run-id="${runId}" title="${runId}">
            <div class="run-top">
              <span class="run-task">${taskId}</span>
              <span class="status dot-only ${statusClass(run.status)}" title="${escapeHtml(String(run.status || 'PENDING'))}"></span>
            </div>
            <span class="run-id">${runId}</span>
          </div>`;
        }).join('');
        box.querySelectorAll('.run').forEach(card => {
          card.addEventListener('click', () => loadRun(card.dataset.runId || ''));
        });
      } catch (error) {
        document.getElementById('run-count').textContent = '!';
        box.innerHTML = `<div class="empty">${escapeHtml(error.message || 'Unable to load runs.')}</div>`;
      }
    }

    async function runTask() {
      const btn = document.getElementById('run-btn');
      const status = document.getElementById('run-status');
      btn.disabled = true;
      btn.textContent = 'Running…';
      status.textContent = 'Starting run…';
      try {
        const res = await fetch('/api/run', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            task: document.getElementById('task').value,
            sandbox: document.getElementById('sandbox').value
          })
        });
        const data = await res.json();
        status.textContent = data.error ? `Error: ${data.error}` : (data.status || 'Done');
        await refreshRuns();
        if (data.run_id) await loadRun(data.run_id);
      } catch (e) {
        status.textContent = `Error: ${e.message || e}`;
      } finally {
        btn.disabled = false;
        btn.textContent = 'Run fixture';
      }
    }

    async function loadRun(id) {
      activeRunId = id;
      const res = await fetch('/api/runs/' + encodeURIComponent(id));
      const data = await res.json();
      if (data.error) {
        document.getElementById('rh-id').textContent = 'Run not found';
        return;
      }
      const run = data.run || {};
      const status = String(run.status || 'PENDING');
      const selected = (data.selected_files || []).map(item => item.path || item);
      const attempts = (data.attempts || []);
      const events = data.events || [];

      document.getElementById('rh-id').textContent = String(run.run_id || 'Unknown run');
      document.getElementById('rh-task').textContent = String(run.task_id || 'Unknown task');
      const rhStatus = document.getElementById('rh-status');
      rhStatus.style.display = '';
      rhStatus.className = 'status ' + statusClass(status);
      rhStatus.textContent = status;

      document.getElementById('status').innerHTML =
        `<span class="status ${statusClass(status)}" style="font-size:13px">${escapeHtml(status)}</span>`;
      document.getElementById('selected').innerHTML = renderList(selected, 'file');
      document.getElementById('attempts').innerHTML = renderAttempts(attempts);
      document.getElementById('event-count').textContent = `${events.length} ${events.length === 1 ? 'event' : 'events'}`;
      document.getElementById('events').innerHTML = renderEvents(events);
      renderReport(data.report);
      renderPatch(data.patch);
      await refreshRuns();
    }

    function renderList(items, kind) {
      if (!items.length) return '<span class="empty">None</span>';
      return '<ul>' + items.map(item => `<li title="${escapeHtml(String(item))}">${escapeHtml(String(item))}</li>`).join('') + '</ul>';
    }

    function renderAttempts(attempts) {
      if (!attempts.length) return '<span class="empty">None</span>';
      return `<div class="big">${attempts.length}</div><ul>` +
        attempts.map(a => `<li class="muted">#${escapeHtml(String(a.attempt))} · ${escapeHtml(String(a.result || ''))}</li>`).join('') +
        '</ul>';
    }

    function renderEvents(events) {
      if (!events.length) return '<div class="pb"><span class="empty">None</span></div>';
      return `<div class="table-scroll">
        <table><thead><tr><th>Time</th><th>State</th><th>Kind</th><th>Message</th></tr></thead><tbody>
        ${events.map(e => {
          const time = String(e.timestamp || '').split('T').pop().slice(0,8);
          return `<tr>
            <td class="t-time">${escapeHtml(time)}</td>
            <td class="t-state">${escapeHtml(e.state || '')}</td>
            <td class="t-kind">${escapeHtml(e.kind || '')}</td>
            <td class="t-msg">${escapeHtml(e.message || '')}</td>
          </tr>`;
        }).join('')}
      </tbody></table></div>`;
    }

    function renderReport(report) {
      const el = document.getElementById('report');
      if (!report) { el.innerHTML = '<span class="empty">No report.</span>'; return; }
      el.textContent = report;
    }

    function renderPatch(patch) {
      const el = document.getElementById('patch');
      if (!patch) { el.innerHTML = '<span class="empty">No patch.</span>'; return; }
      el.innerHTML = String(patch).split('\\n').map(line => {
        const safe = escapeHtml(line);
        let cls = '';
        if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')) cls = 'diff-meta';
        else if (line.startsWith('@@')) cls = 'diff-hunk';
        else if (line.startsWith('+')) cls = 'diff-add';
        else if (line.startsWith('-')) cls = 'diff-del';
        return `<span class="diff-line ${cls}">${safe || ' '}</span>`;
      }).join('');
    }

    function statusClass(status) {
      const s = String(status || '').toUpperCase();
      if (s.includes('SUCCESS')) return 'ok';
      if (s.includes('FAILED')) return 'failed';
      if (s.includes('ESCALATED') || s.includes('BLOCKED')) return 'blocked';
      return 'pending';
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
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
