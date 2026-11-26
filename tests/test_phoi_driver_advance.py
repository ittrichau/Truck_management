"""Driver declarations survive submission and are reviewed by a scoped manager."""
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
import unittest
from unittest.mock import patch

from flask import g
from werkzeug.datastructures import MultiDict

from app import create_app, db
from app.models import FuelLog, Phoi, Truck, User
from config import TestingConfig


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input':
            self.inputs[attrs.get('id') or attrs.get('name')] = attrs


class DriverAdvanceTests(unittest.TestCase):
    def setUp(self):
        with patch('app.get_config', return_value=TestingConfig):
            self.app = create_app('testing')
        self.app.config.update(SECRET_KEY='driver-advance-tests', RATELIMIT_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        self.assertEqual(str(db.engine.url), 'sqlite:///:memory:')
        db.create_all()
        self.manager = User(username='manager', full_name='Manager', role='manager', password_hash='unused')
        self.driver = User(username='driver', full_name='Driver', role='driver', password_hash='unused')
        self.other = User(username='other', full_name='Other', role='driver', password_hash='unused')
        self.admin = User(username='admin', full_name='Admin', role='admin', password_hash='unused')
        self.accountant = User(username='accountant', full_name='Accountant', role='accountant', password_hash='unused')
        self.outsider = User(username='outsider', full_name='Outsider', role='manager', password_hash='unused')
        self.truck = Truck(license_plate='ADVANCE-001')
        db.session.add_all([self.manager, self.driver, self.other, self.admin,
                            self.accountant, self.outsider, self.truck])
        db.session.flush()
        self.truck.manager_id = self.manager.id
        self.driver.manager_id = self.other.manager_id = self.accountant.manager_id = self.manager.id
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

    def form(self, **values):
        data = dict(truck_id=str(self.truck.id), origin='A', destination='B',
                    departure_date='2026-11-26', km_end='650', payment_method='fixed',
                    revenue_full='3600000', revenue_collected='500000', driver_wage='450000')
        data.update(values)
        return data

    def create(self, **values):
        response = self.client.post('/phoi/create', data=self.form(**values))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[-1500:])
        db.session.expire_all()
        return Phoi.query.order_by(Phoi.id.desc()).first()

    def fuel(self, phoi):
        fuel = FuelLog(truck_id=self.truck.id, refuel_date=date(2026, 11, 26),
                       liters=Decimal('10'), price_per_liter=20000,
                       total_cost=Decimal('200000'), paid_by='driver')
        fuel.phois.append(phoi)
        db.session.add(fuel)
        db.session.commit()

    def confirmation(self, **values):
        data = dict(outbound_collection_status='unpaid', driver_wage='450000',
                    toll_fee_status='incurred', toll_fee_amount='350000')
        data.update(values)
        return data

    def test_driver_and_existing_staff_roles_can_declare_on_create(self):
        for user in (self.driver, self.manager, self.accountant, self.admin):
            with self.subTest(role=user.role):
                self.login(user)
                # A real checkbox submits both the hidden 0 and the checked 1.
                data = MultiDict(self.form(driver_advance='1,200,000.25'))
                data.setlist('has_driver_advance', ['0', '1'])
                self.assertEqual(self.client.post('/phoi/create', data=data).status_code, 302)
                phoi = Phoi.query.order_by(Phoi.id.desc()).first()
                self.assertEqual(phoi.driver_advance, Decimal('1200000.25'))
                self.assertEqual(phoi.total_expenses(), 0)
                self.assertEqual(phoi.balance(), Decimal('-50000'))
                self.assertEqual(phoi.settlement_balance(), Decimal('-1250000.25'))
                self.assertEqual(phoi.owner_profit(), Decimal('3150000'))
                phoi.status = 'cancelled'
                db.session.commit()

    def test_unchecked_or_legacy_create_defaults_to_zero(self):
        for values in ({}, {'has_driver_advance': '0', 'driver_advance': 'bad'},
                       {'driver_advance': '900000'}):
            with self.subTest(values=values):
                phoi = self.create(**values)
                self.assertEqual(phoi.driver_advance, 0)
                phoi.status = 'cancelled'
                db.session.commit()

    def test_invalid_declaration_rolls_back_create_and_preserves_entered_form(self):
        for amount in ('', '0', '-1', 'abc', 'NaN', 'Infinity', '1e6', '12,34', '1.001', '10000000000'):
            with self.subTest(amount=amount):
                response = self.client.post('/phoi/create', data=self.form(
                    has_driver_advance='1', driver_advance=amount))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(Phoi.query.count(), 0)
                db.session.refresh(self.truck)
                self.assertEqual(self.truck.status, 'available')
                inputs = Inputs(response.get_data(as_text=True)).inputs
                self.assertIn('checked', inputs['has-driver-advance'])
                self.assertEqual(inputs['driver-advance']['value'], amount)

    def test_driver_can_edit_and_explicitly_clear_advance(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000')
        for flag, amount, expected in (('1', '350,000', '350000'), ('0', 'garbage', '0'),
                                        ('1', '500000', '500000')):
            response = self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(
                has_driver_advance=flag, driver_advance=amount))
            self.assertEqual(response.status_code, 302)
            db.session.refresh(phoi)
            self.assertEqual(phoi.driver_advance, Decimal(expected))

    def test_old_edit_forms_keep_saved_advance(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000.25')
        for status, user in (('draft', self.driver), ('submitted', self.manager)):
            with self.subTest(status=status):
                phoi.status = status
                db.session.commit()
                self.login(user)
                self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(driver_advance='900000'))
                db.session.refresh(phoi)
                self.assertEqual(phoi.driver_advance, Decimal('200000.25'))

    def test_invalid_edit_rolls_back_other_financial_fields(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000')
        for amount in ('', '0', '-1', 'NaN', '12,34', '1.001', '10000000000'):
            with self.subTest(amount=amount):
                response = self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(
                    has_driver_advance='1', driver_advance=amount, driver_wage='800000', revenue_full='9000000'))
                self.assertEqual(response.status_code, 200)
                db.session.refresh(phoi)
                self.assertEqual(phoi.driver_advance, Decimal('200000'))
                self.assertEqual(phoi.driver_wage, Decimal('450000'))
                self.assertEqual(phoi.revenue_full, Decimal('3600000'))

    def test_form_defaults_and_saved_fractional_advance_are_preserved(self):
        inputs = Inputs(self.client.get('/phoi/create').get_data(as_text=True)).inputs
        self.assertNotIn('checked', inputs['has-driver-advance'])
        phoi = self.create(has_driver_advance='1', driver_advance='200000.25')
        inputs = Inputs(self.client.get(f'/phoi/{phoi.id}/edit').get_data(as_text=True)).inputs
        self.assertIn('checked', inputs['has-driver-advance'])
        self.assertEqual(inputs['driver-advance']['value'], '200,000.25')
        self.assertIn('data-decimal-money', inputs['driver-advance'])

    def test_submit_keeps_declaration_and_fuel_requirement(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000')
        self.client.post(f'/phoi/{phoi.id}/submit')
        db.session.refresh(phoi)
        self.assertEqual(phoi.status, 'draft')
        self.fuel(phoi)
        self.client.post(f'/phoi/{phoi.id}/submit', data={'driver_advance': '999999'})
        db.session.refresh(phoi)
        self.assertEqual(phoi.status, 'submitted')
        self.assertEqual(phoi.driver_advance, Decimal('200000'))

    def test_manager_reviews_and_corrects_advance_then_settles_once(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000.25')
        self.fuel(phoi)
        self.client.post(f'/phoi/{phoi.id}/submit')
        self.login(self.manager)
        html = self.client.get(f'/phoi/{phoi.id}/confirm').get_data(as_text=True)
        self.assertIn('Kiểm tra lại tiền ứng đã khai', html)
        self.assertEqual(Inputs(html).inputs['driver-advance']['value'], '200,000.25')
        self.client.post(f'/phoi/{phoi.id}/confirm', data=self.confirmation(driver_advance='300000.25'))
        db.session.refresh(phoi)
        self.assertEqual(phoi.status, 'confirmed')
        self.assertEqual(phoi.driver_advance, Decimal('300000.25'))
        self.assertEqual(phoi.balance(), Decimal('150000'))
        self.assertEqual(phoi.settlement_balance(), Decimal('-150000.25'))
        self.assertEqual(phoi.total_expenses(), Decimal('550000'))
        self.assertEqual(phoi.owner_profit(), Decimal('2600000'))
        self.assertIn('300,000 VNĐ', self.client.get(f'/phoi/{phoi.id}').get_data(as_text=True))
        self.assertIn('Quản lý đã ứng (trừ khi quyết toán): 300,000 VNĐ',
                      self.client.get(f'/phoi/{phoi.id}/print').get_data(as_text=True))

    def test_confirmation_can_retain_or_clear_declared_advance(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000')
        self.fuel(phoi)
        self.login(self.manager)
        for values, expected in (({}, '200000'), ({'driver_advance': '0'}, '0')):
            phoi.status = 'submitted'
            db.session.commit()
            self.client.post(f'/phoi/{phoi.id}/confirm', data=self.confirmation(**values))
            db.session.refresh(phoi)
            self.assertEqual(phoi.status, 'confirmed')
            self.assertEqual(phoi.driver_advance, Decimal(expected))

    def test_driver_loses_edit_right_after_submit_and_cannot_confirm(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000')
        for status in ('submitted', 'confirmed', 'cancelled'):
            with self.subTest(status=status):
                phoi.status = status
                db.session.commit()
                response = self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(
                    has_driver_advance='1', driver_advance='900000'))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.client.post(f'/phoi/{phoi.id}/confirm',
                                                data=self.confirmation(driver_advance='900000')).status_code, 302)
                db.session.refresh(phoi)
                self.assertEqual(phoi.driver_advance, Decimal('200000'))

    def test_other_driver_and_outside_manager_cannot_change_declaration(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000')
        for user in (self.other, self.outsider):
            self.login(user)
            for path in ('edit', 'confirm'):
                response = self.client.post(f'/phoi/{phoi.id}/{path}', data=self.form(
                    has_driver_advance='1', driver_advance='900000'))
                self.assertIn(response.status_code, (302, 404))
            db.session.refresh(phoi)
            self.assertEqual(phoi.driver_advance, Decimal('200000'))

    def test_admin_confirmed_edit_preserves_final_advance(self):
        phoi = self.create(has_driver_advance='1', driver_advance='200000')
        phoi.status = 'confirmed'
        db.session.commit()
        self.login(self.admin)
        html = self.client.get(f'/phoi/{phoi.id}/edit').get_data(as_text=True)
        self.assertNotIn('id="has-driver-advance"', html)
        self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(
            has_driver_advance='0', driver_advance='0'))
        db.session.refresh(phoi)
        self.assertEqual(phoi.driver_advance, Decimal('200000'))

    def test_declaration_form_still_requires_csrf(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        data = self.form(has_driver_advance='1', driver_advance='200000')
        self.assertEqual(self.client.post('/phoi/create', data=data).status_code, 400)
        self.assertEqual(Phoi.query.count(), 0)
        html = self.client.get('/phoi/create').get_data(as_text=True)
        data['csrf_token'] = Inputs(html).inputs['csrf_token']['value']
        self.assertEqual(self.client.post('/phoi/create', data=data).status_code, 302)
        self.assertEqual(Phoi.query.one().driver_advance, Decimal('200000'))


if __name__ == '__main__':
    unittest.main()
