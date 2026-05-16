#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[3]
HARNESS_ROOT = ROOT / "tools" / "agent"
MANIFEST_PATH = HARNESS_ROOT / "repo-manifest.yaml"
MATRIX_PATH = HARNESS_ROOT / "task-matrix.yaml"
SKILL_REGISTRY_PATH = HARNESS_ROOT / "skill-registry.yaml"
STRUCTURE_RULES_PATH = HARNESS_ROOT / "structure-rules.yaml"
CONTEXT_MAP_PATH = HARNESS_ROOT / "context-map.yaml"
MAX_PYTHON_FILE_LINES = 1000
PYTHON_LINE_LIMIT_SURFACES = ("apps", "packages")
PYTHON_LINE_LIMIT_PATTERNS = tuple(f"{surface}/**/*.py" for surface in PYTHON_LINE_LIMIT_SURFACES)
PYTHON_LINE_LIMIT_ALLOWLIST_PATTERNS: tuple[str, ...] = (
    "apps/api/api_runtime_console_ops.py",
    "apps/cli/cli_main_impl.py",
    "apps/cli/runtime_extensions_surface.py",
    "apps/cli/shell_composer.py",
    "apps/cli/shell_methods_commands.py",
    "apps/gateway/gateway_main_impl.py",
    "packages/evidence/runtime.py",
    "packages/learning/personal_model_evolution.py",
    "packages/models/providers/openai_compatible.py",
    "packages/storage/repository_system_methods.py",
)
FRONTEND_TYPECHECKS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "dashboard",
        ("apps/dashboard/**",),
        ("npm", "--prefix", "apps/dashboard", "run", "typecheck"),
    ),
    (
        "site",
        ("apps/site/**",),
        ("npm", "--prefix", "apps/site", "run", "typecheck"),
    ),
)
RESET_BANNED_TERM_ALLOWLIST_PATTERNS: tuple[str, ...] = (
    "docs/system-design/system-layer-model.md",
    "docs/agent/adr/**",
    "docs/agent/plans/personal-model-analyst-agent.md",
    "docs/agent/plans/system-layer-reset.md",
    "docs/agent/task-cards/system-layer-reset-*.md",
    "tests/e2e/api/test_api_surface.py",
    "tests/e2e/release/test_release_certification.py",
    "tests/e2e/release/test_design_closure_certification.py",
    "tests/agent/test_system_layer_reset_matrix.py",
    "tests/agent/test_agent_gate.py",
    "tests/integration/storage_system_layers/test_schema.py",
    "tests/integration/storage_system_layers/test_repository.py",
    "tests/unit/cli/test_shell.py",
    "tests/unit/test_builtin_tools_v2.py",
    "apps/site/src/generated/skillhubCatalog.ts",
    "apps/site/docs/skillhub/**",
    "packages/skills/builtin_packages/**",
    "tools/agent/scripts/agent_gate.py",
)
RESET_BANNED_TERMS: tuple[tuple[str, str], ...] = (
    (" ".join(("voice", "mode")), "speech-mode contract is removed from reset surfaces"),
    (" ".join(("voice", "prompt")), "speech prompt contract is removed from reset surfaces"),
    (" ".join(("goal", "graph")), "current-work graph wording is removed from reset surfaces"),
    (" ".join(("activity", "graph")), "activity-tree wording is removed from reset surfaces"),
    ("packages.goals", "goal package is removed from reset surfaces"),
    ("GoalNode", "goal-node contract is removed from reset surfaces"),
    ("WorklineSnapshot", "workline snapshot contract is removed from reset surfaces"),
    ("activity_graphs", "activity graph storage is removed from reset surfaces"),
    ("activity_nodes", "activity node storage is removed from reset surfaces"),
    ("activity_goals", "activity goal storage table is removed from reset surfaces"),
    ("goal_nodes", "goal node storage table is removed from reset surfaces"),
    ("active_goal_id", "active goal pointer is removed from reset surfaces"),
    ("goal_query", "state_query replaces goal_query in reset surfaces"),
    ("goal_update", "legacy goal update event type is removed from reset surfaces"),
    ("goal_snapshot", "legacy goal snapshot event type is removed from reset surfaces"),
    ("goal_refs", "work_item_refs replaces goal_refs in reset surfaces"),
    ("goal_ids", "work_item_ids replaces goal_ids in reset surfaces"),
    ("focus_activity_ids", "focus_work_item_ids replaces focus_activity_ids in reset surfaces"),
    ("activity_candidates", "work_item_candidates replaces activity_candidates in reset surfaces"),
    ("build_activity_routing_section", "work routing replaces activity routing in reset surfaces"),
    ("tool.profile.manage", "memory.curate owns model-visible durable memory writes"),
    ("tool.memory.upload", "upload cannot represent capture semantics"),
    ("tool.procedure.inspect", "procedure inspection is not model-visible"),
    ("tool.procedure.manage", "direct procedure management is not model-visible"),
    ("DeterministicEpisodeObserver", "Personal Model learning must not use keyword observer fallback"),
    ("PatternClusterer", "skill crystallization must not use ExperienceRecord-first clustering"),
    ("DerivedProcedureCandidateStore", "skill crystallization candidates come from trajectory metrics"),
    ("list_pattern_clusters", "ExperienceRecord-first learning cluster APIs are removed"),
    ("list_procedure_candidates", "procedure candidates are no longer ExperienceRecord-derived"),
    ("/goals", "session-era goal routes are removed from reset surfaces"),
    ("/procedure", "session-era procedure routes are removed from reset surfaces"),
    (" ".join(("intent", "layer")), "intent routing wording is removed from reset surfaces"),
    (
        "/".join(("strong", "weak")) + " " + "model selection",
        "strong-or-weak routing wording is removed from reset surfaces",
    ),
)


