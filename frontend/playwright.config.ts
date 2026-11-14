import { defineConfig, devices } from "@playwright/test";

/**
 * Tests E2E du ticketing — environnement LOCAL uniquement (jamais la production).
 * Django (settings e2e : SQLite jetable, Celery synchrone, IA désactivée) sur :8010,
 * Vite sur :5180 (relais /api vers :8010). La base est recréée à chaque lancement.
 *
 *   npm run e2e            (Python : ../venv/bin/python, ou E2E_PYTHON=…)
 */
const PY = process.env.E2E_PYTHON ?? "./venv/bin/python";
const DJANGO_ENV = {
  DJANGO_SETTINGS_MODULE: "ProjectFlow.settings.e2e",
  ...(process.platform === "darwin" ? { DYLD_FALLBACK_LIBRARY_PATH: process.env.DYLD_FALLBACK_LIBRARY_PATH ?? "/opt/homebrew/lib" } : {}),
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5180", trace: "retain-on-failure", screenshot: "only-on-failure", locale: "fr-FR", timezoneId: "Africa/Abidjan" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: [
        "rm -rf frontend/e2e/.state && mkdir -p frontend/e2e/.state",
        `${PY} manage.py migrate --noinput -v 0`,
        `${PY} manage.py e2e_fixtures seed --out frontend/e2e/.state/fixtures.json --webhook-url http://127.0.0.1:8099/hook`,
        `exec ${PY} manage.py runserver 127.0.0.1:8010 --noreload`,
      ].join(" && "),
      cwd: "..",
      env: DJANGO_ENV,
      url: "http://127.0.0.1:8010/api/v1/auth/me/",
      timeout: 240_000,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "npx vite --host 127.0.0.1 --port 5180 --strictPort",
      env: { DJANGO_ORIGIN: "http://127.0.0.1:8010" },
      url: "http://127.0.0.1:5180/app/login",
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "ignore",
    },
  ],
});
