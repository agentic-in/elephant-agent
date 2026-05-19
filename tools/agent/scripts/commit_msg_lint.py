#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ALLOWED_TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "test",
)
COMMIT_RE = re.compile(
    r"^(?P<type>build|chore|ci|docs|feat|fix|perf|refactor|revert|test)"
    r"\((?P<scope>[a-z0-9][a-z0-9/-]*)\)"
    r"(?P<breaking>!)?: "
    r"(?P<summary>.+)$"
)


def lint_subject(subject: str) -> list[str]:
    errors: list[str] = []
    if not subject.strip():
        return ["commit subject is empty"]
    if len(subject) > 72:
        errors.append("commit subject exceeds 72 characters")
    if subject.endswith("."):
        errors.append("commit subject must not end with a period")
    match = COMMIT_RE.match(subject)
    if not match:
        allowed = ", ".join(ALLOWED_TYPES)
        errors.append(
            f"commit subject must match <type>(<scope>): <summary> with a required scope; allowed types: {allowed}"
        )
        return errors
    if not match.group("summary").strip():
        errors.append("commit subject summary must not be empty")
    return errors


def first_subject_from_file(path: Path) -> str:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return line
    return ""


def subjects_from_range(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--no-merges", "--format=%s", f"{base_ref}..HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"failed to inspect commit range from {base_ref}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint Conventional Commit subjects.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    message_parser = subparsers.add_parser("message", help="Lint a single commit message")
    message_parser.add_argument("--file", type=Path, help="Path to a commit message file")
    message_parser.add_argument("--subject", default="", help="Commit subject to lint directly")

    range_parser = subparsers.add_parser("range", help="Lint commit subjects in a git range")
    range_parser.add_argument("--base-ref", required=True, help="Base ref to compare against HEAD")

    args = parser.parse_args()

    if args.command == "message":
        subject = args.subject
        if args.file:
            subject = first_subject_from_file(args.file)
        errors = lint_subject(subject)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print(subject)
        return 0

    subjects = subjects_from_range(args.base_ref)
    if not subjects:
        print(f"No commits to lint in range {args.base_ref}..HEAD")
        return 0

    failed = False
    for subject in subjects:
        errors = lint_subject(subject)
        if errors:
            failed = True
            print(subject, file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)

    if failed:
        return 1

    print(f"Linted {len(subjects)} commit subject(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
