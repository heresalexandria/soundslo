# Release process

Every pull request must have exactly one of `major`, `minor`, `patch`, or `no-release`. The PR check
enforces this before merge.

When a release-labeled pull request merges to `main`, `.github/workflows/release.yml`:

1. increments `pyproject.toml`, `uv.lock`, `soundslo/__init__.py`, `app/package.json`, and the npm lockfile;
2. commits the version bump to `main`;
3. dispatches that exact trusted `main` commit to a separate release run so Electron Builder never
   treats signing as pull-request work;
4. builds Apple-silicon macOS and Windows x64 on native runners;
5. mounts the publishable DMG and extracts the updater ZIP, requiring both contained macOS apps to
   be Developer ID signed by Team ID `KMZ785G889`, notarized, accepted by Gatekeeper, and stapled;
6. copies the app as a Chrome-quarantined fresh install and requires Gatekeeper to accept it;
7. boots every unpacked application with `--smoke` to verify its embedded Python, backend source,
   service, and model catalog;
8. publishes DMGs, macOS update ZIPs, the Windows NSIS installer, stable-name download aliases, and
   `SHA256SUMS.txt`; and
9. moves the `latest` tag to the released commit.

The tag is created only after every native build and smoke test passes. A failed build therefore
does not leave a partial release behind. `build-check.yml` can package any one target manually
without publishing it.

Published macOS builds require these repository Actions secrets:

| Secret | Purpose |
|---|---|
| `MACOS_CERTIFICATE_P12` | Base64 Developer ID Application certificate and private key |
| `MACOS_CERTIFICATE_PASSWORD` | Password protecting that PKCS#12 bundle |
| `APPLE_ID` | Apple account used for notarization |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password used by `notarytool` |
| `APPLE_TEAM_ID` | Apple developer team; must be `KMZ785G889` |

Local signed builds reuse the existing `clawnsole-notarization` keychain profile by default:

```bash
SOUNDSLO_ELECTRON_SIGN=true uv run python scripts/package/build.py --target mac-arm64 --notarize
```

Run the `Create release labels` workflow once when setting up a new fork. Enable GitHub Pages with
GitHub Actions as its source so `pages.yml` can publish the static download page.
