#!/usr/bin/env bash
set -euo pipefail

SOUNDSLO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOUNDSLO_RUNTIME="$SOUNDSLO_ROOT/.runtime/stable-audio-3"
SOUNDSLO_MLX="$SOUNDSLO_RUNTIME/optimized/mlx"
SOUNDSLO_SA3_REVISION="a0b57f5483c4588f827f3552b7d5c6ca2a9687be"
SOUNDSLO_WITH_FOLEY=false

if [[ "${1:-}" == "--with-foley-runtime" ]]; then
  SOUNDSLO_WITH_FOLEY=true
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--with-foley-runtime]" >&2
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv with the official installer…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "Installing the Soundslo web application…"
cd "$SOUNDSLO_ROOT"
uv sync --dev

if [[ ! -d "$SOUNDSLO_RUNTIME/.git" ]]; then
  echo "Cloning Stability AI's official Stable Audio 3 runtime…"
  mkdir -p "$SOUNDSLO_ROOT/.runtime"
  git clone https://github.com/Stability-AI/stable-audio-3.git "$SOUNDSLO_RUNTIME"
fi

if [[ -n "$(git -C "$SOUNDSLO_RUNTIME" status --porcelain)" ]]; then
  echo "The Stable Audio runtime has local edits; setup will not overwrite them." >&2
  echo "Clean $SOUNDSLO_RUNTIME and run setup again." >&2
  exit 1
fi

echo "Pinning Stable Audio 3 to the tested revision…"
git -C "$SOUNDSLO_RUNTIME" fetch --depth 1 origin "$SOUNDSLO_SA3_REVISION"
git -C "$SOUNDSLO_RUNTIME" checkout --detach "$SOUNDSLO_SA3_REVISION"

echo "Installing the Apple Silicon MLX runtime…"
"$SOUNDSLO_MLX/install.sh" -y

echo "Fetching the text-to-instrumental model files…"
echo "The model weights are governed by the Stability AI Community License, not MIT."
echo "T5Gemma is governed by the Gemma Terms of Use. See NOTICE and licenses/."
"$SOUNDSLO_ROOT/scripts/install_model.sh" medium

if [[ "$SOUNDSLO_WITH_FOLEY" == true ]]; then
  echo "Setting up the optional Foley-Omni runtime (weights remain a separate install)…"
  "$SOUNDSLO_ROOT/scripts/setup_foley.sh"
fi

echo
echo "Soundslo is ready. Start it with:"
echo "  $SOUNDSLO_ROOT/scripts/run.sh"
echo "Optional Foley-Omni: scripts/setup_foley.sh && scripts/install_foley.sh"
