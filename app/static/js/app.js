// HTMX configuration
htmx.config.globalViewTransitions = true;

function initializeDatePicker(input) {
    if (!window.flatpickr || input._flatpickr) return;

    const isDateTime = input.type === 'datetime-local';
    input.lang = 'en-GB';
    window.flatpickr(input, {
        altInput: true,
        altInputClass: `${input.className} date-display-input`,
        altFormat: isDateTime ? 'd/m/Y H:i' : 'd/m/Y',
        dateFormat: isDateTime ? 'Y-m-d\\TH:i' : 'Y-m-d',
        enableTime: isDateTime,
        time_24hr: true,
        locale: window.flatpickr.l10ns.vn || 'default',
        disableMobile: true,
        allowInput: true
    });
}

function initializeDatePickers(root) {
    const selector = 'input[type="date"], input[type="datetime-local"]';
    if (root instanceof HTMLInputElement && root.matches(selector)) {
        initializeDatePicker(root);
    }
    if (root.querySelectorAll) {
        root.querySelectorAll(selector).forEach(initializeDatePicker);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const datePickerObserver = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            mutation.addedNodes.forEach(function(node) {
                if (node instanceof HTMLElement) initializeDatePickers(node);
            });
        });
    });
    datePickerObserver.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => initializeDatePickers(document), 0);
});

// Auto-dismiss alerts after 4 seconds
document.addEventListener('htmx:load', function() {
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 4000);
    });
});

// Validation dùng chung: thông báo rõ ràng, tô đỏ và đưa người dùng đến trường bắt buộc đầu tiên.
let requiredFieldFocusTarget = null;

function setRequiredFieldInvalidState(field, isInvalid) {
    field.classList.toggle('is-invalid', isInvalid);
    if (field._flatpickr?.altInput) {
        field._flatpickr.altInput.classList.toggle('is-invalid', isInvalid);
    }
}

function focusRequiredField(field) {
    const target = field._flatpickr?.altInput || field;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.focus({ preventScroll: true });
}

function requiredFieldLabel(field) {
    const associatedLabel = Array.from(field.labels || []).map(label => label.textContent.trim()).find(Boolean);
    const fieldContainer = field.closest('.form-check, .mb-2, .mb-3, .col, [class*="col-"]');
    const visibleLabel = fieldContainer?.querySelector('.form-label, .form-check-label, label')?.textContent.trim();
    const label = associatedLabel || visibleLabel || field.getAttribute('aria-label') || field.name || 'Trường bắt buộc';
    return label.replace(/\s*\*\s*$/, '').trim();
}

function expandRequiredFieldSection(field) {
    const section = field.closest('[id]');
    if (!section || !section.classList.contains('d-none')) return;

    const title = document.querySelector(`[data-collapse-target="${CSS.escape(section.id)}"]`);
    if (!title) return;

    section.classList.remove('d-none');
    title.setAttribute('aria-expanded', 'true');
    const icon = title.querySelector('.section-toggle-icon');
    icon?.classList.replace('bi-chevron-down', 'bi-chevron-up');
}

function expandRequiredFieldSections(invalidFields) {
    invalidFields.forEach(expandRequiredFieldSection);
}

function showRequiredFieldsModal(invalidFields) {
    const firstInvalidField = invalidFields[0];
    requiredFieldFocusTarget = firstInvalidField;
    expandRequiredFieldSections(invalidFields);

    const modalElement = document.getElementById('required-fields-modal');
    const list = document.getElementById('required-fields-list');
    if (list) {
        list.replaceChildren(...invalidFields.map(field => {
            const item = document.createElement('li');
            item.textContent = requiredFieldLabel(field);
            return item;
        }));
    }
    if (!modalElement || !window.bootstrap) {
        focusRequiredField(firstInvalidField);
        return;
    }
    bootstrap.Modal.getOrCreateInstance(modalElement).show();
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('form').forEach(function(form) {
        if (form.querySelector(':required')) form.noValidate = true;
    });

    const modalElement = document.getElementById('required-fields-modal');
    modalElement?.addEventListener('hidden.bs.modal', function() {
        if (!requiredFieldFocusTarget) return;
        focusRequiredField(requiredFieldFocusTarget);
        requiredFieldFocusTarget = null;
    });
});

document.addEventListener('submit', function(event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.querySelector(':required') || form.checkValidity()) return;

    event.preventDefault();
    const invalidFields = Array.from(form.elements).filter(field =>
        field instanceof HTMLElement && field.matches(':required') && !field.disabled && !field.validity.valid
    );
    invalidFields.forEach(field => setRequiredFieldInvalidState(field, true));
    if (invalidFields[0]) showRequiredFieldsModal(invalidFields);
}, true);

document.addEventListener('input', clearRequiredFieldError);
document.addEventListener('change', clearRequiredFieldError);

function clearRequiredFieldError(event) {
    const field = event.target;
    if (!(field instanceof HTMLElement) || !field.matches(':required')) return;
    setRequiredFieldInvalidState(field, !field.validity.valid);
}

