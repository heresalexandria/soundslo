'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

module.exports = async function afterPack(context) {
  const resources = context.electronPlatformName === 'darwin'
    ? path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`, 'Contents', 'Resources')
    : path.join(context.appOutDir, 'resources');
  for (const relative of ['pyruntime/bin/python3', 'pyruntime/bin/python3.12']) {
    try { fs.chmodSync(path.join(resources, relative), 0o755); } catch (_) {}
  }
  if (context.electronPlatformName !== 'darwin') return;
  if (process.env.SOUNDSLO_ELECTRON_SIGN === 'true' || process.env.CSC_LINK) return;
  const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', appPath], { stdio: 'inherit' });
  execFileSync('codesign', ['--verify', '--verbose=2', appPath], { stdio: 'inherit' });
};
