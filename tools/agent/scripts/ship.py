#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def git(args: list[str], *, capture_output: bool = True, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=capture_output,
        check=check,
    )


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, check=check)


def ensure_branch(branch_override: str) -> str:
    if branch_override:
        return branch_override
    result = git(["rev-parse", "--abbrev-ref", "HEAD"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "failed to resolve current branch")
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        raise SystemExit("agent-ship requires a named branch, not a detached HEAD")
    return branch


def parse_status_paths(lines: list[str]) -> list[str]:
    paths: list[str] = []
    for raw in lines:
        if not raw:
            continue
        payload = raw[3:]
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        payload = payload.strip()
        if payload:
            paths.append(payload)
    return sorted(dict.fromkeys(paths))


def changed_paths() -> list[str]:
    result = git(["status", "--porcelain"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "failed to inspect working tree status")
    return parse_status_paths(result.stdout.splitlines())


def ensure_changes(paths: list[str]) -> None:
    if not paths:
        raise SystemExit("agent-ship requires local changes; working tree is clean")


def resolve_base_ref(explicit: str) -> str:
    if explicit:
        return explicit
    for candidate in ("origin/main", "HEAD^"):
        result = git(["rev-parse", "--verify", candidate])
        if result.returncode == 0:
            return candidate
    return ""


def lint_commit_message(message: str) -> None:
    result = run(
        [
            sys.executable,
            "tools/agent/scripts/commit_msg_lint.py",
            "message",
            "--subject",
            message,
        ],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def run_pr_gate(paths: list[str], base_ref: str) -> None:
    csv_files = ",".join(paths)
    command = ["make", "agent-pr-gate", f"CHANGED_FILES={csv_files}"]
    if base_ref:
        command.append(f"AGENT_BASE_REF={base_ref}")
    run(command)


def run_soft_audit(paths: list[str]) -> None:
    csv_files = ",".join(paths)
    result = subprocess.run(
        [
            sys.executable,
            "tools/agent/scripts/agent_gate.py",
            "report",
            "--changed-files",
            csv_files,
            "--audit",
            "--format",
            "json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return
    try:
        import json

        data = json.loads(result.stdout)
    except (ValueError, ImportError):
        return
    warnings = data.get("audit_warnings", [])
    if warnings:
        print()
        print("Context-Map Audit (soft gate — not blocking)")
        for warning in warnings:
            print(f"  ⚠ {warning}")
        print("  → Consider updating tools/agent/context-map.yaml or skill-registry.yaml")
        print()


def commit_all(message: str) -> None:
    run(["git", "add", "-A"])
    run(["git", "commit", "-s", "-m", message])


def push_branch(remote: str, branch: str) -> None:
    run(["git", "push", "--set-upstream", remote, branch])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run gates, commit atomically, and push the current branch.")
    parser.add_argument("--message", required=True, help="Scoped Conventional Commit subject")
    parser.add_argument("--remote", default="origin", help="Push remote")
    parser.add_argument("--branch", default="", help="Override the branch to push")
    parser.add_argument("--base-ref", default="", help="Override base ref for the PR gate")
    args = parser.parse_args()

    branch = ensure_branch(args.branch)
    paths = changed_paths()
    ensure_changes(paths)
    lint_commit_message(args.message)
    base_ref = resolve_base_ref(args.base_ref)
    run_pr_gate(paths, base_ref)
    run_soft_audit(paths)
    commit_all(args.message)
    push_branch(args.remote, branch)
    print(f"Shipped {branch} to {args.remote}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
