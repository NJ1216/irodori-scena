import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export const readJson = (name) => JSON.parse(readFileSync(path.join(root, name), "utf8"));
export function validateMetadata(metadata, publication = false) {
  const match = /^(\d{1,2})\.(\d{1,2})\.(\d{1,2})(?:-beta(?:\.[1-9]\d*)?)?$/.exec(metadata.version);
  if (!match) throw new Error("Invalid CalVer");
  const date = `20${match[1].padStart(2, "0")}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`;
  if (metadata.releaseDate !== date || new Date(date).toISOString().slice(0, 10) !== date) throw new Error("Invalid release date");
  if (publication && (!metadata.author.trim() || !/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.test(metadata.repository) || !/^[\w+.-]+@users\.noreply\.github\.com$/.test(metadata.commitEmail))) {
    throw new Error("Public author, GitHub repository and GitHub noreply commitEmail are required");
  }
}
export function syncVersions(write = false) {
  const metadata = readJson("release-metadata.json");
  validateMetadata(metadata);
  const licensePath = path.join(root, "LICENSE");
  const licenseBefore = readFileSync(licensePath, "utf8");
  const licenseAfter = licenseBefore.replace(/^Copyright \(c\) .*$/m, `Copyright (c) ${metadata.releaseDate.slice(0, 4)} ${metadata.author || "[PUBLIC AUTHOR REQUIRED]"}`);
  if (licenseBefore !== licenseAfter) {
    if (!write) throw new Error("Copyright metadata drift");
    writeFileSync(licensePath, licenseAfter);
  }
  const files = ["package.json", "src-tauri/tauri.conf.json", "src-tauri/Cargo.toml", "src-tauri/Cargo.lock", "pyproject.toml", "uv.lock"];
  for (const name of files) {
    const file = path.join(root, name);
    const before = readFileSync(file, "utf8");
    // Python's equivalent PEP 440 version is a beta release with the same date.
    const python = name === "pyproject.toml" || name === "uv.lock";
    const version = python ? metadata.version.replace(/-beta(?:\.(\d+))?$/, (_, n) => `b${n ?? "0"}`) : metadata.version;
    const pattern = name.endsWith(".json") ? /("version": ")[^"]+/ : name.endsWith(".lock") ? /(name = "irodori-scena(?:-local-api)?"\nversion = ")[^"]+/ : /(version = ")[^"]+/;
    const after = before.replace(pattern, `$1${version}`);
    if (before === after) continue;
    if (!write) throw new Error(`Version drift: ${name}`);
    writeFileSync(file, after);
  }
}
/** Set the release version and its date (`20YY-MM-DD` from the CalVer tag), keeping the other metadata fields. */
export function setReleaseVersion(metadata, version) {
  const parts = version.split("-")[0].split(".");
  const next = { ...metadata, version, releaseDate: `20${parts.map((part) => part.padStart(2, "0")).join("-")}` };
  validateMetadata(next);
  return next;
}
function optionValue(name) {
  const index = process.argv.indexOf(name);
  if (index < 0) return undefined;
  const value = process.argv[index + 1];
  if (!value || value.startsWith("--")) throw new Error(`${name} requires a version`);
  return value;
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const requested = optionValue("--set");
  const expected = optionValue("--expect");
  if (requested) {
    const file = path.join(root, "release-metadata.json");
    writeFileSync(file, `${JSON.stringify(setReleaseVersion(readJson("release-metadata.json"), requested), null, 2)}\n`);
  }
  if (expected && readJson("release-metadata.json").version !== expected) throw new Error(`Release version is not ${expected}`);
  syncVersions(Boolean(requested) || process.argv.includes("--write"));
}
