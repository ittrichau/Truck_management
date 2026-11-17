"""Debt correction and collection regressions using an isolated in-memory DB."""
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
import re
import subprocess
import unittest

os.environ['FLASK_ENV'] = 'testing'

from flask import g, template_rendered
from sqlalchemy import event, update
from sqlalchemy.exc import SQLAlchemyError

from app import create_app, db
from app.models import (
    ActivityLog, Customer, Phoi, PhoiReturnTrip, Truck, User,
    adjust_manager_collection,
)


class DebtAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.manager = User(username='manager', full_name='Quản lý', role='manager')
        self.admin = User(username='admin', full_name='Chủ xe', role='admin')
        self.driver = User(username='driver', full_name='Tài xế', role='driver')
        for user in (self.manager, self.admin, self.driver):
            user.set_password('test-password')
        self.truck = Truck(license_plate='71H-TEST')
        self.a = Customer(name='Khách A')
        self.b = Customer(name='Khách B')
        db.session.add_all([self.manager, self.admin, self.driver, self.truck, self.a, self.b])
        db.session.flush()
        self.truck.manager_id = self.manager.id
        self.driver.manager_id = self.manager.id
        self.a.managers.append(self.manager)
        self.b.managers.append(self.manager)
        self.main_b = self.phoi('B', self.b, 9, '500000', '100000', '400000')
        self.main_a = self.phoi('A', self.a, 10, '1000000', '0', '0')
        self.return_a = PhoiReturnTrip(
            phoi=self.main_b, customer=self.a, trip_order=1,
            return_date=date(2026, 11, 11), origin='A', destination='B',
            revenue_full=Decimal('600000'), revenue_collected=Decimal('50000'),
            manager_revenue_collected=Decimal('100000'),
        )
        self.return_b = PhoiReturnTrip(
            phoi=self.main_a, customer=self.b, trip_order=1,
            return_date=date(2026, 11, 8), origin='A', destination='B',
            revenue_full=Decimal('200000'), revenue_collected=Decimal('0'),
            manager_revenue_collected=Decimal('0'),
        )
        db.session.add_all([self.return_a, self.return_b])
        db.session.commit()
        self.login(self.manager)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def phoi(self, number, customer, day, full, driver, manager):
        phoi = Phoi(
            phoi_number=number, customer=customer, truck=self.truck,
            driver=self.driver, departure_date=date(2026, 11, day),
            origin='A', destination='B', revenue_full=Decimal(full),
            revenue_collected=Decimal(driver), manager_revenue_collected=Decimal(manager),
            driver_wage=Decimal('20000'), status='confirmed',
        )
        db.session.add(phoi)
        db.session.flush()
        return phoi

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def url(self, target):
        kind = 'phoi' if isinstance(target, Phoi) else 'return_trip'
        return f'/debts/customer/{target.customer_id}/adjust/{kind}/{target.id}'

    def correct(self, target, amount='0', **overrides):
        data = dict(amount=amount, expected_amount=str(target.manager_revenue_collected),
                    reason='Khách A trả tiền, ghi nhầm vào khách B')
        data.update(overrides)
        return self.client.post(self.url(target), data=data)

    def logs(self):
        return ActivityLog.query.filter_by(resource_type='debt_collection').all()

    def test_wrong_customer_can_be_corrected_and_recollected_without_changing_driver_finances(self):
        before = (self.main_b.balance(), self.main_b.owner_profit(),
                  self.main_a.balance(), self.main_a.owner_profit())
        self.assertEqual(self.correct(self.main_b).status_code, 302)
        response = self.client.post(f'/debts/customer/{self.a.id}/collect', data={'amount': '400,000'})
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        self.assertEqual(self.main_b.manager_revenue_collected, 0)
        self.assertEqual(self.main_a.manager_revenue_collected, 400000)
        self.assertEqual(self.return_a.manager_revenue_collected, 100000)
        self.assertEqual(self.main_b.revenue_collected, 100000)
        self.assertEqual(before, (self.main_b.balance(), self.main_b.owner_profit(),
                                 self.main_a.balance(), self.main_a.owner_profit()))
        log, = self.logs()
        details = json.loads(log.details)
        self.assertEqual(log.user_id, self.manager.id)
        self.assertIsNotNone(log.created_at)
        self.assertEqual(log.ip_address, '127.0.0.1')
        self.assertEqual(details['customer_id'], self.b.id)
        self.assertEqual(Decimal(details['old_amount']), 400000)
        self.assertEqual(Decimal(details['new_amount']), 0)
        self.assertIsNone(details['return_trip_id'])
        self.assertIn('ghi nhầm', details['reason'])
        audit_html = self.client.get('/activity-logs').get_data(as_text=True)
        self.assertIn('Khách A trả tiền, ghi nhầm vào khách B', audit_html)
        self.assertIn('Trước: 400,000.00 đ → Sau: 0.00 đ', audit_html)
        contexts = []

        def capture(sender, template, context, **extra):
            contexts.append(context)

        with template_rendered.connected_to(capture, self.app):
            self.assertEqual(self.client.get('/debts').status_code, 200)
        debts = {row['customer'].id: row['outstanding'] for row in contexts[-1]['debts']}
        self.assertEqual(debts[self.b.id], 600000)
        self.assertEqual(debts[self.a.id], 1050000)

    def test_return_trip_uses_its_own_customer_and_admin_can_adjust_up_to_remaining(self):
        self.login(self.admin)
        self.assertEqual(self.correct(self.return_a, '550,000').status_code, 302)
        db.session.expire_all()
        self.assertEqual(self.return_a.manager_revenue_collected, 550000)
        self.assertEqual(self.main_b.manager_revenue_collected, 400000)
        self.assertEqual(self.return_b.manager_revenue_collected, 0)
        log, = self.logs()
        self.assertEqual(log.user_id, self.admin.id)
        self.assertEqual(json.loads(log.details)['return_trip_id'], self.return_a.id)

    def test_invalid_amounts_reason_and_stale_form_leave_data_and_audit_unchanged(self):
        cases = [dict(amount=value) for value in (
            '', '-1', 'NaN', 'Infinity', '1e3', 'abc', '1,00', '1.001',
            '10000000000', '9999999999.99', '400001',
        )]
        cases += [dict(reason=value) for value in ('', '  ', 'x' * 501)]
        cases += [dict(expected_amount='399999'), dict(expected_amount=''), dict(amount='400000')]
        for case in cases:
            with self.subTest(case=case):
                response = self.correct(self.main_b, **case)
                self.assertEqual(response.status_code, 400)
                db.session.expire_all()
                self.assertEqual(self.main_b.manager_revenue_collected, 400000)
                self.assertEqual(self.main_b.revenue_collected, 100000)
                self.assertEqual(self.logs(), [])

    def test_manager_changes_after_get_are_not_overwritten(self):
        response = self.client.get(self.url(self.main_b))
        expected = re.search(r'name="expected_amount" value="([^"]+)"',
                             response.get_data(as_text=True))[1]
        self.main_b.manager_revenue_collected = Decimal('350000')
        db.session.commit()
        response = self.correct(self.main_b, expected_amount=expected)
        self.assertEqual(response.status_code, 400)
        self.assertIn('vừa thay đổi', response.get_data(as_text=True))
        db.session.expire_all()
        self.assertEqual(self.main_b.manager_revenue_collected, 350000)
        self.assertEqual(self.logs(), [])

    def test_compare_and_set_rejects_changes_after_target_was_loaded(self):
        for target in (self.main_b, self.return_a):
            original = target.manager_revenue_collected
            db.session.execute(update(type(target)).where(type(target).id == target.id).values(
                manager_revenue_collected=original - 1,
            ), execution_options={'synchronize_session': False})
            with self.assertRaisesRegex(ValueError, 'vừa thay đổi'):
                adjust_manager_collection(target, '0', str(original), 'Sửa nhầm', self.manager)
            db.session.rollback()
        self.assertEqual(self.logs(), [])

    def test_correction_and_audit_rollback_together(self):
        def fail_audit(mapper, connection, target):
            if target.resource_type == 'debt_collection':
                raise SQLAlchemyError('audit insert failed')

        event.listen(ActivityLog, 'before_insert', fail_audit)
        try:
            with self.assertLogs(self.app.logger, level='ERROR'):
                response = self.correct(self.main_b)
        finally:
            event.remove(ActivityLog, 'before_insert', fail_audit)
        self.assertEqual(response.status_code, 500)
        self.assertIn('Dữ liệu chưa được thay đổi', response.get_data(as_text=True))
        db.session.expire_all()
        self.assertEqual(self.main_b.manager_revenue_collected, 400000)
        self.assertEqual(self.logs(), [])

    def test_wrong_customer_unknown_type_and_unconfirmed_rows_are_rejected(self):
        for target in (self.main_b, self.return_a):
            wrong_customer = self.a.id if target.customer_id == self.b.id else self.b.id
            wrong_url = self.url(target).replace(f'/customer/{target.customer_id}/', f'/customer/{wrong_customer}/')
            for method in (self.client.get, self.client.post):
                self.assertEqual(method(wrong_url).status_code, 404)
        self.assertEqual(self.client.get(self.url(self.main_b).replace('/phoi/', '/other/')).status_code, 404)
        self.assertEqual(self.client.post(self.url(self.main_b).rsplit('/', 1)[0] + '/9999').status_code, 404)
        for status in ('draft', 'submitted', 'cancelled'):
            self.main_b.status = status
            db.session.commit()
            for target in (self.main_b, self.return_a):
                self.assertEqual(self.client.get(self.url(target)).status_code, 404)
                self.assertEqual(self.correct(target).status_code, 404)
        self.assertEqual(self.logs(), [])

    def test_driver_and_anonymous_users_cannot_read_or_correct_debts(self):
        self.login(self.driver)
        for target in (self.main_b, self.return_a):
            for response in (self.client.get(self.url(target)), self.correct(target)):
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.location.endswith('/phoi'))
        with self.client.session_transaction() as session:
            session.clear()
        g.pop('_login_user', None)
        response = self.correct(self.main_b)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)
        self.assertEqual(self.logs(), [])
        self.assertEqual(self.main_b.manager_revenue_collected, 400000)

    def test_csrf_protects_correction(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        response = self.correct(self.main_b)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.main_b.manager_revenue_collected, 400000)
        self.assertEqual(self.logs(), [])

    def test_paid_trip_is_reachable_and_filters_survive_correction(self):
        url = f'/debts/customer/{self.b.id}'
        self.assertNotIn(self.url(self.main_b), self.client.get(url).get_data(as_text=True))
        for status in ('all', 'paid'):
            html = self.client.get(url + f'?payment_status={status}').get_data(as_text=True)
            self.assertIn(self.url(self.main_b), html)
            self.assertIn('Điều chỉnh tiền thu', html)
        filters = f'?payment_status=paid&truck_id={self.truck.id}&start_date=2026-11-01&end_date=2026-11-30&all=1'
        response = self.client.post(self.url(self.main_b) + filters, data={
            'amount': '0', 'expected_amount': '400000', 'reason': 'Sửa nhầm khách',
        })
        self.assertEqual(response.status_code, 302)
        for value in ('payment_status=paid', f'truck_id={self.truck.id}',
                      'start_date=2026-11-01', 'end_date=2026-11-30', 'all=1'):
            self.assertIn(value, response.location)

    def test_collection_keeps_oldest_first_and_excess_does_not_overcollect(self):
        self.main_b.manager_revenue_collected = Decimal('0')
        db.session.commit()
        response = self.client.post(f'/debts/customer/{self.b.id}/collect', data={'amount': '700,000'})
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        self.assertEqual(self.return_b.manager_revenue_collected, 200000)
        self.assertEqual(self.main_b.manager_revenue_collected, 400000)
        self.assertEqual(self.main_a.manager_revenue_collected, 0)
        self.assertEqual(self.return_a.manager_revenue_collected, 100000)
        with self.client.session_transaction() as session:
            self.assertIn('100,000 đ vượt quá', session['_flashes'][-1][1])

    def test_invalid_collection_amounts_never_change_debt(self):
        for value in ('0', '-1', 'NaN', 'Infinity', '1e999', '1.001', '1,00', '10000000000'):
            with self.subTest(value=value):
                response = self.client.post(f'/debts/customer/{self.a.id}/collect', data={'amount': value})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.main_a.manager_revenue_collected, 0)
                self.assertEqual(self.return_a.manager_revenue_collected, 100000)

    def test_both_forms_opt_into_real_currency_input_and_submit_handlers(self):
        root = Path(__file__).resolve().parents[1]
        forms = [self.client.get(f'/debts/customer/{self.b.id}').get_data(as_text=True),
                 self.client.get(self.url(self.main_b)).get_data(as_text=True)]
        for html in forms:
            amount_tag = re.search(r'<input\b[^>]*name="amount"[^>]*>', html)[0]
            self.assertIn('currency-input', amount_tag)
            self.assertIn('inputmode="numeric"', amount_tag)
        result = subprocess.run(['node', str(root / 'tests/debt_currency_checks.js')],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
