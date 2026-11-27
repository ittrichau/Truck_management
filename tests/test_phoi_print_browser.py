"""Optional real-Chrome PDF and dynamic-form checks; no development server."""
from datetime import date
from decimal import Decimal
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

from flask import g

from app import create_app, db
from app.models import Customer, FuelLog, Phoi, PhoiExpense, PhoiReturnTrip, PhoiCargoItem, Truck, User
from config import TestingConfig


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def browser_workspace():
    # Python 3.13's Windows mode=0700 temp directories can exclude the sandbox's
    # restricted token. Inherit the workspace ACL for these synthetic fixtures.
    work = ROOT / f'.phoi-print-test-{uuid4().hex}'
    work.mkdir()
    try:
        yield work
    finally:
        if work.resolve().parent == ROOT and work.name.startswith('.phoi-print-test-'):
            shutil.rmtree(work)


CHROME = os.environ.get('PHOI_TEST_CHROME') or shutil.which('google-chrome') or shutil.which('chromium')
if not CHROME and os.name == 'nt':
    candidate = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    CHROME = str(candidate) if candidate.exists() else None


@unittest.skipUnless(CHROME and shutil.which('node'), 'Chrome and Node.js required for PDF checks')
class PrintBrowserTests(unittest.TestCase):
    def test_pdf_stays_one_a4_page_and_dynamic_expenses_validate(self):
        with browser_workspace() as work:
            artifact_dir = Path(os.environ.get('PHOI_PRINT_ARTIFACT_DIR', str(work)))
            artifact_dir.mkdir(parents=True, exist_ok=True)
            manifest = self.snapshots(work, artifact_dir)
            manifest_file = work / 'manifest.json'
            manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
            startup = None
            if os.name == 'nt':
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = subprocess.SW_HIDE
            profile = work / 'browser-profile'
            process = subprocess.Popen([
                CHROME, '--headless=new', '--disable-gpu', '--no-first-run',
                '--no-default-browser-check', '--disable-background-networking',
                '--remote-debugging-port=0', f'--user-data-dir={profile}', 'about:blank',
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startup)
            try:
                port_file = profile / 'DevToolsActivePort'
                for _ in range(200):
                    if port_file.exists():
                        break
                    if process.poll() is not None:
                        self.fail(f'Chrome exited with {process.returncode}')
                    time.sleep(0.05)
                lines = port_file.read_text().splitlines()
                result = subprocess.run([
                    'node', '--experimental-websocket', str(ROOT / 'tests/phoi_browser_checks.mjs'),
                    f'ws://127.0.0.1:{lines[0]}{lines[1]}', str(manifest_file),
                ], text=True, capture_output=True, encoding='utf-8', timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                checks = json.loads(result.stdout)
                self.assertEqual(len(checks), len(manifest['prints']) + len(manifest['forms']) + len(manifest['confirmations']) + len(manifest['cargoForms']))
                print('\nBrowser checks:', json.dumps(checks, ensure_ascii=True))
            finally:
                process.terminate()
                process.wait(timeout=15)

    def snapshots(self, work, artifacts):
        with patch('app.get_config', return_value=TestingConfig):
            app = create_app('testing')
        app.config.update(SECRET_KEY='print-tests', RATELIMIT_ENABLED=False)
        manifest = {'prints': [], 'forms': [], 'confirmations': [], 'cargoForms': []}

        def save(html, name):
            # Keep local application styles/scripts; prevent CDN/network calls.
            html = re.sub(r'<link\b[^>]*href="https?://[^>]*>', '', html)
            html = re.sub(r'<script\b[^>]*src="https?://[^>]*></script>', '', html)
            html = re.sub(r'<link\b[^>]*href="/static/([^"?]+)"[^>]*>',
                          lambda m: '<style>' + (ROOT / 'app/static' / m[1]).read_text(encoding='utf-8') + '</style>' if m[1].endswith('.css') else '', html)
            html = re.sub(r'<script src="/static/([^"?]+)"></script>',
                          lambda m: '<script>' + (ROOT / 'app/static' / m[1]).read_text(encoding='utf-8') + '</script>', html)
            # app.js expects htmx; this stub only replaces the disconnected CDN.
            html = html.replace('<head>', '<head><script>window.htmx={config:{}};</script><style>.d-none{display:none!important}</style>')
            path = work / f'{name}.html'
            path.write_text(html, encoding='utf-8')
            return str(path)

        with app.app_context():
            self.assertEqual(str(db.engine.url), 'sqlite:///:memory:')
            db.create_all()
            driver = User(username='driver', full_name='Nguyễn Văn Tài', password_hash='unused', role='driver')
            manager = User(username='manager', full_name='Chủ xe', password_hash='unused', role='manager')
            truck = Truck(license_plate='71C-123.45')
            db.session.add_all([driver, manager, truck])
            db.session.flush()
            truck.manager_id = manager.id
            driver.manager_id = manager.id
            driver.current_truck_id = truck.id
            customers = [Customer(name=f'Khách ghép {n}', cargo_type=f'Hàng {n}', managers=[manager]) for n in range(1, 4)]
            db.session.add_all(customers)
            db.session.commit()
            client = app.test_client()

            def login(user):
                g.pop('_login_user', None)
                with client.session_transaction() as session:
                    session['_user_id'] = str(user.id)
                    session['_fresh'] = True

            login(driver)
            manifest['forms'].append(save(client.get('/phoi/create').get_data(as_text=True), 'create-form'))
            manifest['cargoForms'].append({'html': manifest['forms'][0], 'saved': False})
            for count, long in ((0, False), (1, False), (3, False), (5, True), (10, True), (20, True)):
                phoi = Phoi(phoi_number=f'PRINT-{count}', driver_id=driver.id, truck_id=truck.id,
                            departure_date=date(2026, 11, 9), origin='Bến Tre', destination='Tây Ninh',
                            cargo_description='Dừa nguyên trái', cargo_weight_tons=18.5,
                            km_start=0, km_end=650, km_total=650, revenue_full=3600000,
                            revenue_collected=500000, driver_wage=450000, driver_advance=200000,
                            notes='Giao hàng đủ. Giữ lại hóa đơn chi phí để đối soát.')
                db.session.add(phoi)
                db.session.flush()
                markers = ['Vá lốp và phí vào kho chuyến đi.']
                markers.append('Quản lý đã ứng (trừ khi quyết toán): 200,000 VNĐ')
                description = 'Phí vào kho, vá lốp và rửa xe sau khi dỡ hàng. ' if long else 'Phí vào kho.'
                db.session.add(PhoiExpense(phoi_id=phoi.id, category='other', amount=150000,
                                          description=(markers[0] + ' ' + description * (4 if long else 1))[:200]))
                for category, amount in (('porter_fee', 80000), ('toll_fee', 350000), ('repair', 250000)):
                    db.session.add(PhoiExpense(phoi_id=phoi.id, category=category, amount=amount,
                                              description='Thay van bánh xe', is_home_repair=True))
                for n in range(min(count, 3)):
                    fuel = FuelLog(truck_id=truck.id, refuel_date=date(2026, 11, 9 + n),
                                   liters=('137.335', '80', '12.5')[n], price_per_liter=20000,
                                   total_cost=('2746700', '1600000', '250000')[n],
                                   paid_by='driver' if n == 2 else 'owner')
                    fuel.phois.append(phoi)
                    db.session.add(fuel)
                for n in range(count):
                    trip = PhoiReturnTrip(phoi_id=phoi.id, trip_order=n + 1, origin='Tây Ninh',
                                          destination='Bến Tre', cargo_description='Lúa giống',
                                          cargo_weight_tons=20.5, return_date=date(2026, 11, 10),
                                          revenue_full=4000000, revenue_collected=200000,
                                          manager_revenue_collected=100000, porter_fee=50000,
                                          notes='Đã giao hàng và nhận đủ chứng từ.' if long else '')
                    db.session.add(trip)
                    marker = f'Phí kho chuyến về số {n + 1}.'
                    markers.append(marker)
                    db.session.add(PhoiExpense(phoi_id=phoi.id, category='other', amount=75000,
                                              description=(description * (4 if long else 1))[:170] + marker, return_trip=trip))
                db.session.commit()
                for user in (manager, driver):
                    login(user)
                    name = f'{user.role}-{count}-returns'
                    html = save(client.get(f'/phoi/{phoi.id}/print').get_data(as_text=True), name)
                    manifest['prints'].append({
                        'name': name, 'html': html, 'pdf': str(artifacts / f'{name}.pdf'),
                        'expenseCount': count + 1, 'markers': markers, 'mobile': user.is_driver(),
                        **({'screenshot': str(artifacts / f'{name}.png')} if count == 3 and user == manager else {}),
                    })
                if count == 0:
                    phoi.status = 'submitted'
                    db.session.commit()
                    login(manager)
                    manifest['confirmations'].append(save(client.get(f'/phoi/{phoi.id}/confirm').get_data(as_text=True), 'confirm-form'))
                    # Dynamic edit fields are tested on a phơi with no return rows.
                    login(driver)
                    empty = Phoi(phoi_number='EMPTY-EDIT', driver_id=driver.id, truck_id=truck.id,
                                 departure_date=date(2026, 11, 9), origin='A', destination='B',
                                 driver_advance=Decimal('200000.25'))
                    db.session.add(empty)
                    db.session.commit()
                    manifest['forms'].append(save(client.get(f'/phoi/{empty.id}/edit').get_data(as_text=True), 'edit-form'))
            shared = Phoi(phoi_number='PRINT-SHARED', driver_id=driver.id, truck_id=truck.id,
                          customer_id=customers[0].id, departure_date=date(2026, 11, 9),
                          origin='A', destination='B', cargo_description='Hàng 1', revenue_full=1000000,
                          revenue_collected=100000, driver_wage=200000, status='draft')
            db.session.add(shared)
            db.session.flush()
            shared_return = PhoiReturnTrip(phoi_id=shared.id, customer_id=customers[0].id, trip_order=1,
                                          origin='B', destination='A', cargo_description='Hàng về 1',
                                          revenue_full=700000, revenue_collected=0)
            db.session.add(shared_return)
            db.session.flush()
            for return_id in (None, shared_return.id):
                for n, customer in enumerate(customers[1:], 2):
                    db.session.add(PhoiCargoItem(phoi_id=shared.id, return_trip_id=return_id,
                        item_order=n, customer_id=customer.id, cargo_description=f'Hàng riêng {n}',
                        payment_method='per_ton' if n == 2 else 'fixed', cargo_weight_tons=Decimal('0.500') if n == 2 else None,
                        price_per_ton=300000 if n == 2 else None, revenue_full=150000 if n == 2 else 300000,
                        revenue_collected=50000, manager_revenue_collected=20000))
            db.session.commit()
            login(manager)
            shared_html = save(client.get(f'/phoi/{shared.id}/print').get_data(as_text=True), 'shared-print')
            manifest['prints'].append({'name': 'shared-print', 'html': shared_html,
                'pdf': str(artifacts / 'shared-print.pdf'), 'expenseCount': 0,
                'markers': ['Khách #2: Khách ghép 2', 'Khách #3: Khách ghép 3', '2,600,000 VNĐ'], 'mobile': True})
            manifest['cargoForms'].append({'html': save(client.get(f'/phoi/{shared.id}/edit').get_data(as_text=True), 'shared-edit'), 'saved': True})
            shared.status = 'submitted'
            db.session.commit()
            manifest['confirmations'].append(save(client.get(f'/phoi/{shared.id}/confirm').get_data(as_text=True), 'shared-confirm'))
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        return manifest


if __name__ == '__main__':
    unittest.main()
