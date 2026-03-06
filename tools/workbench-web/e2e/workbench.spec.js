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

// ── Test 1: Bootstrap ─────────────────────────────────────────────────
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
    await expect.poll(async () => await modelSelect.locator('option').count()).toBeGreaterThan(0);

    // System prompt is read-only in the new UI (edited via AI bar only).
    const systemPrompt = page.locator('#systemPrompt');
    await expect(systemPrompt).toBeVisible();
    const isReadOnly = await systemPrompt.getAttribute('readonly');
    expect(isReadOnly).not.toBeNull();

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

// ── Test 2: Dry-run suite ─────────────────────────────────────────────
test('dry-run suite renders results without API key', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

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

// ── Test 3: AI propose/apply/undo ─────────────────────────────────────
test('dry-run AI editor propose/apply/undo works without API key', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

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

    // Start from clean state — open compare modal and use Reset to Base button.
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareResetBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();
    await expect(page.locator('#aiEditStatus')).toHaveText('Reset');
    await expect.poll(async () => await page.locator('#systemPrompt').inputValue()).not.toContain('DRY_RUN_EDIT');

    // The AI bar always targets the system prompt in the new UI — no target toggle needed.
    const openerMarker = 'e2e-opener-marker';
    await page.locator('#aiChangeRequest').fill(openerMarker);
    await page.locator('#aiProposeBtn').click();

    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await expect(page.locator('#aiApplyBtn')).toBeEnabled();

    const before = await page.locator('#systemPrompt').inputValue();

    await page.locator('#aiApplyBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Applied');
    await expect(page.locator('#status')).toContainText('Done');

    // The system prompt must contain DRY_RUN_EDIT after apply.
    const afterApply = await page.locator('#systemPrompt').inputValue();
    expect(afterApply).toContain('DRY_RUN_EDIT');
    expect(afterApply.length).toBeGreaterThan(before.length);

    // At least one pill should reference the opener marker in its title.
    // (pill count itself isn't asserted — history cap of 50 can cause net-zero change)
    await expect.poll(async () => {
        const titles = await page.locator('#versionPills .version-pill').evaluateAll(
            btns => btns.map(b => b.getAttribute('title') || '')
        );
        return titles.some(t => t.includes(openerMarker));
    }).toBe(true);

    // Delete the version via the compare modal Delete version button.
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareDeleteBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();
    await expect(page.locator('#aiEditStatus')).toContainText('Version deleted');
    const afterUndo = await page.locator('#systemPrompt').inputValue();
    expect(afterUndo).not.toContain('DRY_RUN_EDIT');

    // Switch to app_chat and verify mode-scoped apply still works.
    const modeValues2 = await modeSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (modeValues2.includes('app_chat')) {
        await modeSelect.selectOption('app_chat');
        await page.waitForTimeout(200);

        const appChatMarker = 'e2e-app-chat-marker';
        await page.locator('#aiChangeRequest').fill(appChatMarker);
        await page.locator('#aiProposeBtn').click();
        await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
        await expect(page.locator('#aiApplyBtn')).toBeEnabled();
        await page.locator('#aiApplyBtn').click();
        await expect(page.locator('#aiEditStatus')).toContainText('Applied');

        // Verify the app_chat system prompt actually contains the dry-run edit.
        // (We use poll because apply triggers an async suite run before updating the textarea)
        await expect.poll(async () => await page.locator('#systemPrompt').inputValue()).toContain('DRY_RUN_EDIT');

        // Pills row must show at least the Base pill after apply + refreshDrafts.
        await expect(page.locator('#versionPills .base-pill')).toBeVisible();

        // Delete the app_chat version via compare modal.
        await page.locator('#compareBaseBtn').click();
        await page.locator('#compareDeleteBtn').click();
        await expect(page.locator('#compareModal')).not.toBeVisible();
        await expect(page.locator('#aiEditStatus')).toContainText('Version deleted');
        await expect.poll(async () => await page.locator('#systemPrompt').inputValue()).not.toContain('DRY_RUN_EDIT');
    }
});

// ── Test 4: Compare modal ─────────────────────────────────────────────
test('compare modal opens with base text and closes', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);

    const appValues = await appSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        // Wait for /api/baselines to resolve so baseSystemText is populated.
        await page.waitForResponse(r => r.url().includes('/api/baselines') && r.status() === 200);
        await page.waitForTimeout(200);
    }

    // Modal should be hidden initially.
    const modal = page.locator('#compareModal');
    await expect(modal).not.toBeVisible();

    // Click "vs Base" button.
    await page.locator('#compareBaseBtn').click();
    await expect(modal).toBeVisible();

    // Base column must have real text (not empty) after /api/baselines loaded.
    const baseTextContent = await page.locator('#compareBaseText').textContent();
    expect((baseTextContent || '').trim().length).toBeGreaterThan(10);

    // Current column must also have real text.
    const currentTextContent = await page.locator('#compareCurrentText').textContent();
    expect((currentTextContent || '').trim().length).toBeGreaterThan(10);

    // Close via the X button.
    await page.locator('#compareModalCloseBtn').click();
    await expect(modal).not.toBeVisible();
});

// ── Test 5: Version pill preview / restore / cancel ───────────────────
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

    // ── Test: version bar must NOT be visible before any pill is clicked ──
    const versionBar = page.locator('#sysVersionBar');
    await expect(versionBar).not.toBeVisible();

    // Click the LAST (oldest) non-base pill to enter preview mode.
    await nonBasePills.last().click();
    await expect(versionBar).toBeVisible();

    // The system prompt must be populated (not blank) after clicking a pill.
    const promptValue = await page.locator('#systemPrompt').inputValue();
    expect(promptValue.length, 'systemPrompt must not be blank after pill click').toBeGreaterThan(0);

    // Close button should dismiss the version bar WITHOUT applying.
    await page.locator('#sysVersionBarClose').click();
    await expect(versionBar).not.toBeVisible();

    // Re-click a pill to enter preview, then re-click the SAME pill to exit (F2 behaviour).
    await nonBasePills.last().click();
    await expect(versionBar).toBeVisible();
    await nonBasePills.last().click(); // re-click same active pill → exits preview
    await expect(versionBar).not.toBeVisible();

    // ── Cleanup: reset draft history ──
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareResetBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();
});

// ── Test 6: Responsive layout ─────────────────────────────────────────
test('responsive layout: editors stack on narrow screens', async ({ page }) => {
    const systemPrompt = page.locator('#systemPrompt');
    const userTemplate = page.locator('#userTemplate');

    await page.setViewportSize({ width: 1100, height: 900 });
    await gotoAndWaitForBootstrap(page);
    await expect(systemPrompt).toBeVisible();
    await expect(userTemplate).toBeVisible();

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

// ── N2: Cleanup \u2014 reset draft history after all tests ──────────────────
test.afterAll(async ({ request }) => {
    try {
        await request.post('/api/edit/reset', {
            data: { appId: 'rizzchatai' },
        });
    } catch (_) {
        // best-effort cleanup \u2014 ignore errors
    }
});
