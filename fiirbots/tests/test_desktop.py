import re
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import AIAnalysisReport
from app.desktop_tools import validate_selection, wifi_observation
from app.network_engine import scan, probe
from app.touch_evidence import ai_report_lines

ADAPTER = {'interface': 'Wi-Fi', 'address': '192.168.0.148',
           'network': '192.168.0.0/24', 'suggested_scope': '192.168.0.0/24'}


class DesktopTests(unittest.TestCase):
    def test_touch_gemini_report_prioritizes_findings_and_matches_current_scan(self):
        report = AIAnalysisReport(overall_threat_score=42, summary='One device needs review.', findings=[
            {'target_ip': '192.168.0.22', 'risk_level': 'LOW', 'is_justified': False,
             'description': 'The device role is unknown.', 'recommended_remediation': 'Check the asset inventory.'},
            {'target_ip': '192.168.0.10', 'risk_level': 'HIGH', 'is_justified': True,
             'description': 'TCP port 23 was observed.', 'recommended_remediation': 'Check whether Telnet is expected.'},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Settings(database=Path(tmp)/'test.db', gpio_enabled=False,
                                      reboot_enabled=False, serial_port='', api_key='test', network=ADAPTER['network']))
            with TestClient(app) as client, patch('app.controller.ai_analyzer.analyze', return_value=report):
                controller = app.state.controller
                path = '/api/industrial/assessment?include_ai=true'
                self.assertIn('complete a LAN scan', ai_report_lines(client.get(path).json())[0])
                controller.db.execute("INSERT INTO scan_batches(id,network,status) VALUES(?,?,'COMPLETE')",
                                      ('scan-test', ADAPTER['network']))
                token = re.search('name="action-token" content="([^"]+)', client.get('/').text)[1]
                headers = {'X-FIIRBots-Token': token}
                self.assertEqual(client.post('/api/analyze?scan_id=old-scan', headers=headers).status_code, 409)
                self.assertEqual(client.post('/api/analyze?scan_id=scan-test', headers=headers).status_code, 202)
                controller.worker.join(timeout=3)
                lines = ai_report_lines(client.get(path).json())
                self.assertIn('42/100 · 2 findings', lines[0])
                self.assertIn('HIGH · 192.168.0.10', lines[1])
                self.assertIn('Next check · Check whether Telnet is expected.', lines[1])
                self.assertIn('Evidence incomplete', lines[2])
                controller.db.execute("INSERT INTO scan_batches(id,network,status) VALUES(?,?,'COMPLETE')",
                                      ('new-scan', ADAPTER['network']))
                self.assertIsNone(client.get(path).json()['ai_report'])

    def test_windows_connect_timeout_is_inconclusive(self):
        with patch('app.network_engine.socket.socket') as socket:
            socket.return_value.__enter__.return_value.connect_ex.return_value = 10035
            self.assertEqual(probe('192.168.0.1', 22, threading.Event()), 'NO_RESPONSE')

    @patch('app.desktop_tools.adapters', return_value=[ADAPTER])
    def test_scope_must_belong_to_selected_adapter(self, _):
        self.assertEqual(validate_selection('192.168.0.0/24', 'Wi-Fi'), '192.168.0.148')
        for network, interface in [('192.168.1.0/24', 'Wi-Fi'), ('192.168.0.0/24', 'missing'),
                                   ('8.8.8.0/24', 'Wi-Fi'), ('192.168.0.0/16', 'Wi-Fi')]:
            with self.assertRaises(ValueError): validate_selection(network, interface)

    @patch('app.desktop_tools.adapters', return_value=[ADAPTER])
    def test_config_api_token_lock_and_persisted_state(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Settings(database=Path(tmp)/'test.db', gpio_enabled=False,
                                      reboot_enabled=False, serial_port='', api_key='', network=''))
            with TestClient(app) as client:
                body = {'network': '192.168.0.0/24', 'interface': 'Wi-Fi'}
                self.assertEqual(client.put('/api/network/configure', json=body).status_code, 403)
                token = re.search('name="action-token" content="([^"]+)', client.get('/').text)[1]
                headers = {'X-FIIRBots-Token': token}
                self.assertEqual(client.put('/api/network/configure', json=body, headers=headers).status_code, 200)
                self.assertEqual(client.get('/api/state').json()['network'], body['network'])
                app.state.controller.job['status'] = 'RUNNING'
                with patch.object(app.state.controller, 'worker') as worker:
                    worker.is_alive.return_value = True
                    self.assertEqual(client.put('/api/network/configure', json=body, headers=headers).status_code, 409)
                app.state.controller.lock_operations()
                self.assertEqual(client.put('/api/network/configure', json=body, headers=headers).status_code, 409)

    def test_closed_ports_are_evidence_and_timeouts_are_not(self):
        rows = scan('192.168.0.0/30', 'fake', [], threading.Event(), lambda *_: None,
                    discover_fn=lambda *_: {},
                    probe_fn=lambda ip, p, c: 'CLOSED' if ip.endswith('.1') else 'NO_RESPONSE')
        self.assertEqual([r['device_ip'] for r in rows], ['192.168.0.1'])
        self.assertEqual(rows[0]['open_ports'], [])

    def test_wifi_unavailable_is_not_empty_success(self):
        with patch('app.desktop_tools.platform.system', return_value='Windows'), \
             patch('app.desktop_tools.windows_wifi.scan_interfaces', side_effect=OSError), \
             patch('app.desktop_tools.subprocess.run', side_effect=OSError):
            self.assertEqual(wifi_observation()['status'], 'UNAVAILABLE')

    def test_windows_cached_and_refreshed_adapter_observations(self):
        # Synthetic netsh inventory containing weak, hidden and shared-name BSSIDs.
        output = b'''Interface name : Wi-Fi
SSID 1 : LAB
    Authentication : WPA2-Personal
    Encryption : CCMP
    BSSID 1 : 00:00:00:00:00:01
         Signal : 25%
         Channel : 36
         Band : 5 GHz
    BSSID 2 : 00:00:00:00:00:02
         Signal : 2%
SSID 2 :
    Authentication : Open
    Encryption : WEP
    BSSID 1 : 00:00:00:00:00:03
SSID 3 : Public
    Authentication : Open
    Encryption : None
    BSSID 1 : 00:00:00:00:00:04
'''
        result = SimpleNamespace(returncode=0, stdout=output, stderr=b'')
        for state, mode in [('complete', 'OS-managed rescan'), ('timed out', 'OS cache')]:
            with self.subTest(state=state), \
                 patch('app.desktop_tools.platform.system', return_value='Windows'), \
                 patch('app.desktop_tools.windows_wifi.scan_interfaces', return_value=[{'state': state}]), \
                 patch('app.desktop_tools.subprocess.run', return_value=result):
                inventory = wifi_observation()
                self.assertEqual(inventory['scan_mode'], mode)
                self.assertEqual(inventory['status'], 'OUTPUT')
                points = inventory['access_points']
                self.assertEqual([p['ssid'] for p in points], ['LAB', 'LAB', '', 'Public'])
                self.assertEqual(points[0]['channel'], 36)
                self.assertEqual(points[0]['band'], '5 GHz')
                self.assertEqual(points[1]['signal_percent'], 2)
                self.assertEqual(points[2]['security'], 'WEP')
                self.assertEqual(points[3]['security'], 'Open')

    def test_windows_permission_message_and_verified_empty(self):
        for output, expected in [(b'Location permission is required', 'UNAVAILABLE'),
                                 (b'There are 0 networks currently visible.', 'OUTPUT')]:
            with self.subTest(output=output), \
                 patch('app.desktop_tools.platform.system', return_value='Windows'), \
                 patch('app.desktop_tools.windows_wifi.scan_interfaces', side_effect=OSError), \
                 patch('app.desktop_tools.subprocess.run', return_value=SimpleNamespace(
                     returncode=0, stdout=output, stderr=b'')):
                self.assertEqual(wifi_observation()['status'], expected)
