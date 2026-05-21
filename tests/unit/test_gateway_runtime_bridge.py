"""Unit tests for daemon-backed gateway runtime bridge snapshots."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.api_runtime_console_ops import _gateway
from packages.runtime_config import global_config_path_for_state_dir, write_global_config


class _Bridge:
    def __init__(self, services: dict[str, dict[str, Any]]) -> None:
        self._services = services

    def gateway_runtime_snapshot(self) -> dict[str, Any]:
        return {
            "daemon": {"status": "running", "pid": os.getpid()},
            "services": self._services,
        }


def _write_gateway_config(state_dir: Path) -> None:
    write_global_config(
        global_config_path_for_state_dir(state_dir),
        {
            "gateway": {
                "adapters": {
                    "weixin": {
                        "enabled": True,
                        "surface": "ilink",
                        "accounts": [
                            {
                                "account_id": "wx-test",
                                "surface": "ilink",
                                "event_path": "/weixin/events",
                            }
                        ],
                    }
                }
            }
        },
    )


def _service_row(payload: dict[str, Any]) -> dict[str, Any]:
    for row in payload["services"]:
        if row["service"] == "weixin":
            return row
    raise AssertionError("weixin service row missing")


class GatewayRuntimeBridgeTests(unittest.TestCase):
    def test_gateway_bridge_overrides_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir)
            _write_gateway_config(state_dir)
            (state_dir / "weixin-ilink.runtime.json").write_text(
                json.dumps({"service_key": "weixin", "status": "running", "pid": os.getpid()}),
                encoding="utf-8",
            )
            bridge = _Bridge(
                {
                    "weixin": {
                        "service": "weixin",
                        "status": "stopped",
                        "lastError": "daemon says stopped",
                        "runtimeSource": "daemon",
                        "details": {"transport": "ilink"},
                    }
                }
            )

            payload = _gateway(state_dir, runtime_bridge=bridge)
            service = _service_row(payload)

            self.assertTrue(service["configured"])
            self.assertFalse(service["running"])
            self.assertFalse(service["starting"])
            self.assertEqual(service["runtimeStatus"], "stopped")
            self.assertEqual(service["runtimeSource"], "daemon")
            self.assertEqual(service["runtimeDetails"], {"transport": "ilink"})
            self.assertEqual(service["lastError"], "daemon says stopped")
            self.assertEqual(payload["runningServiceCount"], 0)
            self.assertTrue(payload["runtimeBridgeConnected"])

    def test_gateway_uses_runtime_files_when_bridge_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir)
            _write_gateway_config(state_dir)
            (state_dir / "weixin-ilink.runtime.json").write_text(
                json.dumps({"service_key": "weixin", "status": "running", "pid": os.getpid()}),
                encoding="utf-8",
            )

            payload = _gateway(state_dir)
            service = _service_row(payload)

            self.assertTrue(service["running"])
            self.assertEqual(service["runtimeStatus"], "running")
            self.assertEqual(service["runtimeSource"], "files")
            self.assertEqual(payload["runningServiceCount"], 1)
            self.assertFalse(payload["runtimeBridgeConnected"])


if __name__ == "__main__":
    unittest.main()
