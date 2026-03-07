const {
    test,
    expect,
    gotoAndWaitForBootstrap,
    auditScreenshot,
    auditA11ySnapshot,
} = require('../helpers/workbenchTest');

test('version pill preview shows version bar and can be dismissed @audit', async ({ page }) => {
    await gotoAndWaitForBootstrap(page);

    const appSelect = page.locator('#appSelect');
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);

    const appValues = await appSelect.locator('option').evaluateAll(opts => opts.map(o => o.value));
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        await page.waitForTimeout(300);
    }

    // ── Setup: ensure we start with a clean state, then create two drafts ──
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareResetBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();

    // Apply dry-run edits to create multiple version pills.
    await page.locator('#dryRun').check();

    // AI editor is modal-based now.
    await page.locator('#sysAiFab').click();
    await expect(page.locator('#aiModal')).toBeVisible();

    await page.locator('#aiChangeRequest').fill('e2e-t5-marker-1');
    await page.locator('#aiProposeBtn').click();
    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await page.locator('#aiApplyBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Applied');

    // Apply auto-closes the modal.
    await expect(page.locator('#aiModal')).not.toBeVisible();

    // Re-open for the second apply.
    await page.locator('#sysAiFab').click();
    await expect(page.locator('#aiModal')).toBeVisible();

    await page.locator('#aiChangeRequest').fill('e2e-t5-marker-2');
    await page.locator('#aiProposeBtn').click();
    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await page.locator('#aiApplyBtn').click();
    await expect(page.locator('#aiEditStatus')).toContainText('Applied');

    // Apply auto-closes the modal.
    await expect(page.locator('#aiModal')).not.toBeVisible();

    const nonBasePills = page.locator('#versionPills .version-pill:not(.base-pill)');
    await expect.poll(async () => await nonBasePills.count()).toBeGreaterThanOrEqual(2);

    const livePromptValue = await page.locator('#systemPrompt').inputValue();
    const liveDryRunCount = (livePromptValue.match(/\[DRY_RUN_EDIT\]/g) || []).length;
    expect(liveDryRunCount, 'live prompt should include multiple DRY_RUN_EDIT blocks after two applies').toBeGreaterThanOrEqual(2);

    // Workflow contract: latest WIP pill is active by default, and highlights are visible.
    const activeWipPill = page.locator('#versionPills .version-pill.active:not(.base-pill)');
    await expect(activeWipPill).toHaveCount(1);
    await expect(activeWipPill).toHaveAttribute('data-version-num', '2');

    const versionBar = page.locator('#sysVersionBar');
    await expect(versionBar).not.toBeVisible();
    await expect(page.locator('#sysPromptDiffOverlay')).toBeVisible();
    await expect(page.locator('#sysPromptDiffOverlay .dl-del')).toHaveCount(0);
    await expect
        .poll(async () => await page.locator('#sysPromptDiffOverlay span[class^="dl-add-hue-"]').count())
        .toBeGreaterThan(0);

    await auditScreenshot(page, test.info(), 'after_creating_two_drafts');

    // Workflow contract: on load (fresh navigation) we still default to latest WIP + highlights.
    await gotoAndWaitForBootstrap(page);
    await expect.poll(async () => await appSelect.locator('option').count()).toBeGreaterThan(0);
    if (appValues.includes('rizzchatai')) {
        await appSelect.selectOption('rizzchatai');
        await page.waitForTimeout(300);
    }

    // Reload resets UI toggles; ensure dry-run stays on so later propose doesn't hit the network.
    await page.locator('#dryRun').check();

    const nonBasePillsAfterReload = page.locator('#versionPills .version-pill:not(.base-pill)');
    await expect.poll(async () => await nonBasePillsAfterReload.count()).toBeGreaterThanOrEqual(2);
    const activeAfterReload = page.locator('#versionPills .version-pill.active:not(.base-pill)');
    await expect(activeAfterReload).toHaveCount(1);
    await expect(activeAfterReload).toHaveAttribute('data-version-num', '2');
    await expect(page.locator('#sysVersionBar')).not.toBeVisible();
    await expect(page.locator('#sysPromptDiffOverlay')).toBeVisible();
    await expect(page.locator('#sysPromptDiffOverlay .dl-del')).toHaveCount(0);
    await expect
        .poll(async () => await page.locator('#sysPromptDiffOverlay span[class^="dl-add-hue-"]').count())
        .toBeGreaterThan(0);
    await auditScreenshot(page, test.info(), 'after_reload_defaults_to_latest_wip');

    // ── Test: version bar must NOT be visible before any pill is clicked ──
    await expect(versionBar).not.toBeVisible();

    await auditScreenshot(page, test.info(), 'before_preview_click');

    // Click the LAST (oldest) non-base pill to enter preview mode.
    await nonBasePills.last().click();
    await expect(versionBar).toBeVisible();

    // Previewed prompt text should differ from the live/latest prompt.
    const previewPromptValue = await page.locator('#systemPrompt').inputValue();
    const previewDryRunCount = (previewPromptValue.match(/\[DRY_RUN_EDIT\]/g) || []).length;
    expect(previewPromptValue, 'previewed prompt should differ from live prompt').not.toBe(livePromptValue);
    expect(previewDryRunCount, 'previewed (older) prompt should have fewer DRY_RUN_EDIT blocks than live').toBeLessThan(liveDryRunCount);

    // Regression: diff overlay must start below the version bar (no visual overlap).
    const overlay = page.locator('#sysPromptDiffOverlay');
    await expect(overlay).toBeVisible();
    await expect(overlay.locator('.dl-del')).toHaveCount(0);
    const barBox = await versionBar.boundingBox();
    const overlayBox = await overlay.boundingBox();
    expect(barBox, 'version bar bounding box must be available').toBeTruthy();
    expect(overlayBox, 'diff overlay bounding box must be available').toBeTruthy();
    expect(
        overlayBox.y,
        'diff overlay top should be at/under version bar bottom'
    ).toBeGreaterThanOrEqual(barBox.y + barBox.height - 0.5);

    await auditScreenshot(page, test.info(), 'preview_mode_visible');
    await auditA11ySnapshot(page, test.info(), 'preview_mode_visible');

    // Regression: diff overlay must not block other primary controls.
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareModalCloseBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();

    // The system prompt must be populated (not blank) after clicking a pill.
    const promptValue = await page.locator('#systemPrompt').inputValue();
    expect(promptValue.length, 'systemPrompt must not be blank after pill click').toBeGreaterThan(0);

    // Close button should dismiss the version bar WITHOUT applying.
    await page.locator('#sysVersionBarClose').click();
    await expect(versionBar).not.toBeVisible();

    await auditScreenshot(page, test.info(), 'preview_mode_dismissed');

    // Re-click a pill to enter preview, then re-click the ACTIVE pill to exit.
    // (Using .active avoids flakiness if the pills list re-renders/reorders.)
    await nonBasePills.last().click();
    await expect(versionBar).toBeVisible();
    const activePill = page.locator('#versionPills .version-pill.active');
    await expect(activePill).toHaveCount(1);
    await activePill.click();
    await expect(versionBar).not.toBeVisible();

    // Workflow regression: proposing a change while previewing must not clobber the live candidate.
    // Expected behavior: preview exits, and the live/latest prompt remains intact.
    await nonBasePills.last().click();
    await expect(versionBar).toBeVisible();
    const previewPromptValue2 = await page.locator('#systemPrompt').inputValue();
    const previewDryRunCount2 = (previewPromptValue2.match(/\[DRY_RUN_EDIT\]/g) || []).length;
    expect(previewDryRunCount2, 'previewed (older) prompt should have fewer DRY_RUN_EDIT blocks than live').toBeLessThan(liveDryRunCount);

    // Open AI editor modal while previewing.
    await page.locator('#sysAiFab').click();
    await expect(page.locator('#aiModal')).toBeVisible();
    await page.locator('#aiChangeRequest').fill('e2e-t5-propose-while-preview');
    await page.keyboard.press('Enter');
    await expect(page.locator('#aiDiff')).toContainText('DRY_RUN_EDIT');
    await expect(versionBar).not.toBeVisible();
    const afterProposePromptValue = await page.locator('#systemPrompt').inputValue();
    const afterProposeDryRunCount = (afterProposePromptValue.match(/\[DRY_RUN_EDIT\]/g) || []).length;
    expect(afterProposeDryRunCount, 'proposing while previewing must not clobber live candidate').toBe(liveDryRunCount);

    await page.locator('#aiModalCloseBtn').click();
    await expect(page.locator('#aiModal')).not.toBeVisible();

    // ── Cleanup: reset draft history ──
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#compareBaseBtn').click();
    await expect(page.locator('#compareModal')).toBeVisible();
    await page.locator('#compareResetBtn').click();
    await expect(page.locator('#compareModal')).not.toBeVisible();
});
