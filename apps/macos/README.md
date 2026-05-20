# Elephant Agent for macOS

Native macOS shell for Elephant Agent. The app uses SwiftUI for the primary interface and small AppKit bridges for window polish, file picking, Finder reveal, menu commands, and notifications.

The mac app does not replace the Python core. It starts the existing `apps.api` service on a free loopback port, reads internal dashboard projections, and presents Elephant as an all-in-one local desktop workspace.

## Build

```bash
swift build --package-path apps/macos
apps/macos/Scripts/build-app.sh
open -n "apps/macos/.build/release/Elephant Agent.app"
```

Full Xcode is not required when the installed Command Line Tools and macOS SDK match. The packaging script creates a local `.app`, copies the site brand assets into the bundle resources, signs ad hoc by default, and emits a `.dmg`, `.app.zip`, and SHA256 files under `apps/macos/.build/artifacts/<target>/`.

The repo-level Makefile wraps the release paths:

```bash
make macos-build
make macos-build MACOS_TARGET=aarch64-apple-darwin
make macos-build MACOS_TARGET=x86_64-apple-darwin
make macos-build-all
```

Developer ID distribution builds can opt into signing and notarization:

```bash
make macos-build-all \
  MACOS_SIGNING_IDENTITY="Developer ID Application: Example Team (TEAMID)" \
  MACOS_NOTARIZE=1 \
  APPLE_ID="apple-id@example.com" \
  APPLE_PASSWORD="app-specific-password" \
  APPLE_TEAM_ID="TEAMID"
```

`make macos-release-latest` expects `gh` authentication and replaces the GitHub `latest` release/tag with the current local artifacts. The CI workflow `.github/workflows/macos-latest-release.yml` runs the same build on each push to `main`, uploads both macOS architecture artifacts, writes `latest.json`, and replaces the `latest` GitHub release.
