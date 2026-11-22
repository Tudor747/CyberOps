"""Local adapters and OS-provided Wi-Fi observations; no shell interpolation."""
import ipaddress
import os
import platform
import socket
import subprocess
import shutil
from datetime import datetime, timezone
import psutil
from . import wifi_inventory, windows_wifi


def adapters():
    stats = psutil.net_if_stats()
    result = []
    for name, addresses in psutil.net_if_addrs().items():
        if name not in stats or not stats[name].isup:
            continue
        for addr in addresses:
            if addr.family != socket.AF_INET or not addr.netmask:
                continue
            ip = ipaddress.IPv4Address(addr.address)
            if ip.is_loopback or ip.is_link_local:
                continue
            net = ipaddress.IPv4Network(f'{addr.address}/{addr.netmask}', strict=False)
            # Large LANs require an explicitly bounded segment, not a broad sweep.
            segment = ipaddress.IPv4Network(f'{addr.address}/{max(24, net.prefixlen)}', strict=False)
            private = any(segment.subnet_of(ipaddress.IPv4Network(n)) for n in
                          ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
            if private:
                result.append({'interface': name, 'address': addr.address, 'network': str(net),
                               'suggested_scope': str(segment),
                               'available_scopes': [str(n) for n in net.subnets(new_prefix=24)]
                               if 18 <= net.prefixlen < 24 else [str(segment)]})
    return result


def validate_selection(network, interface):
    from .network_engine import scope
    net = scope(network)
    matches = [a for a in adapters() if a['interface'] == interface
               and net.subnet_of(ipaddress.IPv4Network(a['network']))]
    if not matches:
        raise ValueError('Choose an active adapter and an on-link subnet from the adapter list')
    return matches[0]['address']


def wifi_observation():
    system = platform.system()
    refresh = []
    refresh_note = ''
    if system == 'Windows':
        source = 'Windows WLAN'
        scan_mode = 'OS cache'
        try:
            refresh = windows_wifi.scan_interfaces()
            completed = sum(adapter['state'] == 'complete' for adapter in refresh)
            if completed:
                scan_mode = ('OS-managed rescan' if completed == len(refresh)
                             else 'Mixed refreshed and cached adapters')
            refresh_note = f' {completed}/{len(refresh)} adapters confirmed a scan completion.'
        except OSError as exc:
            refresh_note = f' Scan refresh unavailable ({exc}).'
        command = ['netsh', 'wlan', 'show', 'networks', 'mode=bssid']
    elif system == 'Linux':
        source, scan_mode = 'NetworkManager', 'OS-managed rescan requested'
        command = ['nmcli', '--colors', 'no', '--terse', '--escape', 'yes', '-f', wifi_inventory.NM_FIELDS,
                   'device', 'wifi', 'list', '--rescan', 'yes']
    else:
        return {'status': 'UNAVAILABLE', 'message': 'Wi-Fi observation is supported on Windows and Linux',
                'access_points': []}
    result = {'status': 'UNAVAILABLE', 'source': source, 'scan_mode': scan_mode, 'access_points': [],
              'refresh': refresh}
    run_options = {'capture_output': True, 'timeout': 20,
                   'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    if system == 'Linux':
        run_options['env'] = {**os.environ, 'LC_ALL': 'C'}
    try:
        proc = subprocess.run(command, **run_options)
        encoding = 'oem' if os.name == 'nt' and system == 'Windows' else 'utf-8'
        output = proc.stdout.decode(encoding, errors='replace')
        error = proc.stderr.decode(encoding, errors='replace').strip()
        result['output'] = '\n'.join(part for part in (output.rstrip('\r\n'), error) if part)
        result['observed_at'] = datetime.now(timezone.utc).isoformat()
        if proc.returncode:
            result['message'] = 'The adapter inventory failed. Check the OS output and permissions.' + refresh_note
            return result
        if system == 'Windows':
            points, malformed, confirmed_empty = wifi_inventory.netsh_access_points(output)
        else:
            points, malformed = wifi_inventory.nm_access_points(output)
            confirmed_empty = False
            if not points and not output.strip() and not error:
                devices = subprocess.run(['nmcli', '-t', '-f', 'TYPE,STATE', 'device', 'status'], **run_options)
                confirmed_empty = devices.returncode == 0 and any(
                    line.startswith('wifi:') and line.split(':', 1)[1] in ('connected', 'connected (externally)', 'disconnected')
                    for line in devices.stdout.decode('utf-8', errors='replace').splitlines())
        result['access_points'] = points
        if points or confirmed_empty:
            result['status'] = 'PARTIAL' if malformed or error else 'OUTPUT'
            result['message'] = f'{len(points)} adapter observations.' + refresh_note
            if malformed:
                result['message'] += f' {malformed} malformed records in the OS output.'
            if error:
                result['message'] += ' The OS also returned a warning.'
        else:
            result['message'] = 'No usable adapter inventory. Check radio availability, permissions and OS output.' + refresh_note
    except (OSError, subprocess.TimeoutExpired) as exc:
        result['message'] = f'Wi-Fi command unavailable or timed out ({exc}).' + refresh_note
    return result


def system_status(storage_path):
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(storage_path)
    battery = psutil.sensors_battery()
    return {'os': platform.system(), 'release': platform.release(), 'architecture': platform.machine(),
            'cpu_percent': psutil.cpu_percent(interval=0.1), 'memory_percent': memory.percent,
            'memory_total_gb': round(memory.total / 1024**3, 1),
            'storage_free_gb': round(disk.free / 1024**3, 1),
            'battery_percent': battery.percent if battery else None,
            'power_plugged': battery.power_plugged if battery else None}
