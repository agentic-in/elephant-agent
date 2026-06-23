"""Unit tests for packages.tools.handlers_skills (skill list/view/manage)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools.handlers_skills import (
    _model_skill_list_entries,
    _required_field,
    _required_skill_reference,
    _skill_source_priority,
    run_skill_list,
    run_skill_manage,
    run_skill_view,
)
from packages.tools.runtime import ToolInvocation, ToolRuntimeContext
from packages.skills import SkillDefinition


def _invocation(**kwargs: object) -> ToolInvocation:
    return ToolInvocation(
        invocation_id="inv-1",
        tool_id="tool.skill.manage",
        session_id="sess-1",
        context=ToolRuntimeContext(cwd=Path.cwd()),
        arguments=kwargs,
    )


class _SkillEntry:
    def __init__(self, skill_id: str, display_name: str, source_id: str, reference: str, summary: str) -> None:
        self.skill_id = skill_id
        self.display_name = display_name
        self.source_id = source_id
        self.reference = reference
        self.summary = summary


class _SkillManagementStub:
    def __init__(self) -> None:
        self.entries: list[_SkillEntry] = []
        self._enabled: dict[str, bool] = {}

    def list_skill_hub(self, *, limit: int | None = None) -> tuple[_SkillEntry, ...]:
        return tuple(self.entries[:limit] if limit else self.entries)

    def inspect_skill(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        return SkillDefinition(
            skill_id=skill_id,
            display_name=skill_id.replace("-", " ").title(),
            version="1.0.0",
            summary="Test skill",
            enabled=self._enabled.get(skill_id, True),
        )

    def set_skill_enabled(self, skill_id: str, enabled: bool, *, session_id: str | None = None, profile_id: str | None = None) -> SkillDefinition:
        self._enabled[skill_id] = enabled
        return SkillDefinition(
            skill_id=skill_id,
            display_name=skill_id.replace("-", " ").title(),
            version="1.0.0",
            summary="Test skill",
            enabled=enabled,
        )

    def install_skill_source(self, reference: str | Path, *, session_id: str | None = None, profile_id: str | None = None, requester: str | None = None) -> object:
        from packages.skills import SkillManifestLoadRecord
        from datetime import datetime, timezone
        return SkillManifestLoadRecord(
            source_path=str(reference),
            skill_ids=("installed-skill",),
            loaded_at=datetime.now(timezone.utc),
            status="installed",
        )

    def create_authored_skill(self, *, skill_id: str, display_name: str, summary: str, instruction_text: str, category: str | None = None, install: bool = True, overwrite: bool = False, session_id: str | None = None, profile_id: str | None = None) -> object:
        from packages.skills import SkillManifestLoadRecord
        from datetime import datetime, timezone
        return SkillManifestLoadRecord(
            source_path=f"/authored/{skill_id}",
            skill_ids=(skill_id,),
            loaded_at=datetime.now(timezone.utc),
            status="created",
        )

    def update_authored_skill(self, skill_id: str, *, display_name: str | None = None, summary: str | None = None, instruction_text: str | None = None, category: str | None = None, session_id: str | None = None, profile_id: str | None = None) -> object:
        from packages.skills import SkillManifestLoadRecord
        from datetime import datetime, timezone
        return SkillManifestLoadRecord(
            source_path=f"/authored/{skill_id}",
            skill_ids=(skill_id,),
            loaded_at=datetime.now(timezone.utc),
            status="updated",
        )

    def delete_skill_source(self, skill_id: str, *, session_id: str | None = None, profile_id: str | None = None) -> tuple[str, str]:
        return (skill_id, f"/deleted/{skill_id}")


class TestSkillSourcePriority(unittest.TestCase):
    def test_installed_highest(self) -> None:
        self.assertEqual(_skill_source_priority("elephant-installed"), 0)

    def test_authored_highest(self) -> None:
        self.assertEqual(_skill_source_priority("elephant-authored"), 0)

    def test_non_builtin_medium(self) -> None:
        self.assertEqual(_skill_source_priority("custom"), 1)

    def test_builtin_lowest(self) -> None:
        self.assertEqual(_skill_source_priority("builtin"), 2)


class TestModelSkillListEntries(unittest.TestCase):
    def test_respects_limit(self) -> None:
        entries = tuple(_SkillEntry(f"s-{i}", f"S {i}", "builtin", f"ref-{i}", "Summary") for i in range(10))
        result = _model_skill_list_entries(entries, limit=3)
        self.assertEqual(len(result), 3)

    def test_sorts_by_source_priority(self) -> None:
        builtin = _SkillEntry("builtin-skill", "B", "builtin", "r1", "Sum")
        installed = _SkillEntry("inst-skill", "I", "elephant-installed", "r2", "Sum")
        custom = _SkillEntry("custom-skill", "C", "custom", "r3", "Sum")
        result = _model_skill_list_entries((builtin, installed, custom), limit=10)
        ids = [e.skill_id for e in result]
        self.assertEqual(ids[0], "inst-skill")  # installed highest priority


class TestRunSkillList(unittest.TestCase):
    def test_none_surface_raises(self) -> None:
        inv = _invocation()
        with self.assertRaises(RuntimeError):
            run_skill_list(inv, surface=None)

    def test_list_success(self) -> None:
        surface = _SkillManagementStub()
        surface.entries = [_SkillEntry("s-1", "Skill 1", "builtin", "ref-1", "A skill")]
        inv = _invocation()
        result = run_skill_list(inv, surface=surface)
        self.assertIn("s-1", result["summary"])

    def test_empty_list(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation()
        result = run_skill_list(inv, surface=surface)
        self.assertIn("<empty>", result["summary"])


class TestRunSkillView(unittest.TestCase):
    def test_none_surface_raises(self) -> None:
        inv = _invocation(skill_id="test-skill")
        with self.assertRaises(RuntimeError):
            run_skill_view(inv, surface=None)

    def test_view_success(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(skill_id="test-skill")
        result = run_skill_view(inv, surface=surface)
        self.assertIn("test-skill", result["summary"])

    def test_missing_reference_raises(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation()
        with self.assertRaises(ValueError) as ctx:
            run_skill_view(inv, surface=surface)
        self.assertIn("skill_id", str(ctx.exception))


class TestRunSkillManage(unittest.TestCase):
    def test_none_surface_raises(self) -> None:
        inv = _invocation(action="enable", skill_id="test")
        with self.assertRaises(RuntimeError):
            run_skill_manage(inv, surface=None)

    def test_enable(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(action="enable", skill_id="test-skill")
        result = run_skill_manage(inv, surface=surface)
        self.assertIn("enabled: True", result["summary"])

    def test_disable(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(action="disable", skill_id="test-skill")
        result = run_skill_manage(inv, surface=surface)
        self.assertIn("enabled: False", result["summary"])

    def test_install(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(action="install", reference="some-ref")
        result = run_skill_manage(inv, surface=surface)
        self.assertIn("installed", result["summary"].lower())

    def test_create(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(
            action="create",
            skill_id="new-skill",
            display_name="New Skill",
            summary="A new skill",
            instruction_text="Do stuff",
        )
        result = run_skill_manage(inv, surface=surface)
        self.assertIn("new-skill", result["summary"])

    def test_update(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(action="update", skill_id="test-skill", display_name="Updated")
        result = run_skill_manage(inv, surface=surface)
        self.assertIn("test-skill", result["summary"])

    def test_delete(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(action="delete", skill_id="test-skill")
        result = run_skill_manage(inv, surface=surface)
        self.assertIn("test-skill", result["summary"])

    def test_unsupported_action_raises(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(action="fly", skill_id="test-skill")
        with self.assertRaises(ValueError):
            run_skill_manage(inv, surface=surface)

    def test_enable_without_reference_raises(self) -> None:
        surface = _SkillManagementStub()
        inv = _invocation(action="enable")
        with self.assertRaises(ValueError):
            run_skill_manage(inv, surface=surface)


class TestRequiredSkillReference(unittest.TestCase):
    def test_skill_id(self) -> None:
        inv = _invocation(skill_id="my-skill")
        self.assertEqual(_required_skill_reference(inv), "my-skill")

    def test_reference_fallback(self) -> None:
        inv = _invocation(reference="hub/ref")
        self.assertEqual(_required_skill_reference(inv), "hub/ref")

    def test_name_fallback(self) -> None:
        inv = _invocation(name="skill-name")
        self.assertEqual(_required_skill_reference(inv), "skill-name")

    def test_missing_raises(self) -> None:
        inv = _invocation()
        with self.assertRaises(ValueError):
            _required_skill_reference(inv)


class TestRequiredField(unittest.TestCase):
    def test_present(self) -> None:
        inv = _invocation(title="hello")
        self.assertEqual(_required_field(inv, "title"), "hello")

    def test_missing_raises(self) -> None:
        inv = _invocation()
        with self.assertRaises(ValueError) as ctx:
            _required_field(inv, "title")
        self.assertIn("title", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
