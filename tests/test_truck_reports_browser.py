"""Offline Chrome checks for report filters and native SVG rendering."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from uuid import uuid4

import test_truck_reports as reports


ROOT = Path(__file__).resolve().parents[1]
CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@unittest.skipUnless(CHROME.exists(), 'Chrome required for report interaction checks')
class TruckReportBrowserTests(unittest.TestCase):
    def test_filters_and_chart_geometry_on_mobile_and_desktop(self):
        fixture = reports.TruckReportTests()
        fixture.setUp()
        folder = ROOT / f'.report-browser-{uuid4().hex}'
        folder.mkdir()
        try:
            checks = r"""
                window.addEventListener('load', () => {
                    try {
                        const check = (value, message) => { if (!value) throw new Error(message); };
                        const form = document.getElementById('report-filters');
                        const mode = document.getElementById('report-mode');
                        const months = document.getElementById('report-month-fields');
                        const dates = document.getElementById('report-range-fields');
                        const setMode = value => { mode.value = value; mode.dispatchEvent(new Event('change')); };
                        setMode('month');
                        check(!months.hidden && dates.hidden && dates.disabled, 'month visibility');
                        let data = new FormData(form);
                        check(data.has('month') && !data.has('start_date') && !data.has('end_date'), 'month form values');
                        setMode('range');
                        check(months.hidden && months.disabled && !dates.hidden, 'range visibility');
                        document.getElementById('start_date').value = '2026-10-31';
                        document.getElementById('end_date').value = '2026-11-01';
                        data = new FormData(form);
                        check(!data.has('month') && data.get('start_date') === '2026-10-31' &&
                              data.get('end_date') === '2026-11-01', 'range form values');
                        check(form.checkValidity(), 'valid range form');
                        document.getElementById('end_date').value = '';
                        check(!form.checkValidity(), 'required end date');
                        setMode('month');
                        check(form.checkValidity(), 'disabled dates do not block month');
                        check(document.querySelectorAll('svg.report-chart').length === 2, 'two charts');
                        for (const bar of document.querySelectorAll('svg rect')) {
                            for (const attr of ['x', 'y', 'width', 'height']) {
                                check(Number.isFinite(Number(bar.getAttribute(attr))), 'finite geometry');
                            }
                            check(bar.height.baseVal.value >= 0, 'nonnegative bars');
                            check(bar.querySelector('title').textContent.includes('VNĐ'), 'exact value tooltip');
                        }
                        for (const box of document.querySelectorAll('.report-chart-scroll')) {
                            check(getComputedStyle(box).overflowX === 'auto', 'scrollable chart');
                            if (window.innerWidth < 640) check(box.scrollWidth > box.clientWidth, 'mobile chart scroll');
                        }
                        check(document.querySelector('.report-table tbody').rows.length === 3, 'vehicle/month detail rows');
                        document.documentElement.dataset.reportChecks = 'passed';
                    } catch (error) {
                        document.documentElement.dataset.reportChecks = 'failed: ' + error.message;
                    }
                });
            """
            for mode in ('month', 'range'):
                query = ('month=2026-10' if mode == 'month' else
                         'mode=range&start_date=2026-10-01&end_date=2026-12-31')
                html = fixture.client.get('/reports?' + query).get_data(as_text=True)
                # Browser verification is offline and does not run a Flask server.
                html = re.sub(r'<link\b[^>]*href="https?://[^>]*>', '', html)
                html = re.sub(r'<script\b[^>]*src="https?://[^>]*></script>', '', html)
                html = re.sub(r'<link\b[^>]*href="/static/([^"?]+)"[^>]*>',
                              lambda m: '<style>' + (ROOT / 'app/static' / m[1]).read_text(encoding='utf-8') + '</style>', html)
                html = re.sub(r'<script src="/static/([^"?]+)"></script>',
                              lambda m: '<script>' + (ROOT / 'app/static' / m[1]).read_text(encoding='utf-8') + '</script>', html)
                html = html.replace('<head>', '<head><script>window.htmx={config:{}};</script>')
                # Number of active vehicle/month rows differs between the two views.
                expected_rows = 1 if mode == 'month' else 3
                html = html.replace('</body>', '<script>' + checks.replace('rows.length === 3', f'rows.length === {expected_rows}') + '</script></body>')
                sample = folder / f'{mode}.html'
                sample.write_text(html, encoding='utf-8')
                for width, height in ((390, 844), (1440, 1000)):
                    with self.subTest(mode=mode, width=width):
                        startup = subprocess.STARTUPINFO()
                        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startup.wShowWindow = subprocess.SW_HIDE
                        result = subprocess.run([
                            str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                            '--disable-background-networking', f'--user-data-dir={folder}/chrome-{mode}-{width}',
                            f'--window-size={width},{height}', '--dump-dom', '--virtual-time-budget=1000', sample.as_uri(),
                        ], capture_output=True, text=True, encoding='utf-8', timeout=30, startupinfo=startup)
                        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
                        status = re.search(r'data-report-checks="([^"]+)"', result.stdout)
                        self.assertIsNotNone(status, result.stderr[-1500:])
                        self.assertEqual(status[1], 'passed')
        finally:
            fixture.tearDown()
            if folder.resolve().parent == ROOT and folder.name.startswith('.report-browser-'):
                shutil.rmtree(folder)


if __name__ == '__main__':
    unittest.main()
