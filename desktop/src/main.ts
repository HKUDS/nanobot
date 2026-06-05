import { spawn, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { createWriteStream, existsSync } from "node:fs";
import { mkdir, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { pathToFileURL } from "node:url";

import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  net as electronNet,
  protocol,
  session,
  shell,
} from "electron";
import type { IpcMainInvokeEvent, WebContents } from "electron";

import { UnixWebSocketClient } from "./unixWebSocket.js";
import {
  clearDesktopNotificationBadge,
  handleDesktopNotificationFrame,
} from "./notifications.js";

type EngineStatus = "starting" | "ready" | "restarting" | "stopped" | "crashed";

type HostRuntime = {
  configPath: string;
  gateway: ChildProcess;
  logsDir: string;
  python: string;
  secret: string;
  socketPath: string;
  status: EngineStatus;
  workspacePath: string;
};

let runtime: HostRuntime | null = null;
let mainWindow: BrowserWindow | null = null;
let crashRestartAttempts = 0;
let isQuitting = false;
const hostSockets = new Map<string, UnixWebSocketClient>();
const APP_PROTOCOL = "nanobot-app:";
const APP_HOST = "app";
const HOST_SOCKET_PROTOCOL = "nanobot-host:";
const HOST_SOCKET_HOST = "engine";
const SAFE_EXTERNAL_PROTOCOLS = new Set(["https:", "http:", "mailto:"]);
const GATEWAY_REQUEST_TIMEOUT_MS = 12_000;
const GATEWAY_REQUEST_RETRIES = 2;
const GATEWAY_RETRY_DELAY_MS = 80;

protocol.registerSchemesAsPrivileged([
  {
    scheme: "nanobot-app",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: false,
    },
  },
]);

function repoRoot(): string {
  return process.env.NANOBOT_DESKTOP_REPO_ROOT
    ? path.resolve(process.env.NANOBOT_DESKTOP_REPO_ROOT)
    : path.resolve(app.getAppPath(), "..");
}

function bundledResourcePath(name: string): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, name)
    : path.join(repoRoot(), "desktop", "resources", name);
}

function webDistPath(root: string): string {
  if (process.env.NANOBOT_DESKTOP_WEB_DIST) {
    return path.resolve(process.env.NANOBOT_DESKTOP_WEB_DIST);
  }
  const bundled = path.join(process.resourcesPath, "nanobot-webui");
  if (app.isPackaged && existsSync(path.join(bundled, "index.html"))) {
    return bundled;
  }
  return path.join(root, "nanobot", "web", "dist");
}

function webDevUrl(): string | null {
  const value = process.env.NANOBOT_DESKTOP_WEB_DEV_URL?.trim();
  return value ? value.replace(/\/+$/, "") : null;
}

function isTrustedAppUrl(rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl);
    return url.protocol === APP_PROTOCOL && url.host === APP_HOST;
  } catch {
    return false;
  }
}

function assertTrustedIpc(event: IpcMainInvokeEvent): void {
  const frameUrl = event.senderFrame?.url || event.sender.getURL();
  if (!isTrustedAppUrl(frameUrl)) {
    throw new Error("Blocked host API call from an untrusted renderer");
  }
}

function parseHostSocketUrl(rawUrl: unknown): string {
  if (typeof rawUrl !== "string") {
    throw new Error("Host socket URL must be a string");
  }
  const url = new URL(rawUrl);
  if (url.protocol !== HOST_SOCKET_PROTOCOL || url.host !== HOST_SOCKET_HOST) {
    throw new Error("Host socket URL is not allowed");
  }
  if (url.username || url.password) {
    throw new Error("Host socket URL credentials are not allowed");
  }
  return url.toString();
}

function openExternalIfSafe(rawUrl: string): void {
  try {
    const url = new URL(rawUrl);
    if (SAFE_EXTERNAL_PROTOCOLS.has(url.protocol)) {
      void shell.openExternal(url.toString());
    }
  } catch {
    // Ignore malformed or unsupported external URLs.
  }
}

function desktopContentSecurityPolicy(devUrl: string | null): string {
  const connectSrc = ["'self'", "nanobot-host:"];
  if (devUrl) {
    const url = new URL(devUrl);
    connectSrc.push(url.origin, url.origin.replace(/^http/, "ws"));
  }
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'none'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https: nanobot-app:",
    "font-src 'self' data:",
    "media-src 'self' data: blob:",
    "worker-src 'self' blob:",
    `connect-src ${connectSrc.join(" ")}`,
  ].join("; ");
}

