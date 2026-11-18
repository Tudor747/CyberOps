"""Receive-only 802.11 metadata, using an already configured monitor interface."""
import platform
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from .network_engine import ScanCancelled


def interfaces():
    if platform.system() != 'Linux':
        return {'status': 'UNAVAILABLE', 'interfaces': [], 'message': 'Live monitor capture requires Linux'}
    try:
        proc = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {'status': 'UNAVAILABLE', 'interfaces': [], 'message': 'iw is unavailable or timed out'}
    if proc.returncode:
        return {'status': 'UNAVAILABLE', 'interfaces': [], 'message': 'Unable to query wireless interfaces'}
    rows = []
    current = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith('Interface '):
            current = {'name': line[10:], 'mode': 'unknown', 'channel': None}
            rows.append(current)
        elif current is not None and line.startswith('type '):
            current['mode'] = line[5:]
        elif current is not None and line.startswith('channel '):
            match = re.match(r'channel (\d+)', line)
            if match:
                current['channel'] = int(match[1])
    return {'status': 'AVAILABLE', 'interfaces': rows,
            'message': 'Capture requires an existing monitor interface. This tool never changes interface mode or channel.'}


class Summary:
    def __init__(self):
        self.counts = Counter()
        self.access_points = {}
        self.probes = {}
        self.events = []
        self.clients = {}
        self.truncated = False

    def receive(self, packet):
        from scapy.layers.dot11 import Dot11, Dot11Elt, Dot11Beacon, Dot11ProbeResp, RadioTap
        if not packet.haslayer(Dot11):
            return
        dot = packet[Dot11]
        names = {(0, 8): 'beacon', (0, 4): 'probe_request', (0, 5): 'probe_response',
                 (0, 12): 'deauthentication', (0, 10): 'disassociation'}
        kind = names.get((dot.type, dot.subtype), {0: 'management', 1: 'control', 2: 'data'}.get(dot.type, 'other'))
        self.counts[kind] += 1
        if dot.type == 2:
            direction = int(dot.FCfield) & 3
            pair = (dot.addr1, dot.addr2) if direction == 1 else (dot.addr2, dot.addr1) if direction == 2 else None
            if pair and all(is_unicast(a) for a in pair):
                if pair in self.clients or len(self.clients) < 512:
                    self.clients[pair] = {'bssid': pair[0], 'client': pair[1]}
                else:
                    self.truncated = True
        # Metadata only: never persist data payloads, handshakes or credentials.
        ssid, channel, rsn = None, None, False
        elt = packet.getlayer(Dot11Elt)
        for _ in range(64):
            if not isinstance(elt, Dot11Elt):
                break
            # Decoded elements such as RSN/DS use specialized Scapy fields,
            # rather than the generic .info attribute.
            encoded = bytes(elt)
            info = encoded[2:2 + encoded[1]] if len(encoded) >= 2 else b''
            if elt.ID == 0:
                ssid = info[:32].decode('utf-8', errors='replace')
            elif elt.ID == 3 and len(info) == 1:
                channel = info[0]
            elif elt.ID == 48:
                rsn = True
            elt = elt.payload
        signal = packet[RadioTap].dBm_AntSignal if packet.haslayer(RadioTap) else None
        if kind in ('beacon', 'probe_response'):
            address = dot.addr3
            if address not in self.access_points and len(self.access_points) >= 512:
                self.truncated = True
                return
            frame = packet.getlayer(Dot11Beacon) or packet.getlayer(Dot11ProbeResp)
            privacy = bool(frame.cap.privacy) if frame is not None else None
            self.access_points[address] = {'bssid': address, 'ssid': ssid, 'channel': channel,
                'rssi_dbm': signal, 'privacy_bit': privacy, 'rsn_advertised': rsn,
                'finding': 'Privacy not advertised' if privacy is False else 'Inspect security configuration'}
        elif kind == 'probe_request':
            key = (dot.addr2, ssid)
            if key not in self.probes and len(self.probes) >= 512:
                self.truncated = True
                return
            self.probes[key] = {'source': dot.addr2, 'ssid': ssid, 'rssi_dbm': signal}
        elif kind in ('deauthentication', 'disassociation'):
            if len(self.events) < 512:
                self.events.append({'kind': kind, 'source': dot.addr2, 'destination': dot.addr1,
                                    'bssid': dot.addr3})
            else:
                self.truncated = True

    def result(self):
        return {'counts': dict(self.counts), 'access_points': list(self.access_points.values()),
                'probes': list(self.probes.values()), 'management_events': self.events, 'clients': list(self.clients.values()),
                'truncated': self.truncated,
                'interpretation': 'Management events may be legitimate or spoofed; counts alone do not prove an attack. Capture covers only the current channel. Empty results are inconclusive.'}


def is_unicast(address):
    return bool(isinstance(address, str) and re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', address)
                and address.lower() != '00:00:00:00:00:00' and not (int(address[:2], 16) & 1))


def capture(interface, duration, cancel):
    if cancel.is_set():
        raise ScanCancelled()
    if not 1 <= duration <= 30:
        raise ValueError('Choose a duration from 1 to 30 seconds')
    selected = next((r for r in interfaces()['interfaces'] if r['name'] == interface), None)
    if not selected or selected['mode'] != 'monitor':
        raise ValueError('Select an existing Linux monitor interface; the current Wi-Fi configuration cannot capture raw frames')
    from scapy.all import conf, sniff
    summary = Summary()
    started = time.monotonic()
    # Reuse one receive socket across bounded waits so Stop works on a quiet channel.
    try:
        with conf.L2listen(iface=interface) as receiver:
            while time.monotonic() - started < duration:
                if cancel.is_set():
                    raise ScanCancelled()
                sniff(opened_socket=receiver, store=False, prn=summary.receive,
                      timeout=min(.25, max(0, duration - (time.monotonic() - started))),
                      count=10000 - sum(summary.counts.values()),
                      stop_filter=lambda _: cancel.is_set())
                if sum(summary.counts.values()) >= 10000:
                    summary.truncated = True
                    break
    except ScanCancelled:
        raise
    except Exception as exc:
        raise ValueError('Wireless capture failed; check the monitor interface and raw-packet permissions') from exc
    if cancel.is_set():
        raise ScanCancelled()
    return {'status': 'COMPLETE', 'interface': interface, 'channel': selected['channel'],
            'duration_s': round(time.monotonic() - started, 3),
            'finished_at': datetime.now(timezone.utc).isoformat(), **summary.result()}
