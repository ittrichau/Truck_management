"""Other expenses belong to one trip and enter driver settlement exactly once."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import g
from flask_migrate import upgrade, downgrade
from sqlalchemy import inspect, text

from app import create_app, db
from app.models import Phoi, PhoiExpense, PhoiReturnTrip, Truck, User
from config import TestingConfig


MIGRATIONS = str(Path(__file__).resolve().parents[1] / 'migrations')


class OtherExpenseTests(unittest.TestCase):
    def setUp(self):
        with patch('app.get_config', return_value=TestingConfig):
            self.app = create_app('testing')
        self.app.config.update(SECRET_KEY='other-expense-tests', RATELIMIT_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        self.assertEqual(str(db.engine.url), 'sqlite:///:memory:')
        db.create_all()
        self.driver = User(username='driver', full_name='Driver', password_hash='unused', role='driver')
        self.manager = User(username='manager', full_name='Manager', password_hash='unused', role='manager')
        self.truck = Truck(license_plate='OTHER-001')
        db.session.add_all([self.driver, self.manager, self.truck])
        db.session.flush()
        self.driver.current_truck_id = self.truck.id
        db.session.commit()
        self.client = self.app.test_client()
        self.login(self.driver)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def form(self, count=2):
        return {
            'truck_id': str(self.truck.id), 'departure_date': '2026-11-09',
            'origin': 'A', 'destination': 'B', 'revenue_full': '1000000',
            'driver_wage': '200000', 'has_other': '1', 'expense_other': '50000',
            'expense_other_description': 'Vá lốp chuyến đi',
            'return_trip_id[]': [''] * count,
            'return_trip_origin[]': ['B'] * count,
            'return_trip_destination[]': ['A'] * count,
            'return_trip_revenue_full[]': ['2000000'] * count,
            'return_trip_has_other[]': ['1'] * count,
            'return_trip_expense_other[]': ['30000'] * count,
            'return_trip_expense_other_description[]': [f'Phí kho chuyến về {n + 1}' for n in range(count)],
        }

    def create(self, data=None):
        response = self.client.post('/phoi/create', data=data or self.form())
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[-1500:])
        db.session.expire_all()
        return Phoi.query.one()

    def edit_form(self, phoi):
        trips = phoi.return_trips.all()
        data = self.form(len(trips))
        data['return_trip_id[]'] = [str(trip.id) for trip in trips]
        return data

    def test_create_links_and_counts_each_cost_once(self):
        phoi = self.create()
        self.assertEqual(PhoiExpense.query.count(), 3)
        self.assertEqual(phoi.expenses.filter_by(return_trip_id=None).one().amount, Decimal('50000'))
        for trip in phoi.return_trips.all():
            self.assertEqual(trip.expenses.one().phoi_id, phoi.id)
            self.assertEqual(trip.expenses.one().amount, Decimal('30000'))
        self.assertEqual(phoi.total_expenses(), Decimal('110000'))
        self.assertEqual(phoi.driver_out_of_pocket_expenses(), Decimal('110000'))
        self.assertEqual(phoi.balance(), Decimal('310000'))
        self.assertEqual(phoi.owner_profit(), Decimal('4690000'))

    def test_unchecked_does_not_require_or_save_amount_and_description(self):
        data = self.form()
        data.update(has_other='0', expense_other='', expense_other_description='')
        data['return_trip_has_other[]'] = ['0', '1']
        data['return_trip_expense_other[]'] = ['', '30000']
        data['return_trip_expense_other_description[]'] = ['', 'Phí kho']
        phoi = self.create(data)
        self.assertEqual(phoi.expenses.count(), 1)
        self.assertEqual(phoi.return_trips.all()[1].expenses.one().description, 'Phí kho')

    def test_missing_invalid_amount_or_content_rolls_back_entire_create(self):
        for scope in ('outbound', 'return'):
            for amount, description in (
                ('', 'Phí'), ('0', 'Phí'), ('-1', 'Phí'), ('NaN', 'Phí'),
                ('Infinity', 'Phí'), ('1.5', 'Phí'), ('10000000000', 'Phí'),
                ('1000', ''), ('1000', '   '), ('1000', 'x' * 201),
            ):
                with self.subTest(scope=scope, amount=amount, description=description[:15]):
                    data = self.form()
                    if scope == 'outbound':
                        data.update(expense_other=amount, expense_other_description=description)
                    else:
                        data['return_trip_expense_other[]'][1] = amount
                        data['return_trip_expense_other_description[]'][1] = description
                    response = self.client.post('/phoi/create', data=data)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('Chi phí khác', response.get_data(as_text=True))
                    self.assertEqual(Phoi.query.count(), 0)
                    self.assertEqual(PhoiReturnTrip.query.count(), 0)
                    self.assertEqual(PhoiExpense.query.count(), 0)

    def test_array_alignment_is_validated_without_javascript(self):
        data = self.form()
        data['return_trip_expense_other_description[]'] = ['One only']
        self.assertEqual(self.client.post('/phoi/create', data=data).status_code, 200)
        self.assertEqual(Phoi.query.count(), 0)

    def test_positive_amount_cannot_bypass_content_requirement_by_omitting_checkbox(self):
        data = self.form()
        data.pop('has_other')
        data.pop('expense_other_description')
        self.assertEqual(self.client.post('/phoi/create', data=data).status_code, 200)
        self.assertEqual(Phoi.query.count(), 0)

    def test_edit_resubmit_reorder_uncheck_and_delete_keep_associations(self):
        phoi = self.create()
        trips = phoi.return_trips.all()
        expense_ids = [trip.expenses.one().id for trip in trips]
        data = self.edit_form(phoi)
        data['return_trip_id[]'].reverse()
        data['return_trip_expense_other[]'] = ['70000', '90000']
        data['return_trip_expense_other_description[]'] = ['Second now first', 'First now second']
        for _ in range(2):
            self.assertEqual(self.client.post(f'/phoi/{phoi.id}/edit', data=data).status_code, 302)
            db.session.expire_all()
            self.assertEqual(phoi.total_expenses(), Decimal('210000'))
            self.assertEqual(PhoiExpense.query.count(), 3)
            self.assertEqual(db.session.get(PhoiExpense, expense_ids[1]).description, 'Second now first')
        data = self.edit_form(phoi)
        data['has_other'] = '0'
        data['return_trip_has_other[]'] = ['0', '1']
        self.assertEqual(self.client.post(f'/phoi/{phoi.id}/edit', data=data).status_code, 302)
        db.session.expire_all()
        self.assertEqual(phoi.total_expenses(), Decimal('30000'))
        data = self.edit_form(phoi)
        for key in list(data):
            if key.startswith('return_trip_'):
                data[key] = data[key][:1]
        data['has_other'] = '0'
        data['return_trip_has_other[]'] = ['0']
        self.assertEqual(self.client.post(f'/phoi/{phoi.id}/edit', data=data).status_code, 302)
        db.session.expire_all()
        self.assertEqual(PhoiExpense.query.count(), 0)

    def test_invalid_edit_does_not_partially_change_costs(self):
        phoi = self.create()
        data = self.edit_form(phoi)
        data['return_trip_expense_other_description[]'][1] = ' '
        data['expense_other'] = '900000'
        self.assertEqual(self.client.post(f'/phoi/{phoi.id}/edit', data=data).status_code, 200)
        db.session.expire_all()
        self.assertEqual(phoi.total_expenses(), Decimal('110000'))

    def test_foreign_and_duplicate_trip_ids_are_rejected(self):
        phoi = self.create()
        for ids in (['999999', ''], [str(phoi.return_trips.first().id)] * 2):
            data = self.edit_form(phoi)
            data['return_trip_id[]'] = ids
            self.assertEqual(self.client.post(f'/phoi/{phoi.id}/edit', data=data).status_code, 200)
            db.session.expire_all()
            self.assertEqual(phoi.total_expenses(), Decimal('110000'))

    def test_legacy_client_without_other_fields_keeps_existing_costs(self):
        phoi = self.create()
        data = self.edit_form(phoi)
        for key in list(data):
            if 'other' in key:
                data.pop(key)
        self.assertEqual(self.client.post(f'/phoi/{phoi.id}/edit', data=data).status_code, 302)
        db.session.expire_all()
        self.assertEqual(phoi.total_expenses(), Decimal('110000'))

    def test_edit_detail_print_show_descriptions_for_driver_and_manager(self):
        data = self.form()
        data['expense_other_description'] = 'OUTBOUND <script>alert(1)</script>'
        data['return_trip_expense_other_description[]'] = ['RETURN_ONE', 'RETURN_TWO']
        phoi = self.create(data)
        for user in (self.driver, self.manager):
            self.login(user)
            for suffix in ('', '/edit', '/print'):
                with self.subTest(role=user.role, suffix=suffix):
                    response = self.client.get(f'/phoi/{phoi.id}{suffix}')
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    for marker in ('OUTBOUND', 'RETURN_ONE', 'RETURN_TWO'):
                        self.assertIn(marker, html)
                    self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
                    if suffix == '/print':
                        self.assertEqual(html.count('OUTBOUND'), 1)
                        self.assertEqual(html.count('RETURN_ONE'), 1)
                        if user.is_driver():
                            self.assertNotIn('finance-section">', html)
                            self.assertNotIn('owner-profit">', html)

    def test_confirmed_edit_permissions_are_unchanged(self):
        phoi = self.create()
        phoi.status = 'confirmed'
        db.session.commit()
        for user in (self.driver, self.manager):
            self.login(user)
            data = self.edit_form(phoi)
            data['expense_other'] = '900000'
            self.assertEqual(self.client.post(f'/phoi/{phoi.id}/edit', data=data).status_code, 302)
            db.session.expire_all()
            self.assertEqual(phoi.total_expenses(), Decimal('110000'))

    def test_migration_preserves_legacy_values_and_guards_downgrade(self):
        phoi = self.create()
        phoi_id = phoi.id
        db.session.remove()
        db.drop_all()
        upgrade(directory=MIGRATIONS, revision='d5e6f7a8b9c0')
        # Raw SQL represents records written before the new ORM column existed.
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, full_name, password_hash, role) VALUES (1, 'legacy', 'Legacy', 'unused', 'driver')"))
            connection.execute(text("INSERT INTO trucks (id, license_plate) VALUES (1, 'LEGACY')"))
            connection.execute(text("INSERT INTO phoi (id, phoi_number, driver_id, truck_id, departure_date, origin, destination) VALUES (:id, 'LEGACY', 1, 1, '2026-11-09', 'A', 'B')"), {'id': phoi_id})
            connection.execute(text("INSERT INTO phoi_expenses (phoi_id, category, amount, description) VALUES (:id, 'other', 50000, 'Legacy cost')"), {'id': phoi_id})
        upgrade(directory=MIGRATIONS)
        expense = PhoiExpense.query.one()
        self.assertEqual(expense.amount, Decimal('50000'))
        self.assertEqual(expense.description, 'Legacy cost')
        self.assertIsNone(expense.return_trip_id)
        self.assertIn('return_trip_id', {c['name'] for c in inspect(db.engine).get_columns('phoi_expenses')})
        db.session.remove()
        downgrade(directory=MIGRATIONS, revision='d5e6f7a8b9c0')
        upgrade(directory=MIGRATIONS)
        trip = PhoiReturnTrip(phoi_id=phoi_id, trip_order=1, origin='B', destination='A')
        db.session.add(trip)
        db.session.flush()
        PhoiExpense.query.one().return_trip = trip
        db.session.commit()
        db.session.remove()
        with self.assertRaises(SystemExit):
            downgrade(directory=MIGRATIONS, revision='d5e6f7a8b9c0')
        self.assertIsNotNone(PhoiExpense.query.one().return_trip_id)


if __name__ == '__main__':
    unittest.main()
