from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.operator_surface import build_api_operator_surface


class _ModelProviderStub:
    def __init__(self) -> None:
        self.active = {"provider_id": "preview", "source": "preview", "secret_status": "not-required"}

    def describe(self):  # type: ignore[no-untyped-def]
        return dict(self.active)


class _AppStub:
    def __init__(self, state_dir: Path) -> None:
        self.repository = SimpleNamespace(database_path=state_dir / "runtime.db")
        self.model_provider = _ModelProviderStub()
        self.provider_payload: dict[str, object] | None = None
        self.created_key: dict[str, object] | None = None

    def doctor_provider(self):  # type: ignore[no-untyped-def]
        return {"status": "ready", "active_provider": self.model_provider.describe(), "checks": ()}

    def set_default_provider(self, payload):  # type: ignore[no-untyped-def]
        self.provider_payload = dict(payload)
        self.model_provider.active = {
            "provider_id": payload["provider_id"],
            "source": "configured",
            "secret_status": "stored" if payload.get("secret_references") else "not-required",
        }
        return {"active_provider": self.model_provider.describe(), "provider_profile": payload}

    def create_provider_key(self, payload):  # type: ignore[no-untyped-def]
        self.created_key = dict(payload)
        return {"status": "ok"}


class _SkillSurfaceStub:
    def list_skill_hub(self, *, limit=None):  # type: ignore[no-untyped-def]
        return ()


class ApiOperatorSurfaceTest(unittest.TestCase):
    def test_api_operator_surface_builds_provider_payload_and_stores_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _AppStub(Path(tmpdir))
            surface = build_api_operator_surface(app, skill_management=_SkillSurfaceStub())

            plan = surface.plan_operator_action(
                "session-1",
                action="provider.set_default",
                parameters={
                    "provider_id": "openai-compatible",
                    "base_url": "https://example.test/v1",
                    "model_id": "model-test",
                    "api_key": "sk-test",
                },
            )
            receipt = surface.apply_operator_action(
                "session-1",
                plan_id=str(plan["planId"]),
                confirmation_token="confirmed",
            )
            daemon_report = surface.inspect_operator("session-1", scope="daemon", probe=False)

            self.assertTrue(receipt["ok"])
            self.assertEqual(app.provider_payload["provider_id"], "openai-compatible")
            self.assertEqual(app.provider_payload["default_model"], "model-test")
            self.assertEqual(app.created_key["value"], "sk-test")
            self.assertEqual(receipt["verification"]["provider"]["provider_id"], "openai-compatible")
            self.assertEqual(daemon_report["components"][0]["details"]["state_dir"], str(app.repository.database_path.parent))


if __name__ == "__main__":
    unittest.main()
