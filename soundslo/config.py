from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
ROOT = PACKAGE_ROOT.parent
SA3_REVISION = "a0b57f5483c4588f827f3552b7d5c6ca2a9687be"
SA3_WEIGHTS_REVISION = "6736003cb57d06b7b1fdc36fad31b2a3709e4774"


@dataclass(frozen=True)
class Settings:
    root: Path
    data_dir: Path
    database_path: Path
    generations_dir: Path
    sa3_root: Path
    static_dir: Path
    stability_api_key: str | None = None
    stability_api_base_url: str = "https://api.stability.ai"
    runtime_backend: str = "mlx"
    runtime_python_path: Path | None = None
    tflite_precision: str = "w16a32"

    @classmethod
    def from_env(cls) -> Settings:
        root = Path(os.environ.get("SOUNDSLO_ROOT", ROOT)).expanduser().resolve()
        data_dir = Path(os.environ.get("SOUNDSLO_DATA_DIR", root / "data")).expanduser().resolve()
        sa3_root = (
            Path(os.environ.get("SOUNDSLO_SA3_ROOT", root / ".runtime" / "stable-audio-3"))
            .expanduser()
            .resolve()
        )
        backend = os.environ.get("SOUNDSLO_BACKEND") or (
            "mlx" if sys.platform == "darwin" and platform.machine() == "arm64" else "tflite"
        )
        if backend not in {"mlx", "tflite"}:
            raise ValueError("SOUNDSLO_BACKEND must be 'mlx' or 'tflite'.")
        runtime_python = os.environ.get("SOUNDSLO_RUNTIME_PYTHON")
        return cls(
            root=root,
            data_dir=data_dir,
            database_path=data_dir / "soundslo.sqlite3",
            generations_dir=data_dir / "generations",
            sa3_root=sa3_root,
            static_dir=Path(os.environ.get("SOUNDSLO_STATIC_DIR", PACKAGE_ROOT / "static"))
            .expanduser()
            .resolve(),
            stability_api_key=os.environ.get("STABILITY_API_KEY") or None,
            stability_api_base_url=os.environ.get(
                "STABILITY_API_BASE_URL", "https://api.stability.ai"
            ).rstrip("/"),
            runtime_backend=backend,
            runtime_python_path=(
                Path(runtime_python).expanduser().resolve() if runtime_python else None
            ),
            tflite_precision=os.environ.get("SOUNDSLO_TFLITE_PRECISION", "w16a32"),
        )

    @property
    def mlx_root(self) -> Path:
        return self.sa3_root / "optimized" / "mlx"

    @property
    def tflite_root(self) -> Path:
        return self.sa3_root / "optimized" / "tflite"

    @property
    def backend_root(self) -> Path:
        return self.mlx_root if self.runtime_backend == "mlx" else self.tflite_root

    @property
    def sa3_executable(self) -> Path:
        if self.runtime_backend == "mlx":
            return self.mlx_root / "scripts" / "sa3_mlx.py"
        return self.tflite_root / "scripts" / "sa3_tflite.py"

    @property
    def runtime_python(self) -> Path:
        if self.runtime_python_path:
            return self.runtime_python_path
        posix = self.backend_root / ".venv" / "bin" / "python"
        windows = self.backend_root / ".venv" / "Scripts" / "python.exe"
        return windows if windows.is_file() else posix

    @property
    def runtime_installed(self) -> bool:
        return self.sa3_executable.is_file() and self.runtime_python.is_file()

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.generations_dir.mkdir(parents=True, exist_ok=True)
