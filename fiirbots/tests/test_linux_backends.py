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
        output = b'SSID BSSID CHAN SIGNAL SECURITY\nLAB aa:bb:cc:dd:ee:ff 6 80 WPA2'
        result, run = self.observe(return_value=SimpleNamespace(
            returncode=0, stdout=output, stderr=b''))
        self.assertEqual(result['status'], 'OUTPUT')
        self.assertEqual(result['output'], output.decode())
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
