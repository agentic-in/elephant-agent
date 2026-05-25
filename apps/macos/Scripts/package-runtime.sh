#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "Usage: package-runtime.sh <runtime-root> <repo-root> <artifact-target> <cache-dir>" >&2
  exit 2
fi

RUNTIME_ROOT="$1"
REPO_ROOT="$2"
ARTIFACT_TARGET="$3"
CACHE_DIR="$4"
mkdir -p "${CACHE_DIR}"
UV_CACHE_DIR="${UV_CACHE_DIR:-${CACHE_DIR}/uv}"
export UV_CACHE_DIR
mkdir -p "${UV_CACHE_DIR}"

PYTHON_VERSION="${MACOS_RUNTIME_PYTHON_VERSION:-3.12}"
PYTHON_ROOT="${RUNTIME_ROOT}/python"
SITE_PACKAGES="${RUNTIME_ROOT}/site-packages"
BROWSERS_ROOT="${RUNTIME_ROOT}/ms-playwright"
MANIFEST="${RUNTIME_ROOT}/manifest.json"
EMBEDDING_RUNTIME_REQUIREMENTS=(
  "sentence-transformers>=3,<4"
  "huggingface-hub>=0.30,<1"
  "modelscope>=1.10,<2"
)
VOICE_RUNTIME_REQUIREMENTS=(
  "edge-tts>=7.2,<8"
  "funasr>=1.2,<2"
  "modelscope>=1.10,<2"
  "setuptools>=69"
  "torchaudio>=2.11,<3"
)

fail() {
  echo "Runtime packaging failed: $*" >&2
  exit 1
}

find_python_in_root() {
  local root="$1"
  for candidate in \
    "${root}/bin/python3.12" \
    "${root}/bin/python3" \
    "${root}/bin/python"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

copy_tree_without_metadata() {
  local source="$1"
  local destination="$2"
  rm -rf "${destination}"
  mkdir -p "${destination}"
  (
    cd "${source}"
    COPYFILE_DISABLE=1 tar -cf - .
  ) | (
    cd "${destination}"
    tar -xf -
  )
}

resolve_source_python() {
  if [[ -n "${MACOS_RUNTIME_PYTHON:-}" ]]; then
    if [[ -d "${MACOS_RUNTIME_PYTHON}" ]]; then
      find_python_in_root "${MACOS_RUNTIME_PYTHON}" || fail "no python executable under MACOS_RUNTIME_PYTHON=${MACOS_RUNTIME_PYTHON}"
      return
    fi
    if [[ -x "${MACOS_RUNTIME_PYTHON}" ]]; then
      printf '%s\n' "${MACOS_RUNTIME_PYTHON}"
      return
    fi
    fail "MACOS_RUNTIME_PYTHON is not executable: ${MACOS_RUNTIME_PYTHON}"
  fi

  if ! command -v uv >/dev/null 2>&1; then
    fail "uv is required to download the bundled CPython runtime; set MACOS_BUNDLE_RUNTIME=0 for a bootstrap-only build"
  fi

  mkdir -p "${CACHE_DIR}/python"
  UV_PYTHON_INSTALL_DIR="${CACHE_DIR}/python" uv python install "${PYTHON_VERSION}" --managed-python --no-bin
  UV_PYTHON_INSTALL_DIR="${CACHE_DIR}/python" uv python find "${PYTHON_VERSION}" --managed-python --no-project
}

validate_python_arch() {
  local python="$1"
  if ! command -v lipo >/dev/null 2>&1; then
    return
  fi
  local archs
  archs="$(lipo -archs "${python}" 2>/dev/null || true)"
  case "${ARTIFACT_TARGET}" in
    aarch64-apple-darwin)
      [[ "${archs}" == *"arm64"* ]] || fail "runtime python is not arm64: ${python} (${archs:-unknown})"
      ;;
    x86_64-apple-darwin)
      [[ "${archs}" == *"x86_64"* ]] || fail "runtime python is not x86_64: ${python} (${archs:-unknown})"
      ;;
  esac
}

install_embedding_runtime_dependencies() {
  local target="${1:-${SITE_PACKAGES}}"
  if command -v uv >/dev/null 2>&1; then
    uv pip install \
      --python "${bundled_python}" \
      --target "${target}" \
      --link-mode copy \
      --prerelease=allow \
      "${EMBEDDING_RUNTIME_REQUIREMENTS[@]}"
  else
    "${bundled_python}" -m pip install --target "${target}" "${EMBEDDING_RUNTIME_REQUIREMENTS[@]}"
  fi
}

