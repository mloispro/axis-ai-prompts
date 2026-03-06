/* eslint-disable no-console */

const http = require('http');

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
    const port = String(process.env.WORKBENCH_PORT || '7540');
    const url = `http://127.0.0.1:${port}/api/edit/reset`;
    try {
        await postJson(url, { appId: 'rizzchatai' });
    } catch (e) {
        // Best-effort cleanup only; never fail the suite.
        console.log('[global-teardown] reset failed:', e && e.message ? e.message : String(e));
    }
};
