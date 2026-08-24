"""Stage the pinned official Stable Audio runtime without any model weights."""

from __future__ import annotations

import shutil
from pathlib import Path

from soundslo.config import SA3_REVISION

from .common import SA3_CACHE, download, extract, log, rmtree
from .targets import Target


def fetch(target: Target, *, force: bool = False) -> Path:
    destination = SA3_CACHE / target.key
    entrypoint = destination / "optimized" / target.backend / "scripts" / (
        "sa3_mlx.py" if target.backend == "mlx" else "sa3_tflite.py"
    )
    if not force and entrypoint.is_file():
        log(f"cached Stable Audio runtime {SA3_REVISION[:12]} / {target.backend}")
        return destination

    archive = download(
        f"https://github.com/Stability-AI/stable-audio-3/archive/{SA3_REVISION}.tar.gz",
        f"stable-audio-3-{SA3_REVISION}.tar.gz",
    )
    unpacked = SA3_CACHE / ".source"
    extract(archive, unpacked)
    roots = [item for item in unpacked.iterdir() if item.is_dir()]
    if len(roots) != 1:
        raise SystemExit("unexpected Stable Audio source archive layout")
    source = roots[0]
    rmtree(destination)
    backend_destination = destination / "optimized" / target.backend
    backend_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / "optimized" / target.backend, backend_destination)
    shutil.copy2(source / "LICENSE", destination / "LICENSE")
    (destination / "REVISION").write_text(f"{SA3_REVISION}\n")
    for unwanted in backend_destination.rglob(".venv"):
        rmtree(unwanted)
    rmtree(unpacked)
    if not entrypoint.is_file():
        raise SystemExit(f"Stable Audio entrypoint missing after staging: {entrypoint}")
    return destination
