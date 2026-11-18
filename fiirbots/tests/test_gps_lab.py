import threading
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from app import gps_observer, lab_radio
from app.network_engine import ScanCancelled


class GPSTests(unittest.TestCase):
    def test_fix_requires_real_fresh_finite_coordinates(self):
        now = datetime.now(timezone.utc)
        report = {'class': 'TPV', 'mode': 3, 'time': now.isoformat(), 'lat': 44.4, 'lon': 26.1, 'track': 90, 'speed': 2}
        self.assertEqual(gps_observer.fix(report, now)['course_over_ground_deg'], 90)
        for changes in ({'lat': float('nan')}, {'lon': 181}, {'mode': 1}, {'status': 8},
                        {'time': (now-timedelta(seconds=30)).isoformat()}, {'time': 'invalid'}, {'lat': True}):
            with self.subTest(changes=changes): self.assertIsNone(gps_observer.fix({**report, **changes}, now))

    def test_geojson_uses_longitude_first(self):
        point = {'longitude': 26.1, 'latitude': 44.4, 'time': 'test'}
        result = gps_observer.geojson([{'points': [point]}], [{'point': point, 'label': 'Lab'}])
        self.assertEqual(result['features'][0]['geometry'], {'type': 'Point', 'coordinates': [26.1, 44.4]})
        self.assertEqual(result['features'][1]['properties']['label'], 'Lab')

    def test_gps_cancel_opens_no_connection(self):
        cancel = threading.Event(); cancel.set()
        with patch('app.gps_observer.socket.create_connection') as connect:
            with self.assertRaises(ScanCancelled): gps_observer.observe(cancel)
            connect.assert_not_called()

    def test_missing_gps_is_not_success(self):
        with patch('app.gps_observer.socket.create_connection', side_effect=ConnectionRefusedError):
            with self.assertRaisesRegex(ValueError, 'gpsd unavailable'):
                gps_observer.observe(threading.Event())


class LabTests(unittest.TestCase):
    bssid = '00:11:22:33:44:55'
    client = '00:11:22:33:44:66'

    def scan(self):
        return {'id': 1, 'interface': 'mon0', 'finished_at': datetime.now(timezone.utc).isoformat(),
                'clients': [{'bssid': self.bssid, 'client': self.client}]}

    def test_only_recent_observed_unicast_pairs(self):
        scan = self.scan()
        lab_radio.validate_target(scan, 1, 'mon0', self.bssid, self.client)
        for bssid, client in [(self.bssid, 'ff:ff:ff:ff:ff:ff'), (self.bssid, '00:11:22:33:44:77'), (self.bssid, self.bssid)]:
            with self.assertRaises(ValueError): lab_radio.validate_target(scan, 1, 'mon0', bssid, client)
        scan['finished_at'] = (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()
        with self.assertRaises(ValueError): lab_radio.validate_target(scan, 1, 'mon0', self.bssid, self.client)

    def test_bounded_submission_reports_no_verified_effect(self):
        cancel = threading.Event()
        with patch('app.wireless_monitor.interfaces', return_value={'interfaces': [{'name': 'mon0', 'mode': 'monitor', 'channel': 6}]}), \
             patch('scapy.all.conf.L2socket') as sender, patch.object(cancel, 'wait', return_value=False):
            result = lab_radio.deauthenticate('mon0', self.bssid, self.client, 2, 6, cancel)
            self.assertEqual(sender.return_value.__enter__.return_value.send.call_count, 2)
            packet = sender.return_value.__enter__.return_value.send.call_args.args[0]
            self.assertEqual(packet.addr1, self.client)
            self.assertEqual(packet.addr2, self.bssid)
            self.assertEqual(result['effect'], 'UNVERIFIED')
            self.assertEqual(result['frames_submitted'], 2)

    def test_channel_mismatch_opens_no_socket(self):
        with patch('app.wireless_monitor.interfaces', return_value={'interfaces': [{'name': 'mon0', 'mode': 'monitor', 'channel': 11}]}), \
             patch('scapy.all.conf.L2socket') as sender:
            with self.assertRaises(ValueError): lab_radio.deauthenticate('mon0', self.bssid, self.client, 1, 6, threading.Event())
            sender.assert_not_called()

    def test_cancel_before_transmission_opens_no_socket(self):
        cancel = threading.Event(); cancel.set()
        with patch('app.wireless_monitor.interfaces', return_value={'interfaces': [{'name': 'mon0', 'mode': 'monitor', 'channel': 6}]}), \
             patch('scapy.all.conf.L2socket') as sender:
            with self.assertRaises(ScanCancelled): lab_radio.deauthenticate('mon0', self.bssid, self.client, 1, 6, cancel)
            sender.assert_not_called()

    def test_named_probe_required_for_beacon_test(self):
        scan = self.scan()
        scan['probes'] = [{'source': self.client, 'ssid': 'Lab'}]
        lab_radio.validate_probe(scan, 1, 'mon0', self.client, 'Lab')
        for name in ('', 'Other', 'x'*33):
            with self.assertRaises(ValueError): lab_radio.validate_probe(scan, 1, 'mon0', self.client, name)

    def test_beacon_is_bounded_and_does_not_claim_an_ap(self):
        cancel = threading.Event()
        with patch('app.wireless_monitor.interfaces', return_value={'interfaces': [{'name': 'mon0', 'mode': 'monitor', 'channel': 6}]}), \
             patch('scapy.all.conf.L2socket') as sender, patch.object(cancel, 'wait', return_value=False):
            result = lab_radio.advertise_probe('mon0', 'Lab', 2, 6, cancel)
            self.assertEqual(sender.return_value.__enter__.return_value.send.call_count, 2)
            self.assertTrue(result['test_bssid'].startswith('02:'))
            self.assertEqual(result['effect'], 'UNVERIFIED')
            self.assertIn('No usable AP', result['message'])
