"""Build a relocatable Python runtime containing Soundslo and one SA3 backend."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .common import CACHE_DIR, REPO_ROOT, RUNTIME_CACHE, download, extract, human, log, rmtree, run
from .targets import PBS_RELEASE, PBS_URL, PY_VERSION, Target, host_target

RECIPE = 2


def project_wheel(builder: Path) -> Path:
    directory = CACHE_DIR / "wheels"
    rmtree(directory)
    directory.mkdir(parents=True)
    run([
        builder,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--no-cache-dir",
        "--wheel-dir",
        directory,
        REPO_ROOT,
    ])
    wheels = list(directory.glob("soundslo-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Soundslo wheel build did not produce exactly one wheel")
    return wheels[0]


def build(target: Target, *, force: bool = False) -> Path:
    if target.key != host_target():
        raise SystemExit(
            f"{target.key} must be built on its native runner (host is {host_target()})"
        )
    root = RUNTIME_CACHE / target.key
    stamp = root / ".soundslo-runtime.json"
    wanted = {
        "recipe": RECIPE,
        "python": PY_VERSION,
        "pbs": PBS_RELEASE,
        "dependencies": list(target.dependencies),
    }
    cached = False
    if not force and stamp.is_file():
        try:
            cached = json.loads(stamp.read_text()) == wanted
        except (OSError, json.JSONDecodeError):
            cached = False

    python = root / target.python_rel
    if not cached:
        archive = download(
            PBS_URL.format(
                release=PBS_RELEASE, version=PY_VERSION, triple=target.pbs_triple
            ),
            f"cpython-{PY_VERSION}+{PBS_RELEASE}-{target.pbs_triple}.tar.gz",
        )
        unpacked = RUNTIME_CACHE / f".{target.key}.unpacked"
        extract(archive, unpacked)
        inner = unpacked / "python"
        if not inner.is_dir():
            raise SystemExit(f"unexpected Python archive layout in {archive}")
        rmtree(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        inner.rename(root)
        rmtree(unpacked)
        run([python, "-m", "pip", "install", "--upgrade", "pip"])
        run([python, "-m", "pip", "install", "--no-cache-dir", *target.dependencies])
    else:
        runtime_size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        log(f"cached Python runtime {target.key} ({human(runtime_size)})")

    wheel = project_wheel(python)
    run([
        python,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--no-deps",
        "--force-reinstall",
        wheel,
    ])
    site_packages = root / target.site_packages_rel
    if not site_packages.is_dir():
        raise SystemExit(f"bundled runtime has no site-packages at {site_packages}")
    run([
        python,
        "-m",
        "compileall",
        "-q",
        "--invalidation-mode",
        "unchecked-hash",
        site_packages,
    ])
    stamp.write_text(json.dumps(wanted, indent=2))
    return root


def verify(target: Target, root: Path) -> None:
    python = root / target.python_rel
    backend_import = "import mlx" if target.backend == "mlx" else "import ai_edge_litert"
    code = (
        "import soundslo,fastapi,huggingface_hub;"
        f"{backend_import};"
        "print(soundslo.__version__)"
    )
    completed = subprocess.run(
        [str(python), "-c", code],
        cwd=tempfile.gettempdir(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode:
        raise SystemExit(f"bundled runtime import failed:\n{completed.stderr[-3000:]}")
    log(f"runtime verified: Soundslo {completed.stdout.strip()} / {target.backend}")
