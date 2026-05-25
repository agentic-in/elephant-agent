# Gateway Core Package

This package owns delivery-agnostic messaging logic.

## Own Here

- identity mapping
- conversation/thread to elephant-State binding rules
- attachment normalization
- delivery fan-out
- interruption semantics for messaging surfaces
- command-driven elephant switching
- delivery-agnostic proactive ask decision and enqueue evaluation
- cron execution visibility policy before app-specific delivery

Keep platform adapters thin by pushing reusable logic here.
