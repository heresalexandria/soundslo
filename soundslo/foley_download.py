"""Download and convert the pinned artifacts needed by Foley-Omni."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

try:
    from soundslo.foley_models import (
        CLIP_FILES,
        CLIP_REPO,
        CLIP_REVISION,
        FOLEY_DIT_BF16,
        FOLEY_REQUIRED_FREE_BYTES,
        FOLEY_WEIGHT_FILES,
        FOLEY_WEIGHTS_REPO,
        FOLEY_WEIGHTS_REVISION,
    )
    from soundslo.model_download import link_or_copy
except ModuleNotFoundError:
    from foley_models import (  # type: ignore[no-redef]
        CLIP_FILES,
        CLIP_REPO,
        CLIP_REVISION,
        FOLEY_DIT_BF16,
        FOLEY_REQUIRED_FREE_BYTES,
        FOLEY_WEIGHT_FILES,
        FOLEY_WEIGHTS_REPO,
        FOLEY_WEIGHTS_REVISION,
    )
    from model_download import link_or_copy  # type: ignore[no-redef]


def download_plan(weights_revision: str, clip_revision: str) -> dict:
    return {
        "required_free_bytes": FOLEY_REQUIRED_FREE_BYTES,
        "files": [
            {
                "repo": FOLEY_WEIGHTS_REPO,
                "revision": weights_revision,
                "path": path,
                "remote_path": f"ckpts/{path}",
                "bytes": size,
            }
            for path, size in FOLEY_WEIGHT_FILES
        ]
        + [
            {
                "repo": CLIP_REPO,
                "revision": clip_revision,
                "path": path,
                "bytes": size,
            }
            for path, size in CLIP_FILES
        ],
    }


def _convert(runtime_root: Path, source: Path, target: Path) -> None:
    converter = runtime_root / "scripts" / "convert_ckpt_bf16.py"
    if not converter.is_file():
        raise RuntimeError(f"Foley-Omni converter not found at {converter}")
    spec = importlib.util.spec_from_file_location("foley_convert_ckpt_bf16", converter)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import Foley-Omni converter at {converter}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_argv = sys.argv
    try:
        sys.argv = [str(converter), str(source), "--dst", str(target), "--dtype", "bf16"]
        module.main()
    finally:
        sys.argv = old_argv
    if not target.is_file():
        raise RuntimeError(f"Conversion finished without creating {target}")
    source.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", type=Path, nargs="?")
    parser.add_argument("--revision", default=FOLEY_WEIGHTS_REVISION)
    parser.add_argument("--clip-revision", default=CLIP_REVISION)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()

    if args.plan:
        print(json.dumps(download_plan(args.revision, args.clip_revision)))
        return
    if args.runtime_root is None or not args.runtime_root.is_dir():
        raise SystemExit(f"Foley-Omni runtime not found at {args.runtime_root}")

    free = shutil.disk_usage(args.runtime_root).free
    if free < FOLEY_REQUIRED_FREE_BYTES:
        need_gb = FOLEY_REQUIRED_FREE_BYTES / 1_000_000_000
        have_gb = free / 1_000_000_000
        raise SystemExit(
            f"Foley-Omni needs at least {need_gb:.0f} GB free before installation; "
            f"only {have_gb:.1f} GB is available. Nothing was downloaded."
        )

    from huggingface_hub import hf_hub_download  # noqa: PLC0415

    ckpts = args.runtime_root / "ckpts"
    source_dit = ckpts / "Foley-Omni" / "v2st.pth"
    converted_dit = ckpts / FOLEY_DIT_BF16
    non_dit_files = [item for item in FOLEY_WEIGHT_FILES if item[0] != "Foley-Omni/v2st.pth"]

    for relative_path, _ in non_dit_files:
        print(f"fetching: {Path(relative_path).name}", flush=True)
        cached = Path(
            hf_hub_download(
                repo_id=FOLEY_WEIGHTS_REPO,
                filename=f"ckpts/{relative_path}",
                revision=args.revision,
            )
        )
        target = ckpts / relative_path
        link_or_copy(cached, target)
        print(f"ready: {target.name}", flush=True)

    for relative_path, _ in CLIP_FILES:
        print(f"fetching: {Path(relative_path).name}", flush=True)
        cached = Path(
            hf_hub_download(
                repo_id=CLIP_REPO,
                filename=relative_path,
                revision=args.clip_revision,
            )
        )
        print(f"ready: {cached.name}", flush=True)

    if not converted_dit.is_file():
        print(f"fetching: {source_dit.name}", flush=True)
        downloaded = Path(
            hf_hub_download(
                repo_id=FOLEY_WEIGHTS_REPO,
                filename="ckpts/Foley-Omni/v2st.pth",
                revision=args.revision,
                local_dir=args.runtime_root,
            )
        )
        if downloaded != source_dit:
            source_dit.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(downloaded, source_dit)
        print(f"ready: {source_dit.name}", flush=True)
        print("converting: v2st.pth -> v2st.bf16.safetensors", flush=True)
        _convert(args.runtime_root, source_dit, converted_dit)
        print(f"converted: {converted_dit.name}", flush=True)
    elif source_dit.is_file():
        source_dit.unlink()


if __name__ == "__main__":
    main()
