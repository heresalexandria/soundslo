from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import imageio_ffmpeg
from fastapi.testclient import TestClient

from soundslo.app import create_app
from soundslo.config import Settings
from soundslo.database import Database
from soundslo.models import FOLEY_ID, MEDIUM_ID


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "soundslo.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / ".runtime" / "stable-audio-3",
        foley_root=tmp_path / ".runtime" / "foley-omni",
        static_dir=Path(__file__).parents[1] / "soundslo" / "static",
    )


def make_video(path: Path, seconds: float = 1.2) -> None:
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=64x64:d={seconds}",
            "-r",
            "25",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def test_database_migrates_foley_columns(tmp_path: Path) -> None:
    path = tmp_path / "soundslo.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE generations (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL
            )"""
        )
    Database(path).initialize()
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(generations)")}
    assert {"mode", "input_path", "sample_rate", "video_path"} <= columns


def test_foley_defaults_and_limits(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path), start_jobs=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/generations",
            json={"prompt": "Footsteps crunching across wet gravel", "model": FOLEY_ID},
        )
        assert response.status_code == 202
        generation = response.json()
        assert generation["duration_seconds"] == 10
        assert generation["steps"] == 50
        assert generation["cfg_scale"] == 5.0
        assert generation["negative_prompt"] == "robotic, muffled, echo, distorted"
        assert generation["sample_rate"] == 16_000
        assert generation["mode"] == "text"

        too_long = client.post(
            "/api/generations",
            json={
                "prompt": "A heavy wooden door creaks",
                "model": FOLEY_ID,
                "duration_seconds": 11,
            },
        )
        assert too_long.status_code == 422
        assert "at most 10 seconds" in too_long.text

        too_many_steps = client.post(
            "/api/generations",
            json={"prompt": "Rain on a metal roof", "model": FOLEY_ID, "steps": 101},
        )
        assert too_many_steps.status_code == 422


def test_video_id_requires_video_model_and_video_endpoint_defaults_to_404(
    tmp_path: Path,
) -> None:
    app = create_app(settings_for(tmp_path), start_jobs=False)
    with TestClient(app) as client:
        invalid = client.post(
            "/api/generations",
            json={
                "prompt": "Instrumental score",
                "model": MEDIUM_ID,
                "video_id": "0b13bd35-8d3f-4d38-b6c7-711d304be98a",
            },
        )
        assert invalid.status_code == 400
        assert "does not accept video" in invalid.text

        generation = client.post(
            "/api/generations",
            json={"prompt": "A clock ticking loudly", "model": FOLEY_ID},
        ).json()
        assert client.get(f"/api/generations/{generation['id']}/video").status_code == 404


def test_upload_generation_video_round_trip_and_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    make_video(source)
    settings = settings_for(tmp_path)
    app = create_app(settings, start_jobs=False)
    with TestClient(app) as client, source.open("rb") as stream:
        uploaded = client.post(
            "/api/uploads", files={"file": (source.name, stream, "video/mp4")}
        )
        assert uploaded.status_code == 201
        upload = uploaded.json()
        assert upload["size"] == source.stat().st_size
        assert 1.0 <= upload["duration_seconds"] <= 1.5
        upload_path = Path(upload["path"])
        assert upload_path.is_file()

        created = client.post(
            "/api/generations",
            json={
                "prompt": "Soft fabric movement and footsteps",
                "model": FOLEY_ID,
                "video_id": upload["id"],
            },
        )
        assert created.status_code == 202
        generation = created.json()
        assert generation["mode"] == "video"
        assert generation["input_path"] == str(upload_path)
        assert 1.0 <= generation["duration_seconds"] <= 1.5

        muxed = settings.generations_dir / f"{generation['id']}.mp4"
        muxed.write_bytes(b"muxed-video")
        app.state.database.update(
            generation["id"], status="completed", video_path=str(muxed)
        )
        video = client.get(f"/api/generations/{generation['id']}/video")
        assert video.status_code == 200
        assert video.content == b"muxed-video"

        assert client.delete(f"/api/generations/{generation['id']}").status_code == 204
        assert not muxed.exists()
        assert not upload_path.exists()


def test_upload_rejects_wrong_extension(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path), start_jobs=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/uploads", files={"file": ("notes.txt", b"not video", "text/plain")}
        )
    assert response.status_code == 415


def test_database_delete_never_unlinks_outside_its_data_directory(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    outside = tmp_path / "keep-me.mov"
    outside.write_bytes(b"video")
    database.create(
        {
            "id": "safe-delete",
            "name": "Safe delete",
            "prompt": "A door closes",
            "negative_prompt": "music",
            "duration_seconds": 2,
            "seed": 1,
            "steps": 50,
            "cfg_scale": 5,
            "model": FOLEY_ID,
            "model_revision": "test",
            "mode": "video",
            "input_path": str(outside),
            "sample_rate": 16_000,
        }
    )

    database.delete("safe-delete")

    assert outside.is_file()
