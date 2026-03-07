const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
    auditA11ySnapshot,
} = require('../helpers/workbenchTest');

test('loads apps, models, and prompt editors @audit', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

    await auditScreenshot(page, test.info(), 'fresh_load');
    await auditA11ySnapshot(page, test.info(), 'fresh_load');

    await expect(page.locator('.topbar-title')).toContainText('Prompt Workbench');

    const appSelect = page.locator('#appSelect');
    await expect(appSelect).toBeVisible();
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);

    const modeSelect = page.locator('#modeSelect');
    await expect(modeSelect).toBeVisible();
    await expect.poll(async () => await modeSelect.locator('option').count()).toBeGreaterThan(0);

    const modelSelect = page.locator('#modelSelect');
    await expect(modelSelect).toBeVisible();
    await expect.poll(async () => await modelSelect.locator('option').count()).toBeGreaterThan(0);

    // System prompt is read-only in the new UI (edited via AI bar only).
    const systemPrompt = page.locator('#systemPrompt');
    await expect(systemPrompt).toBeVisible();
    const isReadOnly = await systemPrompt.getAttribute('readonly');
    expect(isReadOnly).not.toBeNull();

    // Floating AI button should be present on the system prompt.
    await expect(page.locator('#sysAiFab')).toBeVisible();

    // User template is minimized by default (expandable disclosure).
    await expect(page.locator('#userTemplateSection')).toBeVisible();
    await expect(page.locator('#userTemplateSection > summary')).toBeVisible();
    await expect(page.locator('#userTemplate')).toBeHidden();
    await page.locator('#userTemplateSection > summary').click();
    await expect(page.locator('#userTemplate')).toBeVisible();
    await expect(page.locator('#fixtureSelect')).toBeVisible();

    // Version pills row and compare button should be visible.
    await expect(page.locator('#versionPills')).toBeVisible();
    await expect(page.locator('#compareBaseBtn')).toBeVisible();

    // Base pill must always be present.
    await expect(page.locator('#versionPills .base-pill')).toBeVisible();

    // Ensure prompts are actually pre-populated for a known app.
    const appValues = await appSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        await page.waitForTimeout(300);

        const systemVal = await systemPrompt.inputValue();
        expect(systemVal.trim().length).toBeGreaterThan(20);

        // Preview should render when selecting a specific fixture.
        const modeValues = await modeSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
        if (modeValues.includes('opener')) {
            await modeSelect.selectOption('opener');
            await page.waitForTimeout(200);
        }

        const fixtureSelect = page.locator('#fixtureSelect');
        await expect.poll(async () => await fixtureSelect.locator('option').count()).toBeGreaterThan(1);

        const fixtureValues = await fixtureSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
        const firstFixture = fixtureValues.find(v => (v || '').trim().length > 0);
        if (firstFixture) {
            await fixtureSelect.selectOption(firstFixture);
            await expect(page.locator('#previewStatus')).toContainText('OK:');
            await expect(page.locator('#baselinePreviewUser')).toContainText(/\S/);
            await expect(page.locator('#candidatePreviewUser')).toContainText(/\S/);
        }
    }
});
