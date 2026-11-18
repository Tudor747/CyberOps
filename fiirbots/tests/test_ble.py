import threading
import unittest
from types import SimpleNamespace
from app.ble_scanner import observe
from app.network_engine import ScanCancelled


class BLETests(unittest.IsolatedAsyncioTestCase):
    async def test_observation_and_cleanup(self):
        closed = []
        class Scanner:
            def __init__(self, detection_callback): self.callback = detection_callback
            async def __aenter__(self):
                for signal in (-70, -60):
                    self.callback(SimpleNamespace(address='AA:BB', name='Device'),
                        SimpleNamespace(local_name='Lab', rssi=signal, service_uuids=['test']))
                return self
            async def __aexit__(self, *args): closed.append(True)
        result = await observe(threading.Event(), .001, Scanner)
        self.assertEqual(len(result['devices']), 1)
        self.assertEqual(result['devices'][0]['rssi_dbm'], -60)
        self.assertEqual(result['devices'][0]['name'], 'Lab')
        self.assertEqual(closed, [True])

    async def test_cancel_stops_scanner(self):
        cancel = threading.Event()
        closed = []
        class Scanner:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): cancel.set(); return self
            async def __aexit__(self, *args): closed.append(True)
        with self.assertRaises(ScanCancelled):
            await observe(cancel, .01, Scanner)
        self.assertEqual(closed, [True])

    async def test_unavailable_is_not_empty_success(self):
        class Scanner:
            def __init__(self, **kwargs): raise OSError('adapter unavailable')
        with self.assertRaisesRegex(ValueError, 'BLE scan unavailable'):
            await observe(threading.Event(), .01, Scanner)

    async def test_pre_cancel_never_opens_radio(self):
        cancel = threading.Event(); cancel.set()
        def forbidden(**kwargs): self.fail('Radio opened after cancellation')
        with self.assertRaises(ScanCancelled):
            await observe(cancel, .01, forbidden)
