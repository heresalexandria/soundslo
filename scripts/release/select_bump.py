#!/usr/bin/env python3
"""Select exactly one release bump label from GitHub's label JSON."""

from __future__ import annotations

import json
import os

RELEASE = ("major", "minor", "patch")


def main() -> int:
    try:
        labels = json.loads(os.environ.get("LABELS", "[]"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid LABELS JSON: {error}") from error
    names = {item if isinstance(item, str) else item.get("name") for item in labels}
    matches = [label for label in RELEASE if label in names]
    if "no-release" in names:
        if matches:
            raise SystemExit("no-release cannot be combined with a release bump label")
        result = "none"
    elif len(matches) == 1:
        result = matches[0]
    else:
        raise SystemExit("label the PR with exactly one of major, minor, patch, or no-release")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
