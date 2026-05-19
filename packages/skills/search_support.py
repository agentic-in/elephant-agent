"""Shared types and helper utilities for external skill discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import base64
import json
import os
from pathlib import PurePosixPath
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

_DEFAULT_TIMEOUT_SECONDS = 15
_TRUST_RANK = {"builtin": 3, "trusted": 2, "community": 1}
_SOURCE_PRIORITY = {
    "github": 0,
    "skills-sh": 1,
    "well-known": 2,
    "claude-marketplace": 3,
    "clawhub": 4,
    "lobehub": 5,
}
_TRUSTED_GITHUB_REPOS = frozenset(
    {
        "openai/skills",
        "anthropics/skills",
        "aiskillstore/marketplace",
    }
)
_SKILLS_SH_BASE_URL = "https://skills.sh"
_WELL_KNOWN_BASE_PATH = "/.well-known/skills"
_CLAWHUB_BASE_URL = "https://clawhub.ai/api/v1"
_LOBEHUB_INDEX_URL = "https://chat-agents.lobehub.com/index.json"
_CLAUDE_MARKETPLACE_REPOS = (
    "anthropics/skills",
    "aiskillstore/marketplace",
)
_DEFAULT_GITHUB_TAPS = (
    {"repo": "openai/skills", "path": "skills/"},
    {"repo": "anthropics/skills", "path": "skills/"},
    {"repo": "VoltAgent/awesome-agent-skills", "path": "skills/"},
    {"repo": "garrytan/gstack", "path": ""},
)


@dataclass(frozen=True, slots=True)
class SkillSearchEntry:
    skill_id: str
    display_name: str
    summary: str
    source_id: str
    source_label: str
    reference: str
    install_reference: str
    trust_level: str = "community"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        canonical = str(self.metadata.get("canonical_id") or self.install_reference or self.reference).strip().lower()
        return canonical or self.reference.lower()


@dataclass(frozen=True, slots=True)
class RawSkillBundle:
    skill_id: str
    source_id: str
    source_label: str
    reference: str
    install_reference: str
    files: Mapping[str, str]
    trust_level: str = "community"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FetchedSkillBundle:
    skill_id: str
    source_id: str
    source_label: str
    reference: str
    install_reference: str
    package_path: str
    trust_level: str = "community"
    metadata: Mapping[str, Any] = field(default_factory=dict)


class SkillSearchSource(Protocol):
    source_id: str
    label: str

    def search(self, query: str, *, limit: int = 10) -> tuple[SkillSearchEntry, ...]:
        """Search for remote skills matching a query."""

    def fetch(self, reference: str) -> RawSkillBundle | None:
        """Fetch a remote skill bundle."""


def _configured_github_taps() -> tuple[Mapping[str, str], ...]:
    configured = os.environ.get("ELEPHANT_SKILL_SEARCH_GITHUB_TAPS", "").strip()
    if not configured:
        return _DEFAULT_GITHUB_TAPS
    try:
        payload = json.loads(configured)
    except json.JSONDecodeError:
        return _DEFAULT_GITHUB_TAPS
    if not isinstance(payload, list):
        return _DEFAULT_GITHUB_TAPS
    taps: list[Mapping[str, str]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        repo = str(item.get("repo") or "").strip()
        path = str(item.get("path") or "").strip()
        if repo:
            taps.append({"repo": repo, "path": path})
    return tuple(taps) or _DEFAULT_GITHUB_TAPS


def _dedupe_search_entries(
    entries: Sequence[SkillSearchEntry],
) -> list[SkillSearchEntry]:
    resolved: dict[str, SkillSearchEntry] = {}
    for entry in entries:
        existing = resolved.get(entry.dedupe_key)
        if existing is None or _entry_preference(entry) > _entry_preference(existing):
            resolved[entry.dedupe_key] = entry
    return sorted(
        resolved.values(),
        key=lambda item: (
            -_trust_rank(item.trust_level),
            _SOURCE_PRIORITY.get(item.source_id, 99),
            item.display_name.lower(),
            item.reference.lower(),
        ),
    )


def _entry_preference(entry: SkillSearchEntry) -> tuple[int, int, int]:
    return (
        _trust_rank(entry.trust_level),
        -_SOURCE_PRIORITY.get(entry.source_id, 99),
        len(entry.summary),
    )


def _match_score(entry: SkillSearchEntry, tokens: Sequence[str]) -> int:
    haystack = " ".join(
        (
            entry.skill_id,
            entry.display_name,
            entry.summary,
            str(entry.metadata.get("canonical_id") or ""),
        )
    )
    return _query_text_score(haystack, tokens)


def _query_text_score(text: str, tokens: Sequence[str]) -> int:
    normalized = _normalize_query(text)
    if not normalized or not tokens:
        return 0
    score = 0
    for token in tokens:
        if token not in normalized:
            return 0
        if normalized.startswith(token):
            score += 5
        score += normalized.count(token) + 1
    return score


def _query_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in _normalize_query(value).split() if token)


def _normalize_query(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def _trust_rank(level: str) -> int:
    return _TRUST_RANK.get(level, 0)


def _bundle_cache_name(bundle: RawSkillBundle) -> str:
    digest = base64.urlsafe_b64encode(bundle.reference.encode("utf-8")).decode("ascii").rstrip("=")
    slug = _slugify(bundle.skill_id or bundle.reference)
    return f"{bundle.source_id}-{slug}-{digest[:12]}"


def _normalize_bundle_files(files: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for relative_path, content in files.items():
        safe_path = _safe_bundle_rel_path(relative_path)
        normalized[safe_path] = content
    if "SKILL.md" in normalized:
        return normalized
    skill_candidates = [path for path in normalized if path.endswith("/SKILL.md")]
    if len(skill_candidates) != 1:
        return normalized
    prefix = skill_candidates[0][: -len("/SKILL.md")]
    stripped: dict[str, str] = {}
    for relative_path, content in normalized.items():
        if relative_path == prefix:
            continue
        if relative_path == skill_candidates[0]:
            stripped["SKILL.md"] = content
            continue
        if prefix and relative_path.startswith(f"{prefix}/"):
            stripped[relative_path[len(prefix) + 1 :]] = content
    return stripped or normalized


def _safe_bundle_rel_path(relative_path: str) -> str:
    candidate = PurePosixPath(str(relative_path).replace("\\", "/").strip().lstrip("./"))
    if not candidate.parts or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe bundle path: {relative_path}")
    return candidate.as_posix()


def _parse_skill_markdown(text: str, *, default_skill_id: str) -> dict[str, str]:
    frontmatter, body = _split_frontmatter(text)
    display_name = (
        str(frontmatter.get("name") or frontmatter.get("display_name") or "").strip()
        or _first_heading(body)
        or default_skill_id.replace("-", " ").title()
    )
    summary = (
        str(frontmatter.get("description") or frontmatter.get("summary") or "").strip()
        or _first_summary(body)
        or f"Skill package {default_skill_id}."
    )
    skill_id = str(frontmatter.get("skill_id") or default_skill_id).strip() or default_skill_id
    return {
        "skill_id": skill_id,
        "display_name": display_name,
        "summary": summary,
    }


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return ({}, text)
    closing = text.find("\n---\n", 4)
    if closing == -1:
        return ({}, text)
    payload: dict[str, str] = {}
    for raw_line in text[4:closing].splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload, text[closing + len("\n---\n") :]


def _first_heading(body: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("#"):
            continue
        return line.lstrip("#").strip()
    return ""


def _first_summary(body: str) -> str:
    current: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                break
            continue
        if line.startswith("#"):
            continue
        current.append(line)
        if len(" ".join(current)) >= 180:
            break
    return " ".join(current).strip()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower().replace("_", "-").replace(" ", "-"))
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "skill"


def _fetch_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    timeout: int = _DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    payload = _fetch_bytes(url, headers=headers, params=params, timeout=timeout)
    if payload is None:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _fetch_text(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    timeout: int = _DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    payload = _fetch_bytes(url, headers=headers, params=params, timeout=timeout)
    if payload is None:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _fetch_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    timeout: int = _DEFAULT_TIMEOUT_SECONDS,
) -> bytes | None:
    request_url = url
    if params:
        encoded = urlencode({key: value for key, value in params.items() if value is not None})
        if encoded:
            separator = "&" if "?" in request_url else "?"
            request_url = f"{request_url}{separator}{encoded}"
    request = Request(
        request_url,
        headers={
            "User-Agent": "Elephant Agent/2.0 (+https://github.com/agentic-in/elephant)",
            **dict(headers or {}),
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                return None
            return response.read()
    except HTTPError:
        return None
    except (URLError, OSError, TimeoutError):
        return None


def _fetch_github_contents_file_json(repo: str, path: str, *, token: str = "") -> Any:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    payload = _fetch_json(
        f"https://api.github.com/repos/{repo}/contents/{quote(path, safe='/')}",
        headers=headers,
    )
    if not isinstance(payload, Mapping):
        return None
    download_url = str(payload.get("download_url") or "").strip()
    if download_url:
        text = _fetch_text(download_url)
        if text is not None:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None
    encoded = payload.get("content")
    if not isinstance(encoded, str):
        return None
    try:
        text = base64.b64decode(encoded.encode("utf-8")).decode("utf-8")
        return json.loads(text)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
