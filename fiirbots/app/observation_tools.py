"""Persistent BLE inventory and RF baselines derived only from real samples."""
import json


def latest(db, kind):
    rows = db.rows('SELECT id,payload_data,timestamp FROM hardware_events WHERE event_type=? ORDER BY id DESC LIMIT 1', (kind,))
    if not rows:
        return None
    row = rows[0]
    return {'id': row['id'], 'recorded_at': row['timestamp'], **json.loads(row['payload_data'])}


def ble_comparison(db):
    scan = latest(db, 'BLE_SCAN')
    baseline = latest(db, 'BLE_BASELINE')
    devices = {r['address']: r for r in (scan or {}).get('devices', [])}
    known = {r['address']: r for r in (baseline or {}).get('devices', [])}
    rows = []
    for address, observed in devices.items():
        expected = known.get(address)
        changed = expected and (set(expected.get('service_uuids', [])) != set(observed.get('service_uuids', []))
                                or expected.get('name') != observed.get('name'))
        rows.append({**observed, 'comparison': 'UNREGISTERED' if expected is None else 'CHANGED' if changed else 'KNOWN'})
    return {'status': 'COMPLETE' if scan else 'NOT_TESTED', 'scan_id': (scan or {}).get('id'),
            'finished_at': (scan or {}).get('finished_at'), 'baseline_id': (baseline or {}).get('id'),
            'devices': rows, 'not_observed': [v for k, v in known.items() if k not in devices],
            'message': 'Addresses can rotate; missing advertisements and changed fields are not proof of an attack. Baseline enrollment is explicit.'}


def valid_bins(value):
    return isinstance(value, list) and len(value) == 81 and all(type(v) is int and 0 <= v <= 8 for v in value)


def rf_history(db):
    rows = db.rows("SELECT id,payload_data,timestamp FROM hardware_events WHERE event_type='RF_SWEEP' ORDER BY id DESC LIMIT 60")
    samples = []
    for row in reversed(rows):
        payload = json.loads(row['payload_data'])
        if valid_bins(payload.get('bins')):
            samples.append({'id': row['id'], 'recorded_at': row['timestamp'], 'bins': payload['bins']})
    baseline = latest(db, 'RF_BASELINE')
    delta = [v - b for v, b in zip(samples[-1]['bins'], baseline['bins'])] if samples and baseline else None
    return {'samples': samples, 'baseline': baseline, 'delta': delta,
            'frequency_start_mhz': 2400, 'frequency_step_mhz': 1,
            'message': 'Historical carrier occupancy (0–8 detections), not dBm or decoded Wi-Fi. Timestamps identify old samples; missing intervals are not zero readings.'}
