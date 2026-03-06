const { test: base, expect } = require('playwright/test');
const fs = require('fs');
const path = require('path');

const AUDIT_MODE = process.env.E2E_AUDIT === '1' || process.env.PLAYWRIGHT_AUDIT === '1';

let _auditIndexReady = false;
function _auditOutDir() {
    // e2e/helpers -> e2e -> workbench-web
    const root = path.resolve(__dirname, '..', '..');
    const outDir = process.env.E2E_AUDIT_OUT_DIR
        ? path.resolve(String(process.env.E2E_AUDIT_OUT_DIR))
        : path.join(root, 'out', 'audit');
    return outDir;
}

function _auditIndexPath() {
    return path.join(_auditOutDir(), 'audit-index.jsonl');
}

function _ensureAuditIndexReady() {
    if (!AUDIT_MODE) return;
    if (_auditIndexReady) return;
    const dir = _auditOutDir();
    fs.mkdirSync(dir, { recursive: true });
    // Start fresh each run so the checklist matches the current run.
    fs.writeFileSync(_auditIndexPath(), '', 'utf-8');
    _auditIndexReady = true;
}

function _appendAuditIndex(rec) {
    if (!AUDIT_MODE) return;
    _ensureAuditIndexReady();
    const line = JSON.stringify({ ts: new Date().toISOString(), ...rec }) + '\n';
    fs.appendFileSync(_auditIndexPath(), line, 'utf-8');
}

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
    _ensureAuditIndexReady();
    const fileName = `audit_${slugifyForFileName(stateName)}.png`;
    const png = await page.screenshot({ fullPage: true });
    await testInfo.attach(fileName, {
        body: png,
        contentType: 'image/png',
    });

    const outPath = path.join(_auditOutDir(), fileName);
    fs.writeFileSync(outPath, png);
    _appendAuditIndex({
        type: 'screenshot',
        stateName,
        fileName,
        outPath,
        testTitle: testInfo && testInfo.title ? String(testInfo.title) : '',
        testFile: testInfo && testInfo.file ? String(testInfo.file) : '',
    });
}

async function auditA11ySnapshot(page, testInfo, stateName) {
    if (!AUDIT_MODE) return;
    _ensureAuditIndexReady();
    if (!page.accessibility || typeof page.accessibility.snapshot !== 'function') {
        const fileName = `audit_${slugifyForFileName(stateName)}.a11y-unavailable.txt`;
        await testInfo.attach(fileName, {
            body: Buffer.from('Playwright accessibility snapshot is unavailable in this environment/version.', 'utf-8'),
            contentType: 'text/plain',
        });

        const outPath = path.join(_auditOutDir(), fileName);
        fs.writeFileSync(outPath, 'Playwright accessibility snapshot is unavailable in this environment/version.\n', 'utf-8');
        _appendAuditIndex({
            type: 'a11y',
            stateName,
            fileName,
            outPath,
            testTitle: testInfo && testInfo.title ? String(testInfo.title) : '',
            testFile: testInfo && testInfo.file ? String(testInfo.file) : '',
        });
        return;
    }

    const snapshot = await page.accessibility.snapshot();
    const fileName = `audit_${slugifyForFileName(stateName)}.a11y.json`;
    await testInfo.attach(fileName, {
        body: Buffer.from(JSON.stringify(snapshot, null, 2), 'utf-8'),
        contentType: 'application/json',
    });

    const outPath = path.join(_auditOutDir(), fileName);
    fs.writeFileSync(outPath, JSON.stringify(snapshot, null, 2) + '\n', 'utf-8');
    _appendAuditIndex({
        type: 'a11y',
        stateName,
        fileName,
        outPath,
        testTitle: testInfo && testInfo.title ? String(testInfo.title) : '',
        testFile: testInfo && testInfo.file ? String(testInfo.file) : '',
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
