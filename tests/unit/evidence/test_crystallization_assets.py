"""Tests for crystallization-side asset materialization (Task A.2)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.evidence.crystallization_runtime_impl import (
    _b64_encode,
    _materialize_assets_from_steps,
)


@dataclass
class _FakeStep:
    step_id: str
    action: str = "tool.file.write"
    status: str = "success"
    outcome: str = ""
    summary: str = ""
    payload_refs: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


@dataclass
class _FakeRecord:
    payload: dict


class _FakeRepo:
    def __init__(self, records: dict[str, _FakeRecord] | None = None) -> None:
        self._records = records or {}

    def load_record(self, record_id):
        return self._records.get(record_id)


class MaterializeAssetsTests(unittest.TestCase):
    def test_no_hints_returns_empty(self) -> None:
        materialized, report = _materialize_assets_from_steps(
            repository=_FakeRepo(),
            steps=(),
            metadata={},
        )
        self.assertEqual(materialized, {})
        self.assertEqual(report, {})

    def test_invalid_json_is_reported(self) -> None:
        materialized, report = _materialize_assets_from_steps(
            repository=_FakeRepo(),
            steps=(),
            metadata={"proposal_asset_hints": "not-json"},
        )
        self.assertEqual(materialized, {})
        self.assertIn("error", report)

    def test_missing_source_step_is_reported(self) -> None:
        hints = [
            {
                "path": "scripts/run.sh",
                "source_step_id": "nope",
                "content_kind": "script",
            }
        ]
        materialized, report = _materialize_assets_from_steps(
            repository=_FakeRepo(),
            steps=(),
            metadata={"proposal_asset_hints": json.dumps(hints)},
        )
        self.assertEqual(materialized, {})
        self.assertEqual(report["missing"][0]["reason"], "no_source_step")

    def test_extracts_from_tool_call_arguments(self) -> None:
        record = _FakeRecord(
            payload={
                "tool_calls": [
                    {"arguments": {"content": "#!/bin/bash\necho hi\n"}},
                ],
            }
        )
        step = _FakeStep(step_id="step:1", payload_refs=("ref:1",))
        repo = _FakeRepo({"ref:1": record})
        hints = [
            {
                "path": "scripts/run.sh",
                "source_step_id": "step:1",
                "content_kind": "script",
            }
        ]
        materialized, report = _materialize_assets_from_steps(
            repository=repo,
            steps=(step,),
            metadata={"proposal_asset_hints": json.dumps(hints)},
        )
        self.assertEqual(materialized["scripts/run.sh"], b"#!/bin/bash\necho hi\n")
        self.assertIn("scripts/run.sh", report["fulfilled"])

    def test_extracts_from_stdout_fallback(self) -> None:
        record = _FakeRecord(payload={"stdout": "generated config content\n"})
        step = _FakeStep(step_id="step:2", payload_refs=("ref:2",))
        repo = _FakeRepo({"ref:2": record})
        hints = [
            {
                "path": "config/x.yaml",
                "source_step_id": "step:2",
                "content_kind": "config",
            }
        ]
        materialized, report = _materialize_assets_from_steps(
            repository=repo,
            steps=(step,),
            metadata={"proposal_asset_hints": json.dumps(hints)},
        )
        self.assertEqual(materialized["config/x.yaml"], b"generated config content\n")

    def test_fallback_to_step_outcome(self) -> None:
        step = _FakeStep(step_id="step:3", outcome="raw outcome text")
        hints = [
            {
                "path": "notes.txt",
                "source_step_id": "step:3",
                "content_kind": "reference",
            }
        ]
        materialized, _ = _materialize_assets_from_steps(
            repository=_FakeRepo(),
            steps=(step,),
            metadata={"proposal_asset_hints": json.dumps(hints)},
        )
        self.assertEqual(materialized["notes.txt"], b"raw outcome text")

    def test_truncates_oversized_content(self) -> None:
        huge_content = "X" * (2 * 1024 * 1024)
        record = _FakeRecord(payload={"stdout": huge_content})
        step = _FakeStep(step_id="step:4", payload_refs=("ref:4",))
        repo = _FakeRepo({"ref:4": record})
        hints = [
            {
                "path": "huge.bin",
                "source_step_id": "step:4",
                "content_kind": "reference",
            }
        ]
        materialized, report = _materialize_assets_from_steps(
            repository=repo,
            steps=(step,),
            metadata={"proposal_asset_hints": json.dumps(hints)},
        )
        self.assertLessEqual(len(materialized["huge.bin"]), 1024 * 1024)
        self.assertIn("huge.bin", report["truncated"])

    def test_b64_encode_roundtrips(self) -> None:
        data = b"binary payload \x00\x01\x02"
        encoded = _b64_encode(data)
        self.assertEqual(base64.b64decode(encoded.encode("ascii")), data)


if __name__ == "__main__":
    unittest.main()
