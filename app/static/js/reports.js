(() => {
    const mode = document.getElementById('report-mode');
    if (!mode) return;
    const monthFields = document.getElementById('report-month-fields');
    const rangeFields = document.getElementById('report-range-fields');
    function updatePeriodFields() {
        const isRange = mode.value === 'range';
        monthFields.hidden = isRange;
        monthFields.disabled = isRange;
        rangeFields.hidden = !isRange;
        rangeFields.disabled = !isRange;
    }
    mode.addEventListener('change', updatePeriodFields);
    updatePeriodFields();
})();
