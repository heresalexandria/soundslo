'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const updater = require('../app/updater');

assert.deepStrictEqual(updater.parseVersion('v1.2.3'), [1, 2, 3]);
assert.strictEqual(updater.compareVersions('1.3.0', '1.2.9'), 1);
assert.strictEqual(updater.compareVersions('1.2.3', '1.2.3'), 0);
assert.strictEqual(updater.isNewer('2.0.0', '1.9.9'), true);
assert.strictEqual(updater.isNewer('1.0.0', '1.0.1'), false);

const assets = [
  { name: 'Soundslo-1.2.3-mac-arm64.zip' },
  { name: 'Soundslo-1.2.3-win-x64-setup.exe' },
];
assert.strictEqual(updater.assetFor(assets, 'darwin', 'arm64').name, assets[0].name);
assert.strictEqual(updater.assetFor(assets, 'darwin', 'x64'), null);
assert.strictEqual(updater.assetFor(assets, 'win32', 'arm64').name, assets[1].name);
assert.strictEqual(updater.assetFor(assets, 'linux', 'x64'), null);

const digest = 'a'.repeat(64);
assert.strictEqual(updater.checksumFor(`${digest}  ${assets[0].name}\n`, assets[0].name), digest);
assert.strictEqual(updater.allowedUrl('https://api.github.com/repos/x/y'), true);
assert.strictEqual(updater.allowedUrl('http://api.github.com/repos/x/y'), false);
assert.strictEqual(updater.allowedUrl('https://example.com/update.zip'), false);
assert.strictEqual(updater.EXPECTED_MAC_TEAM_ID, 'KMZ785G889');

const release = updater.resultForRelease({
  tag_name: 'v1.2.3',
  draft: false,
  prerelease: false,
  body: 'New instruments\n\nFaster exports',
  html_url: 'https://github.com/heresalexandria/soundslo/releases/tag/v1.2.3',
  assets: [{ name: 'Soundslo-1.2.3-mac-arm64.zip', size: 42 }],
}, {
  current: '1.2.2',
  packaged: true,
  platform: 'darwin',
  arch: 'arm64',
  checkedAt: 1234,
});
assert.strictEqual(release.latest, '1.2.3');
assert.strictEqual(release.available, true);
assert.strictEqual(release.installable, true);
assert.strictEqual(release.notes, 'New instruments\n\nFaster exports');
assert.strictEqual(release.checkedAt, 1234);
assert.throws(() => updater.resultForRelease({
  tag_name: 'v1.2.3-beta.1',
  prerelease: true,
}, { current: '1.2.2', packaged: true }), /stable Soundslo release/);

const root = path.resolve(__dirname, '..');
const renderer = fs.readFileSync(path.join(root, 'soundslo/static/app.js'), 'utf8');
const markup = fs.readFileSync(path.join(root, 'soundslo/static/index.html'), 'utf8');
const styles = fs.readFileSync(path.join(root, 'soundslo/static/styles.css'), 'utf8');
assert.match(renderer, /UPDATE_POLL_INTERVAL_MS = 24 \* 60 \* 60 \* 1000/);
assert.match(renderer, /await checkDesktopUpdate\(true\)/);
assert.match(renderer, /checkDesktopUpdate\(false\).*UPDATE_POLL_INTERVAL_MS/);
assert.match(renderer, /desktopUpdate\.notes/);
assert.ok(markup.indexOf('id="desktop-version"') < markup.indexOf('id="update-chip"'));
assert.match(markup, /id="update-chip"[^>]*>Update Available<\/button>/);
assert.match(markup, /id="update-release-notes"/);
assert.match(styles, /@keyframes update-chip-gradient/);
assert.match(styles, /prefers-reduced-motion: reduce[\s\S]*animation: none !important/);

console.log('updater helpers: PASS');
