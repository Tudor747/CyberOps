import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.ai_analyzer import check_connection, analyze


class AIConnectionTests(unittest.TestCase):
    def test_missing_key_does_not_contact_provider(self):
        with patch('google.genai.Client') as client:
            result = check_connection(SimpleNamespace(api_key=''))
        self.assertEqual(result['status'], 'NOT_CONFIGURED')
        client.assert_not_called()

    def test_live_generation_success(self):
        with patch('google.genai.Client') as client:
            client.return_value.__enter__.return_value.models.generate_content.return_value.text = 'OK'
            result = check_connection(SimpleNamespace(api_key='secret', model='test-model'))
        self.assertEqual(result['status'], 'OK')

    def test_provider_error_does_not_disclose_credentials(self):
        with patch('google.genai.Client', side_effect=RuntimeError('secret-key-in-url')):
            result = check_connection(SimpleNamespace(api_key='secret', model='test-model'))
        self.assertEqual(result['status'], 'ERROR')
        self.assertNotIn('secret', str(result))

    def test_analysis_rejects_unobserved_targets(self):
        report = '{"overall_threat_score":10,"summary":"Test","findings":[{"target_ip":"192.168.0.9","risk_level":"LOW","is_justified":false,"description":"Test","recommended_remediation":"Inspect"}]}'
        with patch('google.genai.Client') as client:
            generate = client.return_value.__enter__.return_value.models.generate_content
            generate.return_value.text = report
            with self.assertRaisesRegex(ValueError, 'outside the scan'):
                analyze(SimpleNamespace(api_key='secret', model='test-model'),
                        {'devices': [{'device_ip': '192.168.0.1'}]}, [], [])
            config = generate.call_args.kwargs['config']
            self.assertIsNone(config.response_schema)
            self.assertFalse(config.response_json_schema['additionalProperties'])
