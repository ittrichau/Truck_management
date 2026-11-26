(() => {
    const input = document.getElementById('driver-advance');
    if (!input) return;
    const toggle = document.getElementById('has-driver-advance');

    function sync() {
        if (!toggle) return; // Confirmation accepts 0 and has its own validation.
        const enabled = toggle.checked;
        document.getElementById('driver-advance-details').classList.toggle('d-none', !enabled);
        toggle.setAttribute('aria-expanded', String(enabled));
        input.required = enabled;
        const text = input.value.trim();
        const amount = Number(text.replace(/,/g, ''));
        const valid = text.length <= 32 && /^(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?$/.test(text)
            && Number.isFinite(amount) && amount > 0 && amount <= 9999999999.99;
        input.setCustomValidity(enabled && !valid
            ? 'Vui lòng nhập tiền ứng lớn hơn 0 và không quá 9.999.999.999,99 VNĐ.' : '');
        if (!enabled || valid) input.classList.remove('is-invalid');
    }

    input.addEventListener('input', () => {
        // Preserve decimal advances already supported by the stored money field.
        if (/^[0-9,]+(?:\.[0-9]{0,2})?$/.test(input.value)) {
            const cursorFromEnd = input.value.length - input.selectionStart;
            const [whole, fraction] = input.value.replace(/,/g, '').split('.');
            input.value = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
                + (fraction === undefined ? '' : '.' + fraction);
            const cursor = Math.max(0, input.value.length - cursorFromEnd);
            input.setSelectionRange(cursor, cursor);
        }
        sync();
    });
    if (toggle) {
        toggle.addEventListener('change', sync);
        window.addEventListener('submit', sync, true);
        window.addEventListener('pageshow', sync);
    }
    sync();
})();
