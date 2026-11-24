import { mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import assert from "node:assert/strict";
import { afterEach, it } from "node:test";
import { tidyMacBundles } from "./tauri-bundles.mjs";

let root;
afterEach(() => rmSync(root, { recursive: true, force: true }));

function project(bundle = "src-tauri/target/release/bundle") {
  root = mkdtempSync(join(tmpdir(), "tauri-bundles-"));
  mkdirSync(join(root, bundle, "dmg"), { recursive: true });
  mkdirSync(join(root, bundle, "macos/App.app/Contents"), { recursive: true });
  writeFileSync(join(root, "src-tauri/tauri.conf.json"), JSON.stringify({ productName: "App", version: "26.11.24" }));
  for (const name of ["App_26.11.24_aarch64.dmg", "App_26.10.3_aarch64.dmg", "bundle_dmg.sh"]) {
    writeFileSync(join(root, bundle, "dmg", name), "x");
  }
  return join(root, bundle);
}

it("keeps only the current DMG after a default build", () => {
  const bundle = project();
  assert.equal(tidyMacBundles(root, ["build"]).length, 2);
  assert.deepEqual(readdirSync(join(bundle, "macos")), []);
  assert.deepEqual(readdirSync(join(bundle, "dmg")).sort(), ["App_26.11.24_aarch64.dmg", "bundle_dmg.sh"]);
});

it("uses the target folder and keeps an explicitly requested app bundle", () => {
  const bundle = project("src-tauri/target/aarch64-apple-darwin/release/bundle");
  assert.deepEqual(tidyMacBundles(root, ["build", "--target", "aarch64-apple-darwin", "--bundles", "app,dmg"]), []);
  assert.deepEqual(readdirSync(join(bundle, "macos")), ["App.app"]);
  assert.equal(tidyMacBundles(root, ["build", "--target", "aarch64-apple-darwin", "--bundles", "dmg"]).length, 2);
  assert.deepEqual(readdirSync(join(bundle, "macos")), []);
});

it("leaves the app when no DMG of this version was made", () => {
  const bundle = project();
  rmSync(join(bundle, "dmg/App_26.11.24_aarch64.dmg"));
  assert.deepEqual(tidyMacBundles(root, ["build"]), []);
  assert.deepEqual(tidyMacBundles(root, ["dev"]), []);
  assert.deepEqual(readdirSync(join(bundle, "macos")), ["App.app"]);
});
