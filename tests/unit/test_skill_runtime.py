"""Unit tests for packages.skills.runtime core types and wiring logic."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.skills.runtime import (
    InMemorySkillCatalog,
    SkillActivationContext,
    SkillActivationRecord,
    SkillDefinition,
    SkillDependency,
    SkillManifest,
    SkillRuntime,
    SkillScope,
    _first_heading,
    _first_summary,
    _frontmatter_bool,
    _frontmatter_string_list,
    _skill_command_slug,
    _split_frontmatter,
    load_skill_package_definition,
)
from packages.contracts import State


def _make_skill(**overrides: object) -> SkillDefinition:
    defaults: dict[str, object] = {
        "skill_id": "test-skill",
        "display_name": "Test Skill",
        "version": "1.0.0",
        "summary": "A test skill.",
    }
    defaults.update(overrides)
    return SkillDefinition(**defaults)  # type: ignore[arg-type]


# ── SkillScope ──────────────────────────────────────────────────────────


class TestSkillScope(unittest.TestCase):
    def test_empty_scope_matches_everything(self) -> None:
        scope = SkillScope()
        self.assertTrue(scope.matches(
            personal_model_id="any", state_id="any",
            surface_id="any", surface_kind="any", mode="any",
        ))

    def test_personal_model_id_filter(self) -> None:
        scope = SkillScope(personal_model_ids=("pm-1",))
        self.assertTrue(scope.matches(
            personal_model_id="pm-1", state_id="", surface_id="", surface_kind="", mode="",
        ))
        self.assertFalse(scope.matches(
            personal_model_id="pm-2", state_id="", surface_id="", surface_kind="", mode="",
        ))

    def test_state_id_filter(self) -> None:
        scope = SkillScope(state_ids=("st-1",))
        self.assertTrue(scope.matches(
            personal_model_id="", state_id="st-1", surface_id="", surface_kind="", mode="",
        ))
        self.assertFalse(scope.matches(
            personal_model_id="", state_id="st-2", surface_id="", surface_kind="", mode="",
        ))

    def test_surface_id_filter(self) -> None:
        scope = SkillScope(surface_ids=("surf-1",))
        self.assertTrue(scope.matches(
            personal_model_id="", state_id="", surface_id="surf-1", surface_kind="", mode="",
        ))
        self.assertFalse(scope.matches(
            personal_model_id="", state_id="", surface_id="surf-2", surface_kind="", mode="",
        ))

    def test_surface_kind_filter(self) -> None:
        scope = SkillScope(surface_kinds=("cli",))
        self.assertTrue(scope.matches(
            personal_model_id="", state_id="", surface_id="", surface_kind="cli", mode="",
        ))
        self.assertFalse(scope.matches(
            personal_model_id="", state_id="", surface_id="", surface_kind="api", mode="",
        ))

    def test_mode_filter(self) -> None:
        scope = SkillScope(modes=("auto",))
        self.assertTrue(scope.matches(
            personal_model_id="", state_id="", surface_id="", surface_kind="", mode="auto",
        ))
        self.assertFalse(scope.matches(
            personal_model_id="", state_id="", surface_id="", surface_kind="", mode="manual",
        ))

    def test_combined_filters(self) -> None:
        scope = SkillScope(personal_model_ids=("pm-1",), modes=("auto",))
        self.assertTrue(scope.matches(
            personal_model_id="pm-1", state_id="", surface_id="", surface_kind="", mode="auto",
        ))
        self.assertFalse(scope.matches(
            personal_model_id="pm-1", state_id="", surface_id="", surface_kind="", mode="manual",
        ))
        self.assertFalse(scope.matches(
            personal_model_id="pm-2", state_id="", surface_id="", surface_kind="", mode="auto",
        ))


# ── InMemorySkillCatalog ────────────────────────────────────────────────


class TestInMemorySkillCatalog(unittest.TestCase):
    def test_register_and_get(self) -> None:
        catalog = InMemorySkillCatalog()
        skill = _make_skill()
        catalog.register(skill)
        self.assertEqual(catalog.get("test-skill"), skill)

    def test_get_missing_returns_none(self) -> None:
        catalog = InMemorySkillCatalog()
        self.assertIsNone(catalog.get("no.such.skill"))

    def test_register_duplicate_same_definition_ok(self) -> None:
        catalog = InMemorySkillCatalog()
        skill = _make_skill()
        catalog.register(skill)
        catalog.register(skill)  # Same definition, should not raise

    def test_register_duplicate_different_raises(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(_make_skill())
        with self.assertRaises(ValueError):
            catalog.register(_make_skill(version="2.0.0"))

    def test_list(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(_make_skill(skill_id="a"))
        catalog.register(_make_skill(skill_id="b"))
        ids = {s.skill_id for s in catalog.list()}
        self.assertEqual(ids, {"a", "b"})

    def test_resolve_for_context(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(_make_skill(skill_id="scoped", scope=SkillScope(modes=("auto",))))
        catalog.register(_make_skill(skill_id="unscoped"))
        resolved = catalog.resolve_for_context(
            personal_model_id="", state_id="", surface_id="",
            surface_kind="", mode="auto",
        )
        ids = {s.skill_id for s in resolved}
        self.assertIn("scoped", ids)
        self.assertIn("unscoped", ids)

    def test_resolve_excludes_non_matching_scope(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(_make_skill(skill_id="only-cli", scope=SkillScope(surface_kinds=("cli",))))
        resolved = catalog.resolve_for_context(
            personal_model_id="", state_id="", surface_id="",
            surface_kind="api", mode="auto",
        )
        ids = {s.skill_id for s in resolved}
        self.assertNotIn("only-cli", ids)

    def test_validate_dependencies(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(_make_skill(skill_id="a"))
        catalog.register(_make_skill(
            skill_id="b",
            dependencies=(SkillDependency(skill_id="a", required=True),),
        ))
        self.assertEqual(catalog.validate_dependencies("b"), ())

    def test_validate_missing_dependencies(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(_make_skill(
            skill_id="b",
            dependencies=(SkillDependency(skill_id="missing", required=True),),
        ))
        self.assertEqual(catalog.validate_dependencies("b"), ("missing",))

    def test_validate_optional_dependencies_not_reported(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(_make_skill(
            skill_id="b",
            dependencies=(SkillDependency(skill_id="missing", required=False),),
        ))
        self.assertEqual(catalog.validate_dependencies("b"), ())

    def test_set_enabled(self) -> None:
        catalog = InMemorySkillCatalog()
        catalog.register(_make_skill(skill_id="a", enabled=True))
        updated = catalog.set_enabled("a", False)
        self.assertFalse(updated.enabled)

    def test_set_enabled_missing_raises(self) -> None:
        catalog = InMemorySkillCatalog()
        with self.assertRaises(KeyError):
            catalog.set_enabled("no.such.skill", True)

    def test_add_manifest(self) -> None:
        catalog = InMemorySkillCatalog()
        skill = _make_skill(skill_id="from-manifest")
        manifest = SkillManifest(source_path="test.json", skills=(skill,))
        catalog.add_manifest(manifest)
        self.assertIsNotNone(catalog.get("from-manifest"))


# ── SkillRuntime ────────────────────────────────────────────────────────


class TestSkillRuntime(unittest.TestCase):
    def test_register_and_describe(self) -> None:
        runtime = SkillRuntime()
        skill = _make_skill()
        runtime.register_skill(skill)
        self.assertEqual(runtime.describe("test-skill"), skill)

    def test_list_skills(self) -> None:
        runtime = SkillRuntime()
        runtime.register_skill(_make_skill(skill_id="a"))
        runtime.register_skill(_make_skill(skill_id="b"))
        self.assertEqual(len(runtime.list_skills()), 2)

    def test_activate_requires_context_resolver(self) -> None:
        runtime = SkillRuntime()
        runtime.register_skill(_make_skill())
        with self.assertRaises(RuntimeError):
            runtime.activate("test-skill", session_id="sess-1")

    def test_activate_missing_skill_raises(self) -> None:
        context = SkillActivationContext(
            personal_model_id="pm-1", state_id="st-1",
            surface_id="surf-1", surface_kind="cli", mode="auto",
        )
        runtime = SkillRuntime(context_resolver=lambda _: context)
        with self.assertRaises(KeyError):
            runtime.activate("no.such.skill", session_id="sess-1")

    def test_activate_disabled_skill_raises(self) -> None:
        context = SkillActivationContext(
            personal_model_id="pm-1", state_id="st-1",
            surface_id="surf-1", surface_kind="cli", mode="auto",
        )
        runtime = SkillRuntime(context_resolver=lambda _: context)
        runtime.register_skill(_make_skill(enabled=False))
        with self.assertRaises(ValueError):
            runtime.activate("test-skill", session_id="sess-1")

    def test_activate_success(self) -> None:
        context = SkillActivationContext(
            personal_model_id="pm-1", state_id="st-1",
            surface_id="surf-1", surface_kind="cli", mode="auto",
        )
        runtime = SkillRuntime(context_resolver=lambda _: context)
        runtime.register_skill(_make_skill())
        record = runtime.activate("test-skill", session_id="sess-1")
        self.assertEqual(record.skill_id, "test-skill")
        self.assertEqual(record.session_id, "sess-1")
        self.assertEqual(record.status, "active")

    def test_list_activations(self) -> None:
        context = SkillActivationContext(
            personal_model_id="pm-1", state_id="st-1",
            surface_id="surf-1", surface_kind="cli", mode="auto",
        )
        runtime = SkillRuntime(context_resolver=lambda _: context)
        runtime.register_skill(_make_skill())
        runtime.activate("test-skill", session_id="sess-1")
        self.assertEqual(len(runtime.list_activations()), 1)

    def test_set_enabled(self) -> None:
        runtime = SkillRuntime()
        runtime.register_skill(_make_skill())
        updated = runtime.set_enabled("test-skill", False)
        self.assertFalse(updated.enabled)

    def test_load_manifest(self) -> None:
        runtime = SkillRuntime()
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(json.dumps({
                "skills": [{
                    "skill_id": "from-manifest",
                    "display_name": "From Manifest",
                    "version": "1.0.0",
                    "summary": "Loaded from manifest.",
                }]
            }))
            manifest = runtime.load_manifest(manifest_path)
            self.assertEqual(len(manifest.skills), 1)
        self.assertIsNotNone(runtime.describe("from-manifest"))

    def test_resolve_for_context(self) -> None:
        runtime = SkillRuntime()
        runtime.register_skill(_make_skill(
            skill_id="scoped",
            scope=SkillScope(modes=("auto",)),
        ))
        runtime.register_skill(_make_skill(skill_id="unscoped"))
        resolved = runtime.resolve_for_context(
            personal_model_id="", state_id="", surface_id="",
            surface_kind="", mode="auto",
        )
        ids = {s.skill_id for s in resolved}
        self.assertIn("scoped", ids)
        self.assertIn("unscoped", ids)


# ── Pure helper functions ───────────────────────────────────────────────


class TestSplitFrontmatter(unittest.TestCase):
    def test_no_frontmatter(self) -> None:
        text = "# Hello\nSome content"
        meta, body = _split_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_with_frontmatter(self) -> None:
        text = "---\nname: test\nversion: 1.0\n---\n# Content"
        meta, body = _split_frontmatter(text)
        self.assertEqual(meta["name"], "test")
        self.assertEqual(meta["version"], "1.0")
        self.assertIn("Content", body)

    def test_unclosed_frontmatter(self) -> None:
        text = "---\nname: test\nno closing"
        meta, body = _split_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)


class TestFrontmatterBool(unittest.TestCase):
    def test_true_values(self) -> None:
        for v in ("true", "True", "yes", "on", "1"):
            self.assertIs(_frontmatter_bool(v), True)

    def test_false_values(self) -> None:
        for v in ("false", "False", "no", "off", "0"):
            self.assertIs(_frontmatter_bool(v), False)

    def test_none_returns_none(self) -> None:
        self.assertIsNone(_frontmatter_bool(None))

    def test_bool_passthrough(self) -> None:
        self.assertIs(_frontmatter_bool(True), True)
        self.assertIs(_frontmatter_bool(False), False)

    def test_unrecognized_returns_none(self) -> None:
        self.assertIsNone(_frontmatter_bool("maybe"))


class TestFrontmatterStringList(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(_frontmatter_string_list(None), ())

    def test_list_input(self) -> None:
        self.assertEqual(_frontmatter_string_list(["a", "b"]), ("a", "b"))

    def test_comma_separated_string(self) -> None:
        self.assertEqual(_frontmatter_string_list("a, b, c"), ("a", "b", "c"))

    def test_json_array_string(self) -> None:
        self.assertEqual(_frontmatter_string_list('["a", "b"]'), ("a", "b"))

    def test_deduplication(self) -> None:
        result = _frontmatter_string_list(["a", "A", "b"])
        self.assertEqual(result, ("a", "b"))

    def test_empty_items_filtered(self) -> None:
        self.assertEqual(_frontmatter_string_list(["a", "", "b"]), ("a", "b"))


class TestSkillCommandSlug(unittest.TestCase):
    def test_simple_name(self) -> None:
        self.assertEqual(_skill_command_slug("Code Review"), "code-review")

    def test_underscores(self) -> None:
        self.assertEqual(_skill_command_slug("my_skill"), "my-skill")

    def test_multiple_hyphens_collapsed(self) -> None:
        self.assertEqual(_skill_command_slug("a--b---c"), "a-b-c")

    def test_special_chars_removed(self) -> None:
        self.assertEqual(_skill_command_slug("skill@v2!"), "skill-v2")


class TestFirstHeading(unittest.TestCase):
    def test_extracts_first_heading(self) -> None:
        self.assertEqual(_first_heading("# Hello\n## World"), "Hello")

    def test_no_heading_returns_empty(self) -> None:
        self.assertEqual(_first_heading("No heading here"), "")

    def test_skips_blank_lines(self) -> None:
        self.assertEqual(_first_heading("\n\n## Found"), "Found")


class TestFirstSummary(unittest.TestCase):
    def test_extracts_first_paragraph(self) -> None:
        body = "# Title\n\nThis is the summary.\n\nMore text."
        self.assertEqual(_first_summary(body), "This is the summary.")

    def test_no_paragraph_returns_empty(self) -> None:
        self.assertEqual(_first_summary("# Just a heading"), "")

    def test_long_paragraph_truncated_at_180(self) -> None:
        body = "x" * 200
        result = _first_summary(body)
        self.assertLessEqual(len(result), 200)


class TestLoadSkillPackageDefinition(unittest.TestCase):
    def test_loads_from_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(
                "---\nname: My Skill\nversion: 2.0.0\n---\n# My Skill\n\nA great skill.\n",
                encoding="utf-8",
            )
            definition = load_skill_package_definition(skill_dir)
            self.assertEqual(definition.skill_id, "my-skill")
            self.assertEqual(definition.display_name, "My Skill")
            self.assertEqual(definition.version, "2.0.0")
            self.assertIn("A great skill.", definition.summary)

    def test_loads_skill_id_from_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(
                "---\nskill_id: custom-id\n---\n# Title\n",
                encoding="utf-8",
            )
            definition = load_skill_package_definition(skill_dir)
            self.assertEqual(definition.skill_id, "custom-id")

    def test_missing_skill_md_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError):
                load_skill_package_definition(Path(tmpdir) / "nonexistent")

    def test_metadata_includes_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text("---\n---\n# My Skill\n", encoding="utf-8")
            definition = load_skill_package_definition(skill_dir)
            self.assertEqual(definition.metadata.get("kind"), "skill-package")


if __name__ == "__main__":
    unittest.main()
