#!/usr/bin/env bash
set -euo pipefail

SOUNDSLO_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOUNDSLO_FOLEY_RUNTIME="${SOUNDSLO_FOLEY_ROOT:-$SOUNDSLO_PROJECT_ROOT/.runtime/foley-omni}"
SOUNDSLO_FOLEY_PYTHON="${SOUNDSLO_FOLEY_PYTHON:-$SOUNDSLO_FOLEY_RUNTIME/.venv/bin/python}"
SOUNDSLO_FOLEY_WEIGHTS_REVISION="840af95b2405941f928d5ee85d9a7f175789ded2"
SOUNDSLO_FOLEY_CLIP_REVISION="01b771ed0d1395ca5ffdd279897d665ebe00dfd2"

if [[ ! -x "$SOUNDSLO_FOLEY_PYTHON" ]]; then
  echo "The Foley-Omni runtime is missing. Run ./scripts/setup_foley.sh first." >&2
  exit 1
fi

cd "$SOUNDSLO_PROJECT_ROOT"
exec "$SOUNDSLO_FOLEY_PYTHON" -m soundslo.foley_download \
  "$SOUNDSLO_FOLEY_RUNTIME" \
  --revision "$SOUNDSLO_FOLEY_WEIGHTS_REVISION" \
  --clip-revision "$SOUNDSLO_FOLEY_CLIP_REVISION"
