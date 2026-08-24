"""Pinned runtimes and native build targets for the desktop app."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

PY_VERSION = "3.12.13"
PY_XY = "3.12"
PBS_RELEASE = "20260728"
PBS_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "{release}/cpython-{version}%2B{release}-{triple}-install_only.tar.gz"
)

BASE_DEPS = (
    "fastapi>=0.116,<1",
    "httpx>=0.28,<1",
    "pydantic>=2.11,<3",
    "uvicorn>=0.35,<1",
    "huggingface_hub>=0.20",
)
MLX_DEPS = ("mlx>=0.30", "numpy>=1.24", "sentencepiece>=0.2", "soundfile>=0.12")
TFLITE_DEPS = (
    "ai_edge_litert>=1.0",
    "numpy>=1.24",
    "sentencepiece>=0.2",
    "soundfile>=0.12",
)


@dataclass(frozen=True)
class Target:
    key: str
    pbs_triple: str
    python_rel: str
    site_packages_rel: str
    backend: str
    eb_platform: str
    eb_arch: str

    @property
    def dependencies(self) -> tuple[str, ...]:
        return BASE_DEPS + (MLX_DEPS if self.backend == "mlx" else TFLITE_DEPS)


TARGETS = {
    "mac-arm64": Target(
        "mac-arm64",
        "aarch64-apple-darwin",
        "bin/python3",
        f"lib/python{PY_XY}/site-packages",
        "mlx",
        "--mac",
        "--arm64",
    ),
    "win-x64": Target(
        "win-x64",
        "x86_64-pc-windows-msvc",
        "python.exe",
        "Lib/site-packages",
        "tflite",
        "--win",
        "--x64",
    ),
}


def host_target() -> str:
    if sys.platform == "darwin":
        return "mac-arm64" if platform.machine() == "arm64" else ""
    if sys.platform.startswith("win"):
        return "win-x64"
    return ""
