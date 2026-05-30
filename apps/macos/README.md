# Elephant Agent for macOS

Native macOS shell for Elephant Agent. The app uses SwiftUI for the primary interface and small AppKit bridges for window polish, file picking, Finder reveal, menu commands, and notifications.

The mac app does not replace the Python core. It starts the existing `apps.api` service on a free loopback port, reads internal dashboard projections, and presents Elephant as an all-in-one local desktop workspace.

## Build

```bash
make macos-build
open -n "apps/macos/.build/release/$(uname -m | sed 's/arm64/aarch64/')-apple-darwin/Elephant Agent.app"
```

Full Xcode is not required when the installed Command Line Tools and macOS SDK match. The packaging script creates a local `.app`, copies the site brand assets into the bundle resources, skips codesign by default for local speed, and emits a `.dmg`, `.app.zip`, and SHA256 files under `apps/macos/.build/artifacts/<target>/`.

By default, `make macos-build` attempts to produce a self-contained app on the current Mac architecture. When `uv` is available and the requested `MACOS_TARGET` matches the host architecture, the bundle includes:

- `Contents/Resources/Runtime/python`: managed CPython 3.12
- `Contents/Resources/Runtime/site-packages`: Elephant Agent and Python dependencies
- `Contents/Resources/Runtime/ms-playwright`: Playwright Chromium headless shell

Set `MACOS_BUNDLE_RUNTIME=0` for a lightweight bootstrap build that falls back to the bundled `Install/install.sh` on machines without a developer repo. Set `MACOS_BUNDLE_RUNTIME=1` to require the embedded runtime and fail instead of falling back. Cross-architecture self-contained builds should run on a matching macOS runner or pass `MACOS_RUNTIME_PYTHON=/path/to/python3.12` for the target architecture.

Runtime downloads and resolved dependency layers are cached under `~/Library/Caches/ElephantAgent/macos-runtime/<target>/` by default, including the managed Python install, `uv` wheel cache, the hashed `site-packages` dependency layer, and the Playwright browser payload. Set `MACOS_RUNTIME_BUILD_CACHE=/path/to/cache` to use another cache location.

The repo-level Makefile wraps the release paths:

```bash
make macos-build
make macos-build MACOS_TARGET=aarch64-apple-darwin
make macos-build MACOS_TARGET=x86_64-apple-darwin
make macos-build-all
make macos-build MACOS_BUNDLE_RUNTIME=1
```

Developer ID distribution builds can opt into signing and notarization:

```bash
make macos-build-all \
  MACOS_BUNDLE_RUNTIME=1 \
  MACOS_SIGNING_IDENTITY="Developer ID Application: Example Team (TEAMID)" \
  MACOS_NOTARIZE=1 \
  APPLE_ID="apple-id@example.com" \
  APPLE_PASSWORD="app-specific-password" \
  APPLE_TEAM_ID="TEAMID"
```

Local builds default to `MACOS_SIGNING_IDENTITY=-`, which creates an ad-hoc signed test artifact suitable for validating privacy-sensitive flows such as microphone and speech recognition permissions. The ad-hoc path uses the same hardened-runtime option and local audio-input entitlements as signed app builds. Use `MACOS_SIGNING_IDENTITY=none` only for packaging-only debugging where macOS privacy prompts are not being exercised. Official shareable releases should use Developer ID signing and notarization.

`make macos-release-latest` expects `gh` authentication and replaces the GitHub `latest` release/tag with the current local artifacts. The CI workflow `.github/workflows/macos-latest-release.yml` runs the same build on each push to `main`, uploads both macOS architecture artifacts, writes `latest.json`, and replaces the `latest` GitHub release.

The `latest` CI release forces `MACOS_BUNDLE_RUNTIME=1`, installs `uv`, builds each architecture on a matching macOS runner, and checks `Contents/Resources/Runtime` before upload. The workflow explicitly sets either a Developer ID signing identity or `MACOS_SIGNING_IDENTITY=-` for the manual `allow_unsigned=true` fallback, then validates codesign and stapled notarization tickets when Developer ID signing is active. If the self-contained runtime or distribution signing path is missing on a push to `main`, CI fails instead of publishing a bootstrap-sized or unsigned DMG. The bootstrap/ad-hoc fallback remains available for local or manually dispatched emergency builds with `MACOS_BUNDLE_RUNTIME=0` or `allow_unsigned=true`.
