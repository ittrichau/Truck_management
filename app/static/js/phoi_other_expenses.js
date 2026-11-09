(() => {
    function syncOtherExpense(section) {
        const enabled = section.querySelector('[data-other-toggle]').checked;
        section.querySelector('[data-other-enabled]').value = enabled ? '1' : '0';
        section.querySelector('[data-other-details]').classList.toggle('d-none', !enabled);
        const amount = section.querySelector('[data-other-amount]');
        const description = section.querySelector('[data-other-description]');
        amount.required = description.required = enabled;
        const value = Number(amount.value.replace(/,/g, ''));
        amount.setCustomValidity(enabled && (!Number.isInteger(value) || value <= 0 || value > 9999999999)
            ? 'Vui lòng nhập số tiền nguyên lớn hơn 0 và không quá 9.999.999.999 VNĐ.' : '');
        description.setCustomValidity(enabled && !description.value.trim()
            ? 'Vui lòng nhập nội dung chi phí khác.' : '');
        if (!enabled) {
            amount.classList.remove('is-invalid');
            description.classList.remove('is-invalid');
        }
    }

    function initialize(root) {
        if (root.matches?.('[data-other-expense]')) syncOtherExpense(root);
        root.querySelectorAll?.('[data-other-expense]').forEach(syncOtherExpense);
    }

    document.addEventListener('change', event => {
        const section = event.target.closest('[data-other-expense]');
        if (section) syncOtherExpense(section);
    });
    document.addEventListener('input', event => {
        const section = event.target.closest('[data-other-expense]');
        if (section) syncOtherExpense(section);
    });
    // Capture on the form's ancestor before app.js validates required fields.
    window.addEventListener('submit', event => initialize(event.target), true);
    document.addEventListener('DOMContentLoaded', () => initialize(document));
    const trips = document.getElementById('return-trips');
    if (trips) new MutationObserver(mutations => {
        mutations.forEach(mutation => mutation.addedNodes.forEach(initialize));
    }).observe(trips, {childList: true, subtree: true});
})();
