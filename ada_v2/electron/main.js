const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

// Apply platform-specific GPU flags
if (process.platform === 'win32') {
    // Use ANGLE D3D11 backend on Windows - fixes "GPU state invalid after WaitForGetOffsetInRange"
    app.commandLine.appendSwitch('use-angle', 'd3d11');
    app.commandLine.appendSwitch('enable-features', 'Vulkan');
}
app.commandLine.appendSwitch('ignore-gpu-blocklist');

let mainWindow;
let pythonProcess;

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1920,
        height: 1080,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false, // For simple IPC/Socket.IO usage
        },
        backgroundColor: '#000000',
        frame: false, // Frameless for custom UI
        titleBarStyle: 'hidden',
        show: false, // Don't show until ready
    });

    // In dev, load Vite server. In prod, load index.html
    const isDev = !app.isPackaged && process.env.NODE_ENV !== 'production';

    const loadFrontend = (retries = 3) => {
        const url = isDev ? 'http://localhost:5173' : null;
        const loadPromise = isDev
            ? mainWindow.loadURL(url)
            : mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));

        loadPromise
            .then(() => {
                console.log('Frontend loaded successfully!');
                windowWasShown = true;
                mainWindow.show();
                if (isDev) {
                    mainWindow.webContents.openDevTools();
                }
            })
            .catch((err) => {
                console.error(`Failed to load frontend: ${err.message}`);
                if (retries > 0) {
                    console.log(`Retrying in 1 second... (${retries} retries left)`);
                    setTimeout(() => loadFrontend(retries - 1), 1000);
                } else {
                    console.error('Failed to load frontend after all retries. Keeping window open.');
                    windowWasShown = true;
                    mainWindow.show(); // Show anyway so user sees something
                }
            });
    };

    loadFrontend();

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

