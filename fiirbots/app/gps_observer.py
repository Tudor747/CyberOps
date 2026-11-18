"""Bounded local gpsd observation with freshness checks and no device reconfiguration."""
import json
import math
import socket
import time
from datetime import datetime, timezone
from .network_engine import ScanCancelled


def fix(report, now=None):
    if not isinstance(report, dict) or report.get('class') != 'TPV' or report.get('mode') not in (2, 3):
        return None
    if report.get('status') in (6, 7, 8):  # estimated / time-only / simulated
        return None
    try:
        when = datetime.fromisoformat(report['time'].replace('Z', '+00:00'))
        age = ((now or datetime.now(timezone.utc)) - when).total_seconds()
        lat, lon = report['lat'], report['lon']
        if type(lat) not in (int, float) or type(lon) not in (int, float):
            return None
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180 or not -2 <= age <= 15:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    result = {'latitude': lat, 'longitude': lon, 'time': when.isoformat(), 'mode': report['mode']}
    for source, target in [('altMSL', 'altitude_msl_m'), ('speed', 'speed_m_s'), ('track', 'course_over_ground_deg')]:
        value = report.get(source)
        if type(value) in (int, float) and math.isfinite(value):
            if source == 'track' and not 0 <= value < 360 or source == 'speed' and value < 0:
                continue
            result[target] = value
    return result


def observe(cancel, duration=5):
    if not 1 <= duration <= 30:
        raise ValueError('GPS observation duration must be 1–30 seconds')
    if cancel.is_set():
        raise ScanCancelled()
    points, buffer, version_ok = {}, b'', False
    deadline = time.monotonic() + duration
    try:
        with socket.create_connection(('127.0.0.1', 2947), timeout=2) as connection:
            connection.settimeout(.2)
            connection.sendall(b'?WATCH={"enable":true,"json":true};\n')
            while time.monotonic() < deadline:
                if cancel.is_set():
                    raise ScanCancelled()
                try:
                    chunk = connection.recv(16384)
                except socket.timeout:
                    continue
                if not chunk:
                    raise ValueError('gpsd disconnected before observation completed')
                buffer += chunk
                if len(buffer) > 65536:
                    raise ValueError('Oversized gpsd response')
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        report = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if not isinstance(report, dict):
                        continue
                    if report.get('class') == 'VERSION':
                        if report.get('proto_major') != 3:
                            raise ValueError('Unsupported gpsd protocol version')
                        version_ok = True
                    point = fix(report) if version_ok else None
                    if point and len(points) < 256:
                        points[point['time']] = point
    except OSError as exc:
        raise ValueError('Local gpsd unavailable; configure a working GPS receiver and gpsd on 127.0.0.1:2947') from exc
    if cancel.is_set():
        raise ScanCancelled()
    if not points:
        raise ValueError('No fresh GPS fix received; verify receiver, sky view and system clock')
    return {'status': 'COMPLETE', 'points': sorted(points.values(), key=lambda p: p['time']),
            'finished_at': datetime.now(timezone.utc).isoformat(),
            'message': 'Course over ground is a movement direction, not a stationary magnetic compass.'}


def geojson(tracks, waypoints):
    features = []
    for row in tracks:
        points = row['points']
        if not points:
            continue
        coordinates = [[p['longitude'], p['latitude']] for p in points]
        geometry = {'type': 'LineString', 'coordinates': coordinates} if len(points) > 1 else {'type': 'Point', 'coordinates': coordinates[0]}
        features.append({'type': 'Feature', 'geometry': geometry,
                         'properties': {'kind': 'track', 'times': [p['time'] for p in points]}})
    for row in waypoints:
        point = row['point']
        features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [point['longitude'], point['latitude']]},
                         'properties': {'kind': 'waypoint', 'label': row['label'], 'time': point['time']}})
    return {'type': 'FeatureCollection', 'features': features}
