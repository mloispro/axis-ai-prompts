const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
} = require('../helpers/workbenchTest');

const APP_ID = 'rizzchatai';

async function apiResetApp(request) {
    await request.post('/api/edit/reset', { data: { appId: APP_ID } });
}

test('publish button is disabled until a clean suite run completes @audit', async ({ page, request }) => {
    await apiResetApp(request);

    await gotoAndWaitForBootstrap(page);

    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);
    await appSelect.selectOption(APP_ID);
    await page.waitForResponse(r => r.url().includes('/api/baselines') && r.status() === 200);

    // Ensure dry-run is enabled so no OpenAI calls happen.
    await page.locator('#dryRun').check();

    // Before any suite run, publish must be disabled.
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();

    const publishBtn = page.locator('#comparePublishBtn');
    await expect(publishBtn).toBeDisabled();
    await expect(publishBtn).toHaveAttribute('title', /Run the suite first/i);

    await auditScreenshot(page, test.info(), 'publish_disabled_before_suite');

    await page.locator('#compareModalCloseBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();

    // Run the suite in dry-run mode; a clean run should make publish eligible.
    await page.locator('#runSuiteBtn').click();
    await expect(page.locator('#status')).toContainText('Done');

    await auditScreenshot(page, test.info(), 'suite_done_before_publish');

    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();

    await expect(publishBtn).toBeEnabled();
    await expect(publishBtn).toHaveAttribute('title', /Publish candidate/i);

    await auditScreenshot(page, test.info(), 'publish_enabled_after_clean_suite');

    await page.locator('#compareModalCloseBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();

    await apiResetApp(request);
});
