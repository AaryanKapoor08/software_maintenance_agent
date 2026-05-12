# PatchPilot Build Plan

PatchPilot turns failing CI and bounded maintenance issues into small, tested, reviewable draft-PR-ready patches with execution traces, risk scoring, rollback notes, and benchmarked retrieval.

## Operating Rules

- Secrets are loaded only from environment variables and are redacted from traces, reports, and test output.
- Untrusted repositories must run in a sandbox. The local sandbox is allowed only for trusted fixture repositories.
- Unsafe commands and blocked paths stop the run before code execution or patch application.
- The agent continues nonblocked work when optional services such as E2B, GitHub PR creation, or external CI are unavailable.
- Baseline retrieval remains in the critical path. Code-JEPA V1 is measured as a retrieval/reranking layer and reported honestly.

## Gates

| Gate | Acceptance Criteria | Verification |
|---|---|---|
| G0 Control plane | `BUILD_PLAN.md`, `PROGRESS.md`, env template, command policy, acceptance criteria | Review files |
| G1 CLI and schemas | Typer CLI, Pydantic contracts, provider abstraction, redaction utilities | `python -m pytest tests/test_schemas_and_redaction.py`; `ama run --task examples/tasks/python_email_empty.json --dry-run` |
| G2 Sandbox and command policy | Local trusted sandbox, E2B blocker path, allow/block policy, path confinement, traced commands | `python -m pytest tests/test_command_policy.py tests/test_sandbox.py` |
| G3 Fixture repos | Python fixture with failing test and task metadata | `cd examples/fixtures/python_email_validator && python -m pytest` fails before agent patch |
| G4 Retrieval baseline | Repo inspection, test detection, lexical/BM25-style retrieval, stack trace/file heuristics | `python -m pytest tests/test_repo_and_retrieval.py`; benchmark top-k metrics |
| G5 First patch loop | Failure reproduced, relevant files selected, patch applied, focused tests pass, report written | `ama run --task examples/tasks/python_email_empty.json --sandbox local` |
| G6 Repair loop | Failure logs summarized, attempt limits and repeated-failure stop conditions, failed-run report | `python -m pytest tests/test_agent_loop.py` |
| G7 Code-JEPA V1 | Latent retrieval predictor, local artifact storage, comparison with baseline retrieval | `ama benchmark --suite benchmark/suites/mvp.json` |
| G8 GitHub path | Issue URL parser, GitHub issue fetch, local PR report fallback, optional draft PR path | `python -m pytest tests/test_github.py` |
| G9 Trace viewer | CLI trace viewer shows status, events, selected files, diff, tests, risk, final report | `ama trace --run-id <run_id>` |
| G10 Portfolio polish | README, demo command, successful report, benchmark output | `python -m pytest`; demo commands below |

## Fallback Paths

- Missing `GEMINI_API_KEY`: use deterministic local patch planning for trusted fixtures and record an LLM-provider blocker.
- Missing `E2B_API_KEY`: use local trusted fixture sandbox and record E2B as manual proof.
- Missing `GITHUB_TOKEN`: fetch public issues without auth when possible and generate a local PR markdown report plus patch file.
- External network unavailable: run local tasks, local fixtures, and benchmark suite.
- Lint/typecheck unavailable: record blocker in trace and final report, then continue tests.

## Verification Commands

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m patchpilot.cli run --task examples/tasks/python_email_empty.json --sandbox local
python -m patchpilot.cli benchmark --suite benchmark/suites/mvp.json
python -m patchpilot.cli dashboard --port 8765
```

## Minimum Product Proof

- One command runs a fixture task end to end.
- The failure is reproduced before patching.
- A patch is generated and applied inside the sandbox copy.
- Focused tests pass after the patch.
- Final report includes summary, issue understanding, changed files, tests run, risk level, rollback plan, known limitations, and trace.
- Failed runs still produce useful reports.
- Secrets are redacted in traces.
- Unsafe commands are blocked.
- Code-JEPA V1 exists and is benchmarked against baseline retrieval.
