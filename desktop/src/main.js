const { app, BrowserWindow, dialog, shell } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const CHAT_URL = "http://localhost:5173/chat";
const HEALTH_URL = "http://localhost:5173/health";
const STARTUP_TIMEOUT_MS = 180_000;

let mainWindow = null;
let startupProcess = null;
let isQuitting = false;

app.setName("Vivi");
app.setPath("userData", path.join(app.getPath("appData"), "Vivi"));

function runtimeTemplateDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "runtime-template");
  }
  return path.resolve(__dirname, "..", "..");
}

function runtimeDir() {
  if (app.isPackaged) {
    return path.join(app.getPath("userData"), "runtime");
  }
  return path.resolve(__dirname, "..", "..");
}

function copyRecursive(src, dest) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
    return;
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function removeIfExists(target) {
  if (fs.existsSync(target)) {
    fs.rmSync(target, { recursive: true, force: true });
  }
}

function syncRuntimeTemplate() {
  const src = runtimeTemplateDir();
  const dest = runtimeDir();

  if (!app.isPackaged) {
    return dest;
  }

  fs.mkdirSync(dest, { recursive: true });

  const replaceEntries = [
    "app",
    "frontend",
    "scripts",
    "docker-compose.yml",
    "Dockerfile.api",
    "requirements-docker.txt",
    ".dockerignore",
    ".env.example"
  ];

  for (const entry of replaceEntries) {
    removeIfExists(path.join(dest, entry));
    copyRecursive(path.join(src, entry), path.join(dest, entry));
  }

  return dest;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    title: "Vivi",
    backgroundColor: "#080908",
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true
    }
  });

  mainWindow.loadURL(
    "data:text/html;charset=utf-8," +
      encodeURIComponent(`
        <!doctype html>
        <html lang="zh-CN">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>Vivi</title>
            <style>
              html,body{margin:0;width:100%;height:100%;background:#080908;color:#f4f0e8;font-family:Inter,Segoe UI,Arial,sans-serif}
              main{height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:16px;text-align:center}
              .mark{width:44px;height:44px;border-radius:8px;border:1px solid rgba(215,183,106,.5);display:flex;align-items:center;justify-content:center;color:#d7b76a;font-weight:800;font-size:24px}
              .title{font-size:20px;font-weight:720}
              .hint{max-width:560px;color:#cfc8bc;line-height:1.5}
            </style>
          </head>
          <body>
            <main>
              <div class="mark">V</div>
              <div class="title">正在启动 Vivi</div>
              <div class="hint">正在检查 Docker Desktop 并启动本地服务，首次启动可能需要构建镜像。</div>
            </main>
          </body>
        </html>
      `)
  );

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith("http://localhost:5173/") && !url.startsWith("data:text/html")) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function runPowerShell(scriptPath, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", scriptPath, ...args],
      {
        cwd,
        env: {
          ...process.env,
          COMPOSE_PROJECT_NAME: "her"
        },
        windowsHide: true
      }
    );
    startupProcess = child;

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data) => {
      stdout += data.toString();
    });
    child.stderr.on("data", (data) => {
      stderr += data.toString();
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      startupProcess = null;
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(new Error(stderr || stdout || `PowerShell exited with code ${code}`));
      }
    });
  });
}

function execDocker(args, cwd) {
  return new Promise((resolve) => {
    execFile(
      "docker",
      args,
      {
        cwd,
        env: {
          ...process.env,
          COMPOSE_PROJECT_NAME: "her"
        },
        windowsHide: true
      },
      (error, stdout, stderr) => {
        resolve({ ok: !error, stdout, stderr, error });
      }
    );
  });
}

async function shouldBuildImages(cwd) {
  const versionFile = path.join(cwd, ".vivi-desktop-version");
  if (app.isPackaged) {
    const previousVersion = fs.existsSync(versionFile) ? fs.readFileSync(versionFile, "utf8").trim() : "";
    if (previousVersion !== app.getVersion()) {
      return true;
    }
  }

  const api = await execDocker(["image", "ls", "her-api", "--format", "{{.Repository}}:{{.Tag}}"], cwd);
  const web = await execDocker(["image", "ls", "her-web", "--format", "{{.Repository}}:{{.Tag}}"], cwd);
  return !api.ok || !web.ok || !api.stdout.trim() || !web.stdout.trim();
}

function writeRuntimeVersion(cwd) {
  if (app.isPackaged) {
    fs.writeFileSync(path.join(cwd, ".vivi-desktop-version"), app.getVersion(), "utf8");
  }
}

async function waitForHealth(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      const response = await fetch(HEALTH_URL, { signal: controller.signal });
      clearTimeout(timer);
      if (response.ok) {
        const payload = await response.json();
        if (payload.status === "ok") {
          return payload;
        }
      }
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
  throw new Error("Vivi API did not become ready within 180 seconds.");
}

async function showStartupError(error) {
  const detail = error && error.message ? error.message : String(error);
  if (mainWindow) {
    await dialog.showMessageBox(mainWindow, {
      type: "error",
      title: "Vivi 启动失败",
      message: "Vivi 启动失败",
      detail:
        "请确认 Docker Desktop 已安装并处于运行状态，然后重新打开 Vivi。\n\n" +
        detail.slice(0, 3000)
    });
  }
  app.quit();
}

async function startVivi() {
  try {
    const cwd = syncRuntimeTemplate();
    const script = path.join(cwd, "scripts", "launch_desktop.ps1");
    const args = ["-NoOpen"];
    if (await shouldBuildImages(cwd)) {
      args.push("-Build");
    }
    await runPowerShell(script, args, cwd);
    writeRuntimeVersion(cwd);
    await waitForHealth(STARTUP_TIMEOUT_MS);
    if (mainWindow) {
      await mainWindow.loadURL(CHAT_URL);
    }
  } catch (error) {
    await showStartupError(error);
  }
}

async function stopVivi() {
  if (startupProcess) {
    startupProcess.kill();
  }
  const cwd = runtimeDir();
  const script = path.join(cwd, "scripts", "stop_desktop.ps1");
  if (!fs.existsSync(script)) {
    return;
  }
  try {
    await runPowerShell(script, [], cwd);
  } catch {
    // Best-effort shutdown. Avoid blocking app exit on Docker cleanup failures.
  }
}

const lock = app.requestSingleInstanceLock();
if (!lock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    createWindow();
    startVivi();
  });

  app.on("before-quit", async (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    isQuitting = true;
    await stopVivi();
    app.quit();
  });

  app.on("window-all-closed", () => {
    app.quit();
  });
}
