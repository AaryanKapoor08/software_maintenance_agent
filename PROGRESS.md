# Software Maintenance Agent Progress

Last updated: 2026-05-16

## Status

| Area | Status | Notes |
|---|---|---|
| CLI and schemas | Complete | Typer commands, Pydantic contracts, settings, and redaction utilities are in place. |
| Sandbox and policy | Complete | Trusted local fixture sandbox, blocked command checks, and path confinement are implemented. |
| Retrieval | Complete | Lexical, hashed embedding, hybrid RRF, and Code-JEPA reranking paths are benchmarked. |
| Patch loop | Complete | The fixture run reproduces the failure, patches the sandbox copy, reruns tests, and writes a report. |
| Repair loop | Complete | The repair fixture forces a bad first patch and recovers on a later attempt. |
| GitHub path | Partial | Issue URL parsing and public issue fetch are implemented; draft PR creation still needs token-backed proof. |
| Dashboard | Complete | The local browser dashboard lists runs and loads reports, patches, attempts, and trace events. |

## Current Verification

- `python -m pytest -q` passes.
- `python -m ruff check .` passes.
- `python -m compileall src tests examples` passes.
- `python -m software_maintaince_agent.cli --help` renders the CLI.
- `python -m software_maintaince_agent.cli benchmark --suite benchmark/suites/mvp.json` passes.
- `python -m software_maintaince_agent.cli run --task examples/tasks/python_email_empty.json --sandbox local` passes.
- Running pytest directly inside `examples/fixtures/python_email_validator` fails by design before the agent patch; that fixture is the reproduction target.

## Generated Artifacts

Runtime output is written under `runs/` and ignored by git. Keep committed files limited to source, tests, docs, configs, benchmark definitions, task metadata, and prompt templates.

## Next Proof

Use a controlled GitHub test repository with `GITHUB_TOKEN` and E2B credentials to prove remote issue ingestion, isolated clone, branch push, and draft PR creation.
