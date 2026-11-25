import json
import unittest
from unittest.mock import Mock

from app.esp_packet_monitor import COUNTERS, capture
from app.serial_link import decode_response
from app.touch_evidence import tool_lines


class PacketMonitorTests(unittest.TestCase):
    def test_live_and_final_counts_exclude_subtype_double_counting(self):
        link = Mock()
        link.snapshot.return_value = {'connected': True}
        scan_id = None

        def respond(command, **params):
            nonlocal scan_id
            if command == 'WIFI_MONITOR_START':
                scan_id = params['scan_id']
            self.assertEqual(scan_id, params['scan_id'])
            complete = command == 'WIFI_MONITOR_STATUS'
            counts = dict.fromkeys(COUNTERS, 0)
            if complete:
                counts.update(management=30, data=20, beacon=25)
            sample = {'request_id': 'req', 'status': 'WIFI_MONITOR', 'scan_id': scan_id,
                      'monitor_state': 'COMPLETE' if complete else 'RUNNING', 'channel': 6,
                      'elapsed_ms': 1000 if complete else 0, 'counts': counts}
            return decode_response(json.dumps(sample), 'req')

        link.request.side_effect = respond
        cancel = Mock()
        cancel.is_set.return_value = cancel.wait.return_value = False
        progress = Mock()
        result = capture(link, 6, 1, cancel, progress)
        progress.assert_called_once_with(1000, 50, 50)
        self.assertIn('Beacon rate · 25.0/s', tool_lines('wireless/esp-monitor/latest', result))
        self.assertEqual(link.request.call_args.args, ('WIFI_MONITOR_CANCEL',))

    def test_exercises_are_labelled_simulated(self):
        for scenario in ('beacon', 'disconnect'):
            lines = tool_lines('lab/wifi-exercise', {'scenario': scenario})
            self.assertIn('Simulated exercise', lines[0])
            self.assertTrue(lines[-1].startswith('Next check'))
