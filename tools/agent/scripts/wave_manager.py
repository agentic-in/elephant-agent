#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "tools" / "agent" / "wave-registry.yaml"


def load_registry() -> dict[str, object]:
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse {REGISTRY_PATH}: {exc}") from exc


def resolve_wave(registry: dict[str, object], wave_id: str) -> dict[str, object]:
    waves = registry.get("waves", {})
    if wave_id not in waves:
        raise SystemExit(f"unknown wave: {wave_id}")
    return waves[wave_id]


def require_head() -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("worktrees require the first commit on main; create the bootstrap commit first")


def branch_exists(branch: str) -> bool:
    return (
        subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def remote_branch_exists(branch: str, remote: str) -> bool:
    return (
        subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", remote, branch],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def parse_worktree_records(output: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    record: dict[str, str] = {}
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            if record:
                records.append(record)
                record = {}
            continue
        key, _, value = line.partition(" ")
        record[key] = value
    if record:
        records.append(record)
    return records


def collect_worktree_paths() -> set[Path]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "failed to list worktrees")
    return {Path(record["worktree"]).resolve() for record in parse_worktree_records(result.stdout)}


def show_wave(wave_id: str, root: Path) -> int:
    registry = load_registry()
    wave = resolve_wave(registry, wave_id)
    operator = registry.get("operator_model", {})

    print("Elephant Agent Wave")
    print(f"  Wave: {wave_id}")
    print(f"  Summary: {wave['summary']}")
    print(f"  Entry session: {operator.get('entry_session', 'main')}")
    print(f"  User talks to: {operator.get('user_talks_to', 'main_session_only')}")
    print(f"  Worker rule: {operator.get('worker_rule', 'one worktree, one branch, one task card')}")
    print(f"  Worker model: {operator.get('worker_model', 'inherit-session-default')}")
    print(
        "  Assignment strategy: "
        f"{operator.get('assignment_strategy', 'maximize safe parallelism across ready disjoint tracks')}"
    )
    print(
        "  Main-session policy: "
        f"{operator.get('main_session_policy', 'launch ready parallel tracks, then return or review later')}"
    )
    print(f"  Ship default: {operator.get('ship_default', 'close each completed atomic branch with make agent-ship')}")
    print("Tracks")
    for track in wave.get("tracks", []):
        print(f"  - {track['id']}")
        print(f"    worktree: {root / track['worktree']}")
        print(f"    branch: {track['branch']}")
        print(f"    task card: {track['task_card']}")
        print(f"    adr: {track['adr']}")
    return 0


def start_wave(wave_id: str, root: Path, base: str) -> int:
    registry = load_registry()
    wave = resolve_wave(registry, wave_id)
    require_head()
    root.mkdir(parents=True, exist_ok=True)

    for track in wave.get("tracks", []):
        target = (root / track["worktree"]).resolve()
        if target.exists():
            print(f"exists: {track['id']} -> {target}")
            continue
        if branch_exists(track["branch"]):
            command = ["git", "worktree", "add", str(target), track["branch"]]
        else:
            command = [
                "git",
                "worktree",
                "add",
                "-b",
                track["branch"],
                str(target),
                base,
            ]
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
        print(f"created: {track['id']} -> {target} [{track['branch']}]")
    return 0


def status_wave(wave_id: str, root: Path, remote: str) -> int:
    registry = load_registry()
    wave = resolve_wave(registry, wave_id)
    worktree_paths = collect_worktree_paths()

    print("Elephant Agent Wave Status")
    print(f"  Wave: {wave_id}")
    print(f"  Remote: {remote}")
    for track in wave.get("tracks", []):
        target = (root / track["worktree"]).resolve()
        local_status = "present" if target in worktree_paths else "missing"
        remote_status = "present" if remote_branch_exists(track["branch"], remote) else "missing"
        print(f"  - {track['id']}")
        print(f"    worktree: {target} ({local_status})")
        print(f"    branch: {track['branch']} (remote {remote_status})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage named multi-agent delivery waves.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("show", "start", "status"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--wave", required=True)
        sub.add_argument("--root", default=".worktrees")
    subparsers.choices["start"].add_argument("--base", default="main")
    subparsers.choices["status"].add_argument("--remote", default="origin")

    args = parser.parse_args()
    worktree_root = (ROOT / args.root).resolve()

    if args.command == "show":
        return show_wave(args.wave, worktree_root)
    if args.command == "start":
        return start_wave(args.wave, worktree_root, args.base)
    return status_wave(args.wave, worktree_root, args.remote)


if __name__ == "__main__":
    raise SystemExit(main())
