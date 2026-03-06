const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
} = require('../helpers/workbenchTest');

test('responsive layout: editors stack on narrow screens', async ({ page }) => {
    const systemPrompt = page.locator('#systemPrompt');
    const userTemplate = page.locator('#userTemplate');

    await page.setViewportSize({ width: 1100, height: 900 });
    await gotoAndWaitForBootstrap(page);
    await expect(systemPrompt).toBeVisible();
    await expect(userTemplate).toBeVisible();

    await auditScreenshot(page, test.info(), 'responsive_wide');

    // Wide: stacked layout.
    const wideA = await systemPrompt.boundingBox();
    const wideB = await userTemplate.boundingBox();
    expect(wideA && wideB).toBeTruthy();
    expect(Math.abs(wideA.x - wideB.x)).toBeLessThan(30);
    expect(wideA.y).toBeLessThan(wideB.y);

    const wideOverflow = await page.evaluate(() => {
        const el = document.documentElement;
        return el.scrollWidth - el.clientWidth;
    });
    expect(wideOverflow).toBeLessThanOrEqual(1);

    // Narrow: still stacked, no overflow.
    await page.setViewportSize({ width: 700, height: 900 });
    await gotoAndWaitForBootstrap(page);
    await expect(systemPrompt).toBeVisible();

    await auditScreenshot(page, test.info(), 'responsive_narrow');

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
