"""Parse the OS adapter's BSSID observations without grouping by network name."""
import csv
import re


MAC = re.compile(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', re.I)
NM_FIELDS = 'DEVICE,BSSID,SSID-HEX,CHAN,FREQ,SIGNAL,SECURITY,WPA-FLAGS,RSN-FLAGS'


def _number(text, suffix='', minimum=0, maximum=None):
    value = text.removesuffix(suffix).strip()
    if not value.isascii() or not value.isdecimal() or len(value) > 6:
        return None
    number = int(value)
    return number if number >= minimum and (maximum is None or number <= maximum) else None


def nm_fields(line):
    return next(csv.reader([line], delimiter=':', escapechar='\\', quoting=csv.QUOTE_NONE))


def nm_access_points(output):
    points = []
    malformed = 0
    for line in output.splitlines():
        if not line:
            continue
        fields = nm_fields(line)
        if len(fields) != 9 or not MAC.fullmatch(fields[1]):
            malformed += 1
            continue
        device, bssid, hex_name, channel, frequency, signal, security, wpa, rsn = fields
        try:
            name = bytes.fromhex(hex_name)
            ssid = name.decode('utf-8') if any(name) else ''
        except (UnicodeError, ValueError):
            ssid = None
        if security in ('', '--'):
            security = 'Open' if wpa == rsn == '(none)' else None
        points.append({'interface': device or None, 'bssid': bssid.upper(), 'ssid': ssid,
                       'ssid_hex': hex_name, 'channel': _number(channel, minimum=1),
                       'frequency_mhz': _number(frequency, 'MHz', minimum=1),
                       'signal_percent': _number(signal, maximum=100), 'rssi_dbm': None,
                       'security': security, 'source': 'NetworkManager'})
    return points, malformed


def _netsh_security(auth, cipher):
    if auth and auth.casefold() in ('open', 'deschis', 'deschisă'):
        if cipher and cipher.casefold() in ('none', 'fără', 'niciuna'):
            return 'Open'
        return cipher
    return ' / '.join(field for field in (auth, cipher) if field) or None


def netsh_access_points(output):
    points = []
    malformed = 0
    interface = ssid = auth = cipher = point = None
    confirmed_empty = False
    for line in output.splitlines():
        key, separator, value = line.partition(':')
        if not separator:
            if re.search(r'\b0\s+(?:networks?|rețele)\b', line, re.I):
                confirmed_empty = True
            continue
        key = key.strip().casefold()
        value = value.removeprefix(' ')
        if key in ('interface name', 'nume interfață', 'numele interfeței'):
            interface = value.strip()
            ssid = auth = cipher = point = None
        elif re.fullmatch(r'ssid\s+\d+', key):
            ssid = value
            auth = cipher = point = None
        elif re.fullmatch(r'bssid\s+\d+', key):
            bssid = value.strip()
            if not MAC.fullmatch(bssid):
                malformed += 1
                point = None
                continue
            point = {'interface': interface, 'bssid': bssid.upper(), 'ssid': ssid,
                     'channel': None, 'frequency_mhz': None, 'rssi_dbm': None,
                     'signal_percent': None, 'security': _netsh_security(auth, cipher),
                     'source': 'Windows WLAN'}
            points.append(point)
        elif key in ('authentication', 'autentificare'):
            auth = value.strip()
        elif key in ('encryption', 'criptare'):
            cipher = value.strip()
        elif point is not None:
            if key in ('signal', 'semnal'):
                point['signal_percent'] = _number(value, '%', maximum=100)
            elif key in ('channel', 'canal'):
                point['channel'] = _number(value, minimum=1)
            elif key in ('band', 'bandă'):
                point['band'] = value.strip()
    return points, malformed, confirmed_empty
