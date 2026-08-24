#!/usr/bin/env python3
"""Build a self-contained Soundslo desktop installer for one native target."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "scripts.package"

from . import build_runtime, fetch_sa3  # noqa: E402
from .common import (  # noqa: E402
    APP_DIR,
    CACHE_DIR,
    REPO_ROOT,
    STAGE_DIR,
    human,
    log,
    mirror,
    npm,
    rmtree,
    run,
    size_of,
)
from .targets import TARGETS  # noqa: E402


def stage(runtime: Path, sa3: Path, target_key: str) -> None:
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    mirror(runtime, STAGE_DIR / "pyruntime")
    mirror(sa3, STAGE_DIR / "sa3-runtime")
    legal = STAGE_DIR / "legal"
    rmtree(legal)
    legal.mkdir(parents=True)
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(REPO_ROOT / name, legal / name)
    shutil.copytree(REPO_ROOT / "licenses", legal / "licenses")
    (STAGE_DIR / "STAGED.json").write_text(json.dumps({
        "target": target_key,
        "runtime_bytes": size_of(runtime),
        "sa3_bytes": size_of(sa3),
    }, indent=2))


def ensure_node_modules() -> None:
    executable = APP_DIR / "node_modules" / ".bin" / (
        "electron-builder.cmd" if sys.platform.startswith("win") else "electron-builder"
    )
    if not executable.exists():
        run([npm(), "ci", "--no-audit", "--no-fund"], cwd=APP_DIR)


def package_environment(
    target_key: str, *, notarize: bool, source: dict[str, str] | None = None
) -> dict[str, str]:
    target = TARGETS[target_key]
    environment = dict(os.environ if source is None else source)
    sign_macos = target.eb_platform == "--mac" and (
        notarize
        or environment.get("SOUNDSLO_ELECTRON_SIGN") == "true"
        or bool(environment.get("CSC_LINK"))
    )
    if sign_macos:
        environment["SOUNDSLO_ELECTRON_SIGN"] = "true"
        environment.pop("CSC_IDENTITY_AUTO_DISCOVERY", None)
        apple_credentials = any(
            environment.get(name)
            for name in ("APPLE_ID", "APPLE_API_KEY", "APPLE_KEYCHAIN_PROFILE")
        )
        if notarize and not apple_credentials:
            environment["APPLE_KEYCHAIN_PROFILE"] = environment.get(
                "SOUNDSLO_NOTARY_KEYCHAIN_PROFILE", "clawnsole-notarization"
            )
    else:
        environment["CSC_IDENTITY_AUTO_DISCOVERY"] = "false"
        environment.pop("CSC_LINK", None)
        environment.pop("CSC_KEY_PASSWORD", None)
    return environment


def package(target_key: str, *, directory_only: bool, notarize: bool) -> None:
    target = TARGETS[target_key]
    if notarize and target.eb_platform != "--mac":
        raise SystemExit("--notarize is available only for macOS targets")
    executable = APP_DIR / "node_modules" / ".bin" / (
        "electron-builder.cmd" if sys.platform.startswith("win") else "electron-builder"
    )
    command = [executable, target.eb_platform, target.eb_arch, "--publish", "never"]
    if directory_only:
        command.append("--dir")
    if notarize:
        command.append("--config.mac.notarize=true")
    environment = package_environment(target_key, notarize=notarize)
    run(command, cwd=APP_DIR, env=environment)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--force-runtime", action="store_true")
    parser.add_argument("--force-sa3", action="store_true")
    parser.add_argument("--stage-only", action="store_true")
    parser.add_argument("--dir-only", action="store_true")
    parser.add_argument("--notarize", action="store_true")
    args = parser.parse_args()
    if args.clean:
        for path in (CACHE_DIR, STAGE_DIR, APP_DIR / "dist"):
            rmtree(path)

    target = TARGETS[args.target]
    runtime = build_runtime.build(target, force=args.force_runtime)
    build_runtime.verify(target, runtime)
    sa3 = fetch_sa3.fetch(target, force=args.force_sa3)
    stage(runtime, sa3, args.target)
    log(f"staged Python {human(size_of(runtime))}; SA3 source {human(size_of(sa3))}")
    if not args.stage_only:
        ensure_node_modules()
        package(args.target, directory_only=args.dir_only, notarize=args.notarize)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
