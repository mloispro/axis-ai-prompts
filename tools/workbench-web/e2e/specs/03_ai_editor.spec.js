const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
} = require('../helpers/workbenchTest');

test('dry-run AI editor propose/apply/undo works without API key @audit', async ({ page }) => {
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

    const nonBasePills = page.locator('#versionPills .version-pill:not(.base-pill)');
    await expect.poll(async () => await nonBasePills.count()).toBe(0);

    // Open the AI editor modal (either system prompt click or floating button).
    await page.locator('#systemPrompt').click();
    await expect(page.locator('#aiModal')).toBeVisible();
    await expect(page.locator('#aiBarLabel')).toBeVisible();
    await expect(page.locator('#aiBarLabel')).toContainText('AI');
    await expect(page.locator('#aiCallMeta')).toBeVisible();
    await expect(page.locator('#aiCallMeta')).toContainText('Model:');

    await auditScreenshot(page, test.info(), 'ai_editor_ready');

    // The AI bar always targets the system prompt in the new UI — no target toggle needed.
    const openerMarker = 'e2e-opener-marker';
    await page.locator('#aiChangeRequest').fill(openerMarker);
    await page.locator('#aiProposeBtn').click();

    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await expect(page.locator('#aiApplyBtn')).toBeEnabled();
    await expect(page.locator('#aiCallMeta')).toContainText('Dry run');
    await expect(page.locator('#aiCallMeta')).toContainText('$0');

    await auditScreenshot(page, test.info(), 'ai_editor_after_propose');

    const before = await page.locator('#systemPrompt').inputValue();

    await page.locator('#aiApplyBtn').click();
    // Workflow contract: Apply should return you to the main editor automatically.
    await expect(page.locator('#aiModal')).not.toBeVisible();
    // Apply triggers an async suite run; wait for the final state to avoid races
    // where later status updates overwrite delete-status assertions.
    await expect(page.locator('#aiEditStatus')).toContainText('suite done');

    await auditScreenshot(page, test.info(), 'after_apply_creates_version');

    // Workflow contract: after apply, latest WIP pill is active and highlights are visible.
    const versionBar = page.locator('#sysVersionBar');
    await expect(versionBar).not.toBeVisible();
    await expect(page.locator('#versionPills .version-pill.active:not(.base-pill)')).toHaveCount(1);
    await expect(page.locator('#sysPromptDiffOverlay')).toBeVisible();
    await expect
        .poll(async () => await page.locator('#sysPromptDiffOverlay span[class^="dl-add-hue-"]').count())
        .toBeGreaterThan(0);

    // The system prompt must contain DRY_RUN_EDIT after apply.
    const afterApply = await page.locator('#systemPrompt').inputValue();
    expect(afterApply).toContain('DRY_RUN_EDIT');
    expect(afterApply.length).toBeGreaterThan(before.length);

    // After apply, a non-base draft pill should exist.
    await expect.poll(async () => await nonBasePills.count()).toBeGreaterThan(0);

    // Delete the version via the compare modal Delete version button.
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();

    // Modal auto-selects the latest draft asynchronously; delete must become enabled.
    await expect(page.locator('#compareDeleteBtn')).toBeEnabled();

    await auditScreenshot(page, test.info(), 'compare_modal_open_before_delete');

    await page.locator('#compareDeleteBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();
    await expect(page.locator('#aiEditStatus')).toContainText('Version deleted');

    await auditScreenshot(page, test.info(), 'after_delete_version');

    const afterUndo = await page.locator('#systemPrompt').inputValue();
    expect(afterUndo).not.toContain('DRY_RUN_EDIT');

    // Switch to app_chat and verify mode-scoped apply still works.
    const modeValues2 = await modeSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (modeValues2.includes('app_chat')) {
        await modeSelect.selectOption('app_chat');
        await page.waitForTimeout(200);

        // Re-open AI editor modal for app_chat edit.
        await page.locator('#sysAiFab').click();
        await expect(page.locator('#aiModal')).toBeVisible();

        const appChatMarker = 'e2e-app-chat-marker';
        await page.locator('#aiChangeRequest').fill(appChatMarker);
        await page.locator('#aiProposeBtn').click();
        await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
        await expect(page.locator('#aiApplyBtn')).toBeEnabled();
        await page.locator('#aiApplyBtn').click();
        await expect(page.locator('#aiModal')).not.toBeVisible();
        await expect(page.locator('#aiEditStatus')).toContainText('suite done');

        // Workflow contract: after apply, latest WIP is selected and highlighted.
        await expect(page.locator('#sysVersionBar')).not.toBeVisible();
        await expect(page.locator('#versionPills .version-pill.active:not(.base-pill)')).toHaveCount(1);
        await expect(page.locator('#sysPromptDiffOverlay')).toBeVisible();
        await expect
            .poll(async () => await page.locator('#sysPromptDiffOverlay span[class^="dl-add-hue-"]').count())
            .toBeGreaterThan(0);

        // Verify the app_chat system prompt actually contains the dry-run edit.
        // (We use poll because apply triggers an async suite run before updating the textarea)
        await expect.poll(async () => await page.locator('#systemPrompt').inputValue()).toContain('DRY_RUN_EDIT');

        // Pills row must show at least the Base pill after apply + refreshDrafts.
        await expect(page.locator('#versionPills .base-pill')).toBeVisible();

        // Delete the app_chat version via compare modal.
        await page.locator('#compareBaseBtn').click();
        await expect(page.locator('#compareDeleteBtn')).toBeEnabled();
        await page.locator('#compareDeleteBtn').click();
        await expect(page.locator('#compareModal')).not.toBeVisible();
        await expect(page.locator('#aiEditStatus')).toContainText('Version deleted');
        await expect.poll(async () => await page.locator('#systemPrompt').inputValue()).not.toContain('DRY_RUN_EDIT');
    }
});
