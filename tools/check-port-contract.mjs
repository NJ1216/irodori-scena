import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ports from "./ports.json" with { type: "json" };

const tauri = readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8");
// The developer port table lives in the build guide; README is the user guide.
const buildGuide = readFileSync(new URL("../docs/public/build.md", import.meta.url), "utf8");
assert.match(tauri, new RegExp(`--port ${ports.tauri.vite}\\b`));
assert.match(tauri, new RegExp(`127\\.0\\.0\\.1:${ports.tauri.vite}\\b`));
for (const port of [ports.browser.vite, ports.browser.api, ports.playwright.vite, ports.playwright.api]) {
  assert.match(buildGuide, new RegExp(`\\b${port}\\b`));
}
assert.equal(ports.tauri.api, "ephemeral");
