// @ts-check
const { defineConfig } = require('playwright/test');

const port = String(process.env.WORKBENCH_PORT || '7540');

module.exports = defineConfig({
    testDir: './e2e',
    globalTeardown: './e2e/global-teardown.js',
    // The workbench mutates local state files (candidate/history). Running in
    // parallel across spec files can cause file-lock errors on Windows.
    workers: 1,
    timeout: 60_000,
    expect: { timeout: 10_000 },
    use: {
        baseURL: `http://127.0.0.1:${port}`,
        headless: true,
    },
    webServer: {
        command: `powershell -NoProfile -ExecutionPolicy Bypass -File launcher.ps1 -Mode serve -Port ${port}`,
        url: `http://127.0.0.1:${port}/api/apps`,
        reuseExistingServer: true,
        timeout: 60_000,
    },
    reporter: [['list']],
});
