"""Financial aggregation, period boundaries and scope checks without a server."""
import calendar
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

os.environ['FLASK_ENV'] = 'testing'

from flask import g, template_rendered
from app import create_app, db
from app.models import ActivityLog, FuelLog, Phoi, PhoiExpense, PhoiReturnTrip, Truck, User


class TruckReportTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config.update(RATELIMIT_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.admin = self.user('admin', 'admin')
        self.a = self.user('manager-a', 'manager')
        self.b = self.user('manager-b', 'manager')
        self.driver = self.user('driver', 'driver')
        self.ta = Truck(license_plate='OWN-A', manager_id=self.a.id)
        self.tb = Truck(license_plate='FOREIGN-B', manager_id=self.b.id)
        self.retired = Truck(license_plate='RETIRED-A', manager_id=self.a.id, is_active=False)
        self.empty = Truck(license_plate='EMPTY-A', manager_id=self.a.id)
        self.unassigned = Truck(license_plate='UNASSIGNED')
        db.session.add_all([self.ta, self.tb, self.retired, self.empty, self.unassigned])
        db.session.flush()
        self.october = self.phoi('OCT', self.ta, date(2026, 10, 31), '10000000.75', '500000')
        self.october.driver_advance = Decimal('800000')
        self.october.revenue_collected = Decimal('1000000')
        self.october.manager_revenue_collected = Decimal('2000000')
        db.session.add(PhoiReturnTrip(
            phoi=self.october, trip_order=1, return_date=date(2026, 11, 2),
            origin='B', destination='A', revenue_full=Decimal('3000000.25'),
            porter_fee=Decimal('60000'), revenue_collected=Decimal('100000'),
        ))
        for category, amount in [('toll_fee', '200000'), ('repair', '150000'),
                                 ('other', '30000'), ('porter_fee', '40000')]:
            db.session.add(PhoiExpense(phoi=self.october, category=category, amount=Decimal(amount)))
        self.november = self.phoi('NOV', self.ta, date(2026, 11, 1), '2000000', '3000000')
        self.retired_phoi = self.phoi('OLD', self.retired, date(2026, 11, 5), '1000000')
        self.foreign = self.phoi('FOREIGN', self.tb, date(2026, 11, 1), '99000000')
        self.legacy = self.phoi('LEGACY', self.unassigned, date(2026, 11, 1), '88000000')
        self.draft = self.phoi('DRAFT', self.ta, date(2026, 11, 1), '77000000', status='draft')
        self.phoi('SUBMITTED', self.ta, date(2026, 11, 1), '66000000', status='submitted')
        self.phoi('CANCELLED', self.ta, date(2026, 11, 1), '55000000', status='cancelled')
        self.fuel('2453062.50', [self.october], 'driver')
        self.shared_fuel = self.fuel('600000', [self.october, self.november, self.draft])
        self.fuel('999999', [])  # Unlinked fuel is not an expense of a confirmed phơi.
        db.session.commit()
        self.login(self.a)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def user(self, username, role):
        user = User(username=username, full_name=username, role=role, password_hash='unused')
        db.session.add(user)
        db.session.flush()
        return user

    def phoi(self, number, truck, day, revenue, wage='0', status='confirmed'):
        phoi = Phoi(phoi_number=number, truck=truck, driver_id=self.driver.id,
                    departure_date=day, origin='A', destination='B', status=status,
                    revenue_full=Decimal(revenue), driver_wage=Decimal(wage))
        db.session.add(phoi)
        db.session.flush()
        return phoi

    def fuel(self, cost, phois, payer='owner'):
        fuel = FuelLog(truck_id=self.ta.id, liters=Decimal('100.125'),
                       price_per_liter=Decimal('24500'), total_cost=Decimal(cost),
                       paid_by=payer, refuel_date=date(2026, 9, 30),
                       phois=phois, allocation_status='allocated' if phois else 'unallocated')
        db.session.add(fuel)
        db.session.flush()
        return fuel

    def login(self, actor):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session.clear()
            if actor:
                session['_user_id'] = str(actor.id)
                session['_fresh'] = True

    def render(self, query='mode=month&month=2026-10', status=200):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get('/reports?' + query)
        self.assertEqual(response.status_code, status, response.get_data(as_text=True)[:500])
        return contexts[-1], response

    def test_month_totals_use_models_and_include_return_trip_in_departure_month(self):
        ctx, response = self.render()
        totals = ctx['report']['totals']
        self.assertEqual(totals['phoi_count'], 1)
        self.assertEqual(totals['revenue'], Decimal('13000001.00'))
        self.assertEqual(totals['fuel'], Decimal('2653062.50'))
        self.assertEqual(totals['other_expenses'], Decimal('480000'))
        self.assertEqual(totals['expenses'], Decimal('3633062.50'))
        self.assertEqual(totals['wages'], Decimal('500000'))
        self.assertEqual(totals['profit'], self.october.owner_profit())
        self.assertEqual(totals['revenue'], self.october.total_revenue_full())
        self.assertEqual(totals['expenses'], self.october.total_expenses() + self.october.driver_wage)
        self.assertEqual(ctx['period_label'], '01/10/2026 – 31/10/2026')
        self.assertIn(b'<svg', response.data)
        self.assertIn('Chi tiết theo xe và tháng'.encode(), response.data)

    def test_inclusive_range_aggregates_consistently_across_all_views(self):
        ctx, _ = self.render('mode=range&start_date=2026-10-31&end_date=2026-11-01')
        report = ctx['report']
        self.assertEqual(report['totals']['phoi_count'], 2)
        for metric in ('revenue', 'expenses', 'fuel', 'profit', 'wages', 'other_expenses'):
            expected = report['totals'][metric]
            for group in ('truck_rows', 'monthly_rows', 'detail_rows'):
                self.assertEqual(sum(row[metric] for row in report[group]), expected)
        self.assertEqual(report['totals']['profit'], self.october.owner_profit() + self.november.owner_profit())
        self.assertEqual([row['label'] for row in report['monthly_rows']], ['10/2026', '11/2026'])

    def test_one_day_range_and_negative_profit(self):
        ctx, response = self.render(f'mode=range&start_date=2026-11-01&end_date=2026-11-01&truck_id={self.ta.id}')
        self.assertEqual(ctx['report']['totals']['phoi_count'], 1)
        self.assertEqual(ctx['report']['totals']['profit'], Decimal('-1200000'))
        self.assertIn(b'-1,200,000', response.data)

    def test_fuel_shared_with_out_of_range_and_draft_keeps_original_denominator(self):
        ctx, _ = self.render(f'mode=month&month=2026-11&truck_id={self.ta.id}')
        self.assertEqual(self.shared_fuel.attached_phoi_count(), 3)
        self.assertEqual(ctx['report']['totals']['fuel'], Decimal('200000'))
        self.assertEqual(ctx['report']['totals']['phoi_count'], 1)

    def test_months_without_trips_are_zero_filled_including_year_boundary(self):
        ctx, _ = self.render('mode=range&start_date=2026-10-01&end_date=2027-02-28')
        months = ctx['report']['monthly_rows']
        self.assertEqual([row['month'] for row in months],
                         ['2026-10', '2026-11', '2026-12', '2027-01', '2027-02'])
        self.assertTrue(all(row['revenue'] == row['expenses'] == row['phoi_count'] == 0
                            for row in months[2:]))

    def test_historical_inactive_truck_is_included_and_filterable(self):
        ctx, response = self.render('mode=month&month=2026-11')
        self.assertEqual(ctx['report']['totals']['phoi_count'], 2)
        self.assertIn(b'RETIRED-A', response.data)
        ctx, _ = self.render(f'mode=month&month=2026-11&truck_id={self.retired.id}')
        self.assertEqual(ctx['report']['totals']['revenue'], Decimal('1000000'))
        self.assertEqual(len(ctx['report']['truck_rows']), 1)

    def test_manager_scope_filters_dropdown_charts_and_details(self):
        _, response = self.render('mode=month&month=2026-11')
        for hidden in (b'FOREIGN-B', b'UNASSIGNED', b'99,000,000', b'88,000,000'):
            self.assertNotIn(hidden, response.data)
        for truck_id in (self.tb.id, self.unassigned.id, 999999):
            self.assertEqual(self.client.get(f'/reports?truck_id={truck_id}').status_code, 404)

    def test_admin_can_view_all_and_select_foreign_truck(self):
        self.login(self.admin)
        ctx, response = self.render('mode=month&month=2026-11')
        self.assertEqual(ctx['report']['totals']['phoi_count'], 4)
        self.assertEqual(ctx['report']['totals']['revenue'], Decimal('190000000'))
        self.assertIn(b'FOREIGN-B', response.data)
        ctx, _ = self.render(f'mode=month&month=2026-11&truck_id={self.tb.id}')
        self.assertEqual(ctx['report']['totals']['revenue'], Decimal('99000000'))

    def test_authentication_driver_and_inactive_account_are_denied(self):
        self.login(None)
        self.assertEqual(self.client.get('/reports').status_code, 302)
        self.login(self.driver)
        self.assertEqual(self.client.get('/reports').status_code, 403)
        self.assertNotIn(b'href="/reports"', self.client.get('/phoi').data)
        self.a.is_active = False
        db.session.commit()
        self.login(self.a)
        self.assertEqual(self.client.get('/reports').status_code, 403)

    def test_invalid_dates_are_rejected_without_showing_unfiltered_totals(self):
        queries = [
            'month=', 'month=2026-13', 'month=2026-1', 'month=0000-01', 'month=abcd-ef',
            'mode=range&start_date=&end_date=2026-11-01',
            'mode=range&start_date=2026-11-01&end_date=',
            'mode=range&start_date=2026-02-29&end_date=2026-03-01',
            'mode=range&start_date=2026-11-02&end_date=2026-11-01',
            'mode=range&start_date=2026-1-01&end_date=2026-11-01',
            'mode=range&start_date=2026-01-01&end_date=2036-01-01',
            'mode=other',
        ]
        for query in queries:
            with self.subTest(query=query):
                ctx, response = self.render(query, status=400)
                self.assertIsNone(ctx['report'])
                self.assertTrue(ctx['error'])
                self.assertNotIn(b'<svg', response.data)

    def test_invalid_truck_ids_do_not_silently_remove_filter(self):
        for identity in ('abc', '-1', '0', '1.5', '999999999999999', '%EF%BC%91'):
            with self.subTest(identity=identity):
                self.assertIn(self.client.get('/reports?truck_id=' + identity).status_code, (400, 404))

    def test_empty_period_empty_truck_and_empty_manager_render_zero_totals(self):
        queries = ['mode=month&month=2025-01', f'month=2026-11&truck_id={self.empty.id}']
        for query in queries:
            ctx, response = self.render(query)
            self.assertEqual(ctx['report']['totals']['phoi_count'], 0)
            self.assertEqual(ctx['report']['totals']['expenses'], 0)
            self.assertIn('Chưa có phơi đã xác nhận'.encode(), response.data)
            self.assertNotIn(b'<svg', response.data)
        self.login(self.user('empty-manager', 'manager'))
        ctx, _ = self.render()
        self.assertEqual(ctx['trucks'], [])
        self.assertEqual(ctx['report']['totals']['phoi_count'], 0)

    def test_default_month_uses_vietnam_time_and_leap_and_last_year_are_valid(self):
        local_now = datetime(2026, 12, 1, 0, 30, tzinfo=timezone(timedelta(hours=7)))
        with patch('app.routes.reports.datetime') as mocked:
            mocked.now.return_value = local_now
            ctx, _ = self.render('')
            self.assertEqual(ctx['month'], '2026-12')
            self.assertEqual(ctx['period_label'], '01/12/2026 – 31/12/2026')
            mocked.now.assert_called_once_with(timezone(timedelta(hours=7)))
        for month in ('2024-02', '9999-12'):
            ctx, _ = self.render('month=' + month)
            year, number = map(int, month.split('-'))
            self.assertTrue(ctx['period_label'].endswith(f'{calendar.monthrange(year, number)[1]:02d}/{number:02d}/{year}'))

    def test_reports_are_read_only_and_navigation_is_available(self):
        before = (Phoi.query.count(), FuelLog.query.count(), ActivityLog.query.count(),
                  self.october.balance(), self.october.owner_profit(), self.october.driver_advance)
        for query in ('month=2026-10', 'month=2026-11', 'month=bad'):
            self.client.get('/reports?' + query)
        after = (Phoi.query.count(), FuelLog.query.count(), ActivityLog.query.count(),
                 self.october.balance(), self.october.owner_profit(), self.october.driver_advance)
        self.assertEqual(before, after)
        self.assertIn(b'href="/reports"', self.client.get('/phoi').data)
        self.assertEqual(self.client.post('/reports').status_code, 405)  # Read-only endpoint.

    def test_zero_value_confirmed_phoi_has_finite_chart_geometry(self):
        self.phoi('ZERO', self.empty, date(2026, 9, 1), '0')
        db.session.commit()
        ctx, response = self.render(f'month=2026-09&truck_id={self.empty.id}')
        self.assertEqual(ctx['report']['totals']['phoi_count'], 1)
        self.assertIn(b'<svg', response.data)
        self.assertIn(b'height="0.00"', response.data)
        self.assertNotIn(b'NaN', response.data)
        self.assertNotIn(b'Infinity', response.data)

    def test_admin_manager_filter_limits_all_report_groups(self):
        self.login(self.admin)
        ctx, response = self.render(f'month=2026-11&manager_id={self.a.id}')
        report = ctx['report']
        self.assertEqual(ctx['selected_manager'].id, self.a.id)
        self.assertEqual({truck.id for truck in ctx['trucks']}, {self.ta.id, self.retired.id, self.empty.id})
        self.assertEqual(report['totals']['revenue'], Decimal('3000000'))
        self.assertEqual(report['totals']['phoi_count'], 2)
        self.assertEqual(report['totals']['profit'], self.november.owner_profit() + self.retired_phoi.owner_profit())
        self.assertEqual({row['truck'].id for row in report['truck_rows']}, {self.ta.id, self.retired.id, self.empty.id})
        self.assertEqual({row['truck'].id for row in report['detail_rows']}, {self.ta.id, self.retired.id})
        for metric in ('revenue', 'expenses', 'fuel', 'profit'):
            for group in ('truck_rows', 'monthly_rows', 'detail_rows'):
                self.assertEqual(sum(row[metric] for row in report[group]), report['totals'][metric])
        self.assertIn('Quản lý: manager-a'.encode(), response.data)

    def test_manager_filter_combines_with_truck_and_custom_period(self):
        self.login(self.admin)
        query = (f'manager_id={self.a.id}&truck_id={self.ta.id}'
                 '&mode=range&start_date=2026-10-31&end_date=2026-11-01')
        ctx, response = self.render(query)
        self.assertEqual(ctx['report']['totals']['phoi_count'], 2)
        self.assertEqual(ctx['report']['totals']['revenue'], Decimal('15000001'))
        self.assertEqual(ctx['filter_manager_id'], str(self.a.id))
        self.assertEqual(ctx['filter_truck_id'], self.ta.id)
        self.assertIn(f'value="{self.a.id}" selected'.encode(), response.data)
        self.assertEqual(ctx['start_date'], '2026-10-31')
        self.assertEqual(ctx['end_date'], '2026-11-01')
        for manager, truck in ((self.a.id, self.tb.id), (self.b.id, self.ta.id), ('unassigned', self.ta.id)):
            with self.subTest(manager=manager, truck=truck):
                self.assertEqual(self.client.get(f'/reports?manager_id={manager}&truck_id={truck}').status_code, 404)

    def test_admin_can_filter_unassigned_trucks(self):
        self.login(self.admin)
        ctx, response = self.render('month=2026-11&manager_id=unassigned')
        self.assertEqual([truck.id for truck in ctx['trucks']], [self.unassigned.id])
        self.assertEqual(ctx['report']['totals']['revenue'], Decimal('88000000'))
        self.assertEqual(ctx['report']['totals']['phoi_count'], 1)
        self.assertIn('Xe chưa phân công quản lý'.encode(), response.data)

    def test_admin_keeps_inactive_managers_and_historical_trucks_filterable(self):
        self.a.is_active = False
        db.session.commit()
        self.login(self.admin)
        ctx, response = self.render(f'month=2026-11&manager_id={self.a.id}&truck_id={self.retired.id}')
        self.assertIn(self.a, ctx['managers'])
        self.assertEqual(ctx['report']['totals']['revenue'], Decimal('1000000'))
        self.assertIn('— đã khóa'.encode(), response.data)

    def test_manager_cannot_expand_scope_with_manager_filter(self):
        ctx, response = self.render(f'month=2026-11&manager_id={self.a.id}')
        self.assertEqual(ctx['report']['totals']['revenue'], Decimal('3000000'))
        self.assertNotIn(b'name="manager_id"', response.data)
        self.assertEqual(ctx['managers'], [])
        for identity in (self.b.id, self.admin.id, 'unassigned', '999999'):
            with self.subTest(manager=identity):
                self.assertEqual(self.client.get(f'/reports?manager_id={identity}').status_code, 403)
        _, response = self.render('month=2026-11&manager_id=')
        self.assertNotIn(b'FOREIGN-B', response.data)

    def test_invalid_manager_ids_do_not_remove_filter(self):
        self.login(self.admin)
        for identity in ('abc', '-1', '1.5', '999999999999999', '%EF%BC%91'):
            with self.subTest(manager=identity):
                self.assertEqual(self.client.get('/reports?manager_id=' + identity).status_code, 400)
        for identity in (0, 999999, self.admin.id, self.driver.id):
            with self.subTest(manager=identity):
                self.assertEqual(self.client.get(f'/reports?manager_id={identity}').status_code, 404)

    def test_manager_filter_empty_and_date_error_keep_selection(self):
        empty_manager = self.user('no-trucks', 'manager')
        db.session.commit()
        self.login(self.admin)
        ctx, response = self.render(f'month=2026-11&manager_id={empty_manager.id}')
        self.assertEqual(ctx['trucks'], [])
        self.assertEqual(ctx['report']['totals']['phoi_count'], 0)
        self.assertIn('Chưa có phơi đã xác nhận'.encode(), response.data)
        ctx, _ = self.render(f'month=invalid&manager_id={self.a.id}', status=400)
        self.assertEqual(ctx['selected_manager'].id, self.a.id)
        self.assertIsNone(ctx['report'])

    def test_manager_filter_follows_current_assignment_without_rewriting_history(self):
        before = self.october.owner_profit(), self.october.balance()
        self.ta.manager_id = self.b.id
        db.session.commit()
        self.login(self.admin)
        ctx, _ = self.render(f'month=2026-10&manager_id={self.a.id}')
        self.assertEqual(ctx['report']['totals']['phoi_count'], 0)
        ctx, _ = self.render(f'month=2026-10&manager_id={self.b.id}')
        self.assertEqual(ctx['report']['totals']['revenue'], self.october.total_revenue_full())
        self.assertEqual(before, (self.october.owner_profit(), self.october.balance()))
        self.assertEqual(self.ta.manager_id, self.b.id)


if __name__ == '__main__':
    unittest.main()
