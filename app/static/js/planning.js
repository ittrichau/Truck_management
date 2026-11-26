(() => {
  'use strict';
  const form = document.getElementById('planning-form');
  if (!form) return;
  const rows = document.getElementById('return-plans');
  const status = document.getElementById('return_load_status');
  const add = document.getElementById('add-return-plan');
  const renumber = () => {
    rows.querySelectorAll('.return-number').forEach((node, index) => { node.textContent = index + 1; });
    add.disabled = rows.children.length >= 20;
  };
  add.addEventListener('click', () => {
    if (rows.children.length >= 20) return;
    rows.append(document.getElementById('return-plan-template').content.cloneNode(true));
    status.value = 'loaded';
    renumber();
  });
  rows.addEventListener('click', event => {
    const button = event.target.closest('.remove-return');
    if (!button) return;
    button.closest('.return-plan-row').remove();
    if (!rows.children.length && status.value === 'loaded') status.value = 'unknown';
    renumber();
  });
  const truck = document.getElementById('truck_id');
  const driver = document.getElementById('driver_id');
  const syncDrivers = () => {
    const owner = truck.selectedOptions[0]?.dataset.managerId;
    for (const option of driver.options) {
      if (!option.value) continue;
      option.disabled = !!owner && option.dataset.managerId !== owner;
      option.hidden = option.disabled;
    }
    if (driver.selectedOptions[0]?.disabled) driver.value = '';
  };
  truck.addEventListener('change', syncDrivers);
  syncDrivers();
  renumber();
})();
