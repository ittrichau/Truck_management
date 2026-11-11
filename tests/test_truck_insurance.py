import os
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ['FLASK_ENV'] = 'testing'

from alembic.config import Config
from alembic.script import ScriptDirectory
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app import create_app, db
from app.models import Truck, User


MIGRATIONS = str(Path(__file__).resolve().parents[1] / 'migrations')


class TruckInsuranceTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.manager = User(
            username='insurance-manager', full_name='Quản lý',
            role='manager', password_hash='unused',
        )
        self.driver = User(
            username='insurance-driver', full_name='Tài xế',
            role='driver', password_hash='unused',
        )
        self.truck = Truck(
            license_plate='INS-001', insurance_expiry_date=date(2027, 3, 20),
            inspection_date=date(2026, 10, 1), inspection_expiry_months=6,
            permit_date=date(2026, 10, 2), permit_expiry_months=12,
        )
        db.session.add_all([self.manager, self.driver, self.truck])
        db.session.flush()
        self.driver.current_truck_id = self.truck.id
        db.session.commit()
        self.login(self.manager)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def login(self, user):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def edit_form(self):
        return {
            'license_plate': self.truck.license_plate,
            'inspection_date': '2026-10-01', 'inspection_expiry_months': '6',
            'permit_date': '2026-10-02', 'permit_expiry_months': '12',
            'current_driver_id': str(self.driver.id),
            'insurance_expiry_date': '2028-02-29',
        }

    def test_create_with_direct_expiry_date_or_without_date(self):
        for plate, value, expected in (
            ('INS-002', '2028-02-29', date(2028, 2, 29)),
            ('INS-003', '', None),
            ('INS-004', None, None),
        ):
            with self.subTest(value=value):
                form = {'license_plate': plate}
                if value is not None:
                    form['insurance_expiry_date'] = value
                response = self.client.post('/trucks/create', data=form)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(Truck.query.filter_by(license_plate=plate).one().insurance_expiry_date, expected)

    def test_edit_updates_date_and_preserves_other_documents_and_assignment(self):
        response = self.client.post(f'/trucks/{self.truck.id}/edit', data=self.edit_form())
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        self.assertEqual(self.truck.insurance_expiry_date, date(2028, 2, 29))
        self.assertEqual(self.truck.inspection_date, date(2026, 10, 1))
        self.assertEqual(self.truck.permit_date, date(2026, 10, 2))
        self.assertEqual(self.driver.current_truck_id, self.truck.id)
        response = self.client.get(f'/trucks/{self.truck.id}/edit')
        self.assertIn(b'value="2028-02-29"', response.data)

    def test_omitted_edit_field_preserves_date_and_explicit_blank_clears_it(self):
        form = self.edit_form()
        del form['insurance_expiry_date']
        self.assertEqual(self.client.post(f'/trucks/{self.truck.id}/edit', data=form).status_code, 302)
        db.session.expire_all()
        self.assertEqual(self.truck.insurance_expiry_date, date(2027, 3, 20))
        form['insurance_expiry_date'] = ''
        self.assertEqual(self.client.post(f'/trucks/{self.truck.id}/edit', data=form).status_code, 302)
        db.session.expire_all()
        self.assertIsNone(self.truck.insurance_expiry_date)

    def test_invalid_dates_do_not_create_or_overwrite_trucks(self):
        for value in ('2027-02-29', '2026-13-01', 'bad-date'):
            with self.subTest(value=value):
                response = self.client.post('/trucks/create', data={
                    'license_plate': 'INVALID', 'insurance_expiry_date': value,
                })
                self.assertIn('Ngày hết hạn bảo hiểm không hợp lệ.', response.get_data(as_text=True))
                self.assertIsNone(Truck.query.filter_by(license_plate='INVALID').first())
                form = self.edit_form()
                form.update(insurance_expiry_date=value, license_plate='CHANGED')
                response = self.client.post(f'/trucks/{self.truck.id}/edit', data=form)
                self.assertIn('Ngày hết hạn bảo hiểm không hợp lệ.', response.get_data(as_text=True))
                db.session.expire_all()
                self.assertEqual(self.truck.license_plate, 'INS-001')
                self.assertEqual(self.truck.insurance_expiry_date, date(2027, 3, 20))
                self.assertEqual(self.driver.current_truck_id, self.truck.id)

    def test_list_shows_date_and_expiry_boundaries(self):
        for days, label in (
            (None, 'Chưa nhập'), (-1, 'Quá hạn 1 ngày'),
            (0, 'Hết hạn hôm nay'), (1, 'Còn 1 ngày'),
            (15, 'Còn 15 ngày'), (16, None),
        ):
            with self.subTest(days=days):
                self.truck.insurance_expiry_date = (
                    date.today() + timedelta(days=days) if days is not None else None
                )
                db.session.commit()
                self.assertEqual(self.truck.insurance_days_until_expiry(), days)
                response = self.client.get('/trucks')
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('Hết hạn bảo hiểm', html)
                if label:
                    self.assertIn(label, html)
                else:
                    self.assertNotIn('Còn 16 ngày', html)
                if days is not None:
                    self.assertIn(self.truck.insurance_expiry_date.strftime('%d/%m/%Y'), html)

    def test_driver_cannot_read_or_change_insurance(self):
        self.login(self.driver)
        for path in ('/trucks', '/trucks/create', f'/trucks/{self.truck.id}/edit'):
            self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.client.post('/trucks/create', data={
            'license_plate': 'BLOCKED', 'insurance_expiry_date': '2028-02-29',
        }).status_code, 302)
        self.assertEqual(self.client.post(f'/trucks/{self.truck.id}/edit', data=self.edit_form()).status_code, 302)
        self.assertIsNone(Truck.query.filter_by(license_plate='BLOCKED').first())
        db.session.expire_all()
        self.assertEqual(self.truck.insurance_expiry_date, date(2027, 3, 20))

    def test_migration_preserves_legacy_truck_and_driver_on_upgrade_and_rollback(self):
        db.session.remove()
        db.drop_all()
        upgrade(directory=MIGRATIONS, revision='e7f8a9b0c1d2')
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO trucks (id, license_plate, inspection_date, is_active) VALUES (1, 'LEGACY', '2026-10-01', 1)"))
            connection.execute(text("INSERT INTO users (id, username, full_name, password_hash, role, current_truck_id) VALUES (1, 'legacy-driver', 'Legacy', 'unused', 'driver', 1)"))
        upgrade(directory=MIGRATIONS)
        truck = db.session.get(Truck, 1)
        self.assertIsNone(truck.insurance_expiry_date)
        self.assertEqual(truck.inspection_date, date(2026, 10, 1))
        truck.insurance_expiry_date = date(2028, 2, 29)
        db.session.commit()
        db.session.expire_all()
        self.assertEqual(truck.insurance_expiry_date, date(2028, 2, 29))
        db.session.remove()
        downgrade(directory=MIGRATIONS, revision='e7f8a9b0c1d2')
        self.assertNotIn('insurance_expiry_date', {c['name'] for c in inspect(db.engine).get_columns('trucks')})
        with db.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT license_plate, inspection_date FROM trucks WHERE id=1')).one(), ('LEGACY', '2026-10-01'))
            self.assertEqual(connection.execute(text('SELECT current_truck_id FROM users WHERE id=1')).scalar_one(), 1)
        upgrade(directory=MIGRATIONS)
        config = Config()
        config.set_main_option('script_location', MIGRATIONS)
        self.assertEqual(ScriptDirectory.from_config(config).get_heads(), ['f8a9b0c1d2e3'])


if __name__ == '__main__':
    unittest.main()
