// HTMX configuration
htmx.config.globalViewTransitions = true;

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

// Format currency on display
function formatCurrency(amount) {
    return new Intl.NumberFormat('vi-VN', { 
        style: 'currency', 
        currency: 'VND',
        maximumFractionDigits: 0 
    }).format(amount);
}

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
        link.getAttribute('href') === '#' ||
        link.getAttribute('href') === '' ||
        link.dataset.noLoading !== undefined) {
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