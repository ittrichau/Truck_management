"""Submission without returns and printable debt, fuel and porter totals."""
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
import unittest
from unittest.mock import patch

from flask import g

from app import create_app, db
from app.models import FuelLog, Phoi, PhoiExpense, PhoiReturnTrip, Truck, User
from config import TestingConfig


class TableRows(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag == 'td':
            self.cell = ''

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag == 'td' and self.row is not None:
            self.row.append(' '.join(self.cell.split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


class PhoiCompletionPrintTests(unittest.TestCase):
    def setUp(self):
        with patch('app.get_config', return_value=TestingConfig):
            self.app = create_app('testing')
        self.app.config.update(SECRET_KEY='completion-print-tests', RATELIMIT_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        self.assertEqual(str(db.engine.url), 'sqlite:///:memory:')
        db.create_all()
        self.driver = User(username='driver', full_name='Driver', password_hash='unused', role='driver')
        self.manager = User(username='manager', full_name='Manager', password_hash='unused', role='manager')
        self.admin = User(username='admin', full_name='Admin', password_hash='unused', role='admin')
        self.other = User(username='other', full_name='Other', password_hash='unused', role='driver')
        self.truck = Truck(license_plate='PRINT-001')
        db.session.add_all([self.driver, self.manager, self.admin, self.other, self.truck])
        db.session.flush()
        self.truck.manager_id = self.manager.id
        self.driver.manager_id = self.manager.id
        self.phoi = Phoi(phoi_number='COMPLETION-PRINT', driver_id=self.driver.id,
                         truck_id=self.truck.id, departure_date=date(2026, 11, 13),
                         origin='A', destination='B', km_start=0, km_end=650, km_total=650,
                         revenue_full=3600000, revenue_collected=500000,
                         manager_revenue_collected=400000, driver_wage=450000)
        db.session.add(self.phoi)
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

    def fuel(self, liters='137.335', cost='2746700', paid_by='owner'):
        fuel = FuelLog(truck_id=self.truck.id, refuel_date=date(2026, 11, 13),
                       liters=Decimal(liters), price_per_liter=20000,
                       total_cost=Decimal(cost), paid_by=paid_by)
        fuel.phois.append(self.phoi)
        db.session.add(fuel)
        db.session.commit()
        return fuel

    def returns(self):
        for n in range(3):
            db.session.add(PhoiReturnTrip(phoi_id=self.phoi.id, trip_order=n + 1,
                                         origin='B', destination='A', revenue_full=4000000,
                                         revenue_collected=200000, manager_revenue_collected=100000,
                                         porter_fee=50000))
        db.session.add(PhoiExpense(phoi_id=self.phoi.id, category='porter_fee', amount=80000))
        db.session.commit()

    def print_html(self, user=None):
        self.login(user or self.manager)
        response = self.client.get(f'/phoi/{self.phoi.id}/print')
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_driver_and_manager_can_submit_without_returns(self):
        self.fuel()
        for user in (self.driver, self.manager):
            with self.subTest(role=user.role):
                self.phoi.status = 'draft'
                db.session.commit()
                self.login(user)
                response = self.client.post(f'/phoi/{self.phoi.id}/submit')
                self.assertEqual(response.status_code, 302)
                db.session.refresh(self.phoi)
                self.assertEqual(self.phoi.status, 'submitted')
                self.assertEqual(self.phoi.return_trips.count(), 0)

    def test_missing_fuel_still_blocks_submission(self):
        response = self.client.post(f'/phoi/{self.phoi.id}/submit', follow_redirects=True)
        self.assertIn('Phơi chưa được gắn'.encode(), response.data)
        self.assertEqual(self.phoi.status, 'draft')

    def test_nonpositive_end_km_still_blocks_submission(self):
        self.fuel()
        for km in (None, 0, -1):
            with self.subTest(km=km):
                self.phoi.km_end = km
                db.session.commit()
                self.client.post(f'/phoi/{self.phoi.id}/submit')
                self.assertEqual(self.phoi.status, 'draft')

    def confirm(self, advance=None, user=None):
        self.login(user or self.manager)
        data = {
            'outbound_collection_status': 'partial',
            'outbound_manager_revenue_collected': '400000',
            'driver_wage': '450000', 'toll_fee_status': 'incurred', 'toll_fee_amount': '350000',
        }
        if advance is not None:
            data['driver_advance'] = advance
        return self.client.post(f'/phoi/{self.phoi.id}/confirm', data=data)

    def test_advance_reduces_settlement_once_without_changing_profit_or_debt(self):
        self.returns()
        self.fuel('12.5', '275000', 'driver')
        self.phoi.status = 'submitted'
        db.session.commit()
        base_balance = self.phoi.balance()
        self.assertEqual(self.confirm('600,000').status_code, 302)
        db.session.refresh(self.phoi)
        self.assertEqual(self.phoi.status, 'confirmed')
        self.assertEqual(self.phoi.driver_advance, Decimal('600000'))
        self.assertEqual(self.phoi.balance(), base_balance)
        self.assertEqual(self.phoi.settlement_balance(), base_balance - Decimal('600000'))
        # Costs remain porter + driver-paid fuel + toll; advance is a transfer.
        self.assertEqual(self.phoi.total_expenses(), Decimal('855000'))
        self.assertEqual(self.phoi.owner_profit(), Decimal('14295000'))
        self.assertEqual(self.phoi.total_revenue_collected(), Decimal('1100000'))
        for user in (self.driver, self.manager, self.admin):
            with self.subTest(role=user.role):
                self.login(user)
                detail = self.client.get(f'/phoi/{self.phoi.id}').get_data(as_text=True)
                listing = self.client.get('/phoi?status=confirmed').get_data(as_text=True)
                printed = self.print_html(user)
                self.assertIn('Tiền quản lý đã ứng cho tài xế', detail)
                self.assertIn('600,000 VNĐ', detail)
                self.assertIn('745,000 VNĐ', detail)
                self.assertIn('Tài xế nộp lại: 745,000 VNĐ', listing)
                self.assertIn('Quản lý đã ứng (trừ khi quyết toán): 600,000 VNĐ', printed)
                self.assertIn('745,000 VNĐ', printed)
                if user.is_driver():
                    self.assertNotIn('Lợi nhuận chủ xe', detail)
                    self.assertNotIn('Lợi nhuận chủ xe', printed)
                else:
                    self.assertIn(['Công nợ còn lại', '14,100,000 VNĐ'], TableRows(printed).rows)

    def test_manager_and_admin_can_confirm_with_advance_and_cannot_confirm_twice(self):
        self.fuel()
        self.phoi.revenue_collected = 0
        for user in (self.manager, self.admin):
            with self.subTest(role=user.role):
                self.phoi.status = 'submitted'
                db.session.commit()
                self.assertEqual(self.confirm('100000', user).status_code, 302)
                db.session.refresh(self.phoi)
                self.assertEqual(self.phoi.status, 'confirmed')
                self.assertEqual(self.phoi.settlement_balance(), Decimal('350000'))
                self.confirm('900000', user)
                db.session.refresh(self.phoi)
                self.assertEqual(self.phoi.driver_advance, Decimal('100000'))
                self.assertEqual(self.phoi.settlement_balance(), Decimal('350000'))

    def test_no_advance_keeps_previous_result_and_exact_advance_settles_to_zero(self):
        self.fuel()
        self.phoi.revenue_collected = 0
        for amount in (None, '', '0', '450,000'):
            with self.subTest(amount=amount):
                self.phoi.status = 'submitted'
                db.session.commit()
                self.confirm(amount)
                db.session.refresh(self.phoi)
                self.assertEqual(self.phoi.status, 'confirmed')
                expected = Decimal('450000') if amount == '450,000' else Decimal('0')
                self.assertEqual(self.phoi.driver_advance, expected)
                self.assertEqual(self.phoi.settlement_balance(), Decimal('450000') - expected)

    def test_invalid_advance_rolls_back_all_confirmation_changes(self):
        self.fuel()
        self.phoi.status = 'submitted'
        self.phoi.driver_wage = Decimal('200000')
        self.phoi.manager_revenue_collected = Decimal('100000')
        db.session.commit()
        for amount in ('-1', 'abc', 'NaN', 'sNaN', 'Infinity', '1e6', '12,34', '1.001', '10000000000'):
            with self.subTest(amount=amount):
                response = self.confirm(amount)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.location.endswith('/confirm'))
                db.session.refresh(self.phoi)
                self.assertEqual(self.phoi.status, 'submitted')
                self.assertEqual(self.phoi.driver_advance, 0)
                self.assertEqual(self.phoi.driver_wage, Decimal('200000'))
                self.assertEqual(self.phoi.manager_revenue_collected, Decimal('100000'))
                self.assertIsNone(self.phoi.confirmed_at)
                self.assertEqual(self.phoi.expenses.count(), 0)

    def test_driver_cannot_record_advance_via_submit_or_confirm(self):
        self.fuel()
        self.client.post(f'/phoi/{self.phoi.id}/submit', data={'driver_advance': '900000'})
        db.session.refresh(self.phoi)
        self.assertEqual(self.phoi.status, 'submitted')
        self.assertEqual(self.phoi.driver_advance, 0)
        for driver in (self.driver, self.other):
            with self.subTest(driver=driver.username):
                self.assertEqual(self.confirm('900000', driver).status_code, 302)
                self.assertEqual(self.client.get(f'/phoi/{self.phoi.id}/confirm').status_code, 302)
                db.session.refresh(self.phoi)
                self.assertEqual(self.phoi.status, 'submitted')
                self.assertEqual(self.phoi.driver_advance, 0)

    def test_advance_does_not_bypass_fuel_requirement(self):
        self.phoi.status = 'submitted'
        db.session.commit()
        self.confirm('100000')
        db.session.refresh(self.phoi)
        self.assertEqual(self.phoi.status, 'submitted')
        self.assertEqual(self.phoi.driver_advance, 0)
        self.assertEqual(self.phoi.expenses.count(), 0)

    def test_manager_outside_truck_scope_cannot_record_advance(self):
        outsider = User(username='outside-manager', full_name='Outside Manager',
                        password_hash='unused', role='manager')
        db.session.add(outsider)
        self.fuel()
        self.phoi.status = 'submitted'
        db.session.commit()
        self.assertEqual(self.confirm('900000', outsider).status_code, 404)
        self.assertEqual(self.client.get(f'/phoi/{self.phoi.id}/confirm').status_code, 404)
        db.session.refresh(self.phoi)
        self.assertEqual(self.phoi.status, 'submitted')
        self.assertEqual(self.phoi.driver_advance, 0)
        self.assertEqual(self.phoi.manager_revenue_collected, Decimal('400000'))

    def test_confirmation_form_explains_advance_and_defaults_to_zero(self):
        self.phoi.status = 'submitted'
        db.session.commit()
        self.login(self.manager)
        response = self.client.get(f'/phoi/{self.phoi.id}/confirm')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Tiền quản lý đã ứng cho tài xế', html)
        self.assertIn('name="driver_advance" value="0"', html)
        self.assertIn('Khoản này được trừ khi quyết toán với tài xế', html)

    def test_outbound_only_phoi_can_be_confirmed(self):
        self.fuel()
        self.client.post(f'/phoi/{self.phoi.id}/submit')
        response = self.confirm()
        self.assertEqual(response.status_code, 302)
        db.session.refresh(self.phoi)
        self.assertEqual(self.phoi.status, 'confirmed')
        rows = TableRows(self.print_html()).rows
        self.assertIn(['Công nợ còn lại', '2,700,000 VNĐ'], rows)

    def test_confirmation_still_requires_fuel_and_valid_revenue(self):
        self.phoi.status = 'submitted'
        db.session.commit()
        self.confirm()
        self.assertEqual(self.phoi.status, 'submitted')
        self.assertEqual(self.phoi.expenses.count(), 0)
        self.fuel()
        self.phoi.revenue_full = 0
        self.phoi.revenue_collected = 0
        db.session.commit()
        self.confirm()
        self.assertEqual(self.phoi.status, 'submitted')
        self.assertEqual(self.phoi.expenses.count(), 0)

    def test_other_driver_cannot_submit_or_print(self):
        self.fuel()
        self.login(self.other)
        self.client.post(f'/phoi/{self.phoi.id}/submit')
        self.assertEqual(self.phoi.status, 'draft')
        self.assertEqual(self.client.get(f'/phoi/{self.phoi.id}/print').status_code, 404)

    def test_print_debt_and_porter_totals_do_not_change_finances(self):
        self.returns()
        self.fuel()
        self.fuel('12.5', '275000', 'driver')
        before = (self.phoi.balance(), self.phoi.owner_profit(), self.phoi.total_expenses())
        for user in (self.manager, self.admin):
            with self.subTest(role=user.role):
                html = self.print_html(user)
                rows = TableRows(html).rows
                self.assertIn(['Quản lý/chủ xe đã thu', '700,000 VNĐ'], rows)
                self.assertIn(['Công nợ còn lại', '13,800,000 VNĐ'], rows)
                self.assertIn(['Tổng bồi dưỡng bốc vác', '230,000 VNĐ'], rows)
                self.assertIn(['Tổng chi', '3,251,700 VNĐ'], rows)
                self.assertEqual(html.count('Tổng bồi dưỡng bốc vác'), 1)
                self.assertEqual(html.count('Còn phải thu:'), 4)
                self.assertIn('2,700,000 VNĐ', html)
                self.assertEqual(html.count('3,700,000 VNĐ'), 3)
                self.assertNotIn('Bốc vác về #', html)
                self.assertNotIn('Bốc vác (tài xế ứng)', html)
        self.assertEqual(before, (self.phoi.balance(), self.phoi.owner_profit(), self.phoi.total_expenses()))
        self.assertEqual(before, (Decimal('-145000'), Decimal('11898300'), Decimal('3251700')))

    def test_each_fuel_fill_has_precise_liters_and_its_own_cost(self):
        self.fuel()
        self.fuel('12.5', '275000', 'driver')
        rows = TableRows(self.print_html()).rows
        fuel_rows = [row for row in rows if row[0].startswith('Dầu (')]
        self.assertEqual(len(fuel_rows), 2)
        self.assertIn('Dầu (137.335 lít)', fuel_rows[0][0])
        self.assertIn('Chủ xe trả', fuel_rows[0][0])
        self.assertEqual(fuel_rows[0][1], '2,746,700 VNĐ')
        self.assertIn('Dầu (12.5 lít)', fuel_rows[1][0])
        self.assertIn('Tài xế tự trả', fuel_rows[1][0])
        self.assertEqual(fuel_rows[1][1], '275,000 VNĐ')

    def test_legacy_shared_fuel_prints_allocated_cost(self):
        fuel = self.fuel()
        other = Phoi(phoi_number='LEGACY-SHARED', driver_id=self.driver.id,
                     truck_id=self.truck.id, departure_date=date(2026, 11, 12), origin='B', destination='A')
        fuel.phois.append(other)
        db.session.commit()
        rows = TableRows(self.print_html()).rows
        fuel_row = next(row for row in rows if row[0].startswith('Dầu ('))
        self.assertIn('137.335 lít', fuel_row[0])
        self.assertIn('Phân bổ 1/2 chi phí', fuel_row[0])
        self.assertEqual(fuel_row[1], '1,373,350 VNĐ')
        self.assertEqual(self.phoi.fuel_expenses(), Decimal('1373350'))

    def test_zero_fuel_porter_and_fully_paid_debt(self):
        self.phoi.manager_revenue_collected = 3100000
        db.session.commit()
        html = self.print_html()
        rows = TableRows(html).rows
        for label in ('Công nợ còn lại', 'Tổng bồi dưỡng bốc vác', 'Dầu (0 lít)'):
            self.assertIn([label, '0 VNĐ'], rows)
        self.assertNotIn('Xăng (', html)

    def test_driver_print_keeps_financial_details_private(self):
        self.returns()
        self.fuel()
        html = self.print_html(self.driver)
        for label in ('Công nợ còn lại', 'Còn phải thu:', 'Lợi nhuận chủ xe',
                      'Doanh thu:', 'Quản lý/chủ xe đã thu', 'Tổng bồi dưỡng bốc vác', 'Dầu ('):
            self.assertNotIn(label, html)
        self.assertIn('ĐỐI CHIẾU THANH TOÁN', html)

    def test_create_and_detail_explain_that_returns_are_optional(self):
        for url in ('/phoi/create', f'/phoi/{self.phoi.id}'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('không bắt buộc'.encode(), response.data)
            self.assertNotIn('Ít nhất một chuyến về'.encode(), response.data)


if __name__ == '__main__':
    unittest.main()
