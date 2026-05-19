from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from apps.cli.snapshot_io import load_snapshot_payload, write_snapshot_payload


class SnapshotIOTest(unittest.TestCase):
    def test_load_snapshot_payload_recovers_concatenated_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "preview-snapshot.json"
            path.write_text('{"session": {"session_id": "one"}}  }\n]\n}', encoding="utf-8")

            payload = load_snapshot_payload(path)

        self.assertEqual(payload, {"session": {"session_id": "one"}})

    def test_write_snapshot_payload_replaces_with_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "preview-snapshot.json"
            path.write_text('{"stale": true}  }', encoding="utf-8")

            write_snapshot_payload(path, {"session": {"session_id": "two"}})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"session": {"session_id": "two"}},
            )


if __name__ == "__main__":
    unittest.main()