function withSecurityHeaders(response: Response, devUrl: string | null): Response {
  const headers = new Headers(response.headers);
  headers.set("Content-Security-Policy", desktopContentSecurityPolicy(devUrl));
  headers.set("X-Content-Type-Options", "nosniff");
  if (devUrl) {
    headers.set("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    headers.set("Pragma", "no-cache");
    headers.set("Expires", "0");
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function handleHostIpc(
  channel: string,
  handler: (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown | Promise<unknown>,
): void {
  ipcMain.handle(channel, async (event, ...args) => {
    assertTrustedIpc(event);
    return await handler(event, ...args);
  });
}

function userDataPath(name: string): string {
  return path.join(app.getPath("userData"), name);
}

function engineSocketPath(): string {
  return userDataPath("engine.sock");
}

function pythonExecutable(): string {
  if (process.env.NANOBOT_DESKTOP_PYTHON) {
    return path.resolve(process.env.NANOBOT_DESKTOP_PYTHON);
  }
  const bundled = path.join(bundledResourcePath("nanobot-engine"), "bin", "python3");
  if (existsSync(bundled)) return bundled;
  return "python3";
}

function engineCwd(root: string): string {
  return app.isPackaged ? app.getPath("userData") : root;
}

function engineEnv(root: string): NodeJS.ProcessEnv {
  if (app.isPackaged) {
    return { ...process.env };
  }
  return {
    ...process.env,
    PYTHONPATH: [root, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  };
}

async function ensureAppDirs(): Promise<{
  configPath: string;
  logsDir: string;
  workspacePath: string;
}> {
  const dataDir = app.getPath("userData");
  const logsDir = userDataPath("logs");
  const workspacePath = userDataPath("workspace");
  await Promise.all([
    mkdir(dataDir, { recursive: true }),
    mkdir(logsDir, { recursive: true }),
    mkdir(workspacePath, { recursive: true }),
  ]);
  return {
    configPath: userDataPath("config.json"),
    logsDir,
    workspacePath,
  };
}

function appendGatewayLogs(gateway: ChildProcess, logsDir: string): void {
  const logPath = path.join(logsDir, "engine.log");
  const stream = createWriteStream(logPath, { flags: "a" });
  gateway.stdout?.on("data", (chunk) => {
    stream.write(chunk);
    process.stdout.write(`[nanobot] ${chunk}`);
  });
  gateway.stderr?.on("data", (chunk) => {
    stream.write(chunk);
    process.stderr.write(`[nanobot] ${chunk}`);
  });
  gateway.once("exit", (code, signal) => {
    stream.write(`\n[nanobot] engine exited code=${code ?? ""} signal=${signal ?? ""}\n`);
    stream.end();
  });
}

function notifyRuntimeStatus(status: EngineStatus): void {
  if (runtime) runtime.status = status;
  sendToRenderer(mainWindow?.webContents, "nanobot:runtime-status", status);
}

function sendToRenderer(
  sender: WebContents | null | undefined,
  channel: string,
  payload: unknown,
): void {
  if (!sender || sender.isDestroyed()) return;
  sender.send(channel, payload);
}

function closeHostSockets(): void {
  for (const [id, socket] of hostSockets) {
    socket.close();
    hostSockets.delete(id);
  }
}

async function fetchGateway(
  current: HostRuntime,
  requestPath: string,
  init: {
    body?: ArrayBuffer;
    headers?: Headers | Record<string, string>;
    method: string;
  },
): Promise<Response> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= GATEWAY_REQUEST_RETRIES; attempt += 1) {
    try {
      return await fetchGatewayOnce(current, requestPath, init);
    } catch (error) {
      lastError = error;
      if (!isTransientGatewayError(error) || attempt >= GATEWAY_REQUEST_RETRIES) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, GATEWAY_RETRY_DELAY_MS));
    }
  }
  throw lastError instanceof Error ? lastError : new Error("gateway request failed");
}

async function fetchGatewayOnce(
  current: HostRuntime,
  requestPath: string,
  init: {
    body?: ArrayBuffer;
    headers?: Headers | Record<string, string>;
    method: string;
  },
): Promise<Response> {
  const body = init.body ? Buffer.from(init.body) : undefined;
  const headers: http.OutgoingHttpHeaders = {};
  if (init.headers instanceof Headers) {
    init.headers.forEach((value, key) => {
      headers[key] = value;
    });
  } else {
    for (const [key, value] of Object.entries(init.headers ?? {})) {
      headers[key] = value;
    }
  }
  if (body) headers["content-length"] = String(body.length);

  return await new Promise<Response>((resolve, reject) => {
    let settled = false;
    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      reject(error);
    };
    const req = http.request(
      {
        socketPath: current.socketPath,
        path: requestPath,
        method: init.method,
        headers,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk: Buffer) => chunks.push(chunk));
        res.on("end", () => {
          if (settled) return;
          settled = true;
          const responseHeaders = new Headers();
          for (const [key, value] of Object.entries(res.headers)) {
            if (Array.isArray(value)) {
              for (const item of value) responseHeaders.append(key, item);
            } else if (value !== undefined) {
              responseHeaders.set(key, String(value));
            }
          }
          resolve(
            new Response(Buffer.concat(chunks), {
              status: res.statusCode ?? 500,
              statusText: res.statusMessage,
              headers: responseHeaders,
            }),
          );
        });
      },
    );
    req.setTimeout(GATEWAY_REQUEST_TIMEOUT_MS, () => {
      req.destroy(new Error(`gateway request timed out after ${GATEWAY_REQUEST_TIMEOUT_MS}ms`));
    });
    req.on("error", fail);
    if (body) req.write(body);
    req.end();
  });
}

