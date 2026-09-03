"""Pinned Foley-Omni runtime and model artifacts used by Soundslo."""

from __future__ import annotations

FOLEY_RUNTIME_REPO = "https://github.com/heresalexandria/foley-omni-mac.git"
FOLEY_RUNTIME_REVISION = "cf4dda1bb3c8f591a84db08f635233260581bb63"

FOLEY_WEIGHTS_REPO = "CocoBro/Foley-Omni"
FOLEY_WEIGHTS_REVISION = "840af95b2405941f928d5ee85d9a7f175789ded2"
FOLEY_WEIGHT_FILES = (
    ("Foley-Omni/v2st.pth", 22_214_978_751),
    ("Wan2.2-TI2V-5B/models_t5_umt5-xxl-enc-bf16.pth", 11_361_920_418),
    ("Wan2.2-TI2V-5B/google/umt5-xxl/tokenizer.json", 16_837_417),
    ("Wan2.2-TI2V-5B/google/umt5-xxl/spiece.model", 4_548_313),
    ("Wan2.2-TI2V-5B/google/umt5-xxl/tokenizer_config.json", 61_728),
    ("Wan2.2-TI2V-5B/google/umt5-xxl/special_tokens_map.json", 6_623),
    ("mmaudio/ext_weights/synchformer_state_dict.pth", 950_058_171),
    ("mmaudio/ext_weights/v1-16.pth", 686_652_758),
    ("mmaudio/ext_weights/best_netG.pt", 449_217_313),
)
FOLEY_DIT_BF16 = "Foley-Omni/v2st.bf16.safetensors"

CLIP_REPO = "apple/DFN5B-CLIP-ViT-H-14-384"
CLIP_REVISION = "01b771ed0d1395ca5ffdd279897d665ebe00dfd2"
CLIP_FILES = (
    ("open_clip_pytorch_model.bin", 3_947_081_637),
    ("open_clip_config.json", 735),
)

FOLEY_DOWNLOAD_BYTES = sum(size for _, size in FOLEY_WEIGHT_FILES) + sum(
    size for _, size in CLIP_FILES
)
FOLEY_REQUIRED_FREE_BYTES = 36_000_000_000


def installed_weight_files() -> tuple[str, ...]:
    """Return checkpoint-relative files retained after fp32 DiT conversion."""
    return tuple(path for path, _ in FOLEY_WEIGHT_FILES if path != "Foley-Omni/v2st.pth") + (
        FOLEY_DIT_BF16,
    )
