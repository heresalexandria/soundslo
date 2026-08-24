'use strict';

const { contextBridge, ipcRenderer } = require('electron');

function launchArg(flag) {
  const hit = process.argv.find((value) => value.startsWith(`${flag}=`));
  return hit ? hit.slice(flag.length + 1) : '';
}

contextBridge.exposeInMainWorld('soundsloDesktop', {
  version: launchArg('--soundslo-version'),
  packaged: launchArg('--soundslo-packaged') === '1',
  smoke: launchArg('--soundslo-smoke') === '1',
  platform: process.platform,
  updateInfo: () => ipcRenderer.invoke('soundslo:update-info'),
  updateCheck: (options) => ipcRenderer.invoke('soundslo:update-check', options),
  updateDownload: () => ipcRenderer.invoke('soundslo:update-download'),
  updateCancel: () => ipcRenderer.invoke('soundslo:update-cancel'),
  updateInstall: () => ipcRenderer.invoke('soundslo:update-install'),
  updateReveal: () => ipcRenderer.invoke('soundslo:update-reveal'),
  onUpdateProgress: (callback) => {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on('soundslo:update-progress', listener);
    return () => ipcRenderer.removeListener('soundslo:update-progress', listener);
  },
});
