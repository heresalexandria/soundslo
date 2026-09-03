from pathlib import Path

from fastapi.testclient import TestClient

from soundslo.app import create_app
from soundslo.config import Settings
from soundslo.models import FOLEY_ID, LARGE_API_ID, MEDIUM_ID, SMALL_MUSIC_ID


def test_generation_crud_and_audio(tmp_path: Path) -> None:
    root = tmp_path
    static_dir = Path(__file__).parents[1] / "soundslo" / "static"
    settings = Settings(
        root=root,
        data_dir=root / "data",
        database_path=root / "data" / "soundslo.sqlite3",
        generations_dir=root / "data" / "generations",
        sa3_root=root / ".runtime" / "stable-audio-3",
        static_dir=static_dir,
    )
    app = create_app(settings, start_jobs=False)

    with TestClient(app) as client:
        favicon = client.get("/favicon.ico")
        assert favicon.status_code == 200
        assert favicon.headers["content-type"] == "image/png"

        created = client.post(
            "/api/generations",
            json={
                "prompt": "Dark analog synth instrumental",
                "duration_seconds": 30,
                "seed": 123,
            },
        )
        assert created.status_code == 202
        generation = created.json()
        generation_id = generation["id"]
        assert generation["status"] == "queued"
        assert generation["seed"] == 123
        assert "vocals" in generation["negative_prompt"]

        renamed = client.patch(f"/api/generations/{generation_id}", json={"name": "Night Drive"})
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Night Drive"

        output_path = settings.generations_dir / f"{generation_id}.wav"
        output_path.write_bytes(b"RIFF-test-wave")
        app.state.database.update(
            generation_id,
            status="completed",
            progress=100,
            stage="Ready",
            file_path=str(output_path),
            file_size=output_path.stat().st_size,
        )

        audio = client.get(f"/api/generations/{generation_id}/audio")
        assert audio.status_code == 200
        assert audio.content == b"RIFF-test-wave"

        download = client.get(f"/api/generations/{generation_id}/download")
        assert download.status_code == 200
        assert "Night%20Drive.wav" in download.headers["content-disposition"]

        deleted = client.delete(f"/api/generations/{generation_id}")
        assert deleted.status_code == 204
        assert not output_path.exists()
        assert client.get(f"/api/generations/{generation_id}").status_code == 404


def test_rejects_delete_while_running(tmp_path: Path) -> None:
    static_dir = Path(__file__).parents[1] / "soundslo" / "static"
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "soundslo.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / ".runtime",
        static_dir=static_dir,
    )
    app = create_app(settings, start_jobs=False)
    with TestClient(app) as client:
        generation = client.post(
            "/api/generations", json={"prompt": "Orchestral instrumental score"}
        ).json()
        app.state.database.update(generation["id"], status="running")
        response = client.delete(f"/api/generations/{generation['id']}")
        assert response.status_code == 409


def test_model_catalog_is_transparent_without_exposing_credentials(tmp_path: Path) -> None:
    static_dir = Path(__file__).parents[1] / "soundslo" / "static"
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "soundslo.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / ".runtime",
        static_dir=static_dir,
        stability_api_key="super-secret-test-key",
    )
    app = create_app(settings, start_jobs=False)
    with TestClient(app) as client:
        response = client.get("/api/models")
        assert response.status_code == 200
        assert "super-secret-test-key" not in response.text
        models = {model["id"]: model for model in response.json()["models"]}
        assert set(models) == {SMALL_MUSIC_ID, MEDIUM_ID, LARGE_API_ID, FOLEY_ID}
        assert models[SMALL_MUSIC_ID]["max_duration_seconds"] == 120
        assert models[SMALL_MUSIC_ID]["download_bytes"] == 1_704_727_702
        assert models[MEDIUM_ID]["max_duration_seconds"] == 380
        assert models[MEDIUM_ID]["download_bytes"] == 5_179_055_990
        assert models[LARGE_API_ID]["parameter_label"] == "2.7B"
        assert models[LARGE_API_ID]["credits_per_generation"] == 26
        assert models[LARGE_API_ID]["ready"] is True
        assert models[LARGE_API_ID]["installable"] is False

        cannot_install = client.post(f"/api/models/{LARGE_API_ID}/install", json={})
        assert cannot_install.status_code == 400
        assert "API-only" in cannot_install.json()["detail"]
        csrf_style_install = client.post(f"/api/models/{SMALL_MUSIC_ID}/install")
        assert csrf_style_install.status_code == 415


def test_tflite_catalog_reports_the_portable_medium_bundle(tmp_path: Path) -> None:
    static_dir = Path(__file__).parents[1] / "soundslo" / "static"
    runtime_python = tmp_path / "python.exe"
    runtime_python.touch()
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "soundslo.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / "runtime",
        static_dir=static_dir,
        runtime_backend="tflite",
        runtime_python_path=runtime_python,
    )
    settings.sa3_executable.parent.mkdir(parents=True)
    settings.sa3_executable.touch()
    app = create_app(settings, start_jobs=False)
    with TestClient(app) as client:
        models = {model["id"]: model for model in client.get("/api/models").json()["models"]}
    medium = models[MEDIUM_ID]
    assert medium["runtime_backend"] == "tflite"
    assert medium["runtime_installed"] is True
    assert medium["download_bytes"] == 4_449_143_136
    assert medium["weight_files"][-1].endswith("dec_w16a32.tflite")


def test_generation_obeys_selected_model_limits(tmp_path: Path) -> None:
    static_dir = Path(__file__).parents[1] / "soundslo" / "static"
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "soundslo.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / ".runtime",
        static_dir=static_dir,
    )
    app = create_app(settings, start_jobs=False)
    with TestClient(app) as client:
        too_long = client.post(
            "/api/generations",
            json={
                "prompt": "Compact electronic instrumental",
                "model": SMALL_MUSIC_ID,
                "duration_seconds": 121,
            },
        )
        assert too_long.status_code == 422
        assert "at most 120 seconds" in too_long.text

        too_many_cloud_steps = client.post(
            "/api/generations",
            json={
                "prompt": "Large cinematic instrumental",
                "model": LARGE_API_ID,
                "steps": 9,
            },
        )
        assert too_many_cloud_steps.status_code == 422
        assert "at most 8 sampling steps" in too_many_cloud_steps.text

        ambiguous_cloud_seed = client.post(
            "/api/generations",
            json={
                "prompt": "Large cinematic instrumental",
                "model": LARGE_API_ID,
                "seed": 0,
            },
        )
        assert ambiguous_cloud_seed.status_code == 422
        assert "Seed 0 is random" in ambiguous_cloud_seed.text

        created = client.post(
            "/api/generations",
            json={
                "prompt": "Compact electronic instrumental",
                "model": SMALL_MUSIC_ID,
                "duration_seconds": 120,
            },
        )
        assert created.status_code == 202
        assert created.json()["model"] == SMALL_MUSIC_ID
