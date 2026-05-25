# Packages

Shared runtime modules and capability contracts live here.

Current modules:

- `auth/`
- `capabilities/`
- `context/`
- `continuity/`
- `contracts/`
- `cron/`
- `curiosity/`
- `embeddings/`
- `evidence/`
- `experience/`
- `gateway_core/`
- `growth/`
- `harness/`
- `kernel/`
- `models/`
- `observability/`
- `operator/`
- `reflect/`
- `security/`
- `semantic_index/`
- `skills/`
- `state/`
- `storage/`
- `telemetry/`
- `tools/`
- `understanding/`

Working rules:

- package boundaries should stay narrower than app boundaries
- prefer contract-first integration over deep imports
- add local `AGENTS.md` files when a package becomes a hotspot with non-obvious rules
