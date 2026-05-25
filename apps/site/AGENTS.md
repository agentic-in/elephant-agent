# Site App

This surface owns the public website and release-facing web content.

## Own Here

- landing pages
- synced product-facing docs pages
- brand assets and favicon
- any future docs shell or release-facing web writing that still belongs to this public site

## Current Shell Surfaces

- `src/pages/`
  - public landing page only; docs route through the native Docusaurus content plugin
- `src/components/`
  - homepage interaction logic and any future shared content-only helpers
- `src/css/`
  - homepage presentation plus native Docusaurus theme-layer styling
- `docs/`, `sidebars.ts`
  - native Docusaurus docs surface and sidebar contract
- `scripts/sync-install-script.mjs`
  - sync/check step that mirrors the public root installer into static site output
- `scripts/sync-skillhub-content.mjs`
  - sync/check step that projects the canonical packaged skill catalog into generated docs and pages
- `scripts/patch-docusaurus-bundler.mjs`
  - local install/build patch for the upstream webpack progress-plugin incompatibility in this Docusaurus stack
- `static/assets/brand/`
  - deployable logo, favicon, and other static brand assets
- `package.json`, `docusaurus.config.ts`, `tsconfig.json`
  - Docusaurus framework and site build contract
- `dist/`
  - generated publish output; do not edit directly

## Implementation Rules

- keep the site static and self-contained until the runtime surface exists
- keep docs on standard Docusaurus layout primitives whenever possible
- preserve the homepage visual identity without re-implementing a second docs shell
- keep operator console concerns out of this app
- keep the Docusaurus app static-first; do not turn it into a runtime-driven app
- keep repo root `install.sh` as the public website installer source and treat
  `apps/site/static/install.sh` as generated build input
- keep SkillHub docs and route pages generated from `packages.skills.site_projection`;
  use `npm run sync:content` to update them and `npm run check:content` to
  verify drift
- keep public docs focused on the supported operator path, not internal design archives
- keep links and copy aligned with repo-native README positioning and design docs

## Do Not Own Here

- operator secrets
- runtime-only API logic
- hidden cognition behavior

Keep the public site cleanly separate from any future operator console.
