#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${APP_DIR}/../.." && pwd)"

TAG="${MACOS_RELEASE_TAG:-latest}"
ASSET_DIR="${MACOS_ASSET_DIR:-${APP_DIR}/.build/artifacts}"
VERSION="${MACOS_RELEASE_VERSION:-}"
SHA="${GITHUB_SHA:-$(git -C "${REPO_ROOT}" rev-parse HEAD)}"
TITLE="${MACOS_RELEASE_TITLE:-Elephant Agent latest}"
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
DRY_RUN="${MACOS_RELEASE_DRY_RUN:-0}"
SIGNING_MODE="${MACOS_RELEASE_SIGNING_MODE:-unknown}"

project_version() {
  python3 - "${REPO_ROOT}/pyproject.toml" <<'PY'
import re
import sys

for line in open(sys.argv[1], encoding="utf-8"):
    match = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
    if match:
        print(match.group(1))
        raise SystemExit(0)
print("0.1.0")
PY
}

repository_slug() {
  if [[ -n "${GITHUB_REPOSITORY:-}" ]]; then
    printf '%s\n' "${GITHUB_REPOSITORY}"
    return
  fi

  local remote
  remote="$(git -C "${REPO_ROOT}" remote get-url origin 2>/dev/null || true)"
  case "${remote}" in
    git@github.com:*)
      remote="${remote#git@github.com:}"
      remote="${remote%.git}"
      printf '%s\n' "${remote}"
      ;;
    https://github.com/*)
      remote="${remote#https://github.com/}"
      remote="${remote%.git}"
      printf '%s\n' "${remote}"
      ;;
    *)
      echo "Could not infer GitHub repository slug from origin remote: ${remote}" >&2
      exit 1
      ;;
  esac
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "Missing required command: python3" >&2
  exit 1
fi

REPOSITORY="$(repository_slug)"
if [[ -z "${VERSION}" ]]; then
  VERSION="$(project_version)"
fi

if [[ ! -d "${ASSET_DIR}" ]]; then
  echo "Asset directory not found: ${ASSET_DIR}" >&2
  exit 1
fi

MANIFEST="${ASSET_DIR}/latest.json"
python3 - "${ASSET_DIR}" "${TAG}" "${REPOSITORY}" "${SHA}" "${VERSION}" "${SERVER_URL}" "${SIGNING_MODE}" <<'PY'
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

asset_dir = pathlib.Path(sys.argv[1])
tag = sys.argv[2]
repository = sys.argv[3]
sha = sys.argv[4]
version = sys.argv[5]
server_url = sys.argv[6].rstrip("/")
signing_mode = sys.argv[7]
base_url = f"{server_url}/{repository}/releases/download/{tag}"

platform_map = {
    "aarch64-apple-darwin": "darwin-aarch64",
    "x86_64-apple-darwin": "darwin-x86_64",
}
platforms = {}
pattern = re.compile(r"^ElephantAgent_(?P<version>.+)_(?P<target>aarch64-apple-darwin|x86_64-apple-darwin)\.(?P<kind>dmg|app\.zip)$")

for path in sorted(asset_dir.rglob("*")):
    if not path.is_file():
        continue
    match = pattern.match(path.name)
    if not match:
        continue
    target = match.group("target")
    platform_key = platform_map[target]
    kind = "app_zip" if match.group("kind") == "app.zip" else "dmg"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    platforms.setdefault(platform_key, {"target": target})[kind] = {
        "url": f"{base_url}/{path.name}",
        "sha256": digest,
        "size": path.stat().st_size,
    }

payload = {
    "version": version,
    "tag": tag,
    "commit": sha,
    "signing_mode": signing_mode,
    "pub_date": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "platforms": platforms,
}
(asset_dir / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

ASSETS=()
while IFS= read -r -d '' asset; do
  ASSETS+=("${asset}")
done < <(find "${ASSET_DIR}" -type f \( -name '*.dmg' -o -name '*.app.zip' -o -name '*.sha256' -o -name 'latest.json' \) -print0 | sort -z)

if [[ "${#ASSETS[@]}" -eq 0 ]]; then
  echo "No release assets found in ${ASSET_DIR}" >&2
  exit 1
fi

NOTES_FILE="$(mktemp)"
{
  printf 'Automated latest macOS build for `%s`.\n\n' "${SHA}"
  printf 'This release is intentionally replaced on each push to `main`.\n\n'
  printf 'Signing mode: `%s`.\n\n' "${SIGNING_MODE}"
  if [[ "${SIGNING_MODE}" == "ad-hoc" ]]; then
    printf 'These artifacts are uploaded directly from CI without Apple Developer ID notarization. They are useful for testing and GitHub artifact distribution, but macOS Gatekeeper may require the user to right-click Open or remove quarantine.\n\n'
  fi
  printf 'Artifacts:\n'
  for asset in "${ASSETS[@]}"; do
    printf -- '- `%s`\n' "$(basename "${asset}")"
  done
} > "${NOTES_FILE}"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "DRY RUN: would replace GitHub release ${REPOSITORY}@${TAG}"
  printf 'DRY RUN: asset %s\n' "${ASSETS[@]}"
  echo "DRY RUN: wrote ${MANIFEST}"
  rm -f "${NOTES_FILE}"
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "Missing required command: gh" >&2
  exit 1
fi

echo "Replacing GitHub release ${REPOSITORY}@${TAG}"
gh release delete "${TAG}" --repo "${REPOSITORY}" --yes --cleanup-tag >/dev/null 2>&1 || true
git -C "${REPO_ROOT}" tag -f "${TAG}" "${SHA}"
git -C "${REPO_ROOT}" push origin "refs/tags/${TAG}" --force
gh release create "${TAG}" "${ASSETS[@]}" \
  --repo "${REPOSITORY}" \
  --target "${SHA}" \
  --title "${TITLE}" \
  --notes-file "${NOTES_FILE}" \
  --latest

rm -f "${NOTES_FILE}"
echo "Published ${SERVER_URL}/${REPOSITORY}/releases/tag/${TAG}"