function isTransientGatewayError(error: unknown): boolean {
  const code = typeof error === "object" && error !== null
    ? (error as { code?: unknown }).code
    : undefined;
  if (
    code === "ECONNRESET" ||
    code === "ECONNREFUSED" ||
    code === "EPIPE" ||
    code === "ETIMEDOUT"
  ) {
    return true;
  }
  const message = error instanceof Error ? error.message : "";
  return message.includes("socket hang up") || message.includes("timed out");
}

async function startGateway(): Promise<HostRuntime> {
  const root = repoRoot();
  const dirs = await ensureAppDirs();
  const socketPath = engineSocketPath();
  await rm(socketPath, { force: true });
  const secret = randomBytes(32).toString("base64url");
  const python = pythonExecutable();
  const args = [
    "-m",
    "nanobot",
    "desktop-gateway",
    "--config",
    dirs.configPath,
    "--workspace",
    dirs.workspacePath,
    "--webui-socket",
    socketPath,
    "--token-issue-secret",
    secret,
  ];
  const gateway = spawn(python, args, {
    cwd: engineCwd(root),
    env: engineEnv(root),
    stdio: ["ignore", "pipe", "pipe"],
  });
  appendGatewayLogs(gateway, dirs.logsDir);
  gateway.once("exit", () => scheduleCrashRestart(gateway));
  return {
    configPath: dirs.configPath,
    gateway,
    logsDir: dirs.logsDir,
    python,
    secret,
    socketPath,
    status: "starting",
    workspacePath: dirs.workspacePath,
  };
}

async function bootstrapFromGateway(current: HostRuntime): Promise<Record<string, unknown>> {
  const response = await fetchGateway(current, "/webui/bootstrap", {
    method: "GET",
    headers: {
      "X-Nanobot-Auth": current.secret,
    },
  });
  if (!response.ok) {
    throw new Error(`engine bootstrap failed: HTTP ${response.status}`);
  }
  return await response.json() as Record<string, unknown>;
}

