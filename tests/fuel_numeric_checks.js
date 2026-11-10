// Runs against the rendered fuel form in headless Chrome, with no server/CDN.
document.addEventListener('DOMContentLoaded', () => {
    try {
        const assert = (condition, message) => { if (!condition) throw new Error(message); };
        const liters = document.getElementById('liters');
        const price = document.getElementById('price_per_liter');
        const mode = document.getElementById('use_manual_price');
        const total = document.getElementById('total_cost_preview');
        function enter(input, value) {
            input.focus();
            input.value = value;
            input.dispatchEvent(new Event('input', {bubbles: true}));
        }
        function blocked(input, text) {
            input.focus();
            input.select();
            const previous = input.value;
            const event = new InputEvent('beforeinput', {
                bubbles: true, cancelable: true, inputType: 'insertText', data: text,
            });
            assert(!input.dispatchEvent(event), `Did not block ${text}`);
            assert(input.value === previous, 'Blocked input changed the value');
        }
        assert(price.readOnly, 'Default price must be read-only');
        mode.click();
        assert(!price.readOnly && price.required, 'Manual price must be editable/required');
        enter(liters, '137.335');
        enter(price, '24500');
        assert(price.value === '24,500', 'Currency formatting failed');
        const previousTotal = total.value;
        assert(previousTotal === '3.364.708 VNĐ', `Wrong preview: ${previousTotal}`);
        for (const text of ['a', 'e', '-', 'đ', '123abc']) {
            blocked(liters, text);
            blocked(price, text);
            assert(total.value === previousTotal, 'Invalid input changed the total');
        }
        const clipboardData = new DataTransfer();
        clipboardData.setData('text/plain', 'abc');
        const paste = new ClipboardEvent('paste', {bubbles: true, cancelable: true, clipboardData});
        assert(!price.dispatchEvent(paste), 'Invalid paste was accepted');
        assert(price.value === '24,500', 'Paste erased the price');
        // Fallback for IME/autofill paths that cannot cancel beforeinput.
        enter(liters, 'abc');
        assert(liters.value === '137.335', 'Fallback erased liters');
        enter(price, 'abc');
        assert(price.value === '24,500', 'Fallback erased price');
        assert(total.value === previousTotal, 'Fallback reset total to zero');
        mode.click();
        assert(price.readOnly && price.value === '25,000', 'Default mode not restored');
        mode.click();
        assert(price.value === '24,500', 'Manual value was lost after toggling');
        enter(liters, '137.3351');
        assert(liters.value === '137.335', 'Fourth decimal was accepted');
        enter(liters, '0.001');
        assert(liters.value === '0.001', 'Three decimal liters failed');
        enter(liters, '');
        assert(liters.value === '', 'Intentional deletion was blocked');
        enter(liters, '100');
        enter(price, '');
        assert(price.value === '', 'Intentional currency deletion was blocked');
        enter(price, '26000');
        assert(total.value === '2.600.000 VNĐ', 'Preview did not resume');
        // Shared currency handling also applies to newly added form fields.
        const dynamic = document.createElement('input');
        dynamic.className = 'currency-input';
        dynamic.value = '150000';
        document.body.append(dynamic);
        dynamic.focus();
        blocked(dynamic, 'x');
        assert(dynamic.value === '150,000', 'Dynamic currency lost its value');
        document.body.dataset.numericChecks = 'passed';
    } catch (error) {
        document.body.dataset.numericChecks = `failed: ${error.message}`;
    }
});
