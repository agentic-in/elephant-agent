from __future__ import annotations

from importlib import metadata
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.semantic_index import (
    SQLITE_VEC_VERSION,
    load_sqlite_vec_extension,
    sqlite_vec_dependency_state,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.extension_enabled: list[bool] = []

    def enable_load_extension(self, enabled: bool) -> None:
        self.extension_enabled.append(enabled)

    def execute(self, sql: str):
        self.queries.append(sql)
        return self

    def fetchone(self) -> tuple[str]:
        return (SQLITE_VEC_VERSION,)


class SQLiteVecLoadTest(unittest.TestCase):
    def test_dependency_state_degrades_when_package_is_missing(self) -> None:
        with mock.patch(
            "packages.semantic_index.sqlite_vec.metadata.version",
            side_effect=metadata.PackageNotFoundError,
        ):
            state = sqlite_vec_dependency_state()

        self.assertEqual(state.status, "degraded")
        self.assertEqual(state.metadata["reason"], "missing-package")

    def test_dependency_state_requires_exact_reset_pin(self) -> None:
        with mock.patch("packages.semantic_index.sqlite_vec.metadata.version", return_value="0.1.8"):
            state = sqlite_vec_dependency_state()

        self.assertEqual(state.status, "degraded")
        self.assertEqual(state.installed_version, "0.1.8")
        self.assertEqual(state.metadata["reason"], "version-mismatch")

    def test_load_extension_uses_sqlite_vec_loader_and_smokes_runtime(self) -> None:
        fake_module = mock.Mock()
        fake_connection = _FakeConnection()

        with (
            mock.patch(
                "packages.semantic_index.sqlite_vec.metadata.version",
                return_value=SQLITE_VEC_VERSION,
            ),
            mock.patch(
                "packages.semantic_index.sqlite_vec.import_module",
                return_value=fake_module,
            ),
        ):
            state = load_sqlite_vec_extension(fake_connection)

        self.assertTrue(state.ready)
        fake_module.load.assert_called_once_with(fake_connection)
        self.assertEqual(fake_connection.extension_enabled, [True, False])
        self.assertEqual(fake_connection.queries, ["SELECT vec_version()"])
        self.assertEqual(state.metadata["runtime_version"], SQLITE_VEC_VERSION)

    def test_load_extension_degrades_when_loader_fails(self) -> None:
        fake_module = mock.Mock()
        fake_module.load.side_effect = RuntimeError("boom")

        with (
            mock.patch(
                "packages.semantic_index.sqlite_vec.metadata.version",
                return_value=SQLITE_VEC_VERSION,
            ),
            mock.patch(
                "packages.semantic_index.sqlite_vec.import_module",
                return_value=fake_module,
            ),
        ):
            state = load_sqlite_vec_extension(_FakeConnection())

        self.assertEqual(state.status, "degraded")
        self.assertEqual(state.metadata["reason"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
