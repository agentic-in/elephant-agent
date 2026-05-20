#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${APP_DIR}/../.." && pwd)"

APP_NAME="${MACOS_APP_NAME:-Elephant Agent}"
BUNDLE_IDENTIFIER="${MACOS_BUNDLE_IDENTIFIER:-ai.agentic.elephant.mac}"
DEPLOYMENT_TARGET="${MACOS_DEPLOYMENT_TARGET:-13.0}"
SIGNING_IDENTITY="${MACOS_SIGNING_IDENTITY:--}"
NOTARIZE="${MACOS_NOTARIZE:-0}"

host_target() {
  case "$(uname -m)" in
    arm64|aarch64) printf '%s\n' "aarch64-apple-darwin" ;;
    x86_64|amd64) printf '%s\n' "x86_64-apple-darwin" ;;
    *) printf '%s\n' "$(uname -m)-apple-darwin" ;;
  esac
}

project_version() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - "${REPO_ROOT}/pyproject.toml" <<'PY'
import re
import sys

path = sys.argv[1]
for line in open(path, encoding="utf-8"):
    match = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
    if match:
        print(match.group(1))
        raise SystemExit(0)
print("0.1.0")
PY
    return
  fi
  awk -F '"' '/^version = / { print $2; found=1; exit } END { if (!found) print "0.1.0" }' "${REPO_ROOT}/pyproject.toml"
}

short_bundle_version() {
  local raw="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$raw" <<'PY'
import re
import sys

parts = re.findall(r"\d+", sys.argv[1])
parts = (parts + ["0", "0", "0"])[:3]
print(".".join(parts))
PY
    return
  fi
  printf '%s\n' "${raw}" | sed -E 's/[^0-9.].*$//' | awk 'NF { print; found=1 } END { if (!found) print "0.1.0" }'
}

sanitize_version() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '-'
}

build_number() {
  git -C "${REPO_ROOT}" rev-list --count HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S
}

MACOS_TARGET="${MACOS_TARGET:-$(host_target)}"
case "${MACOS_TARGET}" in
  aarch64-apple-darwin|arm64-apple-darwin)
    ARTIFACT_TARGET="aarch64-apple-darwin"
    SWIFT_ARCH="arm64"
    ;;
  x86_64-apple-darwin)
    ARTIFACT_TARGET="x86_64-apple-darwin"
    SWIFT_ARCH="x86_64"
    ;;
  *)
    echo "Unsupported MACOS_TARGET: ${MACOS_TARGET}" >&2
    exit 2
    ;;
esac

RAW_VERSION="$(project_version)"
APP_VERSION="${MACOS_APP_VERSION:-${RAW_VERSION}}"
APP_VERSION_SAFE="$(sanitize_version "${APP_VERSION}")"
BUNDLE_SHORT_VERSION="${MACOS_BUNDLE_SHORT_VERSION:-$(short_bundle_version "${APP_VERSION}")}"
APP_BUILD_NUMBER="${MACOS_APP_BUILD_NUMBER:-$(build_number)}"

BUILD_ROOT="${MACOS_BUILD_ROOT:-${APP_DIR}/.build/release}"
BUILD_DIR="${MACOS_BUILD_DIR:-${BUILD_ROOT}/${ARTIFACT_TARGET}}"
ARTIFACT_ROOT="${MACOS_ASSET_DIR:-${APP_DIR}/.build/artifacts}"
ARTIFACT_DIR="${MACOS_ARTIFACT_DIR:-${ARTIFACT_ROOT}/${ARTIFACT_TARGET}}"
BINARY="${BUILD_DIR}/ElephantAgentMac"
BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
DMG="${BUILD_DIR}/${APP_NAME}.dmg"
CONTENTS="${BUNDLE}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"
ARTIFACT_PREFIX="ElephantAgent_${APP_VERSION_SAFE}_${ARTIFACT_TARGET}"
ARTIFACT_DMG="${ARTIFACT_DIR}/${ARTIFACT_PREFIX}.dmg"
ARTIFACT_APP_ZIP="${ARTIFACT_DIR}/${ARTIFACT_PREFIX}.app.zip"

if [[ "${NOTARIZE}" == "auto" ]]; then
  if [[ "${SIGNING_IDENTITY}" != "-" \
    && -n "${APPLE_ID:-}" \
    && -n "${APPLE_PASSWORD:-}" \
    && -n "${APPLE_TEAM_ID:-}" ]]; then
    NOTARIZE="1"
  else
    NOTARIZE="0"
  fi
fi

require_macos_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required macOS tool: $1" >&2
    exit 1
  fi
}

copy_if_exists() {
  local source="$1"
  local destination="$2"
  if [[ -f "${source}" ]]; then
    cp "${source}" "${destination}"
  fi
}

