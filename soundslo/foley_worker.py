#!/usr/bin/env python
"""Soundslo job worker for the Foley-Omni Mac runtime.

This script is executed with the Foley-Omni runtime's Python. It emits the same
progress protocol as the Stable Audio worker: ``[k/5]`` stage markers,
``step i/N`` sampling updates, and a final ``saved:`` line.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

TAGS = ("[AUDIO_CAPTION]", "[MUSIC]", "[WORDS]")
LATENTS_PER_SECOND = 31.4
MAX_SECONDS = 10.0


def structured_prompt(prompt: str) -> str:
    """Wrap an unstructured prompt in Foley-Omni's audio-caption tags."""
    prompt = prompt.strip()
    if any(tag in prompt for tag in TAGS):
        return prompt
    return f"[AUDIO_CAPTION]{prompt}[END_AUDIO_CAPTION]"


def ffmpeg_exe() -> str:
    """Return the ffmpeg binary bundled with the Foley runtime."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def prepare_video(src: Path, workdir: Path) -> Path:
    """Normalize a video for feature extraction, trimming it to ten seconds."""
    dst = workdir / f"{src.stem}.foley-input.mp4"
    subprocess.run(
        [
            ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-t",
            str(MAX_SECONDS),
            "-vf",
            "fps=25,scale='min(iw,1280)':-2",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ],
        check=True,
    )
    return dst


def mux(video: Path, wav: Path, dst: Path) -> None:
    """Mux the generated soundtrack into the normalized input video."""
    subprocess.run(
        [
            ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-i",
            str(wav),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            str(dst),
        ],
        check=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, help="foley-omni-mac checkout")
    parser.add_argument("--ckpt-dir", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", default="robotic, muffled, echo, distorted")
    parser.add_argument("--seconds", type=float, default=MAX_SECONDS)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cfg", type=float, default=5.0)
    parser.add_argument("--video", default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--cpu-offload", action="store_true")
    parser.add_argument("--out", required=True, help="WAV path")
    parser.add_argument("--mux-out", default=None, help="optional MP4 with the new soundtrack")
    parser.add_argument("--dry-run", action="store_true", help="print plan JSON; no torch import")
    return parser


def main() -> int:
    args = _parser().parse_args()

    root = Path(args.runtime_root).resolve()
    ckpts = Path(args.ckpt_dir).resolve()
    dit = ckpts / "Foley-Omni" / "v2st.bf16.safetensors"
    if not dit.exists():
        dit = ckpts / "Foley-Omni" / "v2st.pth"
    seconds = min(max(args.seconds, 1.0), MAX_SECONDS)
    prompt = structured_prompt(args.prompt)
    plan = {
        "runtime_root": str(root),
        "ckpt_dir": str(ckpts),
        "model_checkpoint": str(dit),
        "mode": "video" if args.video else "text",
        "prompt": prompt,
        "seconds": seconds,
        "steps": args.steps,
        "seed": args.seed,
        "cfg": args.cfg,
        "out": args.out,
    }
    if args.dry_run:
        print(json.dumps(plan))
        return 0

    # inference_v2st resolves this path at import time.
    os.environ.setdefault("FOLEY_OMNI_EXT_WEIGHTS", str(ckpts / "mmaudio" / "ext_weights"))
    sys.path[:0] = [str(root), str(root / "mmaudio")]
    logging.basicConfig(level=logging.WARNING)

    print("[1/5] Loading Foley-Omni", flush=True)
    import foley_omni.fusion_engine as fusion_engine
    import inference_v2st
    import numpy as np
    import soundfile as sf
    from foley_omni.device import describe, resolve_device
    from omegaconf import OmegaConf
    from tqdm import tqdm as _tqdm

    total_steps = args.steps

    class StepTqdm(_tqdm):
        """Silent tqdm that emits Soundslo's ``step i/N`` protocol."""

        def __init__(self, *values, **options):
            options.setdefault("disable", True)
            super().__init__(*values, **options)

        def __iter__(self):
            total = self.total or total_steps
            for index, item in enumerate(super().__iter__(), 1):
                yield item
                print(f"step {index}/{total}", flush=True)

    fusion_engine.tqdm = StepTqdm
    inference_v2st.tqdm = StepTqdm

    config = OmegaConf.load(root / "inference_v2st.yaml")
    config.ckpt_dir = str(ckpts)
    config.model_checkpoint = str(dit)
    config.device = args.device
    config.cpu_offload = bool(args.cpu_offload)
    config.sample_steps = args.steps
    config.audio_guidance_scale = args.cfg
    config.audio_negative_prompt = args.negative_prompt
    config.noise_device = "cpu"
    config.cfg_batched = True
    device = resolve_device(args.device)
    print(f"device: {describe(device)}", flush=True)
    engine = fusion_engine.FoleyOmniEngine(config=config, device=device)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.video is None:
        engine.audio_latent_length = max(1, round(seconds * LATENTS_PER_SECOND))
        print("[3/5] Sampling", flush=True)
        _, audio, _ = engine.generate(
            text_prompt=prompt,
            seed=args.seed,
            solver_name=str(config.solver_name),
            sample_steps=args.steps,
            shift=float(config.shift),
            audio_guidance_scale=args.cfg,
            slg_layer=int(config.slg_layer),
            audio_negative_prompt=args.negative_prompt,
        )
        video_in = None
    else:
        print("[2/5] Preparing the video and extracting features", flush=True)
        video_in = prepare_video(Path(args.video), out.parent)
        try:
            audio = inference_v2st.generate_audio_for_video(
                engine,
                str(video_in),
                prompt,
                seed=args.seed,
                solver_name=str(config.solver_name),
                sample_steps=args.steps,
                shift=float(config.shift),
                audio_guidance_scale=args.cfg,
                slg_layer=int(config.slg_layer),
                audio_negative_prompt=args.negative_prompt,
                duration=MAX_SECONDS,
                device=device,
                feature_device=config.get("feature_device", None),
                clip_batch_size=int(config.get("clip_batch_size", 16)),
                sync_batch_size=int(config.get("sync_batch_size", 8)),
            )
        except inference_v2st.SkipShortVideoError as error:
            print(
                f"error: video too short for Foley-Omni (needs at least 0.7 s): {error}",
                flush=True,
            )
            return 2

    print("[5/5] Writing the WAV file", flush=True)
    sample_rate = int(config.sample_rate)
    audio = np.asarray(audio, dtype=np.float32)
    if args.video is None:
        wanted_samples = int(seconds * sample_rate)
        if len(audio) >= wanted_samples:
            audio = audio[:wanted_samples]
        else:
            audio = np.pad(audio, (0, wanted_samples - len(audio)))
    if not np.isfinite(audio).all():
        print("error: model produced non-finite audio", flush=True)
        return 3
    sf.write(out, np.clip(audio, -1.0, 1.0), sample_rate, subtype="PCM_16")
    if args.mux_out and video_in is not None:
        mux(video_in, out, Path(args.mux_out))
        print(f"saved: {args.mux_out}", flush=True)
    print(f"saved: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
