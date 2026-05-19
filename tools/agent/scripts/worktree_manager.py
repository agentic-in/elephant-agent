#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


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


def add_worktree(name: str, branch: str, base: str, root: Path) -> int:
    require_head()
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    if target.exists():
        raise SystemExit(f"worktree path already exists: {target}")

    branch_exists = (
        subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )

    if branch_exists:
        command = ["git", "worktree", "add", str(target), branch]
    else:
        command = ["git", "worktree", "add", "-b", branch, str(target), base]

    return subprocess.run(command, cwd=ROOT, check=False).returncode


def list_worktrees(_root: Path) -> int:
    return subprocess.run(["git", "worktree", "list"], cwd=ROOT, check=False).returncode


def remove_worktree(name: str, root: Path) -> int:
    target = root / name
    if not target.exists():
        raise SystemExit(f"worktree path does not exist: {target}")
    return subprocess.run(["git", "worktree", "remove", str(target)], cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage repo-local git worktrees.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Create a new worktree")
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--branch", required=True)
    add_parser.add_argument("--base", default="main")
    add_parser.add_argument("--root", default=".worktrees")

    list_parser = subparsers.add_parser("list", help="List worktrees")
    list_parser.add_argument("--root", default=".worktrees")

    remove_parser = subparsers.add_parser("remove", help="Remove a worktree")
    remove_parser.add_argument("--name", required=True)
    remove_parser.add_argument("--root", default=".worktrees")

    args = parser.parse_args()
    worktree_root = (ROOT / args.root).resolve()

    if args.command == "add":
        return add_worktree(args.name, args.branch, args.base, worktree_root)
    if args.command == "list":
        return list_worktrees(worktree_root)
    return remove_worktree(args.name, worktree_root)


if __name__ == "__main__":
    raise SystemExit(main())
