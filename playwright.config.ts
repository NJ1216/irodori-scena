import { defineConfig, devices } from "@playwright/test";
import ports from "./tools/ports.json" with { type: "json" };

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${ports.playwright.vite}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Tests never need audible output. The null sink keeps AudioContext.currentTime advancing under parallel
        // load; the real macOS device can take seconds to start, which starves live meters and is-playing.
        launchOptions: { args: ["--disable-audio-output"] },
      },
    },
  ],
  webServer: {
    command: `node tools/start-dev-servers.mjs --api-port ${ports.playwright.api} --vite-port ${ports.playwright.vite} --data-root .test-temp/playwright-data`,
    url: `http://127.0.0.1:${ports.playwright.vite}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