// Format currency on display
function formatCurrency(amount) {
    return new Intl.NumberFormat('vi-VN', {
        style: 'currency',
        currency: 'VND',
        maximumFractionDigits: 0
    }).format(amount);
}

// Định dạng các trường tiền theo dấu phân cách hàng nghìn ngay khi nhập.
const currencyInputNames = new Set([
    'price_per_liter', 'revenue_full', 'revenue_collected', 'price_per_ton',
    'expense_porter_fee', 'expense_toll_fee', 'expense_other',
    'driver_wage', 'repair_amount[]', 'return_trip_revenue_full[]',
    'return_trip_revenue_collected[]', 'return_trip_porter_fee[]', 'return_trip_price_per_ton[]'
]);

function isCurrencyInput(input) {
    return input instanceof HTMLInputElement && (
        input.classList.contains('currency-input') || currencyInputNames.has(input.name)
    );
}

function currencyDigits(value) {
    return String(value || '').replace(/\D/g, '');
}

function formatCurrencyInput(input) {
    const digits = currencyDigits(input.value);
    input.value = digits ? Number(digits).toLocaleString('en-US') : '';
}

function prepareCurrencyInput(input) {
    if (!isCurrencyInput(input)) return;
    input.type = 'text';
    input.inputMode = 'numeric';
    input.autocomplete = 'off';
    formatCurrencyInput(input);
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('input').forEach(prepareCurrencyInput);
});

document.addEventListener('input', function(event) {
    const input = event.target;
    if (!isCurrencyInput(input)) return;

    const cursorFromEnd = input.value.length - input.selectionStart;
    formatCurrencyInput(input);
    const cursor = Math.max(0, input.value.length - cursorFromEnd);
    input.setSelectionRange(cursor, cursor);
});

// Các ô được thêm động (chuyến về, hạng mục sửa xe) cũng tự chuyển thành ô tiền.
document.addEventListener('focusin', function(event) {
    prepareCurrencyInput(event.target);
});

// Tương thích với biểu mẫu chuyến về được tạo bởi các phiên bản giao diện trước.
// Nếu thiếu tiền bốc vác, bổ sung trường này ngay sau khi thẻ chuyến về xuất hiện.
const returnTripObserver = new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
        mutation.addedNodes.forEach(function(node) {
            if (!(node instanceof HTMLElement)) return;
            const trip = node.matches('.return-trip') ? node : node.querySelector('.return-trip');
            if (!trip || trip.querySelector('[name="return_trip_porter_fee[]"]')) return;

            const notes = trip.querySelector('[name="return_trip_notes[]"]');
            if (!notes) return;
            const field = document.createElement('div');
            field.className = 'col-12';
            field.innerHTML = '<label class="form-label">Tiền bốc vác (VNĐ)</label><input type="text" name="return_trip_porter_fee[]" class="form-control form-control-sm currency-input" value="0" inputmode="numeric">';
            notes.closest('.col-12').before(field);
            prepareCurrencyInput(field.querySelector('input'));
        });
    });
});
returnTripObserver.observe(document.body, { childList: true, subtree: true });

// Giá trị gửi về máy chủ phải là số thuần, không có dấu phẩy.
document.addEventListener('submit', function(event) {
    if (event.defaultPrevented) return;
    event.target.querySelectorAll('input').forEach(function(input) {
        if (isCurrencyInput(input)) input.value = currencyDigits(input.value);
    });
});

// Tính doanh thu theo hai cách: bao chuyến hoặc số tấn × giá mỗi tấn.
function numericInputValue(input) {
    return Number(String(input?.value || '').replace(/,/g, '')) || 0;
}

function syncPaymentCalculator(container) {
    const method = container.querySelector('.payment-method');
    if (!method) return;
    const isPerTon = method.value === 'per_ton';
    container.querySelectorAll('.fixed-revenue-field').forEach(field => field.classList.toggle('d-none', isPerTon));
    container.querySelectorAll('.per-ton-field').forEach(field => field.classList.toggle('d-none', !isPerTon));

    const revenue = container.querySelector('.calculated-revenue');
    const price = container.querySelector('.price-per-ton');
    const weight = container.querySelector('.cargo-weight') || document.querySelector('[name="cargo_weight_tons"]');
    if (isPerTon && revenue && price && weight) {
        const total = numericInputValue(weight) * numericInputValue(price);
        revenue.value = total ? Math.round(total).toLocaleString('en-US') : '';
    }
}

function syncAllPaymentCalculators() {
    document.querySelectorAll('[data-payment-calculator]').forEach(syncPaymentCalculator);
}

document.addEventListener('DOMContentLoaded', syncAllPaymentCalculators);
document.addEventListener('change', function(event) {
    if (event.target.matches('.payment-method')) syncPaymentCalculator(event.target.closest('[data-payment-calculator]'));
});
document.addEventListener('input', function(event) {
    if (event.target.matches('.price-per-ton, .cargo-weight, [name="cargo_weight_tons"]')) syncAllPaymentCalculators();
});

