---
name: Web Search
skill_id: web-search
description: Keeps lightweight public-web discovery available for prompts, scheduled jobs, and follow-up research.
version: 1.0.0
source_kind: elephant-builtin
default_enabled: true
include_in_overlay: false
aliases: ["web search", "internet search", "search online"]
keywords: ["web", "search", "internet", "lookup"]
---

# Web Search

Use this built-in skill when a task needs fresh public-web discovery instead of local repo retrieval.

## Core rules

- Search the public web only when the answer depends on external or up-to-date information.
- Prefer targeted queries and trustworthy sources over broad speculative browsing.
- Summarize what the search changed about the answer instead of dumping raw result noise.
