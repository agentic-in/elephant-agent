from __future__ import annotations

import importlib.util
from pathlib import Path
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "agent" / "scripts" / "agent_gate.py"
TASK_MATRIX_PATH = ROOT / "tools" / "agent" / "task-matrix.yaml"
AGENT_MK_PATH = ROOT / "tools" / "make" / "agent.mk"
SPEC = importlib.util.spec_from_file_location("agent_gate", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AgentGateTests(unittest.TestCase):
    def test_match_any(self) -> None:
        self.assertTrue(MODULE.match_any("tools/agent/scripts/agent_gate.py", ["tools/agent/**"]))
        self.assertFalse(MODULE.match_any("README.md", ["tools/agent/**"]))
        self.assertFalse(MODULE.match_any("tools/agent/scripts/agent_gate.py", ["scripts/**"]))
        self.assertFalse(MODULE.match_any("docs/agent/README.md", ["README.md"]))
        self.assertFalse(MODULE.match_any("docs/agent/README.md", ["docs/*.md"]))
        self.assertTrue(MODULE.match_any("docs/README.md", ["docs/*.md"]))

    def test_parse_repo_name_from_remote_url(self) -> None:
        self.assertEqual(MODULE.parse_repo_name_from_remote_url("git@github.com:agentic-in/elephant.git"), "elephant")
        self.assertEqual(MODULE.parse_repo_name_from_remote_url("https://github.com/agentic-in/elephant.git"), "elephant")

    def test_resolve_repo_identity_name_uses_git_common_dir_name(self) -> None:
        completed = mock.Mock(returncode=0, stdout="/tmp/repos/elephant\n")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            self.assertEqual(MODULE.resolve_repo_identity_name(Path("/tmp/activitytrees/fnd-3")), "elephant")

    def test_resolve_repo_identity_name_uses_origin_when_common_dir_is_plain_git_dir(self) -> None:
        common_dir = mock.Mock(returncode=0, stdout=".git\n")
        remote = mock.Mock(returncode=0, stdout="git@github.com:agentic-in/elephant.git\n")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=[common_dir, remote]):
            self.assertEqual(MODULE.resolve_repo_identity_name(Path("/tmp/custom-dir")), "elephant")

    def test_resolve_repo_identity_name_falls_back_to_root_name(self) -> None:
        common_dir = mock.Mock(returncode=1, stdout="")
        remote = mock.Mock(returncode=1, stdout="")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=[common_dir, remote]):
            self.assertEqual(MODULE.resolve_repo_identity_name(Path("/tmp/activitytrees/fnd-3")), "fnd-3")

    def test_validate_contract_accepts_checkout_alias_during_repo_rename(self) -> None:
        with mock.patch.object(MODULE, "resolve_repo_identity_name", return_value="a" + "egis"):
            checks, errors = MODULE.validate_contract()

        self.assertTrue(checks)
        self.assertEqual(errors, [])

    def test_validate_contract(self) -> None:
        checks, errors = MODULE.validate_contract()
        self.assertTrue(checks)
        self.assertEqual(errors, [])

    def test_scan_reset_banned_terms_reports_removed_surface_language(self) -> None:
        removed_term = " ".join(("voice", "mode"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "surface.txt"
            target.write_text(f"{removed_term} remains available\n", encoding="utf-8")

            errors = MODULE.scan_reset_banned_terms(
                root=root,
                surfaces=("surface.txt",),
                banned_terms=((removed_term, "speech-mode contract is removed from reset surfaces"),),
            )

        self.assertEqual(
            errors,
            [
                f"reset banned term in surface.txt:1: {removed_term} "
                "(speech-mode contract is removed from reset surfaces)"
            ],
        )

    def test_scan_reset_banned_terms_accepts_clean_surface(self) -> None:
        removed_term = " ".join(("voice", "mode"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "surface.txt"
            target.write_text("canonical continuity matrix\n", encoding="utf-8")

            errors = MODULE.scan_reset_banned_terms(
                root=root,
                surfaces=("surface.txt",),
                banned_terms=((removed_term, "speech-mode contract is removed from reset surfaces"),),
            )

        self.assertEqual(errors, [])

    def test_collect_changed_files_accepts_space_and_comma_lists(self) -> None:
        self.assertEqual(
            MODULE.collect_changed_files("", "tools/agent/context-map.yaml .github/workflows/agent-lint.yml", ""),
            ["tools/agent/context-map.yaml", ".github/workflows/agent-lint.yml"],
        )
        self.assertEqual(
            MODULE.collect_changed_files("", "tools/agent/context-map.yaml,.github/workflows/agent-lint.yml", ""),
            ["tools/agent/context-map.yaml", ".github/workflows/agent-lint.yml"],
        )

    def test_scan_reset_banned_terms_defaults_to_tracked_files_with_allowlist(self) -> None:
        removed_term = " ".join(("goal", "graph"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            blocked = root / "blocked.txt"
            allowed = root / "allowed.md"
            blocked.write_text(f"{removed_term} remains\n", encoding="utf-8")
            allowed.write_text(f"{removed_term} is historical\n", encoding="utf-8")
            completed = mock.Mock(returncode=0, stdout="blocked.txt\0allowed.md\0")

            with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
                errors = MODULE.scan_reset_banned_terms(
                    root=root,
                    banned_terms=((removed_term, "current-work wording is required"),),
                    allowlist_patterns=("allowed.md",),
                )

        self.assertEqual(
            errors,
            [
                f"reset banned term in blocked.txt:1: {removed_term} "
                "(current-work wording is required)"
            ],
        )

    def test_resolve_rules_for_ci_workflow(self) -> None:
        matches = MODULE.resolve_rule_matches([".github/workflows/ci.yml"])
        names = [match.name for match in matches]
        self.assertIn("release-ops", names)

    def test_surface_paths_are_loaded_from_context_map(self) -> None:
        surface_paths = MODULE.load_surface_path_map()
        self.assertIn("packages/runtime_config.py", surface_paths["infra"])
        self.assertIn("infra", MODULE.resolve_surfaces_for_files(["packages/runtime_config.py"]))

    def test_full_report_includes_surface_path_patterns(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MODULE.print_report("", ["apps/cli/cli_main_impl.py"], context_detail="full")

        output = buffer.getvalue()
        self.assertIn("Surfaces", output)
        self.assertIn("[cli]", output)
        self.assertIn("path: apps/cli/**", output)

    def test_full_report_only_includes_touched_frontend_surface(self) -> None:
        matches = MODULE.resolve_rule_matches(["apps/site/src/pages/index.tsx"])
        pack = MODULE.build_context_pack(["apps/site/src/pages/index.tsx"], matches)

        self.assertEqual(set(pack.surfaces), {"site"})

    def test_app_scaffold_surface_covers_root_scaffold_files(self) -> None:
        self.assertIn("app_scaffold", MODULE.resolve_surfaces_for_files(["pyproject.toml"]))
        matches = MODULE.resolve_rule_matches(["pyproject.toml"])
        pack = MODULE.build_context_pack(["pyproject.toml"], matches)

        self.assertEqual(set(pack.surfaces), {"app_scaffold"})

    def test_audit_warning_prints_context_repair_prompt(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MODULE.print_report("", ["unknown/path.txt"], audit=True)

        output = buffer.getvalue()
        self.assertIn("Audit Warnings", output)
        self.assertIn("Context Repair", output)
        self.assertIn("tools/agent/context-map.yaml", output)

    def test_validate_compact_hides_check_details(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MODULE.print_validate_result(["check detail"], [], detail="compact")

        output = buffer.getvalue()
        self.assertIn("Checks: 1", output)
        self.assertNotIn("check detail", output)

    def test_context_map_covers_harness_and_release_paths(self) -> None:
        matches = MODULE.resolve_rule_matches(
            [
                "tools/agent/context-map.yaml",
                ".github/workflows/agent-lint.yml",
                ".github/copilot-instructions.md",
                "docs/agent/context-management.md",
            ]
        )
        pack = MODULE.build_context_pack(
            [
                "tools/agent/context-map.yaml",
                ".github/workflows/agent-lint.yml",
                ".github/copilot-instructions.md",
                "docs/agent/context-management.md",
            ],
            matches,
        )

        self.assertEqual(MODULE.audit_surface_coverage([], pack), [])
        self.assertEqual(
            MODULE.audit_surface_coverage(
                [
                    "tools/agent/context-map.yaml",
                    ".github/workflows/agent-lint.yml",
                    ".github/copilot-instructions.md",
                    "docs/agent/context-management.md",
                ],
                pack,
            ),
            [],
        )

    def test_resolve_rules_for_root_make_and_gitignore(self) -> None:
        matches = MODULE.resolve_rule_matches(["Makefile", ".gitignore"])
        names = [match.name for match in matches]
        self.assertIn("agent-exec", names)

    def test_print_report_includes_default_ship_closeout(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MODULE.print_report("", ["apps/site/index.html"])

        output = buffer.getvalue()
        self.assertIn("Ship Default", output)
        self.assertIn("make agent-ship AGENT_COMMIT_MESSAGE", output)

    def test_default_report_uses_default_skill_summary(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MODULE.print_report("", ["unknown/path.txt"])

        output = buffer.getvalue()
        self.assertIn("repo-docs: Top-level docs", output)

    def test_task_matrix_tracks_root_build_and_ignore_files(self) -> None:
        task_matrix_text = TASK_MATRIX_PATH.read_text(encoding="utf-8")
        self.assertIn('"*_CODE_ANALYSIS.md"', task_matrix_text)
        self.assertIn('".gitignore"', task_matrix_text)
        self.assertIn('"Makefile"', task_matrix_text)
        self.assertIn('"pyproject.toml"', task_matrix_text)

    def test_python_line_limit_skips_legacy_large_modules(self) -> None:
        files = MODULE._python_files_for_line_limit(
            [
                "apps/api/api_runtime_console_ops.py",
                "packages/evidence/runtime.py",
                "packages/models/providers/openai_compatible.py",
                "packages/storage/repository_system_methods.py",
                "apps/cli/runtime_cognition.py",
            ]
        )

        self.assertEqual(files, ("apps/cli/runtime_cognition.py",))

    def test_frontend_typecheck_commands_select_dashboard_and_site(self) -> None:
        commands = MODULE.frontend_typecheck_commands([
            "apps/dashboard/src/routes/console/ConsolePages.tsx",
            "apps/site/src/pages/index.tsx",
            "packages/state/config.py",
        ])
        self.assertEqual(
            commands,
            (
                ("dashboard", ("npm", "--prefix", "apps/dashboard", "run", "typecheck")),
                ("site", ("npm", "--prefix", "apps/site", "run", "typecheck")),
            ),
        )

    def test_run_frontend_typechecks_executes_selected_commands(self) -> None:
        completed = mock.Mock(returncode=0)
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run_mock:
            MODULE.run_frontend_typechecks(["apps/dashboard/src/main.tsx"])

        run_mock.assert_called_once_with(
            ("npm", "--prefix", "apps/dashboard", "run", "typecheck"),
            cwd=ROOT,
            check=False,
        )

    def test_run_frontend_typechecks_raises_on_failure(self) -> None:
        completed = mock.Mock(returncode=2)
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            with self.assertRaises(SystemExit) as context:
                MODULE.run_frontend_typechecks(["apps/dashboard/src/main.tsx"])
        self.assertEqual(context.exception.code, 2)

    def test_agent_pr_gate_fails_fast_after_first_error(self) -> None:
        agent_mk_text = AGENT_MK_PATH.read_text(encoding="utf-8")
        self.assertIn("@set -e; \\", agent_mk_text)

    def test_makefile_exposes_phony_lint_alias(self) -> None:
        makefile_text = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn(".PHONY: help lint", makefile_text)
        self.assertIn("lint: ## Run repository lint checks", makefile_text)
        self.assertIn("build-and-test:", makefile_text)
        self.assertIn("e2e:", makefile_text)
        self.assertIn("release:", makefile_text)

    def test_ci_lint_uses_commit_range_instead_of_full_repo_scan(self) -> None:
        workflow_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('make build-and-test AGENT_BASE_REF="origin/${{ github.base_ref }}"', workflow_text)
        self.assertIn('BASE_REF="${{ github.event.before }}"', workflow_text)
        self.assertIn('make build-and-test AGENT_BASE_REF="$BASE_REF"', workflow_text)


if __name__ == "__main__":
    unittest.main()
