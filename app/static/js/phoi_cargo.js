/* One customer and one freight charge per row, at most three customers per trip. */
(() => {
    'use strict';
    const form = document.getElementById('phoi-form');
    if (!form) return;
    const manager = form.dataset.cargoManager === 'true';
    const money = value => Number(String(value || '').replace(/,/g, '')) || 0;
    const numberText = value => value ? money(value).toLocaleString('en-US', { maximumFractionDigits: 2 }) : '';

    function scopeOf(editor) { return editor.closest('.return-trip') || form; }
    function primaryCustomer(editor) {
        return scopeOf(editor).querySelector(editor.closest('.return-trip')
            ? '[name="return_trip_customer_id[]"]' : '[name="customer_id"]');
    }

    function addField(row, label, field, values, classes = '') {
        const wrapper = document.createElement('div');
        wrapper.className = 'col-12 col-sm-6';
        const caption = document.createElement('label');
        caption.className = 'form-label small';
        caption.textContent = label;
        const input = document.createElement('input');
        input.type = 'text';
        input.className = `form-control form-control-sm ${classes}`;
        input.setAttribute('aria-label', label);
        input.dataset.cargoField = field;
        input.value = values[field] || '';
        if (classes.includes('currency-input')) {
            input.dataset.decimalMoney = '';
            input.inputMode = 'decimal';
            input.value = numberText(input.value);
        }
        if (field === 'cargo_description') { input.required = true; input.maxLength = 300; }
        if (field === 'cargo_weight_tons') input.placeholder = 'Ví dụ: 0.500 hoặc 18.500';
        wrapper.append(caption, input);
        row.querySelector('.row').append(wrapper);
        return wrapper;
    }

    function addRow(editor, values = {}) {
        if (editor.querySelectorAll('[data-cargo-row]').length >= 2) return;
        const row = document.createElement('div');
        row.className = 'border rounded p-2 mb-2 bg-light';
        row.dataset.cargoRow = '';
        row.dataset.id = values.id || '';
        row.setAttribute('data-payment-calculator', '');
        const header = document.createElement('div');
        header.className = 'd-flex justify-content-between align-items-center mb-2';
        const title = document.createElement('strong');
        title.dataset.cargoTitle = '';
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn btn-outline-danger btn-sm';
        remove.textContent = 'Xóa khách ghép';
        remove.addEventListener('click', () => { row.remove(); refresh(editor); form.dispatchEvent(new Event('change', { bubbles: true })); });
        header.append(title, remove);
        const select = document.createElement('select');
        select.className = 'form-select form-select-sm mb-2';
        select.dataset.cargoField = 'customer_id';
        select.setAttribute('aria-label', 'Khách hàng ghép');
        select.required = true;
        const source = form.querySelector('[name="customer_id"]');
        [...source.options].forEach(option => select.append(option.cloneNode(true)));
        select.value = values.customer_id || '';
        const fields = document.createElement('div');
        fields.className = 'row g-2';
        row.append(header, select, fields);
        addField(row, 'Hàng hóa', 'cargo_description', values);
        const method = document.createElement('select');
        method.className = 'form-select form-select-sm payment-method mb-2';
        method.dataset.cargoField = 'payment_method';
        method.setAttribute('aria-label', 'Cách tính cước khách ghép');
        for (const [value, text] of [['fixed', 'Cước cố định cho khách'], ['per_ton', 'Theo tấn × đơn giá']]) {
            method.add(new Option(text, value));
        }
        method.value = values.payment_method || 'fixed';
        row.insertBefore(method, fields);
        addField(row, 'Cước cố định (VNĐ)', 'revenue_full', values, 'currency-input calculated-revenue').classList.add('fixed-revenue-field');
        addField(row, 'Số tấn', 'cargo_weight_tons', values, 'cargo-weight').classList.add('per-ton-field');
        addField(row, 'Giá mỗi tấn (VNĐ)', 'price_per_ton', values, 'currency-input price-per-ton').classList.add('per-ton-field');
        addField(row, 'Tài xế đã thu (VNĐ)', 'revenue_collected', values, 'currency-input');
        if (manager) addField(row, 'Quản lý đã thu (VNĐ)', 'manager_revenue_collected', values, 'currency-input');
        select.addEventListener('change', () => {
            const option = select.selectedOptions[0];
            row.querySelector('[data-cargo-field="cargo_description"]').value = option ? option.dataset.cargo || '' : '';
        });
        editor.querySelector('[data-cargo-list]').append(row);
        row.querySelectorAll('input').forEach(input => { prepareCurrencyInput(input); prepareWeightInput(input); });
        syncPaymentCalculator(row);
        refresh(editor);
    }

    function refresh(editor) {
        const rows = [...editor.querySelectorAll('[data-cargo-row]')];
        const selects = [primaryCustomer(editor), ...rows.map(row => row.querySelector('select'))];
        selects.forEach(select => {
            const duplicate = select.value && selects.some(other => other !== select && other.value === select.value);
            select.setCustomValidity(duplicate ? 'Mỗi khách chỉ được có một dòng trong chuyến.' :
                (rows.length && !select.value ? 'Vui lòng chọn khách hàng cho tất cả các dòng.' : ''));
            [...select.options].forEach(option => {
                option.disabled = !!option.value && selects.some(other => other !== select && other.value === option.value);
            });
        });
        rows.forEach((row, index) => { row.querySelector('[data-cargo-title]').textContent = `Khách ghép #${index + 2}`; });
        editor.querySelector('[data-add-cargo]').disabled = rows.length >= 2;
        const returning = !!editor.closest('.return-trip');
        const primary = scopeOf(editor).querySelector(returning ? '[name="return_trip_revenue_full[]"]' : '[name="revenue_full"]');
        const total = money(primary.value) + rows.reduce((sum, row) => sum + money(row.querySelector('.calculated-revenue').value), 0);
        editor.querySelector('[data-cargo-total]').textContent = `Tổng cước ${returning ? 'chuyến về' : 'chuyến đi'}: ${total.toLocaleString('en-US', { maximumFractionDigits: 2 })} VNĐ`;
    }

    function initialize() {
        document.querySelectorAll('.return-trip').forEach(trip => {
            if (!trip.querySelector('[data-cargo-extras]')) {
                trip.append(document.getElementById('cargo-editor-template').content.cloneNode(true));
            }
        });
        document.querySelectorAll('[data-cargo-extras]').forEach(editor => {
            if (editor.dataset.ready) return;
            editor.dataset.ready = 'true';
            const values = JSON.parse(editor.querySelector('[data-cargo-json]').value);
            values.forEach(value => addRow(editor, value));
            editor.querySelector('[data-add-cargo]').addEventListener('click', () => {
                addRow(editor);
                form.dispatchEvent(new Event('change', { bubbles: true }));
            });
            refresh(editor);
        });
    }

    // Keep FormData consumers (including mobile wrappers) in sync before submission.
    function serialize(editor) {
        const values = [...editor.querySelectorAll('[data-cargo-row]')].map(row => {
            const value = { id: row.dataset.id };
            row.querySelectorAll('[data-cargo-field]').forEach(input => {
                value[input.dataset.cargoField] = input.value;
            });
            return value;
        });
        editor.querySelector('[data-cargo-json]').value = JSON.stringify(values);
    }

    document.addEventListener('DOMContentLoaded', () => {
        initialize();
        new MutationObserver(initialize).observe(document.getElementById('return-trips'), { childList: true });
    });
    for (const name of ['input', 'change']) form.addEventListener(name, () => {
        syncAllPaymentCalculators();
        document.querySelectorAll('[data-cargo-extras]').forEach(editor => { refresh(editor); serialize(editor); });
    });
    document.addEventListener('submit', event => {
        if (event.target !== form) return;
        initialize();
        form.querySelectorAll('[data-cargo-extras]').forEach(editor => {
            editor.querySelectorAll('.cargo-weight').forEach(finalizeWeightInput);
            serialize(editor);
            refresh(editor);
        });
        if (!form.checkValidity()) { event.preventDefault(); event.stopImmediatePropagation(); form.reportValidity(); }
    }, true);
})();
