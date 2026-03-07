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

function buildScrollPad(versionNum, lineCount) {
    const n = Math.max(1, parseInt(lineCount, 10) || 1);
    const lines = [];
    for (let i = 1; i <= n; i++) {
        lines.push(`e2e-scroll-pad v${versionNum} line ${String(i).padStart(3, '0')}`);
    }
    return lines.join('\n');
}

async function apiApplyPad(request, { targetKey, mode, versionNum, lineCount }) {
    const cand = await apiGetCandidate(request);
    const currentText = cand && cand.prompts ? cand.prompts[targetKey] : '';
    if (typeof currentText !== 'string') throw new Error(`candidate missing prompts.${targetKey}`);

    const pad = buildScrollPad(versionNum, lineCount);
    const updatedText = `${currentText}\n\n${pad}`;

    await request.post('/api/edit/apply', {
        data: {
            appId: APP_ID,
            mode,
            model: 'gpt-5-mini',
            targetKey,
            updatedText,
            selfCheck: true,
            changeRequest: `e2e-scroll-pad v${versionNum}`,
            notes: 'e2e: pill switching + scroll audit',
        },
    });
}

async function getScrollTops(page) {
    return await page.evaluate(() => {
        const overlay = document.getElementById('sysPromptDiffOverlay');
        const ta = document.getElementById('systemPrompt');
        return {
            overlayVisible: !!(overlay && overlay.classList.contains('visible')),
            overlayScrollTop: overlay ? overlay.scrollTop : null,
            textareaScrollTop: ta ? ta.scrollTop : null,
        };
    });
}

async function scrollOverlayToBottom(page) {
    await page.evaluate(() => {
        const overlay = document.getElementById('sysPromptDiffOverlay');
        if (!overlay) return;
        overlay.scrollTop = overlay.scrollHeight;
    });
}

test('switching WIP pills while scrolled behaves sanely @audit', async ({ page, request }, testInfo) => {
    await apiResetApp(request);

    // Create multiple drafts and enough lines to require scrolling.
    await apiApplyPad(request, { targetKey: 'openerSystem', mode: 'opener', versionNum: 1, lineCount: 90 });
    await apiApplyPad(request, { targetKey: 'openerSystem', mode: 'opener', versionNum: 2, lineCount: 90 });
    await apiApplyPad(request, { targetKey: 'openerSystem', mode: 'opener', versionNum: 3, lineCount: 90 });

    await gotoAndWaitForBootstrap(page);

    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);
    await appSelect.selectOption(APP_ID);

    const modeSelect = page.locator('#modeSelect');
    await expect.poll(async () => await modeSelect.locator('option').count()).toBeGreaterThan(0);
    await modeSelect.selectOption('opener');
    await page.waitForTimeout(250);

    const nonBasePills = page.locator('#versionPills .version-pill:not(.base-pill)');
    await expect.poll(async () => await nonBasePills.count()).toBe(3);

    const active = page.locator('#versionPills .version-pill.active:not(.base-pill)');
    await expect(active).toHaveCount(1);
    await expect(active).toHaveAttribute('data-version-num', '3');

    const versionBar = page.locator('#sysVersionBar');
    await expect(versionBar).not.toBeVisible();

    const overlay = page.locator('#sysPromptDiffOverlay');
    await expect(overlay).toBeVisible();

    // Ensure we actually have hue spans before we start scrolling.
    await expect
        .poll(async () => await page.locator('#sysPromptDiffOverlay span[class^="dl-add-hue-"]').count())
        .toBeGreaterThan(0);

    await auditScreenshot(page, testInfo, 'pill_scroll_ready_latest_wip');

    // Scroll to bottom where the v1/v2/v3 pad text exists (this is where attribution/highlights are visible).
    await scrollOverlayToBottom(page);
    await page.waitForTimeout(200);
    await auditScreenshot(page, testInfo, 'pill_scroll_latest_wip_bottom');

    // UX probe: with overlay present, does clicking the visible prompt area still open the AI modal?
    // (User expectation based on the hint text: "click prompt or AI Edit".)
    await overlay.click({ position: { x: 40, y: 40 } });
    const modalOpensFromOverlayClick = await page.locator('#aiModal').isVisible();
    if (modalOpensFromOverlayClick) {
        await page.locator('#aiModalCloseBtn').click();
        await expect(page.locator('#aiModal')).not.toBeVisible();
    }
    await testInfo.attach('overlay_click_opens_ai_modal.json', {
        body: Buffer.from(JSON.stringify({ modalOpensFromOverlayClick }, null, 2), 'utf-8'),
        contentType: 'application/json',
    });

    // Scroll down in the overlay.
    await overlay.evaluate(el => { el.scrollTop = 800; });
    await page.waitForTimeout(150);
    await auditScreenshot(page, testInfo, 'pill_scroll_latest_wip_scrolled');

    // Enter preview mode on v2 while scrolled.
    const v2 = page.locator('#versionPills .version-pill:not(.base-pill)[data-version-num="2"]');
    await v2.click();
    await expect(versionBar).toBeVisible();

    // Scroll again in preview (overlay remains the scroll surface).
    await overlay.evaluate(el => { el.scrollTop = 800; });
    await page.waitForTimeout(150);
    await auditScreenshot(page, testInfo, 'pill_scroll_preview_v2_scrolled');
    await auditA11ySnapshot(page, testInfo, 'pill_scroll_preview_v2_scrolled');

    await scrollOverlayToBottom(page);
    await page.waitForTimeout(200);
    await auditScreenshot(page, testInfo, 'pill_scroll_preview_v2_bottom');

    // Exit preview by re-clicking the active pill.
    const activePillInPreview = page.locator('#versionPills .version-pill.active:not(.base-pill)');
    await expect(activePillInPreview).toHaveCount(1);
    await activePillInPreview.click();
    await expect(versionBar).not.toBeVisible();

    await page.waitForTimeout(150);
    await auditScreenshot(page, testInfo, 'pill_scroll_back_to_latest_wip_after_exit');

    await scrollOverlayToBottom(page);
    await page.waitForTimeout(200);
    await auditScreenshot(page, testInfo, 'pill_scroll_latest_wip_bottom_after_exit');

    // Attach scrollTop diagnostics so we can reason about what happened.
    const tops = await getScrollTops(page);
    await testInfo.attach('scroll_tops.json', {
        body: Buffer.from(JSON.stringify(tops, null, 2), 'utf-8'),
        contentType: 'application/json',
    });

    // Cleanup.
    await apiResetApp(request);
});
