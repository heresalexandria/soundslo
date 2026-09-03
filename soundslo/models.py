from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from soundslo.config import SA3_WEIGHTS_REVISION, Settings
from soundslo.foley_models import (
    CLIP_FILES,
    CLIP_REPO,
    CLIP_REVISION,
    FOLEY_DOWNLOAD_BYTES,
    FOLEY_REQUIRED_FREE_BYTES,
    FOLEY_RUNTIME_REVISION,
    FOLEY_WEIGHTS_REVISION,
    installed_weight_files,
)

SMALL_MUSIC_ID = "stable-audio-3-small-music"
MEDIUM_ID = "stable-audio-3-medium"
LARGE_API_ID = "stable-audio-3-large-api"
FOLEY_ID = "foley-omni-v2st"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    short_name: str
    deployment: Literal["local", "cloud"]
    description: str
    tradeoff: str
    parameter_label: str
    max_duration_seconds: int
    min_duration_seconds: int
    default_steps: int
    max_steps: int
    supports_negative_prompt: bool
    family: Literal["sa3", "foley-omni"] = "sa3"
    default_cfg_scale: float = 3.0
    default_negative_prompt: str = (
        "vocals, singing, speech, spoken word, lyrics, choir"
    )
    sample_rate: int = 44_100
    accepts_video: bool = False
    min_ram_gb: int = 0
    platforms: tuple[str, ...] = ("mac-arm64", "win-x64")
    weight_files: tuple[str, ...] = ()
    download_bytes: int | None = None
    tflite_weight_files: tuple[str, ...] = ()
    tflite_download_bytes: int | None = None
    dit: str | None = None
    decoder: str | None = None
    api_model: str | None = None
    credits_per_generation: int | None = None
    official_url: str = "https://github.com/Stability-AI/stable-audio-3"

    @property
    def revision(self) -> str:
        if self.family == "foley-omni":
            return FOLEY_WEIGHTS_REVISION
        return SA3_WEIGHTS_REVISION if self.deployment == "local" else "api-managed"


MODEL_SPECS = {
    SMALL_MUSIC_ID: ModelSpec(
        id=SMALL_MUSIC_ID,
        name="Stable Audio 3 Small Music",
        short_name="Small Music",
        deployment="local",
        description="Fast, lightweight music generation for lower-memory computers.",
        tradeoff=(
            "Uses much less disk and memory than Medium, but tops out at two minutes "
            "and has lower musical coherence."
        ),
        parameter_label="433M",
        max_duration_seconds=120,
        min_duration_seconds=1,
        default_steps=8,
        max_steps=32,
        supports_negative_prompt=True,
        weight_files=(
            "models/mlx/t5gemma_f16.npz",
            "models/mlx/dit_sm-music_f16.npz",
            "models/mlx/same_s_decoder_f32.npz",
        ),
        download_bytes=1_704_727_702,
        tflite_weight_files=(
            "models/tflite/t5gemma/encoder_fp16.tflite",
            "models/tflite/sa3-sm-music/dit_w16a32.tflite",
            "models/tflite/same-s/dec_w16a32.tflite",
        ),
        tflite_download_bytes=1_597_003_984,
        dit="sm-music",
        decoder="same-s",
        official_url="https://huggingface.co/stabilityai/stable-audio-3-small",
    ),
    MEDIUM_ID: ModelSpec(
        id=MEDIUM_ID,
        name="Stable Audio 3 Medium",
        short_name="Medium",
        deployment="local",
        description=(
            "The highest-quality Stable Audio 3 model with publicly downloadable local weights."
        ),
        tradeoff=(
            "Better structure, melodic coherence, and phrasing than Small, with a larger "
            "memory and storage footprint."
        ),
        parameter_label="1.4B",
        max_duration_seconds=380,
        min_duration_seconds=1,
        default_steps=8,
        max_steps=32,
        supports_negative_prompt=True,
        weight_files=(
            "models/mlx/t5gemma_f16.npz",
            "models/mlx/dit_medium_f16.npz",
            "models/mlx/same_l_decoder_f32.npz",
        ),
        download_bytes=5_179_055_990,
        tflite_weight_files=(
            "models/tflite/t5gemma/encoder_fp16.tflite",
            "models/tflite/sa3-m/dit_w16a32.tflite",
            "models/tflite/same-l/dec_w16a32.tflite",
        ),
        tflite_download_bytes=4_449_143_136,
        dit="medium",
        decoder="same-l",
        official_url="https://huggingface.co/stabilityai/stable-audio-3-medium",
    ),
    LARGE_API_ID: ModelSpec(
        id=LARGE_API_ID,
        name="Stable Audio 3 Large",
        short_name="Large API",
        deployment="cloud",
        description=(
            "Stability AI's highest-musicality Stable Audio 3 model, available through "
            "its hosted API."
        ),
        tradeoff=(
            "No public local weights: prompts leave this computer, internet and an API key are "
            "required, and each successful generation costs credits."
        ),
        parameter_label="2.7B",
        max_duration_seconds=380,
        min_duration_seconds=1,
        default_steps=8,
        max_steps=8,
        supports_negative_prompt=False,
        api_model="stable-audio-3",
        credits_per_generation=26,
        official_url="https://platform.stability.ai/docs/api-reference#tag/Stable-Audio-3.0",
    ),
    FOLEY_ID: ModelSpec(
        id=FOLEY_ID,
        name="Foley-Omni",
        short_name="Foley-Omni",
        deployment="local",
        family="foley-omni",
        description=(
            "Sound effects from text, or a synchronized soundtrack for a video clip "
            "up to 10 seconds."
        ),
        tradeoff=(
            "16 kHz mono, clips up to 10 s, about 2.5 minutes per clip on an M1 Max "
            "and roughly 30 GB of weights."
        ),
        parameter_label="5.5B",
        max_duration_seconds=10,
        min_duration_seconds=1,
        default_steps=50,
        max_steps=100,
        supports_negative_prompt=True,
        default_cfg_scale=5.0,
        default_negative_prompt="robotic, muffled, echo, distorted",
        sample_rate=16_000,
        accepts_video=True,
        min_ram_gb=32,
        platforms=("mac-arm64",),
        weight_files=installed_weight_files(),
        download_bytes=FOLEY_DOWNLOAD_BYTES,
        official_url="https://github.com/NJU-Speech/Foley-Omni",
    ),
}


