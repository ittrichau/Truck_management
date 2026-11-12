import os
import unittest
from datetime import date
from decimal import Decimal

os.environ['FLASK_ENV'] = 'testing'

from app import create_app, db
from app.models import Customer, Phoi, PhoiReturnTrip, Truck, User


class DebtTruckFilterTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config.update(
            WTF_CSRF_ENABLED=False,
            RATELIMIT_ENABLED=False,
        )
        self.client = self.app.test_client()
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        self.manager = User(
            username='debt-filter-manager',
            full_name='Test Manager',
            role='manager',
            is_active=True,
        )
        self.manager.set_password('test-password')
        self.truck_one = Truck(license_plate='0001', is_active=True)
        self.truck_two = Truck(license_plate='0002', is_active=True)
        self.customer_one = Customer(name='Chủ hàng Một', is_active=True)
        self.customer_two = Customer(name='Chủ hàng Hai', is_active=True)
        db.session.add_all([
            self.manager,
            self.truck_one,
            self.truck_two,
            self.customer_one,
            self.customer_two,
        ])
        db.session.flush()

        self._add_phoi(
            'P-TEST-001', self.truck_one, self.customer_one,
            Decimal('1000'), Decimal('200'),
        )
        phoi_with_return = self._add_phoi(
            'P-TEST-002', self.truck_one, self.customer_two,
            Decimal('2000'), Decimal('500'),
        )
        db.session.add(PhoiReturnTrip(
            phoi=phoi_with_return,
            customer=self.customer_one,
            trip_order=1,
            return_date=date(2026, 10, 28),
            origin='A',
            destination='B',
            revenue_full=Decimal('300'),
            revenue_collected=Decimal('100'),
            manager_revenue_collected=Decimal('50'),
        ))
        self._add_phoi(
            'P-TEST-003', self.truck_two, self.customer_one,
            Decimal('5000'), Decimal('1000'),
        )
        db.session.commit()

        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.manager.id)
            session['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    @staticmethod
    def _add_phoi(number, truck, customer, revenue_full, revenue_collected):
        phoi = Phoi(
            phoi_number=number,
            driver_id=1,
            truck=truck,
            customer=customer,
            departure_date=date(2026, 10, 20),
            origin='A',
            destination='B',
            revenue_full=revenue_full,
            revenue_collected=revenue_collected,
            manager_revenue_collected=Decimal('0'),
            status='confirmed',
        )
        db.session.add(phoi)
        db.session.flush()
        return phoi

    def test_selected_truck_filters_customer_trip_count_and_debt(self):
        response = self.client.get(f'/debts?truck_id={self.truck_one.id}')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="truck_id"', response.data)
        self.assertIn(f'truck_id={self.truck_one.id}'.encode(), response.data)

        detail = self.client.get(
            f'/debts/customer/{self.customer_one.id}?truck_id={self.truck_one.id}'
            '&payment_status=all'
        )
        self.assertEqual(detail.status_code, 200)
        self.assertIn('Tổng công nợ hiện tại'.encode(), detail.data)
        # Fixtures: 1,000 + 300 revenue, less 200 + 100 + 50 collected.
        self.assertIn(b'950', detail.data)
        self.assertIn(b'1,300', detail.data)
        self.assertNotIn(b'5,000', detail.data)
        self.assertIn(b'2</span>', detail.data)

    def test_unfiltered_total_and_trip_counts_include_both_trucks(self):
        response = self.client.get('/debts')

        self.assertEqual(response.status_code, 200)
        # All four fixture rows: 1,000 + 2,000 + 300 + 5,000.
        self.assertIn(b'8,300', response.data)
        self.assertIn(b'6,450', response.data)


if __name__ == '__main__':
    unittest.main()
