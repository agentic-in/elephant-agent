#!/usr/bin/env sh

set -eu

ROOT_DIR=$(cd -- "$(dirname "$0")" && pwd)
DIST_DIR="${ROOT_DIR}/dist"

ensure_node_modules() {
  if [ ! -d "${ROOT_DIR}/node_modules" ]; then
    echo "Installing Docusaurus dependencies for apps/site"
    (
      cd "${ROOT_DIR}"
      npm ci
    )
  fi
}

ensure_node_modules

(
  cd "${ROOT_DIR}"
  node ./scripts/patch-docusaurus-bundler.mjs
)

rm -rf "${DIST_DIR}"

BUILD_LOG=$(mktemp "${TMPDIR:-/tmp}/elephant-site-build.XXXXXX")

if (
  cd "${ROOT_DIR}"
  CI=1 npm run build -- --out-dir "${DIST_DIR}" >"${BUILD_LOG}" 2>&1
); then
  cat "${BUILD_LOG}"
  rm -f "${BUILD_LOG}"
else
  cat "${BUILD_LOG}" >&2
  rm -f "${BUILD_LOG}"
  exit 1
fi

echo "Built Elephant Agent site into ${DIST_DIR}"
