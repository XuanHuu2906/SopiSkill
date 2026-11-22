import fs from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8100);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 3100);
const BASE_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

const venvPython = path.resolve(__dirname, "../backend/.venv/bin/python");
const pythonBin =
  process.env.E2E_PYTHON ??
  (fs.existsSync(venvPython) ? venvPython : "python3");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `"${pythonBin}" scripts/run_e2e_backend.py`,
      cwd: path.resolve(__dirname, "../backend"),
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      reuseExistingServer: !process.env.CI && !!process.env.E2E_REUSE_SERVERS,
      timeout: 30_000,
      env: {
        ...process.env,
        E2E_BACKEND_PORT: String(BACKEND_PORT),
        E2E_FRONTEND_ORIGIN: BASE_URL,
      },
    },
    {
      command: `npx next start -H 127.0.0.1 -p ${FRONTEND_PORT}`,
      cwd: __dirname,
      url: BASE_URL,
      reuseExistingServer: !process.env.CI && !!process.env.E2E_REUSE_SERVERS,
      timeout: 30_000,
    },
  ],
});
