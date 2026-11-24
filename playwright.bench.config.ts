import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";

// Interaction benchmarks run apart from the E2E suite: pnpm benchmark:ui
export default defineConfig({
  ...base,
  testDir: "./tests/bench",
  testMatch: /.*\.bench\.ts/,
  workers: 1,
  retries: 0,
  timeout: 240_000,
  expect: { timeout: 8_000 },
  reporter: "line",
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], actionTimeout: 8_000, viewport: { width: 1454, height: 998 } } }],
});
