(() => {
    const sheet = document.querySelector('[data-print-sheet]');
    const status = document.querySelector('.fit-warning');
    if (!sheet || !status) return;
    const tiers = ['density-compact', 'density-dense'];
    const pageHeight = Math.floor((297 - 16) * 96 / 25.4) - 4;
    // Measure the print rules at the actual printable width, independent of the
    // phone/desktop preview. Keep scripts and controls out of the measurement.
    const frame = document.createElement('iframe');
    frame.title = 'Đo bố cục in A4';
    frame.setAttribute('aria-hidden', 'true');
    frame.tabIndex = -1;
    frame.style.cssText = 'position:fixed;left:-10000px;top:0;width:192mm;height:281mm;border:0;visibility:hidden;';
    // Keep its layout during beforeprint; display:none would measure as zero
    // and undo the fitted scale exactly when the print dialog opens.
    frame.className = 'phoi-print-measure';
    document.body.append(frame);
    const doc = frame.contentDocument;
    const style = doc.createElement('style');
    style.textContent = document.getElementById('phoi-print-styles').textContent
        .replace('@media print', '@media all') + '\nhtml,body{margin:0;padding:0;}';
    doc.head.append(style);

    function assessPrintFit() {
        const clone = sheet.cloneNode(true);
        clone.querySelectorAll('script,.print-controls').forEach(node => node.remove());
        clone.classList.remove(...tiers);
        clone.style.setProperty('--print-scale', '1');
        doc.body.replaceChildren(clone);
        let tier = '';
        let scale = 1;
        for (const candidate of ['', ...tiers]) {
            clone.classList.remove(...tiers);
            if (candidate) clone.classList.add(candidate);
            tier = candidate;
            if (clone.getBoundingClientRect().height <= pageHeight) break;
        }
        const fits = () => clone.getBoundingClientRect().height <= pageHeight
            && clone.getBoundingClientRect().width <= doc.documentElement.clientWidth + 1;
        if (!fits()) {
            // Zoom changes wrapping as well as height, so measure each candidate
            // rather than applying a screen-height ratio or clipping overflow.
            let low = 0;
            let high = 1;
            for (let step = 0; step < 18; step++) {
                const candidate = (low + high) / 2;
                clone.style.setProperty('--print-scale', candidate);
                if (fits()) low = candidate;
                else high = candidate;
            }
            scale = Math.max(0.000001, Math.floor(low * 1000000) / 1000000);
        }
        sheet.classList.remove(...tiers);
        if (tier) sheet.classList.add(tier);
        sheet.style.setProperty('--print-scale', scale);
        sheet.dataset.printScale = String(scale);
        const effectiveFont = (tier === 'density-dense' ? 9.5 : 10) * scale;
        status.textContent = effectiveFont < 8
            ? `Vừa 1 trang A4 ở mức ${Math.round(scale * 100)}%. Nội dung dài nên chữ nhỏ; hãy kiểm tra bản xem trước khi in.`
            : `Bố cục vừa 1 trang A4${scale < 1 ? ` · Thu nhỏ ${Math.round(scale * 100)}%` : ''}. Chọn giấy A4, tỷ lệ 100%, tắt đầu/chân trang của trình duyệt.`;
        status.hidden = false;
    }

    window.addEventListener('load', assessPrintFit, {once: true});
    window.addEventListener('beforeprint', assessPrintFit);
    if (document.fonts?.ready) document.fonts.ready.then(() => doc.fonts.ready).then(assessPrintFit);
})();
