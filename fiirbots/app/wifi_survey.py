"""Collect a bounded set of Wi-Fi scans and retain the evidence for each BSSID."""
from collections import defaultdict
from datetime import datetime, timezone
import re
import time
from uuid import uuid4

from . import desktop_tools
from .network_engine import ScanCancelled


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def esp_observation(link, cancel):
    scan_id = uuid4().hex
    source = {'source': 'ESP32', 'scan_mode': 'Passive, 2.4 GHz'}
    rows = []
    try:
        if not link.snapshot().get('connected'):
            raise ValueError('ESP32 disconnected. Check the configured serial port and USB connection.')
        if cancel.is_set():
            raise ScanCancelled()
        started = link.request('WIFI_SCAN_START', scan_id=scan_id)
        if started.get('scan_id') != scan_id or started.get('status') != 'WIFI_SCAN':
            raise ValueError('ESP32 did not start the requested Wi-Fi scan')
        deadline = time.monotonic() + 15
        expected = None
        while True:
            if cancel.is_set():
                raise ScanCancelled()
            page = link.request('WIFI_SCAN_PAGE', scan_id=scan_id, offset=len(rows))
            if page.get('status') != 'WIFI_SCAN' or page.get('scan_id') != scan_id:
                raise ValueError('ESP32 scan interrupted or replaced')
            if page.get('state') == 'scanning':
                if expected is not None or time.monotonic() >= deadline:
                    raise ValueError('ESP32 scan timed out or restarted')
                cancel.wait(.25)
                continue
            total, networks = page.get('total'), page.get('networks')
            if (page.get('state') != 'complete' or type(total) is not int or not 0 <= total <= 65535
                    or expected not in (None, total) or page.get('offset') != len(rows)
                    or not isinstance(networks, list) or len(networks) > 12):
                raise ValueError('Invalid ESP32 scan page')
            expected = total
            for row in networks:
                if (not isinstance(row, dict) or not re.fullmatch(r'(?:[\da-fA-F]{2}:){5}[\da-fA-F]{2}', str(row.get('bssid')))
                        or not isinstance(row.get('ssid'), str) or type(row.get('channel')) is not int
                        or not 1 <= row['channel'] <= 14 or type(row.get('rssi_dbm')) is not int
                        or not -127 <= row['rssi_dbm'] <= 0 or not isinstance(row.get('security'), str)):
                    raise ValueError('Invalid access point in ESP32 scan page')
                if 'ssid_hex' in row:
                    if not isinstance(row['ssid_hex'], str) or not re.fullmatch(r'(?:[a-fA-F0-9]{2}){0,32}', row['ssid_hex']):
                        raise ValueError('Invalid ESP32 SSID bytes')
                    row['ssid'] = bytes.fromhex(row['ssid_hex']).decode('utf-8', errors='backslashreplace')
            rows.extend(networks)
            if len(rows) == total and 'next_offset' in page and page['next_offset'] is None:
                break
            if not networks or len(rows) >= total or page.get('next_offset') != len(rows):
                raise ValueError('Incomplete ESP32 scan pagination')
        return {**source, 'status': 'OUTPUT', 'access_points': rows, 'observed_at': timestamp(),
                'message': 'Scan completed on the integrated Wi-Fi radio.'}
    except (OSError, ValueError) as exc:
        return {**source, 'status': 'UNAVAILABLE', 'access_points': [], 'message': str(exc)}
    finally:
        # The firmware also expires abandoned records after heartbeat loss or inactivity.
        if link.snapshot().get('connected'):
            try:
                link.request('WIFI_SCAN_CANCEL', scan_id=scan_id)
            except (OSError, ValueError):
                pass


def summarize(observations):
    by_bssid = defaultdict(list)
    for batch in observations:
        for ap in batch['access_points']:
            by_bssid[ap['bssid'].upper()].append({**ap, 'source': batch['source'], 'pass': batch['pass'],
                                                  'observed_at': None if ap.get('from_cache') else batch.get('observed_at')})
    points = []
    names = defaultdict(set)
    open_count = wep_count = 0
    for bssid, samples in sorted(by_bssid.items()):
        observed_names = sorted({s['ssid'] for s in samples if s.get('ssid')})
        for name in observed_names:
            names[name].add(bssid)
        security = {str(s.get('security')).upper() for s in samples}
        open_count += 'OPEN' in security
        wep_count += any('WEP' in label.split() or label.startswith('WEP-') for label in security)
        points.append({'bssid': bssid, 'ssids': observed_names, 'samples': samples})
    return points, {'named_ssids': len(names), 'shared_ssids': sum(len(aps) > 1 for aps in names.values()),
                    'open_bssids': open_count, 'wep_bssids': wep_count}


def collect(link, receivers, passes, cancel, progress):
    observations = []
    for index in range(1, passes + 1):
        for receiver in receivers:
            if cancel.is_set():
                raise ScanCancelled()
            progress(index, receiver)
            if receiver == 'Host':
                driver = desktop_tools.pi_driver_observation()
                if driver and driver['status'] == 'OUTPUT' and driver['access_points']:
                    result = driver
                else:
                    result = desktop_tools.wifi_observation()
                    if driver and driver['status'] == 'UNAVAILABLE':
                        result['message'] += ' Direct wlan0 scan unavailable: ' + driver['message']
            else:
                result = esp_observation(link, cancel)
            observations.append({**result, 'pass': index, 'receiver': receiver})
        if index < passes and cancel.wait(2):
            raise ScanCancelled()
    if cancel.is_set():
        raise ScanCancelled()
    points, summary = summarize(observations)
    statuses = {item['status'] for item in observations}
    status = 'COMPLETE' if statuses == {'OUTPUT'} else 'UNAVAILABLE' if statuses == {'UNAVAILABLE'} else 'PARTIAL'
    sources = []
    for item in observations:
        meta = {k: v for k, v in item.items() if k not in ('access_points', 'output')}
        meta['observed_rows'] = len(item['access_points']) if item['status'] != 'UNAVAILABLE' else None
        if item['status'] != 'OUTPUT' and item.get('output'):
            meta['output'] = item['output']
        sources.append(meta)
    return {'status': status, 'finished_at': timestamp(), 'passes': passes, 'sources': sources,
            'access_points': points, 'summary': summary}
