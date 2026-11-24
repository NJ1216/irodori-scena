#!/usr/bin/env node

import assert from "node:assert/strict";
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";

const toolsDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(toolsDirectory, "..");
const tauriRoot = join(repositoryRoot, "src-tauri");
const appName = "irodori SCENA [DEV].app";
const executableName = "irodori-scena";
const runRootPrefix = "irodori-scena-dev-";
const launchServicesRegister = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister";

export function runnerArguments(argv) {
  assert.equal(argv[0], "run", "The Tauri development runner only supports cargo run");
  const separator = argv.indexOf("--");
  return {
    cargo: ["build", ...argv.slice(1, separator < 0 ? undefined : separator)],
    app: separator < 0 ? [] : argv.slice(separator + 1),
  };
}

export function developmentInfoPlist() {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleDevelopmentRegion</key><string>ja</string>
  <key>CFBundleDisplayName</key><string>irodori SCENA [DEV]</string>
  <key>CFBundleExecutable</key><string>${executableName}</string>
  <key>CFBundleIdentifier</key><string>com.irodori-scena.dev</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>irodori SCENA [DEV]</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
`;
}

export function codesignArguments(bundle) {
  return ["--force", "--deep", "--sign", "-", bundle];
}

export function staleDevelopmentRunRoots(entries, activeCommands, temporaryRoot = tmpdir()) {
  return entries
    .filter((entry) => entry.isDirectory() && entry.name.startsWith(runRootPrefix))
    .map((entry) => join(temporaryRoot, entry.name))
    .filter((runRoot) => !activeCommands.includes(join(runRoot, appName, "Contents", "MacOS", executableName)));
}

function unregisterBundle(bundle) {
  spawnSync(launchServicesRegister, ["-u", bundle], { stdio: "ignore" });
}

function cleanupStaleDevelopmentBundles(targetRoot) {
  const processes = spawnSync("/bin/ps", ["-axo", "command="], { encoding: "utf8" });
  if (processes.status !== 0) return;
  const activeCommands = processes.stdout;
  const temporaryRoot = tmpdir();
  const staleRoots = staleDevelopmentRunRoots(readdirSync(temporaryRoot, { withFileTypes: true }), activeCommands, temporaryRoot);
  for (const runRoot of staleRoots) {
    unregisterBundle(join(runRoot, appName));
    rmSync(runRoot, { recursive: true, force: true });
  }
  const generatedBundle = join(targetRoot, "debug", "dev-bundle", appName);
  if (!activeCommands.includes(join(generatedBundle, "Contents", "MacOS", executableName))) {
    unregisterBundle(generatedBundle);
    rmSync(generatedBundle, { recursive: true, force: true });
  }
}

function developmentTargetRoot() {
  return process.env.CARGO_TARGET_DIR ? resolve(tauriRoot, process.env.CARGO_TARGET_DIR) : join(tauriRoot, "target");
}

function bundleExecutable() {
  const targetRoot = developmentTargetRoot();
  // Tauri can briefly overlap runner processes while reacting to config changes.
  // A process-local bundle prevents one runner from replacing another runner's
  // executable while macOS is validating or launching it.
  cleanupStaleDevelopmentBundles(targetRoot);
  const runRoot = mkdtempSync(join(tmpdir(), runRootPrefix));
  const bundle = join(runRoot, appName);
  const executable = join(bundle, "Contents", "MacOS", executableName);
  mkdirSync(dirname(executable), { recursive: true });
  writeFileSync(join(bundle, "Contents", "Info.plist"), developmentInfoPlist());
  copyFileSync(join(targetRoot, "debug", executableName), executable);
  chmodSync(executable, 0o755);
  const signing = spawnSync("codesign", codesignArguments(bundle), { stdio: "inherit" });
  if (signing.status !== 0) throw new Error("Tauri development appのad-hoc署名に失敗しました。");
  const verification = spawnSync("codesign", ["--verify", "--strict", bundle], { stdio: "inherit" });
  if (verification.status !== 0) throw new Error("Tauri development appのコード署名を検証できませんでした。");
  return { executable, runRoot };
}

function selfTest() {
  assert.deepEqual(runnerArguments(["run", "--no-default-features", "--color", "always", "--"]), {
    cargo: ["build", "--no-default-features", "--color", "always"],
    app: [],
  });
  assert.match(developmentInfoPlist(), /<string>com\.irodori-scena\.dev<\/string>/);
  assert.match(developmentInfoPlist(), /<string>irodori SCENA \[DEV\]<\/string>/);
  assert.deepEqual(codesignArguments("/tmp/SCENA Dev.app"), ["--force", "--deep", "--sign", "-", "/tmp/SCENA Dev.app"]);
  const entries = [
    { name: "irodori-scena-dev-stale", isDirectory: () => true },
    { name: "irodori-scena-dev-active", isDirectory: () => true },
    { name: "unrelated", isDirectory: () => true },
  ];
  assert.deepEqual(staleDevelopmentRunRoots(entries, "/tmp/irodori-scena-dev-active/irodori SCENA [DEV].app/Contents/MacOS/irodori-scena", "/tmp"), ["/tmp/irodori-scena-dev-stale"]);
}

if (process.argv[2] === "--self-test") {
  selfTest();
  process.exit(0);
}

if (process.argv[2] === "--cleanup-stale") {
  cleanupStaleDevelopmentBundles(developmentTargetRoot());
  process.exit(0);
}

const invocation = runnerArguments(process.argv.slice(2));
const build = spawnSync("cargo", invocation.cargo, { cwd: tauriRoot, env: process.env, stdio: "inherit" });
if (build.status !== 0) process.exit(build.status ?? 1);

let developmentBundle;
try {
  developmentBundle = bundleExecutable();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
const child = spawn(developmentBundle.executable, invocation.app, {
  cwd: tauriRoot,
  env: process.env,
  stdio: "inherit",
});
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("exit", (code, signal) => {
  unregisterBundle(join(developmentBundle.runRoot, appName));
  rmSync(developmentBundle.runRoot, { recursive: true, force: true });
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
