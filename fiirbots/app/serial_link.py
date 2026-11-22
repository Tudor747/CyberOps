import json
import threading
import time
from uuid import uuid4


def decode_response(line, request_id):
    if len(line) > 16384:
        raise ValueError('Serial frame too large')
    data = json.loads(line)
    if not isinstance(data, dict) or data.get('request_id') != request_id:
        raise ValueError('Unmatched serial response')
    if data.get('status') == 'ERROR':
        return data
    if data.get('status') == 'WIFI_SCAN':
        if not isinstance(data.get('scan_id'), str) or data.get('state') not in ('scanning', 'complete'):
            raise ValueError('Invalid Wi-Fi scan response')
        return data
    if data.get('status') == 'DIAGNOSTIC':
        result = data.get('test')
        if not isinstance(result, dict) or result.get('state') not in ('RUNNING','PASS','FAIL','NO_SIGNAL','PARTIAL','CANCELLED'):
            raise ValueError('Invalid diagnostic result')
        if not isinstance(result.get('test_id'), str) or not isinstance(result.get('measurements'), dict):
            raise ValueError('Missing diagnostic identity or measurements')
        return data
    if data.get('status') not in ('OK', 'STOPPED'):
        raise ValueError('ESP32 reported an error')
    if data['status'] == 'OK':
        required = {'radar_presence', 'last_rfid', 'ir_activity', 'rf_subghz_rssi', 'nrf24_status'}
        if not required.issubset(data):
            raise ValueError('Incomplete hardware sample')
        if data['radar_presence'] is not None and type(data['radar_presence']) is not bool:
            raise ValueError('Invalid radar state')
        if type(data['ir_activity']) is not bool:
            raise ValueError('Invalid IR state')
        if data['rf_subghz_rssi'] is not None and (type(data['rf_subghz_rssi']) is not int or not -160 <= data['rf_subghz_rssi'] <= 20):
            raise ValueError('Invalid RSSI')
        for name in ('last_rfid', 'ir_last_code', 'nrf24_status', 'ethernet_status'):
            if data.get(name) is not None and (not isinstance(data[name], str) or len(data[name]) > 128):
                raise ValueError('Invalid hardware label')
        bins = data.get('rf_bins')
        if bins is not None and (not isinstance(bins, list) or len(bins) != 81 or any(type(v) is not int or not 0 <= v <= 8 for v in bins)):
            raise ValueError('Invalid RF samples')
    return data


class SerialLink:
    def __init__(self, port, db, interlocked):
        self.port, self.db, self.interlocked = port, db, interlocked
        self.shutdown = threading.Event()
        self.io_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.testing = threading.Event()
        self.connection = None
        self.thread = None
        self.state = {'connected': False, 'message': 'Serial port not configured' if not port else 'Connecting'}

    def snapshot(self):
        with self.state_lock:
            state = dict(self.state)
        if state.get('received_at') and time.time() - state['received_at'] > 4:
            return {'connected': False, 'message': 'Hardware telemetry is stale'}
        return state

    def set_state(self, state):
        with self.state_lock:
            self.state = state

    def request(self, command, **params):
        with self.io_lock:
            if not self.connection:
                raise OSError('ESP32 disconnected')
            if command == 'POLL_HARDWARE' and self.testing.is_set():
                return {'status': 'STOPPED'}
            if command in ('POLL_HARDWARE', 'TEST_START', 'WIFI_SCAN_START', 'WIFI_SCAN_PAGE') and self.interlocked():
                command = 'STOP'
            request_id = uuid4().hex[:12]
            self.connection.write((json.dumps({**params, 'cmd': command, 'request_id': request_id}) + '\n').encode())
            deadline = time.monotonic() + 1.5
            frame = bytearray()
            oversized = False
            while time.monotonic() < deadline:
                chunk = self.connection.read_until(b'\n', 16385)
                if not chunk:
                    continue
                if not oversized:
                    frame.extend(chunk)
                    oversized = len(frame) > 16384
                if not chunk.endswith(b'\n'):
                    continue
                line = bytes(frame)
                frame.clear()
                if oversized:
                    oversized = False
                    continue
                try:
                    response = decode_response(line, request_id)
                except (ValueError, UnicodeError):
                    continue  # Ignore ESP boot text, partial frames and stale replies.
                if response['status'] == 'ERROR':
                    raise ValueError(str(response.get('message', 'ESP32 rejected command'))[:200])
                if response['status'] == 'WIFI_SCAN' and command not in ('WIFI_SCAN_START', 'WIFI_SCAN_PAGE'):
                    raise ValueError('Unexpected serial response for command')
                return response
            raise TimeoutError('ESP32 response timed out')

    def stop_hardware(self):
        try:
            self.request('STOP')
        except (OSError, ValueError):
            pass  # Firmware also stops on heartbeat loss.

    def start(self):
        if self.port:
            self.thread = threading.Thread(target=self.run, daemon=True, name='esp32-link')
            self.thread.start()

    def run(self):
        last_log = 0
        last_events = {}
        while not self.shutdown.is_set():
            try:
                import serial
                with self.io_lock:
                    self.connection = serial.Serial(self.port, 115200, timeout=0.2, write_timeout=0.5)
                if self.shutdown.wait(2):
                    break
                while not self.shutdown.is_set():
                    if self.testing.is_set():
                        self.shutdown.wait(0.1)
                        continue
                    held = self.interlocked()
                    response = self.request('STOP' if held else 'POLL_HARDWARE')
                    response.pop('request_id', None)
                    self.set_state({'connected': True, 'received_at': time.time(), **response})
                    if response['status'] == 'OK':
                        samples = {
                            'LD2420_Radar': ('PRESENCE', response.get('radar_presence')),
                            'RC522_RFID': ('RFID_READ', response.get('last_rfid')),
                            'IR': ('IR_CAPTURE', response.get('ir_last_code')),
                        }
                        for module, (kind, value) in samples.items():
                            if value is not None and last_events.get(module) != value:
                                self.db.event(module, kind, {'value': value})
                                last_events[module] = value
                        if time.monotonic() - last_log >= 10:
                            self.db.event('nRF24', 'RF_SWEEP', {'bins': response.get('rf_bins'), 'status': response.get('nrf24_status'),
                                                              'rf_dwell_us': response.get('rf_dwell_us')})
                            self.db.event('CC1101', 'RSSI', {'dbm': response.get('rf_subghz_rssi')})
                            last_log = time.monotonic()
                    if self.shutdown.wait(1):
                        break
            except Exception:
                self.set_state({'connected': False, 'message': 'ESP32 unavailable; check USB and configured serial port'})
            finally:
                with self.io_lock:
                    if self.connection:
                        self.connection.close()
                    self.connection = None
            self.shutdown.wait(2)

    def close(self):
        self.shutdown.set()
        self.stop_hardware()
        if self.thread:
            self.thread.join(timeout=3)
