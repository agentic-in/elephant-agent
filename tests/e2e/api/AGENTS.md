# API E2E Tests

Use this directory for API-level runtime flows.

Good targets:

- elephant, Episode, Loop, and Step flows
- kernel-backed turn execution through the API surface
- controlled execution with registered tools
- internal dashboard, operator controls, and console projection flows in
  `test_api_surface_dashboard.py`
- dashboard gateway, MCP, skill shelf, and operator discovery flows in
  `test_api_surface_dashboard_ops.py`
- provider onboarding, default provider, and provider transport flows in
  `test_api_surface_providers.py`

Shared app fixtures and provider stubs belong in `api_surface_test_base.py`.

Keep these tests focused on surface behavior. They should exercise the API
app, not reimplement kernel or package logic.
