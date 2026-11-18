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
        fixture.login(fixture.admin)
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
                        const manager = document.getElementById('manager_id');
                        const truck = document.getElementById('truck_id');
                        const monthBefore = document.getElementById('report-month').value;
                        const visibleTrucks = () => Array.from(truck.options)
                            .filter(option => option.value && !option.hidden && !option.disabled);
                        const setManager = value => { manager.value = value; manager.dispatchEvent(new Event('change')); };
                        check(manager && manager.value === 'INITIAL_MANAGER', 'initial manager selection');
                        check(truck.value === 'INITIAL_TRUCK', 'initial truck selection');
                        setManager('MANAGER_A');
                        check(visibleTrucks().length === 3 && visibleTrucks().every(option => option.dataset.managerId === 'MANAGER_A'), 'manager A vehicles');
                        truck.value = 'TRUCK_A';
                        setManager('MANAGER_B');
                        check(truck.value === '', 'clear incompatible vehicle');
                        check(visibleTrucks().length === 1 && visibleTrucks()[0].value === 'TRUCK_B', 'manager B vehicles');
                        truck.value = 'TRUCK_B';
                        data = new FormData(form);
                        check(data.get('manager_id') === 'MANAGER_B' && data.get('truck_id') === 'TRUCK_B', 'combined filter values');
                        setManager('');
                        check(visibleTrucks().length === 5 && truck.value === 'TRUCK_B', 'all managers restore options');
                        setManager('unassigned');
                        check(truck.value === '' && visibleTrucks().length === 1 && visibleTrucks()[0].dataset.managerId === 'unassigned', 'unassigned vehicles');
                        check(document.getElementById('report-month').value === monthBefore && mode.value === 'month', 'manager preserves period');
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
            scenarios = [
                ('month', 'month=2026-10', 1, '', ''),
                ('range', 'mode=range&start_date=2026-10-01&end_date=2026-12-31', 5, '', ''),
                ('filtered', f'month=2026-11&manager_id={fixture.a.id}&truck_id={fixture.retired.id}',
                 1, str(fixture.a.id), str(fixture.retired.id)),
            ]
            for mode, query, expected_rows, initial_manager, initial_truck in scenarios:
                html = fixture.client.get('/reports?' + query).get_data(as_text=True)
                # Browser verification is offline and does not run a Flask server.
                html = re.sub(r'<link\b[^>]*href="https?://[^>]*>', '', html)
                html = re.sub(r'<script\b[^>]*src="https?://[^>]*></script>', '', html)
                html = re.sub(r'<link\b[^>]*href="/static/([^"?]+)"[^>]*>',
                              lambda m: '<style>' + (ROOT / 'app/static' / m[1]).read_text(encoding='utf-8') + '</style>', html)
                html = re.sub(r'<script src="/static/([^"?]+)"></script>',
                              lambda m: '<script>' + (ROOT / 'app/static' / m[1]).read_text(encoding='utf-8') + '</script>', html)
                html = html.replace('<head>', '<head><script>window.htmx={config:{}};</script>')
                scenario_checks = checks.replace('rows.length === 3', f'rows.length === {expected_rows}')
                for key, value in {'MANAGER_A': fixture.a.id, 'MANAGER_B': fixture.b.id,
                                   'TRUCK_A': fixture.ta.id, 'TRUCK_B': fixture.tb.id,
                                   'INITIAL_MANAGER': initial_manager, 'INITIAL_TRUCK': initial_truck}.items():
                    scenario_checks = scenario_checks.replace(key, str(value))
                html = html.replace('</body>', '<script>' + scenario_checks + '</script></body>')
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
