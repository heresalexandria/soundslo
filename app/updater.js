'use strict';

let app = null;
try {
  ({ app } = require('electron'));
} catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
}

const { execFile, spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const https = require('https');
const path = require('path');

const REPO = 'heresalexandria/soundslo';
const LATEST_URL = `https://api.github.com/repos/${REPO}/releases/latest`;
const RELEASES_PAGE = `https://github.com/${REPO}/releases/latest`;
const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;
const ALLOWED_HOSTS = [
  'api.github.com',
  'github.com',
  'objects.githubusercontent.com',
  'release-assets.githubusercontent.com',
];

const userAgent = () => `Soundslo/${app.getVersion()} (+https://github.com/${REPO})`;
const statePath = () => path.join(app.getPath('userData'), 'update-state.json');
const downloadDir = () => path.join(app.getPath('temp'), 'soundslo-update');

function readState() {
  try {
    const value = JSON.parse(fs.readFileSync(statePath(), 'utf8'));
    return value && typeof value === 'object' ? value : {};
  } catch (_) { return {}; }
}

function writeState(patch) {
  const value = { ...readState(), ...patch };
  fs.mkdirSync(path.dirname(statePath()), { recursive: true });
  fs.writeFileSync(statePath(), `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  return value;
}

function allowedUrl(raw) {
  let url;
  try { url = new URL(raw); } catch (_) { return false; }
  return url.protocol === 'https:' && ALLOWED_HOSTS.includes(url.hostname);
}

function request(url, redirects = 5) {
  return new Promise((resolve, reject) => {
    if (!allowedUrl(url)) { reject(new Error(`refusing to fetch ${url}`)); return; }
    const req = https.get(url, {
      headers: { 'User-Agent': userAgent(), Accept: 'application/vnd.github+json' },
      timeout: 30000,
    }, (response) => {
      if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume();
        if (!redirects) { reject(new Error('too many redirects')); return; }
        resolve(request(new URL(response.headers.location, url).toString(), redirects - 1));
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`GitHub returned HTTP ${response.statusCode}`));
        return;
      }
      resolve(response);
    });
    req.on('timeout', () => req.destroy(new Error('request timed out')));
    req.on('error', reject);
  });
}

async function text(url) {
  const response = await request(url);
  const chunks = [];
  let bytes = 0;
  for await (const chunk of response) {
    bytes += chunk.length;
    if (bytes > 8 * 1024 * 1024) throw new Error('GitHub response was too large');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

function parseVersion(raw) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/.exec(String(raw || '').trim());
  return match ? match.slice(1).map(Number) : null;
}

function compareVersions(a, b) {
  const left = parseVersion(a);
  const right = parseVersion(b);
  if (!left || !right) return null;
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) return left[index] > right[index] ? 1 : -1;
  }
  return 0;
}

function isNewer(candidate, current) {
  return compareVersions(candidate, current) === 1;
}

function assetFor(assets, platform = process.platform, arch = process.arch) {
  const list = Array.isArray(assets) ? assets : [];
  if (platform === 'darwin') {
    return list.find((asset) => asset.name && asset.name.endsWith(`-mac-${arch}.zip`)) || null;
  }
  if (platform === 'win32') {
    return list.find((asset) => /-win-x64-setup\.exe$/i.test(asset.name || '')) || null;
  }
  return null;
}

let lastResult = null;
let lastRelease = null;
let inFlight = null;

async function check({ force = false } = {}) {
  const state = readState();
  const current = app.getVersion();
  if (!force && state.lastCheckAt && Date.now() - state.lastCheckAt < CHECK_INTERVAL_MS) {
    return lastResult || {
      ok: true,
      current,
      latest: state.latest || null,
      available: Boolean(state.latest && isNewer(state.latest, current)),
      installable: Boolean(app.isPackaged && state.hasAsset),
      asset: state.assetName ? { name: state.assetName, size: state.assetSize || 0 } : null,
      checkedAt: state.lastCheckAt,
      releasesUrl: RELEASES_PAGE,
      skipped: true,
    };
  }
  try {
    const release = JSON.parse(await text(LATEST_URL));
    if (release.draft || release.prerelease || !parseVersion(release.tag_name)) {
      throw new Error('GitHub did not return a stable Soundslo release');
    }
    lastRelease = release;
    const latest = String(release.tag_name).replace(/^v/, '');
    const asset = assetFor(release.assets);
    lastResult = {
      ok: true,
      current,
      latest,
      available: isNewer(latest, current),
      installable: Boolean(app.isPackaged && asset),
      asset: asset ? { name: asset.name, size: asset.size || 0 } : null,
      notes: String(release.body || '').slice(0, 12000),
      htmlUrl: allowedUrl(release.html_url) ? release.html_url : RELEASES_PAGE,
      releasesUrl: RELEASES_PAGE,
      checkedAt: Date.now(),
    };
    writeState({
      lastCheckAt: lastResult.checkedAt,
      latest,
      hasAsset: Boolean(asset),
      assetName: asset ? asset.name : null,
      assetSize: asset ? asset.size || 0 : 0,
    });
    return lastResult;
  } catch (error) {
    return { ok: false, current, available: false, error: String(error.message || error) };
  }
}

function checksumFor(contents, assetName) {
  for (const line of String(contents || '').split('\n')) {
    const match = /^([0-9a-f]{64})\s+\*?(.+?)\s*$/i.exec(line.trim());
    if (match && path.basename(match[2]) === assetName) return match[1].toLowerCase();
  }
  return null;
}

async function download(sender) {
  if (!app.isPackaged) throw new Error('development builds update through git');
  const result = await check({ force: true });
  if (!result.ok) throw new Error(result.error || 'could not check for updates');
  if (!result.available) throw new Error('Soundslo is already up to date');
  const release = lastRelease;
  const asset = assetFor(release.assets);
  const sums = release.assets.find((item) => item.name === 'SHA256SUMS.txt');
  if (!asset || !sums || !allowedUrl(asset.browser_download_url) || !allowedUrl(sums.browser_download_url)) {
    throw new Error('the release is missing a trusted build or checksum file');
  }
  const expected = checksumFor(await text(sums.browser_download_url), asset.name);
  if (!expected) throw new Error(`SHA256SUMS.txt does not cover ${asset.name}`);

  const directory = downloadDir();
  fs.rmSync(directory, { recursive: true, force: true });
  fs.mkdirSync(directory, { recursive: true });
  const destination = path.join(directory, asset.name);
  const response = await request(asset.browser_download_url);
  inFlight = response;
  const total = Number(response.headers['content-length']) || asset.size || 0;
  const hash = crypto.createHash('sha256');
  let received = 0;
  let lastEmit = 0;
  await new Promise((resolve, reject) => {
    const output = fs.createWriteStream(destination, { mode: 0o600 });
    response.on('data', (chunk) => {
      received += chunk.length;
      hash.update(chunk);
      if (Date.now() - lastEmit > 200 && sender && !sender.isDestroyed()) {
        lastEmit = Date.now();
        sender.send('soundslo:update-progress', { received, total, fraction: total ? received / total : 0 });
      }
    });
    response.on('error', reject);
    output.on('error', reject);
    output.on('finish', resolve);
    response.pipe(output);
  });
  inFlight = null;
  const digest = hash.digest('hex');
  if (digest !== expected) {
    fs.rmSync(directory, { recursive: true, force: true });
    throw new Error('checksum mismatch; the update was not staged');
  }
  writeState({ staged: { file: destination, sha256: digest, version: result.latest } });
  return { version: result.latest, verified: true };
}

function cancelDownload() {
  if (!inFlight) return false;
  inFlight.destroy(new Error('download canceled'));
  inFlight = null;
  fs.rmSync(downloadDir(), { recursive: true, force: true });
  writeState({ staged: null });
  return true;
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { maxBuffer: 8 << 20 }, (error, stdout, stderr) => {
      if (error) reject(new Error(String(stderr || error.message).slice(-1000)));
      else resolve(stdout);
    });
  });
}

async function sha256(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

async function installMac(staged) {
  const installed = path.resolve(process.execPath, '..', '..', '..');
  if (!installed.endsWith('.app')) throw new Error('could not locate the installed Soundslo.app');
  fs.accessSync(path.dirname(installed), fs.constants.W_OK);
  const unpacked = path.join(downloadDir(), 'unpacked');
  fs.rmSync(unpacked, { recursive: true, force: true });
  fs.mkdirSync(unpacked, { recursive: true });
  await run('/usr/bin/ditto', ['-x', '-k', staged.file, unpacked]);
  const fresh = path.join(unpacked, 'Soundslo.app');
  if (!fs.existsSync(path.join(fresh, 'Contents', 'Info.plist'))) {
    throw new Error('the update archive did not contain Soundslo.app');
  }
  await run('/usr/bin/codesign', ['--verify', '--deep', '--strict', fresh]);
  const script = path.join(downloadDir(), 'swap.sh');
  fs.writeFileSync(script, `#!/bin/sh
set -u
pid="$1"; fresh="$2"; dest="$3"
for _ in $(seq 1 150); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
kill -0 "$pid" 2>/dev/null && exit 1
rm -rf "$dest.old"
mv "$dest" "$dest.old" || exit 1
if ! /usr/bin/ditto "$fresh" "$dest"; then rm -rf "$dest"; mv "$dest.old" "$dest"; exit 1; fi
rm -rf "$dest.old"
xattr -dr com.apple.quarantine "$dest" 2>/dev/null
open "$dest"
`, { mode: 0o700 });
  const child = spawn('/bin/sh', [script, String(process.pid), fresh, installed], {
    detached: true, stdio: 'ignore',
  });
  child.unref();
}

async function install() {
  const staged = readState().staged;
  if (!staged || !staged.file || !fs.existsSync(staged.file)) throw new Error('no update is staged');
  if (await sha256(staged.file) !== staged.sha256) throw new Error('the staged update failed verification');
  if (process.platform === 'darwin') await installMac(staged);
  else if (process.platform === 'win32') {
    const child = spawn(staged.file, [], { detached: true, stdio: 'ignore' });
    child.unref();
  } else throw new Error('self-update is available only on macOS and Windows');
  writeState({ staged: null, lastCheckAt: 0 });
  setTimeout(() => app.exit(0), 400);
  return { installing: true };
}

function stagedFile() {
  const staged = readState().staged;
  return staged && staged.file && fs.existsSync(staged.file) ? staged.file : null;
}

function info() {
  const state = readState();
  return {
    version: app.getVersion(),
    packaged: app.isPackaged,
    platform: process.platform,
    arch: process.arch,
    stale: !state.lastCheckAt || Date.now() - state.lastCheckAt >= CHECK_INTERVAL_MS,
    staged: stagedFile() ? { version: state.staged.version, verified: true } : null,
    releasesUrl: RELEASES_PAGE,
  };
}

module.exports = {
  check,
  info,
  download,
  cancelDownload,
  install,
  stagedFile,
  parseVersion,
  compareVersions,
  isNewer,
  assetFor,
  allowedUrl,
  checksumFor,
  CHECK_INTERVAL_MS,
};
