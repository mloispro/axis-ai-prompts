const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
} = require('../helpers/workbenchTest');

test('dry-run suite renders results without API key', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

    await auditScreenshot(page, test.info(), 'dry_run_suite_ready');

    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);
    const modeSelect = page.locator('#modeSelect');
    await expect.poll(async () => await modeSelect.locator('option').count()).toBeGreaterThan(0);

    // Ensure dry-run is enabled so no OpenAI calls happen.
    await page.locator('#dryRun').check();

    await page.locator('#runSuiteBtn').click();

    // Wait for completion.
    await expect(page.locator('#status')).toContainText('Done');

    await expect(page.locator('#results')).toContainText('[DRY_RUN]');
    await expect(page.locator('#results')).toContainText('variant=baseline');
    await expect(page.locator('#results')).toContainText('variant=candidate');

    await auditScreenshot(page, test.info(), 'dry_run_suite_done');
});
