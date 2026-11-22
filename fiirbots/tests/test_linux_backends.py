"""Offline Linux backend contracts; these tests do not validate Pi drivers."""
import ipaddress
import subprocess
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.desktop_tools import wifi_observation
from app.network_engine import discover, ScanCancelled


class LinuxWifiTests(unittest.TestCase):
    def observe(self, **kwargs):
        with patch('app.desktop_tools.platform.system', return_value='Linux'), \
             patch('app.desktop_tools.subprocess.run', **kwargs) as run:
            result = wifi_observation()
        return result, run

    def test_wifi_preserves_os_observations(self):
        # Synthetic observations. The same SSID can refer to multiple radios.
        output = (rb'wlan0:aa\:bb\:cc\:dd\:ee\:01:4C4142:6:2437 MHz:80:WPA2:(none):psk' + b'\n'
                  + rb'wlan0:aa\:bb\:cc\:dd\:ee\:02:4C4142:36:5180 MHz:2:WPA2:(none):psk' + b'\n'
                  + rb'wlan1:aa\:bb\:cc\:dd\:ee\:02::36:5180 MHz:0::(none):(none)')
        result, run = self.observe(return_value=SimpleNamespace(
            returncode=0, stdout=output, stderr=b''))
        self.assertEqual(result['status'], 'OUTPUT')
        self.assertEqual(result['output'], output.decode())
        rows = result['access_points']
        self.assertEqual([row['ssid'] for row in rows], ['LAB', 'LAB', ''])
        self.assertEqual(rows[1]['bssid'], 'AA:BB:CC:DD:EE:02')
        self.assertEqual(rows[1]['frequency_mhz'], 5180)
        self.assertEqual(rows[2]['interface'], 'wlan1')
        self.assertEqual(rows[2]['signal_percent'], 0)
        self.assertEqual(rows[2]['security'], 'Open')
        self.assertIsNone(rows[2]['rssi_dbm'])
        self.assertEqual(run.call_args.args[0][0], 'nmcli')
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_permission_denial_is_not_success(self):
        result, _ = self.observe(return_value=SimpleNamespace(
            returncode=1, stdout=b'', stderr=b'Not authorized to scan Wi-Fi'))
        self.assertEqual(result['status'], 'UNAVAILABLE')
        self.assertIn('Not authorized', result['output'])

    def test_missing_nmcli_and_timeout_are_unavailable(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired('nmcli', 20)):
            with self.subTest(error=type(error).__name__):
                result, _ = self.observe(side_effect=error)
                self.assertEqual(result['status'], 'UNAVAILABLE')

    def test_empty_requires_an_available_wifi_adapter(self):
        empty = SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        for state, expected in [(b'wifi:disconnected', 'OUTPUT'), (b'wifi:unavailable', 'UNAVAILABLE'),
                                (b'ethernet:connected', 'UNAVAILABLE')]:
            devices = SimpleNamespace(returncode=0, stdout=state, stderr=b'')
            with self.subTest(state=state):
                result, _ = self.observe(side_effect=[empty, devices])
                self.assertEqual(result['status'], expected)

    def test_partial_and_unreadable_are_explicit(self):
        output = rb'i\:1:00\:00\:00\:00\:00\:0a:FF:1:2412 MHz:35::(none):unknown' + b'\ninvalid'
        result, _ = self.observe(return_value=SimpleNamespace(returncode=0, stdout=output, stderr=b''))
        self.assertEqual(result['status'], 'PARTIAL')
        point, = result['access_points']
        self.assertEqual(point['interface'], 'i:1')
        self.assertEqual(point['ssid_hex'], 'FF')
        self.assertIsNone(point['ssid'])
        self.assertIsNone(point['security'])

    def test_dense_scan_is_not_clipped(self):
        output = '\n'.join(fr'wlan0:aa\:bb\:cc\:dd\:{i // 256:02x}\:{i % 256:02x}:41:6:2437 MHz:1:WPA2:(none):psk'
                           for i in range(1000)).encode()
        self.assertGreater(len(output), 50000)
        result, _ = self.observe(return_value=SimpleNamespace(returncode=0, stdout=output, stderr=b''))
        self.assertEqual(len(result['access_points']), 1000)
        self.assertEqual(result['output'], output.decode())


class LinuxDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.network = ipaddress.IPv4Network('192.168.50.0/24')
        self.cancel = threading.Event()
        self.scapy = MagicMock()

    def discover(self):
        with patch('app.network_engine.sys.platform', 'linux'), \
             patch.dict('sys.modules', {'scapy.all': self.scapy}):
            return discover(self.network, 'eth0', self.cancel)

    def test_discovery_filters_out_of_scope_and_normalizes_mac(self):
        self.scapy.srp.return_value = ([(None, SimpleNamespace(
            psrc=ip, hwsrc='aa:bb:cc:dd:ee:ff')) for ip in
            ('192.168.50.2', '192.168.51.2')], [])
        self.assertEqual(self.discover(), {'192.168.50.2': 'AA:BB:CC:DD:EE:FF'})
        self.assertEqual(self.scapy.srp.call_args.kwargs['iface'], 'eth0')

    def test_missing_raw_packet_permission_is_an_error(self):
        self.scapy.srp.side_effect = PermissionError('CAP_NET_RAW missing')
        with self.assertRaises(PermissionError):
            self.discover()

    def test_cancelled_discovery_sends_nothing(self):
        self.cancel.set()
        with self.assertRaises(ScanCancelled):
            self.discover()
        self.scapy.srp.assert_not_called()

    def test_cancellation_discards_received_results(self):
        def receive(*args, **kwargs):
            self.cancel.set()
            return [(None, SimpleNamespace(psrc='192.168.50.2', hwsrc='aa:bb:cc:dd:ee:ff'))], []
        self.scapy.srp.side_effect = receive
        with self.assertRaises(ScanCancelled):
            self.discover()
