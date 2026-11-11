// Called by test_phoi_print_browser.py with an isolated local Chrome profile.
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const [socketUrl, manifestPath] = process.argv.slice(2);
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const socket = new WebSocket(socketUrl);
await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, {once: true});
    socket.addEventListener('error', reject, {once: true});
});
let sequence = 0;
const pending = new Map();
socket.addEventListener('message', event => {
    const result = JSON.parse(event.data);
    if (!result.id) return;
    const task = pending.get(result.id);
    pending.delete(result.id);
    if (result.error) task.reject(new Error(JSON.stringify(result.error)));
    else task.resolve(result.result);
});
function call(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
        const id = ++sequence;
        pending.set(id, {resolve, reject});
        socket.send(JSON.stringify({id, method, params, sessionId}));
    });
}
const {targetId} = await call('Target.createTarget', {url: 'about:blank'});
const {sessionId} = await call('Target.attachToTarget', {targetId, flatten: true});
const page = (method, params = {}) => call(method, params, sessionId);
async function evaluate(expression) {
    const result = await page('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
}
async function open(file) {
    await page('Page.navigate', {url: pathToFileURL(file).href});
    for (let attempt = 0; attempt < 100; attempt++) {
        if (await evaluate('document.readyState === "complete"')) return;
        await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error(`Load timed out: ${file}`);
}
const results = [];
try {
    for (const sample of manifest.prints) {
        await page('Emulation.setDeviceMetricsOverride', {
            width: sample.mobile ? 390 : 1280, height: 1000,
            deviceScaleFactor: 1, mobile: false,
        });
        // Clear emulation: forcing "screen" would also disable print CSS in PDF.
        await page('Emulation.setEmulatedMedia', {media: ''});
        await open(sample.html);
        await evaluate('document.fonts.ready');
        for (let attempt = 0; attempt < 100; attempt++) {
            if (await evaluate('Boolean(document.querySelector("[data-print-sheet]")?.dataset.printScale)')) break;
            await new Promise(resolve => setTimeout(resolve, 50));
        }
        const metrics = await evaluate(`(() => {
            const sheet = document.querySelector('[data-print-sheet]');
            return {scale: sheet.dataset.printScale, expenses: sheet.querySelectorAll('.other-expense-print').length,
                text: sheet.textContent, warning: document.querySelector('.fit-warning').textContent};
        })()`);
        assert.ok(Number(metrics.scale) > 0, 'Fitting script did not run');
        assert.equal(metrics.expenses, sample.expenseCount);
        for (const marker of sample.markers) assert.ok(metrics.text.includes(marker), marker);
        delete metrics.text;
        if (Number(metrics.scale) < 0.1) {
            const trace = await evaluate(`(() => {
                const doc = document.querySelector('.phoi-print-measure').contentDocument;
                const sheet = doc.querySelector('[data-print-sheet]');
                return [1,.9,.8,.5,.1].map(scale => {
                    sheet.style.setProperty('--print-scale', scale);
                    const rect = sheet.getBoundingClientRect();
                    return {scale, width: rect.width, height: rect.height, available: doc.documentElement.clientWidth,
                        cssWidth: getComputedStyle(sheet).width, zoom: getComputedStyle(sheet).zoom};
                });
            })()`);
            throw new Error(`Excessive scaling ${sample.name}: ${JSON.stringify(trace)}`);
        }
        const {data} = await page('Page.printToPDF', {
            preferCSSPageSize: true, displayHeaderFooter: false, printBackground: true,
        });
        const pdf = Buffer.from(data, 'base64');
        const pages = [...pdf.toString('latin1').matchAll(/\/Type\s*\/Page\b/g)].length;
        fs.writeFileSync(sample.pdf, pdf);
        assert.equal(pages, 1, `${sample.name}: ${pages} pages; ${JSON.stringify(metrics)}`);
        results.push({name: sample.name, pages, scale: Number(metrics.scale), expenses: metrics.expenses});
        if (sample.screenshot) {
            await page('Emulation.setDeviceMetricsOverride', {width: 726, height: 1063, deviceScaleFactor: 1, mobile: false});
            await page('Emulation.setEmulatedMedia', {media: 'print'});
            const image = await page('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
            fs.writeFileSync(sample.screenshot, Buffer.from(image.data, 'base64'));
        }
    }
    for (const form of manifest.forms) {
        await page('Emulation.setEmulatedMedia', {media: ''});
        await open(form);
        const checked = await evaluate(`(async () => {
            const assert = (condition, label) => {if (!condition) throw new Error(label);};
            const scope = document.querySelector('[data-other-expense]');
            scope.querySelector('[data-other-toggle]').click();
            assert(scope.querySelector('[data-other-enabled]').value === '1', 'Checked flag');
            const amount = scope.querySelector('[data-other-amount]');
            const description = scope.querySelector('[data-other-description]');
            assert(amount.required && description.required && !amount.checkValidity(), 'Amount required');
            amount.value = '50,000';
            amount.dispatchEvent(new Event('input', {bubbles: true}));
            description.value = '   ';
            description.dispatchEvent(new Event('input', {bubbles: true}));
            assert(!description.checkValidity(), 'Whitespace content rejected');
            description.value = 'Vá lốp';
            description.dispatchEvent(new Event('input', {bubbles: true}));
            assert(amount.checkValidity() && description.checkValidity(), 'Valid fields');
            addReturnTrip(); addReturnTrip(); addReturnTrip();
            await new Promise(resolve => setTimeout(resolve, 20));
            const trips = document.querySelectorAll('.return-trip');
            trips[0].querySelector('[data-other-toggle]').click();
            trips[2].querySelector('[data-other-toggle]').click();
            trips[1].remove(); renumberReturnTrips();
            const values = new FormData(document.getElementById('phoi-form'));
            assert(values.getAll('return_trip_has_other[]').join(',') === '1,1', 'Checkbox indices after removal');
            assert(values.getAll('return_trip_expense_other[]').length === 2, 'Amount array alignment');
            assert(values.getAll('return_trip_expense_other_description[]').length === 2, 'Content array alignment');
            scope.querySelector('[data-other-toggle]').click();
            assert(!amount.required && !description.required && amount.checkValidity(), 'Unchecked fields optional');
            return true;
        })()`);
        assert.equal(checked, true);
        results.push({form: form.split(/[\\/]/).at(-1), dynamicCheckboxes: 'passed'});
    }
    process.stdout.write(JSON.stringify(results));
} finally {
    await call('Target.closeTarget', {targetId});
    socket.close();
}
