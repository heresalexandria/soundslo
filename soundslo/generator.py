from __future__ import annotations

import os
import queue
import re
import select
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx

try:
    import pty
except ImportError:  # pragma: no cover - exercised by packaged Windows smoke tests
    pty = None

from soundslo.config import Settings
from soundslo.database import TERMINAL_STATUSES, Database
from soundslo.models import LARGE_API_ID, MEDIUM_ID, get_model, model_is_ready

ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
STEP_RE = re.compile(r"step\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
MAX_LOG_CHARS = 40_000


class GenerationRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    def is_ready(self, model_id: str = MEDIUM_ID) -> bool:
        return model_is_ready(self.settings, get_model(model_id))

    def command_for(self, generation: dict, output_path: Path) -> list[str]:
        spec = get_model(generation.get("model", MEDIUM_ID))
        if spec.deployment != "local" or not spec.dit or not spec.decoder:
            raise ValueError(f"{spec.name} does not use the local MLX command.")
        command = [
            str(self.settings.runtime_python),
            str(self.settings.sa3_executable),
            "--prompt",
            generation["prompt"],
            "--negative-prompt",
            generation["negative_prompt"],
            "--dit",
            spec.dit,
            "--decoder",
            spec.decoder,
            "--seconds",
            str(generation["duration_seconds"]),
            "--steps",
            str(generation["steps"]),
            "--seed",
            str(generation["seed"]),
            "--cfg",
            str(generation["cfg_scale"]),
            "--apg",
            "1.0",
            "--out",
            str(output_path),
        ]
        if self.settings.runtime_backend == "mlx":
            command[command.index("--seconds"):command.index("--seconds")] = [
                "--dit-dtype",
                "fp16",
            ]
        else:
            command.extend(["--precision", self.settings.tflite_precision])
        return command

    def run(
        self,
        generation: dict,
        output_path: Path,
        on_output: Callable[[str], None],
        on_progress: Callable[[float, str], None],
        on_process: Callable[[subprocess.Popen[bytes] | None], None],
        is_cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, str]:
        model_id = generation.get("model", MEDIUM_ID)
        spec = get_model(model_id)
        if not self.is_ready(model_id):
            if spec.deployment == "cloud":
                return 127, (
                    "Stable Audio 3 Large requires STABILITY_API_KEY. "
                    "Set it before starting Soundslo."
                )
            return 127, f"{spec.name} is not installed. Open Settings or run its install script."
        if model_id == LARGE_API_ID:
            return self._run_stability_api(
                generation,
                output_path,
                on_output,
                on_progress,
                on_process,
                is_cancelled or (lambda: False),
            )
        return self._run_local(generation, output_path, on_output, on_progress, on_process)

    def _run_local(
        self,
        generation: dict,
        output_path: Path,
        on_output: Callable[[str], None],
        on_progress: Callable[[float, str], None],
        on_process: Callable[[subprocess.Popen[bytes] | None], None],
    ) -> tuple[int, str]:

        if pty is None:
            return self._run_local_pipes(
                generation, output_path, on_output, on_progress, on_process
            )

        master_fd, slave_fd = pty.openpty()
        process: subprocess.Popen[bytes] | None = None
        captured: list[str] = []
        pending = ""
        try:
            process = subprocess.Popen(
                self.command_for(generation, output_path),
                cwd=self.settings.backend_root,
                stdin=subprocess.DEVNULL,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            on_process(process)
            os.close(slave_fd)
            slave_fd = -1

            while True:
                readable, _, _ = select.select([master_fd], [], [], 0.25)
                if readable:
                    try:
                        chunk = os.read(master_fd, 8192).decode("utf-8", errors="replace")
                    except OSError:
                        chunk = ""
                    if chunk:
                        clean = ANSI_RE.sub("", chunk).replace("\r", "\n")
                        captured.append(clean)
                        pending += clean
                        lines = pending.split("\n")
                        pending = lines.pop()
                        for line in lines:
                            stripped = line.strip()
                            if stripped:
                                on_output(stripped)
                                progress = progress_from_line(stripped)
                                if progress:
                                    on_progress(*progress)
                if process.poll() is not None:
                    while True:
                        try:
                            tail = os.read(master_fd, 8192)
                        except OSError:
                            break
                        if not tail:
                            break
                        captured.append(ANSI_RE.sub("", tail.decode("utf-8", errors="replace")))
                    break
            if pending.strip():
                on_output(pending.strip())
            return process.returncode or 0, "".join(captured)[-MAX_LOG_CHARS:]
        finally:
            on_process(None)
            if slave_fd >= 0:
                os.close(slave_fd)
            os.close(master_fd)

    def _run_local_pipes(
        self,
        generation: dict,
        output_path: Path,
        on_output: Callable[[str], None],
        on_progress: Callable[[float, str], None],
        on_process: Callable[[subprocess.Popen[bytes] | None], None],
    ) -> tuple[int, str]:
        captured: list[str] = []
        process: subprocess.Popen | None = None
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            process = subprocess.Popen(
                self.command_for(generation, output_path),
                cwd=self.settings.backend_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            on_process(process)
            assert process.stdout is not None
            for line in process.stdout:
                clean = ANSI_RE.sub("", line).strip()
                if not clean:
                    continue
                captured.append(clean)
                on_output(clean)
                progress = progress_from_line(clean)
                if progress:
                    on_progress(*progress)
            return process.wait(), "\n".join(captured)[-MAX_LOG_CHARS:]
        finally:
            on_process(None)

    def _run_stability_api(
        self,
        generation: dict,
        output_path: Path,
        on_output: Callable[[str], None],
        on_progress: Callable[[float, str], None],
        on_process: Callable[[subprocess.Popen[bytes] | None], None],
        is_cancelled: Callable[[], bool],
    ) -> tuple[int, str]:
        key = self.settings.stability_api_key
        if not key:
            return 127, "STABILITY_API_KEY is not configured."
        headers = {
            "authorization": f"Bearer {key}",
            "accept": "audio/*",
            "stability-client-id": "soundslo",
        }
        spec = get_model(generation.get("model", LARGE_API_ID))
        data = {
            "prompt": generation["prompt"],
            "model": spec.api_model or "stable-audio-3",
            "duration": str(generation["duration_seconds"]),
            "seed": str(min(generation["seed"], 2**32 - 2)),
            "steps": str(min(generation["steps"], 8)),
            "cfg_scale": str(generation["cfg_scale"]),
            "output_format": "wav",
        }
        base_url = self.settings.stability_api_base_url
        on_process(None)
        on_progress(4, "Sending the prompt to Stability AI")
        on_output("Submitting Stable Audio 3 Large generation to the Stability API.")
        started = time.monotonic()
        try:
            with httpx.Client(timeout=httpx.Timeout(60, connect=20)) as client:
                response = client.post(
                    f"{base_url}/v2beta/audio/stable-audio/text-to-audio",
                    headers=headers,
                    files={"none": ("", b"")},
                    data=data,
                )
                if response.status_code != 202:
                    return response.status_code, _http_error(response)
                generation_id = response.json().get("id")
                if not generation_id:
                    return 502, "Stability API accepted the request but returned no generation ID."
                on_output(f"Stability API generation accepted: {generation_id}")
                on_progress(12, "Queued in the Stability cloud")

                while not is_cancelled():
                    result = client.get(
                        f"{base_url}/v2beta/audio/results/{generation_id}",
                        headers=headers,
                    )
                    if result.status_code == 200:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(result.content)
                        on_output("Stable Audio 3 Large WAV downloaded to this computer.")
                        on_progress(99, "Saving the WAV file")
                        return 0, "Stable Audio 3 Large generation completed."
                    if result.status_code != 202:
                        return result.status_code, _http_error(result)
                    elapsed = time.monotonic() - started
                    estimated = min(
                        90.0,
                        14 + elapsed / max(generation["duration_seconds"], 30) * 45,
                    )
                    on_progress(estimated, "Generating with Stable Audio 3 Large")
                    time.sleep(5)
                return 130, "Generation cancelled locally. The hosted API job may still complete."
        except httpx.HTTPError as error:
            return 503, f"Could not reach the Stability API: {error}"


def progress_from_line(line: str) -> tuple[float, str] | None:
    step_match = STEP_RE.search(line)
    if step_match:
        current, total = map(int, step_match.groups())
        return 35 + (current / max(total, 1)) * 35, f"Sampling — step {current} of {total}"
    markers = (
        ("downloading", 3, "Downloading model weights"),
        ("SA3 → MLX", 8, "Starting Stable Audio 3"),
        ("[1/5]", 18, "Encoding the prompt"),
        ("[2/5]", 28, "Building conditioning"),
        ("[3/5]", 35, "Loading and sampling the music model"),
        ("[4/5]", 78, "Decoding audio"),
        ("[5/5]", 95, "Writing the WAV file"),
        ("saved", 99, "Finalizing"),
    )
    lowered = line.lower()
    for marker, progress, stage in markers:
        if marker.lower() in lowered:
            return float(progress), stage
    return None


class JobManager:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        runner: GenerationRunner | None = None,
    ):
        self.database = database
        self.settings = settings
        self.runner = runner or GenerationRunner(settings)
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._current_id: str | None = None
        self._current_process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="soundslo-generator", daemon=True)
        self._thread.start()
        for generation_id in self.database.queued_ids():
            self._queue.put(generation_id)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            process = self._current_process
            generation_id = self._current_id
        if process and process.poll() is None:
            _terminate_process(process)
        if generation_id:
            self.database.update(
                generation_id,
                status="failed",
                stage="Interrupted",
                error="Soundslo stopped before this generation finished.",
            )
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=3)

    def submit(self, generation_id: str) -> None:
        self._queue.put(generation_id)

    def cancel(self, generation_id: str) -> bool:
        generation = self.database.get(generation_id)
        if generation is None or generation["status"] not in {"queued", "running"}:
            return False
        self.database.update(
            generation_id,
            status="cancelled",
            stage="Cancelled",
            error="Cancelled by user.",
        )
        with self._lock:
            if self._current_id == generation_id and self._current_process:
                _terminate_process(self._current_process)
        return True

    def _worker(self) -> None:
        while not self._stop.is_set():
            generation_id = self._queue.get()
            if generation_id is None:
                break
            generation = self.database.get(generation_id)
            if generation is None or generation["status"] != "queued":
                continue
            self._run_one(generation)

    def _run_one(self, generation: dict) -> None:
        generation_id = generation["id"]
        output_path = self.settings.generations_dir / f"{generation_id}.wav"
        started = time.monotonic()
        log_lines: list[str] = []
        last_persist = [0.0]

        with self._lock:
            self._current_id = generation_id
        self.database.update(
            generation_id,
            status="running",
            progress=1.0,
            stage="Starting the local model",
            error=None,
        )

        def on_output(line: str) -> None:
            log_lines.append(line)
            if sum(map(len, log_lines)) > MAX_LOG_CHARS:
                del log_lines[: max(1, len(log_lines) // 4)]

        def on_progress(progress: float, stage: str) -> None:
            current = self.database.get(generation_id)
            if current is None or current["status"] in TERMINAL_STATUSES:
                return
            now = time.monotonic()
            if now - last_persist[0] >= 0.15 or progress >= 95:
                self.database.update(generation_id, progress=progress, stage=stage)
                last_persist[0] = now

        def on_process(process: subprocess.Popen[bytes] | None) -> None:
            with self._lock:
                self._current_process = process

        try:
            return_code, raw_log = self.runner.run(
                generation,
                output_path,
                on_output,
                on_progress,
                on_process,
                lambda: self._stop.is_set()
                or (self.database.get(generation_id) or {}).get("status") == "cancelled",
            )
            elapsed = time.monotonic() - started
            current = self.database.get(generation_id)
            if current and current["status"] == "cancelled":
                output_path.unlink(missing_ok=True)
                self.database.update(generation_id, elapsed_seconds=elapsed, log=raw_log)
            elif return_code == 0 and output_path.is_file():
                self.database.update(
                    generation_id,
                    status="completed",
                    progress=100.0,
                    stage="Ready",
                    file_path=str(output_path),
                    file_size=output_path.stat().st_size,
                    elapsed_seconds=elapsed,
                    error=None,
                    log=raw_log,
                )
            else:
                message = _last_useful_line(raw_log or "\n".join(log_lines))
                self.database.update(
                    generation_id,
                    status="failed",
                    stage="Generation failed",
                    error=message or f"The model runner exited with code {return_code}.",
                    elapsed_seconds=elapsed,
                    log=raw_log,
                )
                output_path.unlink(missing_ok=True)
        except Exception as error:
            output_path.unlink(missing_ok=True)
            self.database.update(
                generation_id,
                status="failed",
                stage="Generation failed",
                error=str(error),
                elapsed_seconds=time.monotonic() - started,
                log="\n".join(log_lines)[-MAX_LOG_CHARS:],
            )
        finally:
            with self._lock:
                self._current_id = None
                self._current_process = None


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _last_useful_line(log: str) -> str:
    lines = [line.strip() for line in log.replace("\r", "\n").splitlines() if line.strip()]
    for line in reversed(lines):
        if "error" in line.lower() or "traceback" in line.lower():
            return line[-1000:]
    return lines[-1][-1000:] if lines else ""


def _http_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        detail = response.text.strip()
    else:
        if isinstance(payload, dict):
            errors = payload.get("errors") or payload.get("message") or payload.get("name")
            detail = "; ".join(errors) if isinstance(errors, list) else str(errors or payload)
        else:
            detail = str(payload)
    detail = detail[:1000] if detail else response.reason_phrase
    return f"Stability API {response.status_code}: {detail}"
