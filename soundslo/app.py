from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from soundslo import __version__
from soundslo.config import SA3_REVISION, SA3_WEIGHTS_REVISION, Settings
from soundslo.database import TERMINAL_STATUSES, Database
from soundslo.generator import GenerationRunner, JobManager
from soundslo.models import (
    LARGE_API_ID,
    MEDIUM_ID,
    ModelInstaller,
    get_model,
    model_catalog,
    system_ram_gb,
    weight_files_for,
)

DEFAULT_NEGATIVE_PROMPT = "vocals, singing, speech, spoken word, lyrics, choir"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


class GenerationCreate(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    name: str | None = Field(default=None, max_length=120)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    model: str = Field(default=MEDIUM_ID)
    duration_seconds: float = Field(default=30, ge=1, le=380)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    steps: int | None = Field(default=None, ge=1, le=100)
    cfg_scale: float | None = Field(default=None, ge=1, le=10)
    video_id: str | None = None

    @field_validator("prompt", "negative_prompt")
    @classmethod
    def strip_prompt(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def validate_model_limits(self) -> GenerationCreate:
        try:
            spec = get_model(self.model)
        except ValueError as error:
            raise ValueError(str(error)) from error
        if self.steps is None:
            self.steps = spec.default_steps
        if self.cfg_scale is None:
            self.cfg_scale = getattr(spec, "default_cfg_scale", 3.0)
        if self.negative_prompt is None:
            self.negative_prompt = getattr(spec, "default_negative_prompt", DEFAULT_NEGATIVE_PROMPT)
        if "duration_seconds" not in self.model_fields_set:
            self.duration_seconds = min(self.duration_seconds, spec.max_duration_seconds)
        if self.duration_seconds > spec.max_duration_seconds:
            raise ValueError(
                f"{spec.name} supports at most {spec.max_duration_seconds} seconds."
            )
        if self.steps > spec.max_steps:
            raise ValueError(f"{spec.name} supports at most {spec.max_steps} sampling steps.")
        if spec.deployment == "cloud" and self.seed is not None:
            if self.seed == 0:
                raise ValueError("Seed 0 is random in the Stability API; leave seed blank instead.")
            if self.seed > 2**32 - 2:
                raise ValueError(f"{spec.name} supports seeds up to {2**32 - 2}.")
        return self


class GenerationRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value


def create_app(settings: Settings | None = None, *, start_jobs: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    uploads_dir = settings.data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_path)
    database.initialize()
    database.fail_interrupted()
    runner = GenerationRunner(settings)
    jobs = JobManager(database, settings, runner)
    model_installer = ModelInstaller(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_jobs:
            jobs.start()
        yield
        if start_jobs:
            jobs.stop()
        model_installer.stop()

    app = FastAPI(title="Soundslo", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.jobs = jobs
    app.state.model_installer = model_installer

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/system")
    def system_status() -> dict:
        usage = shutil.disk_usage(settings.data_dir)
        medium = get_model(MEDIUM_ID)
        weights = {
            Path(relative).name: (settings.backend_root / relative).exists()
            for relative in weight_files_for(settings, medium)
        }
        result = {
            "app_version": __version__,
            "model": "Stable Audio 3 Medium",
            "model_revision": SA3_WEIGHTS_REVISION[:12],
            "runtime_revision": SA3_REVISION[:12],
            "runtime_installed": settings.runtime_installed,
            "runtime_backend": settings.runtime_backend,
            "weights_ready": all(weights.values()),
            "weights": weights,
            "ready": runner.is_ready() and all(weights.values()),
            "free_disk_bytes": usage.free,
            "data_directory": str(settings.data_dir),
        }
        foley = next(
            (model for model in model_catalog(settings) if model.get("family") == "foley-omni"),
            None,
        )
        if foley:
            result["foley"] = {
                "supported": foley.get("supported", False),
                "reason": foley.get("support_reason") or foley.get("unsupported_reason"),
                "ram_gb": system_ram_gb(),
                "runtime_installed": foley.get("runtime_installed", False),
                "weights_ready": foley.get("installed", False),
                "runtime_revision": str(foley.get("runtime_revision", ""))[:12],
                "weights_revision": str(foley.get("revision", ""))[:12],
            }
        return result

    @app.get("/api/models")
    def list_models() -> dict:
        usage = shutil.disk_usage(settings.data_dir)
        models = model_catalog(settings)
        for model in models:
            model["installation"] = model_installer.status(model["id"])
        return {
            "models": models,
            "free_disk_bytes": usage.free,
            "hugging_face_repository": "stabilityai/stable-audio-3-optimized",
            "large_local_available": False,
        }

    @app.post("/api/models/{model_id}/install", status_code=202)
    def install_model(model_id: str, request: Request) -> dict:
        content_type = request.headers.get("content-type", "").partition(";")[0]
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="Model installation requires JSON.")
        try:
            get_model(model_id)
            return model_installer.start(model_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/generations")
    def list_generations(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[dict]:
        return database.list(limit=limit)

    @app.post("/api/uploads", status_code=201)
    async def upload_video(file: Annotated[UploadFile, File(...)]) -> dict:
        upload_id = str(uuid.uuid4())
        temporary = uploads_dir / f".{upload_id}.uploading"
        try:
            filename = file.filename or ""
            extension = Path(filename).suffix.lower()
            if extension not in VIDEO_EXTENSIONS:
                raise HTTPException(
                    status_code=415,
                    detail="Video must be an MP4, MOV, WebM, or M4V file.",
                )
            size = await save_upload(file, temporary)
            path = uploads_dir / f"{upload_id}{extension}"
            temporary.replace(path)
            try:
                duration = probe_video_duration(path, settings)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        except HTTPException:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return {
            "id": upload_id,
            "path": str(path),
            "duration_seconds": duration,
            "size": size,
        }

    @app.post("/api/generations", status_code=202)
    def create_generation(payload: GenerationCreate) -> dict:
        spec = get_model(payload.model)
        if payload.video_id and not spec.accepts_video:
            raise HTTPException(status_code=400, detail=f"{spec.name} does not accept video input.")
        generation_id = str(uuid.uuid4())
        if payload.seed is not None:
            seed = payload.seed
        elif payload.model == LARGE_API_ID:
            seed = secrets.randbelow(2**32 - 2) + 1
        else:
            seed = secrets.randbelow(2**32)
        name = payload.name or suggested_name(payload.prompt)
        input_path = None
        mode = "text"
        duration_seconds = payload.duration_seconds
        if payload.video_id:
            input_path = find_upload(uploads_dir, payload.video_id)
            duration_seconds = min(probe_video_duration(input_path, settings), 10.0)
            mode = "video"
        generation = database.create(
            {
                "id": generation_id,
                "name": name,
                "prompt": payload.prompt,
                "negative_prompt": payload.negative_prompt,
                "duration_seconds": duration_seconds,
                "seed": seed,
                "steps": payload.steps,
                "cfg_scale": payload.cfg_scale,
                "model": payload.model,
                "model_revision": spec.revision,
                "mode": mode,
                "input_path": str(input_path) if input_path else None,
                "sample_rate": getattr(spec, "sample_rate", 44100),
            }
        )
        jobs.submit(generation_id)
        return generation

    @app.get("/api/generations/{generation_id}")
    def get_generation(generation_id: str) -> dict:
        return require_generation(database, generation_id)

    @app.patch("/api/generations/{generation_id}")
    def rename_generation(generation_id: str, payload: GenerationRename) -> dict:
        require_generation(database, generation_id)
        updated = database.update(generation_id, name=payload.name)
        assert updated is not None
        return updated

    @app.post("/api/generations/{generation_id}/retry", status_code=202)
    def retry_generation(generation_id: str) -> dict:
        original = require_generation(database, generation_id)
        payload = GenerationCreate(
            prompt=original["prompt"],
            name=f"{original['name']} — retry",
            negative_prompt=original["negative_prompt"],
            duration_seconds=original["duration_seconds"],
            seed=original["seed"],
            steps=original["steps"],
            cfg_scale=original["cfg_scale"],
            model=original["model"],
            video_id=Path(original["input_path"]).stem if original.get("input_path") else None,
        )
        return create_generation(payload)

    @app.post("/api/generations/{generation_id}/cancel")
    def cancel_generation(generation_id: str) -> dict:
        generation = require_generation(database, generation_id)
        if generation["status"] in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="This generation is no longer active.")
        jobs.cancel(generation_id)
        return require_generation(database, generation_id)

    @app.delete("/api/generations/{generation_id}", status_code=204)
    def delete_generation(generation_id: str) -> Response:
        generation = require_generation(database, generation_id)
        if generation["status"] == "running":
            raise HTTPException(
                status_code=409, detail="Cancel this generation before deleting it."
            )
        deleted = database.delete(generation_id)
        if deleted and deleted.get("file_path"):
            safe_audio_path(settings, deleted).unlink(missing_ok=True)
        return Response(status_code=204)

    @app.get("/api/generations/{generation_id}/audio")
    def play_audio(generation_id: str) -> FileResponse:
        generation = require_generation(database, generation_id)
        path = require_audio_path(settings, generation)
        return FileResponse(path, media_type="audio/wav")

    @app.get("/api/generations/{generation_id}/video")
    def play_video(generation_id: str) -> FileResponse:
        generation = require_generation(database, generation_id)
        path = require_video_path(settings, generation)
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/generations/{generation_id}/download")
    def download_audio(generation_id: str) -> FileResponse:
        generation = require_generation(database, generation_id)
        path = require_audio_path(settings, generation)
        return FileResponse(
            path,
            media_type="audio/wav",
            filename=f"{safe_filename(generation['name'])}.wav",
        )

    @app.post("/api/generations/{generation_id}/reveal")
    def reveal_audio(generation_id: str) -> dict[str, bool]:
        generation = require_generation(database, generation_id)
        path = require_audio_path(settings, generation)
        if sys.platform == "darwin":
            command = ["open", "-R", str(path)]
        elif sys.platform == "win32":
            command = ["explorer.exe", f"/select,{path}"]
        else:
            command = ["xdg-open", str(path.parent)]
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise HTTPException(
                status_code=500, detail="The file manager could not reveal this file."
            )
        return {"revealed": True}

    @app.get("/api/generations/{generation_id}/log")
    def generation_log(generation_id: str) -> dict[str, str]:
        generation = require_generation(database, generation_id)
        return {"log": generation.get("log") or "No runtime log yet."}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(settings.static_dir / "favicon-32.png", media_type="image/png")

    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(request: Request, path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(settings.static_dir / "index.html")

    return app


def require_generation(database: Database, generation_id: str) -> dict:
    generation = database.get(generation_id)
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    return generation


def safe_audio_path(settings: Settings, generation: dict) -> Path:
    raw_path = generation.get("file_path")
    default_path = settings.generations_dir / f"{generation['id']}.wav"
    path = Path(raw_path).resolve() if raw_path else default_path
    root = settings.generations_dir.resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid audio path.")
    return path


def require_audio_path(settings: Settings, generation: dict) -> Path:
    path = safe_audio_path(settings, generation)
    if generation["status"] != "completed" or not path.is_file():
        raise HTTPException(status_code=404, detail="Audio is not available yet.")
    return path


def require_video_path(settings: Settings, generation: dict) -> Path:
    raw_path = generation.get("video_path")
    if not raw_path:
        raise HTTPException(status_code=404, detail="Video is not available yet.")
    path = Path(raw_path).resolve()
    if not path.is_relative_to(settings.generations_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid video path.")
    if generation["status"] != "completed" or not path.is_file():
        raise HTTPException(status_code=404, detail="Video is not available yet.")
    return path


async def save_upload(file: UploadFile, destination: Path) -> int:
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Video uploads are limited to 500 MB.")
            output.write(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail="The uploaded video is empty.")
    return size


def find_upload(uploads_dir: Path, upload_id: str) -> Path:
    try:
        normalized = str(uuid.UUID(upload_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid video upload id.") from error
    matches = [
        path
        for path in uploads_dir.glob(f"{normalized}.*")
        if path.suffix in VIDEO_EXTENSIONS
    ]
    if len(matches) != 1:
        raise HTTPException(status_code=404, detail="Video upload not found.")
    return matches[0].resolve()


def probe_video_duration(path: Path, settings: Settings) -> float:
    try:
        import imageio_ffmpeg

        frames = imageio_ffmpeg.read_frames(str(path))
        metadata = next(frames)
        frames.close()
        duration = float(metadata["duration"])
        if duration > 0:
            return duration
    except (ImportError, KeyError, OSError, RuntimeError, StopIteration, TypeError, ValueError):
        pass

    commands: list[list[str]] = []
    foley_python = getattr(settings, "foley_python", None)
    if foley_python and Path(foley_python).is_file():
        script = (
            "import imageio_ffmpeg,json,sys; "
            "print(json.dumps(imageio_ffmpeg.read_frames(sys.argv[1]).__next__()))"
        )
        commands.append([str(foley_python), "-c", script, str(path)])
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        commands.append(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
        )
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        if result.returncode != 0:
            continue
        try:
            if "imageio_ffmpeg" in " ".join(command):
                import json

                duration = float(json.loads(result.stdout)["duration"])
            else:
                duration = float(result.stdout.strip())
        except (KeyError, TypeError, ValueError):
            continue
        if duration > 0:
            return duration
    raise HTTPException(
        status_code=422,
        detail="Could not read the video duration. Check that the file is a valid video.",
    )


def suggested_name(prompt: str) -> str:
    words = re.sub(r"\s+", " ", prompt).strip()
    return words[:64].rstrip(" ,.;:-") or "Untitled generation"


def safe_filename(name: str) -> str:
    filename = re.sub(r"[^\w\-. ]+", "", name, flags=re.UNICODE).strip(" .")
    return filename[:100] or "soundslo-generation"


app = create_app()
