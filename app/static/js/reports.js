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

    const manager = document.getElementById('manager_id');
    const truck = document.getElementById('truck_id');
    if (manager && truck) {
        function updateTruckChoices() {
            for (const option of truck.options) {
                const matches = !option.value || !manager.value || option.dataset.managerId === manager.value;
                option.hidden = !matches;
                option.disabled = !matches;
            }
            if (truck.selectedOptions[0]?.disabled) truck.value = '';
        }
        manager.addEventListener('change', updateTruckChoices);
        updateTruckChoices();
    }
})();
