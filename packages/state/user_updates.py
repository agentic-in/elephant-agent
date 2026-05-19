"""Canonical user-profile update helpers.

These helpers keep runtime mutations owner-first. Runtime updates mutate
`RenderedUserProfileView` first and only render text afterward.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from packages.state.rendered_views import RenderedUserProfileView

from .governance import parse_user_profile_content, user_biography_field_ids


def user_profile_field_values(record: RenderedUserProfileView | None) -> dict[str, str]:
    if record is None:
        return {}
    values: dict[str, str] = {}
    if _clean(record.preferred_name) is not None:
        values["preferred_name"] = _clean(record.preferred_name) or ""
    if record.boundaries:
        boundary = _clean(record.boundaries[0])
        if boundary is not None:
            values["boundaries"] = boundary
    for fragment in record.biography_fragments:
        key, _, raw_value = fragment.partition(":")
        cleaned_key = key.strip()
        cleaned_value = _clean(raw_value)
        if cleaned_key and cleaned_value is not None:
            values[cleaned_key] = cleaned_value
    return values


def user_profile_durable_notes(
    record: RenderedUserProfileView | None,
) -> tuple[str, ...]:
    if record is None:
        return ()
    return tuple(_clean(note) for note in record.durable_notes if _clean(note) is not None)


def apply_user_profile_update(
    record: RenderedUserProfileView,
    *,
    text: str | None = None,
    field_values: Mapping[str, str] | None = None,
    append: bool = False,
    clear: bool = False,
) -> RenderedUserProfileView:
    if clear:
        next_values: dict[str, str] = {}
        next_notes: tuple[str, ...] = ()
    else:
        explicit_values = {
            key: cleaned for key, value in (field_values or {}).items() if (cleaned := _clean(value)) is not None
        }
        parsed_text = parse_user_profile_content(text or "") if text is not None else None
        if text is not None and not append and not explicit_values:
            next_values = dict(parsed_text.field_values) if parsed_text is not None else {}
            next_notes = parsed_text.durable_notes if parsed_text is not None else ()
        else:
            next_values = user_profile_field_values(record)
            next_notes = user_profile_durable_notes(record)
            if text is not None:
                next_values.update(parsed_text.field_values)
                next_notes = _merge_notes(next_notes, parsed_text.durable_notes)
            next_values.update(explicit_values)
    return replace(
        record,
        preferred_name=_clean(next_values.get("preferred_name")),
        boundaries=_singleton(next_values.get("boundaries")),
        biography_fragments=_biography_fragments(next_values),
        durable_notes=next_notes,
    )


def _biography_fragments(field_values: Mapping[str, str]) -> tuple[str, ...]:
    fragments: list[str] = []
    for key in user_biography_field_ids(field_values):
        cleaned = _clean(field_values.get(key))
        if cleaned is not None:
            fragments.append(f"{key}:{cleaned}")
    return tuple(fragments)


def _singleton(value: str | None) -> tuple[str, ...]:
    cleaned = _clean(value)
    if cleaned is None:
        return ()
    return (cleaned,)


def _merge_notes(existing: tuple[str, ...], incoming: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    for value in (*existing, *incoming):
        cleaned = _clean(value)
        if cleaned is not None and cleaned not in merged:
            merged.append(cleaned)
    return tuple(merged)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


__all__ = [
    "apply_user_profile_update",
    "user_profile_durable_notes",
    "user_profile_field_values",
]