// Cảnh báo trước khi rời biểu mẫu phơi có dữ liệu chưa lưu.
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('form.warn-unsaved-changes').forEach(function(form) {
        let isDirty = false;
        let isSubmitting = false;
        const message = form.dataset.unsavedMessage || 'Phơi chưa lưu. Nếu thoát, dữ liệu sẽ mất hết. Bạn có đồng ý thoát không?';

        form.addEventListener('input', function() { isDirty = true; });
        form.addEventListener('change', function() { isDirty = true; });
        form.addEventListener('submit', function(event) {
            if (!event.defaultPrevented) isSubmitting = true;
        });

        window.addEventListener('beforeunload', function(event) {
            if (!isDirty || isSubmitting) return;
            event.preventDefault();
            event.returnValue = message;
            return message;
        });

        document.addEventListener('click', function(event) {
            const link = event.target.closest('a[href]');
            if (!isDirty || isSubmitting || !link || link.target === '_blank' || event.defaultPrevented) return;
            const href = link.getAttribute('href');
            if (!href || href.startsWith('#') || !confirm(message)) {
                event.preventDefault();
                return;
            }
            isDirty = false;
        });
    });
});

// Keyboard shortcuts
window.addEventListener('keydown', function(e) {
    // Ctrl+N to create new
    if (e.ctrlKey && e.key === 'n') {
        const createBtn = document.querySelector('[href*="create"]');
        if (createBtn) {
            e.preventDefault();
            createBtn.click();
        }
    }
});

// ========== LOADING INDICATOR FOR MOBILE ==========

const loadingOverlay = document.getElementById('loading-overlay');

/**
 * Show the loading overlay
 */
function showLoading(text) {
    if (!loadingOverlay) return;
    const textEl = loadingOverlay.querySelector('.loading-text');
    if (textEl && text) textEl.textContent = text;
    loadingOverlay.classList.add('active');
}

/**
 * Hide the loading overlay
 */
function hideLoading() {
    if (!loadingOverlay) return;
    loadingOverlay.classList.remove('active');
    // Reset text
    const textEl = loadingOverlay.querySelector('.loading-text');
    if (textEl) textEl.textContent = 'Đang xử lý...';
}

/**
 * Show loading khi click vào link điều hướng (mobile nav, card links)
 * - Chỉ kích hoạt trên mobile (màn hình < 768px)
 * - Bỏ qua các link mở tab mới (target="_blank") hoặc có download
 */
document.addEventListener('click', function(e) {
    const link = e.target.closest('a');
    if (!link) return;
    
    // Chỉ áp dụng trên mobile
    if (window.innerWidth >= 768) return;
    
    // Bỏ qua nếu:
    // - Link mở tab mới
    // - Link download
    // - Link chỉ là neo trong trang (#)
    // - Link có data-no-loading
    if (link.target === '_blank' ||
        link.hasAttribute('download') ||
        (link.getAttribute('href') || '').startsWith('#') ||
        link.getAttribute('href') === '' ||
        link.dataset.noLoading !== undefined ||
        link.hasAttribute('data-bs-toggle') ||
        link.hasAttribute('data-bs-dismiss')) {
        return;
    }
    
    const href = link.getAttribute('href');
    // Chỉ kích hoạt cho link nội bộ (cùng origin hoặc relative)
    if (href && !href.startsWith('http')) {
        showLoading('Đang chuyển trang...');
    }
});

/**
 * Ẩn loading sau khi trang đã tải xong
 */
window.addEventListener('load', function() {
    hideLoading();
});

/**
 * Nếu trang load lâu, sau 3s vẫn còn loading thì tự động ẩn
 * (tránh trường hợp bị kẹt)
 */
setTimeout(function() {
    hideLoading();
}, 3000);

/**
 * Loading state cho form submit — thay vì overlay, thêm spinner vào nút submit
 */
document.addEventListener('submit', function(e) {
    if (e.defaultPrevented) return;
    const form = e.target;
    const submitBtn = form.querySelector('button[type="submit"]');
    if (!submitBtn) return;
    
    // Thêm class loading vào nút submit
    submitBtn.classList.add('btn-loading');
    // Disable nút để tránh submit nhiều lần
    submitBtn.disabled = true;
    
    // Lưu text gốc để sau này restore (nếu cần)
    if (!submitBtn.dataset.originalHtml) {
        submitBtn.dataset.originalHtml = submitBtn.innerHTML;
    }
});

/**
 * Khi page chuyển hướng (popstate/back), ẩn loading
 */
window.addEventListener('pageshow', function() {
    hideLoading();
});

/**
 * Xử lý nút "Quay lại" (nút không phải submit, nhưng là link)
 * - Nếu là mobile và là link quay lại, hiển thị loading
 */
document.addEventListener('click', function(e) {
    // Xử lý cho các nút có onclick="history.back()" hoặc tương tự
    const btn = e.target.closest('[onclick*="location"]') || 
                e.target.closest('[onclick*="history"]') ||
                e.target.closest('[onclick*="back"]');
    if (btn && window.innerWidth < 768) {
        showLoading('Đang quay lại...');
    }
});