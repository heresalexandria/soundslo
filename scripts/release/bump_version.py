#!/usr/bin/env python3
"""Check or bump every Soundslo version file."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "soundslo" / "__init__.py"
PACKAGE = ROOT / "app" / "package.json"
LOCK = ROOT / "app" / "package-lock.json"


def current() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit("pyproject.toml has no version")
    return match.group(1)


def parse(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise SystemExit(f"not a semantic version: {version}")
    return tuple(map(int, match.groups()))


def check() -> str:
    version = current()
    package = json.loads(PACKAGE.read_text()).get("version")
    init_match = re.search(r'^__version__\s*=\s*"([^"]+)"', INIT.read_text(), re.MULTILINE)
    init = init_match.group(1) if init_match else None
    lock = json.loads(LOCK.read_text()).get("version")
    if len({version, init, package, lock}) != 1:
        raise SystemExit(
            f"version mismatch: pyproject={version}, __init__={init}, "
            f"package={package}, lock={lock}"
        )
    return version


def replace(path: Path, pattern: str, value: str) -> None:
    contents, count = re.subn(pattern, value, path.read_text(), count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"could not update version in {path}")
    path.write_text(contents)


def write(version: str) -> None:
    replace(PYPROJECT, r'^version\s*=\s*"[^"]+"', f'version = "{version}"')
    replace(INIT, r'^__version__\s*=\s*"[^"]+"', f'__version__ = "{version}"')
    replace(PACKAGE, r'^(\s*)"version":\s*"[^"]+"', rf'\g<1>"version": "{version}"')
    payload = json.loads(LOCK.read_text())
    payload["version"] = version
    payload["packages"][""]["version"] = version
    LOCK.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", nargs="?", choices=("major", "minor", "patch"))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    if args.check or args.show:
        print(check() if args.check else current())
        return 0
    if not args.kind:
        parser.error("choose major, minor, patch, --check, or --show")
    major, minor, patch = parse(check())
    if args.kind == "major":
        version = f"{major + 1}.0.0"
    elif args.kind == "minor":
        version = f"{major}.{minor + 1}.0"
    else:
        version = f"{major}.{minor}.{patch + 1}"
    write(version)
    print(version)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"version={version}\ntag=v{version}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
