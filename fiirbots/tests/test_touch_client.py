import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop import Desktop


class TouchClientTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Graphical session unavailable ({exc})')
        self.root.withdraw()
        with patch.object(Desktop, 'async_request'):
            self.client = Desktop(self.root)
        self.addCleanup(self.client.close)

    def button(self, widget, label):
        for child in widget.winfo_children():
            if isinstance(child, tk.Button) and child['text'] == label:
                return child
            found = self.button(child, label)
            if found:
                return found

    def test_touch_routes_and_survey_controls(self):
        client = self.client
        with patch.object(client, 'async_request') as get, patch.object(client, 'start') as start:
            self.button(self.root, 'Scan nearby Wi-Fi').invoke()
            start.assert_called_once_with('wifi/survey', {'receiver': 'both', 'passes': 1})
            client.toggle_passes()
            client.set_receiver('ESP32 only')
            self.button(self.root, 'Scan nearby Wi-Fi').invoke()
            start.assert_called_with('wifi/survey', {'receiver': 'esp32', 'passes': 3})
            for name, path in [('Bluetooth LE', 'ble/defense'), ('GPS track', 'gps/latest'),
                               ('System info', 'system'), ('RF spectrum', 'rf/history')]:
                self.button(self.root, 'Tools').invoke()
                self.button(self.root, name).invoke()
                self.assertEqual(get.call_args.args[0], path)
            client.render({'samples': []})
            self.assertIn('No completed RF', client.output.get('1.0', 'end'))

    def test_saved_report_includes_missing_wifi_and_lan_evidence(self):
        with patch.object(self.client, 'async_request'):
            self.client.show('Report')
        self.client.render({'network': '', 'scan_at': None, 'assets': [], 'wifi_survey': {'status': 'NOT_TESTED'}})
        with tempfile.TemporaryDirectory() as folder, patch.object(Path, 'home', return_value=Path(folder)):
            self.button(self.root, 'Save report').invoke()
            report, = (Path(folder) / 'FIIRBots Reports').glob('*.txt')
            contents = report.read_text(encoding='utf-8')
            self.assertIn('Unconfigured', contents)
            self.assertIn('No saved Wi-Fi survey', contents)
