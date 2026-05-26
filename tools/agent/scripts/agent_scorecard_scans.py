from __future__ import annotations

import ast
import fnmatch
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable


ROOT = Path(__file__).resolve().parents[3]
MAX_PYTHON_FILE_LINES = 1000
PYTHON_LINE_LIMIT_SURFACES = ("apps", "packages")
PYTHON_LINE_LIMIT_PATTERNS = tuple(f"{surface}/**/*.py" for surface in PYTHON_LINE_LIMIT_SURFACES)
PYTHON_LINE_LIMIT_DISCOVERY_SKIP_PARTS = (
    ".build",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
)
PYTHON_LINE_LIMIT_ALLOWLIST_PATTERNS: tuple[str, ...] = (
    "apps/cli/cli_main_impl.py",
    "packages/embeddings/runtime.py",
    "packages/sandbox/executor.py",
)


APP_IMPORT_BOUNDARY_SOURCE_EXCEPTIONS: tuple[str, ...] = (
    "apps/cli_runtime_bridge.py",
    "apps/cron_scheduler_command.py",
    "apps/daemon.py",
    "apps/daemon_http.py",
    "apps/daemon_tasks.py",
    "apps/dashboard_static_server.py",
    "apps/launcher.py",
    "apps/learning_worker_runtime.py",
    "apps/sandbox_command.py",
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
    "tools/agent/scripts/agent_scorecard_scans.py",
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
APP_IMPORT_BOUNDARY_ALLOWLIST: tuple[tuple[str, str], ...] = ()
BROAD_EXCEPTION_NAMES = frozenset({"BaseException", "Exception"})
OBSERVABLE_EXCEPTION_CALL_NAMES = frozenset(
    {
        "critical",
        "debug",
        "emit",
        "error",
        "exception",
        "info",
        "log",
        "print",
        "record",
        "warning",
        "warn",
    }
)


def _git_output_lines(args: list[str], *, root: Path = ROOT) -> tuple[str, ...]:
    result = subprocess.run(
        args,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _working_tree_changed_files(*, root: Path = ROOT) -> tuple[str, ...]:
    tracked = _git_output_lines(["git", "diff", "--name-only", "HEAD"], root=root)
    if not tracked:
        tracked = _git_output_lines(["git", "diff", "--name-only"], root=root)
    untracked = _git_output_lines(["git", "ls-files", "--others", "--exclude-standard"], root=root)
    return tuple(dict.fromkeys([*tracked, *untracked]))


def match_any(path: str, patterns: Iterable[str]) -> bool:
    pure = PurePosixPath(path)
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if path == prefix or path.startswith(prefix + "/"):
                return True
            continue
        if "/" not in pattern:
            if "/" not in path and fnmatch.fnmatch(path, pattern):
                return True
            continue
        pattern_parts = PurePosixPath(pattern).parts
        if pattern_parts and pure.parts and pattern_parts[0] == pure.parts[0] and pure.match(pattern):
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


def _tracked_python_files(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _python_files_for_line_limit(root: Path) -> tuple[str, ...]:
    discovered: list[str] = []
    for surface in PYTHON_LINE_LIMIT_SURFACES:
        surface_root = root / surface
        if not surface_root.exists():
            continue
        for path in sorted(surface_root.rglob("*.py")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(root).as_posix()
            if any(
                part in PYTHON_LINE_LIMIT_DISCOVERY_SKIP_PARTS
                for part in PurePosixPath(relative_path).parts
            ):
                continue
            if match_any(relative_path, PYTHON_LINE_LIMIT_ALLOWLIST_PATTERNS):
                continue
            discovered.append(relative_path)
    return tuple(discovered)


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


def scan_app_import_boundaries(
    *,
    root: Path = ROOT,
    surfaces: Iterable[str] | None = None,
    allowlist: Iterable[tuple[str, str]] = APP_IMPORT_BOUNDARY_ALLOWLIST,
) -> list[str]:
    allowed = set(allowlist)
    errors: list[str] = []
    for relative_path, line_number, imported_module in app_import_boundary_records(root=root, surfaces=surfaces):
        if (relative_path, imported_module) in allowed:
            continue
        errors.append(
            f"app-to-app import in {relative_path}:{line_number}: {imported_module} "
            "(move shared behavior to packages or register an explicit boundary debt)"
        )
    return errors


def silent_broad_exception_records(
    *,
    root: Path = ROOT,
    surfaces: Iterable[str] | None = None,
) -> tuple[tuple[str, int], ...]:
    """Return broad exception handlers that do not surface their failure.

    This is a scorecard metric, not a validation failure. It intentionally
    prefers a conservative signal over perfect static analysis: broad handlers
    are considered observable when they log/print/emit/record, re-raise, or
    include the caught exception object in their fallback payload.
    """
    if surfaces is None:
        relative_paths = _python_surface_files_for_scorecard(root)
    else:
        relative_paths = tuple(
            path
            for path in surfaces
            if path.endswith(".py") and match_any(path, PYTHON_LINE_LIMIT_PATTERNS)
        )
    records: list[tuple[str, int]] = []
    for relative_path in relative_paths:
        path = root / relative_path
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _catches_broad_exception(node.type):
                continue
            if _handler_has_observable_failure_signal(node):
                continue
            records.append((relative_path, node.lineno))
    return tuple(records)


def _python_surface_files_for_scorecard(root: Path) -> tuple[str, ...]:
    files = list(_tracked_python_files(root))
    files.extend(_working_tree_changed_files(root=root))
    selected = [
        path
        for path in dict.fromkeys(files)
        if path.endswith(".py")
        and match_any(path, PYTHON_LINE_LIMIT_PATTERNS)
        and not any(
            part in PYTHON_LINE_LIMIT_DISCOVERY_SKIP_PARTS
            for part in PurePosixPath(path).parts
        )
    ]
    if selected:
        return tuple(selected)
    return _python_files_for_line_limit(root)


def _catches_broad_exception(exception_type: ast.expr | None) -> bool:
    if exception_type is None:
        return True
    if isinstance(exception_type, ast.Name):
        return exception_type.id in BROAD_EXCEPTION_NAMES
    if isinstance(exception_type, ast.Attribute):
        return exception_type.attr in BROAD_EXCEPTION_NAMES
    if isinstance(exception_type, ast.Tuple):
        return any(_catches_broad_exception(item) for item in exception_type.elts)
    return False


def _handler_has_observable_failure_signal(handler: ast.ExceptHandler) -> bool:
    caught_name = handler.name if isinstance(handler.name, str) else ""
    probe = ast.Module(body=list(handler.body), type_ignores=[])
    for node in ast.walk(probe):
        if isinstance(node, ast.Raise):
            return True
        if caught_name and isinstance(node, ast.Name) and node.id == caught_name:
            return True
        if isinstance(node, ast.Call) and _call_name(node.func) in OBSERVABLE_EXCEPTION_CALL_NAMES:
            return True
    return False


def _call_name(function: ast.expr) -> str:
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def app_import_boundary_records(
    *,
    root: Path = ROOT,
    surfaces: Iterable[str] | None = None,
) -> tuple[tuple[str, int, str], ...]:
    relative_paths = tuple(surfaces) if surfaces is not None else collect_tracked_files(root)
    records: list[tuple[str, int, str]] = []
    for relative_path in relative_paths:
        if not relative_path.startswith("apps/") or not relative_path.endswith(".py"):
            continue
        if relative_path in APP_IMPORT_BOUNDARY_SOURCE_EXCEPTIONS:
            continue
        path = root / relative_path
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            records.append((relative_path, 1, f"<parse-error:{exc.__class__.__name__}>"))
            continue
        source_app = _source_app_name(relative_path)
        for node in ast.walk(tree):
            for imported_module in _apps_imported_modules(node):
                target_app = _target_app_name(imported_module)
                if not target_app:
                    continue
                if target_app == source_app:
                    continue
                if _is_root_app_support_module(target_app, root=root):
                    continue
                records.append((relative_path, getattr(node, "lineno", 1), imported_module))
    return tuple(records)


def _source_app_name(relative_path: str) -> str:
    parts = PurePosixPath(relative_path).parts
    if len(parts) >= 3 and parts[0] == "apps":
        return parts[1]
    return ""


def _target_app_name(imported_module: str) -> str:
    parts = imported_module.split(".")
    if len(parts) >= 2 and parts[0] == "apps":
        return parts[1]
    return ""


def _is_root_app_support_module(module_name: str, *, root: Path = ROOT) -> bool:
    return (root / "apps" / f"{module_name}.py").exists()


def _apps_imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names if alias.name.startswith("apps."))
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module.startswith("apps."):
        return (node.module,)
    return ()
