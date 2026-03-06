const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
    auditA11ySnapshot,
} = require('../helpers/workbenchTest');

test('compare modal opens with base text and closes', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);

    const appValues = await appSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        // Wait for /api/baselines to resolve so baseSystemText is populated.
        await page.waitForResponse(r => r.url().includes('/api/baselines') && r.status() === 200);
        await page.waitForTimeout(200);
    }

    // Modal should be hidden initially.
    const modal = page.locator('#compareModal');
    await expect(modal).not.toBeVisible();

    // Click "vs Base" button.
    await page.locator('#compareBaseBtn').click();
    await expect(modal).toBeVisible();

    // If there are no saved versions, delete must be disabled.
    // (If versions exist from a prior run, this will still pass because the modal selects one.)
    const pills = page.locator('#compareModalPills .version-pill');
    const deleteBtn = page.locator('#compareDeleteBtn');
    const pillCount = await pills.count();
    if (pillCount === 0) await expect(deleteBtn).toBeDisabled();
    else await expect(deleteBtn).toBeEnabled();

    await auditScreenshot(page, test.info(), 'compare_modal_open');
    await auditA11ySnapshot(page, test.info(), 'compare_modal_open');

    // Base column must have real text (not empty) after /api/baselines loaded.
    const baseTextContent = await page.locator('#compareBaseText').textContent();
    expect((baseTextContent || '').trim().length).toBeGreaterThan(10);

    // Current column must also have real text.
    const currentTextContent = await page.locator('#compareCurrentText').textContent();
    expect((currentTextContent || '').trim().length).toBeGreaterThan(10);

    // Close via the X button.
    await page.locator('#compareModalCloseBtn').click();
    await expect(modal).not.toBeVisible();
});
