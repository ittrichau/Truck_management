"""Direct date entry, validation, alerts, and access without a dev server."""
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import unittest
from unittest.mock import patch

from flask import g, template_rendered

import test_truck_insurance as fixtures
from app import db
from app.models import Truck, User


class DateFields(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.inputs = {}; self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'input' and attrs.get('name'): self.inputs[attrs['name']] = attrs


class TruckDocumentExpiryTests(unittest.TestCase):
    setUp = fixtures.TruckInsuranceTests.setUp
    tearDown = fixtures.TruckInsuranceTests.tearDown
    edit_form = fixtures.TruckInsuranceTests.edit_form

    def login(self, user):
        g.pop('_login_user', None)
        fixtures.TruckInsuranceTests.login(self, user)

    def post(self, **values):
        form = self.edit_form(); form.update(values)
        return self.client.post(f'/trucks/{self.truck.id}/edit', data=form)

    def test_create_and_edit_forms_have_only_three_direct_date_inputs(self):
        for path in ('/trucks/create', f'/trucks/{self.truck.id}/edit'):
            with self.subTest(path=path):
                response = self.client.get(path); self.assertEqual(response.status_code, 200)
                fields = DateFields(response.get_data(as_text=True)).inputs
                dates = {name for name, attrs in fields.items() if attrs.get('type') == 'date'}
                self.assertEqual(dates, {'inspection_expiry_date', 'permit_expiry_date', 'insurance_expiry_date'})
                self.assertTrue({'inspection_date', 'inspection_expiry_months', 'permit_date', 'permit_expiry_months'}.isdisjoint(fields))
                if '/edit' in path:
                    self.assertEqual(fields['inspection_expiry_date']['value'], '2027-04-01')
                    self.assertEqual(fields['permit_expiry_date']['value'], '2027-10-02')

    def test_create_stores_exact_dates_not_plus_six_or_twelve_months(self):
        response = self.client.post('/trucks/create', data={'license_plate': 'DIRECT-NEW',
            'inspection_expiry_date': '2026-01-31', 'permit_expiry_date': '2028-02-29',
            'insurance_expiry_date': '2027-03-31'})
        self.assertEqual(response.status_code, 302)
        truck = Truck.query.filter_by(license_plate='DIRECT-NEW').one()
        self.assertEqual(truck.inspection_expiry_date(), date(2026, 1, 31))
        self.assertEqual(truck.permit_expiry_date(), date(2028, 2, 29))
        self.assertEqual(truck.insurance_expiry_date, date(2027, 3, 31))
        self.assertEqual(truck.manager_id, self.manager.id)
        self.assertIsNone(truck.inspection_date); self.assertIsNone(truck.permit_date)

    def test_repeated_edits_keep_entered_dates_and_assignment(self):
        for _ in range(3):
            response = self.post(inspection_expiry_date='2028-02-29', permit_expiry_date='2026-01-31')
            self.assertEqual(response.status_code, 302)
            db.session.expire_all()
            self.assertEqual(self.truck.inspection_expiry_date(), date(2028, 2, 29))
            self.assertEqual(self.truck.permit_expiry_date(), date(2026, 1, 31))
            self.assertEqual(self.driver.current_truck_id, self.truck.id)
            self.assertEqual(self.truck.inspection_date, date(2026, 10, 1)) # retained legacy

    def test_clearing_dates_does_not_fall_back_to_legacy_issue_dates(self):
        self.assertEqual(self.post(inspection_expiry_date='', permit_expiry_date='').status_code, 302)
        self.assertIsNone(self.truck.inspection_expiry_date()); self.assertIsNone(self.truck.permit_expiry_date())
        self.assertIsNone(self.truck.inspection_days_until_expiry()); self.assertIsNone(self.truck.permit_days_until_expiry())
        self.assertFalse(self.truck.inspection_should_notify()); self.assertFalse(self.truck.permit_should_notify())
        self.assertIsNotNone(self.truck.inspection_date)
        fields = DateFields(self.client.get(f'/trucks/{self.truck.id}/edit').get_data(as_text=True)).inputs
        self.assertEqual(fields['inspection_expiry_date']['value'], '')
        self.assertEqual(fields['permit_expiry_date']['value'], '')

    def test_omitted_fields_preserve_dates_and_notification_cooldown(self):
        notified = datetime.utcnow(); self.truck.last_inspection_notified_at = notified
        self.truck.last_permit_notified_at = notified; db.session.commit()
        response = self.client.post(f'/trucks/{self.truck.id}/edit', data={
            'license_plate': self.truck.license_plate, 'current_driver_id': str(self.driver.id)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.truck.inspection_expires_on, date(2027, 4, 1))
        self.assertEqual(self.truck.permit_expires_on, date(2027, 10, 2))
        self.assertEqual(self.truck.last_inspection_notified_at, notified)
        self.assertEqual(self.truck.last_permit_notified_at, notified)

    def test_invalid_date_rejects_whole_edit_before_other_fields_are_changed(self):
        for field in ('inspection_expiry_date', 'permit_expiry_date'):
            for value in ('2027-02-29', '2026-13-01', '2026-1-1', 'bad-date', '2026-02-30'):
                with self.subTest(field=field, value=value):
                    response = self.post(**{field: value, 'license_plate': 'MUST-NOT-SAVE'})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('không hợp lệ', response.get_data(as_text=True))
                    db.session.expire_all()
                    self.assertEqual(self.truck.license_plate, 'INS-001')
                    self.assertEqual(self.truck.inspection_expires_on, date(2027, 4, 1))
                    self.assertEqual(self.truck.permit_expires_on, date(2027, 10, 2))
                    self.assertEqual(self.driver.current_truck_id, self.truck.id)

    def test_invalid_create_does_not_add_truck_and_preserves_other_date_input(self):
        response = self.client.post('/trucks/create', data={'license_plate': 'INVALID-DIRECT',
            'inspection_expiry_date': '2028-02-29', 'permit_expiry_date': '2027-02-29'})
        self.assertIsNone(Truck.query.filter_by(license_plate='INVALID-DIRECT').first())
        fields = DateFields(response.get_data(as_text=True)).inputs
        self.assertEqual(fields['inspection_expiry_date']['value'], '2028-02-29')

    def test_changed_date_resets_only_that_documents_notification(self):
        notified = datetime.utcnow()
        self.truck.last_inspection_notified_at = notified; self.truck.last_permit_notified_at = notified
        db.session.commit()
        self.assertEqual(self.post(inspection_expiry_date='2026-11-24').status_code, 302)
        self.assertIsNone(self.truck.last_inspection_notified_at)
        self.assertEqual(self.truck.last_permit_notified_at, notified)
        self.truck.last_inspection_notified_at = notified; db.session.commit()
        self.assertEqual(self.post(inspection_expiry_date='2026-11-24').status_code, 302)
        self.assertEqual(self.truck.last_inspection_notified_at, notified)

    def test_list_and_edit_show_expiry_date_and_readable_day_boundaries(self):
        for days, label in ((None, 'Chưa nhập'), (-294, 'Quá hạn 294 ngày'),
                            (0, 'Hết hạn hôm nay'), (1, 'Còn 1 ngày'), (15, 'Còn 15 ngày'), (16, None)):
            with self.subTest(days=days):
                expiry = date.today() + timedelta(days=days) if days is not None else None
                self.truck.inspection_expires_on = self.truck.permit_expires_on = expiry
                self.truck.insurance_expiry_date = None; db.session.commit()
                response = self.client.get('/trucks'); html = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.truck.inspection_days_until_expiry(), days)
                self.assertEqual(self.truck.permit_days_until_expiry(), days)
                if label: self.assertIn(label, html)
                else: self.assertNotIn('Còn 16 ngày', html)
                if expiry: self.assertEqual(html.count(expiry.strftime('%d/%m/%Y')), 2)
                self.assertNotIn('còn -', html.lower())
                edited = self.client.get(f'/trucks/{self.truck.id}/edit').get_data(as_text=True)
                if days == -294: self.assertEqual(edited.count('Quá hạn 294 ngày'), 2)

    def test_phoi_alerts_follow_entered_date_and_ignore_retained_legacy_date(self):
        self.truck.inspection_expires_on = date.today() - timedelta(days=1)
        self.truck.permit_expires_on = None; db.session.commit()
        captured = []
        def capture(sender, template, context, **extra): captured.append(context)
        with template_rendered.connected_to(capture, self.app): response = self.client.get('/phoi')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured[-1]['expiry_warnings'], [('INS-001', 'Đăng kiểm (quá hạn)', 1)])

    def test_legacy_open_forms_are_rejected_instead_of_adding_months_or_erasing_dates(self):
        response = self.post(inspection_date='2026-01-31', inspection_expiry_months='6')
        self.assertIn('Vui lòng tải lại trang', response.get_data(as_text=True))
        self.assertEqual(self.truck.inspection_expires_on, date(2027, 4, 1))
        response = self.client.post('/trucks/create', data={'license_plate': 'OLD-FORM',
            'permit_date': '2026-01-31', 'permit_expiry_months': '12'})
        self.assertIn('Vui lòng tải lại trang', response.get_data(as_text=True))
        self.assertIsNone(Truck.query.filter_by(license_plate='OLD-FORM').first())

    def test_other_manager_and_driver_cannot_change_expiry_dates(self):
        other = User(username='other-expiry-manager', full_name='Other', password_hash='unused', role='manager')
        db.session.add(other); db.session.commit()
        self.login(other)
        self.assertEqual(self.post(inspection_expiry_date='2028-02-29').status_code, 404)
        self.login(self.driver)
        self.assertEqual(self.post(permit_expiry_date='2028-02-29').status_code, 302)
        self.assertEqual(self.truck.inspection_expires_on, date(2027, 4, 1))
        self.assertEqual(self.truck.permit_expires_on, date(2027, 10, 2))

    def test_csrf_protects_date_updates(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.post(inspection_expiry_date='2028-02-29').status_code, 400)
        self.assertEqual(self.truck.inspection_expires_on, date(2027, 4, 1))


if __name__ == '__main__': unittest.main()
