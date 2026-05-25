# Reflect App

This app is now a compatibility facade for background reflection imports.
Canonical reflection runner, evidence, prompt, compression, and feature logic
lives under `packages.reflect`.

## Own Here

- compatibility aliases for legacy `apps.reflect.*` import paths
- app-level wiring only when a future reflect executable surface is added

## Do Not Own Here

- durable Personal Model schema
- storage repository internals
- CLI or dashboard rendering
- kernel turn execution
- reflection runner, evidence, prompt, compression, or feature logic

Keep this facade thin. New shared reflection behavior belongs in
`packages.reflect`, with app aliases preserved only for compatibility.
