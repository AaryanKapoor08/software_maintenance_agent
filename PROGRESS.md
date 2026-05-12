# software_maintaince agent Progress

Last updated: 2026-05-12

## Gate Tracker

| Gate | Status | Proof |
|---|---|---|
| G0 Control plane | Complete | `BUILD_PLAN.md`, `PROGRESS.md`, `.env.example`, `.gitignore`, `docs/COMMAND_POLICY.md` |
| G1 CLI and schemas | Complete | Typer CLI, Pydantic contracts, provider abstraction, redaction utilities, dry-run path |
| G2 Sandbox and command policy | Complete | Trusted local fixture sandbox, E2B blocker path, command allow/block policy, path confinement, traced stdout/stderr |
| G3 Fixture repos | Complete | `examples/fixtures/python_email_validator` fails before patching |
| G4 Retrieval baseline | Complete | Repo inspection, test detection, lexical retrieval, stable hash embedding retrieval, hybrid RRF, top-k metrics |
| G5 First patch loop | Complete | `python_email_empty` fixture fixed end to end with focused and broad tests passing |
| G6 Repair loop | Complete | `python_email_repair` forces a bad first patch, then recovers on attempt 2 |
| G7 Code-JEPA V1 | Complete | Code-JEPA V1 artifact and benchmark comparison against keyword and embedding retrieval |
| G8 GitHub path | Partial/manual | GitHub issue URL parser and public issue fetch path implemented; draft PR creation remains gated by token/controlled repo |
| G9 Trace viewer | Complete | CLI trace viewer plus local browser dashboard for runs, selected files, attempts, reports, patches, and events |
| G10 Portfolio polish | Complete for MVP | README, demo commands, reports, benchmark output, safety docs |

## Files Changed

- `.env.example`
- `.gitignore`
- `BUILD_PLAN.md`
- `PROGRESS.md`
- `README.md`
- `benchmark/suites/mvp.json`
- `configs/safety.yml`
- `docs/COMMAND_POLICY.md`
- `examples/fixtures/python_email_validator/**`
- `examples/tasks/python_email_empty.json`
- `examples/tasks/python_email_repair.json`
- `prompts/issue_triage.md`
- `prompts/file_selection.md`
- `prompts/patch_plan.md`
- `pyproject.toml`
- `src/software_maintaince_agent/**`
- `tests/**`

## Commands Run

- `Get-ChildItem -Force` => pass
- `git status --short --branch` => pass; repo had no commits and `.env.local` was untracked before `.gitignore`
- `rg --files -g '!*.env' -g '!**/.env*'` => no tracked files at start
- `python --version` => pass; Python 3.13.2
- `pip --version` => pass
- `New-Item -ItemType Directory -Force ...` => pass
- `python -m compileall src tests` => pass after report rendering fix
- `python -m pytest` before dependency install => failed; pytest missing
- `python -m pip install -e ".[dev]"` => pass
- `python -m pytest` => pass; 16 tests passed
- `cd examples/fixtures/python_email_validator && python -m pytest` => expected fail; 1 failed, 4 passed before agent patch
- `python -m software_maintaince_agent.cli run --task examples/tasks/python_email_empty.json --sandbox local` => pass
- `python -m software_maintaince_agent.cli run --task examples/tasks/python_email_repair.json --sandbox local` => pass
- `python -m software_maintaince_agent.cli benchmark --suite benchmark/suites/mvp.json` => pass
- `python -m software_maintaince_agent.cli trace --run-id 20260511_213624_fixture_email_empty` => pass
- `python -m software_maintaince_agent.cli run --task examples/tasks/python_email_empty.json --sandbox e2b` => pass; blocked report generated because E2B is not configured
- `python -m ruff check .` => pass
- `python -m software_maintaince_agent.cli dashboard --port 8765` => pass; dashboard server started on `http://127.0.0.1:8765`
- `Invoke-WebRequest http://127.0.0.1:8765/` => pass; HTTP 200
- `Invoke-WebRequest http://127.0.0.1:8765/api/runs` => pass; returned recent run metadata
- `rg -n "AIza|GITHUB_TOKEN=gh|GEMINI_API_KEY=AIza|github_pat_|ghp_" -g '!*.env' -g '!**/.env*' -g '!runs/**' .` => pass; matches are fake test tokens, redaction regexes, and this progress entry
- `git status --short` => pass; implementation files untracked, `.env.local` ignored

## Generated Proof Artifacts

- Successful fixture report: `runs/20260511_214811_fixture_email_empty_127e5521/final_report.md`
- Successful fixture patch: `runs/20260511_214811_fixture_email_empty_127e5521/patch.diff`
- Successful fixture trace: `runs/20260511_214811_fixture_email_empty_127e5521/trace.sqlite`
- Repair-loop report: `runs/20260511_214811_fixture_email_repair_108b4b07/final_report.md`
- Repair-loop patch: `runs/20260511_214811_fixture_email_repair_108b4b07/patch.diff`
- Latest benchmark report: `runs/benchmarks/20260511_214757/benchmark_report.md`
- Latest Code-JEPA artifact: `runs/benchmarks/20260511_214757/jepa_artifacts/code_jepa_v1.json`
- Blocked E2B fallback report: `runs/20260511_213843_fixture_email_empty/final_report.md`

## Benchmark Result

Latest suite: `mvp-fixture-suite`, 2 tasks.

| Method | Top-1 | Top-3 | Top-5 | Context Files | Latency ms |
|---|---:|---:|---:|---:|---:|
| keyword_bm25 | 0.500 | 1.000 | 1.000 | 2.50 | 4 |
| embedding | 0.500 | 1.000 | 1.000 | 4.00 | 2 |
| hybrid_rrf | 0.500 | 1.000 | 1.000 | 2.50 | 6 |
| code_jepa_v1 | 0.500 | 1.000 | 1.000 | 2.50 | 4 |

Code-JEPA V1 status: experimental. It matches the stronger hybrid/keyword path on this small suite but does not beat it yet, so hybrid RRF retrieval remains in the critical path.

## Code Audit Notes

- Fixed nondeterministic embedding retrieval by replacing Python's randomized `hash()` with stable `blake2b` token hashing.
- Added hybrid retrieval with Reciprocal Rank Fusion over lexical and embedding rankings.
- Added HyDE-style maintenance query expansion without an external LLM dependency.
- Fixed repair-loop patch output so `patch.diff` is cumulative from the original sandbox state, not only the last repair step.
- Added UUID suffixes to run IDs to avoid same-second collisions.
- Added browser dashboard and tests for dashboard run listing/loading.

## Blockers And Manual Proof

- The pasted API keys are treated as compromised and were not written, read, echoed, or committed.
- `GEMINI_API_KEY` was not used for live LLM calls; the fixture demo uses deterministic local patching.
- `E2B_API_KEY` was not verified; E2B adapter records a blocker and local sandbox remains restricted to trusted fixtures.
- `GITHUB_TOKEN` was not verified; GitHub draft PR creation remains manual. Local PR-ready reports and patch files are generated.
- The Windows user scripts directory is not on PATH, so `ama` may not resolve in this shell. `python -m software_maintaince_agent.cli ...` works reliably.

## Exact Next Action

Use a controlled GitHub test repository with `GITHUB_TOKEN` and E2B credentials to prove remote issue ingestion, isolated clone, branch push, and draft PR creation.
