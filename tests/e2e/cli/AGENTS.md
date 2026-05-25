# CLI E2E Tests

Use this directory for app-level proving-surface flows.

Good targets:

- elephant create, list, use, current, and delete
- wake and continue through State, Episode, Loop, and Step
- inspect memory and runtime summaries without exposing State as primary user management
- skills, tools, providers, and models management

Shared CLI process fixtures, provider stubs, TTY runners, and terminal
rendering helpers belong in `cli_surface_test_base.py`. Keep split modules
focused by user-facing command family so `make test-e2e` can preserve the full
CLI proving surface without growing one large file again.
