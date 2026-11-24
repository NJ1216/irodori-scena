#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import process from "node:process";
import ports from "./ports.json" with { type: "json" };
import { once } from "node:events";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HEALTH_TIMEOUT_MS = 20_000;
const STOP_TIMEOUT_MS = 5_000;

export function serverOptions(argv) {
  const value = { apiPort: ports.browser.api, vitePort: ports.browser.vite, dataRoot: null };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--api-port") value.apiPort = Number(argv[++index]);
    else if (argv[index] === "--vite-port") value.vitePort = Number(argv[++index]);
    else if (argv[index] === "--data-root") value.dataRoot = argv[++index];
    else throw new Error(`未対応の引数です: ${argv[index]}`);
  }
  for (const [name, port] of Object.entries({ apiPort: value.apiPort, vitePort: value.vitePort })) {
    if (!Number.isInteger(port) || port < 1 || port > 65_535) throw new Error(`${name}が正しくありません。`);
  }
  if (value.dataRoot !== null && !value.dataRoot.trim()) throw new Error("dataRootが空です。");
  return value;
}

export function apiArguments(apiPort) {
  return ["run", "uvicorn", "server.app:app", "--port", String(apiPort)];
}

export function viteArguments(vitePort) {
  return ["--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"];
}

export function viteInvocation(vitePort, cli = fileURLToPath(new URL("../node_modules/vite/bin/vite.js", import.meta.url))) {
  // A package-manager wrapper can put Vite in a separate process group,
  // escaping Playwright teardown and keeping its inherited output pipes open.
  return [process.execPath, [cli, ...viteArguments(vitePort)]];
}

export function apiEnvironment(environment, dataRoot) {
  return {
    ...environment,
    UV_CACHE_DIR: environment.UV_CACHE_DIR ?? ".uv-cache",
    ...(dataRoot ? { SCENA_DATA_ROOT: dataRoot } : {}),
  };
}

function waitForExit(child) {
  return new Promise((resolve) => child.once("exit", (code, signal) => resolve({ code, signal })));
}

async function stopChild(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  const exited = waitForExit(child);
  child.kill("SIGTERM");
  let timeout;
  const timer = new Promise((resolve) => {
    timeout = setTimeout(resolve, STOP_TIMEOUT_MS, null);
  });
  const result = await Promise.race([exited, timer]);
  clearTimeout(timeout);
  if (result) return;
  child.kill("SIGKILL");
  await exited;
}

async function waitForHealth(child, apiPort) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (child.spawnError) throw child.spawnError;
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error("FastAPIがhealth確認前に終了しました。");
    }
    try {
      const response = await fetch(`http://127.0.0.1:${apiPort}/api/health`, {
        signal: AbortSignal.timeout(500),
      });
      if (response.ok) return;
    } catch {
      // The listener may not exist yet. Retry until the bounded deadline.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("FastAPIが20秒以内に起動しませんでした。");
}

async function run(argv) {
  const { apiPort, vitePort, dataRoot } = serverOptions(argv);
  const api = spawn("uv", apiArguments(apiPort), {
    stdio: "inherit",
    env: apiEnvironment(process.env, dataRoot),
  });
  api.spawnError = null;
  api.on("error", (error) => {
    api.spawnError = error;
  });
  let web;
  let shuttingDown = false;

  const shutdown = async (code) => {
    if (shuttingDown) return;
    shuttingDown = true;
    await stopChild(web);
    await stopChild(api);
    process.exitCode = code;
  };
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(signal, () => void shutdown(0));
  }

  try {
    await waitForHealth(api, apiPort);
    const [viteCommand, viteArgs] = viteInvocation(vitePort);
    web = spawn(viteCommand, viteArgs, {
      stdio: "inherit",
      env: { ...process.env, SCENA_API_TARGET: `http://127.0.0.1:${apiPort}` },
    });
    web.on("error", (error) => {
      console.error(`Viteを起動できませんでした: ${error.message}`);
      void shutdown(1);
    });
    api.once("exit", (code) => {
      if (!shuttingDown) {
        console.error("FastAPIが終了したためViteを停止します。");
        void shutdown(code ?? 1);
      }
    });
    web.once("exit", (code) => {
      if (!shuttingDown) {
        if (code) console.error("Viteがエラー終了したためFastAPIを停止します。");
        void shutdown(code ?? 0);
      }
    });
  } catch (error) {
    console.error(`開発サーバーを起動できませんでした: ${error.message}`);
    await shutdown(1);
  }
}

async function selfTest() {
  assert.deepEqual(serverOptions([]), { apiPort: 8787, vitePort: 5173, dataRoot: null });
  assert.deepEqual(serverOptions(["--api-port", "8788", "--vite-port", "5174"]), {
    apiPort: 8788,
    vitePort: 5174,
    dataRoot: null,
  });
  assert.deepEqual(serverOptions(["--data-root", ".test-temp/playwright-data"]), {
    apiPort: 8787,
    vitePort: 5173,
    dataRoot: ".test-temp/playwright-data",
  });
  assert.throws(() => serverOptions(["--data-root", ""]), /dataRoot/);
  assert.deepEqual(apiEnvironment({ PATH: "test" }, ".test-temp/playwright-data"), {
    PATH: "test",
    UV_CACHE_DIR: ".uv-cache",
    SCENA_DATA_ROOT: ".test-temp/playwright-data",
  });
  assert.equal(apiEnvironment({ SCENA_DATA_ROOT: "real" }, null).SCENA_DATA_ROOT, "real");
  assert.deepEqual(apiArguments(8788), ["run", "uvicorn", "server.app:app", "--port", "8788"]);
  assert.deepEqual(viteArguments(5174), ["--host", "127.0.0.1", "--port", "5174", "--strictPort"]);
  const cli = fileURLToPath(new URL("../node_modules/vite/bin/vite.js", import.meta.url));
  assert.deepEqual(viteInvocation(5174), [process.execPath, [cli, ...viteArguments(5174)]]);
  const directory = await mkdtemp(join(tmpdir(), "scena-server-stop-"));
  let child;
  try {
    const fixture = join(directory, "fixture.mjs");
    await writeFile(fixture, 'setInterval(() => {}, 1000); process.stdout.write("ready\\n");');
    const [command, args] = viteInvocation(5174, fixture);
    child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
    await once(child.stdout, "data", { signal: AbortSignal.timeout(5000) });
    await stopChild(child);
    assert.notEqual(child.signalCode, null, "The directly owned server must stop");
    assert.throws(() => process.kill(child.pid, 0), { code: "ESRCH" });
  } finally {
    await stopChild(child);
    await rm(directory, { recursive: true, force: true });
  }
  assert.throws(() => serverOptions(["--api-port", "nope"]), /apiPort/);
}

if (process.argv[2] === "--self-test") await selfTest();
else await run(process.argv.slice(2));
