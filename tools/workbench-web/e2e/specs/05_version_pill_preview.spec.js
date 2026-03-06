const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
    auditA11ySnapshot,
} = require('../helpers/workbenchTest');

test('version pill preview shows version bar and can be dismissed', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);

    const appValues = await appSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        await page.waitForTimeout(300);
    }

    // ── Setup: ensure we start with a clean state, then create one draft ──
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareResetBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();

    // Apply a dry-run edit to create a version pill.
    await page.locator('#dryRun').check();
    await page.locator('#aiChangeRequest').fill('e2e-t5-marker');
    await page.locator('#aiProposeBtn').click();
    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await page.locator('#aiApplyBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Applied');

    const nonBasePills = page.locator('#versionPills .version-pill:not(.base-pill)');
    await expect.poll(async () => await nonBasePills.count()).toBeGreaterThan(0);

    await auditScreenshot(page, test.info(), 'after_creating_one_draft');

    // ── Test: version bar must NOT be visible before any pill is clicked ──
    const versionBar = page.locator('#sysVersionBar');
    await expect(versionBar).not.toBeVisible();

    await auditScreenshot(page, test.info(), 'before_preview_click');

    // Click the LAST (oldest) non-base pill to enter preview mode.
    await nonBasePills.last().click();
    await expect(versionBar).toBeVisible();

    // Regression: diff overlay must start below the version bar (no visual overlap).
    const overlay = page.locator('#sysPromptDiffOverlay');
    await expect(overlay).toBeVisible();
    const barBox = await versionBar.boundingBox();
    const overlayBox = await overlay.boundingBox();
    expect(barBox, 'version bar bounding box must be available').toBeTruthy();
    expect(overlayBox, 'diff overlay bounding box must be available').toBeTruthy();
    expect(
        overlayBox.y,
        'diff overlay top should be at/under version bar bottom'
    ).toBeGreaterThanOrEqual(barBox.y + barBox.height - 0.5);

    await auditScreenshot(page, test.info(), 'preview_mode_visible');
    await auditA11ySnapshot(page, test.info(), 'preview_mode_visible');

    // Regression: diff overlay must not block other primary controls.
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareModalCloseBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();

    // The system prompt must be populated (not blank) after clicking a pill.
    const promptValue = await page.locator('#systemPrompt').inputValue();
    expect(promptValue.length, 'systemPrompt must not be blank after pill click').toBeGreaterThan(0);

    // Close button should dismiss the version bar WITHOUT applying.
    await page.locator('#sysVersionBarClose').click();
    await expect(versionBar).not.toBeVisible();

    await auditScreenshot(page, test.info(), 'preview_mode_dismissed');

    // Re-click a pill to enter preview, then re-click the ACTIVE pill to exit.
    // (Using .active avoids flakiness if the pills list re-renders/reorders.)
    await nonBasePills.last().click();
    await expect(versionBar).toBeVisible();
    const activePill = page.locator('#versionPills .version-pill.active');
    await expect(activePill).toHaveCount(1);
    await activePill.click();
    await expect(versionBar).not.toBeVisible();

    // ── Cleanup: reset draft history ──
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareResetBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();
});
