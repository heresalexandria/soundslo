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
  legal/              Soundslo and model notices and licenses
```

On launch, the small Stable Audio source runtime is copied into a revision-keyed user-data folder.
Model files then link to Hugging Face's user-data cache. Keeping every writable artifact outside
`Resources` preserves the macOS app signature and lets updates replace the bundle without touching
models, the SQLite history, or WAV files.

## Native backends

- `mac-arm64` bundles MLX and Stable Audio's MLX command for Metal acceleration.
- `mac-x64` and `win-x64` bundle `ai_edge_litert` and the portable TFLite command.
- TFLite uses `w16a32`: FP16 weights with FP32 activations. The upstream runtime describes this as
  approximately lossless compared with FP32 while cutting the download roughly in half.

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
