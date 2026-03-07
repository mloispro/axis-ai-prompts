// @ts-check
const { defineConfig } = require('playwright/test');

// IMPORTANT: tests mutate workbench state and call /api/edit/reset.
// Default to an isolated port so we don't clobber a developer's running workbench.
const port = String(process.env.WORKBENCH_PORT || '7541');
process.env.WORKBENCH_PORT = port;

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
        // Use an isolated state directory so e2e runs never wipe local WIP drafts/candidate.
        // (cmd.exe syntax works consistently across Windows shells.)
        command: `cmd /c "set WORKBENCH_STATE_DIR=state-e2e&& powershell -NoProfile -ExecutionPolicy Bypass -File launcher.ps1 -Mode serve -Port ${port}"`,
        url: `http://127.0.0.1:${port}/api/apps`,
        // Never reuse an already-running server; it may be pointed at a real WIP state dir.
        reuseExistingServer: false,
        timeout: 60_000,
    },
    reporter: [['list']],
});
