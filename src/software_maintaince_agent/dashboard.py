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
      --rail: #fafafa;
      --ink: #111111;
      --ink-soft: #3d3d3d;
      --muted: #6f6f6f;
      --faint: #a3a3a3;
      --line: #e6e6e6;
      --line-strong: #d4d4d4;
      --fill-soft: #f4f4f4;
      --mono: ui-monospace, "Cascadia Code", Consolas, "SF Mono", Menlo, monospace;
      --sans: "Segoe UI", Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: var(--sans);
      font-size: 13px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }
    a { color: inherit; }
    ::selection { background: rgba(17, 17, 17, 0.1); }
    .num { font-variant-numeric: tabular-nums; }
    .mono { font-family: var(--mono); }
    .hidden { display: none !important; }

    .eyebrow {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--faint);
    }
    .empty { color: var(--faint); font-size: 12px; }

    /* ---------- header ---------- */
    header {
      height: 52px;
      padding: 0 20px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      background: var(--bg);
      z-index: 20;
    }
    .brand { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
    .brand h1 {
      margin: 0;
      font-size: 13px;
      font-weight: 650;
      letter-spacing: 0.02em;
      white-space: nowrap;
    }
    .brand .sep { color: var(--line-strong); }
    .brand .sub { font-size: 12px; color: var(--muted); white-space: nowrap; }
    .header-meta { display: flex; align-items: center; gap: 14px; }
    .header-meta .stamp { font-size: 11px; color: var(--faint); font-family: var(--mono); }

    /* ---------- buttons ---------- */
    button {
      font: inherit;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      height: 30px;
      padding: 0 12px;
      border-radius: 5px;
      border: 1px solid var(--ink);
      background: var(--ink);
      color: #fff;
      transition: opacity 120ms ease, background 120ms ease;
    }
    button:hover { background: var(--ink-soft); border-color: var(--ink-soft); }
    button:disabled { opacity: 0.5; cursor: default; }
    button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
    button.ghost { background: transparent; color: var(--ink); border-color: var(--line-strong); }
    button.ghost:hover { background: var(--fill-soft); }
    button.block { width: 100%; height: 32px; }
    .linklike {
      border: 0; background: none; color: var(--muted);
      height: auto; padding: 0; font-size: 12px; font-weight: 500;
    }
    .linklike:hover { background: none; color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }

    /* ---------- layout ---------- */
    main { display: grid; grid-template-columns: 288px minmax(0, 1fr); min-height: calc(100vh - 52px); }
    aside {
      border-right: 1px solid var(--line);
      background: var(--rail);
      padding: 20px 16px 32px;
      display: flex;
      flex-direction: column;
      gap: 26px;
      overflow-y: auto;
      max-height: calc(100vh - 52px);
      position: sticky;
      top: 52px;
    }
    section.stage { padding: 28px 32px 64px; min-width: 0; }
    .content { max-width: 1060px; margin: 0 auto; }

    /* ---------- sidebar form ---------- */
    .side-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; }
    .side-count { font-size: 11px; color: var(--faint); font-family: var(--mono); }
    .field { display: grid; gap: 5px; margin-bottom: 10px; }
    .field label { font-size: 11.5px; font-weight: 550; color: var(--ink-soft); }
    select {
      width: 100%; height: 32px;
      border: 1px solid var(--line-strong); border-radius: 5px;
      background: #fff; color: var(--ink);
      font: inherit; font-size: 12px;
      padding: 0 26px 0 9px;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%236f6f6f' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 9px center;
    }
    select:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
    .run-hint { font-size: 11.5px; color: var(--muted); min-height: 17px; margin-top: 8px; }

    /* ---------- sidebar run list ---------- */
    .runs { display: flex; flex-direction: column; gap: 2px; }
    .run-item {
      text-align: left;
      border: 1px solid transparent;
      background: transparent;
      color: var(--ink);
      border-radius: 6px;
      padding: 8px 9px;
      height: auto;
      display: block;
      width: 100%;
      font-weight: 400;
    }
    .run-item:hover { background: #fff; border-color: var(--line); }
    .run-item.active { background: #fff; border-color: var(--line-strong); }
    .run-item .r1 { display: flex; align-items: center; gap: 7px; }
    .run-item .r1 .task {
      font-size: 12px; font-weight: 550;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      flex: 1; min-width: 0;
    }
    .run-item .r2 {
      display: flex; justify-content: space-between; gap: 8px;
      margin-top: 2px; padding-left: 17px;
    }
    .run-item .rid {
      font-family: var(--mono); font-size: 10px; color: var(--faint);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .run-item .rwhen { font-size: 10.5px; color: var(--faint); white-space: nowrap; }

    /* ---------- status glyphs & badges ---------- */
    .glyph { width: 10px; height: 10px; flex: 0 0 auto; display: inline-block; vertical-align: -0.5px; }
    .badge {
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;
      border: 1px solid var(--line-strong); border-radius: 4px;
      padding: 3px 8px; color: var(--ink-soft); white-space: nowrap;
      background: #fff;
    }
    .badge.b-ok { background: var(--ink); border-color: var(--ink); color: #fff; }

    /* ---------- panels ---------- */
    .panel { border: 1px solid var(--line); border-radius: 8px; background: #fff; overflow: hidden; }
    .panel + .panel, .panel + .grid2, .grid2 + .panel { margin-top: 14px; }
    .ph {
      display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
      padding: 12px 16px; border-bottom: 1px solid var(--line);
    }
    .ph h2 { margin: 0; font-size: 12px; font-weight: 650; letter-spacing: 0.01em; }
    .ph .meta { font-size: 11px; color: var(--faint); font-family: var(--mono); }
    .pb { padding: 16px; }

    /* ---------- overview ---------- */
    .page-title { margin: 0 0 4px; font-size: 17px; font-weight: 650; letter-spacing: -0.01em; }
    .page-sub { margin: 0 0 22px; font-size: 12.5px; color: var(--muted); }

    .tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
    .tile { border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px 13px; background: #fff; }
    .tile .val { font-size: 26px; font-weight: 650; letter-spacing: -0.02em; line-height: 1.15; margin-top: 6px; font-variant-numeric: tabular-nums; }
    .tile .note { font-size: 11px; color: var(--muted); margin-top: 3px; }

    .dist { display: flex; height: 8px; border-radius: 4px; overflow: hidden; gap: 2px; margin: 14px 0 10px; }
    .dist span { display: block; min-width: 3px; }
    .dist-legend { display: flex; flex-wrap: wrap; gap: 4px 18px; }
    .dl-item { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-soft); }
    .dl-item .n { color: var(--faint); font-family: var(--mono); font-size: 10.5px; }

    /* ---------- tables ---------- */
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    thead th {
      text-align: left; font-size: 10px; font-weight: 600;
      letter-spacing: 0.08em; text-transform: uppercase; color: var(--faint);
      padding: 8px 16px; border-bottom: 1px solid var(--line);
      background: var(--rail);
      position: sticky; top: 0; z-index: 1;
    }
    tbody td { padding: 9px 16px; border-bottom: 1px solid var(--line); vertical-align: top; }
    tbody tr:last-child td { border-bottom: 0; }
    tbody tr.rowlink { cursor: pointer; }
    tbody tr.rowlink:hover { background: var(--rail); }
    td.c-mono { font-family: var(--mono); font-size: 11px; white-space: nowrap; }
    td.c-dim { color: var(--muted); }
    td.c-num { font-variant-numeric: tabular-nums; white-space: nowrap; }
    .table-scroll { max-height: 420px; overflow: auto; }

    /* ---------- run view ---------- */
    .crumbs { margin-bottom: 14px; }
    .run-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; flex-wrap: wrap; margin-bottom: 18px; }
    .run-head .id { margin: 0; font-family: var(--mono); font-size: 17px; font-weight: 650; letter-spacing: -0.01em; overflow-wrap: anywhere; }
    .run-head .task { margin: 3px 0 0; font-size: 12.5px; color: var(--muted); overflow-wrap: anywhere; }
    .run-meta { display: flex; gap: 4px 22px; flex-wrap: wrap; margin: 12px 0 18px; padding: 12px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
    .rm { display: grid; gap: 1px; }
    .rm .k { font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--faint); }
    .rm .v { font-size: 12px; font-variant-numeric: tabular-nums; color: var(--ink-soft); }
    .rm .v.mono { font-size: 11.5px; }

    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
    .grid2 .panel { margin-top: 0; }

    /* ---------- timeline ---------- */
    .timeline { padding: 6px 0; max-height: 480px; overflow: auto; }
    .tl-row {
      display: grid;
      grid-template-columns: 26px 66px 60px 150px minmax(0, 1fr);
      gap: 0 10px;
      align-items: baseline;
      padding: 5px 16px 5px 10px;
    }
    .tl-row:hover { background: var(--rail); }
    .tl-rail { position: relative; align-self: stretch; }
    .tl-rail::before {
      content: ""; position: absolute; left: 50%; top: 0; bottom: 0;
      width: 1px; background: var(--line); transform: translateX(-50%);
    }
    .tl-row:first-child .tl-rail::before { top: 50%; }
    .tl-row:last-child .tl-rail::before { bottom: 50%; }
    .tl-rail i {
      position: absolute; left: 50%; top: 0.55em; transform: translate(-50%, 0);
      width: 5px; height: 5px; border-radius: 50%;
      background: var(--line-strong); border: 1px solid #fff;
    }
    .tl-row.tl-state-change .tl-rail i { background: var(--ink); width: 7px; height: 7px; }
    .tl-time { font-family: var(--mono); font-size: 11px; color: var(--muted); white-space: nowrap; }
    .tl-elapsed { font-family: var(--mono); font-size: 10.5px; color: var(--faint); white-space: nowrap; }
    .tl-state { font-size: 10px; font-weight: 650; letter-spacing: 0.07em; text-transform: uppercase; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tl-state.cont { color: transparent; }
    .tl-row .tl-kind-msg { min-width: 0; }
    .tl-kind { font-family: var(--mono); font-size: 10.5px; color: var(--faint); margin-right: 8px; }
    .tl-msg { font-size: 12px; color: var(--ink-soft); overflow-wrap: anywhere; }

    /* ---------- lists ---------- */
    ul.plain { margin: 0; padding: 0; list-style: none; display: grid; gap: 6px; }
    ul.plain li { font-family: var(--mono); font-size: 11.5px; overflow-wrap: anywhere; }
    .attempt { display: flex; gap: 10px; align-items: baseline; padding: 7px 0; border-bottom: 1px solid var(--line); }
    .attempt:first-child { padding-top: 0; }
    .attempt:last-child { border-bottom: 0; padding-bottom: 0; }
    .attempt .no { font-family: var(--mono); font-size: 11px; color: var(--faint); flex: 0 0 auto; }
    .attempt .res { font-size: 12px; color: var(--ink-soft); overflow-wrap: anywhere; }

    /* ---------- code / report / diff ---------- */
    pre {
      margin: 0; font-family: var(--mono); font-size: 11.5px; line-height: 1.6;
      white-space: pre-wrap; overflow-wrap: anywhere;
      max-height: 460px; overflow: auto; color: var(--ink-soft);
    }
    .diff-file { border-top: 1px solid var(--line); }
    .diff-file:first-child { border-top: 0; }
    .diff-file-head {
      display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
      padding: 9px 16px; background: var(--rail);
      font-family: var(--mono); font-size: 11px;
      border-bottom: 1px solid var(--line);
    }
    .diff-file-head .fname { font-weight: 600; color: var(--ink); overflow-wrap: anywhere; }
    .diff-file-head .fstat { color: var(--muted); white-space: nowrap; font-size: 10.5px; }
    .diff-body { font-family: var(--mono); font-size: 11.5px; line-height: 1.55; max-height: 420px; overflow: auto; padding: 6px 0; }
    .dl { display: flex; }
    .dl .g {
      flex: 0 0 26px; text-align: center; user-select: none;
      color: var(--faint); font-size: 10.5px;
    }
    .dl .t { flex: 1; min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; padding-right: 14px; }
    .dl.add { background: var(--fill-soft); }
    .dl.add .g { color: var(--ink); font-weight: 700; }
    .dl.add .t { color: var(--ink); }
    .dl.del .t { color: var(--faint); }
    .dl.del .g { color: var(--faint); }
    .dl.hunk .t, .dl.hunk .g { color: var(--muted); }
    .dl.hunk { border-top: 1px dashed var(--line); margin-top: 4px; padding-top: 4px; }
    .dl.meta .t { color: var(--faint); }

    @media (max-width: 940px) {
      main { grid-template-columns: 1fr; }
      aside { position: static; max-height: none; border-right: 0; border-bottom: 1px solid var(--line); }
      section.stage { padding: 20px 16px 48px; }
      .tiles { grid-template-columns: repeat(2, 1fr); }
      .grid2 { grid-template-columns: 1fr; }
      .tl-row { grid-template-columns: 26px 66px minmax(0, 1fr); }
      .tl-elapsed, .tl-state { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>MAINTENANCE&nbsp;AGENT</h1>
      <span class="sep">/</span>
      <span class="sub">Autonomous run trace &amp; patch review</span>
    </div>
    <div class="header-meta">
      <span class="stamp" id="stamp"></span>
      <button class="ghost" onclick="refresh()">Refresh</button>
    </div>
  </header>

  <main>
    <aside>
      <div>
        <div class="side-head"><span class="eyebrow">New run</span></div>
        <div class="field">
          <label for="task">Task fixture</label>
          <select id="task">
            <option value="examples/tasks/python_email_empty.json">Email empty fixture</option>
            <option value="examples/tasks/python_email_repair.json">Repair-loop fixture</option>
          </select>
        </div>
        <div class="field">
          <label for="sandbox">Sandbox</label>
          <select id="sandbox">
            <option value="docker">Docker isolated</option>
            <option value="local">Local trusted fixture</option>
            <option value="e2b">E2B blocker proof</option>
          </select>
        </div>
        <button id="run-btn" class="block" onclick="runTask()">Run fixture</button>
        <div id="run-status" class="run-hint"></div>
      </div>
      <div>
        <div class="side-head">
          <span class="eyebrow">Runs</span>
          <span class="side-count" id="run-count"></span>
        </div>
        <div id="runs" class="runs"><span class="empty">Loading…</span></div>
      </div>
    </aside>

    <section class="stage">
      <div class="content">

        <!-- ============ overview ============ -->
        <div id="view-overview">
          <h2 class="page-title">Overview</h2>
          <p class="page-sub">All recorded agent runs, most recent first. Select a run for its full trace, report, and patch.</p>
          <div class="tiles">
            <div class="tile"><span class="eyebrow">Total runs</span><div class="val num" id="ov-total">0</div><div class="note" id="ov-total-note">&nbsp;</div></div>
            <div class="tile"><span class="eyebrow">Success rate</span><div class="val num" id="ov-rate">—</div><div class="note" id="ov-rate-note">&nbsp;</div></div>
            <div class="tile"><span class="eyebrow">Needs attention</span><div class="val num" id="ov-attn">0</div><div class="note">failed or escalated</div></div>
            <div class="tile"><span class="eyebrow">Last activity</span><div class="val" id="ov-last" style="font-size:19px">—</div><div class="note" id="ov-last-note">&nbsp;</div></div>
          </div>
          <div class="panel">
            <div class="ph"><h2>Outcome distribution</h2><span class="meta" id="ov-dist-meta"></span></div>
            <div class="pb" style="padding-top:8px">
              <div class="dist" id="ov-dist"></div>
              <div class="dist-legend" id="ov-legend"></div>
            </div>
          </div>
          <div class="panel">
            <div class="ph"><h2>Run history</h2><span class="meta" id="ov-table-meta"></span></div>
            <div class="table-scroll">
              <table>
                <thead><tr><th>Status</th><th>Run</th><th>Task</th><th>Started</th><th style="text-align:right">Duration</th></tr></thead>
                <tbody id="ov-rows"></tbody>
              </table>
            </div>
            <div class="pb hidden" id="ov-empty"><span class="empty">No runs recorded yet. Start one from the panel on the left.</span></div>
          </div>
        </div>

        <!-- ============ run detail ============ -->
        <div id="view-run" class="hidden">
          <div class="crumbs"><button class="linklike" onclick="goOverview()">&larr; All runs</button></div>
          <div class="run-head">
            <div style="min-width:0">
              <h2 class="id" id="rd-id"></h2>
              <p class="task" id="rd-task"></p>
            </div>
            <span class="badge" id="rd-badge"></span>
          </div>
          <div class="run-meta">
            <div class="rm"><span class="k">Started</span><span class="v" id="rd-started">—</span></div>
            <div class="rm"><span class="k">Duration</span><span class="v" id="rd-duration">—</span></div>
            <div class="rm"><span class="k">Events</span><span class="v" id="rd-events">—</span></div>
            <div class="rm"><span class="k">Attempts</span><span class="v" id="rd-attempts">—</span></div>
            <div class="rm"><span class="k">Files selected</span><span class="v" id="rd-files">—</span></div>
            <div class="rm"><span class="k">Patch</span><span class="v mono" id="rd-diffstat">—</span></div>
          </div>

          <div class="panel">
            <div class="ph"><h2>Trace timeline</h2><span class="meta" id="tl-meta"></span></div>
            <div class="timeline" id="timeline"></div>
          </div>

          <div class="grid2">
            <div class="panel">
              <div class="ph"><h2>Selected files</h2><span class="meta" id="sf-meta"></span></div>
              <div class="pb" id="selected"></div>
            </div>
            <div class="panel">
              <div class="ph"><h2>Repair attempts</h2><span class="meta" id="at-meta"></span></div>
              <div class="pb" id="attempts"></div>
            </div>
          </div>

          <div class="panel">
            <div class="ph"><h2>Final report</h2></div>
            <div class="pb"><pre id="report"></pre></div>
          </div>

          <div class="panel" id="benchmark-panel">
            <div class="ph"><h2>Benchmark</h2></div>
            <div class="pb"><pre id="benchmark"></pre></div>
          </div>

          <div class="panel">
            <div class="ph"><h2>Patch</h2><span class="meta" id="patch-meta"></span></div>
            <div id="patch"></div>
          </div>
        </div>

      </div>
    </section>
  </main>

  <script>
    'use strict';
    let runs = [];
    let activeRunId = '';

    const STATUS = {
      ok:      { label: 'Success',   shade: '#161616' },
      blocked: { label: 'Escalated', shade: '#6f6f6f' },
      failed:  { label: 'Failed',    shade: '#b3b3b3' },
      pending: { label: 'Pending',   shade: '#e2e2e2' },
    };

    function statusKey(status) {
      const s = String(status || '').toUpperCase();
      if (s.includes('SUCCESS')) return 'ok';
      if (s.includes('FAILED')) return 'failed';
      if (s.includes('ESCALATED') || s.includes('BLOCKED')) return 'blocked';
      return 'pending';
    }

    // Monochrome status glyphs: identity by shape, never by color.
    function glyph(key) {
      const shapes = {
        ok:      '<circle cx="5" cy="5" r="4.4" fill="#111"/>',
        failed:  '<path d="M1.8 1.8 L8.2 8.2 M8.2 1.8 L1.8 8.2" stroke="#111" stroke-width="1.7" stroke-linecap="round"/>',
        blocked: '<circle cx="5" cy="5" r="4" fill="none" stroke="#111" stroke-width="1.3"/><path d="M5 1 A4 4 0 0 1 5 9 Z" fill="#111"/>',
        pending: '<circle cx="5" cy="5" r="3.9" fill="none" stroke="#a3a3a3" stroke-width="1.5"/>',
      };
      return '<svg class="glyph" viewBox="0 0 10 10" aria-hidden="true">' + (shapes[key] || shapes.pending) + '</svg>';
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }

    function parseTs(value) {
      const d = new Date(String(value || ''));
      return isNaN(d.getTime()) ? null : d;
    }
    function fmtClock(d) {
      return d ? d.toLocaleTimeString('en-GB', { hour12: false }) : '—';
    }
    function fmtDate(d) {
      if (!d) return '—';
      return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) + ', ' + fmtClock(d);
    }
    function fmtDur(ms) {
      if (ms == null || isNaN(ms) || ms < 0) return '—';
      if (ms < 1000) return ms + 'ms';
      const s = ms / 1000;
      if (s < 60) return s.toFixed(1) + 's';
      const m = Math.floor(s / 60);
      if (m < 60) return m + 'm ' + Math.round(s % 60) + 's';
      return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
    }
    function fmtRel(d) {
      if (!d) return '';
      const diff = Date.now() - d.getTime();
      if (diff < 60000) return 'just now';
      const min = Math.floor(diff / 60000);
      if (min < 60) return min + 'm ago';
      const h = Math.floor(min / 60);
      if (h < 24) return h + 'h ago';
      const days = Math.floor(h / 24);
      if (days < 14) return days + 'd ago';
      return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
    }
    function runDuration(run) {
      const a = parseTs(run.started_at), b = parseTs(run.updated_at);
      return (a && b) ? fmtDur(b - a) : '—';
    }

    /* ---------- data loading ---------- */

    async function refresh() {
      await fetchRuns();
      if (activeRunId) await loadRun(activeRunId, { silent: true });
    }

    async function fetchRuns() {
      const box = document.getElementById('runs');
      try {
        const res = await fetch('/api/runs');
        if (!res.ok) throw new Error('Unable to load runs.');
        runs = await res.json();
        document.getElementById('stamp').textContent =
          'updated ' + new Date().toLocaleTimeString('en-GB', { hour12: false });
      } catch (err) {
        box.innerHTML = '<span class="empty">' + escapeHtml(err.message || 'Unable to load runs.') + '</span>';
        return;
      }
      renderRunList();
      renderOverview();
    }

    function renderRunList() {
      const box = document.getElementById('runs');
      document.getElementById('run-count').textContent = String(runs.length);
      if (!runs.length) {
        box.innerHTML = '<span class="empty">No runs yet.</span>';
        return;
      }
      box.innerHTML = runs.map(run => {
        const id = String(run.run_id || '');
        const key = statusKey(run.status);
        const when = fmtRel(parseTs(run.started_at));
        return '<button class="run-item' + (id === activeRunId ? ' active' : '') + '"' +
          ' data-run-id="' + escapeHtml(id) + '" title="' + escapeHtml(id) + '">' +
          '<span class="r1">' + glyph(key) +
            '<span class="task">' + escapeHtml(String(run.task_id || 'Unknown task')) + '</span></span>' +
          '<span class="r2"><span class="rid">' + escapeHtml(id) + '</span>' +
            '<span class="rwhen">' + escapeHtml(when) + '</span></span>' +
          '</button>';
      }).join('');
      box.querySelectorAll('.run-item').forEach(el => {
        el.addEventListener('click', () => { location.hash = encodeURIComponent(el.dataset.runId || ''); });
      });
    }

    /* ---------- overview ---------- */

    function renderOverview() {
      const counts = { ok: 0, blocked: 0, failed: 0, pending: 0 };
      runs.forEach(run => { counts[statusKey(run.status)] += 1; });
      const total = runs.length;
      const finished = counts.ok + counts.failed + counts.blocked;

      document.getElementById('ov-total').textContent = String(total);
      document.getElementById('ov-total-note').textContent = finished + ' finished';
      document.getElementById('ov-rate').textContent =
        finished ? Math.round((counts.ok / finished) * 100) + '%' : '—';
      document.getElementById('ov-rate-note').textContent =
        finished ? counts.ok + ' of ' + finished + ' finished runs' : 'no finished runs';
      document.getElementById('ov-attn').textContent = String(counts.failed + counts.blocked);

      const last = runs.length ? parseTs(runs[0].started_at) : null;
      document.getElementById('ov-last').textContent = last ? fmtRel(last) : '—';
      document.getElementById('ov-last-note').textContent = last ? fmtDate(last) : 'no runs yet';

      const dist = document.getElementById('ov-dist');
      const legend = document.getElementById('ov-legend');
      const order = ['ok', 'blocked', 'failed', 'pending'];
      if (!total) {
        dist.innerHTML = '<span style="flex:1;background:var(--fill-soft)"></span>';
        legend.innerHTML = '<span class="empty">No data yet.</span>';
      } else {
        dist.innerHTML = order.filter(k => counts[k] > 0).map(k =>
          '<span style="flex:' + counts[k] + ';background:' + STATUS[k].shade + '" title="' +
          STATUS[k].label + ': ' + counts[k] + '"></span>').join('');
        legend.innerHTML = order.map(k =>
          '<span class="dl-item">' + glyph(k) + STATUS[k].label +
          ' <span class="n">' + counts[k] + '</span></span>').join('');
      }
      document.getElementById('ov-dist-meta').textContent = total ? total + ' runs' : '';

      const rows = document.getElementById('ov-rows');
      document.getElementById('ov-empty').classList.toggle('hidden', total > 0);
      document.getElementById('ov-table-meta').textContent = total ? 'newest first' : '';
      rows.innerHTML = runs.map(run => {
        const id = String(run.run_id || '');
        const key = statusKey(run.status);
        return '<tr class="rowlink" data-run-id="' + escapeHtml(id) + '">' +
          '<td style="white-space:nowrap">' + glyph(key) + ' ' + escapeHtml(STATUS[key].label) + '</td>' +
          '<td class="c-mono">' + escapeHtml(id) + '</td>' +
          '<td class="c-dim">' + escapeHtml(String(run.task_id || '')) + '</td>' +
          '<td class="c-dim c-num">' + escapeHtml(fmtDate(parseTs(run.started_at))) + '</td>' +
          '<td class="c-num c-dim" style="text-align:right">' + escapeHtml(runDuration(run)) + '</td>' +
          '</tr>';
      }).join('');
      rows.querySelectorAll('tr.rowlink').forEach(tr => {
        tr.addEventListener('click', () => { location.hash = encodeURIComponent(tr.dataset.runId || ''); });
      });
    }

    /* ---------- run detail ---------- */

    async function loadRun(id, opts) {
      const res = await fetch('/api/runs/' + encodeURIComponent(id));
      const data = await res.json();
      if (data.error) {
        if (!(opts && opts.silent)) goOverview();
        return;
      }
      activeRunId = id;
      renderRunList();

      const run = data.run || {};
      const events = data.events || [];
      const attempts = data.attempts || [];
      const selected = (data.selected_files || []).map(item => (item && item.path) || item);
      const key = statusKey(run.status);

      document.getElementById('view-overview').classList.add('hidden');
      document.getElementById('view-run').classList.remove('hidden');

      document.getElementById('rd-id').textContent = String(run.run_id || id);
      document.getElementById('rd-task').textContent = String(run.task_id || 'Unknown task');
      const badge = document.getElementById('rd-badge');
      badge.className = 'badge' + (key === 'ok' ? ' b-ok' : '');
      badge.innerHTML = (key === 'ok' ? '' : glyph(key) + ' ') + escapeHtml(String(run.status || 'PENDING'));

      document.getElementById('rd-started').textContent = fmtDate(parseTs(run.started_at));
      document.getElementById('rd-duration').textContent = runDuration(run);
      document.getElementById('rd-events').textContent = String(events.length);
      document.getElementById('rd-attempts').textContent = String(attempts.length || '0');
      document.getElementById('rd-files').textContent = String(selected.length);

      const diff = parseDiff(data.patch || '');
      document.getElementById('rd-diffstat').textContent = diff.files.length
        ? diff.files.length + ' file' + (diff.files.length === 1 ? '' : 's') + '  +' + diff.adds + '  \\u2212' + diff.dels
        : 'none';

      renderTimeline(events);
      renderSelected(selected);
      renderAttempts(attempts);
      renderPre('report', data.report, 'No report was produced for this run.');
      const bench = String(data.benchmark || '').trim();
      document.getElementById('benchmark-panel').classList.toggle('hidden', !bench);
      if (bench) renderPre('benchmark', bench, '');
      renderPatch(diff);
    }

    function renderTimeline(events) {
      const box = document.getElementById('timeline');
      document.getElementById('tl-meta').textContent =
        events.length ? events.length + ' events' : '';
      if (!events.length) {
        box.innerHTML = '<div class="pb"><span class="empty">No events recorded.</span></div>';
        return;
      }
      const t0 = parseTs(events[0].timestamp);
      let prevState = null;
      box.innerHTML = events.map(e => {
        const t = parseTs(e.timestamp);
        const state = String(e.state || '');
        const changed = state && state !== prevState;
        if (state) prevState = state;
        const elapsed = (t && t0) ? '+' + fmtDur(t - t0) : '';
        return '<div class="tl-row' + (changed ? ' tl-state-change' : '') + '">' +
          '<span class="tl-rail"><i></i></span>' +
          '<span class="tl-time">' + escapeHtml(fmtClock(t)) + '</span>' +
          '<span class="tl-elapsed">' + escapeHtml(elapsed) + '</span>' +
          '<span class="tl-state' + (changed ? '' : ' cont') + '">' + escapeHtml(changed ? state : '·') + '</span>' +
          '<span class="tl-kind-msg">' +
            '<span class="tl-kind">' + escapeHtml(String(e.kind || '')) + '</span>' +
            '<span class="tl-msg">' + escapeHtml(String(e.message || '')) + '</span>' +
          '</span></div>';
      }).join('');
    }

    function renderSelected(selected) {
      document.getElementById('sf-meta').textContent = selected.length ? String(selected.length) : '';
      document.getElementById('selected').innerHTML = selected.length
        ? '<ul class="plain">' + selected.map(f =>
            '<li title="' + escapeHtml(String(f)) + '">' + escapeHtml(String(f)) + '</li>').join('') + '</ul>'
        : '<span class="empty">No files were selected.</span>';
    }

    function renderAttempts(attempts) {
      document.getElementById('at-meta').textContent = attempts.length ? String(attempts.length) : '';
      document.getElementById('attempts').innerHTML = attempts.length
        ? attempts.map(a =>
            '<div class="attempt"><span class="no">#' + escapeHtml(String(a.attempt)) + '</span>' +
            '<span class="res">' + escapeHtml(String(a.result || '')) + '</span></div>').join('')
        : '<span class="empty">No repair attempts.</span>';
    }

    function renderPre(id, text, emptyMsg) {
      const el = document.getElementById(id);
      if (!String(text || '').trim()) {
        el.innerHTML = '<span class="empty">' + escapeHtml(emptyMsg) + '</span>';
      } else {
        el.textContent = text;
      }
    }

    function parseDiff(patch) {
      const files = [];
      let current = null, adds = 0, dels = 0;
      if (String(patch || '').trim()) {
        String(patch).split('\\n').forEach(line => {
          if (line.startsWith('diff ')) {
            const m = line.split(' b/');
            current = { name: m.length > 1 ? m[m.length - 1] : line, adds: 0, dels: 0, lines: [] };
            files.push(current);
            return;
          }
          if (!current) {
            current = { name: 'patch', adds: 0, dels: 0, lines: [] };
            files.push(current);
          }
          if (current.name === 'patch' && line.startsWith('+++ ')) {
            current.name = line.slice(4).replace(/^b\\//, '');
          }
          let type = 'ctx';
          if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('index ')) type = 'meta';
          else if (line.startsWith('@@')) type = 'hunk';
          else if (line.startsWith('+')) { type = 'add'; current.adds += 1; adds += 1; }
          else if (line.startsWith('-')) { type = 'del'; current.dels += 1; dels += 1; }
          current.lines.push({ type: type, text: line });
        });
      }
      return { files: files, adds: adds, dels: dels };
    }

    function renderPatch(diff) {
      const box = document.getElementById('patch');
      document.getElementById('patch-meta').textContent = diff.files.length
        ? '+' + diff.adds + ' \\u2212' + diff.dels : '';
      if (!diff.files.length) {
        box.innerHTML = '<div class="pb"><span class="empty">No patch was produced.</span></div>';
        return;
      }
      box.innerHTML = diff.files.map(f =>
        '<div class="diff-file">' +
          '<div class="diff-file-head"><span class="fname">' + escapeHtml(f.name) + '</span>' +
          '<span class="fstat">+' + f.adds + ' \\u2212' + f.dels + '</span></div>' +
          '<div class="diff-body">' + f.lines.map(l => {
            const g = l.type === 'add' ? '+' : l.type === 'del' ? '\\u2212' : '';
            const body = l.type === 'add' || l.type === 'del' ? l.text.slice(1) : l.text;
            return '<div class="dl ' + l.type + '"><span class="g">' + g + '</span>' +
              '<span class="t">' + (escapeHtml(body) || ' ') + '</span></div>';
          }).join('') + '</div>' +
        '</div>').join('');
    }

    /* ---------- new run ---------- */

    async function runTask() {
      const btn = document.getElementById('run-btn');
      const status = document.getElementById('run-status');
      btn.disabled = true;
      btn.textContent = 'Running\\u2026';
      status.textContent = 'Run in progress\\u2026';
      try {
        const res = await fetch('/api/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            task: document.getElementById('task').value,
            sandbox: document.getElementById('sandbox').value,
          }),
        });
        const data = await res.json();
        status.textContent = data.error ? 'Error: ' + data.error : (data.status || 'Done');
        await fetchRuns();
        if (data.run_id) location.hash = encodeURIComponent(data.run_id);
      } catch (err) {
        status.textContent = 'Error: ' + (err.message || err);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Run fixture';
      }
    }

    /* ---------- routing ---------- */

    function goOverview() {
      if (location.hash) {
        history.pushState(null, '', location.pathname);
      }
      showOverview();
    }

    function showOverview() {
      activeRunId = '';
      document.getElementById('view-run').classList.add('hidden');
      document.getElementById('view-overview').classList.remove('hidden');
      renderRunList();
      renderOverview();
    }

    function route() {
      const id = decodeURIComponent(location.hash.slice(1));
      if (id) loadRun(id);
      else showOverview();
    }

    window.addEventListener('hashchange', route);
    window.addEventListener('popstate', route);

    (async function init() {
      await fetchRuns();
      route();
    })();
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
