const { test, expect } = require('playwright/test');

test('loads apps, models, and prompt editors', async ({ page }) => {
    await page.goto('/');

    await expect(page.locator('h1')).toContainText('Prompt Workbench Web');

    const appSelect = page.locator('#appSelect');
    await expect(appSelect).toBeVisible();
    expect(await appSelect.locator('option').count()).toBeGreaterThan(0);

    const modeSelect = page.locator('#modeSelect');
    await expect(modeSelect).toBeVisible();
    expect(await modeSelect.locator('option').count()).toBeGreaterThan(0);

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