function startPythonBackend() {
    const fs = require('fs');
    const projectRoot = path.join(__dirname, '..');
    const isDev = !app.isPackaged && process.env.NODE_ENV !== 'production';

    let pythonExe, args, cwd;

    // Build environment variables
    const env = { ...process.env };

    if (!isDev) {
        // Production: PyInstaller COLLECT output is a folder named 'jarvis_server'
        const resourcesPath = process.resourcesPath;
        const binaryName = process.platform === 'win32' ? 'jarvis_server.exe' : 'jarvis_server';
        const bundledBin = path.join(resourcesPath, 'backend', 'jarvis_server', binaryName);

        if (fs.existsSync(bundledBin)) {
            pythonExe = bundledBin;
            args = [];
            cwd = path.join(resourcesPath, 'backend', 'jarvis_server');
            console.log(`[JARVIS] Starting bundled backend: ${bundledBin}`);
        } else {
            console.warn(`[JARVIS] Bundled binary not found at: ${bundledBin}. Falling back to script.`);
            const scriptPath = path.join(resourcesPath, 'backend', 'server.py');
            pythonExe = process.platform === 'win32' ? 'python' : 'python3';
            args = [scriptPath];
            cwd = path.join(resourcesPath, 'backend');
        }

        // Production: set Playwright browsers path to bundled location
        const playwrightBrowsersPath = path.join(resourcesPath, 'backend', 'jarvis_server', '_internal', 'playwright-browsers');
        if (fs.existsSync(playwrightBrowsersPath)) {
            env.PLAYWRIGHT_BROWSERS_PATH = playwrightBrowsersPath;
            console.log(`[JARVIS] Playwright browsers: ${playwrightBrowsersPath}`);
        }

        // Production: set library path to bundled libs (fixes broken system libexpat on macOS)
        if (process.platform === 'darwin') {
            const libDir = path.join(resourcesPath, 'backend', 'jarvis_server');
            env.DYLD_LIBRARY_PATH = libDir;
        } else if (process.platform === 'win32') {
            const libDir = path.join(resourcesPath, 'backend', 'jarvis_server');
            env.PATH = libDir + ';' + (env.PATH || '');
        }
    } else {
        // Dev: use venv python
        const scriptPath = path.join(projectRoot, 'backend', 'server.py');
        const venvPython = path.join(projectRoot, '.venv', 'bin', 'python3');
        pythonExe = fs.existsSync(venvPython)
            ? venvPython
            : (process.platform === 'win32' ? 'python' : 'python3');
        args = [scriptPath];
        cwd = path.join(projectRoot, 'backend');
        console.log(`[JARVIS] Dev mode: ${pythonExe} ${scriptPath}`);

        // Dev: macOS libexpat fix for Homebrew Python
        if (process.platform === 'darwin') {
            env.DYLD_LIBRARY_PATH = '/opt/homebrew/opt/expat/lib';
        }
    }

    // userData dir is always writable (outside the .app bundle on macOS)
    const { app: electronApp } = require('electron');
    const userDataPath = electronApp.getPath('userData');
    env.JARVIS_USERDATA = userDataPath;

    pythonProcess = spawn(pythonExe, args, { cwd, env });

    const safeWrite = (stream, data) => {
        try {
            if (stream.writable && !stream.destroyed) {
                stream.write(data, (err) => { if (err) {} });
            }
        } catch (e) {}
    };

    process.stdout.on('error', () => {});
    process.stderr.on('error', () => {});

    pythonProcess.stdout.on('data', (data) => {
        safeWrite(process.stdout, `[JARVIS Backend] ${data}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        safeWrite(process.stderr, `[JARVIS Backend ERR] ${data}`);
    });

    pythonProcess.on('exit', (code, signal) => {
        console.log(`[JARVIS] Backend exited: code=${code} signal=${signal}`);
    });
}

app.whenReady().then(() => {
    ipcMain.on('window-minimize', () => {
        if (mainWindow) mainWindow.minimize();
    });

    ipcMain.on('window-maximize', () => {
        if (mainWindow) {
            if (mainWindow.isMaximized()) {
                mainWindow.unmaximize();
            } else {
                mainWindow.maximize();
            }
        }
    });

    ipcMain.on('window-close', () => {
        if (mainWindow) mainWindow.close();
    });

    checkBackendPort(8000).then((isTaken) => {
        if (isTaken) {
            console.log('Port 8000 is taken. Assuming backend is already running manually.');
            waitForBackend().then(createWindow);
        } else {
            startPythonBackend();
            // Give it a moment to start, then wait for health check
            setTimeout(() => {
                waitForBackend().then(createWindow);
            }, 1000);
        }
    });

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

function checkBackendPort(port) {
    return new Promise((resolve) => {
        const net = require('net');
        const server = net.createServer();
        server.once('error', (err) => {
            if (err.code === 'EADDRINUSE') {
                resolve(true);
            } else {
                resolve(false);
            }
        });
        server.once('listening', () => {
            server.close();
            resolve(false);
        });
        server.listen(port);
    });
}

function waitForBackend() {
    return new Promise((resolve) => {
        const check = () => {
            const http = require('http');
            http.get('http://127.0.0.1:8000/status', (res) => {
                if (res.statusCode === 200) {
                    console.log('Backend is ready!');
                    resolve();
                } else {
                    console.log('Backend not ready, retrying...');
                    setTimeout(check, 1000);
                }
            }).on('error', (err) => {
                console.log('Waiting for backend...');
                setTimeout(check, 1000);
            });
        };
        check();
    });
}

let windowWasShown = false;

app.on('window-all-closed', () => {
    // Only quit if the window was actually shown at least once
    // This prevents quitting during startup if window creation fails
    if (process.platform !== 'darwin' && windowWasShown) {
        app.quit();
    } else if (!windowWasShown) {
        console.log('Window was never shown - keeping app alive to allow retries');
    }
});

app.on('will-quit', () => {
    console.log('App closing... Killing Python backend.');
    if (pythonProcess) {
        if (process.platform === 'win32') {
            // Windows: Force kill the process tree synchronously
            try {
                const { execSync } = require('child_process');
                execSync(`taskkill /pid ${pythonProcess.pid} /f /t`);
            } catch (e) {
                console.error('Failed to kill python process:', e.message);
            }
        } else {
            // Unix: SIGKILL
            pythonProcess.kill('SIGKILL');
        }
        pythonProcess = null;
    }
});
