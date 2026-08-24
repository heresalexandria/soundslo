#!/usr/bin/env python3
"""Turn the merged PR body and native artifacts into GitHub release notes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PLATFORMS = (
    ("-mac-arm64.dmg", "macOS, Apple silicon"),
    ("-win-x64-setup.exe", "Windows 10/11, 64-bit"),
)


def size(path: Path) -> str:
    megabytes = path.stat().st_size / 1024 / 1024
    return f"{megabytes / 1024:.2f} GB" if megabytes >= 1024 else f"{megabytes:.0f} MB"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr")
    parser.add_argument("--version", required=True)
    parser.add_argument("--previous", default="")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--files", type=Path, required=True)
    parser.add_argument("--output", "-o", required=True)
    args = parser.parse_args()
    pr = json.loads(Path(args.pr).read_text()) if args.pr and Path(args.pr).is_file() else {}
    body = str(pr.get("body") or pr.get("title") or "Soundslo desktop release.").strip()
    files = [path for path in args.files.iterdir() if path.is_file()]
    rows = []
    for suffix, platform in PLATFORMS:
        artifact = next((path for path in files if path.name.endswith(suffix)), None)
        if not artifact:
            raise SystemExit(f"release is missing {platform}")
        rows.append(f"| {platform} | `{artifact.name}` | {size(artifact)} |")
    notes = [
        body,
        "## Downloads",
        "",
        "| platform | file | size |",
        "|---|---|---|",
        *rows,
        "",
        "Soundslo checks GitHub Releases automatically and verifies downloaded updates against "
        "`SHA256SUMS.txt` before installation. The macOS app is Developer ID signed, notarized, "
        "and stapled. Windows is currently unsigned, so its first browser download may show the "
        "standard SmartScreen warning.",
    ]
    if args.previous:
        notes.extend([
            "",
            f"[Full changelog](https://github.com/{args.repo}/compare/{args.previous}...v{args.version})",
        ])
    Path(args.output).write_text("\n".join(notes).strip() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
