from pathlib import Path

import httpx

from soundslo.config import Settings
from soundslo.generator import GenerationRunner, progress_from_line
from soundslo.models import LARGE_API_ID, SMALL_MUSIC_ID


def test_progress_parser() -> None:
    assert progress_from_line("[1/5] T5Gemma encode")[0] == 18
    assert progress_from_line("sampling step 4/8")[0] == 52.5
    assert progress_from_line("[5/5] Unpatch + write WAV")[0] == 95
    assert progress_from_line("unrelated output") is None


def test_medium_command_is_reproducible(tmp_path: Path) -> None:
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "db.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / "stable-audio-3",
        static_dir=tmp_path / "static",
    )
    runner = GenerationRunner(settings)
    command = runner.command_for(
        {
            "prompt": "cinematic instrumental",
            "negative_prompt": "vocals",
            "duration_seconds": 60,
            "steps": 8,
            "seed": 42,
            "cfg_scale": 3.0,
        },
        tmp_path / "out.wav",
    )
    assert command[0] == str(settings.runtime_python)
    assert command[1] == str(settings.sa3_executable)
    assert command[command.index("--dit") + 1] == "medium"
    assert command[command.index("--decoder") + 1] == "same-l"
    assert command[command.index("--seed") + 1] == "42"
    assert command[command.index("--out") + 1] == str(tmp_path / "out.wav")


def test_tflite_command_uses_portable_precision(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "db.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / "stable-audio-3",
        static_dir=tmp_path / "static",
        runtime_backend="tflite",
        runtime_python_path=python,
    )
    command = GenerationRunner(settings).command_for(
        {
            "prompt": "cinematic instrumental",
            "negative_prompt": "vocals",
            "duration_seconds": 30,
            "steps": 8,
            "seed": 42,
            "cfg_scale": 3,
        },
        tmp_path / "portable.wav",
    )
    assert command[:2] == [str(python), str(settings.sa3_executable)]
    assert command[command.index("--precision") + 1] == "w16a32"
    assert "--dit-dtype" not in command


def test_small_music_command_uses_matching_dit_and_decoder(tmp_path: Path) -> None:
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "db.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / "stable-audio-3",
        static_dir=tmp_path / "static",
    )
    runner = GenerationRunner(settings)
    command = runner.command_for(
        {
            "model": SMALL_MUSIC_ID,
            "prompt": "compact instrumental",
            "negative_prompt": "vocals",
            "duration_seconds": 120,
            "steps": 8,
            "seed": 7,
            "cfg_scale": 3,
        },
        tmp_path / "small.wav",
    )
    assert command[command.index("--dit") + 1] == "sm-music"
    assert command[command.index("--decoder") + 1] == "same-s"


def test_large_api_runner_downloads_wav_without_exposing_key(tmp_path: Path, monkeypatch) -> None:
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def post(self, url, *, headers, files, data):
            assert url.endswith("/v2beta/audio/stable-audio/text-to-audio")
            assert headers["authorization"] == "Bearer test-secret"
            assert files == {"none": ("", b"")}
            assert data["model"] == "stable-audio-3"
            return httpx.Response(202, json={"id": "a" * 64})

        def get(self, url, *, headers):
            assert url.endswith("/v2beta/audio/results/" + "a" * 64)
            assert headers["authorization"] == "Bearer test-secret"
            return httpx.Response(200, content=b"RIFF-cloud-wave")

    monkeypatch.setattr("soundslo.generator.httpx.Client", lambda **_: FakeClient())
    settings = Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "db.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / "stable-audio-3",
        static_dir=tmp_path / "static",
        stability_api_key="test-secret",
    )
    runner = GenerationRunner(settings)
    output = tmp_path / "large.wav"
    messages: list[str] = []
    return_code, log = runner.run(
        {
            "model": LARGE_API_ID,
            "prompt": "cinematic instrumental",
            "negative_prompt": "vocals",
            "duration_seconds": 30,
            "steps": 8,
            "seed": 42,
            "cfg_scale": 3,
        },
        output,
        messages.append,
        lambda *_: None,
        lambda *_: None,
    )
    assert return_code == 0
    assert output.read_bytes() == b"RIFF-cloud-wave"
    assert "test-secret" not in log
    assert all("test-secret" not in message for message in messages)