async function waitForGateway(current: HostRuntime): Promise<void> {
  let lastError: unknown;
  for (let attempt = 0; attempt < 160; attempt += 1) {
    if (current.gateway.exitCode !== null) {
      throw new Error(`engine gateway exited with code ${current.gateway.exitCode}`);
    }
    try {
      await bootstrapFromGateway(current);
      crashRestartAttempts = 0;
      notifyRuntimeStatus("ready");
      return;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  throw lastError instanceof Error ? lastError : new Error("engine gateway did not become ready");
}

async function stopGateway(current: HostRuntime | null): Promise<void> {
  if (!current || current.gateway.exitCode !== null) return;
  current.status = "stopped";
  closeHostSockets();
  current.gateway.kill("SIGTERM");
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      if (current.gateway.exitCode === null) current.gateway.kill("SIGKILL");
      resolve();
    }, 2500);
    current.gateway.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function startRuntime(): Promise<void> {
  notifyRuntimeStatus("starting");
  runtime = await startGateway();
  await waitForGateway(runtime);
}

async function restartRuntime(): Promise<void> {
  const previous = runtime;
  notifyRuntimeStatus("restarting");
  await stopGateway(previous);
  await startRuntime();
}

function scheduleCrashRestart(gateway: ChildProcess): void {
  if (runtime?.gateway !== gateway || runtime.status === "restarting" || runtime.status === "stopped") {
    return;
  }
  notifyRuntimeStatus("crashed");
  if (crashRestartAttempts >= 3) return;
  crashRestartAttempts += 1;
  setTimeout(() => {
    if (runtime?.gateway !== gateway || runtime.status === "stopped") return;
    void startRuntime().catch((error) => {
      console.error("failed to restart nanobot engine", error);
      notifyRuntimeStatus("crashed");
    });
  }, 1000);
}

async function proxyToGateway(request: Request): Promise<Response> {
  if (!runtime) {
    return new Response("Engine unavailable", { status: 503 });
  }
  const requestUrl = new URL(request.url);
  const headers = new Headers(request.headers);
  headers.delete("host");
  if (requestUrl.pathname === "/webui/bootstrap") {
    headers.set("X-Nanobot-Auth", runtime.secret);
  }
  const init: {
    body?: ArrayBuffer;
    headers: Headers;
    method: string;
  } = {
    method: request.method,
    headers,
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }
  let response: Response;
  try {
    response = await fetchGateway(
      runtime,
      `${requestUrl.pathname}${requestUrl.search}`,
      init,
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`gateway proxy request failed: ${message}`);
    return new Response("Engine unavailable", { status: 503 });
  }
  if (requestUrl.pathname !== "/webui/bootstrap" || !response.ok) {
    return response;
  }
  const body = await response.json() as Record<string, unknown>;
  const wsPath = typeof body.ws_path === "string" ? body.ws_path : "/";
  const normalizedWsPath = wsPath.startsWith("/") ? wsPath : `/${wsPath}`;
  return Response.json({
    ...body,
    ws_url: `nanobot-host://engine${normalizedWsPath}`,
    runtime_surface: "native",
  });
}

function resolveStaticAsset(webDist: string, requestUrl: string): string | null {
  const url = new URL(requestUrl);
  const rawPath = decodeURIComponent(url.pathname);
  const relativePath = rawPath === "/" ? "index.html" : rawPath.replace(/^\/+/, "");
  const resolved = path.resolve(webDist, relativePath);
  if (resolved !== webDist && !resolved.startsWith(`${webDist}${path.sep}`)) {
    return null;
  }
  if (existsSync(resolved)) return resolved;
  if (!path.extname(relativePath)) return path.join(webDist, "index.html");
  return null;
}

function registerAppProtocol(webDist: string, devUrl: string | null): void {
  protocol.handle("nanobot-app", async (request) => {
    if (!isTrustedAppUrl(request.url)) {
      return new Response("Forbidden", { status: 403 });
    }
    const requestUrl = new URL(request.url);
    if (
      requestUrl.pathname === "/webui/bootstrap"
      || requestUrl.pathname.startsWith("/api/")
    ) {
      return proxyToGateway(request);
    }

    if (devUrl) {
      const upstream = new URL(
        `${requestUrl.pathname}${requestUrl.search}`,
        devUrl,
      );
      const response = await electronNet.fetch(upstream.toString());
      return withSecurityHeaders(response, devUrl);
    }

    const assetPath = resolveStaticAsset(webDist, request.url);
    if (!assetPath) {
      return new Response("Not Found", { status: 404 });
    }
    const response = await electronNet.fetch(pathToFileURL(assetPath).toString());
    return withSecurityHeaders(response, devUrl);
  });
}

function createWindow(): BrowserWindow {
  const preload = path.join(app.getAppPath(), "build", "preload.cjs");
  const win = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 920,
    minHeight: 640,
    title: "nanobot",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 14, y: 16 },
    backgroundColor: process.platform === "darwin" ? "#00000000" : "#ffffff",
    transparent: process.platform === "darwin",
    ...(process.platform === "darwin"
      ? {
          vibrancy: "sidebar" as const,
          visualEffectState: "active" as const,
        }
      : {}),
    show: false,
    webPreferences: {
      preload,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });

  win.once("ready-to-show", () => win.show());
  win.on("focus", clearDesktopNotificationBadge);
  win.on("close", (event) => {
    if (process.platform !== "darwin" || isQuitting) return;
    event.preventDefault();
    win.hide();
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternalIfSafe(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (!isTrustedAppUrl(url)) {
      event.preventDefault();
      openExternalIfSafe(url);
    }
  });
  win.webContents.on("preload-error", (_event, preloadPath, error) => {
    console.error(`Preload failed: ${preloadPath}`, error);
  });
  win.on("closed", () => {
    if (mainWindow === win) mainWindow = null;
    closeHostSockets();
  });
  return win;
}

