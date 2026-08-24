import json
from pathlib import Path

from scripts.package.build import package_environment
from scripts.package.targets import TARGETS
from scripts.release.bump_version import check
from soundslo import __version__
from soundslo.config import SA3_REVISION, SA3_WEIGHTS_REVISION

ROOT = Path(__file__).parents[1]


def test_release_contains_required_license_and_notice_files() -> None:
    required = (
        ROOT / "LICENSE",
        ROOT / "NOTICE",
        ROOT / "docs" / "assets" / "soundslo-app.jpg",
        ROOT / "licenses" / "STABILITY_AI_COMMUNITY_LICENSE.md",
        ROOT / "licenses" / "GEMMA_TERMS_OF_USE.md",
        ROOT / "soundslo" / "static" / "apple-touch-icon.png",
        ROOT / "soundslo" / "static" / "favicon-32.png",
        ROOT / "soundslo" / "static" / "favicon.svg",
        ROOT / "soundslo" / "static" / "soundslo-icon.svg",
        ROOT / "scripts" / "install_model.sh",
        ROOT / "scripts" / "run_with_large.sh",
        ROOT / "app" / "main.js",
        ROOT / "app" / "preload.js",
        ROOT / "app" / "updater.js",
        ROOT / "app" / "package.json",
        ROOT / "app" / "package-lock.json",
        ROOT / "site" / "index.html",
        ROOT / "site" / "styles.css",
        ROOT / ".github" / "workflows" / "release.yml",
        ROOT / ".github" / "workflows" / "pages.yml",
    )
    assert all(path.is_file() and path.stat().st_size > 0 for path in required)

    notice = (ROOT / "NOTICE").read_text()
    assert "This Stability AI Model is licensed under" in notice
    assert "Gemma is provided under and subject to" in notice


def test_third_party_revisions_and_ui_attribution_are_pinned() -> None:
    assert len(SA3_REVISION) == 40
    assert len(SA3_WEIGHTS_REVISION) == 40
    index = (ROOT / "soundslo" / "static" / "index.html").read_text()
    assert "Powered by Stability AI" in index
    assert 'href="/favicon.ico"' in index
    assert 'href="/static/favicon.svg"' in index
    assert 'href="/static/apple-touch-icon.png"' in index


def test_readme_starts_with_branding_and_has_a_one_command_setup() -> None:
    readme = (ROOT / "README.md").read_text()
    assert readme.startswith('<div align="center">')
    assert 'src="soundslo/static/soundslo-icon.svg"' in readme
    assert "<p><em>Generate private," in readme
    assert 'src="docs/assets/soundslo-app.jpg"' in readme
    assert "Download for macOS or Windows" in readme
    assert "bash scripts/setup.sh && bash scripts/run.sh" in readme
    assert "Stable Audio 3 Large has no public local weights" in readme
    assert "bash scripts/install_model.sh small-music" in readme


def test_native_release_targets_match_supported_downloads() -> None:
    assert tuple(TARGETS) == ("mac-arm64", "win-x64")
    assert TARGETS["mac-arm64"].site_packages_rel == "lib/python3.12/site-packages"
    assert TARGETS["win-x64"].site_packages_rel == "Lib/site-packages"

    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    download_page = (ROOT / "site" / "index.html").read_text()
    assert "mac-x64" not in release_workflow
    assert "mac-x64" not in download_page
    assert "Soundslo-mac-arm64.dmg" in download_page
    assert "Soundslo-win-x64-setup.exe" in download_page


def test_every_release_version_source_agrees() -> None:
    assert check() == __version__


def test_macos_release_requires_signing_while_local_and_windows_builds_do_not() -> None:
    unsigned = package_environment("mac-arm64", notarize=False, source={})
    assert unsigned["CSC_IDENTITY_AUTO_DISCOVERY"] == "false"
    assert "SOUNDSLO_ELECTRON_SIGN" not in unsigned

    local_notarized = package_environment("mac-arm64", notarize=True, source={})
    assert local_notarized["SOUNDSLO_ELECTRON_SIGN"] == "true"
    assert local_notarized["APPLE_KEYCHAIN_PROFILE"] == "clawnsole-notarization"
    assert "CSC_IDENTITY_AUTO_DISCOVERY" not in local_notarized

    signed = package_environment(
        "mac-arm64",
        notarize=True,
        source={"CSC_LINK": "base64-certificate", "APPLE_ID": "developer@example.com"},
    )
    assert signed["SOUNDSLO_ELECTRON_SIGN"] == "true"
    assert signed["CSC_LINK"] == "base64-certificate"
    assert "APPLE_KEYCHAIN_PROFILE" not in signed

    windows = package_environment(
        "win-x64", notarize=False, source={"CSC_LINK": "mac-certificate"}
    )
    assert windows["CSC_IDENTITY_AUTO_DISCOVERY"] == "false"
    assert "CSC_LINK" not in windows

    package = json.loads((ROOT / "app" / "package.json").read_text())
    assert package["build"]["mac"]["hardenedRuntime"] is True
    assert package["build"]["mac"]["signIgnore"] == [r"\.py[co]$"]
    assert "identity" not in package["build"]["mac"]
