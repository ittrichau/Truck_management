"""Deployed-schema upgrade/downgrade with existing records, plus backup restore."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import sqlite3
import unittest
from unittest.mock import patch

os.environ['FLASK_ENV'] = 'testing'
from flask_migrate import upgrade, downgrade
from sqlalchemy import inspect, text, create_engine
from app import create_app, db
from config import TestingConfig
from deploy.backup_database import backup_database

MIGRATIONS = str(Path(__file__).resolve().parents[1] / 'migrations')


class ScopeMigrationTests(unittest.TestCase):
    def test_upgrade_keeps_legacy_records_unassigned_and_finances_unchanged(self):
        with patch('app.get_config', return_value=TestingConfig): app = create_app('testing')
        with app.app_context():
            upgrade(directory=MIGRATIONS, revision='f8a9b0c1d2e3')
            with db.engine.begin() as conn:
                conn.execute(text("INSERT INTO users (id, username, password_hash, full_name, role, is_active) VALUES (1, 'admin', 'unused', 'Admin', 'admin', 1), (2, 'manager', 'unused', 'Manager', 'manager', 1), (3, 'driver', 'unused', 'Driver', 'driver', 1)"))
                conn.execute(text("INSERT INTO trucks (id, license_plate, is_active) VALUES (1, 'OLD-TRUCK', 1)"))
                conn.execute(text("UPDATE users SET current_truck_id=1 WHERE id=3"))
                conn.execute(text("INSERT INTO customers (id, name, created_by_id, is_active) VALUES (1, 'OLD-CUSTOMER', 2, 1)"))
                conn.execute(text("INSERT INTO phoi (id, phoi_number, driver_id, truck_id, customer_id, departure_date, origin, destination, revenue_full, revenue_collected, manager_revenue_collected, driver_wage, status) VALUES (1, 'OLD-PHOI', 3, 1, 1, '2026-11-14', 'A', 'B', 1000, 100, 200, 50, 'confirmed')"))
                conn.execute(text("INSERT INTO activity_logs (id, user_id, action, details) VALUES (1, 2, 'UPDATE', 'legacy')"))
            try:
                upgrade(directory=MIGRATIONS)
                with db.engine.begin() as conn:
                    self.assertEqual(conn.execute(text('SELECT manager_id FROM trucks')).scalar(), None)
                    self.assertEqual(conn.execute(text('SELECT count(*) FROM manager_customers')).scalar(), 0)
                    self.assertEqual(conn.execute(text('SELECT current_truck_id FROM users WHERE id=3')).scalar(), 1)
                    self.assertEqual(tuple(conn.execute(text('SELECT revenue_full, revenue_collected, manager_revenue_collected, driver_wage FROM phoi')).one()), (1000, 100, 200, 50))
                    self.assertEqual(tuple(conn.execute(text('SELECT scope_truck_id, scope_manager_id FROM activity_logs')).one()), (None, None))
                    conn.execute(text('UPDATE trucks SET manager_id=2 WHERE id=1'))
                    conn.execute(text('UPDATE users SET manager_id=2 WHERE id=3'))
                    conn.execute(text('INSERT INTO manager_customers VALUES (2, 1)'))
                downgrade(directory=MIGRATIONS, revision='f8a9b0c1d2e3')
                self.assertNotIn('manager_id', {c['name'] for c in inspect(db.engine).get_columns('trucks')})
                with db.engine.connect() as conn:
                    self.assertEqual(conn.execute(text('SELECT revenue_full FROM phoi')).scalar(), 1000)
                upgrade(directory=MIGRATIONS)
            finally:
                db.session.remove()
                db.metadata.drop_all(db.engine)
                with db.engine.begin() as conn: conn.execute(text('DROP TABLE IF EXISTS alembic_version'))
                db.engine.dispose()

    def test_live_sqlite_backup_can_restore_data_without_changing_source(self):
        with TemporaryDirectory() as directory:
            engine = create_engine(f'sqlite:///{directory}/source.db')
            with engine.begin() as conn:
                conn.execute(text('CREATE TABLE records (amount NUMERIC)'))
                conn.execute(text('INSERT INTO records VALUES (350000)'))
            backup = backup_database(engine, Path(directory) / 'backups')
            with sqlite3.connect(backup) as restored:
                self.assertEqual(restored.execute('SELECT amount FROM records').fetchone()[0], 350000)
                self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            engine.dispose()

    def test_missing_postgres_backup_tool_blocks_deployment(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as directory, patch('deploy.backup_database.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'pg_dump'):
                backup_database(SimpleNamespace(dialect=SimpleNamespace(name='postgresql')), directory)


    def test_postgres_backup_keeps_password_out_of_arguments_and_verifies_archive(self):
        from types import SimpleNamespace
        from sqlalchemy.engine import URL
        engine = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'),
            url=URL.create('postgresql+psycopg2', username='user', password='secret-password',
                           host='database', database='trucks', query={'sslmode': 'require'}))
        def run(command, **kwargs):
            self.assertNotIn('secret-password', str(command))
            if command[0] == 'pg_dump':
                self.assertEqual(kwargs['env']['PGPASSWORD'], 'secret-password')
                self.assertIn('sslmode=require', command[-1])
                self.assertNotIn('***', command[-1])
                kwargs['stdout'].write(b'archive-fixture')
        with TemporaryDirectory() as directory, patch('deploy.backup_database.shutil.which', return_value='/bin/pg_dump'), patch('deploy.backup_database.subprocess.run', side_effect=run) as calls:
            backup = backup_database(engine, directory)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(calls.call_count, 2)


if __name__ == '__main__': unittest.main()
