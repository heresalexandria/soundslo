# Desktop updates

Soundslo follows Aesthetician's explicit GitHub Release updater rather than Squirrel or
`electron-updater`. Unsigned Squirrel.Mac packages cannot update reliably; the explicit flow also
makes the trust boundary visible.

1. At startup and at most once per day, the renderer asks the main process to check the latest
   stable GitHub Release.
2. The main process selects the current platform/architecture asset and reports an available
   version without downloading it.
3. A user click downloads the asset and `SHA256SUMS.txt` from allow-listed GitHub HTTPS hosts.
4. Bytes are hashed while streaming. A mismatch deletes the staging directory and refuses install.
5. A second user click re-hashes the staged file immediately before install.
6. macOS extracts the release ZIP with `ditto`, verifies its ad-hoc signature, swaps the app through
   a detached rollback-capable script, and relaunches. Windows launches the normal NSIS installer
   and exits so locked files can be replaced.

The update state file contains timestamps, public version metadata, and a temporary staged path. It
does not contain credentials. Update URLs from release JSON are accepted only when they use HTTPS
and an expected GitHub host.
