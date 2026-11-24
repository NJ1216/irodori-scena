import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join } from "node:path";
import { fileURLToPath } from "node:url";
import { inspectInstallerEntries, windowsBuildPaths } from "./windows-build-contract.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const paths = windowsBuildPaths(root);
const required = [
  ["irodori-scena.exe", null],
  ["scena-api-runtime/scena-api.exe", "src-tauri/binaries/scena-api/scena-api.exe"],
  ["environment-manager/uv.exe", "src-tauri/resources/environment-manager/uv.exe"],
  "scena-api-runtime/_internal/server/irodori_worker.py",
  "scena-api-runtime/_internal/server/irodori_runtime_layout.py",
  "scena-api-runtime/_internal/server/irodori_host.py",
  "scena-api-runtime/_internal/server/irodori_load_adapter.py",
  "scena-api-runtime/_internal/server/irodori_acceleration_adapter.py",
  "scena-api-runtime/_internal/server/irodori_acceleration_sampler.py",
  "scena-api-runtime/_internal/server/irodori_cuda_calibration.py",
  "scena-api-runtime/_internal/server/irodori_cuda_graphs.py",
  "scena-api-runtime/_internal/server/catalogs/rhubarb-runtime.json",
  "scena-api-runtime/_internal/server/catalogs/llama-cpp-runtime.json",
].map((item) => (Array.isArray(item) ? item : [item, join("src-tauri/binaries/scena-api", item.replace("scena-api-runtime/", ""))]));

const sha256 = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
for (const [relativePath, source] of required) {
  const bundled = join(paths.release, relativePath);
  assert.ok(statSync(bundled).isFile(), `missing ${relativePath}`);
  if (source) assert.equal(sha256(bundled), sha256(join(root, source)), `content mismatch for ${relativePath}`);
}

function peSubsystem(path) {
  const bytes = readFileSync(path);
  assert.equal(bytes.toString("ascii", 0, 2), "MZ", `${path} is not PE`);
  const pe = bytes.readUInt32LE(0x3c);
  assert.equal(bytes.toString("ascii", pe, pe + 4), "PE\0\0", `${path} has no PE header`);
  const optional = pe + 24;
  assert.ok([0x10b, 0x20b].includes(bytes.readUInt16LE(optional)), `${path} has unknown optional header`);
  return bytes.readUInt16LE(optional + 68);
}

for (const executable of ["irodori-scena.exe", "scena-api-runtime/scena-api.exe"]) {
  assert.equal(peSubsystem(join(paths.release, executable)), 2, `${executable} must use Windows GUI subsystem`);
}
const bundle = join(paths.release, "bundle");
assert.equal(existsSync(join(bundle, "msi")), false, "MSI output is not allowed");
const argument = (name) => process.argv[process.argv.indexOf(name) + 1];
const productName = JSON.parse(readFileSync(join(root, "src-tauri/tauri.conf.json"), "utf8")).productName;
const entries = readdirSync(paths.nsisOutput, { withFileTypes: true }).map((entry) => ({ name: entry.name, mtimeMs: statSync(join(paths.nsisOutput, entry.name)).mtimeMs }));
const result = inspectInstallerEntries(entries, { productName, version: argument("--version"), buildStartedAt: Number(argument("--started-at")) });
assert.deepEqual(result.problems, []);
const installer = join(paths.nsisOutput, result.installer.name);
assert.equal(peSubsystem(installer), 2, "NSIS installer must use Windows GUI subsystem");
assert.ok(statSync(join(paths.release, "scena-api-runtime/scena-api.exe")).size <= 100663296, "API executable exceeds 96 MiB");
console.log(basename(installer));
