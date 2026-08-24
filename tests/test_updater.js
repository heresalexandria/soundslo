'use strict';

const assert = require('assert');
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

console.log('updater helpers: PASS');
