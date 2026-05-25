"""External skill discovery and fetch adapters for public skill sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import base64
import io
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
from tempfile import mkdtemp
from typing import Any
from urllib.parse import quote, urlparse, urlunparse
import zipfile

from packages.runtime_layout import default_skill_search_cache_dir

from .search_support import (
    FetchedSkillBundle,
    RawSkillBundle,
    SkillSearchEntry,
    SkillSearchSource,
    _CLAUDE_MARKETPLACE_REPOS,
    _CLAWHUB_BASE_URL,
    _LOBEHUB_INDEX_URL,
    _SKILLS_SH_BASE_URL,
    _TRUSTED_GITHUB_REPOS,
    _WELL_KNOWN_BASE_PATH,
    _bundle_cache_name,
    _configured_github_taps,
    _dedupe_search_entries,
    _fetch_bytes,
    _fetch_github_contents_file_json,
    _fetch_json,
    _fetch_text,
    _match_score,
    _normalize_bundle_files,
    _parse_skill_markdown,
    _query_text_score,
    _query_tokens,
    _safe_bundle_rel_path,
    _slugify,
    _trust_rank,
)

LOGGER = logging.getLogger(__name__)


class SkillSearchHub:
    """Aggregate public skill search sources and materialize bundles on demand."""

    def __init__(
        self,
        sources: Sequence[SkillSearchSource] | None = None,
        *,
        cache_root: Path | None = None,
    ) -> None:
        self._sources = tuple(sources or default_skill_search_sources())
        self._sources_by_id = {source.source_id: source for source in self._sources}
        self._cache_root = (cache_root or default_skill_search_cache_dir()).expanduser()
        self._fetched: dict[str, FetchedSkillBundle] = {}

    @property
    def sources(self) -> tuple[SkillSearchSource, ...]:
        return self._sources

    def search(
        self,
        query: str,
        *,
        source: str | None = None,
        limit: int = 12,
    ) -> tuple[SkillSearchEntry, ...]:
        normalized = " ".join(query.split())
        if not normalized:
            return ()
        selected = self._select_sources(source)
        if not selected:
            return ()
        per_source_limit = max(limit, 8)
        results: list[SkillSearchEntry] = []
        with ThreadPoolExecutor(max_workers=min(8, len(selected))) as executor:
            future_map = {
                executor.submit(skill_source.search, normalized, limit=per_source_limit): skill_source
                for skill_source in selected
            }
            for future in as_completed(future_map):
                try:
                    results.extend(future.result())
                except Exception:
                    LOGGER.warning("skill search source failed", exc_info=True)
                    continue
        deduped = _dedupe_search_entries(results)
        return tuple(deduped[:limit])

    def fetch(self, reference: str) -> FetchedSkillBundle | None:
        normalized = reference.strip()
        if not normalized:
            return None
        cached = self._fetched.get(normalized)
        if cached is not None:
            return cached
        source = self._source_for_reference(normalized)
        if source is None:
            return None
        bundle = source.fetch(normalized)
        if bundle is None:
            return None
        package_path = self._materialize_bundle(bundle)
        fetched = FetchedSkillBundle(
            skill_id=bundle.skill_id,
            source_id=bundle.source_id,
            source_label=bundle.source_label,
            reference=bundle.reference,
            install_reference=bundle.install_reference,
            package_path=str(package_path),
            trust_level=bundle.trust_level,
            metadata=bundle.metadata,
        )
        self._fetched[normalized] = fetched
        return fetched

    def _select_sources(self, source: str | None) -> tuple[SkillSearchSource, ...]:
        if source is None or not source.strip() or source.strip().lower() == "all":
            return self._sources
        selected = self._sources_by_id.get(source.strip().lower())
        if selected is None:
            return ()
        return (selected,)

    def _source_for_reference(self, reference: str) -> SkillSearchSource | None:
        prefix, _, _rest = reference.partition(":")
        if _ and prefix in self._sources_by_id:
            return self._sources_by_id[prefix]
        if reference.startswith(("http://", "https://")):
            return self._sources_by_id.get("well-known")
        if reference.count("/") >= 2:
            return self._sources_by_id.get("github")
        return None

    def _materialize_bundle(self, bundle: RawSkillBundle) -> Path:
        self._cache_root.mkdir(parents=True, exist_ok=True)
        normalized_files = _normalize_bundle_files(bundle.files)
        target = self._cache_root / _bundle_cache_name(bundle)
        if target.exists() and (target / "SKILL.md").exists():
            return target
        scratch = Path(mkdtemp(prefix="skill-bundle-", dir=self._cache_root))
        try:
            for relative_path, content in normalized_files.items():
                destination = scratch / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            if target.exists():
                shutil.rmtree(target)
            scratch.rename(target)
            return target
        except Exception:
            shutil.rmtree(scratch, ignore_errors=True)
            raise


class GitHubSkillSearchSource:
    source_id = "github"
    label = "GitHub"

    def __init__(self, *, taps: Sequence[Mapping[str, str]] | None = None, token: str | None = None) -> None:
        self._taps = tuple(taps or _configured_github_taps())
        self._token = (token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        self._contents_cache: dict[str, Any] = {}
        self._text_cache: dict[str, str] = {}
        self._tap_cache: dict[str, tuple[SkillSearchEntry, ...]] = {}

    def search(self, query: str, *, limit: int = 10) -> tuple[SkillSearchEntry, ...]:
        tokens = _query_tokens(query)
        if not tokens:
            return ()
        matches: list[tuple[int, SkillSearchEntry]] = []
        for tap in self._taps:
            repo = str(tap.get("repo") or "").strip()
            base_path = str(tap.get("path") or "").strip().strip("/")
            if not repo:
                continue
            for entry in self._list_repo_skills(repo, base_path):
                score = _match_score(entry, tokens)
                if score <= 0:
                    continue
                matches.append((score, entry))
        matches.sort(
            key=lambda item: (
                -item[0],
                -_trust_rank(item[1].trust_level),
                item[1].display_name.lower(),
                item[1].reference.lower(),
            )
        )
        return tuple(_dedupe_search_entries([item[1] for item in matches])[:limit])

    def fetch(self, reference: str) -> RawSkillBundle | None:
        parsed = self._parse_reference(reference)
        if parsed is None:
            return None
        repo, skill_path = parsed
        files = self._download_directory(repo, skill_path)
        if "SKILL.md" not in _normalize_bundle_files(files):
            return None
        canonical = f"{repo}/{skill_path}".strip("/")
        return RawSkillBundle(
            skill_id=PurePosixPath(skill_path).name,
            source_id=self.source_id,
            source_label=self.label,
            reference=f"{self.source_id}:{canonical}",
            install_reference=f"{self.source_id}:{canonical}",
            files=files,
            trust_level=self._trust_level(repo),
            metadata={
                "canonical_id": canonical,
                "repo": repo,
                "path": skill_path,
                "repo_url": f"https://github.com/{repo}",
            },
        )

    def _list_repo_skills(self, repo: str, base_path: str) -> tuple[SkillSearchEntry, ...]:
        cache_key = f"{repo}:{base_path}"
        cached = self._tap_cache.get(cache_key)
        if cached is not None:
            return cached
        entries: list[SkillSearchEntry] = []
        stack = [base_path]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            current_key = current.strip("/")
            if current_key in seen:
                continue
            seen.add(current_key)
            payload = self._github_contents(repo, current_key)
            if not isinstance(payload, list):
                continue
            skill_file = next(
                (
                    item
                    for item in payload
                    if isinstance(item, Mapping)
                    and item.get("type") == "file"
                    and str(item.get("name") or "") == "SKILL.md"
                ),
                None,
            )
            if skill_file is not None:
                text = self._github_file_text(repo, skill_file)
                if not text:
                    continue
                canonical_path = current_key.strip("/")
                if not canonical_path:
                    continue
                meta = _parse_skill_markdown(text, default_skill_id=PurePosixPath(canonical_path).name)
                canonical = f"{repo}/{canonical_path}"
                entries.append(
                    SkillSearchEntry(
                        skill_id=meta["skill_id"],
                        display_name=meta["display_name"],
                        summary=meta["summary"],
                        source_id=self.source_id,
                        source_label=self.label,
                        reference=f"{self.source_id}:{canonical}",
                        install_reference=f"{self.source_id}:{canonical}",
                        trust_level=self._trust_level(repo),
                        metadata={
                            "canonical_id": canonical,
                            "repo": repo,
                            "path": canonical_path,
                            "repo_url": f"https://github.com/{repo}",
                            "detail_url": str(skill_file.get("html_url") or "").strip(),
                        },
                    )
                )
                continue
            for item in payload:
                if not isinstance(item, Mapping) or item.get("type") != "dir":
                    continue
                path_value = str(item.get("path") or "").strip("/")
                if not path_value or ".git" in path_value.split("/"):
                    continue
                stack.append(path_value)
        resolved = tuple(entries)
        self._tap_cache[cache_key] = resolved
        return resolved

    def _download_directory(self, repo: str, root_path: str) -> dict[str, str]:
        files: dict[str, str] = {}
        stack = [root_path.strip("/")]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            payload = self._github_contents(repo, current)
            if not isinstance(payload, list):
                continue
            for item in payload:
                if not isinstance(item, Mapping):
                    continue
                item_type = str(item.get("type") or "")
                item_path = str(item.get("path") or "").strip("/")
                if item_type == "dir" and item_path:
                    stack.append(item_path)
                    continue
                if item_type != "file" or not item_path:
                    continue
                text = self._github_file_text(repo, item)
                if text is None:
                    continue
                rel_path = PurePosixPath(item_path).relative_to(PurePosixPath(root_path.strip("/"))).as_posix()
                files[rel_path] = text
        return files

    def _github_contents(self, repo: str, path: str) -> Any:
        cache_key = f"{repo}:{path}"
        if cache_key in self._contents_cache:
            return self._contents_cache[cache_key]
        suffix = f"/{quote(path, safe='/')}" if path else ""
        payload = _fetch_json(
            f"https://api.github.com/repos/{repo}/contents{suffix}",
            headers=self._github_headers(),
        )
        self._contents_cache[cache_key] = payload
        return payload

    def _github_file_text(self, repo: str, item: Mapping[str, Any]) -> str | None:
        download_url = str(item.get("download_url") or "").strip()
        if download_url:
            return _fetch_text(download_url)
        item_path = str(item.get("path") or "").strip("/")
        if not item_path:
            return None
        cache_key = f"{repo}:{item_path}"
        if cache_key in self._text_cache:
            return self._text_cache[cache_key]
        payload = _fetch_json(
            f"https://api.github.com/repos/{repo}/contents/{quote(item_path, safe='/')}",
            headers=self._github_headers(),
        )
        if not isinstance(payload, Mapping):
            return None
        encoded = payload.get("content")
        if not isinstance(encoded, str):
            return None
        try:
            text = base64.b64decode(encoded.encode("utf-8")).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
        self._text_cache[cache_key] = text
        return text

    def _parse_reference(self, reference: str) -> tuple[str, str] | None:
        raw = reference[len("github:") :] if reference.startswith("github:") else reference
        parts = raw.strip("/").split("/", 2)
        if len(parts) < 3:
            return None
        return (f"{parts[0]}/{parts[1]}", parts[2].strip("/"))

    def _github_headers(self) -> Mapping[str, str]:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        return headers

    def _trust_level(self, repo: str) -> str:
        return "trusted" if repo in _TRUSTED_GITHUB_REPOS else "community"


class SkillsShSkillSearchSource:
    source_id = "skills-sh"
    label = "Skills.sh"

    def __init__(self, github: GitHubSkillSearchSource) -> None:
        self._github = github

    def search(self, query: str, *, limit: int = 10) -> tuple[SkillSearchEntry, ...]:
        if not query.strip():
            return ()
        payload = _fetch_json(
            f"{_SKILLS_SH_BASE_URL}/api/search",
            params={"q": query, "limit": str(limit)},
        )
        if not isinstance(payload, Mapping):
            return ()
        items = payload.get("skills", ())
        if not isinstance(items, list):
            return ()
        entries: list[SkillSearchEntry] = []
        for item in items[:limit]:
            if not isinstance(item, Mapping):
                continue
            canonical = str(item.get("id") or "").strip().strip("/")
            repo = str(item.get("source") or "").strip()
            skill_path = str(item.get("skillId") or "").strip().strip("/")
            if not canonical and repo and skill_path:
                canonical = f"{repo}/{skill_path}"
            if canonical.count("/") < 2:
                continue
            display_name = str(item.get("name") or PurePosixPath(canonical).name).strip() or PurePosixPath(canonical).name
            installs = item.get("installs")
            install_note = f" · {int(installs):,} installs" if isinstance(installs, int) else ""
            repo_slug = "/".join(canonical.split("/", 2)[:2])
            entries.append(
                SkillSearchEntry(
                    skill_id=PurePosixPath(canonical).name,
                    display_name=display_name,
                    summary=f"Indexed by skills.sh from {repo_slug}{install_note}",
                    source_id=self.source_id,
                    source_label=self.label,
                    reference=f"{self.source_id}:{canonical}",
                    install_reference=f"github:{canonical}",
                    trust_level=self._github._trust_level(repo_slug),
                    metadata={
                        "canonical_id": canonical,
                        "detail_url": f"{_SKILLS_SH_BASE_URL}/{canonical}",
                        "repo_url": f"https://github.com/{repo_slug}",
                    },
                )
            )
        return tuple(entries)

    def fetch(self, reference: str) -> RawSkillBundle | None:
        canonical = reference[len("skills-sh:") :] if reference.startswith("skills-sh:") else reference
        bundle = self._github.fetch(f"github:{canonical}")
        if bundle is None:
            return None
        return replace(
            bundle,
            source_id=self.source_id,
            source_label=self.label,
            reference=f"{self.source_id}:{canonical}",
            install_reference=f"github:{canonical}",
            metadata={
                **dict(bundle.metadata),
                "canonical_id": canonical,
                "detail_url": f"{_SKILLS_SH_BASE_URL}/{canonical}",
                "repo_url": f"https://github.com/{'/'.join(canonical.split('/', 2)[:2])}",
            },
        )


class WellKnownSkillSearchSource:
    source_id = "well-known"
    label = "Well-Known"

    def search(self, query: str, *, limit: int = 10) -> tuple[SkillSearchEntry, ...]:
        index_url = self._query_to_index_url(query)
        if index_url is None:
            return ()
        payload = _fetch_json(index_url)
        if not isinstance(payload, Mapping):
            return ()
        skills = payload.get("skills", ())
        if not isinstance(skills, list):
            return ()
        base_url = index_url[: -len("/index.json")]
        entries: list[SkillSearchEntry] = []
        for item in skills[:limit]:
            if not isinstance(item, Mapping):
                continue
            skill_name = str(item.get("name") or "").strip()
            if not skill_name:
                continue
            reference = f"{self.source_id}:{index_url}#{skill_name}"
            entries.append(
                SkillSearchEntry(
                    skill_id=skill_name,
                    display_name=skill_name,
                    summary=str(item.get("description") or f"Published at {base_url}").strip(),
                    source_id=self.source_id,
                    source_label=self.label,
                    reference=reference,
                    install_reference=reference,
                    trust_level="community",
                    metadata={
                        "canonical_id": reference.lower(),
                        "base_url": base_url,
                        "index_url": index_url,
                        "detail_url": f"{base_url}/{skill_name}",
                        "files": tuple(item.get("files") or ("SKILL.md",)),
                    },
                )
            )
        return tuple(entries)

    def fetch(self, reference: str) -> RawSkillBundle | None:
        parsed = self._parse_reference(reference)
        if parsed is None:
            return None
        payload = _fetch_json(parsed["index_url"])
        if not isinstance(payload, Mapping):
            return None
        skills = payload.get("skills", ())
        if not isinstance(skills, list):
            return None
        entry = next(
            (
                item
                for item in skills
                if isinstance(item, Mapping) and str(item.get("name") or "").strip() == parsed["skill_name"]
            ),
            None,
        )
        if entry is None:
            return None
        files = entry.get("files")
        file_list = tuple(str(item).strip() for item in files) if isinstance(files, list) else ("SKILL.md",)
        downloaded: dict[str, str] = {}
        for relative_path in file_list:
            if not relative_path:
                continue
            safe_path = _safe_bundle_rel_path(relative_path)
            text = _fetch_text(f"{parsed['skill_url']}/{safe_path}")
            if text is None:
                return None
            downloaded[safe_path] = text
        if "SKILL.md" not in _normalize_bundle_files(downloaded):
            return None
        return RawSkillBundle(
            skill_id=parsed["skill_name"],
            source_id=self.source_id,
            source_label=self.label,
            reference=parsed["reference"],
            install_reference=parsed["reference"],
            files=downloaded,
            trust_level="community",
            metadata={
                "canonical_id": parsed["reference"].lower(),
                "base_url": parsed["base_url"],
                "index_url": parsed["index_url"],
                "detail_url": parsed["skill_url"],
            },
        )

    def _query_to_index_url(self, query: str) -> str | None:
        candidate = query.strip()
        if not candidate.startswith(("http://", "https://")):
            return None
        if candidate.endswith("/index.json"):
            return candidate
        if f"{_WELL_KNOWN_BASE_PATH}/" in candidate:
            return candidate.split(f"{_WELL_KNOWN_BASE_PATH}/", 1)[0] + f"{_WELL_KNOWN_BASE_PATH}/index.json"
        return candidate.rstrip("/") + f"{_WELL_KNOWN_BASE_PATH}/index.json"

    def _parse_reference(self, reference: str) -> dict[str, str] | None:
        raw = reference[len("well-known:") :] if reference.startswith("well-known:") else reference
        if not raw.startswith(("http://", "https://")):
            return None
        parsed_url = urlparse(raw)
        clean_url = urlunparse(parsed_url._replace(fragment=""))
        fragment = parsed_url.fragment.strip()
        if clean_url.endswith("/index.json") and fragment:
            base_url = clean_url[: -len("/index.json")]
            return {
                "reference": f"{self.source_id}:{clean_url}#{fragment}",
                "index_url": clean_url,
                "base_url": base_url,
                "skill_name": fragment,
                "skill_url": f"{base_url}/{fragment}",
            }
        if clean_url.endswith("/SKILL.md"):
            skill_url = clean_url[: -len("/SKILL.md")]
        else:
            skill_url = clean_url.rstrip("/")
        if f"{_WELL_KNOWN_BASE_PATH}/" not in skill_url:
            return None
        base_url, skill_name = skill_url.rsplit("/", 1)
        index_url = f"{base_url}/index.json"
        normalized = f"{self.source_id}:{index_url}#{skill_name}"
        return {
            "reference": normalized,
            "index_url": index_url,
            "base_url": base_url,
            "skill_name": skill_name,
            "skill_url": skill_url,
        }


class ClawHubSkillSearchSource:
    source_id = "clawhub"
    label = "ClawHub"

    def search(self, query: str, *, limit: int = 10) -> tuple[SkillSearchEntry, ...]:
        payload = _fetch_json(
            f"{_CLAWHUB_BASE_URL}/skills",
            params={"search": query, "limit": str(limit)},
            timeout=20,
        )
        if payload is None:
            return ()
        items = payload.get("items", payload) if isinstance(payload, Mapping) else payload
        if not isinstance(items, list):
            return ()
        entries: list[SkillSearchEntry] = []
        for item in items[:limit]:
            if not isinstance(item, Mapping):
                continue
            slug = str(item.get("slug") or "").strip()
            if not slug:
                continue
            display_name = str(item.get("displayName") or item.get("name") or slug).strip() or slug
            summary = str(item.get("summary") or item.get("description") or "").strip()
            reference = f"{self.source_id}:{slug}"
            entries.append(
                SkillSearchEntry(
                    skill_id=slug,
                    display_name=display_name,
                    summary=summary or f"Published on ClawHub as {slug}.",
                    source_id=self.source_id,
                    source_label=self.label,
                    reference=reference,
                    install_reference=reference,
                    trust_level="community",
                    metadata={
                        "canonical_id": slug.lower(),
                        "detail_url": f"https://clawhub.ai/skills/{slug}",
                    },
                )
            )
        return tuple(entries)

    def fetch(self, reference: str) -> RawSkillBundle | None:
        slug = reference[len("clawhub:") :] if reference.startswith("clawhub:") else reference
        slug = slug.strip().split("/")[-1]
        if not slug:
            return None
        details = _fetch_json(f"{_CLAWHUB_BASE_URL}/skills/{slug}", timeout=20)
        if not isinstance(details, Mapping):
            return None
        version = self._resolve_version(slug, details)
        if not version:
            return None
        files = self._download_bundle_zip(slug, version)
        if "SKILL.md" not in _normalize_bundle_files(files):
            version_payload = _fetch_json(f"{_CLAWHUB_BASE_URL}/skills/{slug}/versions/{version}", timeout=20)
            if isinstance(version_payload, Mapping):
                files = self._extract_inline_files(version_payload)
        if "SKILL.md" not in _normalize_bundle_files(files):
            return None
        normalized_reference = f"{self.source_id}:{slug}"
        return RawSkillBundle(
            skill_id=slug,
            source_id=self.source_id,
            source_label=self.label,
            reference=normalized_reference,
            install_reference=normalized_reference,
            files=files,
            trust_level="community",
            metadata={
                "canonical_id": slug.lower(),
                "detail_url": f"https://clawhub.ai/skills/{slug}",
                "version": version,
            },
        )

    def _resolve_version(self, slug: str, payload: Mapping[str, Any]) -> str | None:
        latest = payload.get("latestVersion")
        if isinstance(latest, Mapping):
            version = str(latest.get("version") or "").strip()
            if version:
                return version
        tags = payload.get("tags")
        if isinstance(tags, Mapping):
            latest_tag = str(tags.get("latest") or "").strip()
            if latest_tag:
                return latest_tag
        versions = _fetch_json(f"{_CLAWHUB_BASE_URL}/skills/{slug}/versions", timeout=20)
        if isinstance(versions, list) and versions:
            first = versions[0]
            if isinstance(first, Mapping):
                version = str(first.get("version") or "").strip()
                if version:
                    return version
        return None

    def _download_bundle_zip(self, slug: str, version: str) -> dict[str, str]:
        content = _fetch_bytes(
            f"{_CLAWHUB_BASE_URL}/download",
            params={"slug": slug, "version": version},
            timeout=30,
        )
        if content is None:
            return {}
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile:
            return {}
        files: dict[str, str] = {}
        with archive:
            for member in archive.infolist():
                if member.is_dir() or member.file_size > 500_000:
                    continue
                name = member.filename.replace("\\", "/").strip("/")
                if not name:
                    continue
                try:
                    safe_name = _safe_bundle_rel_path(name)
                except ValueError:
                    continue
                try:
                    text = archive.read(member.filename).decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    continue
                files[safe_name] = text
        return files

    def _extract_inline_files(self, payload: Mapping[str, Any]) -> dict[str, str]:
        files: dict[str, str] = {}
        nested = payload.get("version")
        if isinstance(nested, Mapping):
            files.update(self._extract_inline_files(nested))
        file_list = payload.get("files")
        if isinstance(file_list, Mapping):
            for name, content in file_list.items():
                if not isinstance(name, str) or not isinstance(content, str):
                    continue
                try:
                    safe_name = _safe_bundle_rel_path(name)
                except ValueError:
                    continue
                files[safe_name] = content
            return files
        if not isinstance(file_list, list):
            return files
        for item in file_list:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("path") or item.get("name") or "").strip()
            inline = item.get("content")
            if not name or not isinstance(inline, str):
                continue
            try:
                safe_name = _safe_bundle_rel_path(name)
            except ValueError:
                continue
            files[safe_name] = inline
        return files


class ClaudeMarketplaceSkillSearchSource:
    source_id = "claude-marketplace"
    label = "Claude Marketplace"

    def __init__(self, github: GitHubSkillSearchSource) -> None:
        self._github = github

    def search(self, query: str, *, limit: int = 10) -> tuple[SkillSearchEntry, ...]:
        query_tokens = _query_tokens(query)
        if not query_tokens:
            return ()
        entries: list[tuple[int, SkillSearchEntry]] = []
        for repo in _CLAUDE_MARKETPLACE_REPOS:
            for plugin in self._marketplace_plugins(repo):
                name = str(plugin.get("name") or "").strip()
                description = str(plugin.get("description") or "").strip()
                if _query_text_score(" ".join((name, description)), query_tokens) <= 0:
                    continue
                identifier = self._plugin_identifier(repo, plugin)
                if not identifier:
                    continue
                repo_slug = "/".join(identifier.split("/", 2)[:2])
                entry = SkillSearchEntry(
                    skill_id=PurePosixPath(identifier).name,
                    display_name=name or PurePosixPath(identifier).name,
                    summary=description or f"Published in marketplace repo {repo}.",
                    source_id=self.source_id,
                    source_label=self.label,
                    reference=f"{self.source_id}:{identifier}",
                    install_reference=f"github:{identifier}",
                    trust_level=self._github._trust_level(repo_slug),
                    metadata={
                        "canonical_id": identifier,
                        "repo": repo,
                        "repo_url": f"https://github.com/{repo}",
                    },
                )
                entries.append((_match_score(entry, query_tokens), entry))
        entries.sort(
            key=lambda item: (
                -item[0],
                -_trust_rank(item[1].trust_level),
                item[1].display_name.lower(),
            )
        )
        return tuple(_dedupe_search_entries([item[1] for item in entries])[:limit])

    def fetch(self, reference: str) -> RawSkillBundle | None:
        identifier = reference[len("claude-marketplace:") :] if reference.startswith("claude-marketplace:") else reference
        bundle = self._github.fetch(f"github:{identifier}")
        if bundle is None:
            return None
        return replace(
            bundle,
            source_id=self.source_id,
            source_label=self.label,
            reference=f"{self.source_id}:{identifier}",
            install_reference=f"github:{identifier}",
            metadata={
                **dict(bundle.metadata),
                "canonical_id": identifier,
                "repo_url": f"https://github.com/{'/'.join(identifier.split('/', 2)[:2])}",
            },
        )

    def _marketplace_plugins(self, repo: str) -> tuple[Mapping[str, Any], ...]:
        payload = _fetch_github_contents_file_json(repo, ".claude-plugin/marketplace.json", token=self._github._token)
        if not isinstance(payload, Mapping):
            return ()
        plugins = payload.get("plugins", ())
        if not isinstance(plugins, list):
            return ()
        return tuple(item for item in plugins if isinstance(item, Mapping))

    def _plugin_identifier(self, repo: str, plugin: Mapping[str, Any]) -> str:
        source_path = str(plugin.get("source") or "").strip()
        if not source_path:
            return ""
        if source_path.startswith("./"):
            return f"{repo}/{source_path[2:]}"
        if source_path.count("/") >= 2:
            return source_path
        return f"{repo}/{source_path.lstrip('/')}"


class LobeHubSkillSearchSource:
    source_id = "lobehub"
    label = "LobeHub"

    def search(self, query: str, *, limit: int = 10) -> tuple[SkillSearchEntry, ...]:
        payload = _fetch_json(_LOBEHUB_INDEX_URL, timeout=30)
        if payload is None:
            return ()
        agents = payload.get("agents", payload) if isinstance(payload, Mapping) else payload
        if not isinstance(agents, list):
            return ()
        query_tokens = _query_tokens(query)
        if not query_tokens:
            return ()
        matches: list[tuple[int, SkillSearchEntry]] = []
        for item in agents:
            if not isinstance(item, Mapping):
                continue
            meta = item.get("meta", item)
            if not isinstance(meta, Mapping):
                meta = item
            identifier = str(item.get("identifier") or "").strip()
            title = str(meta.get("title") or identifier).strip() or identifier
            description = str(meta.get("description") or "").strip()
            searchable = " ".join((identifier, title, description))
            score = _query_text_score(searchable, query_tokens)
            if score <= 0:
                continue
            entry = SkillSearchEntry(
                skill_id=identifier or _slugify(title),
                display_name=title or identifier or "lobehub-agent",
                summary=description[:220] or f"LobeHub agent template {identifier or title}.",
                source_id=self.source_id,
                source_label=self.label,
                reference=f"{self.source_id}:{identifier or _slugify(title)}",
                install_reference=f"{self.source_id}:{identifier or _slugify(title)}",
                trust_level="community",
                metadata={
                    "canonical_id": (identifier or _slugify(title)).lower(),
                    "detail_url": f"https://chat-agents.lobehub.com/{identifier or _slugify(title)}.json",
                },
            )
            matches.append((score, entry))
        matches.sort(key=lambda item: (-item[0], item[1].display_name.lower()))
        return tuple(_dedupe_search_entries([item[1] for item in matches])[:limit])

    def fetch(self, reference: str) -> RawSkillBundle | None:
        agent_id = reference[len("lobehub:") :] if reference.startswith("lobehub:") else reference
        agent_id = agent_id.strip().split("/", 1)[-1]
        if not agent_id:
            return None
        payload = _fetch_json(f"https://chat-agents.lobehub.com/{agent_id}.json")
        if not isinstance(payload, Mapping):
            return None
        skill_md = self._to_skill_markdown(payload, agent_id=agent_id)
        normalized_reference = f"{self.source_id}:{agent_id}"
        return RawSkillBundle(
            skill_id=agent_id,
            source_id=self.source_id,
            source_label=self.label,
            reference=normalized_reference,
            install_reference=normalized_reference,
            files={"SKILL.md": skill_md},
            trust_level="community",
            metadata={
                "canonical_id": agent_id.lower(),
                "detail_url": f"https://chat-agents.lobehub.com/{agent_id}.json",
            },
        )

    def _to_skill_markdown(self, payload: Mapping[str, Any], *, agent_id: str) -> str:
        meta = payload.get("meta", payload)
        if not isinstance(meta, Mapping):
            meta = payload
        title = str(meta.get("title") or agent_id).strip() or agent_id
        description = str(meta.get("description") or "").strip()
        config = payload.get("config", {})
        if not isinstance(config, Mapping):
            config = {}
        system_role = str(config.get("systemRole") or "").strip()
        lines = [
            "---",
            f"name: {title}",
            f"skill_id: {agent_id}",
            f"description: {description or f'LobeHub agent {agent_id}'}",
            "version: 1.0.0",
            "source_kind: lobehub-agent",
            "---",
            "",
            f"# {title}",
            "",
        ]
        if description:
            lines.extend([description, ""])
        lines.extend(
            [
                "## Instructions",
                "",
                system_role or "Follow the LobeHub system role attached to this agent.",
                "",
            ]
        )
        return "\n".join(lines)


def default_skill_search_sources() -> tuple[SkillSearchSource, ...]:
    github = GitHubSkillSearchSource()
    return (
        SkillsShSkillSearchSource(github),
        WellKnownSkillSearchSource(),
        github,
        ClawHubSkillSearchSource(),
        ClaudeMarketplaceSkillSearchSource(github),
        LobeHubSkillSearchSource(),
    )

__all__ = [
    "FetchedSkillBundle",
    "GitHubSkillSearchSource",
    "RawSkillBundle",
    "SkillSearchEntry",
    "SkillSearchHub",
    "SkillSearchSource",
    "default_skill_search_sources",
]
