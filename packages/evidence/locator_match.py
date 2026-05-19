"""Fuzzy locator matching shared by CLI / API / Gateway recall tools.

## Why this module exists

All three surfaces (`apps/cli/runtime_records.py`, `apps/api/tool_surfaces.py`,
`apps/gateway/runtime_capabilities.py`) implemented the same four-step
matching pipeline for recall delete/correct commands,
etc.:

  1. lowercase-strip the locator,
  2. look for an exact content equality,
  3. look for a single substring match,
  4. fall back to the most recent of multiple substring hits.

The three copies drifted subtly (one would return None on ambiguity, another
picked the latest) and none of them handled:

  * CJK text where the user asks "我想删关于缓存的那条" but the entry is
    stored in different Unicode normal form,
  * locator vs content case drift beyond basic ASCII (e.g. Turkish "i"),
  * approximate matches — if the user remembers "Redis 缓存" but the
    stored content uses "redis cache", substring fails and the user
    is stuck.

This module hosts one implementation, adds Unicode NFKC normalisation, and
exposes an optional embedding-similarity fallback for the truly fuzzy
case. The callers should delete their local copies and invoke
`find_entry_by_locator(entries, locator, embedding_service=...)` directly.

## Matching precedence (unchanged order)

The public API preserves the historic semantics so no surface sees a
behaviour change on its happy path:

  exact(casefold+NFKC) > unique substring > most-recent substring > None

When `embedding_service` is supplied and the above four fail, we add one
more tier: cosine similarity over the query vs per-entry content vectors,
returning the best hit above a threshold (0.80 default). This is
opt-in because computing per-entry embeddings every call is expensive
and only useful when the user's locator drifts far from stored text.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any
import unicodedata


__all__ = [
    "find_entry_by_locator",
    "normalize_locator",
]


def normalize_locator(text: str) -> str:
    """Case-fold + NFKC normalise a locator string.

    NFKC collapses width variants (e.g. full-width ASCII vs half-width)
    and composed / decomposed CJK forms, so "缓存" typed on two
    different IMEs matches one entry. `casefold` handles non-ASCII
    case pairs (Turkish dotted/dotless i, German eszett, etc.).
    """
    return unicodedata.normalize("NFKC", str(text or "")).strip().casefold()


def _entry_content(entry: Any) -> str:
    return str(getattr(entry, "content", "") or "")


def _entry_updated_key(entry: Any):
    # Sort by updated_at if present, otherwise created_at, otherwise
    # zero — most-recent-first tiebreak.
    return getattr(entry, "updated_at", None) or getattr(entry, "created_at", None)


def find_entry_by_locator(
    entries: Iterable[Any],
    locator: str,
    *,
    embedding_service: Any = None,
    embedding_threshold: float = 0.80,
) -> Any | None:
    """Find one recall entry by fuzzy locator match.

    Semantics (same as pre-refactor, plus NFKC):
      1. `normalize_locator(content) == normalize_locator(locator)` —
         unambiguous exact match wins.
      2. Single substring hit where `locator` appears inside entry
         content (both normalised) wins.
      3. Multiple substring hits — return the most-recent-updated
         entry (stable fallback; callers may refine).
      4. If `embedding_service` is supplied and no lexical match
         succeeded, cosine-similarity score every candidate and pick
         the top one above `embedding_threshold`. When the service is
         missing / throws / returns None, silently skip this tier.
      5. Return `None` when nothing matches — the tool surface turns
         this into a human-readable "no match, please refine" error.

    Callers are responsible for pre-filtering `entries` by status
    (`"active"` / `"committed"`). We accept any iterable to avoid
    needing a shared protocol.
    """
    needle = normalize_locator(locator)
    if not needle:
        return None

    materialised = tuple(entries or ())
    if not materialised:
        return None

    # Tier 1: exact normalised equality.
    exact = [entry for entry in materialised if normalize_locator(_entry_content(entry)) == needle]
    if len(exact) == 1:
        return exact[0]
    if exact:
        # Ambiguous exact matches — prefer the most recent so the user
        # sees the "live" version and can refine if needed.
        return _pick_most_recent(exact)

    # Tier 2 + 3: substring.
    substring = [entry for entry in materialised if needle in normalize_locator(_entry_content(entry))]
    if len(substring) == 1:
        return substring[0]
    if substring:
        return _pick_most_recent(substring)

    # Tier 4: embedding similarity.
    if embedding_service is not None:
        hit = _embedding_best_match(
            entries=materialised,
            locator=locator,
            embedding_service=embedding_service,
            threshold=embedding_threshold,
        )
        if hit is not None:
            return hit

    return None


def _pick_most_recent(entries: Sequence[Any]) -> Any:
    return sorted(entries, key=_entry_updated_key, reverse=True)[0]


def _embedding_best_match(
    *,
    entries: Sequence[Any],
    locator: str,
    embedding_service: Any,
    threshold: float,
) -> Any | None:
    """Rank entries by cosine similarity vs the locator vector.

    The embedding service contract is lenient: we try `embed_text` and
    fall back to `embed` if present, swallow any error, and return
    None on failure — fuzzy matching is a bonus tier, never a
    correctness requirement.
    """
    try:
        locator_vec = _embed_one(embedding_service, locator)
    except Exception:
        return None
    if locator_vec is None:
        return None

    best: Any | None = None
    best_score = float(threshold)
    for entry in entries:
        text = _entry_content(entry).strip()
        if not text:
            continue
        try:
            entry_vec = _embed_one(embedding_service, text)
        except Exception:
            continue
        if entry_vec is None:
            continue
        score = _cosine(locator_vec, entry_vec)
        if score is None:
            continue
        if score > best_score:
            best_score = score
            best = entry
    return best


def _embed_one(embedding_service: Any, text: str) -> tuple[float, ...] | None:
    """Call the embedding service with the safest interface available."""
    for attr in ("embed_text", "embed"):
        func = getattr(embedding_service, attr, None)
        if not callable(func):
            continue
        try:
            result = func(text)
        except TypeError:
            # Some services require kwargs.
            try:
                result = func(text=text)
            except Exception:
                continue
        except Exception:
            continue
        # Unpack common return shapes.
        values = getattr(result, "values", None)
        if values is None and isinstance(result, (list, tuple)):
            values = tuple(float(v) for v in result)
        elif values is not None:
            values = tuple(float(v) for v in values)
        if values:
            return values
    return None


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return None
    return dot / ((na**0.5) * (nb**0.5))
