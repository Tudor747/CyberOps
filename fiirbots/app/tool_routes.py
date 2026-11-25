from typing import Literal
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from fastapi import APIRouter
from pydantic import Field
from .models import StrictModel
from . import esp_packet_monitor, observation_tools, wireless_monitor, gps_observer, wifi_survey
from .network_engine import ScanCancelled


class CaptureRequest(StrictModel):
    interface: str = Field(min_length=1, max_length=64)
    duration_s: int = Field(default=10, ge=1, le=30)


class EspMonitorRequest(StrictModel):
    channel: int = Field(ge=1, le=13)
    duration_s: int = Field(default=10, ge=1, le=30)


class WifiSurveyRequest(StrictModel):
    receiver: Literal['both', 'host', 'esp32'] = 'both'
    passes: Literal[1, 3] = 1


class Enrollment(StrictModel):
    scan_id: int = Field(gt=0)
    addresses: list[str] = Field(min_length=1, max_length=512)


class GPSRequest(StrictModel):
    duration_s: int = Field(default=5, ge=1, le=30)


class WaypointRequest(StrictModel):
    track_id: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=80)


class LabDeauthRequest(StrictModel):
    scan_id: int = Field(gt=0)
    interface: str = Field(min_length=1, max_length=64)
    bssid: str = Field(min_length=17, max_length=17)
    client: str = Field(min_length=17, max_length=17)
    frames: int = Field(default=1, ge=1, le=10)
    isolated_lab_confirmed: bool


class LabBeaconRequest(StrictModel):
    scan_id: int = Field(gt=0)
    interface: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=17, max_length=17)
    ssid: str = Field(min_length=1, max_length=32)
    frames: int = Field(default=1, ge=1, le=10)
    isolated_lab_confirmed: bool


