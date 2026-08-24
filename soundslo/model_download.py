"""Download the exact local model files Soundslo needs for its active backend."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

REPO_ID = "stabilityai/stable-audio-3-optimized"

MLX_FILES = {
    "sm-music": (
        ("models/mlx/t5gemma_f16.npz", "MLX/t5gemma_f16.npz"),
        ("models/mlx/dit_sm-music_f16.npz", "MLX/dit_sm-music_f16.npz"),
        ("models/mlx/same_s_decoder_f32.npz", "MLX/same_s_decoder_f32.npz"),
    ),
    "medium": (
        ("models/mlx/t5gemma_f16.npz", "MLX/t5gemma_f16.npz"),
        ("models/mlx/dit_medium_f16.npz", "MLX/dit_medium_f16.npz"),
        ("models/mlx/same_l_decoder_f32.npz", "MLX/same_l_decoder_f32.npz"),
    ),
}


def tflite_files(model: str, precision: str) -> tuple[tuple[str, str], ...]:
    family, decoder = {
        "sm-music": ("sa3-sm-music", "same-s"),
        "medium": ("sa3-m", "same-l"),
    }[model]
    paths = (
        "tflite/t5gemma/encoder_fp16.tflite",
        f"tflite/{family}/dit_{precision}.tflite",
        f"tflite/{decoder}/dec_{precision}.tflite",
    )
    return tuple((f"models/{path}", path) for path in paths)


def link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink()
    try:
        target.symlink_to(source)
        return
    except OSError:
        pass
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--model", choices=("sm-music", "medium"), default="medium")
    parser.add_argument("--backend", choices=("mlx", "tflite"), required=True)
    parser.add_argument("--precision", default="w16a32")
    args = parser.parse_args()

    if not args.runtime_root.is_dir():
        raise SystemExit(f"Stable Audio runtime not found at {args.runtime_root}")
    files = (
        MLX_FILES[args.model]
        if args.backend == "mlx"
        else tflite_files(args.model, args.precision)
    )

    from huggingface_hub import hf_hub_download  # noqa: PLC0415

    print(
        f"Downloading pinned Stable Audio 3 {args.model} files for {args.backend} "
        f"({args.revision[:12]}).",
        flush=True,
    )
    for relative_path, remote_path in files:
        print(f"fetching: {Path(remote_path).name}", flush=True)
        cached = Path(
            hf_hub_download(repo_id=REPO_ID, filename=remote_path, revision=args.revision)
        )
        target = args.runtime_root / relative_path
        link_or_copy(cached, target)
        print(f"ready: {target.name}", flush=True)


if __name__ == "__main__":
    main()