function runtimeInfo() {
  return {
    surface: "native" as const,
    app_version: app.getVersion(),
    engine_status: runtime?.status ?? "stopped",
    data_dir: app.getPath("userData"),
    logs_dir: runtime?.logsDir ?? userDataPath("logs"),
    config_path: runtime?.configPath ?? userDataPath("config.json"),
    workspace_path: runtime?.workspacePath ?? userDataPath("workspace"),
    python: runtime?.python ?? pythonExecutable(),
    engine_transport: "unix_socket",
  };
}

function registerIpcHandlers(): void {
  handleHostIpc("nanobot:get-runtime-info", () => runtimeInfo());
  handleHostIpc("nanobot:restart-engine", async () => {
    await restartRuntime();
  });
  handleHostIpc("nanobot:pick-folder", async () => {
    const result = await dialog.showOpenDialog({
      properties: ["openDirectory", "createDirectory"],
    });
    if (result.canceled || !result.filePaths[0]) return null;
    return path.resolve(result.filePaths[0]);
  });
  handleHostIpc("nanobot:open-logs", async () => {
    const logsDir = runtime?.logsDir ?? userDataPath("logs");
    await mkdir(logsDir, { recursive: true });
    const error = await shell.openPath(logsDir);
    if (error) throw new Error(error);
  });
  handleHostIpc("nanobot:export-diagnostics", async () => {
    const diagnosticsPath = path.join(
      app.getPath("temp"),
      `nanobot-diagnostics-${Date.now()}.json`,
    );
    await writeFile(
      diagnosticsPath,
      JSON.stringify(runtimeInfo(), null, 2),
      "utf8",
    );
    shell.showItemInFolder(diagnosticsPath);
    return diagnosticsPath;
  });
  handleHostIpc("nanobot:check-for-updates", () => ({
    supported: false,
    message: "Auto update is not configured for this build.",
  }));
  handleHostIpc("nanobot:ws-connect", (event, rawUrl) => {
    if (!runtime) throw new Error("nanobot engine is not running");
    const url = parseHostSocketUrl(rawUrl);
    const id = randomBytes(12).toString("hex");
    const client = new UnixWebSocketClient(runtime.socketPath, url, {
      onOpen: () => sendToRenderer(event.sender, "nanobot:ws-event", { id, type: "open" }),
      onMessage: (data) => {
        handleDesktopNotificationFrame(data, { getWindow: () => mainWindow });
        sendToRenderer(event.sender, "nanobot:ws-event", { id, type: "message", data });
      },
      onError: (message) => sendToRenderer(event.sender, "nanobot:ws-event", { id, type: "error", message }),
      onClose: (code, reason) => {
        hostSockets.delete(id);
        sendToRenderer(event.sender, "nanobot:ws-event", { id, type: "close", code, reason });
      },
    });
    hostSockets.set(id, client);
    client.connect();
    event.sender.once("destroyed", () => {
      client.close();
      hostSockets.delete(id);
    });
    return id;
  });
  handleHostIpc("nanobot:ws-send", (_event, id, data) => {
    if (typeof id !== "string" || typeof data !== "string") {
      throw new Error("Invalid host socket send arguments");
    }
    const socket = hostSockets.get(id);
    if (!socket) throw new Error("Host socket not found");
    socket.send(data);
  });
  handleHostIpc("nanobot:ws-close", (_event, id) => {
    if (typeof id !== "string") {
      throw new Error("Invalid host socket close argument");
    }
    hostSockets.get(id)?.close();
    hostSockets.delete(id);
  });
}

async function loadAppWindow(win: BrowserWindow): Promise<void> {
  if (!runtime || runtime.status === "stopped" || runtime.status === "crashed") {
    await startRuntime();
  }
  await win.loadURL("nanobot-app://app/index.html");
}

app.whenReady().then(async () => {
  const root = repoRoot();
  const webDist = webDistPath(root);
  const devUrl = webDevUrl();
  if (!devUrl && !existsSync(path.join(webDist, "index.html"))) {
    throw new Error(`WebUI dist not found at ${webDist}. Run npm run build:webui first.`);
  }
  if (devUrl) {
    await session.defaultSession.clearCache();
  }

  registerIpcHandlers();
  registerAppProtocol(webDist, devUrl);

  mainWindow = createWindow();
  await loadAppWindow(mainWindow);

  app.on("activate", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.focus();
      return;
    }
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createWindow();
      void loadAppWindow(mainWindow);
    }
  });
}).catch((error) => {
  console.error(error);
  app.quit();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  isQuitting = true;
  if (runtime) runtime.status = "stopped";
  if (runtime?.gateway.exitCode === null) {
    runtime.gateway.kill("SIGTERM");
  }
});
