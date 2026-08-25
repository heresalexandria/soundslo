#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
dist="${1:-$repo_root/app/dist}"
version="${EXPECTED_VERSION:-$(node -p "require('$repo_root/app/package.json').version")}"
expected_team_id="${EXPECTED_TEAM_ID:-KMZ785G889}"
expected_authority="Developer ID Application: Alex Redmon ($expected_team_id)"
dmg="$dist/Soundslo-$version-mac-arm64.dmg"
zip="$dist/Soundslo-$version-mac-arm64.zip"

for artifact in "$dmg" "$zip"; do
  if [[ ! -s "$artifact" ]]; then
    echo "::error::Missing macOS release artifact: $artifact"
    exit 1
  fi
done

verify_app() {
  local app="$1"
  local source="$2"
  local signature
  local actual_version

  if [[ ! -d "$app" ]]; then
    echo "::error::$source does not contain Soundslo.app"
    exit 1
  fi

  actual_version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist")"
  if [[ "$actual_version" != "$version" ]]; then
    echo "::error::$source contains version $actual_version; expected $version"
    exit 1
  fi

  codesign --verify --deep --strict --verbose=4 "$app"
  signature="$(codesign -dvvv "$app" 2>&1)"
  printf '%s\n' "$signature"
  grep -F "Authority=$expected_authority" <<< "$signature"
  grep -F "TeamIdentifier=$expected_team_id" <<< "$signature"
  spctl --assess --type execute --verbose=4 "$app"
  xcrun stapler validate "$app"
}

verify_root="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/soundslo-macos-verify.XXXXXX")"
mount_point="$verify_root/dmg"
mounted=false

cleanup() {
  if [[ "$mounted" == true ]]; then
    hdiutil detach "$mount_point" >/dev/null || true
  fi
  rm -rf "$verify_root"
}
trap cleanup EXIT

hdiutil verify "$dmg"
mkdir "$mount_point"
hdiutil attach -readonly -nobrowse -mountpoint "$mount_point" "$dmg" >/dev/null
mounted=true
verify_app "$mount_point/Soundslo.app" "DMG"

fresh_app="$verify_root/fresh/Soundslo.app"
mkdir -p "$(dirname "$fresh_app")"
ditto "$mount_point/Soundslo.app" "$fresh_app"
xattr -w com.apple.quarantine \
  '0083;68ac0000;Google Chrome;00000000-0000-0000-0000-000000000001' \
  "$fresh_app"
verify_app "$fresh_app" "Chrome-quarantined fresh install"

hdiutil detach "$mount_point" >/dev/null
mounted=false

mkdir "$verify_root/zip"
ditto -x -k "$zip" "$verify_root/zip"
verify_app "$verify_root/zip/Soundslo.app" "updater ZIP"

echo "Verified the signed, notarized, stapled DMG, quarantined install, and updater ZIP."