install_voice_runtime_dependencies() {
  local target="${1:-${SITE_PACKAGES}}"
  if command -v uv >/dev/null 2>&1; then
    uv pip install \
      --python "${bundled_python}" \
      --target "${target}" \
      --link-mode copy \
      --prerelease=allow \
      "${VOICE_RUNTIME_REQUIREMENTS[@]}"
  else
    "${bundled_python}" -m pip install --target "${target}" "${VOICE_RUNTIME_REQUIREMENTS[@]}"
  fi
}

runtime_dependency_cache_key() {
  local requirements="$1"
  local python_version="$2"
  local key_source="${CACHE_DIR}/runtime-dependency-cache-key.txt"
  {
    printf 'target=%s\n' "${ARTIFACT_TARGET}"
    printf 'python=%s\n' "${python_version}"
    printf 'requirements=\n'
    cat "${requirements}"
    printf '\nembedding_requirements=\n'
    printf '%s\n' "${EMBEDDING_RUNTIME_REQUIREMENTS[@]}"
    printf '\nvoice_requirements=\n'
    printf '%s\n' "${VOICE_RUNTIME_REQUIREMENTS[@]}"
  } > "${key_source}"
  shasum -a 256 "${key_source}" | awk '{print $1}'
}

install_runtime_dependency_layer() {
  local requirements="$1"
  local python_version="$2"
  local key
  key="$(runtime_dependency_cache_key "${requirements}" "${python_version}")"
  local dependency_cache="${CACHE_DIR}/site-packages-${ARTIFACT_TARGET}-${key}"
  local marker="${dependency_cache}/.elephant-runtime-cache-ok"

  rm -rf "${SITE_PACKAGES}"
  if [[ -f "${marker}" ]]; then
    echo "Reusing cached Python dependency layer ${dependency_cache}"
    copy_tree_without_metadata "${dependency_cache}" "${SITE_PACKAGES}"
    return
  fi

  local temp_cache="${dependency_cache}.tmp"
  rm -rf "${temp_cache}"
  mkdir -p "${temp_cache}"
  echo "Building cached Python dependency layer ${dependency_cache}"
  if command -v uv >/dev/null 2>&1; then
    uv pip install \
      --python "${bundled_python}" \
      --target "${temp_cache}" \
      --link-mode copy \
      --prerelease=allow \
      --requirements "${requirements}"
  else
    "${bundled_python}" -m ensurepip --upgrade
    "${bundled_python}" -m pip install --upgrade pip
    "${bundled_python}" -m pip install --target "${temp_cache}" --requirements "${requirements}"
  fi
  install_embedding_runtime_dependencies "${temp_cache}"
  install_voice_runtime_dependencies "${temp_cache}"
  PYTHONPATH="${temp_cache}" "${bundled_python}" - <<'PY'
import importlib.util

import playwright  # noqa: F401

for module_name in ("sentence_transformers", "huggingface_hub", "modelscope", "edge_tts"):
    if importlib.util.find_spec(module_name) is None:
        raise SystemExit(f"missing bundled runtime dependency: {module_name}")
PY
  touch "${temp_cache}/.elephant-runtime-cache-ok"
  rm -rf "${dependency_cache}"
  mv "${temp_cache}" "${dependency_cache}"
  copy_tree_without_metadata "${dependency_cache}" "${SITE_PACKAGES}"
}

source_python="$(resolve_source_python)"
source_python_root="$(cd "$(dirname "${source_python}")/.." && pwd)"
validate_python_arch "${source_python}"

echo "Bundling Python runtime from ${source_python_root}"
rm -rf "${RUNTIME_ROOT}"
copy_tree_without_metadata "${source_python_root}" "${PYTHON_ROOT}"

bundled_python="$(find_python_in_root "${PYTHON_ROOT}")"
"${bundled_python}" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(f"Python 3.12+ is required, got {sys.version}")
PY

rm -rf "${SITE_PACKAGES}"
mkdir -p "${SITE_PACKAGES}"
python_version="$("${bundled_python}" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