@dataclass
class RuleMatch:
    name: str
    summary: str
    score: int
    priority: int
    read_first: list[str]
    fast_tests: list[str]
    feature_tests: list[str]


@dataclass
class SurfaceRef:
    path: str
    reason: str = ""


@dataclass
class ContextPack:
    primary_skill: str
    primary_summary: str
    also_matched: list[str]
    start_here: list[SurfaceRef]
    read_first: list[str]
    surfaces: dict[str, list[SurfaceRef]]
    surface_paths: dict[str, tuple[str, ...]]
    local_agents_md: list[str]
    validation: list[str]
    acceptance_criteria: str = ""
    audit_warnings: list[str] = field(default_factory=list)


def load_manifest(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        try:
            return yaml.safe_load(text) or {}
        except Exception:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse {path}: {exc}") from exc


def load_surface_path_map() -> dict[str, tuple[str, ...]]:
    context_map = load_manifest(CONTEXT_MAP_PATH) if CONTEXT_MAP_PATH.exists() else {}
    raw_map = context_map.get("surface_paths", {})
    if not isinstance(raw_map, dict):
        return {}
    return {
        str(surface_name): tuple(str(pattern) for pattern in patterns)
        for surface_name, patterns in raw_map.items()
        if isinstance(patterns, list)
    }


def path_exists(relative_path: str) -> bool:
    return (ROOT / relative_path).exists()


def parse_repo_name_from_remote_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if ":" in cleaned and "/" not in cleaned.rsplit(":", 1)[-1]:
        cleaned = cleaned.rsplit(":", 1)[-1]
    return cleaned.rsplit("/", 1)[-1]


def resolve_repo_identity_name(root: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        common_dir = result.stdout.strip()
        if common_dir:
            common_path = Path(common_dir)
            if not common_path.is_absolute():
                common_path = (root / common_path).resolve()
            if common_path.name != ".git":
                return common_path.name

    remote_result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if remote_result.returncode == 0:
        remote_url = remote_result.stdout.strip()
        if remote_url:
            return parse_repo_name_from_remote_url(remote_url)

    return root.name


def collect_changed_files(base_ref: str, changed_files: str, changed_files_path: str) -> list[str]:
    if changed_files:
        normalized = changed_files.replace("\n", ",")
        if "," in normalized:
            return [item.strip() for item in normalized.split(",") if item.strip()]
        return shlex.split(changed_files)

    if changed_files_path:
        path = ROOT / changed_files_path
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    if base_ref:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return []


def match_any(path: str, patterns: Iterable[str]) -> bool:
    pure = PurePosixPath(path)
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pure.match(pattern):
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if path == prefix or path.startswith(prefix + "/"):
                return True
    return False


def collect_tracked_files(root: Path = ROOT) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ()
    return tuple(path for path in result.stdout.split("\0") if path)


# ─── Surface resolution ───────────────────────────────────────────────────────


def resolve_surfaces_for_files(changed_files: list[str]) -> set[str]:
    matched: set[str] = set()
    for surface_name, patterns in load_surface_path_map().items():
        for path in changed_files:
            if match_any(path, patterns):
                matched.add(surface_name)
                break
    return matched


def resolve_local_agents_md(changed_files: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for path in changed_files:
        parts = PurePosixPath(path).parts
        for i in range(len(parts) - 1, 0, -1):
            candidate = "/".join(parts[:i]) + "/AGENTS.md"
            if candidate in seen:
                break
            seen.add(candidate)
            if (ROOT / candidate).exists():
                results.append(candidate)
                break
    return sorted(set(results))


def build_context_pack(changed_files: list[str], matches: list[RuleMatch]) -> ContextPack:
    context_map = load_manifest(CONTEXT_MAP_PATH) if CONTEXT_MAP_PATH.exists() else {}
    registry = load_manifest(SKILL_REGISTRY_PATH)
    manifest = load_manifest(MANIFEST_PATH)

    defaults = context_map.get("defaults", {})
    start_here = [
        SurfaceRef(path=entry["path"], reason=entry.get("reason", ""))
        for entry in defaults.get("start_here", [])
    ]

    primary = matches[0] if matches else None
    primary_name = primary.name if primary else registry.get("default_skill", "repo-docs")
    primary_summary = primary.summary if primary else ""

    skills = registry.get("skills", {})
    skill_data = skills.get(primary_name, {})

    # L1: read_first from manifest + skill
    read_first: list[str] = []
    seen_paths: set[str] = set()
    for entry in manifest.get("read_first", []):
        p = entry["path"]
        if p not in seen_paths:
            seen_paths.add(p)
            read_first.append(p)
    for p in skill_data.get("read_first", []):
        if p not in seen_paths:
            seen_paths.add(p)
            read_first.append(p)

    # L2: surface resolution
    touched_surfaces = resolve_surfaces_for_files(changed_files)
    required_surfaces = set(skill_data.get("required_surfaces", []))
    conditional_surfaces = set(skill_data.get("conditional_surfaces", []))
    active_surfaces = required_surfaces | (conditional_surfaces & touched_surfaces)
    if not active_surfaces and touched_surfaces:
        active_surfaces = touched_surfaces

    surfaces_section = context_map.get("surfaces", {})
    surface_path_map = load_surface_path_map()
    resolved_surfaces: dict[str, list[SurfaceRef]] = {}
    resolved_surface_paths: dict[str, tuple[str, ...]] = {}
    for surface_name in sorted(active_surfaces):
        refs = surfaces_section.get(surface_name, [])
        resolved_surfaces[surface_name] = [
            SurfaceRef(path=ref["path"], reason=ref.get("reason", ""))
            for ref in refs
        ]
        resolved_surface_paths[surface_name] = surface_path_map.get(surface_name, ())

    # Also add rule-specific context from context-map rules section
    rules_section = context_map.get("rules", {})
    rule_refs = rules_section.get(primary_name, [])
    for ref in rule_refs:
        p = ref["path"]
        if p not in seen_paths:
            seen_paths.add(p)
            read_first.append(p)

    # L3: local AGENTS.md
    local_agents = resolve_local_agents_md(changed_files)

    # Validation
    validation: list[str] = []
    if primary:
        validation.extend(primary.fast_tests)
        validation.extend(primary.feature_tests)
    for match in matches[1:]:
        validation.extend(match.fast_tests)
        validation.extend(match.feature_tests)
    validation = sorted(set(validation))

    also_matched = [m.name for m in matches[1:]] if len(matches) > 1 else []

    acceptance = skill_data.get("acceptance_criteria", "")

    return ContextPack(
        primary_skill=primary_name,
        primary_summary=primary_summary,
        also_matched=also_matched,
        start_here=start_here,
        read_first=read_first,
        surfaces=resolved_surfaces,
        surface_paths=resolved_surface_paths,
        local_agents_md=local_agents,
        validation=validation,
        acceptance_criteria=acceptance,
    )


def audit_surface_coverage(changed_files: list[str], context_pack: ContextPack) -> list[str]:
    warnings: list[str] = []
    touched = resolve_surfaces_for_files(changed_files)
    active = set(context_pack.surfaces.keys())
    uncovered = touched - active
    for surface in sorted(uncovered):
        warnings.append(
            f"surface '{surface}' has matching files but is not in the active skill's required/conditional surfaces"
        )
    unmatched = [p for p in changed_files if not any(match_any(p, patterns) for patterns in load_surface_path_map().values())]
    for path in unmatched:
        warnings.append(f"file does not belong to any surface: {path}")
    return warnings


# ─── Validation ────────────────────────────────────────────────────────────────


def validate_contract() -> tuple[list[str], list[str]]:
    manifest = load_manifest(MANIFEST_PATH)
    matrix = load_manifest(MATRIX_PATH)
    registry = load_manifest(SKILL_REGISTRY_PATH)
    structure = load_manifest(STRUCTURE_RULES_PATH)

    errors: list[str] = []
    checks: list[str] = []

    repo_identity = resolve_repo_identity_name()
    accepted_repo_names = {str(manifest.get("repo_name") or "")}
    accepted_repo_names.update(str(alias) for alias in manifest.get("checkout_aliases", []) if str(alias).strip())
    if repo_identity not in accepted_repo_names:
        errors.append(f"repo_name mismatch: {manifest.get('repo_name')} != {repo_identity}")
    else:
        checks.append("manifest repo_name matches repo root")

    for entry in manifest.get("read_first", []):
        path = entry["path"]
        if path_exists(path):
            checks.append(f"read-first path exists: {path}")
        else:
            errors.append(f"missing read-first path: {path}")

    for required_path in manifest.get("required_paths", []):
        if path_exists(required_path):
            checks.append(f"required path exists: {required_path}")
        else:
            errors.append(f"missing required path: {required_path}")

    skills = registry.get("skills", {})
    default_skill = registry.get("default_skill")
    if default_skill not in skills:
        errors.append(f"default skill is missing from registry: {default_skill}")
    else:
        checks.append(f"default skill exists: {default_skill}")

    for skill_name, skill_data in skills.items():
        for rf in skill_data.get("read_first", []):
            if path_exists(rf):
                checks.append(f"skill read-first path exists: {skill_name} -> {rf}")
            else:
                errors.append(f"skill read-first path missing: {skill_name} -> {rf}")

    rules = matrix.get("rules", [])
    for rule in rules:
        if rule["name"] not in skills:
            errors.append(f"task rule references missing skill: {rule['name']}")
        else:
            checks.append(f"task rule has skill: {rule['name']}")
        for rf in rule.get("read_first", []):
            if path_exists(rf):
                checks.append(f"rule read-first path exists: {rule['name']} -> {rf}")
            else:
                errors.append(f"rule read-first path missing: {rule['name']} -> {rf}")

    for directory in structure.get("directories", {}):
        if path_exists(directory):
            checks.append(f"structure directory exists: {directory}")
        else:
            errors.append(f"missing structure directory: {directory}")

    # Validate context-map references
    if CONTEXT_MAP_PATH.exists():
        context_map = load_manifest(CONTEXT_MAP_PATH)
        surface_names = set(context_map.get("surfaces", {}).keys())
        surface_path_names = set(context_map.get("surface_paths", {}).keys())
        for surface_name in sorted(surface_names - surface_path_names):
            errors.append(f"context-map surface is missing surface_paths entry: {surface_name}")
        for surface_name in sorted(surface_path_names - surface_names):
            errors.append(f"context-map surface_paths references missing surface: {surface_name}")
        for surface_name, patterns in context_map.get("surface_paths", {}).items():
            if not isinstance(patterns, list) or not patterns:
                errors.append(f"context-map surface_paths entry must be a non-empty list: {surface_name}")
                continue
            checks.append(f"context-map surface paths exist: {surface_name}")
        for surface_name, refs in context_map.get("surfaces", {}).items():
            for ref in refs:
                p = ref.get("path", "")
                if path_exists(p):
                    checks.append(f"context-map surface path exists: {surface_name} -> {p}")
                else:
                    errors.append(f"context-map surface path missing: {surface_name} -> {p}")
        # Validate skill required_surfaces reference valid surface names
        for skill_name, skill_data in skills.items():
            for srf in skill_data.get("required_surfaces", []):
                if srf not in surface_names:
                    errors.append(f"skill required_surface references missing surface: {skill_name} -> {srf}")
                else:
                    checks.append(f"skill surface valid: {skill_name} -> {srf}")
            for srf in skill_data.get("conditional_surfaces", []):
                if srf not in surface_names:
                    errors.append(f"skill conditional_surface references missing surface: {skill_name} -> {srf}")
                else:
                    checks.append(f"skill surface valid: {skill_name} -> {srf}")

    errors.extend(scan_reset_banned_terms())

    return checks, errors


def scan_reset_banned_terms(
    *,
    root: Path = ROOT,
    surfaces: Iterable[str] | None = None,
    banned_terms: Iterable[tuple[str, str]] = RESET_BANNED_TERMS,
    allowlist_patterns: Iterable[str] = RESET_BANNED_TERM_ALLOWLIST_PATTERNS,
) -> list[str]:
    errors: list[str] = []
    relative_paths = tuple(surfaces) if surfaces is not None else collect_tracked_files(root)
    for relative_path in relative_paths:
        if surfaces is None and match_any(relative_path, allowlist_patterns):
            continue
        path = root / relative_path
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            line_lower = line.lower()
            for term, rationale in banned_terms:
                if term.lower() in line_lower:
                    errors.append(
                        f"reset banned term in {relative_path}:{line_number}: {term} ({rationale})"
                    )
    return errors


# ─── Rule matching ─────────────────────────────────────────────────────────────


def resolve_rule_matches(changed_files: list[str]) -> list[RuleMatch]:
    matrix = load_manifest(MATRIX_PATH)
    registry = load_manifest(SKILL_REGISTRY_PATH)
    rules = matrix.get("rules", [])
    skills = registry.get("skills", {})

    if not changed_files:
        default_name = registry["default_skill"]
        for rule in rules:
            if rule["name"] == default_name:
                skill_data = skills.get(default_name, {})
                return [
                    RuleMatch(
                        name=rule["name"],
                        summary=rule["summary"],
                        score=0,
                        priority=skill_data.get("priority", 0),
                        read_first=rule.get("read_first", []),
                        fast_tests=rule.get("fast_tests", []),
                        feature_tests=rule.get("feature_tests", []),
                    )
                ]
        return []

    matches: list[RuleMatch] = []
    for rule in rules:
        score = sum(1 for path in changed_files if match_any(path, rule.get("paths", [])))
        if score <= 0:
            continue
        skill_data = skills.get(rule["name"], {})
        priority = skill_data.get("priority", 0)
        matches.append(
            RuleMatch(
                name=rule["name"],
                summary=rule["summary"],
                score=score,
                priority=priority,
                read_first=rule.get("read_first", []),
                fast_tests=rule.get("fast_tests", []),
                feature_tests=rule.get("feature_tests", []),
            )
        )
    # Sort by priority descending, then score descending, then name
    return sorted(matches, key=lambda item: (-item.priority, -item.score, item.name))


# ─── Report output ─────────────────────────────────────────────────────────────


def print_report(base_ref: str, changed_files: list[str], *, context_detail: str = "compact", fmt: str = "text", audit: bool = False) -> None:
    matches = resolve_rule_matches(changed_files)
    pack = build_context_pack(changed_files, matches)

    if audit:
        pack.audit_warnings = audit_surface_coverage(changed_files, pack)

    if fmt == "json":
        print_report_json(pack, changed_files, base_ref)
        return

    print("Elephant Agent Harness Report")
    print(f"  Repo: {ROOT}")
    print(f"  Base ref: {base_ref or '<none>'}")
    print(f"  Changed files: {len(changed_files)}")
    if changed_files:
        for path in changed_files:
            print(f"    {path}")
    else:
        print("    (none — using default skill)")

    print()
    print("Primary Skill")
    print(f"  {pack.primary_skill}: {pack.primary_summary}")

    if pack.also_matched:
        print()
        print("Also Matched")
        for name in pack.also_matched:
            print(f"  - {name}")

    print()
    print("Read First")
    for path in pack.read_first:
        print(f"  - {path}")

    if context_detail == "full" and pack.surfaces:
        print()
        print("Surfaces")
        for surface_name, refs in pack.surfaces.items():
            print(f"  [{surface_name}]")
            for pattern in pack.surface_paths.get(surface_name, ()):
                print(f"    path: {pattern}")
            for ref in refs:
                reason_part = f" :: {ref.reason}" if ref.reason else ""
                print(f"    - {ref.path}{reason_part}")

    if pack.local_agents_md:
        print()
        print("Local Context")
        for path in pack.local_agents_md:
            print(f"  - {path}")

    print()
    print("Validation")
    if pack.validation:
        for command in pack.validation:
            print(f"  - {command}")
    else:
        print("  - make agent-validate")

    if context_detail == "full" and pack.acceptance_criteria:
        print()
        print("Acceptance Criteria")
        print(f"  {pack.acceptance_criteria}")

    print()
    print("Ship Default")
    print("  - If this diff is one controlled atomic unit and validation is green, ship it with:")
    print("  - make agent-ship AGENT_COMMIT_MESSAGE='<type>(<scope>): <summary>'")
    print("  - agent-ship reruns the PR gate, creates a signed commit, and pushes the current branch to origin.")
    print("  - Leave changes unshipped only when publish was explicitly deferred, the diff still needs splitting, or a validation failure remains.")

    if audit and pack.audit_warnings:
        print()
        print("Audit Warnings")
        for warning in pack.audit_warnings:
            print(f"  - {warning}")


def print_report_json(pack: ContextPack, changed_files: list[str], base_ref: str) -> None:
    output = {
        "base_ref": base_ref,
        "changed_files": changed_files,
        "primary_skill": pack.primary_skill,
        "primary_summary": pack.primary_summary,
        "also_matched": pack.also_matched,
        "start_here": [{"path": ref.path, "reason": ref.reason} for ref in pack.start_here],
        "read_first": pack.read_first,
        "surfaces": {
            name: {
                "path_patterns": list(pack.surface_paths.get(name, ())),
                "refs": [{"path": ref.path, "reason": ref.reason} for ref in refs],
            }
            for name, refs in pack.surfaces.items()
        },
        "local_agents_md": pack.local_agents_md,
        "validation": pack.validation,
        "acceptance_criteria": pack.acceptance_criteria,
        "audit_warnings": pack.audit_warnings,
    }
    print(json.dumps(output, indent=2))


# ─── Lint ──────────────────────────────────────────────────────────────────────


def lint_changed_files(changed_files: list[str]) -> list[str]:
    matrix = load_manifest(MATRIX_PATH)
    errors: list[str] = []
    for path in changed_files:
        if not any(match_any(path, rule.get("paths", [])) for rule in matrix.get("rules", [])):
            errors.append(f"changed file does not match any task surface: {path}")
    return errors


def _python_files_for_line_limit(changed_files: list[str], *, root: Path = ROOT) -> tuple[str, ...]:
    if changed_files:
        return tuple(
            dict.fromkeys(
                path
                for path in changed_files
                if match_any(path, PYTHON_LINE_LIMIT_PATTERNS)
                and not match_any(path, PYTHON_LINE_LIMIT_ALLOWLIST_PATTERNS)
            )
        )

    discovered: list[str] = []
    for surface in PYTHON_LINE_LIMIT_SURFACES:
        surface_root = root / surface
        if not surface_root.exists():
            continue
        for path in sorted(surface_root.rglob("*.py")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(root).as_posix()
            if match_any(relative_path, PYTHON_LINE_LIMIT_ALLOWLIST_PATTERNS):
                continue
            discovered.append(relative_path)
    return tuple(discovered)


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def lint_python_file_lengths(changed_files: list[str], *, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for relative_path in _python_files_for_line_limit(changed_files, root=root):
        path = root / relative_path
        if not path.exists():
            continue
        line_count = _line_count(path)
        if line_count > MAX_PYTHON_FILE_LINES:
            errors.append(
                f"python file exceeds {MAX_PYTHON_FILE_LINES} lines: {relative_path} ({line_count} lines)"
            )
    return errors


def frontend_typecheck_commands(changed_files: list[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    selected: list[tuple[str, tuple[str, ...]]] = []
    for name, patterns, command in FRONTEND_TYPECHECKS:
        if any(match_any(path, patterns) for path in changed_files):
            selected.append((name, command))
    return tuple(selected)


def run_frontend_typechecks(changed_files: list[str]) -> None:
    for name, command in frontend_typecheck_commands(changed_files):
        print(f"Running frontend typecheck: {name}")
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            raise SystemExit(result.returncode)


def run_compileall() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "compileall", "tools/agent/scripts", "tests"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def print_scorecard() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    matrix = load_manifest(MATRIX_PATH)
    registry = load_manifest(SKILL_REGISTRY_PATH)

    context_map = load_manifest(CONTEXT_MAP_PATH) if CONTEXT_MAP_PATH.exists() else {}
    surface_count = len(context_map.get("surfaces", {}))

    print("Elephant Agent Harness Scorecard")
    print(f"  Repo: {manifest['repo_name']}")
    print(f"  Read-first entries: {len(manifest.get('read_first', []))}")
    print(f"  Required paths: {len(manifest.get('required_paths', []))}")
    print(f"  Skills: {len(registry.get('skills', {}))}")
    print(f"  Task surfaces: {len(matrix.get('rules', []))}")
    print(f"  Context-map surfaces: {surface_count}")


# ─── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Elephant Agent harness gate commands.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("validate", "scorecard"):
        subparsers.add_parser(name)

    for name in ("report", "lint", "changed-files"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--base-ref", default="")
        sub.add_argument("--changed-files", default="")
        sub.add_argument("--changed-files-path", default="")
        if name == "report":
            sub.add_argument("--context-detail", choices=["compact", "full"], default="compact")
            sub.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
            sub.add_argument("--audit", action="store_true", default=False)

    args = parser.parse_args()

    if args.command == "validate":
        checks, errors = validate_contract()
        print("Elephant Agent Harness Validate")
        print(f"  Checks: {len(checks)}")
        print(f"  Errors: {len(errors)}")
        for check in checks:
            print(f"  - {check}")
        if errors:
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 1
        return 0

    if args.command == "scorecard":
        print_scorecard()
        return 0

    changed_files = collect_changed_files(args.base_ref, args.changed_files, args.changed_files_path)
    if args.command == "changed-files":
        for path in changed_files:
            print(path)
        return 0

    if args.command == "report":
        print_report(
            args.base_ref,
            changed_files,
            context_detail=args.context_detail,
            fmt=args.output_format,
            audit=args.audit,
        )
        return 0

    checks, errors = validate_contract()
    _ = checks
    errors.extend(lint_changed_files(changed_files))
    errors.extend(lint_python_file_lengths(changed_files))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    run_compileall()
    print("Elephant Agent Harness Lint")
    print("  Status: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
