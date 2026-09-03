# Desktop architecture

The Electron main process owns the local service lifecycle. It chooses a free loopback port, starts
the bundled Python interpreter with Uvicorn, waits for `/api/health`, and then loads that private
origin in a context-isolated `BrowserWindow`. The renderer has no Node access. A narrow preload
bridge exposes only update operations and immutable desktop metadata.

Packaged resources are immutable:

```text
Resources/
  app.asar            Electron main, preload, and updater
  pyruntime/          relocatable CPython, Soundslo, web UI, and backend dependencies
  sa3-runtime/        one pinned official Stable Audio backend, without model weights
  foley-runtime/      pinned Foley-Omni Mac source, without its venv or model weights
  legal/              Soundslo and model notices and licenses
```

On launch, the small Stable Audio source runtime is copied into a revision-keyed user-data folder.
Model files then link to Hugging Face's user-data cache. Keeping every writable artifact outside
`Resources` preserves the macOS app signature and lets updates replace the bundle without touching
models, the SQLite history, or WAV files.

## Native backends

- `mac-arm64` bundles MLX and Stable Audio's MLX command for Metal acceleration.
- `win-x64` bundles `ai_edge_litert` and the portable TFLite command.
- TFLite uses `w16a32`: FP16 weights with FP32 activations. The upstream runtime describes this as
  approximately lossless compared with FP32 while cutting the download roughly in half.

Intel macOS is not a release target because the official LiteRT package has no macOS x64 runtime.

## Foley-Omni sound effects

Apple-silicon Macs can optionally install the pinned Foley-Omni runtime and model stack. It adds
text-to-sound-effects and video-to-synchronized-soundtrack generation. The released checkpoint
produces 16 kHz mono WAV files and accepts clips from 1 to 10 seconds; video inputs longer than 10
seconds are trimmed. Inputs shorter than roughly 0.7 seconds cannot provide enough synchronization
frames.

Foley-Omni is deliberately not installed on first launch. Installing it downloads about 40 GB,
needs 36 GB free during fp32-to-bf16 conversion, and settles at roughly 30 GB of model data plus a
1.3 GB Python environment. Soundslo requires a 32 GB Apple-silicon Mac, enables CPU offload below
48 GB, and recommends 64 GB. A 50-step ten-second clip takes about 2.7 minutes on an M1 Max in the
reference benchmark; startup can add 30–90 seconds while the model is loaded.

The optional stack is for local non-commercial research and personal experimentation. Its Apple
DFN5B checkpoint is research-only and its MMAudio-derived checkpoints are CC BY-NC 4.0. See the
legal files in `licenses/`; these dependencies block a commercial release until relicensed or
replaced.

Generation commands invoke the backend Python entrypoint directly through the same bundled Python
that runs the service. POSIX streams use a pseudo-terminal for progress; Windows uses a merged line
pipe and terminates process trees with `taskkill` on cancel or shutdown.

## First run

After the service becomes healthy, Electron requests installation of Medium. The existing model
manager owns the background subprocess and exposes progress through `/api/models`. Downloads are
pinned to `SA3_WEIGHTS_REVISION`, and each backend requests only the text encoder, Medium DiT, and
decoder required for text-to-audio.

If a file is already in the Hugging Face cache, setup links it immediately. Windows falls back from
symlink to hardlink and then copy when Developer Mode is unavailable. A failed download remains
retryable from Settings.
