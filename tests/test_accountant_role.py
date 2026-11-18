"""Accountant permissions, manager ownership, and customer phone privacy."""
import json
import os
from datetime import date
import unittest

os.environ['FLASK_ENV'] = 'testing'

from flask import g
from app import create_app, db
from app.access import can_access_phoi, manager_id, trucks_query
from app.models import (ActivityLog, Customer, FuelLog, Phoi, PhoiReturnTrip,
                        Truck, User, adjust_manager_collection)


class AccountantRoleTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.admin = self.user('admin', 'admin')
        self.a = self.user('manager-a', 'manager')
        self.b = self.user('manager-b', 'manager')
        self.accountant = self.user('accountant-a', 'accountant', self.a.id)
        self.other = self.user('accountant-b', 'accountant', self.b.id)
        self.driver = self.user('driver-a', 'driver', self.a.id)
        self.foreign_driver = self.user('driver-b', 'driver', self.b.id)
        self.ta = Truck(license_plate='TRUCK-A', manager_id=self.a.id)
        self.tb = Truck(license_plate='TRUCK-B', manager_id=self.b.id)
        self.ca = Customer(name='CUSTOMER-A', contact_phone='0912345678', managers=[self.a])
        self.cb = Customer(name='CUSTOMER-B', contact_phone='0987654321', managers=[self.b])
        self.shared = Customer(name='SHARED', contact_phone='0909090909', managers=[self.a, self.b])
        db.session.add_all([self.ta, self.tb, self.ca, self.cb, self.shared])
        db.session.flush()
        self.driver.current_truck_id = self.ta.id
        self.foreign_driver.current_truck_id = self.tb.id
        self.pa = self.phoi('PHOI-A', self.ta, self.driver, self.ca)
        self.pb = self.phoi('PHOI-B', self.tb, self.foreign_driver, self.cb)
        self.ra = PhoiReturnTrip(phoi=self.pa, customer=self.shared, trip_order=1,
                                origin='Return', destination='End', payment_method='fixed',
                                revenue_full=200, revenue_collected=0, manager_revenue_collected=0)
        db.session.add(self.ra)
        for phoi, driver in ((self.pa, self.driver), (self.pb, self.foreign_driver)):
            fuel = FuelLog(truck_id=phoi.truck_id, liters=10, price_per_liter=20,
                           total_cost=200, paid_by='owner', refuel_date=date(2026, 11, 18),
                           created_by_id=driver.id)
            fuel.phois.append(phoi)
            db.session.add(fuel)
        db.session.commit()
        self.login(self.accountant)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def user(self, username, role, owner=None):
        user = User(username=username, full_name=username, role=role,
                    password_hash='unused', manager_id=owner)
        db.session.add(user)
        db.session.flush()
        return user

    def phoi(self, number, truck, driver, customer):
        phoi = Phoi(phoi_number=number, truck=truck, driver=driver, customer=customer,
                    departure_date=date(2026, 11, 18), origin='Start', destination='End',
                    km_start=0, km_end=100, payment_method='fixed', revenue_full=1000,
                    revenue_collected=0, manager_revenue_collected=0, driver_wage=50,
                    status='confirmed')
        db.session.add(phoi)
        db.session.flush()
        return phoi

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session.clear()
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    @staticmethod
    def account_form(username, **extra):
        return dict(username=username, full_name=username, password='password',
                    confirm_password='password', role='accountant', **extra)

    def test_accountant_inherits_manager_views_without_foreign_data(self):
        self.assertTrue(self.accountant.is_manager_or_admin())
        self.assertEqual(manager_id(self.accountant), self.a.id)
        self.assertTrue(can_access_phoi(self.accountant, self.pa))
        self.assertFalse(can_access_phoi(self.accountant, self.pb))
        for path in ('/trucks', '/drivers', '/customers', '/phoi?status=confirmed',
                     '/phoi/create', '/fuel', '/fuel/create', '/fuel/prices', '/debts',
                     '/reports?month=2026-11', '/activity-logs',
                     f'/phoi/{self.pa.id}', f'/phoi/{self.pa.id}/print'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                for hidden in (b'TRUCK-B', b'CUSTOMER-B', b'PHOI-B', b'driver-b'):
                    self.assertNotIn(hidden, response.data)
        self.assertEqual({c['id'] for c in self.client.get('/api/customers').get_json()},
                         {self.ca.id, self.shared.id})

    def test_foreign_objects_and_mutations_stay_denied(self):
        for path in (f'/trucks/{self.tb.id}/edit', f'/drivers/{self.foreign_driver.id}/edit',
                     f'/customers/{self.cb.id}/edit', f'/api/customers/{self.cb.id}',
                     f'/phoi/{self.pb.id}', f'/phoi/{self.pb.id}/print',
                     f'/phoi/{self.pb.id}/edit', f'/debts/customer/{self.cb.id}'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        for path in (f'/trucks/{self.tb.id}/delete', f'/customers/{self.cb.id}/delete',
                     f'/drivers/{self.foreign_driver.id}/delete', f'/phoi/{self.pb.id}/submit',
                     f'/phoi/{self.pb.id}/cancel', f'/phoi/{self.pb.id}/edit'):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 404)
        self.assertTrue(self.tb.is_active)
        self.assertEqual(self.pb.status, 'confirmed')
        self.assertEqual(self.client.get('/admin/management').status_code, 403)
        self.assertEqual(self.client.post('/admin/management').status_code, 403)

    def test_confirmation_is_hidden_and_direct_get_post_do_not_change_finances(self):
        self.pa.status = 'submitted'
        db.session.commit()
        before = (self.pa.driver_wage, self.pa.manager_revenue_collected,
                  self.pa.balance(), self.pa.owner_profit())
        self.assertFalse(self.accountant.can_confirm_phoi())
        for path in (f'/phoi/{self.pa.id}', f'/phoi/{self.pa.id}/edit'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('Xác nhận nhanh', response.get_data(as_text=True))
            self.assertNotIn(f'href="/phoi/{self.pa.id}/confirm"', response.get_data(as_text=True))
        for target in (self.pa, self.pb):
            path = f'/phoi/{target.id}/confirm'
            self.assertEqual(self.client.get(path).status_code, 302)
            self.assertEqual(self.client.post(path, data={
                'outbound_collection_status': 'full', 'driver_wage': '999',
                'toll_fee_status': 'incurred', 'toll_fee_amount': '10',
            }).status_code, 302)
        db.session.refresh(self.pa)
        self.assertEqual(self.pa.status, 'submitted')
        self.assertIsNone(self.pa.confirmed_by_id)
        self.assertEqual(before, (self.pa.driver_wage, self.pa.manager_revenue_collected,
                                  self.pa.balance(), self.pa.owner_profit()))

    def test_manager_can_still_confirm_after_accountant_reconciliation(self):
        self.pa.status = 'draft'
        db.session.commit()
        self.assertEqual(self.client.post(f'/phoi/{self.pa.id}/edit', data={
            'truck_id': self.ta.id, 'customer_id': self.ca.id, 'origin': 'Edited',
            'destination': 'End', 'km_end': '100', 'revenue_full': '1000',
            'driver_wage': '50',
        }).status_code, 302)
        self.assertEqual(self.pa.origin, 'Edited')
        self.assertEqual(self.client.post(f'/phoi/{self.pa.id}/submit').status_code, 302)
        self.assertEqual(self.pa.status, 'submitted')
        self.login(self.a)
        self.assertIn(f'href="/phoi/{self.pa.id}/confirm"',
                      self.client.get(f'/phoi/{self.pa.id}').get_data(as_text=True))
        self.assertEqual(self.client.post(f'/phoi/{self.pa.id}/confirm', data={
            'outbound_collection_status': 'unpaid', 'driver_wage': '50',
            'toll_fee_status': 'incurred', 'toll_fee_amount': '10',
        }).status_code, 302)
        self.assertEqual(self.pa.status, 'confirmed')
        self.assertEqual(self.pa.confirmed_by_id, self.a.id)

    def test_customer_phones_absent_from_html_apis_and_logs(self):
        log = ActivityLog(user_id=self.a.id, username=self.a.username, action='UPDATE',
                          resource_type='customers', resource_id=str(self.ca.id),
                          scope_manager_id=self.a.id,
                          details=json.dumps({'contact_phone': self.ca.contact_phone, 'name': 'Allowed-name'}))
        malformed = ActivityLog(user_id=self.a.id, action='UPDATE', resource_type='customers',
                                resource_id=str(self.ca.id), scope_manager_id=self.a.id,
                                details=f'Legacy phone {self.ca.contact_phone}')
        db.session.add_all([log, malformed])
        db.session.commit()
        for path in ('/customers', '/customers/create', f'/customers/{self.ca.id}/edit',
                     '/api/customers', f'/api/customers/{self.ca.id}', '/debts',
                     f'/debts/customer/{self.ca.id}', f'/debts/customer/{self.shared.id}',
                     '/activity-logs'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                for phone in (self.ca.contact_phone, self.cb.contact_phone, self.shared.contact_phone):
                    self.assertNotIn(phone, response.get_data(as_text=True))
                self.assertNotIn('name="contact_phone"', response.get_data(as_text=True))
        self.assertIn('Allowed-name', self.client.get('/activity-logs').get_data(as_text=True))
        db.session.refresh(log)
        self.assertIn(self.ca.contact_phone, log.details)
        for actor in (self.a, self.admin):
            self.login(actor)
            for path in ('/customers', f'/customers/{self.ca.id}/edit', '/debts',
                         f'/debts/customer/{self.ca.id}'):
                self.assertIn(self.ca.contact_phone, self.client.get(path).get_data(as_text=True))

    def test_customer_edit_preserves_phone_even_when_forged(self):
        for data in ({'name': 'Updated'}, {'name': 'Updated', 'contact_phone': '0000000000'}):
            self.assertEqual(self.client.post(f'/customers/{self.ca.id}/edit', data=data).status_code, 302)
            db.session.refresh(self.ca)
            self.assertEqual(self.ca.contact_phone, '0912345678')
            self.assertEqual(self.ca.name, 'Updated')

    def test_created_resources_belong_to_parent_and_cannot_inject_owner(self):
        self.assertEqual(self.client.post('/trucks/create', data={
            'license_plate': 'NEW-TRUCK', 'manager_id': self.b.id,
        }).status_code, 302)
        self.assertEqual(Truck.query.filter_by(license_plate='NEW-TRUCK').one().manager_id, self.a.id)
        self.assertEqual(self.client.post('/customers/create', data={
            'name': 'NEW-CUSTOMER', 'contact_phone': '0000000000', 'manager_ids': self.b.id,
        }).status_code, 302)
        customer = Customer.query.filter_by(name='NEW-CUSTOMER').one()
        self.assertEqual([manager.id for manager in customer.managers], [self.a.id])
        self.assertEqual(customer.contact_phone, '')
        data = self.account_form('new-driver', manager_id=self.b.id)
        data['role'] = 'admin'
        self.assertEqual(self.client.post('/drivers/create', data=data).status_code, 302)
        user = User.query.filter_by(username='new-driver').one()
        self.assertEqual((user.role, user.manager_id), ('driver', self.a.id))

    def test_accountant_can_collect_and_adjust_owned_debt(self):
        balance = self.pa.balance()
        self.assertEqual(self.client.post(f'/debts/customer/{self.ca.id}/collect',
                                         data={'amount': '100'}).status_code, 302)
        self.assertEqual(self.pa.manager_revenue_collected, 100)
        adjust_manager_collection(self.pa, '150', '100', 'Đối soát', self.accountant)
        db.session.commit()
        self.assertEqual(self.pa.manager_revenue_collected, 150)
        self.assertEqual(self.pa.balance(), balance)
        with self.assertRaises(ValueError):
            adjust_manager_collection(self.pb, '150', '0', 'Sai phạm vi', self.accountant)
        self.assertEqual(self.pb.manager_revenue_collected, 0)

    def test_customer_delete_has_same_sharing_guards_as_parent(self):
        self.assertEqual(self.client.post(f'/customers/{self.shared.id}/delete').status_code, 403)
        self.assertTrue(self.shared.is_active)
        self.assertEqual(self.client.post(f'/customers/{self.ca.id}/delete').status_code, 302)
        self.assertFalse(self.ca.is_active)

    def test_accountant_creates_scoped_phoi_and_cannot_choose_foreign_resources(self):
        before = Phoi.query.count()
        data = {'truck_id': self.ta.id, 'customer_id': self.cb.id,
                'origin': 'New trip', 'destination': 'End'}
        self.client.post('/phoi/create', data=data)
        self.assertEqual(Phoi.query.count(), before)
        data.update(truck_id=self.tb.id, customer_id=self.ca.id)
        self.client.post('/phoi/create', data=data)
        self.assertEqual(Phoi.query.count(), before)
        data['truck_id'] = self.ta.id
        self.assertEqual(self.client.post('/phoi/create', data=data).status_code, 302)
        created = Phoi.query.filter_by(origin='New trip').one()
        self.assertEqual((created.driver_id, created.truck_id, created.customer_id, created.created_by_id),
                         (self.driver.id, self.ta.id, self.ca.id, self.accountant.id))

    def test_accountant_fuel_permissions_match_parent_for_draft_and_confirmed(self):
        fuel = self.pa.fuel_logs[0]
        foreign = self.pb.fuel_logs[0]
        self.assertEqual(self.client.get(f'/fuel/{foreign.id}/edit').status_code, 404)
        self.assertEqual(self.client.post(f'/fuel/{foreign.id}/delete').status_code, 404)
        self.client.post(f'/fuel/{fuel.id}/delete')
        self.assertIsNotNone(db.session.get(FuelLog, fuel.id))
        self.pa.status = 'draft'
        db.session.commit()
        self.assertEqual(self.client.get(f'/fuel/{fuel.id}/edit').status_code, 200)
        self.assertEqual(self.client.post(f'/fuel/{fuel.id}/delete').status_code, 302)
        self.assertIsNone(db.session.get(FuelLog, fuel.id))
        self.assertEqual(self.client.post(f'/phoi/{self.pa.id}/submit').status_code, 302)
        self.assertEqual(self.pa.status, 'draft')  # The fuel requirement still applies.

    def test_parent_can_create_edit_and_deactivate_own_accountant(self):
        self.login(self.a)
        self.assertIn('value="accountant"', self.client.get('/drivers/create').get_data(as_text=True))
        data = self.account_form('new-accountant', manager_id=self.b.id, current_truck_id=self.ta.id)
        self.assertEqual(self.client.post('/drivers/create', data=data).status_code, 302)
        user = User.query.filter_by(username='new-accountant').one()
        self.assertEqual((user.role, user.manager_id, user.current_truck_id), ('accountant', self.a.id, None))
        listing = self.client.get('/drivers').get_data(as_text=True)
        self.assertIn('new-accountant', listing)
        self.assertNotIn('accountant-b', listing)
        self.assertEqual(self.client.get(f'/drivers/{user.id}/edit').status_code, 200)
        self.assertEqual(self.client.post(f'/drivers/{user.id}/edit', data={
            'full_name': 'Updated accountant', 'role': 'admin', 'manager_id': self.b.id,
            'password': 'updated-password', 'confirm_password': 'updated-password',
        }).status_code, 302)
        self.assertEqual((user.role, user.manager_id), ('accountant', self.a.id))
        self.assertTrue(user.check_password('updated-password'))
        self.assertEqual(self.client.post(f'/drivers/{user.id}/delete').status_code, 302)
        self.assertFalse(user.is_active)
        self.assertEqual(self.client.get(f'/drivers/{self.other.id}/edit').status_code, 404)
        self.assertEqual(self.client.post(f'/drivers/{self.other.id}/delete').status_code, 404)

    def test_accountant_cannot_manage_self_peers_or_superiors(self):
        for user in (self.accountant, self.other, self.a, self.b, self.admin):
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(f'/drivers/{user.id}/edit').status_code, 404)
                self.assertEqual(self.client.post(f'/drivers/{user.id}/edit', data={'role': 'admin'}).status_code, 404)
                self.assertEqual(self.client.post(f'/drivers/{user.id}/delete').status_code, 404)
        self.assertNotIn('value="accountant"', self.client.get('/drivers/create').get_data(as_text=True))
        self.assertEqual(self.client.post('/drivers/create', data=self.account_form('forged')).status_code, 302)
        self.assertEqual(User.query.filter_by(username='forged').one().role, 'driver')

    def test_admin_selects_active_parent_and_can_transfer_accountant(self):
        self.login(self.admin)
        page = self.client.get('/drivers/create').get_data(as_text=True)
        self.assertIn('value="accountant"', page)
        self.assertIn('name="manager_id"', page)
        self.assertEqual(self.client.post('/drivers/create', data=self.account_form(
            'admin-created', manager_id=self.b.id)).status_code, 302)
        user = User.query.filter_by(username='admin-created').one()
        self.assertEqual((user.role, user.manager_id, user.current_truck_id), ('accountant', self.b.id, None))
        self.assertEqual(self.client.post(f'/drivers/{user.id}/edit', data={
            'full_name': user.full_name, 'role': 'accountant', 'manager_id': self.a.id,
        }).status_code, 302)
        self.assertEqual(user.manager_id, self.a.id)
        self.login(user)
        self.assertEqual(self.client.get(f'/phoi/{self.pa.id}').status_code, 200)
        self.assertEqual(self.client.get(f'/phoi/{self.pb.id}').status_code, 404)

    def test_invalid_parent_rolls_back_account_create_and_edit(self):
        self.login(self.admin)
        inactive = self.user('inactive-manager', 'manager')
        inactive.is_active = False
        db.session.commit()
        for owner in ('', 'bad', '999999', self.driver.id, self.accountant.id, inactive.id):
            with self.subTest(owner=owner):
                self.assertEqual(self.client.post('/drivers/create', data=self.account_form(
                    'invalid-parent', manager_id=owner)).status_code, 400)
                self.assertIsNone(User.query.filter_by(username='invalid-parent').first())
                self.assertEqual(self.client.post(f'/drivers/{self.accountant.id}/edit', data={
                    'full_name': 'Should roll back', 'role': 'accountant', 'manager_id': owner,
                }).status_code, 400)
                db.session.refresh(self.accountant)
                self.assertEqual((self.accountant.full_name, self.accountant.manager_id),
                                 ('accountant-a', self.a.id))

    def test_csrf_protects_accountant_creation(self):
        self.login(self.a)
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post('/drivers/create', data=self.account_form('no-csrf')).status_code, 400)
        self.assertIsNone(User.query.filter_by(username='no-csrf').first())

    def test_parent_assignment_follows_current_truck_ownership(self):
        self.ta.manager_id = self.b.id
        self.driver.manager_id = self.b.id
        db.session.commit()
        self.assertFalse(can_access_phoi(self.accountant, self.pa))
        self.assertEqual(self.client.get(f'/phoi/{self.pa.id}').status_code, 404)
        self.login(self.other)
        self.assertEqual(self.client.get(f'/phoi/{self.pa.id}').status_code, 200)

    def test_parent_missing_inactive_or_invalid_denies_existing_session(self):
        parent_id = self.a.id
        accountant_id = self.accountant.id
        for owner in (None, self.driver.id, accountant_id, parent_id):
            with self.subTest(owner=owner):
                # Core SQL also covers malformed self-parent rows without ORM cycles.
                db.session.execute(db.update(User).where(User.id == accountant_id).values(manager_id=owner))
                if owner == parent_id:
                    self.a.is_active = False
                db.session.commit()
                db.session.expire_all()
                self.assertIsNone(manager_id(self.accountant))
                self.assertFalse(can_access_phoi(self.accountant, self.pa))
                self.assertEqual(trucks_query(self.accountant).count(), 0)
                self.login(self.accountant)
                self.assertEqual(self.client.get('/customers').status_code, 403)

    def test_report_filter_and_activity_log_scope_use_parent(self):
        self.assertEqual(self.client.get(f'/reports?manager_id={self.a.id}').status_code, 200)
        for identity in (self.b.id, self.accountant.id, 'unassigned'):
            self.assertEqual(self.client.get(f'/reports?manager_id={identity}').status_code, 403)
        self.client.post(f'/customers/{self.ca.id}/edit', data={'name': 'Updated'})
        log = ActivityLog.query.filter_by(user_id=self.accountant.id, resource_type='customers').one()
        self.assertEqual(log.scope_manager_id, self.a.id)
        self.login(self.a)
        self.assertIn('accountant-a', self.client.get('/activity-logs').get_data(as_text=True))
        self.login(self.b)
        self.assertNotIn('accountant-a', self.client.get('/activity-logs').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
