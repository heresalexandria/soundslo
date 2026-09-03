#!/usr/bin/env bash
set -euo pipefail

SOUNDSLO_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOUNDSLO_FOLEY_RUNTIME="${SOUNDSLO_FOLEY_ROOT:-$SOUNDSLO_PROJECT_ROOT/.runtime/foley-omni}"
SOUNDSLO_FOLEY_REVISION="cf4dda1bb3c8f591a84db08f635233260581bb63"
SOUNDSLO_FOLEY_REPO="https://github.com/heresalexandria/foley-omni-mac.git"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to set up Foley-Omni. Install it from https://docs.astral.sh/uv/." >&2
  exit 1
fi

if [[ ! -e "$SOUNDSLO_FOLEY_RUNTIME/inference_v2st.py" ]]; then
  echo "runtime: cloning foley-omni-mac @ ${SOUNDSLO_FOLEY_REVISION:0:12}"
  mkdir -p "$(dirname "$SOUNDSLO_FOLEY_RUNTIME")"
  git clone "$SOUNDSLO_FOLEY_REPO" "$SOUNDSLO_FOLEY_RUNTIME"
fi

if [[ -d "$SOUNDSLO_FOLEY_RUNTIME/.git" ]]; then
  if [[ -n "$(git -C "$SOUNDSLO_FOLEY_RUNTIME" status --porcelain)" ]]; then
    echo "The Foley-Omni runtime has local edits; setup will not overwrite them." >&2
    exit 1
  fi
  git -C "$SOUNDSLO_FOLEY_RUNTIME" fetch --depth 1 origin "$SOUNDSLO_FOLEY_REVISION"
  git -C "$SOUNDSLO_FOLEY_RUNTIME" checkout --detach "$SOUNDSLO_FOLEY_REVISION"
fi

if [[ ! -x "$SOUNDSLO_FOLEY_RUNTIME/.venv/bin/python" ]]; then
  echo "runtime: creating .venv"
  uv venv --python 3.11 "$SOUNDSLO_FOLEY_RUNTIME/.venv"
fi

echo "runtime: installing torch runtime (1.3 GB)"
uv pip install \
  --python "$SOUNDSLO_FOLEY_RUNTIME/.venv/bin/python" \
  -r "$SOUNDSLO_PROJECT_ROOT/requirements-foley.lock"

if [[ -d "$SOUNDSLO_FOLEY_RUNTIME/tests" ]]; then
  "$SOUNDSLO_FOLEY_RUNTIME/.venv/bin/python" \
    -m pytest -q -m "not weights" "$SOUNDSLO_FOLEY_RUNTIME/tests"
fi
echo "runtime: ready"
