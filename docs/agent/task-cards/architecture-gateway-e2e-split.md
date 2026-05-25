# architecture-gateway-e2e-split Gateway E2E Suite Decomposition

## Roadmap Track

[Track B: Hotspot Decomposition](../plans/architecture-scorecard-roadmap.md#track-b-hotspot-decomposition)

## Readiness

Ready after the app-boundary guard lands. This card covers only the largest
gateway e2e suite and shared gateway e2e helpers.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

Gateway test maintainer who can separate adapter-specific behavior from shared
route/control/runtime proofs.

## Suggested Branch

`vsr/architecture-gateway-e2e-split`

## Suggested Worktree

`architecture-gateway-e2e-split`

## Dependencies

- Read `tests/e2e/gateway/AGENTS.md` and `apps/gateway/AGENTS.md`.
- Coordinate with app-boundary work if imports move.

## Write Scope

- Primary: `tests/e2e/gateway/test_gateway_adapter.py` and new
  `tests/e2e/gateway/test_*` suites or helper modules.
- App code changes are out of scope unless a test split exposes a small missing
  helper boundary.

## Deliverables

- Done: add `make test-gateway-e2e-smoke` as a cross-adapter route/control
  smoke target for fast feedback before running the full gateway e2e module.
- Done: extract the shared gateway e2e fixture into
  `tests/e2e/gateway/gateway_adapter_test_base.py`, including route/control
  helper methods reused by Feishu, webhook, and control bridge tests.
- Done: split Telegram identity/thread routing tests into
  `tests/e2e/gateway/test_gateway_adapter_telegram.py`.
- Done: split low-coupling gateway CLI/parser surface tests into
  `tests/e2e/gateway/test_gateway_adapter_cli_surface.py`.
- Done: split Feishu control bridge route/binding tests into
  `tests/e2e/gateway/test_gateway_adapter_feishu_control.py`.
- Done: split Feishu long-connection and async lifecycle tests into
  `tests/e2e/gateway/test_gateway_adapter_feishu_long_connection.py`.
- Done: split Feishu setup CLI/runtime tests into
  `tests/e2e/gateway/test_gateway_adapter_feishu_setup.py`.
- Done: split Feishu event, webhook, and runtime routing tests into
  `tests/e2e/gateway/test_gateway_adapter_feishu_events.py`.
- Done: split Discord setup, runtime, delivery, and SDK dispatch tests into
  `tests/e2e/gateway/test_gateway_adapter_discord.py`.
- Done: split Weixin/WeCom control bridge and same-conversation serialization
  tests into `tests/e2e/gateway/test_gateway_adapter_weixin_wecom.py`.
- Done: split chat-bot identity mapping and webhook delivery tests into
  `tests/e2e/gateway/test_gateway_adapter_chat_webhook.py`.
- Done: split Telegram service dispatch and cross-adapter web-app mounting
  tests into `tests/e2e/gateway/test_gateway_adapter_services.py`.
- Done: register all focused gateway e2e modules in `make test-e2e` so split
  coverage stays in the full e2e contract, not only the smoke target.
- Continue splitting one adapter family or route-control family per branch-sized
  increment.
- Preserve the `make test-e2e` gateway coverage contract.
- Keep shared fixtures explicit rather than hidden behind broad helper magic.

## Validation

- `make agent-report CHANGED_FILES="tests/e2e/gateway/..."`
- `make test-gateway-e2e-smoke` for fast cross-adapter feedback.
- Targeted gateway e2e module(s).
- `make test-e2e` when the split changes suite wiring.
- `make agent-fast-gate`

## Handoff

Remaining sections in `test_gateway_adapter.py` after the current splits:
gateway profile/provider setup, shared setup summary, and gateway chat
runtime/context/PM-update coverage. The mixed gateway suite is now small enough
to serve as the shared core suite; future gateway decomposition should target
large focused suites such as Discord or Feishu long-connection only when a
cohesive sub-family emerges.

## Guardrails

- Test-only refactor unless explicitly scoped otherwise.
- Do not reduce adapter or command-control coverage.
- Keep each new suite focused enough for reviewers to inspect independently.
