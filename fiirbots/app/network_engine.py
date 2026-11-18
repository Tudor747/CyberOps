"""Bounded local-network discovery; never sends service payloads or changes firewall rules."""
import errno
import ipaddress
import socket
import sys
from concurrent.futures import ThreadPoolExecutor

SERVICES = {21: 'FTP', 22: 'SSH', 23: 'Telnet', 80: 'HTTP', 443: 'HTTPS',
            445: 'SMB', 502: 'Modbus TCP', 1883: 'MQTT', 3389: 'RDP',
            4840: 'OPC UA', 8080: 'HTTP alternative', 8883: 'MQTT TLS', 44818: 'EtherNet/IP'}


class ScanCancelled(Exception):
    pass


def scope(value):
    try:
        net = ipaddress.IPv4Network(value, strict=True)
    except ValueError as exc:
        raise ValueError('Configure a valid IPv4 subnet in FIIRBOTS_SCAN_NETWORK') from exc
    private = [ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    if net.num_addresses > 256 or not any(net.subnet_of(n) for n in private):
        raise ValueError('Use a private IPv4 subnet with at most 256 addresses (/24 or smaller)')
    return net


def require_target(ip, network):
    net = scope(network)
    address = ipaddress.IPv4Address(ip)
    if address not in net or (net.prefixlen < 31 and address in (net.network_address, net.broadcast_address)):
        raise ValueError('Target is outside the configured host range')


def probe(ip, port, cancel, source=None):
    if cancel.is_set():
        raise ScanCancelled()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.35)
            if source:
                sock.bind((source, 0))
            code = sock.connect_ex((ip, port))
        if cancel.is_set():
            raise ScanCancelled()
        if code == 0:
            return 'OPEN'
        if code in (errno.ECONNREFUSED, 10061):
            return 'CLOSED'
        if code in (errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH,
                    errno.EWOULDBLOCK, errno.EINPROGRESS, 10035, 10060, 10065, 10051):
            return 'NO_RESPONSE'
        return 'ERROR'
    except (TimeoutError, socket.timeout):
        return 'NO_RESPONSE'


def discover(network, interface, cancel):
    if cancel.is_set():
        raise ScanCancelled()
    if sys.platform == 'win32':
        return discover_windows(network, interface, cancel)
    from scapy.all import ARP, Ether, srp
    # Requires an on-link IPv4 subnet and CAP_NET_RAW on Linux.
    replies, _ = srp(Ether(dst='ff:ff:ff:ff:ff:ff') / ARP(pdst=str(network)),
                     iface=interface, timeout=1, retry=0, verbose=False)
    if cancel.is_set():
        raise ScanCancelled()
    return {r.psrc: r.hwsrc.upper() for _, r in replies if ipaddress.IPv4Address(r.psrc) in network}


def discover_windows(network, interface, cancel):
    """Native Windows ARP, bound to the selected source; no Npcap required."""
    import ctypes
    from ctypes import wintypes
    from .desktop_tools import validate_selection
    source = validate_selection(str(network), interface)
    send_arp = ctypes.WinDLL('iphlpapi').SendARP
    send_arp.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
    send_arp.restype = wintypes.DWORD
    source_int = int.from_bytes(socket.inet_aton(source), 'little')
    def query(host):
        if cancel.is_set():
            raise ScanCancelled()
        mac = (ctypes.c_ubyte * 8)()
        length = wintypes.ULONG(8)
        code = send_arp(int.from_bytes(socket.inet_aton(str(host)), 'little'),
                        source_int, mac, ctypes.byref(length))
        if code == 0 and length.value == 6:
            return str(host), ':'.join(f'{b:02X}' for b in mac[:6])
        if code not in (0, 31, 67, 1168):
            raise ValueError(f'Windows ARP failed (code {code}); check the selected adapter')
        return None
    with ThreadPoolExecutor(max_workers=32) as pool:
        rows = list(pool.map(query, network.hosts()))
    if cancel.is_set():
        raise ScanCancelled()
    return dict(r for r in rows if r)


def classify(ip, mac, opened, baseline, checked_ports):
    known = baseline.get(ip)
    if not known:
        return 'UNAUTHORIZED'
    changed_mac = bool(known['mac_address'] and mac and known['mac_address'].upper() != mac.upper())
    expected = set(known['authorized_ports']) & set(checked_ports)
    if changed_mac or set(opened) != expected:
        return 'CONFIG_CHANGED'
    return 'ONLINE'


def scan(network, interface, baseline_rows, cancel, progress, discover_fn=discover, probe_fn=probe):
    net = scope(network)
    source = None
    if discover_fn is discover:
        from .desktop_tools import validate_selection
        source = validate_selection(network, interface)
    baseline = {r['device_ip']: r for r in baseline_rows if ipaddress.IPv4Address(r['device_ip']) in net}
    found = discover_fn(net, interface, cancel)
    ports = sorted(set(SERVICES) | {p for r in baseline.values() for p in r['authorized_ports']})
    if len(ports) > 64:
        raise ValueError('The combined baseline exceeds the 64-port scan limit')
    hosts = list(net.hosts())
    result = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for index, host in enumerate(hosts):
            if cancel.is_set():
                raise ScanCancelled()
            ip = str(host)
            states = list(pool.map(lambda p: probe_fn(ip, p, cancel, source=source)
                                   if probe_fn is probe else probe_fn(ip, p, cancel), ports))
            if cancel.is_set():
                raise ScanCancelled()
            if 'ERROR' in states:
                raise OSError('Network probe failed; scan not committed')
            opened = [p for p, state in zip(ports, states) if state == 'OPEN']
            responded = ip in found or bool(opened) or 'CLOSED' in states
            if responded or ip in baseline:
                result.append({'device_ip': ip, 'mac_address': found.get(ip), 'open_ports': opened,
                    'detected_services': {str(p): SERVICES.get(p, 'Unknown (port open)') for p in opened},
                    'status': classify(ip, found.get(ip), opened, baseline, ports) if responded else 'MISSING'})
            progress(index + 1, len(hosts))
    return result
