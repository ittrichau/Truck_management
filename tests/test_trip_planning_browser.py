"""Offline browser checks; no development server or production data."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from uuid import uuid4

import test_trip_planning as fixtures


ROOT = Path(__file__).resolve().parents[1]
CHROME = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')


@unittest.skipUnless(CHROME.exists(), 'Chrome required')
class TripPlanningBrowserTests(unittest.TestCase):
    def test_return_leg_forms_review_actions_and_calendar_on_mobile_and_desktop(self):
        fixture = fixtures.TripPlanningTests()
        fixture.setUp()
        folder = ROOT / f'.planning-browser-{uuid4().hex}'
        folder.mkdir()
        try:
            plan = fixture.plan()
            phoi = fixture.phoi()
            fixture.submit(phoi)
            sources = {
                'list': fixture.client.get('/planning?start_date=2026-12-01&end_date=2026-12-31'),
                'form': fixture.client.get(f'/planning/{plan.id}/edit'),
                'detail': fixture.client.get(f'/planning/{plan.id}'),
            }
            checks = r"""
            window.addEventListener('load', () => {
              try {
                const check = (condition, message) => { if (!condition) throw new Error(message); };
                const form = document.getElementById('planning-form');
                if (form) {
                  check(!document.querySelector('input[type="datetime-local"]'), 'date only');
                  check(form.checkValidity() === false, 'edit requires reason');
                  form.elements.reason.value = 'Khách đổi lịch';
                  check(form.checkValidity(), 'valid edit form');
                  const add = document.getElementById('add-return-plan');
                  add.click(); add.click();
                  check(document.querySelectorAll('#return-plans .return-plan-row').length === 2, 'add return legs');
                  check(document.getElementById('return_load_status').value === 'loaded', 'loaded state');
                  let data = new FormData(form);
                  check(data.getAll('return_origin[]').length === 2, 'two leg arrays');
                  const remove = document.querySelector('#return-plans .remove-return');
                  remove.click();
                  check(document.querySelector('#return-plans .return-number').textContent === '1', 'renumber');
                  document.querySelector('#return-plans .remove-return').click();
                  check(document.getElementById('return_load_status').value === 'unknown', 'unknown after remove');
                  for (let index = 0; index < 21; index++) add.click();
                  check(document.querySelectorAll('#return-plans .return-plan-row').length === 20 && add.disabled, 'leg limit');
                }
                const calendar = document.querySelector('.planning-calendar-scroll');
                if (calendar) {
                  check(getComputedStyle(calendar).overflowX === 'auto', 'calendar scroll');
                  if (window.innerWidth < 1200) check(calendar.scrollWidth > calendar.clientWidth, 'wide calendar scrolls');
                  check(document.querySelectorAll('.planning-calendar-day').length === 31, 'calendar period');
                  check(document.querySelectorAll('.planning-calendar-bar').length === 2, 'planned and actual');
                  for (const bar of document.querySelectorAll('.planning-calendar-bar')) {
                    check(Number(getComputedStyle(bar).gridColumnStart) > 0, 'valid bar start');
                    check(Number(getComputedStyle(bar).gridColumnEnd) > Number(getComputedStyle(bar).gridColumnStart), 'valid bar end');
                  }
                  const table = document.querySelector('.planning-table-wrap');
                  check(getComputedStyle(table).overflowX === 'auto', 'table scroll');
                }
                const accept = document.querySelector('button[name="action"][value="accept"]');
                if (accept) {
                  const reviewForm = accept.form;
                  check(!reviewForm.checkValidity(), 'review reason required');
                  reviewForm.elements.reason.value = 'Đã xác minh';
                  const data = new FormData(reviewForm, accept);
                  check(data.getAll('action').length === 1 && data.get('action') === 'accept', 'accept action');
                  check(data.get('actual_signature').length === 64, 'stale actual protection');
                  check(data.has('csrf_token') && data.has('version'), 'protected form');
                  check(reviewForm.checkValidity(), 'valid review');
                }
                document.documentElement.dataset.planningChecks = 'passed';
              } catch (error) {
                document.documentElement.dataset.planningChecks = 'failed: ' + error.message;
              }
            });
            """
            for name, response in sources.items():
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                html = re.sub(r'<link\b[^>]*href="https?://[^>]*>', '', html)
                html = re.sub(r'<script\b[^>]*src="https?://[^>]*></script>', '', html)
                html = re.sub(r'<link\b[^>]*href="/static/([^"?]+)"[^>]*>',
                              lambda match: '<style>' + (ROOT / 'app/static' / match[1]).read_text(encoding='utf-8') + '</style>', html)
                html = re.sub(r'<script src="/static/([^"?]+)"></script>',
                              lambda match: '<script>' + (ROOT / 'app/static' / match[1]).read_text(encoding='utf-8') + '</script>', html)
                html = html.replace('<head>', '<head><script>window.htmx={config:{}};</script>')
                html = html.replace('</body>', '<script>' + checks + '</script></body>')
                sample = folder / f'{name}.html'
                sample.write_text(html, encoding='utf-8')
                for width, height in ((390, 844), (1440, 1000)):
                    with self.subTest(name=name, width=width):
                        startup = subprocess.STARTUPINFO()
                        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startup.wShowWindow = subprocess.SW_HIDE
                        result = subprocess.run([
                            str(CHROME), '--headless=new', '--disable-gpu', '--no-first-run',
                            '--disable-background-networking', f'--user-data-dir={folder}/chrome-{name}-{width}',
                            f'--window-size={width},{height}', '--dump-dom', '--virtual-time-budget=1000', sample.as_uri(),
                        ], capture_output=True, text=True, encoding='utf-8', timeout=30, startupinfo=startup)
                        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
                        marker = re.search(r'data-planning-checks="([^"]+)"', result.stdout)
                        self.assertIsNotNone(marker, result.stderr[-1500:])
                        self.assertEqual(marker[1], 'passed')
        finally:
            fixture.tearDown()
            if folder.resolve().parent == ROOT and folder.name.startswith('.planning-browser-'):
                shutil.rmtree(folder)


if __name__ == '__main__':
    unittest.main()
