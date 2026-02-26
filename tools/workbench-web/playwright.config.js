// @ts-check
const { defineConfig } = require('playwright/test');

const port = String(process.env.WORKBENCH_PORT || '8787');

module.exports = defineConfig({
    testDir: './e2e',
    timeout: 60_000,
    expect: { timeout: 10_000 },
    use: {
        baseURL: `http://127.0.0.1:${port}`,
        headless: true,
    },
    webServer: {
        command: `powershell -NoProfile -ExecutionPolicy Bypass -File serve.ps1 -Port ${port}`,
        url: `http://127.0.0.1:${port}/api/apps`,
        reuseExistingServer: true,
        timeout: 60_000,
    },
    reporter: [['list']],
});
