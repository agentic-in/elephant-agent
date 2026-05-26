# Paper Drafts

This directory holds outward-facing paper drafts derived from the canonical
system layer model in `../system-design/`.

## Purpose

Keep here:

- system-report drafts
- outward-facing architecture narrative
- paper-specific section structure, abstract, and narrative refinements
- compile-ready LaTeX assets that package the paper as a coherent artifact

Do not keep here:

- repo contributor workflow policy
- implementation-only design notes that still belong in `../system-design/`
- unchecked citation guesses
- temporary execution plans that belong in `../agent/plans/`

## Current Draft

- `main.tex`
  - the primary LaTeX entrypoint for the current Elephant Agent system report
- `Elephant_Agent__Agency_First_Personal_AI.pdf`
  - the generated PDF for the current Agency-First Personal AI paper
- `sections/`
  - section-level paper text for the Personal-Model-first architecture,
    including the agency-first L4 positioning, Claim/Question boundaries,
    step-provenanced recall, background learning, and operator-managed skills as
    downstream capabilities
- `references.bib`
  - bibliography file; add only programmatically verified references
- `assets/`
  - local paper assets, including the lab logo used in the title block

## Source Stack

The current paper draft is grounded in this order:

1. `../system-design/system-layer-model.md`
2. `../system-design/README.md`
3. `../../README.md`
4. `../../apps/site/src/pages/index.tsx`
5. `../../apps/site/blog/2026-04-29-personal-model-first.md`

## Working Rule

Treat `docs/system-design/` as the product-design source of truth and
`docs/paper/` as the outward-facing argument layer built from it. The paper is
not a second source of architecture truth.
