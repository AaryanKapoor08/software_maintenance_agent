# Command Policy

PatchPilot runs project commands through a command policy before execution.

Allowed command families:

- Read/search: `git status`, `git diff`, `rg`, `find`, `ls`, `cat`
- Python fixture/test commands: `python -m pytest`, `python -m compileall`, `pytest`
- Common package/test commands, only after project inspection: `npm test`, `npm run test`, `npm run lint`, `npm run typecheck`, `ruff check`, `mypy`

Blocked command patterns:

- Destructive filesystem commands such as `rm -rf`, `del /s`, `rmdir /s`, `Remove-Item -Recurse`
- Privilege escalation such as `sudo`
- Deployment/cloud commands
- Secret reads such as `.env`, private keys, and credential files
- Commands that touch parent directories outside the sandbox repository

Policy failures are recorded in the trace and final report.