def get_model(model_id: str) -> ModelSpec:
    try:
        return MODEL_SPECS[model_id]
    except KeyError as error:
        raise ValueError(f"Unknown model: {model_id}") from error


def model_is_installed(settings: Settings, spec: ModelSpec) -> bool:
    files = weight_files_for(settings, spec)
    if spec.family == "foley-omni":
        return bool(files) and all(
            (settings.foley_ckpts / relative_path).is_file() for relative_path in files
        ) and all(_clip_cache_path(path).is_file() for path, _ in CLIP_FILES)
    return bool(files) and all(
        (settings.backend_root / relative_path).is_file() for relative_path in files
    )


def model_is_ready(settings: Settings, spec: ModelSpec) -> bool:
    if spec.deployment == "cloud":
        return bool(settings.stability_api_key)
    if spec.family == "foley-omni":
        return (
            settings.foley_supported
            and settings.foley_runtime_installed
            and model_is_installed(settings, spec)
        )
    return settings.runtime_installed and model_is_installed(settings, spec)


def model_catalog(settings: Settings) -> list[dict]:
    catalog: list[dict] = []
    for spec in MODEL_SPECS.values():
        runtime_installed = (
            settings.foley_runtime_installed
            if spec.family == "foley-omni"
            else settings.runtime_installed
        )
        installed = model_is_installed(settings, spec) if spec.deployment == "local" else False
        supported, unsupported_reason = _support_status(settings, spec)
        details = asdict(spec)
        details["weight_files"] = weight_files_for(settings, spec)
        details["download_bytes"] = download_bytes_for(settings, spec)
        details.pop("tflite_weight_files", None)
        details.pop("tflite_download_bytes", None)
        details.update(
            {
                "installed": installed,
                "installed_bytes": _installed_bytes(settings, spec),
                "ready": model_is_ready(settings, spec),
                "runtime_installed": runtime_installed,
                "runtime_backend": settings.runtime_backend,
                "installable": spec.deployment == "local" and supported,
                "supported": supported,
                "unsupported_reason": unsupported_reason,
                "configured": (
                    installed if spec.deployment == "local" else bool(settings.stability_api_key)
                ),
                "revision": spec.revision,
                "install_command": (
                    "bash scripts/install_foley.sh"
                    if spec.family == "foley-omni"
                    else (
                        f"bash scripts/install_model.sh {spec.dit}"
                        if spec.deployment == "local"
                        else None
                    )
                ),
                "credential_note": (
                    "Public weights; no login is required. For non-commercial research and "
                    "personal experimentation only under the Apple and MMAudio model terms."
                    if spec.family == "foley-omni"
                    else (
                        "Hugging Face may require a free account, license acceptance, and "
                        "hf auth login."
                        if spec.deployment == "local"
                        else (
                            "Set STABILITY_API_KEY before starting Soundslo. The key is never "
                            "returned to the browser."
                        )
                    )
                ),
                "runtime_revision": (
                    FOLEY_RUNTIME_REVISION if spec.family == "foley-omni" else None
                ),
                "clip_repository": CLIP_REPO if spec.family == "foley-omni" else None,
                "clip_revision": CLIP_REVISION if spec.family == "foley-omni" else None,
            }
        )
        catalog.append(details)
    return catalog


