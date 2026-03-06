const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
    auditA11ySnapshot,
} = require('../helpers/workbenchTest');

const APP_ID = 'rizzchatai';

async function apiResetApp(request) {
    await request.post('/api/edit/reset', { data: { appId: APP_ID } });
}

async function apiGetCandidate(request) {
    const res = await request.get(`/api/candidate-prompts?appId=${encodeURIComponent(APP_ID)}`);
    return await res.json();
}

async function apiApplyMarker(request, { targetKey, mode, marker }) {
    const cand = await apiGetCandidate(request);
    const currentText = cand && cand.prompts ? cand.prompts[targetKey] : '';
    if (typeof currentText !== 'string') throw new Error(`candidate missing prompts.${targetKey}`);

    const updatedText = `${currentText}\n\n${marker}`;

    await request.post('/api/edit/apply', {
        data: {
            appId: APP_ID,
            mode,
            model: 'gpt-5-mini',
            targetKey,
            updatedText,
            selfCheck: true,
            changeRequest: marker,
            notes: 'e2e: hue cycle',
        },
    });
}

test('multi-draft pills cycle hues and preview bar hue matches pill @audit', async ({ page, request }) => {
    await apiResetApp(request);

    // Create enough drafts to force at least one full hue cycle (8 hues).
    for (let i = 1; i <= 10; i++) {
        await apiApplyMarker(request, {
            targetKey: 'openerSystem',
            mode: 'opener',
            marker: `e2e-hue-cycle v${i}`,
        });
    }

    await gotoAndWaitForBootstrap(page);

    // Select the known app and wait for baselines to load.
    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);
    await appSelect.selectOption(APP_ID);
    await page.waitForResponse(r => r.url().includes('/api/baselines') && r.status() === 200);

    const modeSelect = page.locator('#modeSelect');
    await expect.poll(async () => await modeSelect.locator('option').count()).toBeGreaterThan(0);
    await modeSelect.selectOption('opener');
    await page.waitForTimeout(200);

    const nonBasePills = page.locator('#versionPills .version-pill:not(.base-pill)');
    await expect.poll(async () => await nonBasePills.count()).toBe(10);

    // Active pill should be the newest version (v10).
    const active = page.locator('#versionPills .version-pill.active:not(.base-pill)');
    await expect(active).toHaveCount(1);
    await expect(active).toHaveAttribute('data-version-num', '10');

    // Validate that each pill carries the expected hue class derived from its version number.
    const pillMeta = await nonBasePills.evaluateAll(els =>
        els.map(el => ({
            versionNum: String(el.dataset.versionNum || ''),
            className: String(el.className || ''),
        }))
    );

    for (const p of pillMeta) {
        const n = parseInt(p.versionNum, 10);
        expect(Number.isFinite(n) && n >= 1, `pill versionNum must be 1+ (got ${p.versionNum})`).toBeTruthy();
        const expectedHue = (n - 1) % 8;
        expect(
            p.className,
            `pill v${n} should include vp-hue-${expectedHue}`
        ).toContain(`vp-hue-${expectedHue}`);
    }

    await auditScreenshot(page, test.info(), 'multi_draft_hue_cycle_ready');

    // Pick a pill that wraps the hue palette (v9 -> hue 0) and ensure preview bar hue matches.
    const v9 = page.locator('#versionPills .version-pill:not(.base-pill)[data-version-num="9"]');
    await expect(v9).toBeVisible();
    // Capture pill background BEFORE it becomes active (active state intentionally darkens).
    const pillBg = await v9.evaluate(el => getComputedStyle(el).backgroundColor);
    await v9.click();

    const versionBar = page.locator('#sysVersionBar');
    await expect(versionBar).toBeVisible();

    const barBg = await versionBar.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(barBg, 'preview version bar background should match pill background').toBe(pillBg);

    await auditScreenshot(page, test.info(), 'multi_draft_preview_hue_matches');
    await auditA11ySnapshot(page, test.info(), 'multi_draft_preview_hue_matches');

    // Cleanup so later specs start clean even if global teardown is skipped.
    await apiResetApp(request);
});