def router(controller, operation):
    routes = APIRouter()
    lab_actions = APIRouter()
    db = controller.db

    def idle():
        if controller.locked or (controller.worker and controller.worker.is_alive()):
            raise ValueError('Stop the current operation and release the hardware lock first')

    @routes.post('/api/wifi/survey', status_code=202)
    def survey(request: WifiSurveyRequest):
        receivers = {'both': ['Host', 'ESP32'], 'host': ['Host'], 'esp32': ['ESP32']}[request.receiver]

        def progress(index, receiver):
            with controller.guard:
                controller.job.update(message=f'Wi-Fi survey · pass {index} of {request.passes} · {receiver}')

        def work(cancel):
            result = wifi_survey.collect(controller.serial, receivers, request.passes, cancel, progress)
            with controller.guard:
                if cancel.is_set():
                    raise ScanCancelled()
                db.event('wifi', 'WIFI_SURVEY', result)

        operation(lambda: controller.launch('Wi-Fi survey', work))
        return {'status': 'STARTED'}

    @routes.get('/api/wifi/survey/latest')
    def latest_survey():
        scan = observation_tools.latest(db, 'WIFI_SURVEY')
        if not scan:
            return {'status': 'NOT_TESTED'}
        baseline = observation_tools.latest(db, 'WIFI_AP_BASELINE') or {}
        known = baseline.get('access_points', {})
        observed = wifi_survey.fresh_inventory(scan)
        return {**scan, 'known_bssids': sorted(known), 'fresh_bssids': sorted(observed),
                'alerts': wifi_survey.inventory_alerts(observed, known)}

    @routes.put('/api/wifi/baseline')
    def wifi_baseline(request: Enrollment):
        def save():
            with controller.guard:
                idle()
                scan = observation_tools.latest(db, 'WIFI_SURVEY')
                if not scan or scan['id'] != request.scan_id:
                    raise ValueError('Refresh the Wi-Fi survey before marking an access point as known')
                observed = wifi_survey.fresh_inventory(scan)
                addresses = {address.upper() for address in request.addresses}
                if not addresses.issubset(observed):
                    raise ValueError('Select access points from refreshed observations')
                baseline = observation_tools.latest(db, 'WIFI_AP_BASELINE') or {}
                known = baseline.get('access_points', {})
                for address in addresses:
                    previous = known.get(address, {'ssids': [], 'security': {}})
                    current = observed[address]
                    known[address] = {'ssids': current['ssids'] or previous['ssids'],
                                      'security': {**previous['security'], **current['security']}}
                if len(known) > 512:
                    raise ValueError('The known access point list is full')
                db.event('wifi', 'WIFI_AP_BASELINE', {'access_points': known})
                return {'status': 'SAVED'}
        return operation(save)

    @routes.post('/api/gps/wifi-snapshot', status_code=202)
    def gps_wifi_snapshot():
        def work(cancel):
            with ThreadPoolExecutor(max_workers=1) as pool:
                fixes = pool.submit(gps_observer.observe, cancel, 10)
                start = datetime.fromisoformat(wifi_survey.timestamp())
                scan = wifi_survey.esp_observation(controller.serial, cancel)
                if scan['status'] != 'OUTPUT':
                    raise ValueError(scan['message'])
                end = datetime.fromisoformat(scan['observed_at'])
                points = [p for p in fixes.result()['points']
                          if start <= datetime.fromisoformat(p['time']) <= end]
            if not points:
                raise ValueError('No fresh GPS position overlapped the ESP32 scan')
            with controller.guard:
                if cancel.is_set():
                    raise ScanCancelled()
                db.event('gps', 'GPS_WIFI_SNAPSHOT', {'status': 'COMPLETE', 'receiver_positions': points,
                         'started_at': start.isoformat(), 'scan': scan})
        operation(lambda: controller.launch('GPS and Wi-Fi snapshot', work))
        return {'status': 'STARTED'}

    @routes.get('/api/gps/wifi-snapshot/latest')
    def gps_wifi_latest():
        return observation_tools.latest(db, 'GPS_WIFI_SNAPSHOT') or {'status': 'NOT_TESTED'}

    @routes.get('/api/wireless/interfaces')
    def interfaces():
        return wireless_monitor.interfaces()

    @routes.post('/api/wireless/scan', status_code=202)
    def capture(request: CaptureRequest):
        def work(cancel):
            result = wireless_monitor.capture(request.interface, request.duration_s, cancel)
            with controller.guard:
                if cancel.is_set():
                    raise ScanCancelled()
                db.event('wifi', 'WIRELESS_SCAN', result)
        operation(lambda: controller.launch('Wireless observation', work))
        return {'status': 'STARTED'}

    @routes.get('/api/wireless/latest')
    def wireless_latest():
        return observation_tools.latest(db, 'WIRELESS_SCAN') or {'status': 'NOT_TESTED'}

    @routes.post('/api/wireless/esp-monitor', status_code=202)
    def esp_monitor(request: EspMonitorRequest):
        def progress(elapsed, total, rate):
            with controller.guard:
                controller.job.update(message=f'ESP32 · Ch {request.channel} · {rate} frames/s · {total} total '
                                              f'· {elapsed / 1000:.0f}/{request.duration_s} s')

        def work(cancel):
            result = esp_packet_monitor.capture(controller.serial, request.channel, request.duration_s, cancel, progress)
            with controller.guard:
                if cancel.is_set():
                    raise ScanCancelled()
                db.event('wifi', 'ESP_WIFI_MONITOR', result)
        operation(lambda: controller.launch('ESP32 Packet Monitor', work))
        return {'status': 'STARTED'}

    @routes.get('/api/wireless/esp-monitor/latest')
    def esp_monitor_latest():
        return observation_tools.latest(db, 'ESP_WIFI_MONITOR') or {
            'status': 'NOT_TESTED', 'message': 'Choose a 2.4 GHz channel to listen using the ESP32.'}

    @routes.get('/api/ble/defense')
    def ble_defense():
        return observation_tools.ble_comparison(db)

    @routes.put('/api/ble/baseline')
    def ble_baseline(request: Enrollment):
        def save():
            with controller.guard:
                idle()
                scan = observation_tools.latest(db, 'BLE_SCAN')
                if not scan or scan['id'] != request.scan_id:
                    raise ValueError('Refresh the BLE observations before enrolling devices')
                observed = {d['address']: d for d in scan['devices']}
                if any(a not in observed for a in request.addresses):
                    raise ValueError('Only devices from the completed scan can be enrolled')
                previous = observation_tools.latest(db, 'BLE_BASELINE') or {}
                known = {d['address']: d for d in previous.get('devices', [])}
                known.update({a: observed[a] for a in request.addresses})
                if len(known) > 512:
                    raise ValueError('BLE baseline limit reached; clear the baseline before rebuilding it')
                db.event('bluetooth', 'BLE_BASELINE', {'devices': list(known.values())})
                return {'status': 'SAVED'}
        return operation(save)

    @routes.delete('/api/ble/baseline')
    def clear_ble_baseline():
        def clear():
            with controller.guard:
                idle()
                db.event('bluetooth', 'BLE_BASELINE', {'devices': []})
            return {'status': 'CLEARED'}
        return operation(clear)

    @routes.get('/api/rf/history')
    def rf_history():
        return observation_tools.rf_history(db)

    @routes.put('/api/rf/baseline')
    def rf_baseline():
        def save():
            with controller.guard:
                idle()
                sample = controller.serial.snapshot()
                if not sample.get('connected') or sample.get('status') != 'OK' or not observation_tools.valid_bins(sample.get('rf_bins')):
                    raise ValueError('A fresh RF sample from the connected ESP32 is required')
                db.event('nRF24', 'RF_BASELINE', {'bins': sample['rf_bins'], 'received_at': sample['received_at'],
                                                  'rf_dwell_us': sample.get('rf_dwell_us')})
            return {'status': 'SAVED'}
        return operation(save)

    @routes.get('/api/tools/export')
    def export():
        return {'wifi_survey': latest_survey(), 'wireless': wireless_latest(), 'ble': ble_defense(), 'rf': rf_history(), 'gps': gps_latest(), 'lab_test': lab_latest(), 'lab_beacon': lab_beacon_latest()}

    @lab_actions.post('/api/lab/deauth', status_code=202)
    def lab_deauth(request: LabDeauthRequest):
        def start():
            with controller.guard:
                idle()
                if not request.isolated_lab_confirmed:
                    raise ValueError('Confirm that both devices belong to the isolated authorized laboratory')
                scan = observation_tools.latest(db, 'WIRELESS_SCAN')
                lab_radio.validate_target(scan, request.scan_id, request.interface, request.bssid, request.client)
                def work(cancel):
                    db.event('wifi-lab', 'LAB_DEAUTH_REQUEST', request.model_dump())
                    try:
                        result = lab_radio.deauthenticate(request.interface, request.bssid, request.client,
                                                         request.frames, scan.get('channel'), cancel)
                    except Exception as exc:
                        db.event('wifi-lab', 'LAB_DEAUTH_RESULT', {'status': 'CANCELLED' if isinstance(exc, ScanCancelled) else 'ERROR',
                            'effect': 'UNVERIFIED', 'message': 'No effect established; inspect the operation status and service log'})
                        raise
                    db.event('wifi-lab', 'LAB_DEAUTH_RESULT', result)
                controller.launch('Lab deauthentication test', work)
        operation(start)
        return {'status': 'STARTED'}

    @routes.get('/api/lab/latest')
    def lab_latest():
        return observation_tools.latest(db, 'LAB_DEAUTH_RESULT') or {'status': 'NOT_TESTED', 'effect': 'UNVERIFIED'}

    @lab_actions.post('/api/lab/beacon', status_code=202)
    def lab_beacon(request: LabBeaconRequest):
        def start():
            with controller.guard:
                idle()
                if not request.isolated_lab_confirmed:
                    raise ValueError('Confirm the selected SSID/device belongs to the isolated authorized lab')
                scan = observation_tools.latest(db, 'WIRELESS_SCAN')
                lab_radio.validate_probe(scan, request.scan_id, request.interface, request.source, request.ssid)
                def work(cancel):
                    db.event('wifi-lab', 'LAB_BEACON_REQUEST', request.model_dump())
                    try:
                        result = lab_radio.advertise_probe(request.interface, request.ssid, request.frames, scan.get('channel'), cancel)
                    except Exception as exc:
                        db.event('wifi-lab', 'LAB_BEACON_RESULT', {'status': 'CANCELLED' if isinstance(exc, ScanCancelled) else 'ERROR',
                            'effect': 'UNVERIFIED', 'message': 'No reception established; inspect operation status and service log'})
                        raise
                    db.event('wifi-lab', 'LAB_BEACON_RESULT', result)
                controller.launch('Lab selected-probe beacon test', work)
        operation(start)
        return {'status': 'STARTED'}

    @routes.get('/api/lab/beacon/latest')
    def lab_beacon_latest():
        return observation_tools.latest(db, 'LAB_BEACON_RESULT') or {'status': 'NOT_TESTED', 'effect': 'UNVERIFIED'}

    @routes.post('/api/gps/observe', status_code=202)
    def gps_observe(request: GPSRequest):
        def work(cancel):
            result = gps_observer.observe(cancel, request.duration_s)
            with controller.guard:
                if cancel.is_set():
                    raise ScanCancelled()
                db.event('gps', 'GPS_TRACK', result)
        operation(lambda: controller.launch('GPS observation', work))
        return {'status': 'STARTED'}

    @routes.get('/api/gps/latest')
    def gps_latest():
        return observation_tools.latest(db, 'GPS_TRACK') or {'status': 'NOT_TESTED', 'points': []}

    @routes.put('/api/gps/waypoint')
    def waypoint(request: WaypointRequest):
        def save():
            with controller.guard:
                idle()
                track = gps_latest()
                if track.get('id') != request.track_id or not track['points']:
                    raise ValueError('Refresh the GPS track before saving a waypoint')
                db.event('gps', 'GPS_WAYPOINT', {'label': request.label, 'point': track['points'][-1]})
            return {'status': 'SAVED'}
        return operation(save)

    @routes.get('/api/gps/export')
    def gps_export():
        import json
        def history(kind):
            return [json.loads(row['payload_data']) for row in db.rows(
                'SELECT payload_data FROM hardware_events WHERE event_type=? ORDER BY id DESC LIMIT 100', (kind,))]
        return gps_observer.geojson(history('GPS_TRACK'), history('GPS_WAYPOINT'))

    if os.getenv('FIIRBOTS_OBSERVATION_ONLY') != '1':
        from . import lab_radio
        routes.include_router(lab_actions)
    return routes
