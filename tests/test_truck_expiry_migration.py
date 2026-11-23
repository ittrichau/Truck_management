"""Backfill exact legacy expiries and refuse lossy rollback of edited dates."""
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

from flask_migrate import upgrade, downgrade
from sqlalchemy import inspect, text
from app import create_app, db
from config import TestingConfig

MIGRATIONS = str(Path(__file__).resolve().parents[1] / 'migrations')
OLD_HEAD = 'b8d2c4f6a091'


class TruckExpiryMigrationTests(unittest.TestCase):
    def setUp(self):
        with patch('app.get_config', return_value=TestingConfig): self.app = create_app('testing')
        self.context = self.app.app_context(); self.context.push()
        upgrade(directory=MIGRATIONS, revision=OLD_HEAD)

    def tearDown(self):
        db.session.remove()
        with db.engine.begin() as connection:
            for table in reversed(inspect(db.engine).get_table_names()):
                connection.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
        db.engine.dispose(); self.context.pop()

    def insert(self, identity, start, months, permit_start=None, permit_months=None, active=1):
        with db.engine.begin() as connection:
            connection.execute(text('''INSERT INTO trucks
                (id, license_plate, inspection_date, inspection_expiry_months, permit_date,
                 permit_expiry_months, insurance_expiry_date, last_inspection_notified_at,
                 last_permit_notified_at, is_active)
                VALUES (:id, :plate, :start, :months, :permit, :term, '2028-02-29',
                        '2026-11-22 09:00:00', '2026-11-21 09:00:00', :active)'''),
                dict(id=identity, plate=f'LEGACY-{identity}', start=start, months=months,
                     permit=permit_start, term=permit_months, active=active))

    def rows(self):
        with db.engine.connect() as connection:
            return connection.execute(text('SELECT * FROM trucks ORDER BY id')).mappings().all()

    def test_backfill_month_ends_leap_year_variable_terms_null_zero_and_inactive_trucks(self):
        cases = [
            ('2026-01-31', 1, '2026-02-28'),
            ('2024-01-31', 1, '2024-02-29'),
            ('2024-02-29', 12, '2025-02-28'),
            ('2026-08-31', 6, '2027-02-28'),
            ('2026-11-23', 12, '2027-11-23'),
            ('2025-12-31', 18, '2027-06-30'),
            (None, 6, None), ('2026-01-31', None, None), ('2026-01-31', 0, None),
            ('2026-03-31', -1, '2026-02-28'),
        ]
        for identity, (start, months, expected) in enumerate(cases, 1):
            self.insert(identity, start, months, start, months, active=0 if identity == 4 else 1)
        before = self.rows()
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, full_name, password_hash, role, is_active) VALUES (1, 'manager', 'Manager', 'unused', 'manager', 1), (2, 'driver', 'Driver', 'unused', 'driver', 1)"))
            connection.execute(text('UPDATE trucks SET manager_id=1 WHERE id=1'))
            connection.execute(text('UPDATE users SET manager_id=1, current_truck_id=1 WHERE id=2'))
            connection.execute(text("INSERT INTO phoi (id, phoi_number, driver_id, truck_id, departure_date, origin, destination, revenue_full, revenue_collected, driver_wage, driver_advance, status) VALUES (1, 'LEGACY-EXPIRY', 2, 1, '2026-11-23', 'A', 'B', 1000, 100, 50, 25, 'confirmed')"))
        upgrade(directory=MIGRATIONS)
        after = self.rows()
        for old, new, (_, _, expected) in zip(before, after, cases, strict=True):
            with self.subTest(truck=new['id']):
                self.assertEqual(new['inspection_expires_on'], expected)
                self.assertEqual(new['permit_expires_on'], expected)
                for key in ('inspection_date', 'inspection_expiry_months', 'permit_date', 'permit_expiry_months',
                            'insurance_expiry_date', 'last_inspection_notified_at', 'last_permit_notified_at', 'is_active'):
                    self.assertEqual(new[key], old[key])
        with db.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT manager_id FROM trucks WHERE id=1')).scalar(), 1)
            self.assertEqual(tuple(connection.execute(text('SELECT current_truck_id, manager_id FROM users WHERE id=2')).one()), (1, 1))
            self.assertEqual(tuple(connection.execute(text('SELECT revenue_full, revenue_collected, driver_wage, driver_advance FROM phoi')).one()), (1000, 100, 50, 25))

    def test_unchanged_backfill_can_downgrade_and_upgrade_without_date_drift(self):
        self.insert(1, '2026-08-31', 6, '2024-02-29', 12)
        before = self.rows()
        upgrade(directory=MIGRATIONS)
        self.assertEqual(self.rows()[0]['inspection_expires_on'], '2027-02-28')
        downgrade(directory=MIGRATIONS, revision=OLD_HEAD)
        self.assertEqual(self.rows(), before)
        upgrade(directory=MIGRATIONS)
        self.assertEqual(self.rows()[0]['inspection_expires_on'], '2027-02-28')
        self.assertEqual(self.rows()[0]['permit_expires_on'], '2025-02-28')

    def test_changed_and_cleared_dates_block_lossy_downgrade_before_columns_are_dropped(self):
        self.insert(1, '2026-08-31', 6, '2024-02-29', 12)
        upgrade(directory=MIGRATIONS)
        for value in ('2028-02-29', None):
            with self.subTest(value=value):
                with db.engine.begin() as connection:
                    connection.execute(text('UPDATE trucks SET inspection_expires_on=:date WHERE id=1'), {'date': value})
                with self.assertRaises(SystemExit): downgrade(directory=MIGRATIONS, revision=OLD_HEAD)
                self.assertIn('inspection_expires_on', {column['name'] for column in inspect(db.engine).get_columns('trucks')})
                self.assertEqual(self.rows()[0]['inspection_expires_on'], value)

    def test_new_direct_date_blocks_downgrade_instead_of_dropping_user_input(self):
        upgrade(directory=MIGRATIONS)
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO trucks (id, license_plate, inspection_expires_on) VALUES (1, 'DIRECT', '2026-01-31')"))
        with self.assertRaises(SystemExit): downgrade(directory=MIGRATIONS, revision=OLD_HEAD)
        self.assertEqual(self.rows()[0]['inspection_expires_on'], '2026-01-31')

    def test_unrepresentable_legacy_expiry_fails_before_schema_change(self):
        self.insert(1, '9999-12-31', 12)
        with self.assertRaises(SystemExit): upgrade(directory=MIGRATIONS)
        self.assertNotIn('inspection_expires_on', {column['name'] for column in inspect(db.engine).get_columns('trucks')})
        self.assertEqual(self.rows()[0]['inspection_date'], '9999-12-31')


if __name__ == '__main__': unittest.main()
