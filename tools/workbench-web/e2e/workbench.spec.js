const { test, expect } = require('playwright/test');

test('loads apps, models, and prompt editors', async ({ page }) => {
    await page.goto('/');

    await expect(page.locator('h1')).toContainText('Prompt Workbench Web');

    const appSelect = page.locator('#appSelect');
    await expect(appSelect).toBeVisible();
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);

    const modeSelect = page.locator('#modeSelect');
    await expect(modeSelect).toBeVisible();
    await expect.poll(async () => await modeSelect.locator('option').count()).toBeGreaterThan(0);

    const modelSelect = page.locator('#modelSelect');
    await expect(modelSelect).toBeVisible();
    await expect(modelSelect.locator('option')).toHaveCount(4);

    await expect(page.locator('#systemPrompt')).toBeVisible();
    await expect(page.locator('#userTemplate')).toBeVisible();
    await expect(page.locator('#fixtureSelect')).toBeVisible();

    // Ensure prompts are actually pre-populated for a known app.
    // This catches the regression where candidate prompts load as blanks.
    const appValues = await appSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        // Allow async app change + candidate load.
        await page.waitForTimeout(200);

        const systemVal = await page.locator('#systemPrompt').inputValue();
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

test('dry-run suite renders results without API key', async ({ page }) => {
    await page.goto('/');

    // Ensure dry-run is enabled so no OpenAI calls happen.
    await page.locator('#dryRun').check();

    await page.locator('#runSuiteBtn').click();

    // Wait for completion.
    await expect(page.locator('#status')).toContainText('Done');

    await expect(page.locator('#results')).toContainText('[DRY_RUN]');
    await expect(page.locator('#results')).toContainText('variant=baseline');
    await expect(page.locator('#results')).toContainText('variant=candidate');
});

test('dry-run AI editor propose/apply/undo works without API key', async ({ page }) => {
    await page.goto('/');

    // Enable dry-run so propose does not call OpenAI.
    await page.locator('#dryRun').check();

    const appSelect = page.locator('#appSelect');
    const modeSelect = page.locator('#modeSelect');

    const appValues = await appSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        await page.waitForTimeout(200);
    }

    const modeValues = await modeSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (modeValues.includes('opener')) {
        await modeSelect.selectOption('opener');
        await page.waitForTimeout(200);
    }

    // Ensure test starts from a clean candidate state so Undo has a known baseline.
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#aiResetBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Reset');
    await expect.poll(async () => await page.locator('#systemPrompt').inputValue()).not.toContain('DRY_RUN_EDIT');

    // Clear edit history selection so the Diff pane reflects the AI proposal.
    await page.locator('#draftSelect').selectOption('');

    const targetKey = page.locator('#aiTargetKey');
    await expect.poll(async () => await targetKey.locator('option').count()).toBeGreaterThan(0);

    // Pick the system key if present.
    const keyValues = await targetKey.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (keyValues.includes('openerSystem')) {
        await targetKey.selectOption('openerSystem');
    } else {
        await targetKey.selectOption(keyValues[0]);
    }

    await page.locator('#aiChangeRequest').fill('Append a dry-run marker for testing');
    await page.locator('#aiProposeBtn').click();

    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await expect(page.locator('#aiApplyBtn')).toBeEnabled();

    const before = await page.locator('#systemPrompt').inputValue();

    await page.locator('#aiApplyBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Applied');
    await expect(page.locator('#status')).toContainText('Done');

    const afterApply = await page.locator('#systemPrompt').inputValue();
    expect(afterApply).toContain('DRY_RUN_EDIT');
    expect(afterApply.length).toBeGreaterThan(before.length);

    await page.locator('#aiUndoBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Undone');
    const afterUndo = await page.locator('#systemPrompt').inputValue();
    expect(afterUndo).not.toContain('DRY_RUN_EDIT');
});

test('responsive layout: editors stack on narrow screens', async ({ page }) => {
    const systemPrompt = page.locator('#systemPrompt');
    const userTemplate = page.locator('#userTemplate');

    await page.setViewportSize({ width: 1100, height: 900 });
    await page.goto('/');
    await expect(systemPrompt).toBeVisible();
    await expect(userTemplate).toBeVisible();

    // Wide: expect side-by-side layout.
    const wideA = await systemPrompt.boundingBox();
    const wideB = await userTemplate.boundingBox();
    expect(wideA && wideB).toBeTruthy();
    expect(Math.abs(wideA.y - wideB.y)).toBeLessThan(30);
    expect(wideA.x).toBeLessThan(wideB.x);

    const wideOverflow = await page.evaluate(() => {
        const el = document.documentElement;
        return el.scrollWidth - el.clientWidth;
    });
    expect(wideOverflow).toBeLessThanOrEqual(1);

    // Narrow: breakpoint at 720px should stack the 2 editors vertically.
    await page.setViewportSize({ width: 700, height: 900 });
    await page.goto('/');
    await expect(systemPrompt).toBeVisible();

    const narrowA = await systemPrompt.boundingBox();
    const narrowB = await userTemplate.boundingBox();
    expect(narrowA && narrowB).toBeTruthy();
    expect(Math.abs(narrowA.x - narrowB.x)).toBeLessThan(30);
    expect(narrowA.y).toBeLessThan(narrowB.y);

    const narrowOverflow = await page.evaluate(() => {
        const el = document.documentElement;
        return el.scrollWidth - el.clientWidth;
    });
    expect(narrowOverflow).toBeLessThanOrEqual(1);
});