if command -v uv >/dev/null 2>&1; then
  requirements="${CACHE_DIR}/runtime-requirements.txt"
  uv export \
    --frozen \
    --no-dev \
    --no-emit-project \
    --no-hashes \
    --format requirements.txt \
    --output-file "${requirements}" \
    --python "${bundled_python}" >/dev/null
  install_runtime_dependency_layer "${requirements}" "${python_version}"
  uv pip install \
    --python "${bundled_python}" \
    --target "${SITE_PACKAGES}" \
    --link-mode copy \
    --no-deps \
    "${REPO_ROOT}"
else
  "${bundled_python}" -m ensurepip --upgrade
  "${bundled_python}" -m pip install --upgrade pip
  "${bundled_python}" -m pip install --target "${SITE_PACKAGES}" "${REPO_ROOT}"
  install_embedding_runtime_dependencies "${SITE_PACKAGES}"
  install_voice_runtime_dependencies "${SITE_PACKAGES}"
fi

PYTHONPATH="${SITE_PACKAGES}" "${bundled_python}" - <<'PY'
import importlib.util

import apps.api  # noqa: F401
import playwright  # noqa: F401

for module_name in ("sentence_transformers", "huggingface_hub", "modelscope", "edge_tts"):
    if importlib.util.find_spec(module_name) is None:
        raise SystemExit(f"missing bundled runtime dependency: {module_name}")
PY

seed_playwright_browser_cache() {
  local dry_run="$1"
  local cache_root
  mkdir -p "${BROWSERS_ROOT}"
  for cache_root in \
    "${CACHE_DIR}/ms-playwright" \
    "${HOME}/Library/Caches/ms-playwright" \
    "${HOME}/.cache/ms-playwright"; do
    [[ -d "${cache_root}" ]] || continue
    while IFS= read -r revision; do
      local name="chromium_headless_shell-${revision}"
      if [[ -d "${cache_root}/${name}" && ! -d "${BROWSERS_ROOT}/${name}" ]]; then
        echo "Seeding ${name} from ${cache_root}"
        copy_tree_without_metadata "${cache_root}/${name}" "${BROWSERS_ROOT}/${name}"
      fi
    done < <(printf '%s\n' "${dry_run}" | sed -n 's/.*playwright chromium-headless-shell v\([0-9][0-9]*\).*/\1/p')
    while IFS= read -r revision; do
      local name="ffmpeg-${revision}"
      if [[ -d "${cache_root}/${name}" && ! -d "${BROWSERS_ROOT}/${name}" ]]; then
        echo "Seeding ${name} from ${cache_root}"
        copy_tree_without_metadata "${cache_root}/${name}" "${BROWSERS_ROOT}/${name}"
      fi
    done < <(printf '%s\n' "${dry_run}" | sed -n 's/.*playwright ffmpeg v\([0-9][0-9]*\).*/\1/p')
  done
}

rm -rf "${BROWSERS_ROOT}"
playwright_dry_run="$(
  PYTHONPATH="${SITE_PACKAGES}" \
  PLAYWRIGHT_BROWSERS_PATH="${BROWSERS_ROOT}" \
  PLAYWRIGHT_SKIP_BROWSER_GC=1 \
    "${bundled_python}" -m playwright install --dry-run --only-shell chromium
)"
seed_playwright_browser_cache "${playwright_dry_run}"
PYTHONPATH="${SITE_PACKAGES}" \
PLAYWRIGHT_BROWSERS_PATH="${BROWSERS_ROOT}" \
PLAYWRIGHT_SKIP_BROWSER_GC=1 \
  "${bundled_python}" -m playwright install --only-shell chromium
if [[ -d "${BROWSERS_ROOT}" ]]; then
  copy_tree_without_metadata "${BROWSERS_ROOT}" "${CACHE_DIR}/ms-playwright"
fi

find "${RUNTIME_ROOT}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${RUNTIME_ROOT}" -type f -name '*.pyc' -delete

python_version="$("${bundled_python}" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
cat > "${MANIFEST}" <<JSON
{
  "runtime": "bundled-python",
  "target": "${ARTIFACT_TARGET}",
  "python": "python/bin/$(basename "${bundled_python}")",
  "sitePackages": "site-packages",
  "playwrightBrowsersPath": "ms-playwright",
  "pythonVersion": "${python_version}"
}
JSON

du -sh "${RUNTIME_ROOT}"
