<div align="center">
  <img src="soundslo/static/soundslo-icon.svg" alt="Soundslo icon" width="104" height="104" />
  <h1>Soundslo</h1>
  <p><em>Generate private, six-minute instrumental soundtracks from text on macOS or Windows.</em></p>
  <p><strong>Powered by Stability AI.</strong></p>
</div>

<p align="center">
  <img src="docs/assets/soundslo-app.jpg" alt="Soundslo's local music generation workbench" width="1100" />
</p>

Soundslo is a local-first music workbench for the **Stable Audio 3** family. Describe an
instrumental in ordinary language, set its exact duration and generation controls, queue several
takes, and keep a searchable library of WAV files. Medium is the default local model, Small Music
is an optional lighter download, and Large remains an explicitly opt-in hosted model.

Soundslo is an independent project and is not affiliated with, sponsored by, or endorsed by
Stability AI.

## Download for macOS or Windows

The [Soundslo download page](https://heresalexandria.github.io/soundslo/) links directly to the
latest stable installers:

| Platform | Build | Local engine |
|---|---|---|
| macOS, Apple silicon | [DMG](https://github.com/heresalexandria/soundslo/releases/latest/download/Soundslo-mac-arm64.dmg) | MLX on the Metal GPU |
| macOS, Intel | [DMG](https://github.com/heresalexandria/soundslo/releases/latest/download/Soundslo-mac-x64.dmg) | LiteRT/TFLite on CPU |
| Windows 10/11, 64-bit | [Installer](https://github.com/heresalexandria/soundslo/releases/latest/download/Soundslo-win-x64-setup.exe) | LiteRT/TFLite on CPU |

The desktop app bundles Electron, Python, Soundslo, and the correct Stable Audio runtime for its
platform. On first launch it automatically starts downloading the pinned Stable Audio 3 Medium
files if they are not already installed. Progress and retries live in **Settings**. The app stores
the runtime, Hugging Face cache, generation history, and WAVs in its user-data directory, so an app
update does not erase them.

Allow at least 8 GB free for first setup and temporary download space. The Apple-silicon MLX bundle
is approximately 5.2 GB. Intel Mac and Windows use the approximately 4.5 GB, near-lossless
`w16a32` LiteRT bundle. Generated WAVs use roughly 10 MB per minute.

The current downloads are unsigned. On macOS, Control-click the app and choose **Open**. On
Windows, choose **More info**, then **Run anyway** in the SmartScreen prompt.

## What it includes

- Exact 1–380 second text-to-instrumental generation
- Stable Audio 3 Medium and Small Music as local models, plus optional hosted Large
- Negative prompting, guidance, sampling steps, exact duration, and reproducible seeds
- A durable one-at-a-time queue with live stages and sampling progress
- Persistent playback history, WAV downloads, rename, retry, cancel, prompt reuse, logs, and delete
- Private random-port loopback service managed by the Electron main process
- Automatic first-run runtime/model setup with resumable Hugging Face caching
- Daily GitHub Release checks and checksum-verified, user-approved in-app updates

Apple-silicon builds use Stability AI's native MLX implementation. Intel Mac and Windows builds use
the official portable LiteRT/TFLite implementation with near-lossless FP16 weights and FP32
activations. Both use the same pinned upstream runtime and model snapshot.

## Run from source

The original shell setup remains useful for development on an Apple-silicon Mac:

```bash
bash scripts/setup.sh && bash scripts/run.sh
```

This installs `uv`, checks out the official Stable Audio 3 runtime at revision
`a0b57f5483c4588f827f3552b7d5c6ca2a9687be`, creates the MLX environment, and downloads model
snapshot `6736003cb57d06b7b1fdc36fad31b2a3709e4774`. After setup, `bash scripts/run.sh` starts the
browser app at [http://127.0.0.1:8733](http://127.0.0.1:8733).

To develop the Electron shell after source setup:

```bash
cd app
npm ci
npm start
```

The Settings panel can install or repair local model files. The equivalent source commands are:

```bash
bash scripts/install_model.sh small-music
bash scripts/install_model.sh medium
```

Hugging Face may require a free account, license acceptance, and `hf auth login`. Soundslo uses
Hugging Face's own cache and credential store; it does not save tokens in this repository.

## Optional hosted Large

Stable Audio 3 Large has no public local weights. To use Stability AI's hosted model from a source
checkout, start with:

```bash
bash scripts/run_with_large.sh
```

The API key stays in the server process environment and is never returned to the renderer. Large
prompts leave the computer, each successful generation costs Stability AI credits, and the hosted
API's own terms apply.

## Development and packaging

```bash
uv sync --dev
uv run ruff check .
uv run pytest
node tests/test_updater.js
cd app && npm run smoke
```

Native desktop packages use a pinned relocatable Python distribution and must be built on their
target platform:

```bash
python scripts/package/build.py --target mac-arm64
python scripts/package/build.py --target mac-x64
python scripts/package/build.py --target win-x64
```

See [desktop architecture](docs/desktop.md), [updates](docs/updates.md), and
[releases](docs/releases.md) for the bundle layout and CI/CD flow.

## Releases and updates

Pull requests carry exactly one `major`, `minor`, `patch`, or `no-release` label. Merging a release
PR bumps every version file, builds and smoke-tests all three native targets, publishes versioned
and stable-name assets plus `SHA256SUMS.txt`, and moves the rolling `latest` tag. GitHub Pages
publishes the static download page from `site/`.

Packaged apps check GitHub Releases at most once per day. Updates never install silently: Soundslo
shows the available version, downloads only after a click, verifies its SHA-256 digest, and asks the
user to install and restart. Model data remains in user data and is not part of app replacement.

## Licensing

Soundslo source code is available under the [MIT License](LICENSE). That license does **not**
relicense Stable Audio 3, T5Gemma, downloaded model weights, or other third-party components.

- The official Stable Audio 3 software runtime is MIT licensed and is bundled at its pinned source
  revision in desktop installers.
- Stable Audio 3 model weights download separately under the
  [Stability AI Community License](licenses/STABILITY_AI_COMMUNITY_LICENSE.md). Commercial users
  must follow its registration and revenue provisions.
- T5Gemma weights remain governed by the [Gemma Terms of Use](licenses/GEMMA_TERMS_OF_USE.md).
- Hosted Large use is governed by Stability AI's API terms, pricing, and acceptable-use policies.

Required attributions are retained in [NOTICE](NOTICE) and included with desktop packages. The
complete installed stack is best described as an **open-source application using separately
licensed open-weight models**, not as an entirely MIT-licensed distribution.
