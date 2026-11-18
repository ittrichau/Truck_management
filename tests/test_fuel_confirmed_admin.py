"""Admin fuel corrections on confirmed phoi, with isolated data and uploads."""
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

import test_fuel_precision as precision
from test_fuel_manual_price import workspace_uploads
from app import db
from app.models import FuelLog, FuelPrice, Phoi, Truck


ROOT = Path(__file__).resolve().parents[1]


class FormFields(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.phoi_options = set()
        self.in_phoi_select = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name'):
            self.inputs[attrs['name']] = attrs
        if tag == 'select' and attrs.get('name') == 'phoi_id':
            self.in_phoi_select = True
        if tag == 'option' and self.in_phoi_select and attrs.get('value'):
            self.phoi_options.add(attrs['value'])

    def handle_endtag(self, tag):
        if tag == 'select':
            self.in_phoi_select = False


class ConfirmedAdminFuelTests(unittest.TestCase):
    seed = precision.FuelPrecisionTests.seed
    login = precision.FuelPrecisionTests.login
    photo = precision.FuelPrecisionTests.photo
    create = precision.FuelPrecisionTests.create
    add_log = precision.FuelPrecisionTests.add_log
    tearDown = precision.FuelPrecisionTests.tearDown

    def setUp(self):
        with patch.object(precision, 'TemporaryDirectory', workspace_uploads):
            precision.FuelPrecisionTests.setUp(self)
        self.log = self.add_log()
        self.phoi.status = 'confirmed'
        self.phoi.revenue_full = Decimal('10000000')
        self.phoi.revenue_collected = Decimal('500000')
        self.phoi.driver_wage = Decimal('450000')
        self.phoi.driver_advance = Decimal('200000')
        db.session.commit()
        self.login(self.admin)

    def edit(self, **overrides):
        data = dict(liters='137.335', price_per_liter='24,500',
                    refuel_date='2026-11-18')
        data.update(overrides)
        return self.client.post(f'/fuel/{self.log.id}/edit', data=data)

    def assert_original(self):
        db.session.expire_all()
        self.assertEqual(self.log.liters, Decimal('100'))
        self.assertEqual(self.log.price_per_liter, Decimal('25000'))
        self.assertEqual(self.log.total_cost, Decimal('2500000'))
        self.assertEqual(self.log.refuel_date, date(2026, 11, 9))
        self.assertEqual(self.log.receipts.count(), 1)
        self.assertEqual(self.log.receipts.one().image_type, 'receipt')
        self.assertEqual(self.log.phois.one().id, self.phoi.id)
        self.assertEqual(self.phoi.status, 'confirmed')

    def test_admin_edits_liters_price_and_finances_for_both_payers(self):
        for payer in ('owner', 'driver'):
            with self.subTest(payer=payer):
                self.log.paid_by = payer
                db.session.commit()
                response = self.edit()
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.location, f'/phoi/{self.phoi.id}')
                db.session.expire_all()
                total = Decimal('3364707.50')
                self.assertEqual(self.log.liters, Decimal('137.335'))
                self.assertEqual(self.log.price_per_liter, Decimal('24500'))
                self.assertEqual(self.log.total_cost, total)
                self.assertEqual(self.log.refuel_date, date(2026, 11, 18))
                self.assertEqual(self.phoi.fuel_expenses(), total)
                driver_fuel = total if payer == 'driver' else Decimal('0')
                self.assertEqual(self.phoi.balance(), driver_fuel - Decimal('50000'))
                self.assertEqual(self.phoi.settlement_balance(), driver_fuel - Decimal('250000'))
                self.assertEqual(self.phoi.owner_profit(), Decimal('9550000') - total)
                self.assertEqual(self.phoi.status, 'confirmed')
                self.assertEqual(self.log.created_by_id, self.driver.id)
                self.assertEqual(self.log.phois.one().id, self.phoi.id)
                self.assertEqual(self.log.receipts.count(), 1)

    def test_fractional_price_and_old_form_preserve_saved_price(self):
        self.assertEqual(self.edit(liters='100', price_per_liter='24500.25').status_code, 302)
        db.session.expire_all()
        page = self.client.get(f'/fuel/{self.log.id}/edit')
        fields = FormFields(page.get_data(as_text=True)).inputs
        self.assertEqual(fields['price_per_liter']['value'], '24500.25')
        self.assertIn('data-decimal-money', fields['price_per_liter'])
        old_form = self.client.post(f'/fuel/{self.log.id}/edit', data={
            'liters': '101', 'refuel_date': '2026-11-18',
        })
        self.assertEqual(old_form.status_code, 302)
        db.session.expire_all()
        self.assertEqual(self.log.price_per_liter, Decimal('24500.25'))
        self.assertEqual(self.log.total_cost, Decimal('2474525.25'))

    def test_admin_edit_and_detail_pages_expose_fuel_actions(self):
        for status in ('submitted', 'confirmed'):
            self.phoi.status = status
            db.session.commit()
            for path in (f'/phoi/{self.phoi.id}', f'/phoi/{self.phoi.id}/edit'):
                with self.subTest(status=status, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(f'href="/fuel/{self.log.id}/edit"', response.text)
                    self.assertIn(f'href="/fuel/create?phoi_id={self.phoi.id}&amp;truck_id={self.truck.id}"', response.text)

    def test_admin_adds_confirmed_fuel_with_receipt_and_financial_updates(self):
        for payer in ('owner', 'driver'):
            with self.subTest(payer=payer):
                page = self.client.get(f'/fuel/create?phoi_id={self.phoi.id}')
                self.assertEqual(page.status_code, 200)
                fields = FormFields(page.text)
                self.assertIn(str(self.phoi.id), fields.phoi_options)
                self.assertEqual(fields.inputs['return_to_phoi_id']['value'], str(self.phoi.id))
                response = self.create(liters='10.125', price_per_liter='24,500',
                                       paid_by=payer, return_to_phoi_id=str(self.phoi.id))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.location, f'/phoi/{self.phoi.id}')
                db.session.expire_all()
                added = FuelLog.query.order_by(FuelLog.id.desc()).first()
                self.assertEqual(added.total_cost, Decimal('248062.50'))
                self.assertEqual(added.phois.one().id, self.phoi.id)
                self.assertEqual(added.truck_id, self.truck.id)
                self.assertEqual(added.receipts.count(), 1)
                self.assertEqual(added.created_by_id, self.admin.id)
                self.assertEqual(self.phoi.status, 'confirmed')
        self.assertEqual(FuelLog.query.count(), 3)
        self.assertEqual(self.phoi.fuel_expenses(), Decimal('2996125'))
        self.assertEqual(self.phoi.balance(), Decimal('2698062.50'))
        self.assertEqual(self.phoi.settlement_balance(), Decimal('2498062.50'))
        self.assertEqual(self.phoi.owner_profit(), Decimal('6553875'))

    def test_admin_create_keeps_table_price_and_manual_override(self):
        from datetime import datetime
        db.session.add(FuelPrice(price_per_liter=Decimal('26000'),
                                 effective_from=datetime(2026, 11, 8)))
        db.session.commit()
        for manual, expected in (('0', '26000'), ('1', '24500')):
            response = self.create(use_manual_price=manual, price_per_liter='24,500')
            self.assertEqual(response.status_code, 302)
            added = FuelLog.query.order_by(FuelLog.id.desc()).first()
            self.assertEqual(added.price_per_liter, Decimal(expected))

    def test_manager_and_driver_cannot_edit_or_add_confirmed_fuel(self):
        for actor in (self.manager, self.driver):
            with self.subTest(role=actor.role):
                self.login(actor)
                page = self.client.get('/fuel/create')
                self.assertNotIn(str(self.phoi.id), FormFields(page.text).phoi_options)
                self.assertEqual(self.client.get(f'/fuel/create?phoi_id={self.phoi.id}').status_code, 302)
                self.assertEqual(self.client.get(f'/fuel/{self.log.id}/edit').status_code, 302)
                self.assertEqual(self.edit().status_code, 302)
                self.assertEqual(self.create().status_code, 200)
                self.assert_original()
                self.assertEqual(FuelLog.query.count(), 1)
                detail = self.client.get(f'/phoi/{self.phoi.id}').text
                self.assertNotIn(f'href="/fuel/{self.log.id}/edit"', detail)
                self.assertNotIn('href="/fuel/create?', detail)

    def test_non_admin_cannot_forge_price_changes_on_open_phoi(self):
        for status in ('draft', 'submitted'):
            self.phoi.status = status
            db.session.commit()
            for actor in (self.manager, self.driver):
                with self.subTest(status=status, role=actor.role):
                    self.login(actor)
                    page = self.client.get(f'/fuel/{self.log.id}/edit')
                    self.assertEqual(page.status_code, 200)
                    self.assertNotIn('price_per_liter', FormFields(page.text).inputs)
                    self.assertEqual(self.edit().status_code, 200)
                    db.session.expire_all()
                    self.assertEqual(self.log.liters, Decimal('100'))
                    self.assertEqual(self.log.price_per_liter, Decimal('25000'))

    def test_invalid_price_or_total_rolls_back_whole_edit(self):
        for price in ('', 'abc', '0', '-1', 'NaN', 'Infinity', '10000000000', '1.001'):
            with self.subTest(price=price):
                self.assertEqual(self.edit(price_per_liter=price, is_home_station='1').status_code, 200)
                self.assert_original()
        self.assertEqual(self.edit(liters='9999999999.999', price_per_liter='25000').status_code, 200)
        self.assert_original()

    def test_shared_confirmed_fuel_remains_blocked_for_admin(self):
        second = Phoi(phoi_number='SHARED-LEGACY', driver_id=self.driver.id,
                      truck_id=self.truck.id, departure_date=date(2026, 11, 9),
                      origin='B', destination='C', status='draft')
        self.log.phois.append(second)
        db.session.commit()
        self.assertEqual(self.client.get(f'/fuel/{self.log.id}/edit').status_code, 302)
        self.assertEqual(self.edit().status_code, 302)
        for path in (f'/phoi/{self.phoi.id}', f'/phoi/{self.phoi.id}/edit'):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(f'href="/fuel/{self.log.id}/edit"', page.text)
        db.session.expire_all()
        self.assertEqual(self.log.total_cost, Decimal('2500000'))
        self.assertEqual(self.log.phois.count(), 2)
        self.assertEqual(self.phoi.fuel_expenses(), Decimal('1250000'))

    def test_create_guards_receipt_same_truck_cancelled_and_missing_phoi(self):
        other = Truck(license_plate='FUEL-OTHER')
        db.session.add(other)
        db.session.commit()
        for overrides in ({'receipts': []}, {'receipts': [self.photo() for _ in range(6)]},
                          {'truck_id': str(other.id)}, {'phoi_id': ''}, {'phoi_id': '9999'}):
            with self.subTest(fields=list(overrides)):
                self.assertEqual(self.create(**overrides).status_code, 200)
                self.assert_original()
                self.assertEqual(FuelLog.query.count(), 1)
        self.phoi.status = 'cancelled'
        db.session.commit()
        self.assertEqual(self.client.get(f'/fuel/create?phoi_id={self.phoi.id}').status_code, 302)
        self.assertEqual(self.create().status_code, 200)
        self.assertEqual(FuelLog.query.count(), 1)

    def test_missing_edit_receipt_requires_upload_and_can_be_repaired(self):
        self.log.receipts.delete()
        db.session.commit()
        self.assertEqual(self.edit().status_code, 200)
        db.session.expire_all()
        self.assertEqual(self.log.total_cost, Decimal('2500000'))
        self.assertEqual(self.edit(receipts=self.photo()).status_code, 302)
        self.assertEqual(self.log.receipts.count(), 1)
        self.assertEqual(self.log.total_cost, Decimal('3364707.50'))

    def test_edit_receipt_limit_and_upload_failure_do_not_save_financial_changes(self):
        self.assertEqual(self.edit(receipts=[self.photo() for _ in range(5)]).status_code, 200)
        self.assert_original()
        with patch('app.routes.fuel.save_phoi_attachment', side_effect=ValueError('Ảnh không hợp lệ.')):
            response = self.edit(receipts=self.photo(), is_home_station='1')
        self.assertEqual(response.status_code, 200)
        self.assert_original()

    @unittest.skipUnless(Path('C:/Program Files/Google/Chrome/Application/chrome.exe').exists(),
                         'Chrome required for decimal price checks')
    def test_edit_price_survives_browser_initialization_focus_and_submit(self):
        self.log.price_per_liter = Decimal('24500.25')
        self.log.total_cost = Decimal('2450025')
        db.session.commit()
        html = self.client.get(f'/fuel/{self.log.id}/edit').text
        html = re.sub(r'<link\b[^>]*href="https?://[^>]*>', '', html)
        html = re.sub(r'<script\b[^>]*src="https?://[^>]*></script>', '', html)
        html = re.sub(r'<script src="/static/([^"?]+)"></script>',
                      lambda m: '<script>' + (ROOT / 'app/static' / m[1]).read_text(encoding='utf-8') + '</script>', html)
        html = html.replace('<head>', '<head><script>window.htmx={config:{}};</script>')
        checks = """
        document.addEventListener('DOMContentLoaded', () => {
            try {
                const price = document.getElementById('price_per_liter');
                const assert = (ok, msg) => { if (!ok) throw new Error(msg); };
                assert(price.type === 'number' && price.value === '24500.25', 'Initial price changed');
                price.focus();
                assert(price.value === '24500.25', 'Focus changed price');
                price.value = '24000.75';
                price.dispatchEvent(new Event('input', {bubbles: true}));
                price.form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
                assert(new FormData(price.form).get('price_per_liter') === '24000.75', 'Submit changed price');
                document.body.dataset.priceChecks = 'passed';
            } catch (error) { document.body.dataset.priceChecks = 'failed: ' + error.message; }
        });
        """
        html = html.replace('</body>', '<script>' + checks + '</script></body>')
        sample = Path(self.uploads.name) / 'edit-fuel.html'
        sample.write_text(html, encoding='utf-8')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run([
            'C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new',
            '--disable-gpu', '--no-first-run', '--disable-background-networking',
            f'--user-data-dir={self.uploads.name}/chrome', '--dump-dom',
            '--virtual-time-budget=1000', sample.as_uri(),
        ], capture_output=True, text=True, encoding='utf-8', timeout=30, startupinfo=startup)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        status = re.search(r'data-price-checks="([^"]+)"', result.stdout)
        self.assertIsNotNone(status, result.stderr[-2000:])
        self.assertEqual(status[1], 'passed')


if __name__ == '__main__':
    unittest.main()
