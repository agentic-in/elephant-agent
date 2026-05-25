from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.cli.runtime import CliRuntime
from packages.tools import (
    BuiltinToolDependencies,
    CallableApprovalGateway,
    InMemoryToolExecutor,
    InMemoryToolRegistry,
    ToolRuntime,
    register_builtin_tools,
)


class BuiltinToolsTestBase(unittest.TestCase):
    def _make_builtin_runtime(self, *, cwd: Path, dependencies: BuiltinToolDependencies | None = None) -> ToolRuntime:
        runtime = ToolRuntime(
            registry=InMemoryToolRegistry(),
            executor=InMemoryToolExecutor(),
            approval_gateway=CallableApprovalGateway(lambda *_: True),
        )
        register_builtin_tools(
            runtime,
            enabled_overrides={},
            dependencies=dependencies or BuiltinToolDependencies(cwd=cwd),
        )
        return runtime

    def _make_cli_runtime(self, *, external_skill_dir: Path | None = None) -> CliRuntime:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        state_dir = root / "state"
        profile_dir = root / "profile"
        profile_dir.mkdir()
        skill_dirs = [] if external_skill_dir is None else [str(external_skill_dir)]
        (root / "config.yaml").write_text(
            f"skills:\n  external_dirs: {json.dumps(skill_dirs)}\n",
            encoding="utf-8",
        )
        (root / "profile.json").write_text(
            """{"profile_id":"profile-companion","display_name":"Elephant Agent","mode":"companion"}""",
            encoding="utf-8",
        )
        runtime = CliRuntime.create(state_dir=state_dir)
        runtime.update_identity_state(
            profile_id="profile-companion",
            elephant_identity_text="Stay durable and grounded.",
        )
        return runtime

