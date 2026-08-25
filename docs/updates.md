# Desktop updates

Soundslo follows Clawnsole's explicit GitHub Release updater rather than Squirrel or
`electron-updater`. The explicit flow keeps the trust boundary visible and preserves the local
model cache across application replacement.

1. At every startup, the renderer asks the main process for a fresh check of the latest stable
   GitHub Release, then checks again every 24 hours while the app remains open.
2. The main process selects the current platform/architecture asset and reports an available
   version without downloading it.
3. A user click downloads the asset and `SHA256SUMS.txt` from allow-listed GitHub HTTPS hosts.
4. Bytes are hashed while streaming. A mismatch deletes the staging directory and refuses install.
5. A second user click re-hashes the staged file immediately before install.
6. macOS extracts the release ZIP with `ditto`, requires a strict Developer ID signature from Team
   ID `KMZ785G889`, passes Gatekeeper, validates the stapled notarization ticket, swaps the app
   through a detached rollback-capable script, and relaunches. Windows launches the normal NSIS
   installer and exits so locked files can be replaced.

The desktop top bar always shows the running version. When GitHub reports a newer release, an
animated blue-purple **Update Available** chip appears immediately beside it. Opening either the
version or update chip shows the available version and the release's notes before any download is
started. The animation respects the operating system's reduced-motion preference.

The update state file contains timestamps, public version metadata, and a temporary staged path. It
does not contain credentials. Update URLs from release JSON are accepted only when they use HTTPS
and an expected GitHub host.
