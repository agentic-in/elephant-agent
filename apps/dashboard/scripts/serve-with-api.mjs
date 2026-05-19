import { spawn } from "node:child_process";
import net from "node:net";
import { dirname, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDirectory, "..");
const repoRoot = resolve(dashboardRoot, "..", "..");
const viteBin = resolve(dashboardRoot, "node_modules", "vite", "bin", "vite.js");

const forwardedArgs = process.argv[2] === "dev" ? process.argv.slice(3) : process.argv.slice(2);
const apiHost = process.env.ELEPHANT_DASHBOARD_API_HOST ?? "127.0.0.1";
const requestedApiPort = Number.parseInt(process.env.ELEPHANT_DASHBOARD_API_PORT ?? "8000", 10);
const elephantHome = process.env.ELEPHANT_HOME ?? `${process.env.HOME}/.elephant`;
const cliStateDir = process.env.ELEPHANT_HERD_DIR ?? resolve(elephantHome, "herd");
const apiDatabase = process.env.ELEPHANT_DASHBOARD_API_DATABASE ?? resolve(cliStateDir, "elephant.sqlite3");
const explicitApiBase = (process.env.VITE_ELEPHANT_API_BASE_URL ?? "").trim().replace(/\/$/, "");
const autoStartApi = process.env.ELEPHANT_DASHBOARD_API_AUTO_START !== "0" && !explicitApiBase;
const HEALTH_REQUEST_TIMEOUT_MS = 650;
const API_HEALTH_READY_TIMEOUT_MS = 6_000;
const OPERATOR_CONSOLE_REQUEST_TIMEOUT_MS = parsePositiveIntegerEnv(
  "ELEPHANT_DASHBOARD_CONSOLE_REQUEST_TIMEOUT_MS",
  30_000,
);
const OPERATOR_CONSOLE_READY_TIMEOUT_MS = parsePositiveIntegerEnv(
  "ELEPHANT_DASHBOARD_CONSOLE_READY_TIMEOUT_MS",
  45_000,
);

let apiProcess = null;
let shuttingDown = false;

function parsePositiveIntegerEnv(name, fallback) {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function log(message) {
  console.log(`[elephant-dashboard] ${message}`);
}

function portAcceptsConnection(host, port) {
  return new Promise((resolvePort) => {
    const socket = net.createConnection({ host, port });
    const finish = (result) => {
      socket.removeAllListeners();
      socket.destroy();
      resolvePort(result);
    };
    socket.setTimeout(350);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

async function findFreePort(host, startPort) {
  for (let port = startPort; port < startPort + 40; port += 1) {
    if (!(await portAcceptsConnection(host, port))) {
      return port;
    }
  }
  throw new Error(`Could not find a free API port near ${startPort}.`);
}

async function healthReady(apiBaseUrl) {
  try {
    const response = await fetch(`${apiBaseUrl}/healthz`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(HEALTH_REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      return false;
    }
    const payload = await response.json();
    return payload?.service === "elephant-api" && payload?.status === "ok";
  } catch {
    return false;
  }
}

async function dashboardReady(apiBaseUrl) {
  try {
    const response = await fetch(`${apiBaseUrl}/v1/internal/dashboard/overview`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(OPERATOR_CONSOLE_REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      return false;
    }
    const payload = await response.json();
    return Boolean(payload?.dashboard?.meta);
  } catch {
    return false;
  }
}

async function waitForHealth(apiBaseUrl) {
  const deadline = Date.now() + API_HEALTH_READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await healthReady(apiBaseUrl)) {
      return;
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 180));
  }
  throw new Error(`Elephant Agent API did not become ready at ${apiBaseUrl}.`);
}

async function waitForConsole(apiBaseUrl) {
  const deadline = Date.now() + OPERATOR_CONSOLE_READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await dashboardReady(apiBaseUrl)) {
      return;
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 250));
  }
  throw new Error(`Elephant Agent internal dashboard did not become ready at ${apiBaseUrl}.`);
}

function stopProcess(child) {
  if (!child || child.killed || child.exitCode !== null) {
    return;
  }
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    child.kill("SIGTERM");
  }
}

function shutdown(exitCode = 0) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  stopProcess(apiProcess);
  setTimeout(() => process.exit(exitCode), 80);
}

process.once("SIGINT", () => shutdown(0));
process.once("SIGTERM", () => shutdown(0));

async function resolveApiBaseUrl() {
  if (!autoStartApi) {
    return explicitApiBase || `http://${apiHost}:${requestedApiPort}`;
  }

  const requestedApiBase = `http://${apiHost}:${requestedApiPort}`;
  if ((await healthReady(requestedApiBase)) && (await dashboardReady(requestedApiBase))) {
    log(`reusing dashboard-ready API at ${requestedApiBase}`);
    return requestedApiBase;
  }

  const occupied = await portAcceptsConnection(apiHost, requestedApiPort);
  const apiPort = occupied ? await findFreePort(apiHost, requestedApiPort + 1) : requestedApiPort;
  const apiBaseUrl = `http://${apiHost}:${apiPort}`;
  if (occupied) {
    log(`port ${requestedApiPort} is occupied but not dashboard-ready; using ${apiBaseUrl}`);
  } else {
    log(`starting local API at ${apiBaseUrl}`);
  }

  apiProcess = spawn(
    process.env.PYTHON ?? "python3",
    [
      "-m",
      "apps.api",
      "--host",
      apiHost,
      "--port",
      String(apiPort),
      "--database",
      apiDatabase,
    ],
    {
      cwd: repoRoot,
      detached: true,
      stdio: "inherit",
    },
  );
  apiProcess.once("exit", (code, signal) => {
    if (!shuttingDown) {
      console.error(`[elephant-dashboard] API exited unexpectedly (${signal ?? code ?? "unknown"}).`);
      process.exit(code ?? 1);
    }
  });

  await waitForHealth(apiBaseUrl);
  await waitForConsole(apiBaseUrl);
  return apiBaseUrl;
}

async function main() {
  const apiBaseUrl = await resolveApiBaseUrl();
  const viteProcess = spawn(process.execPath, [viteBin, ...forwardedArgs], {
    cwd: dashboardRoot,
    env: {
      ...process.env,
      VITE_ELEPHANT_API_BASE_URL: apiBaseUrl,
    },
    stdio: "inherit",
  });

  viteProcess.once("exit", (code, signal) => {
    if (signal) {
      stopProcess(apiProcess);
      process.kill(process.pid, signal);
      return;
    }
    shutdown(code ?? 0);
  });
}

main().catch((error) => {
  console.error(`[elephant-dashboard] ${error instanceof Error ? error.message : String(error)}`);
  shutdown(1);
});
