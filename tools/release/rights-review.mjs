import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

const inputs = ["release-metadata.json", "pnpm-lock.yaml", "uv.lock", "src-tauri/Cargo.lock", "native/scena-native/Cargo.lock", "tools/omlx-runtime-requirements.txt", "server/modules/tts_catalog.py", "LICENSE", "src-tauri/icons/icon.png", "src-tauri/icons/icon.icns"];
// Files that decide what the Windows installer bundles; changing them requires a new binary review.
export const BINARY_INPUTS = ["tools/pyinstaller/scena-api.spec", "src-tauri/tauri.windows.release.conf.json", "src-tauri/windows/installer.nsi", "src-tauri/windows/installer-hooks.nsh"];

function digest(root, packages, names) {
  const hash = createHash("sha256").update(JSON.stringify(packages));
  const notices = [...new Set(packages.flatMap((entry) => entry.files ?? []))].sort();
  for (const name of [...names, ...notices]) {
    hash.update(name).update(readFileSync(path.join(root, name)));
  }
  return hash.digest("hex");
}

export function rightsDigest(root, packages) {
  return digest(root, packages, inputs);
}

export function binaryDigest(root, packages) {
  return digest(root, packages, [...inputs, ...BINARY_INPUTS]);
}

export function verifyRightsReview(root, review, metadata) {
  if (!["source", "source-and-windows-installer"].includes(metadata.distribution) || review.review?.scope !== "source-only") throw new Error("Rights review covers source distribution only");
  if (review.review?.sha256 !== rightsDigest(root, review.packages)) throw new Error("Rights review is stale; review changed dependencies, metadata and assets");
  if (metadata.distribution !== "source-and-windows-installer") return;
  if (review.binaryReview?.scope !== "windows-x64-nsis") throw new Error("Windows installer distribution needs a binary rights review");
  if (review.binaryReview.sha256 !== binaryDigest(root, review.packages)) throw new Error("Windows installer rights review is stale; review the bundled components again");
}
