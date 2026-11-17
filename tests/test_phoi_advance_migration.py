"""Advance migration preserves existing settlements and can be rolled back."""
from pathlib import Path
import unittest
from unittest.mock import patch

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app import create_app, db
from app.models import Phoi
from config import TestingConfig


MIGRATIONS = str(Path(__file__).resolve().parents[1] / 'migrations')


class PhoiAdvanceMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_preserve_legacy_phoi_and_linked_expenses(self):
        with patch('app.get_config', return_value=TestingConfig):
            app = create_app('testing')
        with app.app_context():
            self.assertEqual(str(db.engine.url), 'sqlite:///:memory:')
            try:
                upgrade(directory=MIGRATIONS, revision='f8a9b0c1d2e3')
                with db.engine.begin() as connection:
                    connection.execute(text("INSERT INTO trucks (id, license_plate) VALUES (1, 'ADV-LEGACY')"))
                    connection.execute(text("INSERT INTO users (id, username, full_name, password_hash, role) VALUES (1, 'legacy', 'Legacy', 'unused', 'driver')"))
                    connection.execute(text("""INSERT INTO phoi
                        (id, phoi_number, driver_id, truck_id, departure_date, origin, destination,
                         revenue_full, revenue_collected, driver_wage, status)
                        VALUES (1, 'ADV-LEGACY', 1, 1, '2026-11-17', 'A', 'B', 1000000, 100000, 300000, 'confirmed')"""))
                    connection.execute(text("INSERT INTO phoi_expenses (id, phoi_id, category, amount) VALUES (1, 1, 'porter_fee', 50000)"))
                upgrade(directory=MIGRATIONS)
                phoi = db.session.get(Phoi, 1)
                self.assertEqual(phoi.driver_advance, 0)
                self.assertEqual(phoi.settlement_balance(), 250000)
                phoi.driver_advance = 200000
                db.session.commit()
                db.session.expire_all()
                self.assertEqual(phoi.settlement_balance(), 50000)
                self.assertEqual(phoi.balance(), 250000)
                self.assertEqual(phoi.owner_profit(), 650000)
                db.session.remove()
                downgrade(directory=MIGRATIONS, revision='f8a9b0c1d2e3')
                self.assertNotIn('driver_advance', {column['name'] for column in inspect(db.engine).get_columns('phoi')})
                with db.engine.connect() as connection:
                    self.assertEqual(connection.execute(text('SELECT phoi_number, status, driver_wage FROM phoi WHERE id=1')).one(), ('ADV-LEGACY', 'confirmed', 300000))
                    self.assertEqual(connection.execute(text('SELECT phoi_id, amount FROM phoi_expenses WHERE id=1')).one(), (1, 50000))
                upgrade(directory=MIGRATIONS)
                self.assertEqual(db.session.get(Phoi, 1).driver_advance, 0)
            finally:
                db.session.remove()
                db.drop_all()
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
