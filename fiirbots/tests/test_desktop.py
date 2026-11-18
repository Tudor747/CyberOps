import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.desktop_tools import validate_selection, wifi_observation
from app.network_engine import scan, probe

ADAPTER = {'interface': 'Wi-Fi', 'address': '192.168.0.148',
           'network': '192.168.0.0/24', 'suggested_scope': '192.168.0.0/24'}


class DesktopTests(unittest.TestCase):
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
             patch('app.desktop_tools.subprocess.run', side_effect=OSError):
            self.assertEqual(wifi_observation()['status'], 'UNAVAILABLE')
