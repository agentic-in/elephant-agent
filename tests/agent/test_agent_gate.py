from __future__ import annotations

import importlib.util
import json
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

    def test_collect_changed_files_includes_dirty_tree_with_base_ref(self) -> None:
        def fake_run(args, **_: object):
            stdout_by_command = {
                ("git", "diff", "--name-only", "origin/main...HEAD"): "packages/kernel/runtime.py\n",
                ("git", "diff", "--name-only", "HEAD"): "packages/reflect/trajectory_signals.py\n",
                ("git", "ls-files", "--others", "--exclude-standard"): "packages/reflect/AGENTS.md\n",
            }
            return mock.Mock(returncode=0, stdout=stdout_by_command.get(tuple(args), ""))

        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            self.assertEqual(
                MODULE.collect_changed_files("origin/main", "", ""),
                [
                    "packages/kernel/runtime.py",
                    "packages/reflect/trajectory_signals.py",
                    "packages/reflect/AGENTS.md",
                ],
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

    def test_scan_app_import_boundaries_reports_new_cross_app_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "apps" / "alpha"
            source_dir.mkdir(parents=True)
            (source_dir / "feature.py").write_text(
                "\n".join(
                    [
                        "from apps.beta import service",
                        "from apps.alpha import local",
                        "from apps.shared_support import helper",
                        "import apps.gamma.worker as gamma_worker",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "apps" / "shared_support.py").write_text("helper = object()\n", encoding="utf-8")

            errors = MODULE.scan_app_import_boundaries(
                root=root,
                surfaces=("apps/alpha/feature.py",),
                allowlist=(),
            )

        self.assertEqual(
            errors,
            [
                "app-to-app import in apps/alpha/feature.py:1: apps.beta "
                "(move shared behavior to packages or register an explicit boundary debt)",
                "app-to-app import in apps/alpha/feature.py:4: apps.gamma.worker "
                "(move shared behavior to packages or register an explicit boundary debt)",
            ],
        )

    def test_scan_app_import_boundaries_accepts_explicit_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "apps" / "alpha"
            source_dir.mkdir(parents=True)
            (source_dir / "feature.py").write_text(
                "from apps.beta import service\n",
                encoding="utf-8",
            )

            errors = MODULE.scan_app_import_boundaries(
                root=root,
                surfaces=("apps/alpha/feature.py",),
                allowlist=(("apps/alpha/feature.py", "apps.beta"),),
            )

        self.assertEqual(errors, [])

    def test_scan_app_import_boundaries_ignores_documented_top_level_support_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "apps"
            source_dir.mkdir(parents=True)
            filenames = (
                "cli_runtime_bridge.py",
                "cron_scheduler_command.py",
                "daemon.py",
                "daemon_http.py",
                "daemon_tasks.py",
                "dashboard_static_server.py",
                "launcher.py",
                "learning_worker_runtime.py",
            )
            for filename in filenames:
                (source_dir / filename).write_text(
                    "from apps.cli import __main__ as cli_main\n"
                    "from apps.gateway import __main__ as gateway_main\n",
                    encoding="utf-8",
                )

            errors = []
            for filename in filenames:
                errors.extend(
                    MODULE.scan_app_import_boundaries(
                        root=root,
                        surfaces=(f"apps/{filename}",),
                        allowlist=(),
                    )
                )

        self.assertEqual(errors, [])

    def test_public_contract_inventory_accepts_paths_markers_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            api_dir = root / "apps" / "api"
            package_dir = root / "packages" / "demo"
            api_dir.mkdir(parents=True)
            package_dir.mkdir(parents=True)
            (api_dir / "routes.py").write_text(
                'if parts[0] == "providers":\n    pass\n',
                encoding="utf-8",
            )
            (package_dir / "__init__.py").write_text(
                '__all__ = ["DemoService", "DemoResult"]\n',
                encoding="utf-8",
            )
            inventory_path = root / "public-contracts.json"
            inventory_path.write_text(
                json.dumps(
                    {
                        "http_routes": [
                            {
                                "id": "api.v1.providers",
                                "owner": "apps/api/routes.py",
                                "contains": ['parts[0] == "providers"'],
                            }
                        ],
                        "package_exports": [
                            {
                                "package": "packages.demo",
                                "owner": "packages/demo/__init__.py",
                                "exports": ["DemoService"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            errors = MODULE.public_contract_inventory_errors(
                root=root,
                path=inventory_path,
                required_sections=("http_routes", "package_exports"),
            )

        self.assertEqual(errors, [])

    def test_public_contract_inventory_reports_missing_paths_markers_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            api_dir = root / "apps" / "api"
            package_dir = root / "packages" / "demo"
            api_dir.mkdir(parents=True)
            package_dir.mkdir(parents=True)
            (api_dir / "routes.py").write_text("pass\n", encoding="utf-8")
            (package_dir / "__init__.py").write_text('__all__ = ["DemoService"]\n', encoding="utf-8")
            inventory_path = root / "public-contracts.json"
            inventory_path.write_text(
                json.dumps(
                    {
                        "http_routes": [
                            {
                                "id": "api.v1.providers",
                                "owner": "apps/api/routes.py",
                                "contains": ['parts[0] == "providers"'],
                            },
                            {
                                "id": "api.v1.missing",
                                "owner": "apps/api/missing.py",
                            },
                        ],
                        "package_exports": [
                            {
                                "package": "packages.demo",
                                "owner": "packages/demo/__init__.py",
                                "exports": ["DemoResult"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            errors = MODULE.public_contract_inventory_errors(
                root=root,
                path=inventory_path,
                required_sections=("http_routes", "package_exports"),
            )

        self.assertIn(
            'public contract api.v1.providers missing owner marker in apps/api/routes.py: parts[0] == "providers"',
            errors,
        )
        self.assertIn(
            "public contract api.v1.missing references missing owner: apps/api/missing.py",
            errors,
        )
        self.assertIn(
            "public package export missing from packages/demo/__init__.py: DemoResult",
            errors,
        )

    def test_public_contract_docs_render_key_sections(self) -> None:
        markdown = MODULE.render_public_contract_inventory_markdown()

        self.assertIn("# Public Contract Inventory", markdown)
        self.assertIn("## HTTP Routes", markdown)
        self.assertIn("api.healthz", markdown)
        self.assertIn("## Package Exports", markdown)
        self.assertIn("packages.kernel", markdown)
        self.assertIn("## Compatibility Contracts", markdown)
        self.assertIn("compat.cli.wizard", markdown)
        self.assertIn("## Runtime Resource Contracts", markdown)

    def test_public_contract_docs_errors_report_stale_generated_doc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_dir = root / "docs" / "agent"
            docs_dir.mkdir(parents=True)
            inventory_path = root / "public-contracts.json"
            doc_path = docs_dir / "public-contracts.md"
            inventory_path.write_text(
                json.dumps(
                    {
                        "http_routes": [
                            {
                                "id": "api.healthz",
                                "method": "GET",
                                "path": "/healthz",
                                "owner": "apps/api/routes.py",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            expected = MODULE.render_public_contract_inventory_markdown(
                root=root,
                inventory_path=inventory_path,
                required_sections=("http_routes",),
            )
            doc_path.write_text(expected, encoding="utf-8")

            self.assertEqual(
                MODULE.public_contract_docs_errors(
                    root=root,
                    inventory_path=inventory_path,
                    doc_path=doc_path,
                    required_sections=("http_routes",),
                ),
                [],
            )

            doc_path.write_text("stale\n", encoding="utf-8")
            errors = MODULE.public_contract_docs_errors(
                root=root,
                inventory_path=inventory_path,
                doc_path=doc_path,
                required_sections=("http_routes",),
            )

        self.assertEqual(
            errors,
            [
                "generated public contract docs are stale: docs/agent/public-contracts.md "
                "(run make agent-public-contracts-docs)"
            ],
        )

    def test_silent_broad_exception_records_report_unobservable_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "packages" / "sample"
            source_dir.mkdir(parents=True)
            target = source_dir / "feature.py"
            target.write_text(
                "\n".join(
                    [
                        "def silent():",
                        "    try:",
                        "        work()",
                        "    except Exception:",
                        "        return None",
                        "",
                        "def logged():",
                        "    try:",
                        "        work()",
                        "    except Exception:",
                        "        logger.debug('failed', exc_info=True)",
                        "        return None",
                        "",
                        "def payload():",
                        "    try:",
                        "        work()",
                        "    except Exception as exc:",
                        "        return {'error': str(exc)}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            records = MODULE.silent_broad_exception_records(
                root=root,
                surfaces=("packages/sample/feature.py",),
            )

        self.assertEqual(records, (("packages/sample/feature.py", 4),))

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

    def test_audit_ignores_local_agents_docs_as_surface_drift(self) -> None:
        matches = MODULE.resolve_rule_matches(["packages/growth/AGENTS.md"])
        pack = MODULE.build_context_pack(["packages/growth/AGENTS.md"], matches)

        self.assertEqual(MODULE.audit_surface_coverage(["packages/growth/AGENTS.md"], pack), [])

    def test_audit_uses_also_matched_skill_surface_coverage(self) -> None:
        changed_files = ["packages/semantic_index/AGENTS.md", "tools/agent/context-map.yaml"]
        matches = MODULE.resolve_rule_matches(changed_files)
        pack = MODULE.build_context_pack(changed_files, matches)

        self.assertEqual(MODULE.audit_surface_coverage(changed_files, pack), [])

    def test_validate_compact_hides_check_details(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MODULE.print_validate_result(["check detail"], [], detail="compact")

        output = buffer.getvalue()
        self.assertIn("Checks: 1", output)
        self.assertNotIn("check detail", output)

    def test_scorecard_reports_hotspot_and_boundary_debt_counts(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            MODULE.print_scorecard()

        output = buffer.getvalue()
        self.assertIn("Python line-limit allowlist debt:", output)
        self.assertIn("App import boundary allowlist debt:", output)
        self.assertIn("Silent broad exception debt:", output)
        self.assertIn("Public contract inventory debt:", output)

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

        self.assertEqual(
            files,
            (
                "apps/api/api_runtime_console_ops.py",
                "packages/evidence/runtime.py",
                "packages/storage/repository_system_methods.py",
                "apps/cli/runtime_cognition.py",
            ),
        )

    def test_python_line_limit_full_scan_ignores_generated_runtime_trees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "apps" / "cli"
            source_dir.mkdir(parents=True)
            (source_dir / "small.py").write_text("print('ok')\n", encoding="utf-8")
            generated_dir = root / "apps" / "macos" / ".build" / "vendor"
            generated_dir.mkdir(parents=True)
            (generated_dir / "bad.py").write_bytes(b"\xa4\x00not utf8")

            errors = MODULE.lint_python_file_lengths([], root=root)

        self.assertEqual(errors, [])

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
                ("site", ("npm", "--prefix", "apps/site", "run", "ci:check")),
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

    def test_lint_command_runs_frontend_typechecks_for_changed_files(self) -> None:
        changed_files = ["apps/site/src/pages/index.tsx"]
        with (
            mock.patch.object(sys, "argv", ["agent_gate.py", "lint"]),
            mock.patch.object(MODULE, "collect_changed_files", return_value=changed_files),
            mock.patch.object(MODULE, "validate_contract", return_value=([object()], [])),
            mock.patch.object(MODULE, "lint_changed_files", return_value=[]),
            mock.patch.object(MODULE, "lint_python_file_lengths", return_value=[]),
            mock.patch.object(MODULE, "run_frontend_typechecks") as frontend_mock,
            mock.patch.object(MODULE, "run_compileall") as compileall_mock,
        ):
            result = MODULE.main()

        self.assertEqual(result, 0)
        frontend_mock.assert_called_once_with(changed_files)
        compileall_mock.assert_called_once_with()

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
