from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.cli.operator_surface import build_cli_operator_surface


class _SkillEntry:
    def __init__(self, skill_id: str) -> None:
        self.skill_id = skill_id
        self.source_id = "builtin"
        self.metadata = {"default_enabled": True}


class _SkillDefinition:
    def __init__(self, skill_id: str, enabled: bool) -> None:
        self.skill_id = skill_id
        self.enabled = enabled


class _RuntimeStub:
    def __init__(self, state_dir: Path) -> None:
        self.paths = SimpleNamespace(state_dir=state_dir)
        self.security_policy = None
        self.tool_runtime = None
        self.provider_update: dict[str, object] | None = None
        self.skill_enabled = True

    def provider_summary(self):  # type: ignore[no-untyped-def]
        if self.provider_update is not None:
            return {"provider_id": self.provider_update["provider_id"], "source": "configured", "secret_status": "not-required"}
        return {"provider_id": "preview", "source": "preview", "secret_status": "not-required"}

    def provider_doctor(self, *, deep: bool = True):  # type: ignore[no-untyped-def]
        return {"status": "ready", "provider": self.provider_summary(), "checks": ()}

    def set_default_provider(self, **kwargs):  # type: ignore[no-untyped-def]
        self.provider_update = dict(kwargs)
        return SimpleNamespace(state=SimpleNamespace(profile_id="profile-companion"))

    def list_skill_hub(self, *, limit=None):  # type: ignore[no-untyped-def]
        return (_SkillEntry("elephant-operator"),)

    def set_skill_enabled(self, skill_id: str, enabled: bool, **_kwargs):  # type: ignore[no-untyped-def]
        self.skill_enabled = enabled
        return _SkillDefinition(skill_id, enabled)

    def inspect_skill(self, skill_id: str, **_kwargs):  # type: ignore[no-untyped-def]
        return _SkillDefinition(skill_id, self.skill_enabled)


class CliOperatorSurfaceTest(unittest.TestCase):
    def test_cli_operator_surface_dispatches_provider_and_skill_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _RuntimeStub(Path(tmpdir))
            surface = build_cli_operator_surface(runtime)

            provider_plan = surface.plan_operator_action(
                "session-1",
                action="provider.set_default",
                parameters={"provider_id": "openai", "model_id": "gpt-test"},
            )
            provider_receipt = surface.apply_operator_action(
                "session-1",
                plan_id=str(provider_plan["planId"]),
                confirmation_token="confirmed",
            )
            skill_plan = surface.plan_operator_action(
                "session-1",
                action="skill.disable",
                parameters={"skill_id": "elephant-operator"},
            )
            skill_receipt = surface.apply_operator_action(
                "session-1",
                plan_id=str(skill_plan["planId"]),
                confirmation_token="confirmed",
            )
            daemon_report = surface.inspect_operator("session-1", scope="daemon", probe=False)

            self.assertTrue(provider_receipt["ok"])
            self.assertEqual(runtime.provider_update["provider_id"], "openai")
            self.assertEqual(runtime.provider_update["model_id"], "gpt-test")
            self.assertTrue(skill_receipt["ok"])
            self.assertFalse(runtime.skill_enabled)
            self.assertEqual(daemon_report["components"][0]["details"]["state_dir"], str(runtime.paths.state_dir))


if __name__ == "__main__":
    unittest.main()
