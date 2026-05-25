# architecture-provider-hotspot-split Provider Adapter Hotspot Decomposition

## Roadmap Track

[Track B: Hotspot Decomposition](../plans/architecture-scorecard-roadmap.md#track-b-hotspot-decomposition)

## Readiness

Ready after provider contract tests are identified. This card covers only the
OpenAI-compatible provider adapter hotspot.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

Model-provider maintainer comfortable with request shaping, response parsing,
usage accounting, streaming, and tool-call compatibility.

## Suggested Branch

`vsr/architecture-provider-hotspot-split`

## Suggested Worktree

`architecture-provider-hotspot-split`

## Dependencies

- Read `packages/models/AGENTS.md` and provider-related unit tests.
- Keep live-provider behavior behind existing optional smoke gates.

## Write Scope

- Primary: `packages/models/providers/openai_compatible.py` and new
  `packages/models/providers/openai_compatible_*.py` support modules.
- Tests: `tests/unit/models/**`, provider auth/model integration tests, and
  release/live smoke documentation only when behavior changes.

## Deliverables

- Done: response parsing, usage accounting, streaming delta parsing, embedding
  extraction, and tool-call compatibility are extracted to
  `packages/models/providers/openai_compatible_response_parsing.py`.
- Done: OpenAI-compatible provider integration tests now use
  `tests/integration/models_auth/openai_compatible_provider_test_base.py` and
  focused reasoning, Responses API, and HTTP fallback modules.
- Remaining: extract request shaping and transport planning if the adapter grows
  again.
- Preserve provider public API and error behavior.
- Keep optional live-provider smoke requirements unchanged.

## Validation

- `make agent-report CHANGED_FILES="packages/models/... tests/unit/models/..."`
- Targeted provider tests.
- `make agent-fast-gate`
- Optional `make test-live-provider-smoke` only when maintainer secrets are
  available and live behavior is intentionally touched.

## Handoff

Remaining provider work is request shaping and transport planning only; no
live-smoke behavior was intentionally changed by the parsing extraction or test
suite split.

## Guardrails

- Behavior-preserving refactor only unless a separate task card says otherwise.
- Do not log or persist provider secrets.
- Do not change tool-call compatibility without tests.
