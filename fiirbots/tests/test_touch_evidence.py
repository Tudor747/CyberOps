"""Synthetic API fixtures for the native presentation layer."""
import unittest

from app.touch_evidence import hardware_lines, tool_lines, wifi_lines
from app.wifi_survey import fresh_inventory, inventory_alerts


class TouchEvidenceTests(unittest.TestCase):
    def test_ap_alerts_require_fresh_observations_and_compare_security_by_receiver(self):
        known_ap = '02:00:00:00:00:01'
        new_ap = '02:00:00:00:00:02'
        cached_ap = '02:00:00:00:00:03'
        sample = {'ssid': 'Office', 'source': 'ESP32', 'security': 'WPA2'}
        known = fresh_inventory({'access_points': [{'bssid': known_ap, 'samples': [sample]}]})
        survey = {'status': 'PARTIAL', 'access_points': [
            {'bssid': known_ap, 'samples': [{**sample, 'security': 'OPEN'},
                                            {**sample, 'source': 'NetworkManager', 'security': 'WPA3'}]},
            {'bssid': new_ap, 'samples': [sample]},
            {'bssid': cached_ap, 'samples': [{**sample, 'from_cache': True}]},
        ]}
        alerts = inventory_alerts(fresh_inventory(survey), known)
        self.assertEqual([(alert['kind'], alert['bssid']) for alert in alerts],
                         [('SECURITY_CHANGED', known_ap), ('NEW_BSSID', new_ap)])
        display = '\n'.join(wifi_lines({**survey, 'alerts': alerts}))
        self.assertIn('WPA2 → OPEN', display)
        self.assertIn(f'New BSSID for Office · {new_ap}', display)

    def test_survey_preserves_cached_and_receiver_specific_evidence(self):
        sample = {'security': 'WEP', 'signal_percent': 0, 'source': 'NetworkManager',
                  'pass': 1, 'from_cache': True}
        ap = {'ssids': ['Lab\nSignal'], 'bssid': '02:11:22:33:44:55', 'samples': [sample]}
        result = {'status': 'PARTIAL', 'access_points': [ap]}
        display = '\n'.join(wifi_lines(result))
        self.assertIn('1 seen only in cache', display)
        self.assertIn('0 WEP', display)
        self.assertIn('Lab\\nSignal', display)
        self.assertIn('0% adapter signal', display)
        self.assertIn('cached · last seen unknown', display)
        ap['samples'].append({'source': 'ESP32', 'security': 'Open', 'rssi_dbm': -66})
        display = '\n'.join(wifi_lines(result))
        self.assertIn('1 open · 0 WEP', display)
        self.assertIn('ESP32', display)
        self.assertIn('-66 dBm', display)
        self.assertIn('no link encryption advertised', display)

    def test_survey_absent_failed_and_empty_are_distinct(self):
        for status, message in [('NOT_TESTED', 'No saved Wi-Fi survey'),
                                ('UNAVAILABLE', 'coverage is incomplete'),
                                ('COMPLETE', 'No access points reported in this scan window')]:
            self.assertIn(message, '\n'.join(wifi_lines({'status': status})))

    def test_older_os_cache_pass_has_unknown_sighting_time(self):
        result = {'status': 'COMPLETE',
                  'sources': [{'source': 'Windows WLAN', 'pass': 1, 'scan_mode': 'OS cache'}],
                  'access_points': [{'samples': [{'source': 'Windows WLAN', 'pass': 1,
                                                 'observed_at': 'cache read time', 'security': 'Open'}]}]}
        display = '\n'.join(wifi_lines(result))
        self.assertIn('1 seen only in cache', display)
        self.assertNotIn('cache read time', display)
        self.assertIn('0 open', display)

    def test_hardware_shows_only_available_fields_and_preserves_zero(self):
        hw = {'connected': True, 'status': 'OK', 'last_rfid': '0x0001',
              'rfid_age_ms': 0, 'rf_subghz_rssi': 0, 'radar_presence': None}
        display = '\n'.join(hardware_lines(hw))
        self.assertIn('0x0001 · 0 ms ago', display)
        self.assertIn('0 dBm', display)
        self.assertIn('No recent ON/OFF report', display)
        hw.update(connected=False, message='Hardware telemetry is stale')
        display = '\n'.join(hardware_lines(hw))
        self.assertIn('stale', display)
        self.assertNotIn('0x0001', display)
        hw.update(connected=True, status='STOPPED')
        self.assertNotIn('0x0001', '\n'.join(hardware_lines(hw)))

    def test_rf_peak_delta_and_missing_sweeps(self):
        bins = [0]*81
        bins[2] = 5
        delta = [0]*81
        delta[79] = -7
        result = {'samples': [{'bins': bins, 'rf_dwell_us': 200}],
                  'incomplete_sweeps': 2, 'delta': delta}
        display = '\n'.join(tool_lines('rf/history', result))
        self.assertIn('5/8 windows at 2402 MHz', display)
        self.assertIn('-7 hits per 8 windows at 2479 MHz', display)
        self.assertIn('2 additional saved records', display)
        self.assertIn('2400 MHz · 0 0 5', display)
        self.assertNotIn('dBm', display)

    def test_tool_formats_preserve_observation_type_and_partial_capture(self):
        fixtures = [
            ('ble/defense', {'status': 'NOT_TESTED'}, 'No saved'),
            ('ble/defense', {'status': 'COMPLETE', 'devices': []}, '0 advertising addresses'),
            ('wireless/interfaces', {'status': 'UNAVAILABLE', 'message': 'iw unavailable'}, 'iw unavailable'),
            ('wireless/latest', {'counts': {'deauthentication': 2}, 'truncated': True}, 'limit reached'),
            ('gps/wifi-snapshot/latest', {'scan': {'access_points': []},
                                         'receiver_positions': [{'latitude': 0, 'longitude': 0}]}, 'Latitude 0°'),
            ('diagnostics/history', [{'result': {'component': 'cc1101', 'state': 'PARTIAL',
                                                'measurements': {'capture_truncated': True}}}], 'capture truncated'),
            ('system', {'battery_percent': None, 'cpu_percent': 0}, 'CPU in use · 0 %'),
        ]
        for path, result, expected in fixtures:
            with self.subTest(path=path):
                self.assertIn(expected, '\n'.join(tool_lines(path, result)))
