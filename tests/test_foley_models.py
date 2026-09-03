from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from soundslo.config import Settings
from soundslo.foley_models import (
    CLIP_FILES,
    CLIP_REPO,
    CLIP_REVISION,
    FOLEY_DOWNLOAD_BYTES,
    FOLEY_RUNTIME_REVISION,
    FOLEY_WEIGHT_FILES,
    FOLEY_WEIGHTS_REPO,
    FOLEY_WEIGHTS_REVISION,
)
from soundslo.models import (
    FOLEY_ID,
    ModelInstaller,
    get_model,
    model_catalog,
    model_is_installed,
)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "soundslo.sqlite3",
        generations_dir=tmp_path / "data" / "generations",
        sa3_root=tmp_path / "sa3",
        static_dir=tmp_path / "static",
        foley_root=tmp_path / "foley",
    )


def test_foley_settings_default_and_environment(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "project"
    custom_root = tmp_path / "custom-foley"
    custom_python = tmp_path / "python"
    monkeypatch.setenv("SOUNDSLO_ROOT", str(root))
    monkeypatch.setenv("SOUNDSLO_FOLEY_ROOT", str(custom_root))
    monkeypatch.setenv("SOUNDSLO_FOLEY_PYTHON", str(custom_python))

    settings = Settings.from_env()

    assert settings.foley_root == custom_root
    assert settings.foley_python == custom_python
    assert settings.foley_ckpts == custom_root / "ckpts"
    assert settings.foley_worker.name == "foley_worker.py"


def test_foley_spec_has_pinned_size_and_runtime_metadata(tmp_path: Path) -> None:
    spec = get_model(FOLEY_ID)
    settings = make_settings(tmp_path)
    entry = next(item for item in model_catalog(settings) if item["id"] == FOLEY_ID)

    assert spec.family == "foley-omni"
    assert spec.download_bytes == FOLEY_DOWNLOAD_BYTES
    assert spec.download_bytes == sum(size for _, size in FOLEY_WEIGHT_FILES) + sum(
        size for _, size in CLIP_FILES
    )
    assert spec.default_steps == 50
    assert spec.default_cfg_scale == 5.0
    assert spec.sample_rate == 16_000
    assert spec.accepts_video is True
    assert entry["runtime_revision"] == FOLEY_RUNTIME_REVISION
    assert entry["install_command"] == "bash scripts/install_foley.sh"


def test_foley_install_check_requires_checkpoints_and_both_clip_files(
    monkeypatch, tmp_path: Path
) -> None:
    settings = make_settings(tmp_path)
    spec = get_model(FOLEY_ID)
    hf_home = tmp_path / "huggingface"
    monkeypatch.setenv("HF_HOME", str(hf_home))
    assert not model_is_installed(settings, spec)

    for relative_path in spec.weight_files:
        path = settings.foley_ckpts / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    clip_dir = (
        hf_home
        / "hub"
        / f"models--{CLIP_REPO.replace('/', '--')}"
        / "snapshots"
        / CLIP_REVISION
    )
    clip_dir.mkdir(parents=True)
    for filename, _ in CLIP_FILES:
        (clip_dir / filename).touch()

    assert model_is_installed(settings, spec)
    (clip_dir / CLIP_FILES[-1][0]).unlink()
    assert not model_is_installed(settings, spec)


def test_foley_download_plan_is_offline_and_revision_pinned() -> None:
    script = Path(__file__).parents[1] / "soundslo" / "foley_download.py"
    result = subprocess.run(
        [sys.executable, str(script), "--plan"],
        check=True,
        capture_output=True,
        text=True,
    )
    plan = json.loads(result.stdout)

    assert len(plan["files"]) == len(FOLEY_WEIGHT_FILES) + len(CLIP_FILES) == 11
    assert [item["path"] for item in plan["files"][: len(FOLEY_WEIGHT_FILES)]] == [
        path for path, _ in FOLEY_WEIGHT_FILES
    ]
    assert all(
        item["repo"] == FOLEY_WEIGHTS_REPO
        and item["revision"] == FOLEY_WEIGHTS_REVISION
        for item in plan["files"][: len(FOLEY_WEIGHT_FILES)]
    )
    assert all(
        item["repo"] == CLIP_REPO and item["revision"] == CLIP_REVISION
        for item in plan["files"][len(FOLEY_WEIGHT_FILES) :]
    )


def test_packaged_runtime_uses_bundled_python_and_staged_lock(
    monkeypatch, tmp_path: Path
) -> None:
    settings = make_settings(tmp_path)
    settings.foley_root.mkdir(parents=True)
    (settings.foley_root / "inference_v2st.py").touch()
    lock = settings.foley_root / "requirements-foley.lock"
    lock.touch()
    installer = ModelInstaller(settings)
    spec = get_model(FOLEY_ID)
    installer._statuses[spec.id] = installer._status(spec.id, "installing", 2, "Preparing")
    commands: list[list[str]] = []

    def fake_run(_spec, command, _output, env=None):
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            python = Path(command[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.touch()

    monkeypatch.setattr(installer, "_run_foley_process", fake_run)
    installer._create_packaged_foley_venv(spec, [], installer._foley_env())

    assert commands[0][:3] == [str(settings.runtime_python), "-m", "venv"]
    assert commands[1][:4] == [str(settings.foley_python), "-m", "pip", "install"]
    assert commands[1][-1] == str(lock)
    assert str(Path(__file__).parents[1]) in installer._foley_env()["PYTHONPATH"]


def test_installed_weights_do_not_skip_missing_foley_runtime(
    monkeypatch, tmp_path: Path
) -> None:
    settings = make_settings(tmp_path)
    installer = ModelInstaller(settings)
    monkeypatch.setattr("soundslo.models.FOLEY_REQUIRED_FREE_BYTES", 0)
    monkeypatch.setattr("soundslo.models._support_status", lambda *_: (True, None))
    monkeypatch.setattr("soundslo.models.model_is_installed", lambda *_: True)
    monkeypatch.setattr("soundslo.models.model_is_ready", lambda *_: False)
    monkeypatch.setattr(installer, "_install", lambda _spec: None)

    status = installer.start(FOLEY_ID)

    assert status["state"] == "installing"
