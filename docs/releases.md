# Release process

Every pull request must have exactly one of `major`, `minor`, `patch`, or `no-release`. The PR check
enforces this before merge.

When a release-labeled pull request merges to `main`, `.github/workflows/release.yml`:

1. increments `pyproject.toml`, `uv.lock`, `soundslo/__init__.py`, `app/package.json`, and the npm lockfile;
2. commits the version bump to `main`;
3. builds Apple-silicon macOS and Windows x64 on native runners;
4. boots every unpacked application with `--smoke` to verify its embedded Python, backend source,
   service, and model catalog;
5. publishes DMGs, macOS update ZIPs, the Windows NSIS installer, stable-name download aliases, and
   `SHA256SUMS.txt`; and
6. moves the `latest` tag to the released commit.

The tag is created only after every native build and smoke test passes. A failed build therefore
does not leave a partial release behind. `build-check.yml` can package any one target manually
without publishing it.

Run the `Create release labels` workflow once when setting up a new fork. Enable GitHub Pages with
GitHub Actions as its source so `pages.yml` can publish the static download page.
