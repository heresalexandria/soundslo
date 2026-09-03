"""Stage the pinned Foley-Omni Apple-silicon runtime without model weights."""

from __future__ import annotations

import shutil
from pathlib import Path

from soundslo.config import FOLEY_RUNTIME_REVISION

from .common import FOLEY_CACHE, download, extract, log, rmtree
from .targets import Target


def fetch(target: Target, *, force: bool = False) -> Path:
    destination = FOLEY_CACHE / target.key
    entrypoint = destination / "inference_v2st.py"
    if target.key != "mac-arm64":
        # electron-builder requires every declared extraResource to exist. Keep
        # the unsupported Windows resource deterministic and effectively empty.
        if force or not destination.is_dir():
            rmtree(destination)
            destination.mkdir(parents=True)
            (destination / "UNSUPPORTED").write_text("Foley-Omni requires macOS arm64.\n")
            (destination / "REVISION").write_text(f"{FOLEY_RUNTIME_REVISION}\n")
        return destination
    if not force and entrypoint.is_file():
        log(f"cached Foley-Omni runtime {FOLEY_RUNTIME_REVISION[:12]} / mac-arm64")
        return destination

    archive = download(
        "https://github.com/heresalexandria/foley-omni-mac/archive/"
        f"{FOLEY_RUNTIME_REVISION}.tar.gz",
        f"foley-omni-mac-{FOLEY_RUNTIME_REVISION}.tar.gz",
    )
    unpacked = FOLEY_CACHE / ".source"
    extract(archive, unpacked)
    roots = [item for item in unpacked.iterdir() if item.is_dir()]
    if len(roots) != 1:
        raise SystemExit("unexpected Foley-Omni source archive layout")
    source = roots[0]
    rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "assets",
            "ckpts",
            "bench_results",
            "__pycache__",
            ".pytest_cache",
        ),
    )
    rmtree(destination / "examples" / "videos")
    (destination / "REVISION").write_text(f"{FOLEY_RUNTIME_REVISION}\n")
    rmtree(unpacked)
    if not entrypoint.is_file():
        raise SystemExit(f"Foley-Omni entrypoint missing after staging: {entrypoint}")
    return destination
