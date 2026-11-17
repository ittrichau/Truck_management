"""Authorization regressions using two managers and isolated SQLite data."""
import json
import os
from datetime import date
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ['FLASK_ENV'] = 'testing'
from flask import g, template_rendered
from PIL import Image
from werkzeug.datastructures import MultiDict
from sqlalchemy import event

from app import create_app, db
from app.models import (User, Truck, Customer, Phoi, PhoiReturnTrip, PhoiAttachment,
                        FuelLog, FuelReceipt, ActivityLog, adjust_manager_collection)
from app.access import trucks_query, customers_query, fuel_query


class ManagerScopeTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.files = TemporaryDirectory()
        self.app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False,
                               PHOI_ATTACHMENT_UPLOAD_FOLDER=self.files.name)
        self.context = self.app.app_context(); self.context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.admin = self.user('admin', 'admin')
        self.a = self.user('manager-a', 'manager')
        self.b = self.user('manager-b', 'manager')
        self.da = self.user('driver-a', 'driver', self.a.id)
        self.db = self.user('driver-b', 'driver', self.b.id)
        self.ta = Truck(license_plate='TRUCK-A', manager_id=self.a.id)
        self.tb = Truck(license_plate='TRUCK-B', manager_id=self.b.id)
        self.legacy = Truck(license_plate='UNASSIGNED')
        self.ca = Customer(name='CUSTOMER-A', managers=[self.a])
        self.cb = Customer(name='CUSTOMER-B', managers=[self.b])
        self.shared = Customer(name='SHARED', managers=[self.a, self.b])
        db.session.add_all([self.ta, self.tb, self.legacy, self.ca, self.cb, self.shared]); db.session.flush()
        self.da.current_truck_id = self.ta.id
        self.db.current_truck_id = self.tb.id
        self.pa = self.phoi('PHOI-A', self.ta, self.da, self.shared)
        self.pb = self.phoi('PHOI-B', self.tb, self.db, self.shared)
        self.ra = PhoiReturnTrip(phoi=self.pa, customer=self.shared, trip_order=1,
            origin='Return-A', destination='End', revenue_full=200, revenue_collected=0,
            manager_revenue_collected=0)
        self.rb = PhoiReturnTrip(phoi=self.pb, customer=self.shared, trip_order=1,
            origin='Return-B', destination='End', revenue_full=900, revenue_collected=0,
            manager_revenue_collected=0)
        self.fa = self.fuel(self.pa, self.da)
        self.fb = self.fuel(self.pb, self.db)
        db.session.add_all([self.ra, self.rb]); db.session.flush()
        self.ab = PhoiAttachment(phoi_id=self.pb.id, attachment_type='other',
            uploaded_by_id=self.db.id, **self.image_metadata('b.jpg'))
        self.receipt_b = FuelReceipt(fuel_log_id=self.fb.id, uploaded_by_id=self.db.id,
            **self.image_metadata('fuel-b.jpg'))
        db.session.add_all([self.ab, self.receipt_b]); db.session.commit()
        self.login(self.a)

    def tearDown(self):
        db.session.remove(); db.drop_all(); db.engine.dispose(); self.context.pop(); self.files.cleanup()

    def user(self, username, role, manager_id=None):
        user = User(username=username, full_name=username, role=role,
                    password_hash='unused', manager_id=manager_id)
        db.session.add(user); db.session.flush(); return user

    def phoi(self, number, truck, driver, customer, status='confirmed'):
        p = Phoi(phoi_number=number, truck=truck, driver=driver, customer=customer,
                 departure_date=date(2026, 11, 14), origin='Start', destination='End',
                 revenue_full=1000, revenue_collected=0, manager_revenue_collected=0,
                 driver_wage=50, status=status)
        db.session.add(p); db.session.flush(); return p

    def fuel(self, phoi, driver):
        log = FuelLog(truck_id=phoi.truck_id, liters=10, price_per_liter=20,
                      total_cost=200, paid_by='owner', refuel_date=date(2026, 11, 14),
                      created_by_id=driver.id)
        log.phois.append(phoi); db.session.add(log); db.session.flush(); return log

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as s:
            s.clear(); s['_user_id'] = str(user.id); s['_fresh'] = True

    def render_context(self, path):
        captured = []
        def capture(sender, template, context, **extra): captured.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.data[:500])
        return captured[-1], response

    @staticmethod
    def image_metadata(key):
        return dict(original_filename=key, storage_key=key, mime_type='image/jpeg',
                    file_size=1, width=1, height=1)

    def assignment(self, kind, obj, owner, expected=None):
        return self.client.post('/admin/management', data={
            'kind': kind, 'resource_id': obj.id, 'manager_id': owner.id if owner else '',
            'expected': str(obj.manager_id or '') if expected is None else expected})

    def test_lists_and_dropdowns_do_not_leak_other_manager(self):
        for path in ('/trucks', '/drivers', '/customers', '/phoi?status=confirmed',
                     '/phoi/create', '/fuel', '/fuel/create', '/debts'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                for hidden in (b'TRUCK-B', b'PHOI-B', b'CUSTOMER-B', b'driver-b', b'UNASSIGNED'):
                    self.assertNotIn(hidden, response.data)
        api = self.client.get('/api/customers').get_json()
        self.assertEqual({c['id'] for c in api}, {self.ca.id, self.shared.id})

    def test_foreign_object_gets_are_denied(self):
        urls = [f'/trucks/{self.tb.id}/edit', f'/drivers/{self.db.id}/edit',
                f'/customers/{self.cb.id}/edit', f'/api/customers/{self.cb.id}',
                f'/fuel/{self.fb.id}/edit', f'/fuel/{self.fb.id}/receipts/{self.receipt_b.id}',
                f'/phoi/{self.pb.id}', f'/phoi/{self.pb.id}/print',
                f'/phoi/{self.pb.id}/edit', f'/phoi/{self.pb.id}/confirm',
                f'/phoi/{self.pb.id}/attachments/{self.ab.id}',
                f'/debts/customer/{self.cb.id}',
                f'/debts/customer/{self.shared.id}/adjust/phoi/{self.pb.id}',
                f'/debts/customer/{self.shared.id}/adjust/return_trip/{self.rb.id}']
        for url in urls:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code, 404)

    def test_foreign_mutations_are_denied_without_side_effects(self):
        urls = [f'/trucks/{self.tb.id}/delete', f'/drivers/{self.db.id}/delete',
                f'/customers/{self.cb.id}/delete', f'/fuel/{self.fb.id}/delete',
                f'/fuel/{self.fb.id}/edit', f'/phoi/{self.pb.id}/edit',
                f'/phoi/{self.pb.id}/confirm', f'/phoi/{self.pb.id}/submit',
                f'/phoi/{self.pb.id}/cancel', f'/phoi/{self.pb.id}/attachments',
                f'/phoi/{self.pb.id}/attachments/{self.ab.id}/delete',
                f'/debts/customer/{self.cb.id}/collect',
                f'/debts/customer/{self.shared.id}/adjust/return_trip/{self.rb.id}']
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data={'amount': '100', 'reason': 'bad'}).status_code, 404)
        self.assertTrue(self.tb.is_active); self.assertTrue(self.db.is_active)
        self.assertEqual(self.pb.status, 'confirmed'); self.assertEqual(self.pb.manager_revenue_collected, 0)
        self.assertIsNotNone(db.session.get(FuelLog, self.fb.id))

    def test_shared_customer_debt_and_collection_only_touch_owned_trips(self):
        ctx, _ = self.render_context(f'/debts/customer/{self.shared.id}?payment_status=all')
        self.assertEqual(ctx['total_revenue_full'], 1200)
        self.assertEqual({row['phoi'].id for row in ctx['rows']}, {self.pa.id})
        response = self.client.post(f'/debts/customer/{self.shared.id}/collect', data={'amount': '2000'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.pa.manager_revenue_collected, 1000)
        self.assertEqual(self.ra.manager_revenue_collected, 200)
        self.assertEqual(self.pb.manager_revenue_collected, 0)
        self.assertEqual(self.rb.manager_revenue_collected, 0)

    def test_debt_filters_cannot_expand_scope(self):
        ctx, _ = self.render_context(f'/debts?truck_id={self.tb.id}')
        self.assertEqual(ctx['totals']['outstanding'], 0)
        ctx, _ = self.render_context(f'/debts/customer/{self.shared.id}?truck_id={self.tb.id}&all=1')
        self.assertEqual(ctx['total_count'], 0)

    def test_model_collection_service_also_rejects_foreign_trip(self):
        with self.assertRaises(ValueError):
            adjust_manager_collection(self.pb, '10', '0', 'test', self.a)
        self.assertEqual(self.pb.manager_revenue_collected, 0)

    def test_created_resources_are_owned_and_posted_owner_is_ignored(self):
        self.client.post('/trucks/create', data={'license_plate': 'NEW-TRUCK', 'manager_id': self.b.id})
        truck = Truck.query.filter_by(license_plate='NEW-TRUCK').one()
        self.assertEqual(truck.manager_id, self.a.id)
        self.client.post('/customers/create', data={'name': 'NEW-CUSTOMER', 'manager_ids': str(self.b.id)})
        customer = Customer.query.filter_by(name='NEW-CUSTOMER').one()
        self.assertEqual([m.id for m in customer.managers], [self.a.id])
        self.client.post('/drivers/create', data={'username': 'new-driver', 'full_name': 'New driver',
            'password': 'password', 'confirm_password': 'password', 'role': 'admin', 'manager_id': self.b.id})
        driver = User.query.filter_by(username='new-driver').one()
        self.assertEqual((driver.role, driver.manager_id), ('driver', self.a.id))
        self.login(self.b)
        self.assertEqual(self.client.get(f'/trucks/{truck.id}/edit').status_code, 404)

    def test_assignment_page_is_admin_only_and_csrf_protected(self):
        for actor in (self.a, self.da):
            self.login(actor)
            self.assertEqual(self.client.get('/admin/management').status_code, 403)
            self.assertEqual(self.assignment('truck', self.ta, self.b).status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.client.get('/admin/management').status_code, 200)
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.assignment('truck', self.ta, self.b).status_code, 400)
        self.assertEqual(self.ta.manager_id, self.a.id)

    def test_transfer_truck_moves_current_driver_and_all_history(self):
        before = self.pa.balance(), self.pa.owner_profit()
        # Customer A is not explicitly assigned to B; its historical debt must follow the truck.
        self.pa.customer = self.ca; db.session.commit()
        self.login(self.admin)
        self.assertEqual(self.assignment('truck', self.ta, self.b).status_code, 302)
        self.assertEqual((self.ta.manager_id, self.da.manager_id), (self.b.id, self.b.id))
        self.assertEqual(self.da.current_truck_id, self.ta.id)
        self.login(self.a)
        self.assertEqual(self.client.get(f'/phoi/{self.pa.id}').status_code, 404)
        ctx, _ = self.render_context(f'/debts/customer/{self.ca.id}?payment_status=all')
        self.assertEqual(ctx['total_count'], 0)
        self.login(self.b)
        self.assertEqual(self.client.get(f'/phoi/{self.pa.id}').status_code, 200)
        ctx, _ = self.render_context(f'/debts/customer/{self.ca.id}?payment_status=all')
        self.assertEqual(ctx['total_count'], 1)
        self.assertEqual(before, (self.pa.balance(), self.pa.owner_profit()))

    def test_stale_assignment_and_invalid_manager_leave_ownership_unchanged(self):
        self.login(self.admin)
        self.assertEqual(self.assignment('truck', self.ta, self.b, expected='9999').status_code, 400)
        inactive = self.user('inactive', 'manager'); inactive.is_active = False; db.session.commit()
        self.assertEqual(self.assignment('truck', self.ta, inactive).status_code, 400)
        self.assertEqual(self.ta.manager_id, self.a.id)

    def test_customers_can_be_shared_and_revoked_atomically(self):
        self.login(self.admin)
        data = MultiDict([('kind','customer'),('resource_id',str(self.ca.id)),('expected',str(self.a.id)),
                          ('manager_ids',str(self.a.id)),('manager_ids',str(self.b.id))])
        self.assertEqual(self.client.post('/admin/management', data=data).status_code, 302)
        self.assertEqual({m.id for m in self.ca.managers}, {self.a.id, self.b.id})
        data.setlist('manager_ids', [str(self.b.id)])
        self.assertEqual(self.client.post('/admin/management', data=data).status_code, 400) # stale
        data['expected'] = f'{self.a.id},{self.b.id}'
        self.assertEqual(self.client.post('/admin/management', data=data).status_code, 302)
        self.login(self.a)
        self.assertEqual(self.client.get(f'/api/customers/{self.ca.id}').status_code, 404)

    def test_linked_driver_cannot_be_transferred_separately(self):
        self.login(self.admin)
        self.assertEqual(self.assignment('driver', self.da, self.b).status_code, 400)
        self.assertEqual(self.da.manager_id, self.a.id)

    def test_legacy_unassigned_data_is_admin_only(self):
        self.assertEqual(self.client.get(f'/trucks/{self.legacy.id}/edit').status_code, 404)
        self.login(self.admin)
        self.assertEqual(self.client.get(f'/trucks/{self.legacy.id}/edit').status_code, 200)
        self.assertEqual(self.assignment('truck', self.legacy, self.a).status_code, 302)
        self.login(self.a)
        self.assertEqual(self.client.get(f'/trucks/{self.legacy.id}/edit').status_code, 200)

    def test_cross_manager_truck_driver_form_rejected_without_partial_save(self):
        response = self.client.post(f'/drivers/{self.da.id}/edit', data={
            'full_name': 'SHOULD-NOT-SAVE', 'current_truck_id': str(self.tb.id)})
        self.assertEqual(response.status_code, 404)
        db.session.expire_all()
        self.assertEqual(self.da.full_name, 'driver-a')
        self.assertEqual(self.da.current_truck_id, self.ta.id)
        response = self.client.post(f'/trucks/{self.ta.id}/edit', data={
            'license_plate': 'SHOULD-NOT-SAVE', 'current_driver_id': str(self.db.id)})
        self.assertEqual(response.status_code, 404)
        db.session.expire_all()
        self.assertEqual(self.ta.license_plate, 'TRUCK-A')
        self.assertEqual(self.da.current_truck_id, self.ta.id)

    def test_shared_customer_cannot_be_soft_deleted_by_one_manager(self):
        self.assertEqual(self.client.post(f'/customers/{self.shared.id}/delete').status_code, 403)
        self.assertTrue(self.shared.is_active)

    def test_driver_only_sees_own_fuel_and_assigned_customer_options(self):
        self.login(self.da)
        self.assertEqual(self.client.get(f'/fuel/{self.fb.id}/edit').status_code, 404)
        self.assertEqual(self.client.get(f'/api/customers/{self.cb.id}').status_code, 404)
        _, response = self.render_context('/fuel')
        self.assertNotIn(b'TRUCK-B', response.data)
        _, response = self.render_context('/phoi/create')
        self.assertNotIn(b'TRUCK-B', response.data)

    def test_logs_do_not_leak_other_manager_or_unscoped_history(self):
        db.session.add_all([
            ActivityLog(user_id=self.a.id, action='UPDATE', details='OLD-GLOBAL-SECRET'),
            ActivityLog(user_id=self.b.id, action='UPDATE', details='B-SECRET', scope_truck_id=self.tb.id),
            ActivityLog(user_id=self.b.id, action='UPDATE', details='A-ALLOWED', scope_truck_id=self.ta.id),
        ]); db.session.commit()
        response = self.client.get('/activity-logs')
        self.assertIn(b'A-ALLOWED', response.data)
        self.assertNotIn(b'B-SECRET', response.data)
        self.assertNotIn(b'OLD-GLOBAL-SECRET', response.data)

    def test_admin_cannot_deactivate_or_demote_manager_with_assignments(self):
        self.login(self.admin)
        self.assertEqual(self.client.post(f'/drivers/{self.a.id}/delete').status_code, 400)
        self.assertEqual(self.client.post(f'/drivers/{self.a.id}/edit', data={
            'role': 'driver', 'full_name': 'bad'}).status_code, 400)
        db.session.expire_all()
        self.assertTrue(self.a.is_active); self.assertEqual(self.a.role, 'manager')

    def test_inactive_existing_session_is_denied(self):
        self.a.is_active = False; db.session.commit()
        self.assertEqual(self.client.get('/phoi').status_code, 403)

    def test_phoi_creation_rejects_foreign_truck_and_customers(self):
        count = Phoi.query.count()
        data = {'truck_id': self.ta.id, 'customer_id': self.cb.id, 'origin': 'A', 'destination': 'B'}
        self.client.post('/phoi/create', data=data)
        self.assertEqual(Phoi.query.count(), count)
        data['customer_id'] = self.ca.id; data['truck_id'] = self.tb.id
        self.client.post('/phoi/create', data=data)
        self.assertEqual(Phoi.query.count(), count)
        data['truck_id'] = self.ta.id
        data.update({'return_trip_origin[]': 'A', 'return_trip_destination[]': 'B',
                     'return_trip_customer_id[]': self.cb.id})
        self.client.post('/phoi/create', data=data)
        self.assertEqual(Phoi.query.count(), count)

    def test_assignment_rolls_back_if_audit_write_fails(self):
        self.login(self.admin)
        def fail(mapper, connection, target):
            if target.resource_type == 'manager_assignments':
                from sqlalchemy.exc import SQLAlchemyError
                raise SQLAlchemyError('audit unavailable')
        event.listen(ActivityLog, 'before_insert', fail)
        try: response = self.assignment('truck', self.ta, self.b)
        finally: event.remove(ActivityLog, 'before_insert', fail)
        self.assertEqual(response.status_code, 409)
        db.session.expire_all()
        self.assertEqual((self.ta.manager_id, self.da.manager_id), (self.a.id, self.a.id))

    def test_valid_phoi_create_preserves_owner_and_customer_scopes(self):
        self.login(self.a)
        response = self.client.post('/phoi/create', data={
            'truck_id': self.ta.id, 'customer_id': self.ca.id,
            'origin': 'OWN-ORIGIN', 'destination': 'OWN-END',
            'return_trip_origin[]': 'OWN-RETURN', 'return_trip_destination[]': 'OWN-END',
            'return_trip_customer_id[]': self.shared.id,
        })
        self.assertEqual(response.status_code, 302)
        created = Phoi.query.filter_by(origin='OWN-ORIGIN').one()
        self.assertEqual((created.truck_id, created.driver_id, created.customer_id),
                         (self.ta.id, self.da.id, self.ca.id))
        self.assertEqual(created.return_trips.one().customer_id, self.shared.id)
        self.login(self.b)
        self.assertEqual(self.client.get(f'/phoi/{created.id}').status_code, 404)

    def test_fuel_form_cannot_link_other_managers_phoi(self):
        self.pb.status = 'draft'; db.session.commit()
        before = FuelLog.query.count()
        for truck, phoi in ((self.tb, self.pb), (self.ta, self.pb), (self.tb, self.pa)):
            image = BytesIO(); Image.new('RGB', (2, 2)).save(image, 'PNG'); image.seek(0)
            response = self.client.post('/fuel/create', data={
                'truck_id': truck.id, 'phoi_id': phoi.id, 'liters': '10',
                'price_per_liter': '20000', 'refuel_date': '2026-11-14',
                'receipts': (image, 'receipt.png'),
            })
            self.assertEqual(FuelLog.query.count(), before)
            self.assertNotIn(b'PHOI-B', response.data)

    def test_historical_customer_stays_selected_when_editing_transferred_phoi(self):
        self.pa.customer = self.ca; self.pa.status = 'draft'; db.session.commit()
        self.login(self.admin); self.assignment('truck', self.ta, self.b)
        self.login(self.b)
        ctx, _ = self.render_context(f'/phoi/{self.pa.id}/edit')
        self.assertIn(self.ca.id, {customer.id for customer in ctx['customers']})
        # Historical access does not grant that customer for unrelated new trips.
        self.assertEqual(self.client.get(f'/api/customers/{self.ca.id}').status_code, 404)
        response = self.client.post(f'/phoi/{self.pa.id}/edit', data={
            'truck_id': self.ta.id, 'customer_id': self.ca.id,
            'origin': 'NEW-ORIGIN', 'destination': 'End',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.pa.customer_id, self.ca.id)

    def test_unlinked_driver_can_be_assigned_and_revoked_by_admin(self):
        driver = self.user('unlinked', 'driver'); db.session.commit()
        self.login(self.admin)
        self.assertEqual(self.assignment('driver', driver, self.a).status_code, 302)
        self.assertEqual(driver.manager_id, self.a.id)
        self.assertEqual(self.assignment('driver', driver, None).status_code, 302)
        self.assertIsNone(driver.manager_id)

    def test_assignment_audit_contains_old_and_new_owner(self):
        self.login(self.admin); self.assignment('truck', self.ta, self.b)
        log = ActivityLog.query.filter_by(resource_type='manager_assignments').one()
        self.assertEqual(json.loads(log.details), {'kind': 'truck', 'before': self.a.id, 'after': self.b.id})

    def test_admin_sees_both_managers_trips_and_shared_debt(self):
        self.login(self.admin)
        ctx, _ = self.render_context('/phoi?status=confirmed')
        self.assertEqual({p.id for p in ctx['phois'].items}, {self.pa.id, self.pb.id})
        ctx, _ = self.render_context(f'/debts/customer/{self.shared.id}?payment_status=all')
        self.assertEqual(ctx['total_revenue_full'], 3100)
        self.assertEqual(ctx['total_count'], 4)

    def test_malformed_legacy_fuel_links_do_not_expose_foreign_phoi(self):
        self.fa.phois.append(self.pb); db.session.commit()
        self.assertEqual(self.client.get(f'/fuel/{self.fa.id}/edit').status_code, 404)
        ctx, _ = self.render_context('/fuel')
        self.assertEqual(ctx['logs'].total, 0)


if __name__ == '__main__': unittest.main()
