'use strict';

const { app, BrowserWindow, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const path = require('path');

const updater = require('./updater');

const REPO_ROOT = path.resolve(__dirname, '..');
const SA3_REVISION = 'a0b57f5483c4588f827f3552b7d5c6ca2a9687be';
const PACKAGED = app.isPackaged;
const SMOKE = process.argv.includes('--smoke');
const BACKEND = process.platform === 'darwin' && process.arch === 'arm64' ? 'mlx' : 'tflite';

if (SMOKE) {
  app.setPath('userData', path.join(app.getPath('temp'), 'soundslo-smoke'));
}

const USER_DATA = app.getPath('userData');
const PYTHON = process.env.SOUNDSLO_PYTHON || (PACKAGED
  ? path.join(process.resourcesPath, 'pyruntime', process.platform === 'win32' ? 'python.exe' : 'bin/python3')
  : path.join(REPO_ROOT, '.venv', 'bin', 'python'));
const RUNTIME_SOURCE = process.env.SOUNDSLO_SA3_ROOT || (PACKAGED
  ? path.join(process.resourcesPath, 'sa3-runtime')
  : path.join(REPO_ROOT, '.runtime', 'stable-audio-3'));
const RUNTIME_DIR = PACKAGED
  ? path.join(USER_DATA, 'runtime', SA3_REVISION)
  : RUNTIME_SOURCE;

let mainWindow = null;
let backendProcess = null;
let backendPort = null;
let quitting = false;

function ensurePackagedRuntime() {
  if (!PACKAGED) return;
  if (!fs.existsSync(RUNTIME_SOURCE)) {
    throw new Error(`Bundled Stable Audio runtime is missing at ${RUNTIME_SOURCE}`);
  }
  fs.mkdirSync(RUNTIME_DIR, { recursive: true });
  fs.cpSync(RUNTIME_SOURCE, RUNTIME_DIR, { recursive: true, force: true });
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

function backendEnv() {
  const dataDir = path.join(USER_DATA, 'data');
  const env = {
    ...process.env,
    SOUNDSLO_ROOT: PACKAGED ? process.resourcesPath : REPO_ROOT,
    SOUNDSLO_DATA_DIR: dataDir,
    SOUNDSLO_SA3_ROOT: RUNTIME_DIR,
    SOUNDSLO_BACKEND: BACKEND,
    SOUNDSLO_RUNTIME_PYTHON: PYTHON,
    SOUNDSLO_TFLITE_PRECISION: 'w16a32',
    HF_HOME: path.join(USER_DATA, 'huggingface'),
    PYTHONUNBUFFERED: '1',
  };
  if (PACKAGED) env.PYTHONDONTWRITEBYTECODE = '1';
  return env;
}

async function startBackend() {
  ensurePackagedRuntime();
  if (!fs.existsSync(PYTHON)) throw new Error(`Python runtime is missing at ${PYTHON}`);
  backendPort = await freePort();
  const logDir = path.join(USER_DATA, 'logs');
  fs.mkdirSync(logDir, { recursive: true });
  const log = fs.createWriteStream(path.join(logDir, 'backend.log'), { flags: 'a' });
  backendProcess = spawn(PYTHON, [
    '-m', 'uvicorn', 'soundslo.app:app',
    '--host', '127.0.0.1', '--port', String(backendPort), '--no-access-log',
  ], {
    cwd: PACKAGED ? process.resourcesPath : REPO_ROOT,
    env: backendEnv(),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  backendProcess.stdout.pipe(log, { end: false });
  backendProcess.stderr.pipe(log, { end: false });
  backendProcess.on('exit', (code) => {
    log.write(`\n[soundslo] backend exited ${code}\n`);
    if (!quitting && mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('soundslo:backend-exit', { code });
    }
  });
  backendProcess.on('error', (error) => log.write(`\n[soundslo] ${error.stack || error}\n`));
  await waitForBackend();
}

async function waitForBackend() {
  const deadline = Date.now() + 45000;
  let lastError = null;
  while (Date.now() < deadline) {
    if (backendProcess && backendProcess.exitCode !== null) {
      throw new Error(`Local service exited with code ${backendProcess.exitCode}`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${backendPort}/api/health`);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Local service did not start: ${lastError || 'timed out'}`);
}

async function installDefaultModel() {
  try {
    await fetch(`http://127.0.0.1:${backendPort}/api/models/stable-audio-3-medium/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
  } catch (_) {
    // The model manager shows the actionable error and offers a retry.
  }
}

function trustedExternal(raw) {
  let url;
  try { url = new URL(raw); } catch (_) { return false; }
  return url.protocol === 'https:' && [
    'github.com', 'huggingface.co', 'stability.ai', 'platform.stability.ai',
  ].includes(url.hostname);
}

async function createWindow({ show = true } = {}) {
  const icon = path.join(__dirname, 'build', 'icon.png');
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 900,
    minWidth: 920,
    minHeight: 680,
    title: 'Soundslo',
    backgroundColor: '#0c0c0b',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    icon,
    show,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: [
        `--soundslo-version=${app.getVersion()}`,
        `--soundslo-packaged=${PACKAGED ? '1' : '0'}`,
        `--soundslo-smoke=${SMOKE ? '1' : '0'}`,
      ],
    },
  });
  const localOrigin = `http://127.0.0.1:${backendPort}`;
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (trustedExternal(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(localOrigin)) event.preventDefault();
  });
  const loaded = new Promise((resolve, reject) => {
    mainWindow.webContents.once('did-finish-load', resolve);
    mainWindow.webContents.once('did-fail-load', (_event, code, description) => {
      reject(new Error(`renderer failed to load: ${code} ${description}`));
    });
  });
  await mainWindow.loadURL(localOrigin);
  await loaded;
  mainWindow.on('closed', () => { mainWindow = null; });
  return mainWindow;
}

async function runSmoke() {
  const response = await fetch(`http://127.0.0.1:${backendPort}/api/models`);
  if (!response.ok) throw new Error(`model catalog returned ${response.status}`);
  const payload = await response.json();
  const medium = payload.models.find((model) => model.id === 'stable-audio-3-medium');
  if (!medium || !medium.runtime_installed || medium.runtime_backend !== BACKEND) {
    throw new Error(`packaged ${BACKEND} runtime did not pass its model-catalog check`);
  }
  const smokeWindow = await createWindow({ show: false });
  const rendererReady = await smokeWindow.webContents.executeJavaScript(
    `new Promise((resolve) => {
      const deadline = Date.now() + 10000;
      const check = () => {
        const models = document.querySelectorAll('#model-grid .model-card').length;
        const presets = document.querySelectorAll('#duration-presets button').length;
        if (models === 3 && presets > 0) resolve(true);
        else if (Date.now() >= deadline) resolve(false);
        else setTimeout(check, 100);
      };
      check();
    })`
  );
  if (!rendererReady) throw new Error('renderer did not create its primary workbench controls');
  app.exit(0);
}

function stopBackend() {
  quitting = true;
  if (!backendProcess || backendProcess.exitCode !== null) return;
  if (process.platform === 'win32') {
    spawn('taskkill', ['/PID', String(backendProcess.pid), '/T', '/F'], {
      windowsHide: true,
      stdio: 'ignore',
    });
  } else {
    backendProcess.kill('SIGTERM');
  }
}

app.whenReady().then(async () => {
  try {
    await startBackend();
    if (SMOKE) {
      await runSmoke();
      return;
    }
    await installDefaultModel();
    await createWindow();
  } catch (error) {
    console.error(error.stack || error);
    app.exit(1);
  }
});

app.on('before-quit', stopBackend);
app.on('window-all-closed', () => app.quit());

ipcMain.handle('soundslo:update-info', () => updater.info());
ipcMain.handle('soundslo:update-check', (_event, options) => updater.check(options || {}));
ipcMain.handle('soundslo:update-download', (event) => updater.download(event.sender));
ipcMain.handle('soundslo:update-cancel', () => updater.cancelDownload());
ipcMain.handle('soundslo:update-install', () => updater.install());
ipcMain.handle('soundslo:update-reveal', () => {
  const file = updater.stagedFile();
  if (file) shell.showItemInFolder(file);
  return { file: Boolean(file) };
});
