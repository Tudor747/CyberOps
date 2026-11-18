"""Bounded BLE advertisement discovery; never connects to discovered devices."""
import asyncio
from datetime import datetime, timezone
from .network_engine import ScanCancelled


async def observe(cancel, duration=10, scanner_factory=None):
    if not 0 < duration <= 30:
        raise ValueError('BLE scan duration must be between 0 and 30 seconds')
    if cancel.is_set():
        raise ScanCancelled()
    if scanner_factory is None:
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise ValueError('BLE backend unavailable; install requirements.txt') from exc
        scanner_factory = BleakScanner
    rows = {}
    def received(device, advertisement):
        if cancel.is_set() or (device.address not in rows and len(rows) >= 512):
            return
        rows[device.address] = {
            'address': device.address, 'name': advertisement.local_name or device.name,
            'rssi_dbm': advertisement.rssi,
            'service_uuids': list(advertisement.service_uuids),
            'observed_at': datetime.now(timezone.utc).isoformat()}
    try:
        async with scanner_factory(detection_callback=received):
            deadline = asyncio.get_running_loop().time() + duration
            while asyncio.get_running_loop().time() < deadline:
                if cancel.is_set():
                    raise ScanCancelled()
                await asyncio.sleep(min(.1, max(0, deadline - asyncio.get_running_loop().time())))
    except ScanCancelled:
        raise
    except Exception as exc:
        raise ValueError('BLE scan unavailable: check Bluetooth adapter, service and permissions') from exc
    if cancel.is_set():
        raise ScanCancelled()
    return {'status': 'COMPLETE', 'devices': sorted(rows.values(), key=lambda r: r['address']),
            'finished_at': datetime.now(timezone.utc).isoformat(),
            'message': 'Advertisement observations only; an empty scan does not prove absence. Addresses may rotate.'}