sha256_file() {
  local file="$1"
  shasum -a 256 "${file}" | awk '{ print $1 }'
}

write_sha256_file() {
  local file="$1"
  printf '%s  %s\n' "$(sha256_file "${file}")" "$(basename "${file}")" > "${file}.sha256"
}

sign_path() {
  local path="$1"
  require_macos_tool codesign
  if [[ "${SIGNING_IDENTITY}" == "-" ]]; then
    codesign --force --deep --sign - "${path}" >/dev/null
  else
    codesign --force --deep --options runtime --timestamp --sign "${SIGNING_IDENTITY}" "${path}" >/dev/null
  fi
}

notarize_submission() {
  local path="$1"
  local label="$2"
  if [[ "${NOTARIZE}" != "1" ]]; then
    return
  fi
  if [[ "${SIGNING_IDENTITY}" == "-" ]]; then
    echo "Cannot notarize ${label}: MACOS_SIGNING_IDENTITY is ad-hoc." >&2
    exit 1
  fi
  for var in APPLE_ID APPLE_PASSWORD APPLE_TEAM_ID; do
    if [[ -z "${!var:-}" ]]; then
      echo "Cannot notarize ${label}: missing ${var}." >&2
      exit 1
    fi
  done
  require_macos_tool xcrun
  echo "Notarizing ${label}..."
  xcrun notarytool submit "${path}" \
    --apple-id "${APPLE_ID}" \
    --password "${APPLE_PASSWORD}" \
    --team-id "${APPLE_TEAM_ID}" \
    --wait
}

notarize_path() {
  local path="$1"
  local label="$2"
  notarize_submission "${path}" "${label}"
  if [[ "${NOTARIZE}" != "1" ]]; then
    return
  fi
  xcrun stapler staple "${path}"
}

require_macos_tool xcrun
require_macos_tool hdiutil
require_macos_tool ditto
require_macos_tool shasum

mkdir -p "${BUILD_DIR}" "${ARTIFACT_DIR}"
rm -rf "${BUNDLE}" "${DMG}" "${ARTIFACT_DMG}" "${ARTIFACT_APP_ZIP}"

SDK_PATH="$(xcrun --show-sdk-path)"
SWIFT_TARGET="${SWIFT_ARCH}-apple-macosx${DEPLOYMENT_TARGET}"
SWIFTPM_LOG="${BUILD_DIR}/swiftpm-build.log"

