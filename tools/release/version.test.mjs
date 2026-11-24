import assert from "node:assert/strict";
import test from "node:test";
import { setReleaseVersion, validateMetadata } from "./version.mjs";

test("CalVer accepts first beta, same-day follow-ups and stable", () => {
  for (const version of ["26.9.6-beta", "26.9.6-beta.1", "26.9.6-beta.2", "26.9.6"]) validateMetadata({ version, releaseDate: "2026-09-06" });
});
test("setting a release version derives its date and keeps the other fields", () => {
  const metadata = { version: "26.10.4", releaseDate: "2026-10-04", author: "NJ", license: "MIT" };
  assert.deepEqual(setReleaseVersion(metadata, "26.11.24"), { ...metadata, version: "26.11.24", releaseDate: "2026-11-24" });
  assert.equal(setReleaseVersion(metadata, "26.9.6-beta.1").releaseDate, "2026-09-06");
  assert.throws(() => setReleaseVersion(metadata, "26.2.30"));
});
test("CalVer rejects invalid calendar dates and mismatched dates", () => {
  for (const version of ["26.2.30-beta", "26.13.6-beta", "26.9.6-beta.0", "2026.9.6-beta", "26.9.6-beta.01"]) assert.throws(() => validateMetadata({ version, releaseDate: "2026-09-06" }));
});
test("publication requires explicit public identity without personal email", () => {
  const value = { version: "26.9.6-beta", releaseDate: "2026-09-06", author: "", repository: "", commitEmail: "" };
  assert.throws(() => validateMetadata(value, true));
  validateMetadata({ ...value, author: "Example", repository: "https://github.com/example/scena", commitEmail: "example@users.noreply.github.com" }, true);
});

test("rights approval rejects changed dependencies, assets and binary distribution", async () => {
  const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const path = await import("node:path");
  const { rightsDigest, verifyRightsReview } = await import("./rights-review.mjs");
  const root = mkdtempSync(path.join(tmpdir(), "scena-rights-test-"));
  try {
    for (const name of ["release-metadata.json", "pnpm-lock.yaml", "uv.lock", "src-tauri/Cargo.lock", "native/scena-native/Cargo.lock", "tools/omlx-runtime-requirements.txt", "server/modules/tts_catalog.py", "LICENSE", "src-tauri/icons/icon.png", "src-tauri/icons/icon.icns"]) {
      mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
      writeFileSync(path.join(root, name), "original");
    }
    writeFileSync(path.join(root, "notice.txt"), "original");
    const packages = [{ id: "example@1.0.0", files: ["notice.txt"] }];
    const review = { packages, review: { scope: "source-only", sha256: rightsDigest(root, packages) } };
    verifyRightsReview(root, review, { distribution: "source" });
    assert.throws(() => verifyRightsReview(root, review, { distribution: "binary" }), /source distribution only/);
    assert.throws(() => verifyRightsReview(root, { ...review, packages: [...packages, { id: "new@2.0.0" }] }, { distribution: "source" }), /stale/);
    for (const name of ["pnpm-lock.yaml", "src-tauri/icons/icon.png", "server/modules/tts_catalog.py", "notice.txt"]) {
      writeFileSync(path.join(root, name), "changed");
      assert.throws(() => verifyRightsReview(root, review, { distribution: "source" }), /stale/);
      writeFileSync(path.join(root, name), "original");
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("Windows installer distribution needs its own current binary review", async () => {
  const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const path = await import("node:path");
  const { BINARY_INPUTS, binaryDigest, rightsDigest, verifyRightsReview } = await import("./rights-review.mjs");
  const root = mkdtempSync(path.join(tmpdir(), "scena-binary-rights-"));
  try {
    for (const name of ["release-metadata.json", "pnpm-lock.yaml", "uv.lock", "src-tauri/Cargo.lock", "native/scena-native/Cargo.lock", "tools/omlx-runtime-requirements.txt", "server/modules/tts_catalog.py", "LICENSE", "src-tauri/icons/icon.png", "src-tauri/icons/icon.icns", ...BINARY_INPUTS]) {
      mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
      writeFileSync(path.join(root, name), "original");
    }
    const packages = [{ id: "example@1.0.0" }];
    const source = { packages, review: { scope: "source-only", sha256: rightsDigest(root, packages) } };
    const installer = { distribution: "source-and-windows-installer" };
    assert.throws(() => verifyRightsReview(root, source, installer), /Windows installer/);
    const reviewed = { ...source, binaryReview: { scope: "windows-x64-nsis", sha256: binaryDigest(root, packages) } };
    verifyRightsReview(root, reviewed, installer);
    writeFileSync(path.join(root, "tools/pyinstaller/scena-api.spec"), "changed");
    assert.throws(() => verifyRightsReview(root, reviewed, installer), /Windows installer rights review is stale/);
    verifyRightsReview(root, reviewed, { distribution: "source" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
