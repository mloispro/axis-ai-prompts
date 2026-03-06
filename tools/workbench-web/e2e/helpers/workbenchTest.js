const { test: base, expect } = require('playwright/test');

const AUDIT_MODE = process.env.E2E_AUDIT === '1' || process.env.PLAYWRIGHT_AUDIT === '1';

function isRelevantUrl(url) {
    return url.includes('/api/') || url.includes('/js/') || url.includes('/css/');
}

function startDiagnosticsCapture(page) {
    const diag = {
        pageErrors: [],
        console: [],
        requestFailed: [],
        httpErrors: [],
    };

    page.on('pageerror', err => {
        diag.pageErrors.push({
            type: 'pageerror',
            message: err && err.message ? err.message : String(err),
            stack: err && err.stack ? err.stack : undefined,
        });
    });

    page.on('console', msg => {
        const t = msg.type();
        if (t === 'error' || t === 'warning') {
            diag.console.push({
                type: `console.${t}`,
                text: msg.text(),
                location: msg.location ? msg.location() : undefined,
            });
        }
    });

    page.on('requestfailed', req => {
        const url = req.url();
        if (isRelevantUrl(url)) {
            diag.requestFailed.push({
                url,
                method: req.method(),
                failure: req.failure() ? req.failure().errorText : undefined,
            });
        }
    });

    page.on('response', res => {
        const url = res.url();
        if (res.status() >= 400 && isRelevantUrl(url)) {
            diag.httpErrors.push({
                url,
                status: res.status(),
                statusText: res.statusText(),
            });
        }
    });

    return diag;
}

function slugifyForFileName(s) {
    return String(s)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
        .slice(0, 120);
}

async function auditScreenshot(page, testInfo, stateName) {
    if (!AUDIT_MODE) return;
    const fileName = `audit_${slugifyForFileName(stateName)}.png`;
    await testInfo.attach(fileName, {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
    });
}

async function auditA11ySnapshot(page, testInfo, stateName) {
    if (!AUDIT_MODE) return;
    if (!page.accessibility || typeof page.accessibility.snapshot !== 'function') {
        const fileName = `audit_${slugifyForFileName(stateName)}.a11y-unavailable.txt`;
        await testInfo.attach(fileName, {
            body: Buffer.from('Playwright accessibility snapshot is unavailable in this environment/version.', 'utf-8'),
            contentType: 'text/plain',
        });
        return;
    }

    const snapshot = await page.accessibility.snapshot();
    const fileName = `audit_${slugifyForFileName(stateName)}.a11y.json`;
    await testInfo.attach(fileName, {
        body: Buffer.from(JSON.stringify(snapshot, null, 2), 'utf-8'),
        contentType: 'application/json',
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

const test = base.extend({
    diag: async ({ page }, use) => {
        const diag = startDiagnosticsCapture(page);
        await use(diag);
    },
});

test.afterEach(async ({ page, diag }, testInfo) => {
    if (diag) {
        await testInfo.attach('diagnostics.json', {
            body: Buffer.from(JSON.stringify(diag, null, 2), 'utf-8'),
            contentType: 'application/json',
        });
    }

    // Always capture a screenshot on failure — turns Playwright into a practical UI inspector.
    if (testInfo.status !== testInfo.expectedStatus) {
        await testInfo.attach('failure.png', {
            body: await page.screenshot({ fullPage: true }),
            contentType: 'image/png',
        });
    }
});

module.exports = {
    test,
    expect,
    AUDIT_MODE,
    gotoAndWaitForBootstrap,
    auditScreenshot,
    auditA11ySnapshot,
};
