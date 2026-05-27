"""CLI helpers for the RTK terminal optimizer surface."""

from __future__ import annotations

from pathlib import Path

from packages.runtime_config import (
    global_config_path_for_state_dir,
    load_global_config,
    load_rtk_from_config,
    save_rtk_to_config,
)
from packages.tools.rtk import probe_rtk, resolve_rtk_binary


def run_rtk_doctor(state_dir: Path) -> int:
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    rtk_config = load_rtk_from_config(config)
    enabled = bool(rtk_config.get("enabled", False))
    binary = str(rtk_config.get("binary") or "rtk")
    timeout = int(rtk_config.get("rewrite_timeout_seconds") or 2)
    probe = probe_rtk(binary, timeout_seconds=timeout)

    print("RTK terminal optimizer")
    print(f"enabled: {'yes' if enabled else 'no'}")
    print(f"config: {config_path}")
    print(f"binary: {binary}")
    print(f"resolved_binary: {probe.binary if probe.binary else resolve_rtk_binary(binary) or '<not found>'}")
    if probe.version:
        print(f"version: {probe.version}")
    print(f"rewrite_probe: {'ok' if probe.ok else 'not-ready'}")
    if probe.rewrite_exit_code is not None:
        print(f"rewrite_exit_code: {probe.rewrite_exit_code}")
    if probe.rewrite_output:
        print(f"rewrite_output: {probe.rewrite_output}")
    if probe.error:
        print(f"error: {probe.error}")
    print("coverage: non-sandbox foreground tool.terminal.exec")
    print("out_of_scope: sandbox terminal exec, background terminal processes")
    return 0 if probe.ok or not enabled else 1


def run_rtk_start(state_dir: Path, *, binary: str | None = None) -> int:
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    current = load_rtk_from_config(config)
    requested_binary = binary or str(current.get("binary") or "rtk")
    timeout = int(current.get("rewrite_timeout_seconds") or 2)
    probe = probe_rtk(requested_binary, timeout_seconds=timeout)
    if not probe.ok:
        print("RTK terminal optimizer was not enabled.")
        print(f"binary: {requested_binary}")
        if probe.error:
            print(f"error: {probe.error}")
        return 1

    payload = {
        **current,
        "enabled": True,
        "binary": probe.binary,
        "rewrite_timeout_seconds": timeout,
    }
    save_rtk_to_config(config_path, state_dir=state_dir, rtk_payload=payload)
    print("RTK terminal optimizer enabled.")
    print(f"binary: {probe.binary}")
    print("coverage: non-sandbox foreground tool.terminal.exec")
    return 0


def run_rtk_stop(state_dir: Path) -> int:
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    current = load_rtk_from_config(config)
    save_rtk_to_config(
        config_path,
        state_dir=state_dir,
        rtk_payload={**current, "enabled": False},
    )
    print("RTK terminal optimizer disabled.")
    print(f"binary: {current.get('binary') or 'rtk'}")
    return 0
