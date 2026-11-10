"""Fuel price overrides and numeric-entry regression checks, without a server."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import shutil
import re
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_fuel_precision as precision
from app import db
from app.models import FuelLog, FuelPrice

ROOT = Path(__file__).resolve().parents[1]


def workspace_uploads():
    # Inherit the workspace ACL; Windows Python 3.13 temp ACLs can deny the sandbox.
    folder = ROOT / f'.fuel-test-{uuid4().hex}'
    folder.mkdir()

    def cleanup():
        if folder.resolve().parent == ROOT and folder.name.startswith('.fuel-test-'):
            shutil.rmtree(folder)

    return SimpleNamespace(name=str(folder), cleanup=cleanup)


class ManualFuelPriceTests(unittest.TestCase):
    seed = precision.FuelPrecisionTests.seed
    login = precision.FuelPrecisionTests.login
    photo = precision.FuelPrecisionTests.photo
    create = precision.FuelPrecisionTests.create
    add_log = precision.FuelPrecisionTests.add_log
    tearDown = precision.FuelPrecisionTests.tearDown

    def setUp(self):
        with patch.object(precision, 'TemporaryDirectory', workspace_uploads):
            precision.FuelPrecisionTests.setUp(self)
        db.session.add(FuelPrice(
            price_per_liter=Decimal('25000'), effective_from=datetime(2026, 11, 8),
        ))
        db.session.commit()

    def test_manual_override_for_both_payers_and_default_compatibility(self):
        for payer in ('driver', 'owner'):
            response = self.create(liters='137.335', paid_by=payer,
                                   use_manual_price='1', price_per_liter='24,500')
            self.assertEqual(response.status_code, 302)
            db.session.expire_all()
            log = FuelLog.query.order_by(FuelLog.id.desc()).first()
            self.assertEqual(log.price_per_liter, Decimal('24500'))
            self.assertEqual(log.total_cost, Decimal('3364707.50'))
        response = self.create(price_per_liter='1')
        self.assertEqual(response.status_code, 302)
        log = FuelLog.query.order_by(FuelLog.id.desc()).first()
        self.assertEqual(log.price_per_liter, Decimal('25000'))
        self.assertEqual(self.phoi.driver_fuel_expenses(), Decimal('6798082.50'))
        self.assertEqual(self.phoi.fuel_expenses(), Decimal('10162790.00'))
        self.assertEqual(self.phoi.balance(), Decimal('6798082.50'))
        self.assertEqual(self.phoi.owner_profit(), Decimal('-10162790.00'))

    def test_invalid_manual_price_cannot_create_even_with_active_table(self):
        for value in ('', 'abc', '0', '-1', 'NaN', 'Infinity', '10000000000', '1.001'):
            with self.subTest(price=value):
                response = self.create(use_manual_price='1', price_per_liter=value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(FuelLog.query.count(), 0)
                self.assertIn(b'id="use_manual_price" value="1" checked', response.data)
        response = self.create(liters='9999999999.999', use_manual_price='1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FuelLog.query.count(), 0)

    def test_missing_table_requires_valid_manual_price(self):
        FuelPrice.query.delete()
        db.session.commit()
        self.assertEqual(self.create(price_per_liter='0').status_code, 200)
        self.assertEqual(FuelLog.query.count(), 0)
        self.assertEqual(self.create(price_per_liter='24,000').status_code, 302)
        self.assertEqual(FuelLog.query.one().price_per_liter, Decimal('24000'))

    def test_manual_price_keeps_receipt_phoi_and_truck_guards(self):
        for overrides in ({'receipts': []}, {'phoi_id': ''}, {'truck_id': '9999'}):
            self.assertEqual(self.create(use_manual_price='1', **overrides).status_code, 200)
            self.assertEqual(FuelLog.query.count(), 0)
        self.phoi.status = 'confirmed'
        db.session.commit()
        self.assertEqual(self.create(use_manual_price='1').status_code, 200)
        self.assertEqual(FuelLog.query.count(), 0)

    @unittest.skipUnless(Path('C:/Program Files/Google/Chrome/Application/chrome.exe').exists(),
                         'Chrome required for numeric input checks')
    def test_numeric_input_in_chrome(self):
        html = self.client.get('/fuel/create').get_data(as_text=True)
        html = re.sub(r'<link\b[^>]*href="https?://[^>]*>', '', html)
        html = re.sub(r'<script\b[^>]*src="https?://[^>]*></script>', '', html)
        html = re.sub(r'<script src="/static/([^"?]+)"></script>',
                      lambda m: '<script>' + (ROOT / 'app/static' / m[1]).read_text(encoding='utf-8') + '</script>', html)
        html = html.replace('<head>', '<head><script>window.htmx={config:{}};</script>')
        checks = (ROOT / 'tests/fuel_numeric_checks.js').read_text(encoding='utf-8')
        html = html.replace('</body>', '<script>' + checks + '</script></body>')
        sample = Path(self.uploads.name) / 'fuel.html'
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
        status = re.search(r'data-numeric-checks="([^"]+)"', result.stdout)
        self.assertIsNotNone(status, result.stderr[-2000:])
        self.assertEqual(status[1], 'passed')


if __name__ == '__main__':
    unittest.main()
