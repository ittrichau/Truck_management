"""Manager planning, isolated phơi synchronization and reconciliation boundaries."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from alembic.config import Config
from alembic.script import ScriptDirectory
from flask import g, template_rendered
from flask_migrate import upgrade, downgrade
from sqlalchemy import inspect, text

from app import create_app, db
from app.models import Customer, FuelLog, Phoi, PhoiReturnTrip, Truck, User
from app.trip_planning import TripPlan, TripPlanHistory, actual_from_phoi, sync_after_phoi_commit
from config import TestingConfig


MIGRATIONS = str(Path(__file__).resolve().parents[1] / 'migrations')


class TripPlanningTests(unittest.TestCase):
    def setUp(self):
        with patch('app.get_config', return_value=TestingConfig):
            self.app = create_app('testing')
        self.app.config.update(RATELIMIT_ENABLED=False)
        self.context = self.app.app_context()
        self.context.push()
        self.assertEqual(str(db.engine.url), 'sqlite:///:memory:')
        db.create_all()
        self.manager = self.user('manager', 'manager')
        self.other = self.user('other', 'manager')
        self.admin = self.user('admin', 'admin')
        self.accountant = self.user('accountant', 'accountant', self.manager)
        self.driver = self.user('driver', 'driver', self.manager)
        self.other_driver = self.user('other-driver', 'driver', self.other)
        self.truck = Truck(license_plate='OWN-TRUCK', manager_id=self.manager.id)
        self.other_truck = Truck(license_plate='FOREIGN-TRUCK', manager_id=self.other.id)
        self.customer = Customer(name='Hàng B', managers=[self.manager])
        self.return_customer = Customer(name='Hàng C', managers=[self.manager])
        self.foreign_customer = Customer(name='Khách riêng', managers=[self.other])
        db.session.add_all([self.truck, self.other_truck, self.customer, self.return_customer, self.foreign_customer])
        db.session.flush()
        self.driver.current_truck_id = self.truck.id
        self.other_driver.current_truck_id = self.other_truck.id
        db.session.commit()
        self.client = self.app.test_client()
        self.login(self.manager)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def user(self, username, role, manager=None):
        user = User(username=username, full_name=username, role=role, password_hash='unused',
                    manager_id=manager.id if manager else None)
        db.session.add(user)
        db.session.flush()
        return user

    def login(self, actor):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session.clear()
            if actor:
                session['_user_id'] = str(actor.id)
                session['_fresh'] = True

    def form(self, **changes):
        data = dict(truck_id=str(self.truck.id), driver_id=str(self.driver.id),
                    customer_id=str(self.customer.id), departure_date='2026-12-11',
                    return_date='2026-12-13', origin='A', destination='B',
                    cargo_description='Hàng', return_load_status='unknown')
        data.update(changes)
        return data

    def plan(self, **changes):
        response = self.client.post('/planning/create', data=self.form(**changes))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        return TripPlan.query.order_by(TripPlan.id.desc()).first()

    def phoi(self, day=12, truck=None, driver=None, status='draft', fuel=True, **changes):
        data = dict(phoi_number=f'PLAN-PHOI-{Phoi.query.count()+1}', truck_id=(truck or self.truck).id,
                    driver_id=(driver or self.driver).id, customer_id=self.customer.id,
                    departure_date=date(2026, 12, day), return_date=date(2026, 12, 15),
                    origin='A', destination='B', cargo_description='Hàng', km_end=500,
                    km_total=500, status=status, revenue_full=Decimal('1000000'),
                    revenue_collected=Decimal('100000'), driver_wage=Decimal('200000'))
        data.update(changes)
        phoi = Phoi(**data)
        db.session.add(phoi)
        db.session.flush()
        if fuel:
            db.session.add(FuelLog(truck_id=phoi.truck_id, refuel_date=date(2026, 12, day),
                                   liters=Decimal('10.125'), price_per_liter=20000,
                                   total_cost=Decimal('202500'), paid_by='owner', phois=[phoi]))
        db.session.commit()
        return phoi

    def submit(self, phoi):
        self.login(self.driver)
        response = self.client.post(f'/phoi/{phoi.id}/submit')
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        self.login(self.manager)
        return response

    def action(self, plan, action, **data):
        if action in ('accept', 'review') and 'actual_signature' not in data:
            actual = actual_from_phoi(plan.phoi) if plan.phoi else None
            data['actual_signature'] = plan.signature(db.session, actual)
        data.update(version=str(plan.version), action=action)
        response = self.client.post(f'/planning/{plan.id}/action', data=data)
        db.session.expire_all()
        return response

    def render(self, query='start_date=2026-12-01&end_date=2026-12-31'):
        contexts = []
        def capture(sender, template, context, **kwargs):
            contexts.append(context)
        template_rendered.connect(capture, self.app)
        try:
            response = self.client.get('/planning?' + query)
        finally:
            template_rendered.disconnect(capture, self.app)
        return response, contexts[-1] if contexts else None

    def test_create_edit_and_history_never_create_or_change_phoi_or_assignment(self):
        plan = self.plan()
        original = plan.original_data.copy()
        self.assertEqual(Phoi.query.count(), 0)
        form = self.form(departure_date='2026-12-12', version=str(plan.version), reason='Khách dời ngày')
        self.assertEqual(self.client.post(f'/planning/{plan.id}/edit', data=form).status_code, 302)
        self.assertEqual(plan.departure_date, date(2026, 12, 12))
        self.assertEqual(plan.original_data, original)
        self.assertEqual(TripPlanHistory.query.filter_by(plan_id=plan.id).count(), 2)
        self.assertEqual(self.driver.current_truck_id, self.truck.id)
        self.assertEqual(self.truck.status, 'available')
        self.assertEqual(Phoi.query.count(), 0)
        self.assertEqual(self.client.get(f'/planning/{plan.id}').status_code, 200)
        self.assertEqual(self.client.get(f'/planning/{plan.id}/edit').status_code, 200)

    def test_default_index_renders_before_any_plan_exists_for_manager_and_admin(self):
        for actor in (self.manager, self.admin):
            with self.subTest(role=actor.role):
                self.login(actor)
                response, context = self.render('')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(context['rows'], [])
                self.assertEqual(context['outside'], [])
                self.assertIn('Chưa có kế hoạch phù hợp', response.get_data(as_text=True))

    def test_submit_auto_links_and_records_differences_without_changing_finances(self):
        plan = self.plan()
        phoi = self.phoi()
        before = (phoi.balance(), phoi.owner_profit(), phoi.total_revenue_full(), phoi.fuel_logs[0].id)
        self.submit(phoi)
        self.assertEqual(phoi.status, 'submitted')
        self.assertEqual(plan.phoi_id, phoi.id)
        self.assertEqual(plan.actual_data['departure_date'], '2026-12-12')
        self.assertEqual(plan.departure_date, date(2026, 12, 11))
        self.assertEqual({row['field'] for row in plan.differences(db.session)}, {'departure_date', 'return_date'})
        self.assertEqual(plan.status(db.session)[0], 'review')
        self.assertEqual(before, (phoi.balance(), phoi.owner_profit(), phoi.total_revenue_full(), phoi.fuel_logs[0].id))
        self.assertIn('Các thông tin khác biệt', self.client.get(f'/planning/{plan.id}').get_data(as_text=True))

    def test_draft_preview_does_not_write_or_link_and_is_not_reviewable(self):
        plan = self.plan()
        phoi = self.phoi()
        count = TripPlanHistory.query.count()
        response, context = self.render()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(context['rows'][0]['phoi'].id, phoi.id)
        self.assertIsNone(plan.phoi_id)
        self.assertIsNone(plan.actual_data)
        self.assertEqual(count, TripPlanHistory.query.count())
        self.action(plan, 'accept', reason='Chưa chốt')
        self.assertEqual(plan.departure_date, date(2026, 12, 11))

    def test_accept_updates_only_plan_and_preserves_original_and_reason(self):
        plan = self.plan()
        phoi = self.phoi()
        self.submit(phoi)
        before = actual_from_phoi(phoi), phoi.balance(), phoi.owner_profit()
        self.action(plan, 'accept', reason='Khách dời ngày')
        self.assertEqual(plan.departure_date, date(2026, 12, 12))
        self.assertEqual(plan.return_date, date(2026, 12, 15))
        self.assertEqual(plan.original_data['departure_date'], '2026-12-11')
        self.assertEqual(plan.status(db.session)[0], 'matched')
        self.assertEqual(before, (actual_from_phoi(phoi), phoi.balance(), phoi.owner_profit()))
        self.assertEqual(plan.history[0].action, 'accept')
        self.assertEqual(plan.history[0].reason, 'Khách dời ngày')

    def test_review_keeps_plan_and_new_phoi_edit_reopens_review(self):
        plan = self.plan()
        phoi = self.phoi()
        self.submit(phoi)
        self.action(plan, 'review', reason='Đã kiểm tra với khách')
        self.assertEqual(plan.status(db.session)[0], 'reviewed')
        self.assertEqual(plan.departure_date, date(2026, 12, 11))
        phoi.return_date = date(2026, 12, 16)
        db.session.commit()
        sync_after_phoi_commit(phoi.id, self.manager.id)
        db.session.expire_all()
        self.assertEqual(plan.actual_data['return_date'], '2026-12-16')
        self.assertEqual(plan.status(db.session)[0], 'review')

    def test_ambiguous_matching_in_both_directions_requires_manual_link(self):
        first = self.plan()
        second = self.plan(departure_date='2026-12-12')
        phoi = self.phoi()
        self.submit(phoi)
        self.assertIsNone(first.phoi_id)
        self.assertIsNone(second.phoi_id)
        self.action(first, 'link', phoi_id=str(phoi.id), reason='Chọn đúng kế hoạch')
        self.assertEqual(first.phoi_id, phoi.id)
        self.action(second, 'link', phoi_id=str(phoi.id), reason='Thử ghép trùng')
        self.assertIsNone(second.phoi_id)

    def test_multiple_phois_and_large_date_shift_do_not_auto_match(self):
        plan = self.plan()
        first = self.phoi(day=11)
        self.phoi(day=12)
        self.submit(first)
        self.assertIsNone(plan.phoi_id)
        self.assertEqual(self.client.get(f'/planning/{plan.id}').status_code, 200)
        # Manual links permit a date shift beyond the automatic seven-day window.
        distant = self.phoi(day=25, status='submitted')
        self.action(plan, 'link', phoi_id=str(distant.id), reason='Khách dời nhiều ngày')
        self.assertEqual(plan.phoi_id, distant.id)
        self.assertIn('departure_date', [item['field'] for item in plan.differences(db.session)])

    def test_sync_failure_does_not_prevent_driver_submission(self):
        self.plan()
        phoi = self.phoi()
        with patch('app.trip_planning.sync_phoi', side_effect=RuntimeError('planning unavailable')):
            self.submit(phoi)
        self.assertEqual(phoi.status, 'submitted')
        self.assertEqual(len(phoi.fuel_logs), 1)

    def test_existing_fuel_and_km_submission_requirements_are_preserved(self):
        plan = self.plan()
        phoi = self.phoi(fuel=False)
        self.submit(phoi)
        self.assertEqual(phoi.status, 'draft')
        self.assertIsNone(plan.actual_data)
        fuel = FuelLog(truck_id=self.truck.id, refuel_date=date(2026, 12, 12), liters=10,
                       price_per_liter=20000, total_cost=200000, phois=[phoi])
        db.session.add(fuel)
        phoi.km_end = 0
        db.session.commit()
        self.submit(phoi)
        self.assertEqual(phoi.status, 'draft')
        self.assertIsNone(plan.phoi_id)

    def test_roles_and_scope_apply_to_every_endpoint_and_navigation(self):
        plan = self.plan()
        paths = ('/planning', '/planning/create', f'/planning/{plan.id}', f'/planning/{plan.id}/edit')
        for actor in (self.driver, self.accountant):
            self.login(actor)
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 403)
                self.assertIn(self.client.post(path).status_code, (403, 405))
            self.assertEqual(self.client.post(f'/planning/{plan.id}/action', data={'action': 'cancel'}).status_code, 403)
            self.assertNotIn(b'href="/planning"', self.client.get('/phoi').data)
        self.login(self.other)
        for path in (f'/planning/{plan.id}', f'/planning/{plan.id}/edit', f'/planning/{plan.id}/action'):
            self.assertIn(self.client.post(path).status_code, (404, 405))
        self.assertEqual(self.client.get(f'/planning/{plan.id}').status_code, 404)
        self.assertNotIn(b'OWN-TRUCK', self.render()[0].data)
        self.login(self.admin)
        self.assertEqual(self.client.get(f'/planning/{plan.id}').status_code, 200)
        self.assertIn(b'href="/planning"', self.client.get('/phoi').data)
        self.login(None)
        self.assertEqual(self.client.get('/planning').status_code, 302)

    def test_foreign_choices_and_phoi_cannot_be_injected(self):
        for changes in ({'truck_id': str(self.other_truck.id)}, {'driver_id': str(self.other_driver.id)},
                        {'customer_id': str(self.foreign_customer.id)}):
            self.assertEqual(self.client.post('/planning/create', data=self.form(**changes)).status_code, 400)
        self.assertEqual(TripPlan.query.count(), 0)
        plan = self.plan()
        foreign = self.phoi(truck=self.other_truck, driver=self.other_driver)
        response = self.action(plan, 'link', phoi_id=str(foreign.id), reason='Không được phép')
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(plan.phoi_id)

    def test_invalid_forms_are_atomic_and_keep_entered_values(self):
        for changes in ({'departure_date': '2026-02-30'}, {'departure_date': '20261211'},
                        {'return_date': '2026-12-10'}, {'truck_id': 'abc'},
                        {'origin': ''}, {'return_load_status': 'bad'},
                        {'return_load_status': 'loaded'}, {'notes': 'x' * 2001}):
            with self.subTest(changes=changes):
                response = self.client.post('/planning/create', data=self.form(**changes))
                self.assertEqual(response.status_code, 400)
                self.assertIn('Hàng B', response.get_data(as_text=True))
                self.assertEqual(TripPlan.query.count(), 0)
                self.assertEqual(TripPlanHistory.query.count(), 0)

    def test_multiple_return_legs_compare_and_accept_without_losing_original(self):
        values = dict(return_load_status='loaded', **{
            'return_customer_id[]': [str(self.return_customer.id), str(self.customer.id)],
            'return_return_date[]': ['2026-12-12', '2026-12-13'],
            'return_origin[]': ['B', 'C'], 'return_destination[]': ['C', 'A'],
            'return_cargo_description[]': ['Gạo', 'Bắp'],
        })
        plan = self.plan(**values)
        phoi = self.phoi()
        for index, (origin, dest) in enumerate((('B', 'C'), ('C', 'A'))):
            db.session.add(PhoiReturnTrip(phoi_id=phoi.id, customer_id=self.return_customer.id,
                trip_order=index + 1, origin=origin, destination=dest,
                return_date=date(2026, 12, 13 + index), cargo_description='Gạo'))
        db.session.commit()
        self.submit(phoi)
        self.assertIn('return_trips', [item['field'] for item in plan.differences(db.session)])
        self.action(plan, 'accept', reason='Cập nhật hàng về')
        self.assertEqual(len(plan.return_trips), 2)
        self.assertEqual(plan.return_trips[1]['customer_id'], self.return_customer.id)
        self.assertEqual(plan.original_data['return_trips'][1]['customer_id'], self.customer.id)
        self.assertEqual(phoi.return_trips.count(), 2)

    def test_stale_version_and_missing_reason_do_not_change_plan_or_history(self):
        plan = self.plan()
        before = plan.audit_data(db.session), TripPlanHistory.query.count()
        self.client.post(f'/planning/{plan.id}/edit', data=self.form(version='999', reason='Cũ'))
        self.action(plan, 'cancel', reason='')
        self.assertEqual(before, (plan.audit_data(db.session), TripPlanHistory.query.count()))

    def test_date_filter_includes_crossing_trips_and_return_customer_and_rejects_bad_filters(self):
        plan = self.plan(return_date='2027-01-02')
        response, context = self.render('start_date=2027-01-01&end_date=2027-01-03')
        self.assertEqual([row['plan'].id for row in context['rows']], [plan.id])
        for query in ('start_date=bad', 'start_date=2026-12-31&end_date=2026-12-01',
                      'start_date=2020-01-01&end_date=2026-12-31', 'truck_id=abc', 'status=bad'):
            self.assertEqual(self.render(query)[0].status_code, 400)
        self.assertEqual(self.render(f'truck_id={self.other_truck.id}')[0].status_code, 404)

    def test_gap_same_day_overlap_unknown_return_and_next_trip_outside_filter(self):
        first = self.plan()
        second = self.plan(departure_date='2026-12-13', return_date='2026-12-16')
        third = self.plan(departure_date='2026-12-15', return_date='2026-12-18')
        self.plan(departure_date='2026-12-20', return_date='')
        response, context = self.render()
        rows = {row['plan'].id: row for row in context['rows']}
        self.assertEqual(rows[first.id]['gap'], 0)
        self.assertFalse(rows[first.id]['warnings'])
        self.assertEqual(rows[second.id]['gap'], -1)
        self.assertTrue(rows[third.id]['warnings'])
        self.assertEqual(rows[third.id]['gap'], 2)
        self.assertIsNone(context['rows'][-1]['gap'])

    def test_cancel_plan_keeps_phoi_unchanged_and_cancel_phoi_marks_discrepancy(self):
        plan = self.plan()
        phoi = self.phoi()
        self.action(plan, 'link', phoi_id=str(phoi.id), reason='Đã giao xe')
        self.client.post(f'/phoi/{phoi.id}/cancel', data={'cancellation_reason': 'Khách hủy'})
        db.session.expire_all()
        self.assertTrue(plan.actual_data['cancelled'])
        self.assertIn('cancelled', [item['field'] for item in plan.differences(db.session)])
        self.action(plan, 'cancel', reason='Hủy theo khách')
        self.assertTrue(plan.is_cancelled)
        self.assertEqual(phoi.status, 'cancelled')

    def test_ownership_transfer_hides_plan_and_prevents_cross_manager_sync(self):
        plan = self.plan()
        phoi = self.phoi()
        self.submit(phoi)
        previous = plan.actual_data.copy()
        self.truck.manager_id = self.other.id
        phoi.return_date = date(2026, 12, 17)
        db.session.commit()
        sync_after_phoi_commit(phoi.id)
        db.session.expire_all()
        self.assertEqual(plan.actual_data, previous)
        self.assertEqual(self.client.get(f'/planning/{plan.id}').status_code, 404)
        self.login(self.other)
        self.assertEqual(self.client.get(f'/planning/{plan.id}').status_code, 404)

    def test_repeated_sync_is_idempotent_and_sync_action_recovers_failed_auto_sync(self):
        plan = self.plan()
        phoi = self.phoi(status='submitted')
        self.action(plan, 'sync')
        self.assertEqual(plan.phoi_id, phoi.id)
        count = TripPlanHistory.query.count()
        self.action(plan, 'sync')
        self.assertEqual(TripPlanHistory.query.count(), count)

    def test_csrf_is_required_for_planning_writes(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post('/planning/create', data=self.form()).status_code, 400)
        self.assertEqual(TripPlan.query.count(), 0)

    def test_submitted_edit_route_syncs_and_reopens_review(self):
        plan = self.plan()
        phoi = self.phoi()
        self.submit(phoi)
        self.action(plan, 'review', reason='Đã kiểm tra')
        response = self.client.post(f'/phoi/{phoi.id}/edit', data={
            'truck_id': str(self.truck.id), 'driver_id': str(self.driver.id),
            'customer_id': str(self.customer.id), 'departure_date': '2026-12-12',
            'return_date': '2026-12-16', 'origin': 'A', 'destination': 'B',
            'cargo_description': 'Hàng', 'payment_method': 'fixed', 'revenue_full': '1000000',
            'revenue_collected': '100000', 'driver_wage': '200000', 'km_end': '500',
        })
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        self.assertEqual(plan.actual_data['return_date'], '2026-12-16')
        self.assertEqual(plan.status(db.session)[0], 'review')

    def test_stale_actual_is_rejected_even_if_auto_sync_previously_failed(self):
        plan = self.plan()
        phoi = self.phoi()
        self.submit(phoi)
        old_signature = plan.signature(db.session)
        phoi.return_date = date(2026, 12, 17)
        db.session.commit()
        self.action(plan, 'accept', reason='Không được chấp nhận dữ liệu chưa xem', actual_signature=old_signature)
        self.assertEqual(plan.return_date, date(2026, 12, 13))
        self.assertIsNone(plan.reviewed_signature)

    def test_create_plan_after_submitted_phoi_links_and_exact_dates_match(self):
        phoi = self.phoi(day=11, status='submitted', return_date=date(2026, 12, 13))
        plan = self.plan()
        self.assertEqual(plan.phoi_id, phoi.id)
        self.assertEqual(plan.status(db.session)[0], 'matched')

    def test_unknown_customer_never_auto_matches_and_empty_return_is_not_inferred(self):
        plan = self.plan(customer_id='', return_load_status='empty')
        phoi = self.phoi(customer_id=None)
        self.submit(phoi)
        self.assertIsNone(plan.phoi_id)
        self.action(plan, 'link', phoi_id=str(phoi.id), reason='Xác minh chuyến chưa có khách')
        self.assertEqual(plan.actual_data['return_load_status'], 'unknown')
        self.assertIn('chưa đủ để xác nhận xe về rỗng', self.client.get(f'/planning/{plan.id}').get_data(as_text=True))

    def test_pagination_filters_and_calendar_use_the_same_rows(self):
        for day in range(1, 32):
            self.plan(departure_date=f'2026-12-{day:02}', return_date=f'2026-12-{day:02}')
        response, context = self.render()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(context['total'], 31)
        self.assertEqual(len(context['rows']), 30)
        self.assertEqual(len(context['days']), 31)
        self.assertEqual(context['rows'][0]['bars'][0]['start'], 1)
        response, context = self.render('start_date=2026-12-01&end_date=2026-12-31&page=2')
        self.assertEqual(len(context['rows']), 1)
        self.assertEqual(context['rows'][0]['bars'][0]['start'], 31)

    def test_return_customer_filter_and_invalid_return_dates(self):
        returns = {
            'return_load_status': 'loaded', 'return_customer_id[]': [str(self.return_customer.id)],
            'return_return_date[]': ['2026-12-12'], 'return_origin[]': ['B'],
            'return_destination[]': ['A'], 'return_cargo_description[]': ['Gạo'],
        }
        plan = self.plan(**returns)
        _, context = self.render(f'start_date=2026-12-01&end_date=2026-12-31&customer_id={self.return_customer.id}')
        self.assertEqual([row['plan'].id for row in context['rows']], [plan.id])
        for day in ('2026-12-10', '2026-12-14', 'bad'):
            returns['return_return_date[]'] = [day]
            self.assertEqual(self.client.post('/planning/create', data=self.form(**returns)).status_code, 400)


class TripPlanningMigrationTests(unittest.TestCase):
    setUp = TripPlanningTests.setUp
    tearDown = TripPlanningTests.tearDown
    user = TripPlanningTests.user
    login = TripPlanningTests.login
    def test_migration_upgrade_downgrade_preserves_existing_business_data(self):
        db.session.remove()
        db.drop_all()
        upgrade(directory=MIGRATIONS, revision='c7e8f901a2b3')
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, full_name, password_hash, role) VALUES (1, 'legacy', 'Legacy', 'unused', 'manager')"))
            connection.execute(text("INSERT INTO trucks (id, license_plate, manager_id, is_active) VALUES (1, 'LEGACY', 1, 1)"))
        upgrade(directory=MIGRATIONS)
        self.assertIn('trip_plans', inspect(db.engine).get_table_names())
        self.assertEqual(db.session.get(Truck, 1).license_plate, 'LEGACY')
        db.session.remove()
        downgrade(directory=MIGRATIONS, revision='c7e8f901a2b3')
        self.assertNotIn('trip_plans', inspect(db.engine).get_table_names())
        self.assertEqual(db.session.get(Truck, 1).manager_id, 1)
        upgrade(directory=MIGRATIONS)
        config = Config()
        config.set_main_option('script_location', MIGRATIONS)
        self.assertEqual(ScriptDirectory.from_config(config).get_heads(), ['f1a2b3c4d5e6'])

    def test_migration_refuses_to_discard_saved_plans(self):
        db.session.remove()
        db.drop_all()
        upgrade(directory=MIGRATIONS)
        owner = self.user('migrated-manager', 'manager')
        truck = Truck(license_plate='KEEP', manager_id=owner.id)
        db.session.add(truck)
        db.session.flush()
        plan = TripPlan(manager_id=owner.id, truck_id=truck.id, departure_date=date(2026, 12, 11),
                        origin='A', destination='B', created_by_id=owner.id)
        db.session.add(plan)
        db.session.commit()
        db.session.remove()
        with self.assertRaises(SystemExit):
            downgrade(directory=MIGRATIONS, revision='c7e8f901a2b3')
        self.assertEqual(TripPlan.query.count(), 1)


if __name__ == '__main__':
    unittest.main()
