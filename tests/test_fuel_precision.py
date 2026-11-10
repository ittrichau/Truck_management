"""Regression coverage for three-decimal fuel quantities and Decimal arithmetic."""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from flask_migrate import downgrade, upgrade
from flask import g
from PIL import Image
from sqlalchemy import inspect

from app import create_app, db
from app.models import FuelLog, FuelPrice, FuelReceipt, Phoi, Truck, User
from config import TestingConfig


MIGRATIONS = str(Path(__file__).resolve().parents[1] / 'migrations')


class FuelPrecisionTests(unittest.TestCase):
    def setUp(self):
        with patch('app.get_config', return_value=TestingConfig):
            self.app = create_app('testing')
        self.uploads = TemporaryDirectory()
        self.app.config.update(
            SECRET_KEY='fuel-test-key', RATELIMIT_ENABLED=False,
            PHOI_ATTACHMENT_UPLOAD_FOLDER=self.uploads.name,
        )
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.seed()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        self.uploads.cleanup()

    def seed(self):
        self.driver = User(username='fuel-driver', full_name='Driver',
                           password_hash='unused', role='driver')
        self.admin = User(username='fuel-admin', full_name='Admin',
                          password_hash='unused', role='admin')
        self.manager = User(username='fuel-manager', full_name='Manager',
                            password_hash='unused', role='manager')
        self.truck = Truck(license_plate='FUEL-001')
        db.session.add_all([self.driver, self.admin, self.manager, self.truck])
        db.session.flush()
        self.driver.current_truck_id = self.truck.id
        self.phoi = Phoi(
            phoi_number='P-FUEL-001', driver_id=self.driver.id,
            truck_id=self.truck.id, departure_date=date(2026, 11, 9),
            origin='A', destination='B', status='draft',
        )
        db.session.add(self.phoi)
        db.session.commit()
        self.login(self.driver)

    def login(self, user):
        # Each test holds an app context; clear Flask-Login's cached user.
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def photo(self):
        stream = BytesIO()
        Image.new('RGB', (4, 4), 'white').save(stream, format='PNG')
        stream.seek(0)
        return stream, 'receipt.png'

    def create(self, liters='137.335', **overrides):
        data = dict(
            liters=liters, price_per_liter='25,000',
            truck_id=str(self.truck.id), phoi_id=str(self.phoi.id),
            refuel_date='2026-11-09', paid_by='driver', receipts=self.photo(),
        )
        data.update(overrides)
        return self.client.post('/fuel/create', data=data)

    def add_log(self, liters='100.00'):
        log = FuelLog(
            truck_id=self.truck.id, liters=Decimal(liters),
            price_per_liter=Decimal('25000.00'),
            total_cost=Decimal(liters) * Decimal('25000.00'),
            refuel_date=date(2026, 11, 9), created_by_id=self.driver.id,
            paid_by='driver',
        )
        log.phois.append(self.phoi)
        db.session.add(log)
        db.session.flush()
        db.session.add(FuelReceipt(
            fuel_log_id=log.id, uploaded_by_id=self.driver.id,
            original_filename='existing.png', storage_key='existing.png',
            mime_type='image/png', file_size=10, width=4, height=4,
        ))
        db.session.commit()
        return log

    def test_create_preserves_three_decimals_with_manual_and_active_price(self):
        for active_price in (False, True):
            with self.subTest(active_price=active_price):
                if active_price:
                    db.session.add(FuelPrice(
                        price_per_liter=Decimal('25000.00'),
                        effective_from=datetime(2026, 11, 8),
                    ))
                    db.session.commit()
                response = self.create()
                self.assertEqual(response.status_code, 302)
                db.session.expire_all()
                log = FuelLog.query.order_by(FuelLog.id.desc()).first()
                self.assertEqual(log.liters, Decimal('137.335'))
                self.assertEqual(log.total_cost, Decimal('3433375.00'))
                self.assertEqual(log.phois.one().id, self.phoi.id)
                self.assertEqual(log.receipts.count(), 1)
                self.assertEqual(self.phoi.driver_fuel_expenses(),
                                 Decimal('3433375.00') * (1 + active_price))

    def test_edit_reloads_and_resubmits_exact_quantity(self):
        log = self.add_log()
        response = self.client.post(f'/fuel/{log.id}/edit', data={
            'liters': '137.335', 'refuel_date': '2026-11-09',
        })
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        self.assertEqual(log.liters, Decimal('137.335'))
        self.assertEqual(log.total_cost, Decimal('3433375.00'))
        page = self.client.get(f'/fuel/{log.id}/edit')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'value="137.335"', page.data)
        response = self.client.post(f'/fuel/{log.id}/edit', data={
            'liters': '137.335', 'refuel_date': '2026-11-09',
        })
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        self.assertEqual(log.liters, Decimal('137.335'))
        self.assertEqual(self.phoi.fuel_expenses(), Decimal('3433375.00'))
        self.assertEqual(self.phoi.balance(), Decimal('3433375.00'))

    def test_integer_two_decimal_and_smallest_quantity(self):
        log = self.add_log()
        for value in ('137', '137.33', '0.001'):
            with self.subTest(value=value):
                response = self.client.post(f'/fuel/{log.id}/edit', data={
                    'liters': value, 'refuel_date': '2026-11-09',
                })
                self.assertEqual(response.status_code, 302)
                db.session.expire_all()
                self.assertEqual(log.liters, Decimal(value))
                self.assertEqual(log.total_cost, Decimal(value) * Decimal('25000'))

    def test_invalid_quantities_do_not_create_or_modify_logs(self):
        log = self.add_log()
        for value in ('0', '-1', '', 'abc', 'NaN', 'Infinity', '137.3351',
                      '0.0001', '10000000000'):
            with self.subTest(value=value):
                self.assertEqual(self.create(value).status_code, 200)
                response = self.client.post(f'/fuel/{log.id}/edit', data={
                    'liters': value, 'refuel_date': '2026-11-09',
                })
                self.assertEqual(response.status_code, 200)
                db.session.expire_all()
                self.assertEqual(log.liters, Decimal('100'))
                self.assertEqual(log.total_cost, Decimal('2500000'))
                self.assertEqual(FuelLog.query.count(), 1)

    def test_receipt_and_same_truck_requirements_remain_enforced(self):
        self.assertEqual(self.create(receipts=[]).status_code, 200)
        other = Truck(license_plate='FUEL-002')
        db.session.add(other)
        db.session.commit()
        self.assertEqual(self.create(truck_id=str(other.id)).status_code, 200)
        self.assertEqual(FuelLog.query.count(), 0)

    def test_confirmed_log_permissions_remain_enforced(self):
        log = self.add_log()
        self.phoi.status = 'confirmed'
        db.session.commit()
        for user in (self.driver, self.manager, self.admin):
            with self.subTest(role=user.role):
                self.login(user)
                response = self.client.post(f'/fuel/{log.id}/edit', data={
                    'liters': '137.335', 'refuel_date': '2026-11-09',
                })
                self.assertEqual(response.status_code, 302)
                db.session.expire_all()
                self.assertEqual(log.liters, Decimal('137.335' if user.is_admin() else '100'))

    def test_migration_preserves_existing_data_links_and_safe_downgrade(self):
        db.session.remove()
        db.drop_all()
        upgrade(directory=MIGRATIONS, revision='c4d5e6f7a8b9')
        self.seed()
        log = self.add_log('137.33')
        log_id, phoi_id = log.id, self.phoi.id
        # Close ORM read transactions before Alembic opens a DDL connection.
        # PostgreSQL otherwise waits for this test's own table locks.
        db.session.remove()
        upgrade(directory=MIGRATIONS)
        column = next(c for c in inspect(db.engine).get_columns('fuel_logs')
                      if c['name'] == 'liters')
        self.assertEqual((column['type'].precision, column['type'].scale), (13, 3))
        log = db.session.get(FuelLog, log_id)
        self.assertEqual(log.liters, Decimal('137.330'))
        self.assertEqual(log.total_cost, Decimal('3433250'))
        self.assertEqual(log.phois.one().id, phoi_id)
        self.assertEqual(log.receipts.count(), 1)
        # A downgrade is safe while all quantities still fit two decimal places.
        db.session.remove()
        downgrade(directory=MIGRATIONS, revision='c4d5e6f7a8b9')
        upgrade(directory=MIGRATIONS)
        response = self.client.post(f'/fuel/{log_id}/edit', data={
            'liters': '137.335', 'refuel_date': '2026-11-09',
        })
        self.assertEqual(response.status_code, 302)
        db.session.remove()
        # Flask-Migrate turns the migration's RuntimeError into a CLI exit.
        with self.assertRaises(SystemExit) as blocked:
            downgrade(directory=MIGRATIONS, revision='c4d5e6f7a8b9')
        self.assertEqual(blocked.exception.code, 1)
        db.session.expire_all()
        self.assertEqual(db.session.get(FuelLog, log_id).liters, Decimal('137.335'))


if __name__ == '__main__':
    unittest.main()
