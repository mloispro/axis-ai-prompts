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
    await expect(page.locator('#userPrompt')).toBeVisible();

    // Ensure prompts are actually pre-populated for a known app.
    // This catches the regression where candidate prompts load as blanks.
    const appValues = await appSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        // Allow async app change + candidate load.
        await page.waitForTimeout(200);

        const systemVal = await page.locator('#systemPrompt').inputValue();
        expect(systemVal.trim().length).toBeGreaterThan(20);
    }
});

test('dry-run tune renders results without API key', async ({ page }) => {
    await page.goto('/');

    // Ensure dry-run is enabled so no OpenAI calls happen.
    await page.locator('#dryRun').check();

    await page.locator('#userPrompt').fill('Hello from Playwright');
    await page.locator('#runTuneBtn').click();

    // Wait for completion.
    await expect(page.locator('#status')).toContainText('Done');

    await expect(page.locator('#results')).toContainText('[DRY RUN]');
    await expect(page.locator('#results')).toContainText('Tokens —');
    await expect(page.locator('#results')).toContainText('Cost —');
});

test('responsive layout: editors stack on narrow screens', async ({ page }) => {
    const systemPrompt = page.locator('#systemPrompt');
    const userPrompt = page.locator('#userPrompt');

    await page.setViewportSize({ width: 1100, height: 900 });
    await page.goto('/');
    await expect(systemPrompt).toBeVisible();
    await expect(userPrompt).toBeVisible();

    // Wide: expect side-by-side layout.
    const wideA = await systemPrompt.boundingBox();
    const wideB = await userPrompt.boundingBox();
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
    const narrowB = await userPrompt.boundingBox();
    expect(narrowA && narrowB).toBeTruthy();
    expect(Math.abs(narrowA.x - narrowB.x)).toBeLessThan(30);
    expect(narrowA.y).toBeLessThan(narrowB.y);

    const narrowOverflow = await page.evaluate(() => {
        const el = document.documentElement;
        return el.scrollWidth - el.clientWidth;
    });
    expect(narrowOverflow).toBeLessThanOrEqual(1);
});
