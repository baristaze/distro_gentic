import { defineConfig } from "@playwright/test";

// The browser check runs against a stack that is already up: the API, the
// maintenance worker, the session runner on the scripted provider, and this
// portal's dev server. It starts none of them (README, Run).
// ACME_PORTAL_URL names the portal. What it writes lands in e2e/results and
// e2e/screenshots, which git ignores.
export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/results",
  timeout: 300_000,
  // A shared local database can take seconds to answer one call.
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.ACME_PORTAL_URL ?? "http://127.0.0.1:5173",
    browserName: "chromium",
    viewport: { width: 1280, height: 900 },
    screenshot: "only-on-failure",
  },
});
