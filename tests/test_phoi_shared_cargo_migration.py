"""Additive cargo migration preserves legacy money; rollback cannot discard new customer debts."""
from pathlib import Path
import unittest
from unittest.mock import patch

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app import create_app, db
from app.models import Phoi
from config import TestingConfig


MIGRATIONS = str(Path(__file__).resolve().parents[1] / 'migrations')


class SharedCargoMigrationTests(unittest.TestCase):
    def setUp(self):
        with patch('app.get_config', return_value=TestingConfig):
            self.app = create_app('testing')
        self.context = self.app.app_context()
        self.context.push()
        self.assertEqual(str(db.engine.url), 'sqlite:///:memory:')
        upgrade(directory=MIGRATIONS, revision='d8e9f0a1b2c3')
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, full_name, password_hash, role) VALUES (1, 'legacy-driver', 'Driver', 'unused', 'driver')"))
            connection.execute(text("INSERT INTO trucks (id, license_plate) VALUES (1, 'CARGO-LEGACY')"))
            connection.execute(text("INSERT INTO customers (id, name) VALUES (1, 'Legacy customer'), (2, 'Shared customer')"))
            connection.execute(text("""INSERT INTO phoi
                (id, phoi_number, driver_id, truck_id, customer_id, departure_date, origin, destination,
                 revenue_full, revenue_collected, manager_revenue_collected, driver_wage, driver_advance, status)
                VALUES (1, 'CARGO-LEGACY', 1, 1, 1, '2026-11-27', 'A', 'B', 1000000, 100000, 200000, 300000, 50000, 'confirmed')"""))

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def assert_legacy(self):
        phoi = db.session.get(Phoi, 1)
        self.assertEqual(phoi.total_revenue_full(), 1000000)
        self.assertEqual(phoi.total_revenue_collected(), 100000)
        self.assertEqual(phoi.total_manager_revenue_collected(), 200000)
        self.assertEqual(phoi.balance(), 200000)
        self.assertEqual(phoi.settlement_balance(), 150000)
        self.assertEqual(phoi.owner_profit(), 700000)
        self.assertEqual(phoi.cargo_items.count(), 0)

    def test_upgrade_and_empty_downgrade_reupgrade_preserve_legacy_data(self):
        upgrade(directory=MIGRATIONS)
        self.assert_legacy()
        db.session.remove()
        downgrade(directory=MIGRATIONS, revision='d8e9f0a1b2c3')
        self.assertNotIn('phoi_cargo_items', inspect(db.engine).get_table_names())
        with db.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT revenue_full, revenue_collected, manager_revenue_collected, driver_advance FROM phoi WHERE id=1')).one(), (1000000, 100000, 200000, 50000))
        upgrade(directory=MIGRATIONS)
        self.assert_legacy()

    def test_downgrade_refuses_to_discard_saved_shared_customer(self):
        upgrade(directory=MIGRATIONS)
        with db.engine.begin() as connection:
            connection.execute(text("""INSERT INTO phoi_cargo_items
                (phoi_id, item_order, customer_id, cargo_description, payment_method, revenue_full, revenue_collected, manager_revenue_collected)
                VALUES (1, 2, 2, 'Rice', 'fixed', 500000, 100000, 0)"""))
        with self.assertRaises(SystemExit):
            downgrade(directory=MIGRATIONS, revision='d8e9f0a1b2c3')
        with db.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT revenue_full, customer_id FROM phoi_cargo_items')).one(), (500000, 2))
            self.assertEqual(connection.execute(text('SELECT version_num FROM alembic_version')).scalar(), 'f1a2b3c4d5e6')
