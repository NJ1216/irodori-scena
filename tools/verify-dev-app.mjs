#!/usr/bin/env node

import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const toolsDirectory = dirname(fileURLToPath(import.meta.url));
const expectedRunnerCwd = realpathSync(resolve(toolsDirectory, "../src-tauri"));
const expectedAppPrefix = join(tmpdir(), "irodori-scena-dev-");

export function parentPidFor(pid, rows) {
  return rows.find(([candidate]) => candidate === pid)?.[1] ?? null;
}

export function cwdFromLsof(output) {
  return (
    output
      .split("\n")
      .find((line) => line.startsWith("n"))
      ?.slice(1) ?? null
  );
}

export function isTemporaryDevelopmentCommand(command, prefix = expectedAppPrefix) {
  return command.startsWith(prefix) && command.includes("/irodori SCENA [DEV].app/Contents/MacOS/irodori-scena");
}

export function supervisedLoopbackListener(listeners) {
  return listeners.find((listener) => /^127\.0\.0\.1:\d+$/.test(listener)) ?? null;
}

export function apiTokenFromEnvironment(environment) {
  return environment.match(/(?:^|\s)SCENA_API_TOKEN=([^\s]+)/)?.[1] ?? null;
}

export function listenerOutputFromProbe(result) {
  if (result.status === 0) return result.stdout;
  // lsof can return 1 with valid sockets when an unrelated mounted backup
  // volume cannot be stat'ed. Still require a supervised socket and API auth.
  const warnings = result.stderr.trim().split("\n");
  const backupWarning = warnings.length > 0 && warnings.every((line) => /^lsof: WARNING: can't stat\(\) smbfs file system /.test(line) || /^\s+Output information may be incomplete\.$/.test(line) || /^\s+assuming "dev=\d+" from mount table$/.test(line));
  if (result.status === 1 && /^n127\.0\.0\.1:\d+$/m.test(result.stdout) && backupWarning) return result.stdout;
  throw new Error("supervised listener inspection failed");
}

function selfTest() {
  assert.equal(
    parentPidFor(30, [
      [10, 1],
      [30, 20],
    ]),
    20,
  );
  assert.equal(
    parentPidFor(40, [
      [10, 1],
      [30, 20],
    ]),
    null,
  );
  assert.equal(cwdFromLsof("p20\nfcwd\nn/repository/src-tauri\n"), "/repository/src-tauri");
  assert.equal(isTemporaryDevelopmentCommand("/tmp/irodori-scena-dev-AbCd/irodori SCENA [DEV].app/Contents/MacOS/irodori-scena", "/tmp/irodori-scena-dev-"), true);
  assert.equal(isTemporaryDevelopmentCommand("/repository/target/debug/dev-bundle/irodori SCENA [DEV].app/Contents/MacOS/irodori-scena", "/tmp/irodori-scena-dev-"), false);
  assert.equal(supervisedLoopbackListener(["*:5175", "127.0.0.1:60421"]), "127.0.0.1:60421");
  assert.equal(supervisedLoopbackListener(["*:5175"]), null);
  assert.equal(apiTokenFromEnvironment("python server SCENA_API_TOKEN=secret-token SCENA_DESKTOP=1"), "secret-token");
  assert.equal(apiTokenFromEnvironment("python server SCENA_DESKTOP=1"), null);
  const warning = 'lsof: WARNING: can\'t stat() smbfs file system /backup\n      Output information may be incomplete.\n      assuming "dev=123" from mount table\n';
  assert.equal(listenerOutputFromProbe({ status: 1, stdout: "p20\nf10\nn127.0.0.1:60421\n", stderr: warning }), "p20\nf10\nn127.0.0.1:60421\n");
  assert.throws(() => listenerOutputFromProbe({ status: 1, stdout: "", stderr: warning }));
  assert.throws(() => listenerOutputFromProbe({ status: 1, stdout: "n127.0.0.1:60421\n", stderr: "permission denied" }));
}

if (process.argv[2] === "--self-test") {
  selfTest();
  process.exit(0);
}

function fail(message) {
  console.error(`Development app verification failed: ${message}`);
  process.exit(1);
}

if (process.platform === "win32") {
  const result = spawnSync("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", join(toolsDirectory, "windows-dev/verify-dev-app.ps1")], { stdio: "inherit" });
  process.exit(result.status ?? 1);
}

const probe = spawnSync("cargo", ["run", "--quiet", "--manifest-path", "src-tauri/Cargo.toml", "--bin", "dev-app-probe"], { encoding: "utf8" });
if (probe.status !== 0) fail(probe.stderr.trim() || "the native process probe failed");

let state;
try {
  state = JSON.parse(probe.stdout);
} catch {
  fail("the native process probe returned invalid JSON");
}