if [[ "${MACOS_USE_SWIFTPM:-1}" == "1" && "${ARTIFACT_TARGET}" == "$(host_target)" ]]; then
  if swift build -c release --package-path "${APP_DIR}" --build-path "${BUILD_DIR}/swiftpm" >"${SWIFTPM_LOG}" 2>&1; then
    cp "${BUILD_DIR}/swiftpm/release/ElephantAgentMac" "${BINARY}"
    echo "SwiftPM build succeeded for ${ARTIFACT_TARGET}."
  else
    echo "SwiftPM build failed; falling back to direct swiftc compile." >&2
    echo "SwiftPM log: ${SWIFTPM_LOG}" >&2
    /usr/bin/swiftc -O -target "${SWIFT_TARGET}" -sdk "${SDK_PATH}" -parse-as-library "${APP_DIR}"/Sources/*.swift -o "${BINARY}"
  fi
else
  /usr/bin/swiftc -O -target "${SWIFT_TARGET}" -sdk "${SDK_PATH}" -parse-as-library "${APP_DIR}"/Sources/*.swift -o "${BINARY}"
fi

if command -v lipo >/dev/null 2>&1; then
  lipo -info "${BINARY}"
fi

mkdir -p "${MACOS}" "${RESOURCES}/Brand" "${RESOURCES}/Resources" "${RESOURCES}/Install"
install -m 755 "${BINARY}" "${MACOS}/${APP_NAME}"

printf "%s\n" "${REPO_ROOT}" > "${RESOURCES}/RepoRoot.txt"
if command -v python3 >/dev/null 2>&1; then
  command -v python3 > "${RESOURCES}/PythonPath.txt"
fi
install -m 755 "${REPO_ROOT}/install.sh" "${RESOURCES}/Install/install.sh"

BRAND_DIR="${REPO_ROOT}/apps/site/static/assets/brand"
if [[ -d "${BRAND_DIR}" ]]; then
  copy_if_exists "${BRAND_DIR}/elephant-logo.png" "${RESOURCES}/Brand/elephant-logo.png"
  copy_if_exists "${BRAND_DIR}/favicon.png" "${RESOURCES}/Brand/favicon.png"
  copy_if_exists "${BRAND_DIR}/elephant-savanna-snr.jpg" "${RESOURCES}/Brand/elephant-savanna-snr.jpg"
  copy_if_exists "${BRAND_DIR}/elephant-body-image-02.webp" "${RESOURCES}/Brand/elephant-body-image-02.webp"
fi

SITE_RESOURCES_DIR="${REPO_ROOT}/apps/site/static/assets/resources"
if [[ -d "${SITE_RESOURCES_DIR}" ]]; then
  copy_if_exists "${SITE_RESOURCES_DIR}/readme-1.png" "${RESOURCES}/Resources/readme-1.png"
  copy_if_exists "${SITE_RESOURCES_DIR}/readme-2.png" "${RESOURCES}/Resources/readme-2.png"
  copy_if_exists "${SITE_RESOURCES_DIR}/paper-1.png" "${RESOURCES}/Resources/paper-1.png"
  copy_if_exists "${SITE_RESOURCES_DIR}/paper-2.png" "${RESOURCES}/Resources/paper-2.png"
fi

ICON_SOURCE="${RESOURCES}/Brand/favicon.png"
ICONSET="${RESOURCES}/AppIcon.iconset"
if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1 && [[ -f "${ICON_SOURCE}" ]]; then
  rm -rf "${ICONSET}"
  mkdir -p "${ICONSET}"
  for size in 16 32 128 256 512; do
    sips -z "${size}" "${size}" "${ICON_SOURCE}" --out "${ICONSET}/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "${double}" "${double}" "${ICON_SOURCE}" --out "${ICONSET}/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "${ICONSET}" -o "${RESOURCES}/AppIcon.icns"
  rm -rf "${ICONSET}"
fi

cat > "${CONTENTS}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>${APP_NAME}</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>${BUNDLE_IDENTIFIER}</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key>
  <string>${APP_NAME}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${BUNDLE_SHORT_VERSION}</string>
  <key>CFBundleVersion</key>
  <string>${APP_BUILD_NUMBER}</string>
  <key>LSApplicationCategoryType</key>
  <string>public.app-category.productivity</string>
  <key>LSMinimumSystemVersion</key>
  <string>${DEPLOYMENT_TARGET}</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Elephant Agent uses the microphone to turn your voice into chat text when you tap the voice input button.</string>
  <key>NSSpeechRecognitionUsageDescription</key>
  <string>Elephant Agent uses speech recognition to transcribe voice input into the chat composer.</string>
  <key>NSSupportsAutomaticGraphicsSwitching</key>
  <true/>
</dict>
</plist>
PLIST

sign_path "${BUNDLE}"
codesign --verify --deep --strict --verbose=2 "${BUNDLE}"

if [[ "${NOTARIZE}" == "1" ]]; then
  APP_ZIP_FOR_NOTARY="$(mktemp "/tmp/ElephantAgent-${ARTIFACT_TARGET}-notary-XXXXXX.zip")"
  ditto -c -k --keepParent "${BUNDLE}" "${APP_ZIP_FOR_NOTARY}"
  notarize_submission "${APP_ZIP_FOR_NOTARY}" "${APP_NAME}.app"
  rm -f "${APP_ZIP_FOR_NOTARY}"
  xcrun stapler staple "${BUNDLE}"
fi

STAGE="$(mktemp -d)"
cleanup() {
  rm -rf "${STAGE}"
}
trap cleanup EXIT
ditto "${BUNDLE}" "${STAGE}/${APP_NAME}.app"
ln -s /Applications "${STAGE}/Applications"
hdiutil create -volname "${APP_NAME}" -srcfolder "${STAGE}" -ov -format UDZO "${DMG}" >/dev/null

if [[ "${SIGNING_IDENTITY}" != "-" ]]; then
  codesign --force --timestamp --sign "${SIGNING_IDENTITY}" "${DMG}" >/dev/null
  notarize_path "${DMG}" "${APP_NAME}.dmg"
fi

ditto -c -k --keepParent "${BUNDLE}" "${ARTIFACT_APP_ZIP}"
cp "${DMG}" "${ARTIFACT_DMG}"
write_sha256_file "${ARTIFACT_DMG}"
write_sha256_file "${ARTIFACT_APP_ZIP}"

echo "macOS build output paths:"
printf '  app: %s\n' "${BUNDLE}"
printf '  dmg: %s\n' "${DMG}"
printf '  artifact_dmg: %s\n' "${ARTIFACT_DMG}"
printf '  artifact_dmg_sha256: %s\n' "${ARTIFACT_DMG}.sha256"
printf '  artifact_app_zip: %s\n' "${ARTIFACT_APP_ZIP}"
printf '  artifact_app_zip_sha256: %s\n' "${ARTIFACT_APP_ZIP}.sha256"
