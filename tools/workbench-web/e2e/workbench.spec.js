const { test, expect } = require('playwright/test');

function attachDiagnostics(page) {
    page.on('pageerror', err => {
        console.log('[pageerror]', err && err.stack ? err.stack : String(err));
    });
    page.on('console', msg => {
        const t = msg.type();
        if (t === 'error' || t === 'warning') {
            console.log(`[console.${t}]`, msg.text());
        }
    });
    page.on('requestfailed', req => {
        const url = req.url();
        if (url.includes('/api/') || url.includes('/js/') || url.includes('/css/')) {
            console.log('[requestfailed]', url, req.failure() ? req.failure().errorText : '');
        }
    });
    page.on('response', res => {
        const url = res.url();
        if (res.status() >= 400 && (url.includes('/api/') || url.includes('/js/') || url.includes('/css/'))) {
            console.log(`[http${res.status()}]`, url);
        }
    });
}

async function gotoAndWaitForBootstrap(page) {
    // Install watchers before navigation so we don't miss early responses.
    const jsWait = page.waitForResponse(r => r.url().includes('/js/workbench.js') && r.status() === 200);
    const modelsWait = page.waitForResponse(r => r.url().includes('/api/models') && r.status() === 200);
    const appsWait = page.waitForResponse(r => r.url().includes('/api/apps') && r.status() === 200);

    await page.goto('/');
    await jsWait;
    await modelsWait;
    await appsWait;

    // If bootstrap failed, the page usually writes a top-level error into #status.
    const statusText = await page.locator('#status').textContent().catch(() => '');
    if ((statusText || '').trim().startsWith('Error:')) {
        throw new Error('UI bootstrap error: ' + statusText.trim());
    }
}

test.beforeEach(async ({ page }) => {
    attachDiagnostics(page);
});

test('loads apps, models, and prompt editors', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

    await expect(page.locator('.topbar-title')).toContainText('Prompt Workbench');

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
    await gotoAndWaitForBootstrap(page);

    // Wait for UI bootstrap (apps/modes/models) so click handlers have data.
    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);
    const modeSelect = page.locator('#modeSelect');
    await expect.poll(async () => await modeSelect.locator('option').count()).toBeGreaterThan(0);

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
    await gotoAndWaitForBootstrap(page);

    // Edit History (draftSelect) lives under the Advanced accordion.
    await page.locator('details.adv').evaluate(el => { el.open = true; });

    // Wait for UI bootstrap (apps/modes/models) before interacting.
    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);
    const modeSelect = page.locator('#modeSelect');
    await expect.poll(async () => await modeSelect.locator('option').count()).toBeGreaterThan(0);

    // Enable dry-run so propose does not call OpenAI.
    await page.locator('#dryRun').check();

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

    const getDraftOptions = async () => {
        const opts = await page.locator('#draftSelect option').evaluateAll(nodes => nodes.map(n => ({
            value: n.value || '',
            text: (n.textContent || '').trim(),
        })));
        return opts.filter(o => o.value);
    };

    const openerBefore = await getDraftOptions();

    // Ensure the underlying target-key select is populated (even though it's hidden).
    await expect.poll(async () => await page.locator('#aiTargetKey option').count()).toBeGreaterThan(0);

    // Target the system prompt via the visible pill UI.
    await page.locator('#aiTargetSysBtn').click();

    const openerMarker = 'e2e-opener-marker';
    await page.locator('#aiChangeRequest').fill(openerMarker);
    await page.locator('#aiProposeBtn').click();

    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await expect(page.locator('#aiApplyBtn')).toBeEnabled();

    const before = await page.locator('#systemPrompt').inputValue();

    await page.locator('#aiApplyBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Applied');
    await expect(page.locator('#status')).toContainText('Done');

    // Edit History should include a new opener snapshot, scoped/labeled by mode.
    const draftSelect = page.locator('#draftSelect');
    await expect.poll(async () => await draftSelect.locator('option').count()).toBeGreaterThan(1);
    const openerAfter = await getDraftOptions();
    const openerNew = openerAfter.filter(o => !openerBefore.some(b => b.value === o.value));
    expect(openerNew.length).toBeGreaterThan(0);
    expect(openerNew.map(o => o.text).join('\n')).toContain('[opener]');
    expect(openerNew.map(o => o.text).join('\n')).toContain(openerMarker);

    const afterApply = await page.locator('#systemPrompt').inputValue();
    expect(afterApply).toContain('DRY_RUN_EDIT');
    expect(afterApply.length).toBeGreaterThan(before.length);

    // Now switch to app_chat and apply a distinct edit; history dropdown should be mode-scoped.
    const modeValues2 = await modeSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (modeValues2.includes('app_chat')) {
        await modeSelect.selectOption('app_chat');
        await page.waitForTimeout(200);
    }

    const appChatBefore = await getDraftOptions();

    // After changing modes, re-target the system prompt via the visible pill UI.
    await page.locator('#aiTargetSysBtn').click();

    const appChatMarker = 'e2e-app-chat-marker';
    await page.locator('#aiChangeRequest').fill(appChatMarker);
    await page.locator('#aiProposeBtn').click();
    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await expect(page.locator('#aiApplyBtn')).toBeEnabled();
    await page.locator('#aiApplyBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Applied');
    await expect(page.locator('#status')).toContainText('Done');

    await expect.poll(async () => await draftSelect.locator('option').count()).toBeGreaterThan(1);
    const appChatAfter = await getDraftOptions();
    const appChatNew = appChatAfter.filter(o => !appChatBefore.some(b => b.value === o.value));
    expect(appChatNew.length).toBeGreaterThan(0);
    expect(appChatNew.map(o => o.text).join('\n')).toContain('[app_chat]');
    expect(appChatNew.map(o => o.text).join('\n')).toContain(appChatMarker);
    // Mode-scoped dropdown should not show opener's marker.
    expect(appChatAfter.map(o => o.text).join('\n')).not.toContain(openerMarker);

    await page.locator('#aiUndoBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Undone');
    const afterUndo = await page.locator('#systemPrompt').inputValue();
    expect(afterUndo).not.toContain('DRY_RUN_EDIT');
});

test('responsive layout: editors stack on narrow screens', async ({ page }) => {
    const systemPrompt = page.locator('#systemPrompt');
    const userTemplate = page.locator('#userTemplate');

    await page.setViewportSize({ width: 1100, height: 900 });
    await gotoAndWaitForBootstrap(page);
    await expect(systemPrompt).toBeVisible();
    await expect(userTemplate).toBeVisible();

    // Wide: stacked layout (chosen UX spec).
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

    // Narrow: still stacked, and should not overflow.
    await page.setViewportSize({ width: 700, height: 900 });
    await gotoAndWaitForBootstrap(page);
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
