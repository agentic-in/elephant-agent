"""Tests for SandboxPathMapper — unified host ↔ sandbox path mapping."""

from __future__ import annotations

import unittest
from pathlib import Path

from packages.sandbox.path_mapper import SandboxPathMapper


class TestSandboxPathMapperToRemote(unittest.TestCase):
    """Test SandboxPathMapper.to_remote() with all mapping rules."""

    def setUp(self) -> None:
        self.mapper = SandboxPathMapper(
            workspaces_dir=Path("/Users/alice/.elephant/workspaces"),
            startup_cwd=Path("/Users/alice/projects/myapp"),
        )

    # Rule 1: already remote paths pass through unchanged
    def test_home_path_unchanged(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("/home/user/mother-elephant/foo.py"),
            "/home/user/mother-elephant/foo.py",
        )

    def test_tmp_path_unchanged(self) -> None:
        self.assertEqual(self.mapper.to_remote("/tmp/test.py"), "/tmp/test.py")

    def test_home_subdir_unchanged(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("/home/sandbox/work"),
            "/home/sandbox/work",
        )

    # Rule 2: relative paths resolved under sandbox_home
    def test_relative_file(self) -> None:
        self.assertEqual(self.mapper.to_remote("foo.py"), "/home/user/foo.py")

    def test_relative_subdir(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("subdir/bar.py"),
            "/home/user/subdir/bar.py",
        )

    # Rule 3: paths under workspaces_dir → strip prefix
    def test_workspace_elephant_file(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("/Users/alice/.elephant/workspaces/mother-elephant/two_sum.py"),
            "/home/user/mother-elephant/two_sum.py",
        )

    def test_workspace_elephant_dir(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("/Users/alice/.elephant/workspaces/mother-elephant"),
            "/home/user/mother-elephant",
        )

    def test_workspace_nested_deep(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("/Users/alice/.elephant/workspaces/felix/algorithms/bst.py"),
            "/home/user/felix/algorithms/bst.py",
        )

    # Rule 4: paths under startup_cwd → map to project/
    def test_startup_cwd_file(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("/Users/alice/projects/myapp/src/main.py"),
            "/home/user/project/src/main.py",
        )

    def test_startup_cwd_root(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("/Users/alice/projects/myapp"),
            "/home/user/project",
        )

    # Rule 5: fallback — use basename
    def test_fallback_random_path(self) -> None:
        self.assertEqual(
            self.mapper.to_remote("/opt/random/file.txt"),
            "/home/user/file.txt",
        )

    # Edge cases
    def test_empty_string(self) -> None:
        self.assertEqual(self.mapper.to_remote(""), "/home/user")

    def test_mapper_without_workspaces_dir(self) -> None:
        mapper = SandboxPathMapper(startup_cwd=Path("/Users/bob/work"))
        # Falls to rule 4 (startup_cwd)
        self.assertEqual(
            mapper.to_remote("/Users/bob/work/file.py"),
            "/home/user/project/file.py",
        )

    def test_mapper_without_any_config(self) -> None:
        mapper = SandboxPathMapper()
        # Falls to rule 5 (basename)
        self.assertEqual(
            mapper.to_remote("/some/path/file.py"),
            "/home/user/file.py",
        )
        # Relative still works (rule 2)
        self.assertEqual(mapper.to_remote("foo.py"), "/home/user/foo.py")


class TestSandboxPathMapperRemoteCwd(unittest.TestCase):
    """Test SandboxPathMapper.remote_cwd()."""

    def setUp(self) -> None:
        self.mapper = SandboxPathMapper(
            workspaces_dir=Path("/Users/alice/.elephant/workspaces"),
            startup_cwd=Path("/Users/alice/projects/myapp"),
        )

    def test_remote_cwd_from_workspace(self) -> None:
        self.assertEqual(
            self.mapper.remote_cwd("/Users/alice/.elephant/workspaces/mother-elephant"),
            "/home/user/mother-elephant",
        )

    def test_remote_cwd_none(self) -> None:
        self.assertEqual(self.mapper.remote_cwd(None), "/home/user")

    def test_remote_cwd_from_path_object(self) -> None:
        self.assertEqual(
            self.mapper.remote_cwd(Path("/Users/alice/.elephant/workspaces/felix")),
            "/home/user/felix",
        )


class TestSandboxPathMapperConsistency(unittest.TestCase):
    """Ensure executor and backend would produce the same paths."""

    def test_same_workspace_path_maps_identically(self) -> None:
        """Both executor file.write and backend cwd should agree."""
        mapper = SandboxPathMapper(
            workspaces_dir=Path("/Users/wuhao/.elephant/workspaces"),
        )
        # Simulates what executor does for file.write path
        file_path = mapper.to_remote(
            "/Users/wuhao/.elephant/workspaces/mother-elephant/two_sum.py"
        )
        # Simulates what backend does for cwd
        cwd_path = mapper.remote_cwd(
            "/Users/wuhao/.elephant/workspaces/mother-elephant"
        )
        # File should be under cwd
        self.assertTrue(
            file_path.startswith(cwd_path),
            f"File {file_path} should be under cwd {cwd_path}",
        )

    def test_no_duplicate_workspaces_in_path(self) -> None:
        """The mapped path must NOT contain 'workspaces/' segment."""
        mapper = SandboxPathMapper(
            workspaces_dir=Path("/Users/wuhao/.elephant/workspaces"),
        )
        result = mapper.to_remote(
            "/Users/wuhao/.elephant/workspaces/mother-elephant/foo.py"
        )
        self.assertNotIn("/workspaces/", result)
        self.assertEqual(result, "/home/user/mother-elephant/foo.py")


if __name__ == "__main__":
    unittest.main()
