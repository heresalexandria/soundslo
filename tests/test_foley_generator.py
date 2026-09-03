from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from soundslo.config import Settings
from soundslo.database import Database
from soundslo.foley_worker import structured_prompt
from soundslo.generator import GenerationRunner, JobManager, progress_from_line
from soundslo.models import FOLEY_ID


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "db.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / "stable-audio-3",
        static_dir=tmp_path / "static",
        foley_root=tmp_path / "foley-omni",
        foley_python_path=tmp_path / "foley-python",
    )


def _generation(**overrides) -> dict:
    return {
        "model": FOLEY_ID,
        "prompt": "boots crossing a gravel path",
        "negative_prompt": "music, speech",
        "duration_seconds": 6,
        "steps": 50,
        "seed": 17,
        "cfg_scale": 5.0,
        **overrides,
    }


def test_structured_prompt_wraps_plain_text_and_preserves_model_tags() -> None:
    assert structured_prompt("  a door creaks  ") == (
        "[AUDIO_CAPTION]a door creaks[END_AUDIO_CAPTION]"
    )
    tagged = "[MUSIC]quiet score[END_MUSIC][AUDIO_CAPTION]rain[END_AUDIO_CAPTION]"
    assert structured_prompt(tagged) == tagged


def test_worker_dry_run_needs_no_model_runtime_and_clamps_duration(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    checkpoints = runtime / "ckpts"
    converted = checkpoints / "Foley-Omni" / "v2st.bf16.safetensors"
    converted.parent.mkdir(parents=True)
    converted.touch()
    worker = Path(__file__).parents[1] / "soundslo" / "foley_worker.py"

    result = subprocess.run(
        [
            sys.executable,
            str(worker),
            "--runtime-root",
            str(runtime),
            "--ckpt-dir",
            str(checkpoints),
            "--prompt",
            "waves on rocks",
            "--seconds",
            "30",
            "--steps",
            "25",
            "--seed",
            "9",
            "--cfg",
            "4.5",
            "--video",
            str(tmp_path / "clip.mov"),
            "--out",
            str(tmp_path / "result.wav"),
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    plan = json.loads(result.stdout)
    assert plan == {
        "runtime_root": str(runtime.resolve()),
        "ckpt_dir": str(checkpoints.resolve()),
        "model_checkpoint": str(converted),
        "mode": "video",
        "prompt": "[AUDIO_CAPTION]waves on rocks[END_AUDIO_CAPTION]",
        "seconds": 10.0,
        "steps": 25,
        "seed": 9,
        "cfg": 4.5,
        "out": str(tmp_path / "result.wav"),
    }


def test_foley_text_command_uses_dedicated_runtime(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr("soundslo.generator.ram_gb", lambda: 64)
    output = tmp_path / "effect.wav"

    command = GenerationRunner(settings).command_for(_generation(), output)

    assert command[:2] == [str(settings.foley_python), str(settings.foley_worker)]
    assert command[command.index("--runtime-root") + 1] == str(settings.foley_root)
    assert command[command.index("--ckpt-dir") + 1] == str(settings.foley_ckpts)
    assert command[command.index("--steps") + 1] == "50"
    assert command[command.index("--out") + 1] == str(output)
    assert "--video" not in command
    assert "--cpu-offload" not in command
    assert GenerationRunner(settings).workdir_for(_generation()) == settings.foley_root


def test_foley_video_command_muxes_and_enables_low_memory_mode(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr("soundslo.generator.ram_gb", lambda: 32)
    output = tmp_path / "effect.wav"
    source = tmp_path / "source.mov"

    command = GenerationRunner(settings).command_for(
        _generation(input_path=str(source)), output
    )

    assert command[command.index("--video") + 1] == str(source)
    assert command[command.index("--mux-out") + 1] == str(output.with_suffix(".mp4"))
    assert "--cpu-offload" in command


def test_foley_progress_parser_uses_sound_effect_stages() -> None:
    assert progress_from_line("[1/5] Loading Foley-Omni", "foley-omni") == (
        18.0,
        "Loading Foley-Omni",
    )
    assert progress_from_line("device: mps", "foley-omni") == (
        10.0,
        "Starting on Apple silicon",
    )
    assert progress_from_line("step 25/50", "foley-omni") == (
        52.5,
        "Sampling — step 25 of 50",
    )
    assert progress_from_line("[2/5] Preparing video", "foley-omni") == (
        28.0,
        "Extracting video features",
    )
    assert progress_from_line("saved: result.wav", "foley-omni") == (99.0, "Finalizing")


def test_completed_video_generation_records_muxed_output(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    generation = database.create(
        {
            "id": "foley-job",
            "name": "Gravel walk",
            "prompt": "boots crossing a gravel path",
            "negative_prompt": "music, speech",
            "duration_seconds": 6,
            "seed": 17,
            "steps": 50,
            "cfg_scale": 5.0,
            "model": FOLEY_ID,
            "model_revision": "test-revision",
            "mode": "video",
            "input_path": str(tmp_path / "source.mov"),
            "sample_rate": 16_000,
        }
    )

    class FakeRunner:
        def run(self, _generation, output_path, on_output, on_progress, on_process, _cancelled):
            output_path.write_bytes(b"RIFF-test")
            output_path.with_suffix(".mp4").write_bytes(b"video-test")
            on_process(None)
            on_output("saved: effect.wav")
            on_progress(99, "Finalizing")
            return 0, "saved: effect.wav"

    manager = JobManager(database, settings, runner=FakeRunner())
    manager._run_one(generation)

    completed = database.get("foley-job")
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["file_path"] == str(settings.generations_dir / "foley-job.wav")
    assert completed["video_path"] == str(settings.generations_dir / "foley-job.mp4")
