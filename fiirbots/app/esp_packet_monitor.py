"""Collect receive-only frame counters from the ESP32 on a single channel."""
import time
from uuid import uuid4

from .network_engine import ScanCancelled
from .wifi_survey import timestamp

FRAME_TYPES = ('management', 'data', 'control', 'other')
COUNTERS = (*FRAME_TYPES, 'beacon', 'deauthentication', 'disassociation', 'probe_request', 'probe_response')


def capture(link, channel, duration_s, cancel, progress):
    if not link.snapshot().get('connected'):
        raise ValueError('ESP32 disconnected. Check the USB connection.')
    if cancel.is_set():
        raise ScanCancelled()
    scan_id = uuid4().hex
    previous_ms = previous_total = 0
    try:
        sample = link.request('WIFI_MONITOR_START', scan_id=scan_id, channel=channel, duration_s=duration_s)
        deadline = time.monotonic() + duration_s + 4
        while not cancel.is_set():
            state = sample.get('monitor_state')
            if sample.get('status') != 'WIFI_MONITOR' or sample.get('scan_id') != scan_id:
                raise ValueError('ESP32 did not return the requested monitor session')
            if state not in ('RUNNING', 'COMPLETE'):
                raise ValueError(f'ESP32 monitor ended with status {state}')
            elapsed = sample.get('elapsed_ms')
            counts = sample.get('counts')
            if (sample.get('channel') != channel or type(elapsed) is not int
                    or not previous_ms <= elapsed <= (duration_s + 3) * 1000
                    or not isinstance(counts, dict)
                    or any(type(counts.get(key)) is not int or not 0 <= counts[key] <= 0xffffffff
                           for key in COUNTERS)):
                raise ValueError('Invalid ESP32 frame counters')
            counts = {key: counts[key] for key in COUNTERS}
            total = sum(counts[key] for key in FRAME_TYPES)
            if total < previous_total:
                raise ValueError('ESP32 frame counter reset during capture')
            if elapsed > previous_ms:
                progress(elapsed, total, round((total - previous_total) * 1000 / (elapsed - previous_ms)))
            previous_ms, previous_total = elapsed, total
            if state == 'COMPLETE':
                return {'status': 'COMPLETE', 'interface': 'ESP32 via USB', 'channel': channel,
                        'duration_s': elapsed / 1000, 'finished_at': timestamp(), 'counts': counts}
            if time.monotonic() >= deadline:
                raise ValueError('ESP32 monitor timed out')
            if cancel.wait(1):
                break
            sample = link.request('WIFI_MONITOR_STATUS', scan_id=scan_id)
        raise ScanCancelled()
    except OSError as exc:
        raise ValueError('ESP32 monitor connection interrupted. Check USB and firmware.') from exc
    finally:
        try:
            link.request('WIFI_MONITOR_CANCEL', scan_id=scan_id)
        except (OSError, ValueError):
            pass
