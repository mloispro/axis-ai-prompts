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
            notes: 'e2e: mode switch',
        },
    });
}

async function expectPillCount(page, expectedNonBase) {
    const base = page.locator('#versionPills .base-pill');
    await expect(base).toBeVisible();

    const nonBase = page.locator('#versionPills .version-pill:not(.base-pill)');
    await expect.poll(async () => await nonBase.count()).toBe(expectedNonBase);

    if (expectedNonBase > 0) {
        const active = page.locator('#versionPills .version-pill.active:not(.base-pill)');
        await expect(active).toHaveCount(1);
        await expect(active).toHaveAttribute('data-version-num', String(expectedNonBase));
    }
}

test('mode switching filters version pills by mode @audit', async ({ page, request }) => {
    await apiResetApp(request);

    // Create minimal per-mode history.
    await apiApplyMarker(request, {
        targetKey: 'openerSystem',
        mode: 'opener',
        marker: 'e2e-mode opener v1',
    });
    await apiApplyMarker(request, {
        targetKey: 'openerSystem',
        mode: 'opener',
        marker: 'e2e-mode opener v2',
    });
    await apiApplyMarker(request, {
        targetKey: 'appChatSystem',
        mode: 'app_chat',
        marker: 'e2e-mode app_chat v1',
    });
    await apiApplyMarker(request, {
        targetKey: 'regChatSystem',
        mode: 'reg_chat',
        marker: 'e2e-mode reg_chat v1',
    });

    await gotoAndWaitForBootstrap(page);

    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);
    await appSelect.selectOption(APP_ID);
    await page.waitForResponse(r => r.url().includes('/api/baselines') && r.status() === 200);

    const modeSelect = page.locator('#modeSelect');
    await expect.poll(async () => await modeSelect.locator('option').count()).toBeGreaterThan(0);

    await modeSelect.selectOption('opener');
    await page.waitForTimeout(200);
    await expectPillCount(page, 2);

    await auditScreenshot(page, test.info(), 'mode_opener_pills');

    await modeSelect.selectOption('app_chat');
    await page.waitForTimeout(200);
    await expectPillCount(page, 1);

    await auditScreenshot(page, test.info(), 'mode_app_chat_pills');

    await modeSelect.selectOption('reg_chat');
    await page.waitForTimeout(200);
    await expectPillCount(page, 1);

    await auditScreenshot(page, test.info(), 'mode_reg_chat_pills');

    await apiResetApp(request);
});
