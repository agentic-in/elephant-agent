# Gateway E2E Tests

Use this directory for adapter-level routing and delivery coverage.

## Own Here

- identity mapping
- conversation/thread to elephant-State binding
- command-driven elephant switching
- outbound delivery formatting
- adapter bootstrap behavior

## Do Not Own Here

- kernel lifecycle policy
- model provider behavior
- storage internals

## Validation

- Use `make test-gateway-e2e-smoke` for a fast cross-adapter route/control
  smoke before running the full gateway e2e suite.
- Use the focused `tests.e2e.gateway.test_gateway_adapter_*` module for the
  adapter or route family you changed.
- Use `make test-e2e` when suite wiring changes or coverage moves between
  gateway e2e modules.
