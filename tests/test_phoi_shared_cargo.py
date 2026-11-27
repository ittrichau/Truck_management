"""Shared customers across outbound/return trips, financial isolation and legacy compatibility."""
from decimal import Decimal
import json
import unittest

from flask import template_rendered

import test_trip_planning as fixtures
from app import db
from app.models import ActivityLog, Customer, FuelLog, Phoi, PhoiCargoItem
from app.routes.phoi import financial_confirmation_error
from app.trip_planning import actual_from_phoi
from app.truck_reports import build_truck_report


class SharedCargoTests(unittest.TestCase):
    tearDown = fixtures.TripPlanningTests.tearDown
    login = fixtures.TripPlanningTests.login
    user = fixtures.TripPlanningTests.user

    def setUp(self):
        fixtures.TripPlanningTests.setUp(self)
        self.third = Customer(name='Khách thứ ba', cargo_type='Bắp', managers=[self.manager])
        db.session.add(self.third)
        db.session.commit()

    def row(self, customer=None, **changes):
        data = dict(customer_id=str((customer or self.return_customer).id), cargo_description='Hàng ghép',
                    payment_method='fixed', revenue_full='500000', revenue_collected='100000')
        data.update(changes)
        return data

    def form(self, **changes):
        data = fixtures.TripPlanningTests.form(self, revenue_full='1000000', revenue_collected='50000',
                                               payment_method='fixed', km_end='500', driver_wage='200000')
        data.update(changes)
        return data

    def returning(self, rows=None, **changes):
        data = {
            'return_trip_customer_id[]': [str(self.customer.id)],
            'return_trip_date[]': ['2026-12-13'], 'return_trip_origin[]': ['B'],
            'return_trip_destination[]': ['A'], 'return_trip_cargo[]': ['Hàng về'],
            'return_trip_payment_method[]': ['fixed'], 'return_trip_revenue_full[]': ['700000'],
            'return_trip_revenue_collected[]': ['20000'], 'return_trip_porter_fee[]': ['30000'],
            'return_trip_cargo_items[]': [json.dumps(rows if rows is not None else [self.row()])],
        }
        data.update(changes)
        return data

    def create(self, rows=None, **changes):
        data = self.form(cargo_items=json.dumps(rows if rows is not None else [self.row()]))
        data.update(changes)
        response = self.client.post('/phoi/create', data=data)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        phoi = Phoi.query.order_by(Phoi.id.desc()).first()
        self.assertIsNotNone(phoi)
        return phoi

    def capture(self, path):
        contexts = []
        def receive(sender, template, context, **extra):
            contexts.append(context)
        template_rendered.connect(receive, self.app)
        try:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            return response.get_data(as_text=True), contexts[-1]
        finally:
            template_rendered.disconnect(receive, self.app)

    def confirm_form(self, phoi, **changes):
        data = dict(outbound_collection_status='unpaid', driver_wage='200000',
                    toll_fee_status='incurred', toll_fee_amount='100000')
        for row in phoi.cargo_items:
            data[f'cargo_collection_status_{row.id}'] = 'unpaid'
        data.update(changes)
        return data

    def ready(self, phoi):
        from datetime import date
        fuel = FuelLog(truck_id=phoi.truck_id, refuel_date=date(2026, 12, 11), liters=10,
                       price_per_liter=20000, total_cost=200000, paid_by='driver', phois=[phoi])
        db.session.add(fuel)
        phoi.status = 'submitted'
        db.session.commit()

    def test_three_customers_per_direction_recalculate_prices_and_preserve_trip_count(self):
        rows = [self.row(payment_method='per_ton', cargo_weight_tons='0.500', price_per_ton='300000', revenue_full='999999'),
                self.row(self.third, revenue_full='300000', revenue_collected='20000')]
        phoi = self.create(rows, **self.returning(rows))
        self.assertEqual(phoi.return_trips.count(), 1)
        self.assertEqual(phoi.cargo_items.count(), 4)
        self.assertEqual(phoi.trip_revenue_full(), 1450000)
        self.assertEqual(phoi.return_trips.first().trip_revenue_full(), 1150000)
        self.assertEqual(phoi.total_revenue_full(), 2600000)
        self.assertEqual(phoi.total_revenue_collected(), 310000)
        self.assertEqual(phoi.km_total, 500)
        self.assertEqual(phoi.driver_wage, 200000)
        self.assertEqual(phoi.total_expenses(), 30000)
        self.assertEqual(phoi.owner_profit(), 2370000)
        self.assertEqual(phoi.balance(), -80000)

    def test_server_rejects_fourth_customer_even_with_forged_payload(self):
        self.client.post('/phoi/create', data=self.form(cargo_items=json.dumps([self.row(), self.row(self.third), self.row()])))
        self.assertEqual(Phoi.query.count(), 0)

    def test_server_rejects_duplicate_primary_or_extra_customer_and_missing_primary(self):
        for primary, rows in ((self.customer.id, [self.row(self.customer)]),
                              (self.customer.id, [self.row(), self.row()]), ('', [self.row()])):
            with self.subTest(primary=primary, rows=rows):
                self.client.post('/phoi/create', data=self.form(customer_id=str(primary), cargo_items=json.dumps(rows)))
                self.assertEqual(Phoi.query.count(), 0)

    def test_foreign_inactive_or_missing_customer_is_rejected(self):
        for customer in (self.foreign_customer, self.third):
            if customer is self.third:
                customer.is_active = False
                db.session.commit()
            self.client.post('/phoi/create', data=self.form(cargo_items=json.dumps([self.row(customer)])))
            self.assertEqual(Phoi.query.count(), 0)

    def test_invalid_payload_and_nonfinite_negative_excessive_amounts_rollback(self):
        payloads = ['broken', '{}', '[null]']
        payloads += [json.dumps([self.row(revenue_full=amount)]) for amount in ('NaN', 'Infinity', '-1', '10000000000', 'abc')]
        payloads += [json.dumps([self.row(revenue_collected='600000')]), json.dumps([self.row(cargo_description='')])]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.client.post('/phoi/create', data=self.form(cargo_items=payload))
                self.assertEqual(Phoi.query.count(), 0)
                self.assertEqual(PhoiCargoItem.query.count(), 0)

    def test_invalid_return_duplicates_or_misaligned_arrays_rollback_entire_phoi(self):
        for changes in (self.returning([self.row(self.customer)]),
                        self.returning(**{'return_trip_cargo_items[]': ['[]', '[]']}),
                        self.returning(**{'return_trip_origin[]': [''], 'return_trip_destination[]': ['']})):
            self.client.post('/phoi/create', data=self.form(cargo_items=json.dumps([self.row()]), **changes))
            self.assertEqual(Phoi.query.count(), 0)

    def test_reorder_delete_and_legacy_omission_preserve_remaining_id_and_money(self):
        phoi = self.create([self.row(), self.row(self.third, revenue_full='300000')])
        rows = phoi.cargo_form_data()
        identities = [row['id'] for row in rows]
        self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(cargo_items=json.dumps(list(reversed(rows)))))
        self.assertEqual([str(row.id) for row in phoi.additional_cargo()], list(reversed(identities)))
        self.client.post(f'/phoi/{phoi.id}/edit', data=self.form())
        self.assertEqual(phoi.cargo_items.count(), 2)
        self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(cargo_items=json.dumps([rows[0]])))
        self.assertEqual([str(row.id) for row in phoi.additional_cargo()], identities[:1])
        self.assertEqual(phoi.total_revenue_full(), 1500000)
        self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(cargo_items='[]'))
        self.assertEqual(phoi.cargo_items.count(), 0)
        self.assertEqual(phoi.total_revenue_full(), 1000000)

    def test_outbound_cannot_claim_return_item_or_duplicate_an_identity(self):
        phoi = self.create(**self.returning())
        return_row = phoi.return_trips.first().cargo_form_data()[0]
        base = phoi.cargo_form_data()[0]
        for rows in ([return_row], [base, base]):
            self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(cargo_items=json.dumps(rows)))
            self.assertEqual(phoi.cargo_items.count(), 2)
            self.assertEqual(phoi.total_revenue_full(), 2700000)

    def test_deleting_return_trip_removes_only_its_cargo(self):
        phoi = self.create(**self.returning())
        outbound_id = phoi.additional_cargo()[0].id
        self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(cargo_items=json.dumps(phoi.cargo_form_data())))
        self.assertEqual(phoi.return_trips.count(), 0)
        self.assertEqual([row.id for row in phoi.cargo_items], [outbound_id])
        self.assertEqual(phoi.total_revenue_full(), 1500000)

    def test_driver_cannot_forge_manager_collection_on_any_row(self):
        phoi = self.create([self.row(manager_revenue_collected='70000')], **self.returning([self.row(manager_revenue_collected='80000')]))
        self.login(self.driver)
        outbound = phoi.cargo_form_data()
        outbound[0]['manager_revenue_collected'] = '0'
        returning = phoi.return_trips.first()
        returns = returning.cargo_form_data()
        returns[0]['manager_revenue_collected'] = '0'
        self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(cargo_items=json.dumps(outbound),
            **self.returning(returns, **{'return_trip_id[]': [str(returning.id)], 'return_trip_manager_revenue_collected[]': ['300000']})))
        self.assertEqual(phoi.total_manager_revenue_collected(), 150000)
        self.assertEqual(returning.manager_revenue_collected, 0)

    def test_confirmation_records_each_customer_without_changing_financial_formulas(self):
        phoi = self.create([self.row(), self.row(self.third, revenue_full='300000', revenue_collected='0')])
        self.ready(phoi)
        rows = phoi.additional_cargo()
        html, _ = self.capture(f'/phoi/{phoi.id}/confirm')
        self.assertIn(f'cargo_collection_status_{rows[0].id}', html)
        changes = {f'cargo_collection_status_{rows[0].id}': 'full',
                   f'cargo_collection_status_{rows[1].id}': 'partial',
                   f'cargo_manager_revenue_collected_{rows[1].id}': '50000', 'driver_advance': '100000'}
        self.client.post(f'/phoi/{phoi.id}/confirm', data=self.confirm_form(phoi, **changes))
        self.assertEqual(phoi.status, 'confirmed')
        self.assertEqual(phoi.total_manager_revenue_collected(), 450000)
        self.assertEqual(phoi.balance(), phoi.driver_out_of_pocket_expenses() + phoi.driver_wage - phoi.total_revenue_collected())
        self.assertEqual(phoi.settlement_balance(), phoi.balance() - 100000)
        self.assertEqual(phoi.owner_profit(), phoi.total_revenue_full() - phoi.total_expenses() - phoi.driver_wage)

    def test_missing_fuel_or_missing_extra_price_or_overpayment_blocks_confirmation(self):
        phoi = self.create([self.row(payment_method='per_ton', cargo_weight_tons='2.000', price_per_ton='', revenue_collected='0')])
        phoi.status = 'submitted'
        db.session.commit()
        self.client.post(f'/phoi/{phoi.id}/confirm', data=self.confirm_form(phoi))
        self.assertEqual(phoi.status, 'submitted')
        self.ready(phoi)
        self.assertIsNotNone(financial_confirmation_error(phoi))
        row = phoi.additional_cargo()[0]
        row.price_per_ton = 100000
        row.revenue_full = 200000
        db.session.commit()
        self.client.post(f'/phoi/{phoi.id}/confirm', data=self.confirm_form(phoi,
            **{f'cargo_collection_status_{row.id}': 'partial', f'cargo_manager_revenue_collected_{row.id}': '200001'}))
        self.assertEqual(phoi.status, 'submitted')
        self.assertEqual(row.manager_revenue_collected, 0)

    def test_debts_collect_and_correction_target_only_the_selected_customer(self):
        phoi = self.create(**self.returning())
        phoi.status = 'confirmed'
        db.session.commit()
        row = phoi.additional_cargo()[0]
        html, context = self.capture(f'/debts/customer/{self.return_customer.id}?payment_status=all')
        self.assertEqual(context['total_revenue_full'], 1000000)
        self.assertEqual(context['total_outstanding'], 800000)
        self.assertIn(f'/adjust/cargo_item/{row.id}', html)
        self.client.post(f'/debts/customer/{self.return_customer.id}/collect', data={'amount': '450000'})
        self.assertEqual(row.manager_revenue_collected, 400000)
        self.assertEqual(phoi.return_trips.first().additional_cargo()[0].manager_revenue_collected, 50000)
        self.assertEqual(phoi.manager_revenue_collected, 0)
        _, context = self.capture('/debts')
        debt = next(debt for debt in context['debts'] if debt['customer'].id == self.return_customer.id)
        self.assertEqual(debt['outstanding'], 350000)
        url = f'/debts/customer/{self.return_customer.id}/adjust/cargo_item/{row.id}'
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, data={'amount': '300000', 'expected_amount': '400000', 'reason': 'Đối soát lại'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(row.manager_revenue_collected, 300000)
        log = ActivityLog.query.filter_by(resource_type='debt_collection').one()
        self.assertEqual(log.debt_collection_details()['cargo_item_id'], row.id)
        self.assertEqual(self.client.post(url, data={'amount': '100', 'expected_amount': '400000', 'reason': 'Cũ'}).status_code, 400)

    def test_extra_customer_respects_scope_filters_and_historical_selection(self):
        phoi = self.create(**self.returning())
        phoi.status = 'confirmed'
        db.session.commit()
        _, context = self.capture(f'/debts/customer/{self.return_customer.id}?payment_status=all&start_date=2026-12-13&end_date=2026-12-13')
        self.assertEqual(context['total_revenue_full'], 500000)
        _, context = self.capture(f'/debts/customer/{self.return_customer.id}?payment_status=all&truck_id={self.other_truck.id}')
        self.assertEqual(context['total_revenue_full'], 0)
        self.return_customer.managers = [self.other]
        self.return_customer.is_active = False
        db.session.commit()
        self.assertEqual(self.client.get(f'/debts/customer/{self.return_customer.id}').status_code, 200)
        phoi.status = 'submitted'
        db.session.commit()
        html, context = self.capture(f'/phoi/{phoi.id}/edit')
        self.assertIn(self.return_customer.id, [customer.id for customer in context['customers']])
        phoi.status = 'confirmed'
        db.session.commit()
        self.login(self.other)
        row = phoi.additional_cargo()[0]
        self.assertEqual(self.client.get(f'/debts/customer/{self.return_customer.id}/adjust/cargo_item/{row.id}').status_code, 404)
        self.assertEqual(self.client.get(f'/phoi/{phoi.id}').status_code, 404)

    def test_detail_print_and_planning_include_shared_customers_and_correct_totals(self):
        phoi = self.create([self.row(manager_revenue_collected='50000')], **self.returning())
        for path in (f'/phoi/{phoi.id}', f'/phoi/{phoi.id}/print'):
            html, _ = self.capture(path)
            self.assertIn('Khách #2: Hàng C', html)
            self.assertIn('2,700,000', html)
            self.assertIn('50,000', html)
        actual = actual_from_phoi(phoi)
        self.assertIn('Hàng C: Hàng ghép', actual['cargo_description'])
        self.assertIn('Hàng C: Hàng ghép', actual['return_trips'][0]['cargo_description'])
        self.login(self.driver)
        html, _ = self.capture(f'/phoi/{phoi.id}/print')
        self.assertIn('Khách #2: Hàng C', html)
        self.assertNotIn('Tổng cước chuyến:', html)

    def test_single_customer_legacy_phoi_needs_no_backfill(self):
        phoi = self.create([])
        self.assertEqual(phoi.cargo_items.count(), 0)
        self.assertEqual(phoi.total_revenue_full(), phoi.revenue_full)
        self.assertEqual(phoi.total_revenue_collected(), phoi.revenue_collected)
        self.assertEqual(phoi.total_manager_revenue_collected(), phoi.manager_revenue_collected)
        for path in ('/phoi/create', f'/phoi/{phoi.id}/edit'):
            html, _ = self.capture(path)
            self.assertIn('data-cargo-extras', html)
            self.assertIn('phoi_cargo.js', html)

    def test_truck_report_includes_shared_revenue_once_and_unchanged_trip_count(self):
        from datetime import date
        phoi = self.create(**self.returning())
        phoi.status = 'confirmed'
        db.session.commit()
        report = build_truck_report(self.manager, [self.truck], date(2026, 12, 1), date(2026, 12, 31))
        self.assertEqual(report['totals']['phoi_count'], 1)
        self.assertEqual(report['totals']['revenue'], 2700000)
        self.assertEqual(report['totals']['profit'], phoi.owner_profit())

    def test_sub_ton_prices_round_once_and_reject_invalid_weight_or_overflow(self):
        from app.phoi_cargo import revenue_from_values
        self.assertEqual(revenue_from_values('per_ton', '999999', '0.5', '300000.01'),
                         (Decimal('150000.01'), Decimal('0.5'), Decimal('300000.01')))
        self.assertEqual(revenue_from_values('per_ton', '', '18500', '300000')[1], Decimal('18.5'))
        for weight in ('0', '-1', 'NaN', 'Infinity', '0.0001', '100', '100000'):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                revenue_from_values('per_ton', '', weight, '300000')
        with self.assertRaises(ValueError):
            revenue_from_values('per_ton', '', '99.999', '9999999999.99')

    def test_driver_form_does_not_expose_manager_collection_and_keeps_server_value(self):
        phoi = self.create([self.row(manager_revenue_collected='70000')])
        self.login(self.driver)
        html, _ = self.capture(f'/phoi/{phoi.id}/edit')
        self.assertNotIn('manager_revenue_collected', html)
        values = phoi.cargo_form_data(include_manager=False)
        self.client.post(f'/phoi/{phoi.id}/edit', data=self.form(cargo_items=json.dumps(values)))
        self.assertEqual(phoi.additional_cargo()[0].manager_revenue_collected, 70000)

    def test_shared_summary_fits_existing_planning_column_without_truncating_phoi_data(self):
        phoi = self.create([self.row(cargo_description='Gạo ' * 70),
                            self.row(self.third, cargo_description='Bắp ' * 70)])
        self.assertLessEqual(len(actual_from_phoi(phoi)['cargo_description']), 300)
        self.assertIn('Khách thứ ba', phoi.cargo_summary())
        self.assertEqual(phoi.additional_cargo()[0].cargo_description, 'Gạo ' * 69 + 'Gạo')


if __name__ == '__main__':
    unittest.main()
