import { defineConfig } from "@playwright/test";

/* The end-to-end suite: the real app in the system's Chrome, against an isolated stack - a backend on 5002 and a
   Vite server on 5183 - that Playwright starts and stops itself. The backend keeps one active graph, so the tests
   run one at a time. Before any test, global-setup.js writes the expected values the specs check against. */
export default defineConfig({
    testDir: "./e2e",
    outputDir: "./e2e/.results",
    globalSetup: "./e2e/global-setup.js",
    workers: 1,
    fullyParallel: false,
    timeout: 90_000,
    expect: { timeout: 15_000 },
    retries: 0,
    reporter: [["list"], ["html", { outputFolder: "e2e/.report", open: "never" }]],
    use: {
        baseURL: "http://localhost:5183",
        channel: "chrome",
        viewport: { width: 1600, height: 1000 },
        trace: "retain-on-failure",
        screenshot: "only-on-failure",
    },
    webServer: [
        {
            command: ".venv/bin/python -c \"from app import app; app.run(host='127.0.0.1', port=5002, use_reloader=False)\"",
            cwd: "..",
            url: "http://127.0.0.1:5002/",
            reuseExistingServer: true,
            timeout: 120_000,
        },
        {
            command: "npx vite --config e2e/vite.e2e.config.js",
            url: "http://localhost:5183/",
            reuseExistingServer: true,
            timeout: 120_000,
        },
    ],
});