def _platform_key() -> str:
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "mac-arm64"
    if platform.system() == "Windows" and platform.machine().lower() in {"amd64", "x86_64"}:
        return "win-x64"
    return f"{platform.system().lower()}-{platform.machine().lower()}"


def system_ram_gb() -> float | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (AttributeError, OSError, ValueError):
        if sys.platform == "darwin":
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True,
                    check=True,
                    text=True,
                    timeout=5,
                )
                return int(result.stdout.strip()) / 1024**3
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        return None


def _support_status(settings: Settings, spec: ModelSpec) -> tuple[bool, str | None]:
    if spec.family == "foley-omni" and not settings.foley_supported:
        return False, "Foley-Omni currently requires an Apple-silicon Mac."
    if spec.deployment == "local" and _platform_key() not in spec.platforms:
        return False, f"This model does not support {_platform_key()}."
    ram = system_ram_gb()
    if ram is not None and ram < spec.min_ram_gb:
        return False, f"This model needs at least {spec.min_ram_gb} GB of memory."
    return True, None


def _clip_cache_path(filename: str) -> Path:
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    repo_cache = f"models--{CLIP_REPO.replace('/', '--')}"
    return hf_home / "hub" / repo_cache / "snapshots" / CLIP_REVISION / filename


def _model_root(settings: Settings, spec: ModelSpec) -> Path:
    return settings.foley_ckpts if spec.family == "foley-omni" else settings.backend_root


def _installed_bytes(settings: Settings, spec: ModelSpec) -> int:
    total = 0
    for relative_path in weight_files_for(settings, spec):
        path = _model_root(settings, spec) / relative_path
        try:
            total += path.stat().st_size
        except OSError:
            continue
    if spec.family == "foley-omni":
        for filename, _ in CLIP_FILES:
            try:
                total += _clip_cache_path(filename).stat().st_size
            except OSError:
                continue
    return total


def weight_files_for(settings: Settings, spec: ModelSpec) -> tuple[str, ...]:
    if spec.family == "foley-omni":
        return spec.weight_files
    if settings.runtime_backend == "tflite":
        return spec.tflite_weight_files
    return spec.weight_files


