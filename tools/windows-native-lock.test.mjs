import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { copyWindowsNativeModule, verifyBundledNativeModule } from "./native-extension-output.mjs";

test("release native output does not overwrite a loaded development module", { skip: process.platform !== "win32" }, async () => {
  const directory = mkdtempSync(join(tmpdir(), "scena-native-lock-"));
  const source = join(directory, "scena_native.dll");
  const development = join(directory, "scena_native.pyd");
  const release = join(directory, "release");
  writeFileSync(source, "new native module");
  writeFileSync(development, "loaded development module");
  const script = "$file = [IO.File]::Open($env:SCENA_LOCK_PATH, 'Open', 'ReadWrite', 'None'); try { [Console]::WriteLine('READY'); [Console]::ReadLine() | Out-Null } finally { $file.Dispose() }";
  const holder = spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, SCENA_LOCK_PATH: development },
  });
  let timeout;
  try {
    await Promise.race([
      new Promise((resolve, reject) => {
        holder.once("error", reject);
        holder.stdout.once("data", (data) => (data.toString().includes("READY") ? resolve() : reject(new Error(`Lock holder: ${data}`))));
        holder.once("exit", (code) => reject(new Error(`Lock holder exited: ${code}`)));
      }),
      new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error("Lock holder timed out")), 10_000);
      }),
    ]);
    assert.throws(() => copyWindowsNativeModule(source, directory), { code: "EBUSY" });
    const staged = copyWindowsNativeModule(source, release);
    assert.equal(readFileSync(staged, "utf8"), "new native module");
    verifyBundledNativeModule(staged, copyWindowsNativeModule(source, join(directory, "bundle")));
  } finally {
    clearTimeout(timeout);
    holder.stdin.end("\n");
    await new Promise((resolve) => holder.once("exit", resolve));
    assert.equal(readFileSync(development, "utf8"), "loaded development module");
    assert.throws(() => verifyBundledNativeModule(join(release, "scena_native.pyd"), development), /different native module/);
    rmSync(directory, { recursive: true, force: true });
  }
});
