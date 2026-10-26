import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

// P11 browser E2E: ONE browser (Chromium), eight scenarios in e2e/, against the real application served by
// e2e/fixture_server.py (temporary database, two tenants, scripted investigations, the built UI). No model is called.
// Retries are disabled on purpose: a flaky test must fail, not be hidden.
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const runtime = path.join(root, "e2e", ".runtime");
const port = Number(process.env.PULSEOPS_E2E_PORT ?? 18900);
const python = process.env.PULSEOPS_PYTHON ?? "python";

export default defineConfig({
  testDir: path.join(root, "e2e"),
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: path.join(runtime, "test-results"),
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "off",
    video: "off",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `"${python}" "${path.join(root, "e2e", "fixture_server.py")}" --port ${port} --db "${path.join(runtime, "e2e.db")}" --runtime-dir "${runtime}" --fresh`,
    url: `http://127.0.0.1:${port}/health/ready`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