def download_bytes_for(settings: Settings, spec: ModelSpec) -> int | None:
    if spec.family == "foley-omni":
        return spec.download_bytes
    if settings.runtime_backend == "tflite":
        return spec.tflite_download_bytes
    return spec.download_bytes


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ModelInstaller:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._statuses: dict[str, dict] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def stop(self) -> None:
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()

    def status(self, model_id: str) -> dict:
        with self._lock:
            status = self._statuses.get(model_id)
            if status:
                return dict(status)
        spec = get_model(model_id)
        if model_is_ready(self.settings, spec):
            return self._status(model_id, "complete", 100, "Ready")
        return self._status(model_id, "idle", 0, "Not installed")

    def start(self, model_id: str) -> dict:
        spec = get_model(model_id)
        if spec.deployment != "local":
            raise ValueError(
                "Stable Audio 3 Large is API-only and has no public Hugging Face weights "
                "to install."
            )
        supported, reason = _support_status(self.settings, spec)
        if not supported:
            raise RuntimeError(reason or "This model is not supported on this computer.")
        if spec.family == "foley-omni":
            disk_root = (
                self.settings.foley_root
                if self.settings.foley_root and self.settings.foley_root.exists()
                else self.settings.root
            )
            free = shutil.disk_usage(disk_root).free
            if free < FOLEY_REQUIRED_FREE_BYTES:
                raise RuntimeError(
                    "Foley-Omni needs at least 36 GB free before installation; "
                    f"only {free / 1_000_000_000:.1f} GB is available."
                )
        elif not self.settings.runtime_installed:
            raise RuntimeError("The local model runtime is missing. Run setup again.")
        with self._lock:
            current = self._statuses.get(model_id)
            if current and current["state"] == "installing":
                return dict(current)
            if model_is_ready(self.settings, spec):
                current = self._status(model_id, "complete", 100, "Ready")
                self._statuses[model_id] = current
                return dict(current)
            status = self._status(model_id, "installing", 2, "Preparing download")
            status["started_at"] = _utc_now()
            self._statuses[model_id] = status
        thread = threading.Thread(
            target=self._install,
            args=(spec,),
            name=f"soundslo-install-{spec.dit}",
            daemon=True,
        )
        thread.start()
        return dict(status)

    def _install(self, spec: ModelSpec) -> None:
        if spec.family == "foley-omni":
            self._install_foley(spec)
            return
        command = [
            str(self.settings.runtime_python),
            str(Path(__file__).with_name("model_download.py")),
            str(self.settings.backend_root),
            "--revision",
            SA3_WEIGHTS_REVISION,
            "--model",
            str(spec.dit),
            "--backend",
            self.settings.runtime_backend,
            "--precision",
            self.settings.tflite_precision,
        ]
        output: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                cwd=self.settings.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._processes[spec.id] = process
            assert process.stdout is not None
            ready_count = 0
            total = max(len(weight_files_for(self.settings, spec)), 1)
            for line in process.stdout:
                clean = line.strip()
                if not clean:
                    continue
                output.append(clean)
                if clean.startswith("fetching:"):
                    self._update(
                        spec.id,
                        progress=8 + (ready_count / total) * 82,
                        stage=f"Downloading {clean.removeprefix('fetching:').strip()}",
                    )
                elif clean.startswith("ready:"):
                    ready_count += 1
                    self._update(
                        spec.id,
                        progress=8 + (ready_count / total) * 88,
                        stage=f"Installed {ready_count} of {total} files",
                    )
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(
                    output[-1] if output else f"Installer exited with {return_code}."
                )
            if not model_is_installed(self.settings, spec):
                raise RuntimeError(
                    "Download finished but one or more model files are still missing."
                )
            self._update(
                spec.id,
                state="complete",
                progress=100,
                stage="Ready",
                error=None,
                finished_at=_utc_now(),
            )
        except Exception as error:
            self._update(
                spec.id,
                state="failed",
                stage="Installation failed",
                error=str(error),
                finished_at=_utc_now(),
            )
        finally:
            with self._lock:
                self._processes.pop(spec.id, None)

    def _install_foley(self, spec: ModelSpec) -> None:
        output: list[str] = []
        try:
            assert self.settings.foley_root is not None
            runtime_source = self.settings.foley_root / "inference_v2st.py"
            process_env = self._foley_env()
            if not runtime_source.is_file():
                setup_script = self.settings.root / "scripts" / "setup_foley.sh"
                if not setup_script.is_file():
                    raise RuntimeError(
                        "The packaged Foley-Omni source is missing and no developer setup "
                        f"script was found at {setup_script}."
                    )
                setup_command = ["bash", str(setup_script)]
                self._run_foley_process(
                    spec,
                    setup_command,
                    output,
                    env=process_env,
                )
            elif not self.settings.foley_python.is_file():
                self._create_packaged_foley_venv(spec, output, process_env)

            if not self.settings.foley_runtime_installed:
                raise RuntimeError("Foley-Omni runtime setup finished but is still incomplete.")

            command = [
                str(self.settings.foley_python),
                "-m",
                "soundslo.foley_download",
                str(self.settings.foley_root),
                "--revision",
                FOLEY_WEIGHTS_REVISION,
                "--clip-revision",
                CLIP_REVISION,
            ]
            self._run_foley_process(spec, command, output, env=process_env)
            if not model_is_installed(self.settings, spec):
                raise RuntimeError(
                    "Download finished but one or more Foley-Omni model files are missing."
                )
            self._update(
                spec.id,
                state="complete",
                progress=100,
                stage="Ready",
                error=None,
                finished_at=_utc_now(),
            )
        except Exception as error:
            self._update(
                spec.id,
                state="failed",
                stage="Installation failed",
                error=str(error),
                finished_at=_utc_now(),
            )
        finally:
            with self._lock:
                self._processes.pop(spec.id, None)

    def _create_packaged_foley_venv(
        self,
        spec: ModelSpec,
        output: list[str],
        env: dict[str, str],
    ) -> None:
        assert self.settings.foley_root is not None
        venv_dir = self.settings.foley_root / ".venv"
        self._update(spec.id, progress=5, stage="Runtime: creating .venv")
        self._run_foley_process(
            spec,
            [str(self.settings.runtime_python), "-m", "venv", str(venv_dir)],
            output,
            env=env,
        )
        if not self.settings.foley_python.is_file():
            raise RuntimeError(
                f"Could not create the Foley-Omni Python at {self.settings.foley_python}"
            )
        requirements = self.settings.root / "requirements-foley.lock"
        if not requirements.is_file():
            requirements = self.settings.foley_root / "requirements-foley.lock"
        if not requirements.is_file():
            raise RuntimeError("The packaged Foley-Omni requirements lockfile is missing.")
        self._update(spec.id, progress=8, stage="Runtime: installing torch runtime (1.3 GB)")
        self._run_foley_process(
            spec,
            [
                str(self.settings.foley_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(requirements),
            ],
            output,
            env=env,
        )
        self._update(spec.id, progress=15, stage="Runtime: ready")

    def _foley_env(self) -> dict[str, str]:
        package_parent = str(Path(__file__).resolve().parents[1])
        existing_pythonpath = os.environ.get("PYTHONPATH")
        pythonpath = (
            os.pathsep.join((package_parent, existing_pythonpath))
            if existing_pythonpath
            else package_parent
        )
        return {
            **os.environ,
            "PYTHONPATH": pythonpath,
            "SOUNDSLO_FOLEY_ROOT": str(self.settings.foley_root),
        }

    def _run_foley_process(
        self,
        spec: ModelSpec,
        command: list[str],
        output: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        process = subprocess.Popen(
            command,
            cwd=self.settings.root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        with self._lock:
            self._processes[spec.id] = process
        assert process.stdout is not None
        ready_count = 0
        total = 11
        for line in process.stdout:
            clean = line.strip()
            if not clean:
                continue
            output.append(clean)
            if clean.startswith("runtime:"):
                runtime_stage = clean.removeprefix("runtime:").strip()
                progress = 15 if runtime_stage == "ready" else 5
                self._update(spec.id, progress=progress, stage=f"Runtime: {runtime_stage}")
            elif clean.startswith("fetching:"):
                name = clean.removeprefix("fetching:").strip()
                self._update(
                    spec.id,
                    progress=15 + (ready_count / total) * 75,
                    stage=f"Downloading {name}",
                )
            elif clean.startswith("ready:"):
                ready_count += 1
                self._update(
                    spec.id,
                    progress=15 + (ready_count / total) * 75,
                    stage=f"Installed {ready_count} of {total} files",
                )
            elif clean.startswith("converting:"):
                self._update(spec.id, progress=92, stage="Converting the model to bf16")
            elif clean.startswith("converted:"):
                self._update(spec.id, progress=97, stage="Converted model to bf16")
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(output[-1] if output else f"Installer exited with {return_code}.")

    def _update(self, model_id: str, **values: object) -> None:
        with self._lock:
            self._statuses[model_id].update(values)

    @staticmethod
    def _status(model_id: str, state: str, progress: float, stage: str) -> dict:
        return {
            "model": model_id,
            "state": state,
            "progress": progress,
            "stage": stage,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }
