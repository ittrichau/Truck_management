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
