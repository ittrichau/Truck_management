import json
import os
import unittest
from unittest.mock import patch

os.environ['FLASK_ENV'] = 'testing'

from app import create_app, db
from app.ai_trip_suggestions import AiSuggestionError, suggest_trip_draft
from app.models import ActivityLog, Customer, Phoi, User


class ProviderSuggestionTests(unittest.TestCase):
    def test_parses_trip_draft_and_accepts_only_customer_from_catalog(self):
        customers = [Customer(id=8, name='Chủ hàng A', cargo_type='Lúa')]

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                content = json.dumps({
                    'customer_id': 8,
                    'customer_match': 'matched',
                    'origin': ' Bến Tre ',
                    'destination': 'Tây Ninh',
                    'cargo_description': 'Lúa',
                    'departure_date': '',
                    'notes': '',
                    'payment_method': 'per_ton',
                    'revenue_full': None,
                    'cargo_weight_tons': 18.5,
                    'price_per_ton': 350000,
                })
                return json.dumps({'choices': [{'message': {'content': content}}]}).encode()

        with patch('app.ai_trip_suggestions.urllib.request.urlopen', return_value=Response()):
            result = suggest_trip_draft('Chủ hàng A, Bến Tre đến Tây Ninh chở lúa, giá 350.000/tấn', customers,
                                        'test-key', 'test-model')

        self.assertEqual(result['customer_id'], 8)
        self.assertEqual(result['customer_name'], 'Chủ hàng A')
        self.assertEqual(result['origin'], 'Bến Tre')
        self.assertEqual(result['destination'], 'Tây Ninh')
        self.assertEqual(result['payment_method'], 'per_ton')
        self.assertEqual(result['price_per_ton'], 350000)

    def test_rejects_empty_or_oversized_input_before_provider_call(self):
        with patch('app.ai_trip_suggestions.urllib.request.urlopen') as provider:
            with self.assertRaises(ValueError):
                suggest_trip_draft('  ', [], 'test-key', 'test-model')
            with self.assertRaises(ValueError):
                suggest_trip_draft('x' * 1201, [], 'test-key', 'test-model')
        provider.assert_not_called()

    def test_rejects_malformed_model_output(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return json.dumps({'choices': [{'message': {'content': 'not json'}}]}).encode()

        with patch('app.ai_trip_suggestions.urllib.request.urlopen', return_value=Response()):
            with self.assertRaises(AiSuggestionError):
                suggest_trip_draft('Chuyến giả lập', [], 'test-key', 'test-model')


class AiSuggestionRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config.update(
            WTF_CSRF_ENABLED=False,
            CMD_API_KEY='test-key',
            CMD_API_MODEL='test-model',
            RATELIMIT_ENABLED=False,
        )
        self.client = self.app.test_client()
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def login_as_driver(self):
        driver = User(
            username='ai-test-driver',
            full_name='Test Driver',
            role='driver',
            is_active=True,
        )
        driver.set_password('test-password')
        db.session.add(driver)
        db.session.commit()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(driver.id)
            session['_fresh'] = True

    @patch('app.routes.phoi.suggest_trip_draft')
    def test_authenticated_driver_gets_suggestion_without_database_writes(self, suggest):
        self.login_as_driver()
        customer = Customer(name='Chủ hàng test', cargo_type='Lúa', is_active=True)
        db.session.add(customer)
        db.session.commit()
        suggest.return_value = {
            'customer_id': customer.id,
            'customer_name': customer.name,
            'customer_match': 'matched',
            'origin': 'Bến Tre',
            'destination': 'Tây Ninh',
            'cargo_description': 'Lúa',
            'departure_date': '',
            'notes': '',
            'payment_method': 'per_ton',
            'revenue_full': None,
            'cargo_weight_tons': 18.5,
            'price_per_ton': 350000,
        }

        response = self.client.post(
            '/phoi/ai-trip-suggestions',
            json={'description': 'Chở dừa từ Bến Tre đến Tây Ninh'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['suggestions']['origin'], 'Bến Tre')
        self.assertEqual(Phoi.query.count(), 0)
        self.assertEqual(ActivityLog.query.count(), 0)
        self.assertEqual(suggest.call_args.args[1], [customer])

    def test_logged_out_user_is_redirected_to_login(self):
        response = self.client.post(
            '/phoi/ai-trip-suggestions',
            json={'description': 'Dữ liệu giả'},
        )
        self.assertEqual(response.status_code, 302)

    def test_unconfigured_provider_is_disabled(self):
        self.login_as_driver()
        self.app.config['CMD_API_KEY'] = ''
        response = self.client.post(
            '/phoi/ai-trip-suggestions',
            json={'description': 'Dữ liệu giả'},
        )
        self.assertEqual(response.status_code, 503)

    def test_invalid_payload_is_rejected(self):
        self.login_as_driver()
        response = self.client.post('/phoi/ai-trip-suggestions', json={'description': 'x' * 1201})
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()