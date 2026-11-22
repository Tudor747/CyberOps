import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from scapy.layers.dot11 import Dot11, Dot11Beacon, Dot11Elt, Dot11ProbeReq, Dot11Deauth, RadioTap, Dot11EltRSN
from scapy.layers.l2 import Ether
from app.config import Settings
from app.main import create_app
from app.network_engine import ScanCancelled
from app.wireless_monitor import Summary, interfaces, capture


class WirelessTests(unittest.TestCase):
    def test_decoded_specialized_rsn_and_channel_elements(self):
        packet = RadioTap()/Dot11(type=0, subtype=8, addr3='00:11:22:33:44:55')/Dot11Beacon(cap='ESS+privacy')/Dot11Elt(ID=0, info=b'Lab')/Dot11Elt(ID=3, info=b'\x06')/Dot11EltRSN()
        summary = Summary()
        summary.receive(RadioTap(bytes(packet)))
        ap = summary.result()['access_points'][0]
        self.assertTrue(ap['rsn_advertised'])
        self.assertTrue(ap['privacy_bit'])
        self.assertEqual(ap['channel'], 6)

    def test_metadata_and_threat_counts_are_not_attack_verdicts(self):
        summary = Summary()
        summary.receive(RadioTap()/Dot11(type=0, subtype=8, addr3='00:11:22:33:44:55')/
                        Dot11Beacon(cap='ESS')/Dot11Elt(ID=0, info=b'<script>lab</script>')/
                        Dot11Elt(ID=3, info=b'\x06'))
        summary.receive(Dot11(type=0, subtype=4, addr2='00:11:22:33:44:66')/
                        Dot11ProbeReq()/Dot11Elt(ID=0, info=b'lab'))
        summary.receive(Dot11(type=0, subtype=12, addr2='00:11:22:33:44:55')/Dot11Deauth(reason=3))
        summary.receive(Ether())
        result = summary.result()
        self.assertEqual(result['counts'], {'beacon': 1, 'probe_request': 1, 'deauthentication': 1})
        self.assertFalse(result['access_points'][0]['privacy_bit'])
        self.assertEqual(result['access_points'][0]['channel'], 6)
        self.assertEqual(result['probes'][0]['ssid'], 'lab')
        self.assertIn('do not prove an attack', result['interpretation'])

    def test_probe_storage_is_bounded(self):
        summary = Summary()
        for i in range(520):
            summary.receive(Dot11(type=0, subtype=4, addr2='00:11:22:33:44:66')/
                            Dot11ProbeReq()/Dot11Elt(ID=0, info=str(i).encode()))
        self.assertEqual(len(summary.probes), 512)
        self.assertTrue(summary.truncated)

    def test_interface_parser_retains_mode_and_channel(self):
        output = 'phy#0\n\tInterface wlan0\n\t\ttype managed\n\tInterface mon0\n\t\ttype monitor\n\t\tchannel 6 (2437 MHz)\n'
        with patch('app.wireless_monitor.platform.system', return_value='Linux'), \
             patch('app.wireless_monitor.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=output)):
            self.assertEqual(interfaces()['interfaces'][1], {'name': 'mon0', 'mode': 'monitor', 'channel': 6})

    def test_managed_interface_is_rejected_without_capture(self):
        with patch('app.wireless_monitor.interfaces', return_value={'interfaces': [{'name': 'wlan0', 'mode': 'managed'}]}), \
             patch('scapy.all.sniff') as sniff:
            with self.assertRaisesRegex(ValueError, 'monitor interface'):
                capture('wlan0', 1, threading.Event())
            sniff.assert_not_called()

    def test_capture_cancel_closes_socket(self):
        cancel = threading.Event()
        with patch('app.wireless_monitor.interfaces', return_value={'interfaces': [{'name': 'mon0', 'mode': 'monitor', 'channel': 6}]}), \
             patch('scapy.all.conf.L2listen') as socket, \
             patch('scapy.all.sniff', side_effect=lambda **kwargs: cancel.set()):
            with self.assertRaises(ScanCancelled): capture('mon0', 1, cancel)
            socket.return_value.__exit__.assert_called_once()


class ToolAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Settings(database=Path(self.temp.name)/'test.db', gpio_enabled=False,
                                      reboot_enabled=False, serial_port='', api_key='', network=''))
        self.client = self.enterContext(TestClient(self.app))
        token = re.search('name="action-token" content="([^"]+)', self.client.get('/').text)[1]
        self.headers = {'X-FIIRBots-Token': token}
        self.controller = self.app.state.controller

    def seed_ble(self):
        self.controller.db.event('bluetooth', 'BLE_SCAN', {'status': 'COMPLETE', 'devices': [
            {'address': 'AA:BB:CC:DD:EE:FF', 'name': 'Lab', 'service_uuids': ['1234'], 'rssi_dbm': -50}]})
        return self.client.get('/api/ble/defense').json()['scan_id']

    def test_ble_enrollment_and_change_detection(self):
        scan_id = self.seed_ble()
        body = {'scan_id': scan_id, 'addresses': ['AA:BB:CC:DD:EE:FF']}
        self.assertEqual(self.client.put('/api/ble/baseline', json=body).status_code, 403)
        self.assertEqual(self.client.put('/api/ble/baseline', json=body, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get('/api/ble/defense').json()['devices'][0]['comparison'], 'KNOWN')
        self.controller.db.event('bluetooth', 'BLE_SCAN', {'devices': [{'address': 'AA:BB:CC:DD:EE:FF', 'name': 'Changed', 'service_uuids': []}]})
        self.assertEqual(self.client.get('/api/ble/defense').json()['devices'][0]['comparison'], 'CHANGED')
        self.assertEqual(self.client.put('/api/ble/baseline', json=body, headers=self.headers).status_code, 409)

    def test_enrollment_cannot_invent_devices_or_bypass_lock(self):
        scan_id = self.seed_ble()
        body = {'scan_id': scan_id, 'addresses': ['unobserved']}
        self.assertEqual(self.client.put('/api/ble/baseline', json=body, headers=self.headers).status_code, 409)
        body['addresses'] = ['AA:BB:CC:DD:EE:FF']
        self.controller.lock_operations()
        self.assertEqual(self.client.put('/api/ble/baseline', json=body, headers=self.headers).status_code, 409)

    def test_rf_requires_fresh_sample_and_persists_difference(self):
        self.assertEqual(self.client.put('/api/rf/baseline', headers=self.headers).status_code, 409)
        sample = {'connected': True, 'status': 'OK', 'received_at': time.time()-10, 'rf_bins': [1]*81}
        self.controller.serial.set_state(sample)
        self.assertEqual(self.client.put('/api/rf/baseline', headers=self.headers).status_code, 409)
        sample['received_at'] = time.time()
        self.controller.serial.set_state(sample)
        self.assertEqual(self.client.put('/api/rf/baseline', headers=self.headers).status_code, 200)
        self.controller.db.event('nRF24', 'RF_SWEEP', {'bins': None})
        self.controller.db.event('nRF24', 'RF_SWEEP', {'bins': [3]*81})
        result = self.client.get('/api/rf/history').json()
        self.assertEqual(len(result['samples']), 1)
        self.assertEqual(result['delta'], [2]*81)
        self.controller.db.event('nRF24', 'RF_SWEEP', {'bins': [3]*81, 'rf_dwell_us': 200})
        self.assertIsNone(self.client.get('/api/rf/history').json()['delta'])

    def test_wifi_survey_keeps_shared_names_and_unavailable_receiver(self):
        # Synthetic OS inventory with two BSSIDs sharing the same name.
        rows = [{'ssid': 'Lab', 'bssid': '02:00:00:00:00:' + suffix, 'security': security}
                for suffix, security in [('01', 'Open'), ('02', 'WPA2')]]
        fixture = {'access_points': rows + rows[:1], 'source': 'Host', 'status': 'OUTPUT'}
        with patch('app.desktop_tools.wifi_observation', return_value=fixture):
            response = self.client.post('/api/wifi/survey', headers=self.headers, json={'receiver': 'both', 'passes': 1})
            self.assertEqual(response.status_code, 202)
            self.controller.worker.join(2)
        result = self.client.get('/api/wifi/survey/latest').json()
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(len(result['access_points']), 2)
        self.assertEqual(result['summary'], dict(named_ssids=1, shared_ssids=1, open_bssids=1, wep_bssids=0))
        self.assertIsNone(result['sources'][1]['observed_rows'])

    def test_snapshot_requires_a_fix_during_the_survey(self):
        from app import wifi_survey
        # Synthetic GPS fixes and empty completed scan exercise temporal matching.
        for fix_time, expected in [('2000-01-01T00:00:00+00:00', 'ERROR'), (None, 'COMPLETE')]:
            times = []
            def observation(*args):
                times.append(wifi_survey.timestamp())
                return dict(status='OUTPUT', observed_at=wifi_survey.timestamp(), access_points=[])
            class Fixes:
                def __getitem__(self, key):
                    return [{'time': fix_time or times[0]}]
            with patch('app.wifi_survey.esp_observation', side_effect=observation), patch('app.gps_observer.observe', return_value=Fixes()):
                self.assertEqual(self.client.post('/api/gps/wifi-snapshot', headers=self.headers).status_code, 202)
                self.controller.worker.join(2)
            self.assertEqual(self.controller.job['status'], expected)
        self.assertEqual(self.client.get('/api/gps/wifi-snapshot/latest').json()['status'], 'COMPLETE')

    def test_esp_wifi_survey_reads_every_page(self):
        from app.wifi_survey import esp_observation
        def reply(command, scan_id, offset=0):
            header = dict(status='WIFI_SCAN', scan_id=scan_id)
            if command == 'WIFI_SCAN_START':
                return dict(**header, state='scanning')
            if command == 'WIFI_SCAN_CANCEL':
                return dict(status='STOPPED')
            rows = [dict(bssid=f'02:00:00:00:00:{i:02x}', ssid='Lab', channel=6, security='Open', rssi_dbm=-70)
                    for i in range(offset, min(offset+12, 37))]
            return dict(**header, state='complete', offset=offset, total=37, networks=rows,
                        next_offset=offset+12 if offset+12 < 37 else None)
        link = self.controller.serial
        with patch.object(link, 'snapshot', return_value={'connected': True}), patch.object(link, 'request', side_effect=reply):
            result = esp_observation(link, threading.Event())
        self.assertEqual(len(result['access_points']), 37)

    def test_wireless_job_saves_result_and_exports(self):
        result = {'status': 'COMPLETE', 'counts': {'beacon': 3}}
        with patch('app.wireless_monitor.capture', return_value=result):
            response = self.client.post('/api/wireless/scan', headers=self.headers,
                                        json={'interface': 'mon0', 'duration_s': 1})
            self.assertEqual(response.status_code, 202)
            self.controller.worker.join(2)
        self.assertEqual(self.client.get('/api/wireless/latest').json()['counts'], {'beacon': 3})
        self.assertEqual(self.client.get('/api/tools/export').json()['wireless']['status'], 'COMPLETE')

    def test_cancelled_capture_does_not_replace_saved_result(self):
        self.controller.db.event('wifi', 'WIRELESS_SCAN', {'status': 'COMPLETE', 'counts': {'beacon': 2}})
        def cancelled(interface, duration, cancel):
            cancel.set()
            return {'status': 'COMPLETE', 'counts': {'beacon': 99}}
        with patch('app.wireless_monitor.capture', side_effect=cancelled):
            self.client.post('/api/wireless/scan', headers=self.headers, json={'interface': 'mon0'})
            self.controller.worker.join(2)
        self.assertEqual(self.client.get('/api/wireless/latest').json()['counts'], {'beacon': 2})

    def test_mutations_validate_input_and_respect_lock(self):
        self.assertEqual(self.client.post('/api/wireless/scan', json={'interface': 'mon0'}).status_code, 403)
        self.assertEqual(self.client.post('/api/wireless/scan', json={'interface': 'mon0', 'duration_s': 31}, headers=self.headers).status_code, 422)
        self.controller.lock_operations()
        self.assertEqual(self.client.post('/api/wireless/scan', json={'interface': 'mon0'}, headers=self.headers).status_code, 409)

    def test_lab_api_requires_scope_confirmation_and_bounded_parameters(self):
        from datetime import datetime, timezone
        pair = {'bssid': '00:11:22:33:44:55', 'client': '00:11:22:33:44:66'}
        self.controller.db.event('wifi', 'WIRELESS_SCAN', {'status': 'COMPLETE', 'interface': 'mon0', 'channel': 6,
            'finished_at': datetime.now(timezone.utc).isoformat(), 'clients': [pair],
            'probes': [{'source': pair['client'], 'ssid': 'Lab'}]})
        scan_id = self.client.get('/api/wireless/latest').json()['id']
        body = {'scan_id': scan_id, 'interface': 'mon0', **pair, 'frames': 1, 'isolated_lab_confirmed': False}
        self.assertEqual(self.client.post('/api/lab/deauth', headers=self.headers, json=body).status_code, 409)
        body['isolated_lab_confirmed'] = True
        self.assertEqual(self.client.post('/api/lab/deauth', json=body).status_code, 403)
        self.assertEqual(self.client.post('/api/lab/deauth', headers=self.headers, json={**body, 'frames': 11}).status_code, 422)
        with patch('app.lab_radio.deauthenticate', return_value={'status': 'TRANSMISSION_ATTEMPTED', 'effect': 'UNVERIFIED'}):
            self.assertEqual(self.client.post('/api/lab/deauth', headers=self.headers, json=body).status_code, 202)
            self.controller.worker.join(2)
        self.assertEqual(self.client.get('/api/lab/latest').json()['effect'], 'UNVERIFIED')
        probe = {'scan_id': scan_id, 'interface': 'mon0', 'source': pair['client'], 'ssid': 'Lab', 'isolated_lab_confirmed': True}
        with patch('app.lab_radio.advertise_probe', return_value={'status': 'TRANSMISSION_ATTEMPTED', 'effect': 'UNVERIFIED'}):
            self.assertEqual(self.client.post('/api/lab/beacon', headers=self.headers, json=probe).status_code, 202)
            self.controller.worker.join(2)
        self.assertEqual(self.client.get('/api/lab/beacon/latest').json()['effect'], 'UNVERIFIED')

    def test_gps_job_waypoint_and_export(self):
        point = {'longitude': 26.1, 'latitude': 44.4, 'time': '2026-11-18T12:00:00+00:00'}
        with patch('app.gps_observer.observe', return_value={'status': 'COMPLETE', 'points': [point]}):
            self.assertEqual(self.client.post('/api/gps/observe', headers=self.headers, json={'duration_s': 1}).status_code, 202)
            self.controller.worker.join(2)
        track_id = self.client.get('/api/gps/latest').json()['id']
        self.assertEqual(self.client.put('/api/gps/waypoint', headers=self.headers,
                                        json={'track_id': track_id, 'label': 'Lab'}).status_code, 200)
        result = self.client.get('/api/gps/export').json()
        self.assertEqual(len(result['features']), 2)
        self.assertEqual(result['features'][1]['geometry']['coordinates'], [26.1, 44.4])
