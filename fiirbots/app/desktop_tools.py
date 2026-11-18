"""Local adapters and OS-provided Wi-Fi observations; no shell interpolation."""
import ipaddress
import platform
import socket
import subprocess
import shutil
from datetime import datetime, timezone
import psutil


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
                               'suggested_scope': str(segment)})
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
    if system == 'Windows':
        command = ['netsh', 'wlan', 'show', 'networks', 'mode=bssid']
    elif system == 'Linux':
        command = ['nmcli', '--colors', 'no', '-f', 'SSID,BSSID,CHAN,SIGNAL,SECURITY',
                   'device', 'wifi', 'list', '--rescan', 'yes']
    else:
        return {'status': 'UNAVAILABLE', 'message': 'Wi-Fi observation is supported on Windows and Linux'}
    try:
        proc = subprocess.run(command, capture_output=True, timeout=20,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        output = (proc.stdout + proc.stderr).decode('utf-8', errors='replace').strip()
        return {'status': 'OUTPUT' if proc.returncode == 0 else 'UNAVAILABLE',
                'message': 'OS output; empty results or permission messages are not proof that no Wi-Fi exists.',
                'output': output[:50000], 'observed_at': datetime.now(timezone.utc).isoformat()}
    except (OSError, subprocess.TimeoutExpired):
        return {'status': 'UNAVAILABLE', 'message': 'Wi-Fi command unavailable or timed out. Check adapter and OS permissions.'}


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
