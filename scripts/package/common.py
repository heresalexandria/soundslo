"""Shared paths and deterministic download/staging helpers."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "app"
CACHE_DIR = REPO_ROOT / ".cache" / "package"
DOWNLOAD_DIR = CACHE_DIR / "downloads"
RUNTIME_CACHE = CACHE_DIR / "pyruntime"
SA3_CACHE = CACHE_DIR / "sa3-runtime"
STAGE_DIR = APP_DIR / "build-resources"
_STARTED = time.monotonic()


def log(message: str) -> None:
    print(f"[{time.monotonic() - _STARTED:6.1f}s] {message}", flush=True)


def run(command: list[str | Path], *, cwd: Path | None = None, env: dict | None = None) -> None:
    log("$ " + " ".join(map(str, command)))
    subprocess.run(
        [str(part) for part in command], cwd=cwd, env=env, check=True
    )


def rmtree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) \
        if path.exists() else 0


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def download(url: str, name: str) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = DOWNLOAD_DIR / name
    if destination.is_file() and destination.stat().st_size:
        log(f"cached {name} ({human(destination.stat().st_size)})")
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "soundslo-packager"})
    log(f"fetch {url}")
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    partial.replace(destination)
    log(f"downloaded {name} ({human(destination.stat().st_size)})")
    return destination


def extract(archive: Path, destination: Path) -> None:
    rmtree(destination)
    destination.mkdir(parents=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(destination, filter="data")


def mirror(source: Path, destination: Path) -> None:
    rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)


def npm() -> str:
    return "npm.cmd" if sys.platform.startswith("win") else "npm"
