// Execute the production event handlers with a small DOM adapter, without a server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const listeners = {};
class HTMLElement {
    matches() { return false; }
    hasAttribute() { return false; }
}
class HTMLInputElement extends HTMLElement {
    constructor() {
        super();
        this.name = 'amount';
        this.value = '';
        this.classList = {contains: name => name === 'currency-input'};
    }
    setSelectionRange(start, end) {
        this.selectionStart = start;
        this.selectionEnd = end;
    }
}
class HTMLFormElement extends HTMLElement {
    querySelectorAll() { return [input]; }
    querySelector() { return null; }
}
const input = new HTMLInputElement();
const context = {
    HTMLElement, HTMLInputElement, HTMLFormElement,
    htmx: {config: {}},
    window: {addEventListener() {}},
    MutationObserver: class {observe() {}},
    setTimeout() {},
    document: {
        body: {},
        getElementById() { return null; },
        querySelectorAll(selector) { return selector === 'input' ? [input] : []; },
        addEventListener(name, callback, capture) {
            (listeners[name] ??= []).push({callback, capture: !!capture});
        },
    },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/app.js'), 'utf8'), context);
function dispatch(type, props = {}) {
    const event = {target: input, defaultPrevented: false,
        preventDefault() { this.defaultPrevented = true; }, ...props};
    [...(listeners[type] || [])].sort((a, b) => b.capture - a.capture)
        .forEach(({callback}) => callback(event));
    return event;
}
dispatch('DOMContentLoaded', {target: context.document});
for (const [raw, display] of [['400000', '400,000'], ['10000000', '10,000,000'],
    ['9999999999', '9,999,999,999'], ['0', '0'], ['', '']]) {
    input.value = raw;
    input.setSelectionRange(raw.length, raw.length);
    dispatch('input');
    assert.equal(input.value, display);
    dispatch('submit', {target: new HTMLFormElement()});
    assert.equal(input.value, raw);
}
input.value = '400,000';
input.setSelectionRange(input.value.length, input.value.length);
dispatch('focusin');
assert(dispatch('beforeinput', {inputType: 'insertText', data: 'a'}).defaultPrevented);
assert(dispatch('paste', {clipboardData: {getData: () => 'abc'}}).defaultPrevented);
input.value = '400,000a';
dispatch('input');
assert.equal(input.value, '400,000');
input.value = '500,000';
dispatch('submit', {target: new HTMLFormElement(), defaultPrevented: true});
assert.equal(input.value, '500,000');