const expectedSchemaHash = readFileSync(resolve(toolsDirectory, "../src/generated/api-schema-hash.ts"), "utf8").match(/[a-f0-9]{64}/)?.[0];
let apiHealthUrl = "http://127.0.0.1:8787/api/health";
let apiHealthHeaders = {};
if (process.platform === "darwin") {
  const processRows = execFileSync("/bin/ps", ["-axo", "pid=,ppid="], { encoding: "utf8" })
    .trim()
    .split("\n")
    .map((line) => line.trim().split(/\s+/).map(Number));
  const descendants = [state.pid];
  for (let index = 0; index < descendants.length; index += 1) {
    descendants.push(...processRows.filter(([, parent]) => parent === descendants[index]).map(([pid]) => pid));
  }
  const listenerOutput = listenerOutputFromProbe(spawnSync("/usr/sbin/lsof", ["-nP", "-a", "-p", descendants.join(","), "-iTCP", "-sTCP:LISTEN", "-Fn"], { encoding: "utf8" }));
  const listeners = [
    ...new Set(
      listenerOutput
        .split("\n")
        .filter((line) => line.startsWith("n"))
        .map((line) => line.slice(1)),
    ),
  ];
  const loopbackListener = supervisedLoopbackListener(listeners);
  if (!loopbackListener) fail("the development app has no supervised listening API socket");
  let token = "";
  for (const pid of descendants.slice(1)) {
    const environment = execFileSync("/bin/ps", ["eww", "-p", String(pid), "-o", "command="], { encoding: "utf8" });
    token = apiTokenFromEnvironment(environment) ?? "";
    if (token) break;
  }
  if (!token) fail("the supervised DEV API token could not be inspected");
  apiHealthUrl = `http://${loopbackListener}/api/health`;
  apiHealthHeaders = { Authorization: `Bearer ${token}` };
}
try {
  const response = await fetch(apiHealthUrl, { headers: apiHealthHeaders, signal: AbortSignal.timeout(2000) });
  if (!response.ok) fail(`API health returned HTTP ${response.status}`);
  const health = await response.json();
  if (!expectedSchemaHash || health.apiSchemaHash !== expectedSchemaHash) fail("running DEV API schema does not match this checkout");
  state.apiSchemaHash = health.apiSchemaHash;
} catch (error) {
  fail(`DEV API schema verification failed: ${error.message}`);
}

try {
  const response = await fetch("http://127.0.0.1:5175/", { signal: AbortSignal.timeout(2000) });
  if (!response.ok) fail(`Vite returned HTTP ${response.status}`);
} catch (error) {
  fail(`Vite is unreachable: ${error.message}`);
}

if (process.platform === "darwin") {
  const rows = execFileSync("/bin/ps", ["-axo", "pid=,ppid="], { encoding: "utf8" })
    .trim()
    .split("\n")
    .map((line) => line.trim().split(/\s+/).map(Number));
  const appCommand = execFileSync("/bin/ps", ["-p", String(state.pid), "-o", "command="], { encoding: "utf8" }).trim();
  if (!isTemporaryDevelopmentCommand(appCommand)) {
    fail("the development app is not the process-local temporary bundle created by the current runner");
  }
  const runnerPid = parentPidFor(state.pid, rows);
  if (!runnerPid) fail("the development app has no parent runner process");
  const runnerCommand = execFileSync("/bin/ps", ["-p", String(runnerPid), "-o", "command="], {
    encoding: "utf8",
  }).trim();
  if (!runnerCommand.includes("tools/tauri-dev-runner.mjs")) {
    fail("the development app was not launched by the repository development runner");
  }
  let runnerCwd;
  try {
    runnerCwd = cwdFromLsof(
      execFileSync("/usr/sbin/lsof", ["-nP", "-a", "-p", String(runnerPid), "-d", "cwd", "-Fn"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      }),
    );
  } catch {
    fail("the development runner working directory could not be inspected");
  }
  if (!runnerCwd || realpathSync(runnerCwd) !== expectedRunnerCwd) {
    fail("the development app belongs to a runner outside this repository");
  }
  const processIds = [state.pid];
  for (let index = 0; index < processIds.length; index += 1) {
    processIds.push(...rows.filter(([, parent]) => parent === processIds[index]).map(([pid]) => pid));
  }
  let listeners = "";
  try {
    listeners = execFileSync("/usr/sbin/lsof", ["-nP", "-a", "-p", processIds.join(","), "-iTCP", "-sTCP:LISTEN", "-Fn"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  } catch {
    fail("the development app has no supervised listening API socket");
  }
  state.apiListeners = [
    ...new Set(
      listeners
        .split("\n")
        .filter((line) => line.startsWith("n"))
        .map((line) => line.slice(1)),
    ),
  ];
  if (state.apiListeners.length === 0) fail("the development app has no supervised listening API socket");
}

state.frontendUrl = "http://127.0.0.1:5175/";
console.log(JSON.stringify(state, null, 2));
