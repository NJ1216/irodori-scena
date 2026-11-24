import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { verifyRightsReview } from "./rights-review.mjs";
import { readJson, root, syncVersions, validateMetadata } from "./version.mjs";

syncVersions();
const publication = process.argv.includes("--publication");
validateMetadata(readJson("release-metadata.json"), publication);
const notices = readJson("licenses/inventory.json");
for (const [name, expected] of Object.entries(notices.inputs)) {
  const actual = createHash("sha256")
    .update(readFileSync(path.join(root, name)))
    .digest("hex");
  if (actual !== expected) throw new Error(`License inventory input changed: ${name}; run pnpm release:licenses`);
}
for (const [digest, content] of Object.entries(notices.texts)) {
  if (createHash("sha256").update(content).digest("hex") !== digest) throw new Error("License text hash mismatch");
}
for (const entry of notices.entries) {
  for (const text of entry.texts) {
    if (!(text.sha256 in notices.texts)) throw new Error(`Missing license text: ${entry.id}`);
    if (text.name.startsWith("licenses/texts/")) {
      const actual = createHash("sha256")
        .update(readFileSync(path.join(root, text.name)))
        .digest("hex");
      if (actual !== text.sha256) throw new Error(`License source changed: ${entry.id}`);
    }
  }
}
const regenerated = spawnSync("uv", ["run", "--locked", "python", "tools/release/licenses.py", "--check"], {
  cwd: root,
  env: { ...process.env, UV_CACHE_DIR: path.join(root, ".uv-cache") },
  encoding: "utf8",
});
if (regenerated.status !== 0) throw new Error(regenerated.stderr || regenerated.stdout || "License inventory regeneration failed");
if (publication) {
  const review = readJson("release-license-supplements.json");
  if (notices.entries.some((entry) => entry.status !== "collected") || !review.compatibilityReviewed || !review.assetsReviewed || !review.runtimeDownloadsReviewed) throw new Error("Third-party rights review is incomplete");
  verifyRightsReview(root, review, readJson("release-metadata.json"));
}
console.log(`Release metadata and ${notices.entries.length} license entries checked.`);
