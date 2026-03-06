/* eslint-disable no-console */

const http = require('http');
const fs = require('fs');
const path = require('path');

function postJson(url, data) {
    return new Promise((resolve, reject) => {
        const body = Buffer.from(JSON.stringify(data), 'utf-8');
        const req = http.request(
            url,
            {
                method: 'POST',
                headers: {
                    'content-type': 'application/json',
                    'content-length': String(body.length),
                },
                timeout: 5_000,
            },
            res => {
                const chunks = [];
                res.on('data', c => chunks.push(c));
                res.on('end', () => resolve({ status: res.statusCode || 0, body: Buffer.concat(chunks).toString('utf-8') }));
            }
        );

        req.on('error', reject);
        req.on('timeout', () => {
            req.destroy(new Error('timeout'));
        });

        req.write(body);
        req.end();
    });
}

module.exports = async () => {
    const auditMode = process.env.E2E_AUDIT === '1' || process.env.PLAYWRIGHT_AUDIT === '1';
    if (auditMode) {
        try {
            const root = path.resolve(__dirname, '..'); // e2e -> workbench-web
            const outDir = process.env.E2E_AUDIT_OUT_DIR
                ? path.resolve(String(process.env.E2E_AUDIT_OUT_DIR))
                : path.join(root, 'out', 'audit');
            const indexPath = path.join(outDir, 'audit-index.jsonl');
            const mdPath = path.join(outDir, 'audit-findings.md');

            if (fs.existsSync(indexPath)) {
                const lines = fs.readFileSync(indexPath, 'utf-8').split(/\r?\n/).filter(Boolean);
                const recs = [];
                for (const ln of lines) {
                    try { recs.push(JSON.parse(ln)); } catch (_) { }
                }

                // Deduplicate by filename; keep first occurrence.
                const byFile = new Map();
                for (const r of recs) {
                    const key = String(r.fileName || '');
                    if (!key) continue;
                    if (!byFile.has(key)) byFile.set(key, r);
                }

                const rel = p => {
                    try { return path.relative(root, p).replace(/\\/g, '/'); } catch (_) { return String(p || ''); }
                };

                let md = '';
                md += '# Workbench UI audit findings checklist\n\n';
                md += `Generated: ${new Date().toISOString()}\n\n`;
                md += 'Run command:\n\n';
                md += '```\ncd tools/workbench-web && E2E_AUDIT=1 npx playwright test --reporter=line,html\n```\n\n';
                md += 'Report UI:\n\n';
                md += '```\ncd tools/workbench-web && npx playwright show-report playwright-report\n```\n\n';
                md += 'Artifacts (stable paths):\n\n';

                const files = [...byFile.values()].sort((a, b) => String(a.fileName).localeCompare(String(b.fileName)));
                for (const r of files) {
                    const fileName = String(r.fileName || '');
                    const state = String(r.stateName || '');
                    const outPath = String(r.outPath || '');
                    const testTitle = String(r.testTitle || '');
                    const testFile = String(r.testFile || '');
                    md += `- [ ] ${state || fileName}\n`;
                    md += `  - file: ${rel(outPath)}\n`;
                    if (testTitle) md += `  - test: ${testTitle}\n`;
                    if (testFile) md += `  - spec: ${rel(testFile)}\n`;
                }

                md += '\nTriage buckets:\n';
                md += '- Bug\n- UX workflow inefficiency\n- UI/layout\n';

                fs.mkdirSync(outDir, { recursive: true });
                fs.writeFileSync(mdPath, md, 'utf-8');
                console.log('[global-teardown] wrote audit findings:', rel(mdPath));
            }
        } catch (e) {
            console.log('[global-teardown] audit findings generation failed:', e && e.message ? e.message : String(e));
        }
    }

    const port = String(process.env.WORKBENCH_PORT || '7540');
    const url = `http://127.0.0.1:${port}/api/edit/reset`;
    try {
        await postJson(url, { appId: 'rizzchatai' });
    } catch (e) {
        // Best-effort cleanup only; never fail the suite.
        console.log('[global-teardown] reset failed:', e && e.message ? e.message : String(e));
    }
};
