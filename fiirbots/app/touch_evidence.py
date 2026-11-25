"""Format local API observations for the native touchscreen and text reports."""
from datetime import datetime, timezone

from .observation_tools import valid_bins


def _text(value, missing='Unknown'):
    if value is None or value == '':
        return missing
    # Network and device names can contain newlines and directional controls.
    return ''.join(c if c.isprintable() else ascii(c)[1:-1] for c in str(value))


def ai_report_lines(result):
    if not result.get('scan_id'):
        return ['Gemini analysis\nGo to Assets and complete a LAN scan first.']
    record = result.get('ai_report')
    if not record:
        return ['Gemini analysis\nSelect Analyze with Gemini to review this LAN scan.']
    report = record['report']
    findings = report['findings']
    order = ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO')
    lines = [f"Gemini estimate · {report['overall_threat_score']}/100 · {len(findings)} findings\n"
             f"Generated UTC · {_text(record.get('created_at'))}\n{_text(report['summary'])}"]
    for finding in sorted(findings, key=lambda item: order.index(item['risk_level'])):
        confidence = 'Review finding' if finding['is_justified'] else 'Evidence incomplete'
        lines.append(f"{finding['risk_level']} · {_text(finding['target_ip'])} · {confidence}\n"
                     f"{_text(finding['description'])}\n"
                     f"Next check · {_text(finding['recommended_remediation'])}")
    if not findings:
        lines.append('Gemini returned no findings for this scan.')
    return lines


def _measurement(value, unit):
    return f'{value} {unit}' if type(value) in (int, float) else 'Unknown'


def _signal(sample):
    if sample.get('rssi_dbm') is not None:
        return _measurement(sample['rssi_dbm'], 'dBm')
    if sample.get('signal_percent') is not None:
        return f"{sample['signal_percent']}% adapter signal"
    return 'Signal unknown'


def _advertisement(sample):
    security = _text(sample.get('security'), 'Security unknown')
    if security.upper() == 'OPEN':
        return 'Open · no link encryption advertised'
    if 'WEP' in security.upper().replace('-', ' ').split():
        return security + ' · obsolete encryption advertised'
    return security


def _wifi_sample(sample):
    receiver = _text(sample.get('source'), 'Receiver unknown')
    if sample.get('interface'):
        receiver += ' / ' + _text(sample['interface'])
    if sample.get('pass') is not None:
        receiver += ' · pass ' + _text(sample['pass'])
    band = sample.get('band')
    channel = 'Ch ' + _text(sample.get('channel'), '?')
    if sample.get('frequency_mhz') is not None:
        channel += ' · ' + _measurement(sample['frequency_mhz'], 'MHz')
    elif band:
        channel += ' · ' + _text(band)
    if sample.get('from_cache'):
        age = 'cached · last seen unknown'
        if sample.get('last_seen_ms_ago') is not None:
            age = 'cached · last seen ' + _measurement(sample['last_seen_ms_ago'], 'ms') + ' before inventory read'
    else:
        age = 'read ' + _text(sample.get('observed_at'), 'time unknown')
    return f"{receiver} · {age}\n{channel} · {_signal(sample)} · {_advertisement(sample)}"


def _survey_samples(point, cached_passes):
    for sample in point.get('samples', []):
        # Early Windows surveys described cache use at pass level only.
        if 'from_cache' not in sample and (sample.get('source'), sample.get('pass')) in cached_passes:
            sample = {**sample, 'from_cache': True}
        yield sample


def wifi_lines(result):
    status = result.get('status')
    if status == 'NOT_TESTED':
        return ['No saved Wi-Fi survey. Start a scan to check nearby access points.']
    points = result.get('access_points') or []
    lines = [f"Wi-Fi survey · {_text(status)}"]
    if result.get('finished_at'):
        lines.append('Finished · ' + _text(result['finished_at']))
    if 'known_bssids' in result:
        lines.append(f"Known access points · {len(result['known_bssids'])}")
    for alert in result.get('alerts', []):
        bssid = _text(alert['bssid'])
        if alert['kind'] == 'NEW_BSSID':
            names = ', '.join(_text(name) for name in alert['ssids'])
            lines.append(f'New BSSID for {names} · {bssid}')
        elif alert['kind'] == 'SECURITY_CHANGED':
            previous = ', '.join(_text(label) for label in alert['previous'])
            observed = ', '.join(_text(label) for label in alert['observed'])
            lines.append(f"Advertised security changed · {bssid} · {_text(alert['source'])}\n"
                         f'{previous} → {observed}')
    sources = result.get('sources', [])
    cached_passes = {(s.get('source'), s.get('pass')) for s in sources
                     if s.get('scan_mode') in ('OS cache', 'Mixed refreshed and cached adapters')}
    # Older saved surveys counted cache entries in their summary. Derive these
    # figures from the rows so reopening a report keeps the evidence consistent.
    if points:
        open_count = wep_count = cached_only = 0
        for point in points:
            fresh = [s for s in _survey_samples(point, cached_passes) if not s.get('from_cache')]
            labels = {_text(s.get('security')).upper() for s in fresh}
            open_count += 'OPEN' in labels
            wep_count += any('WEP' in label.replace('-', ' ').split() for label in labels)
            cached_only += bool(point.get('samples')) and not fresh
        lines.append(f"{len(points)} distinct access points · {cached_only} seen only in cache\n"
                     f"Advertised security in refreshed listings · {open_count} open · {wep_count} WEP")
    for source in sources:
        lines.append(f"{_text(source.get('source') or source.get('receiver'))} · pass {_text(source.get('pass'))}"
                     f" · {_text(source.get('status'))}\n"
                     + (_text(source['scan_mode']) + ' · ' if source.get('scan_mode') else '')
                     + _text(source.get('message')))
    if not points:
        lines.append('No access points reported in this scan window.' if status == 'COMPLETE'
                     else 'Access-point coverage is incomplete.')
        return lines
    for point in points:
        names = ' / '.join(_text(name) for name in point.get('ssids', []) if name)
        rows = [names or 'Hidden or unknown network name', _text(point.get('bssid'))]
        # Keep each pass and receiver. Different advertised security values and
        # signal units can legitimately appear under the same BSSID.
        for sample in _survey_samples(point, cached_passes):
            rows.append(_wifi_sample(sample))
        lines.append('\n'.join(rows))
    return lines


def hardware_lines(hw):
    if not hw.get('connected'):
        return ['ESP32 · telemetry unavailable', _text(hw.get('message'), 'Check the serial connection.')]
    if hw.get('status') != 'OK':
        return ['ESP32 · connected', 'Monitoring state · ' + _text(hw.get('status'))]
    radar = {True: 'Presence reported', False: 'Absence reported', None: 'No recent ON/OFF report'}
    lines = ['ESP32 · connected']
    when = hw.get('received_at')
    if type(when) in (float, int):
        lines.append('Host received · ' + datetime.fromtimestamp(when, timezone.utc).isoformat(timespec='seconds'))
    lines.extend([
        'nRF24 receiver status · ' + _text(hw.get('nrf24_status')),
        'Ethernet physical link · ' + _text(hw.get('ethernet_status')),
        'Radar · ' + radar.get(hw.get('radar_presence'), 'Unknown'),
        'RFID reader · ' + _text(hw.get('rfid_status')),
        'Last RFID UID · ' + _text(hw.get('last_rfid'), 'No UID reported')
        + (f" · {_measurement(hw['rfid_age_ms'], 'ms')} ago" if hw.get('rfid_age_ms') is not None else ''),
        'Last IR code · ' + _text(hw.get('ir_last_code'), 'No code reported'),
        'IR activity in the last 1.5 s · ' + {True: 'Detected', False: 'None detected'}.get(hw.get('ir_activity'), 'Unknown'),
        'CC1101 received signal level · ' + _measurement(hw.get('rf_subghz_rssi'), 'dBm'),
    ])
    return lines


def _ble_lines(result):
    devices = result.get('devices', [])
    lines = [f'{len(devices)} advertising addresses observed']
    if result.get('finished_at'):
        lines.append('Scan finished · ' + _text(result['finished_at']))
    for device in devices:
        summary = f"{_text(device.get('name'), 'Unnamed device')} · {_text(device.get('address'))}\n{_signal(device)}"
        if device.get('comparison'):
            summary += ' · ' + _text(device['comparison']).lower()
        if device.get('service_uuids'):
            summary += '\nAdvertised services · ' + ', '.join(_text(x) for x in device['service_uuids'])
        lines.append(summary)
    if 'not_observed' in result:
        lines.append(f"{len(result['not_observed'])} enrolled addresses unseen in this scan.")
    lines.append('Devices can change their advertising address between scans.')
    return lines


def _rf_lines(result):
    samples = result.get('samples') or []
    if not samples:
        incomplete = result.get('incomplete_sweeps', 0)
        return ([f'{incomplete} saved RF records have incomplete channel counts.'] if incomplete
                else ['No completed RF sweeps in the saved history.'])
    latest = samples[-1]
    bins = latest.get('bins')
    lines = [f"{len(samples)} saved sweeps · latest {_text(latest.get('recorded_at'))}"]
    if not valid_bins(bins):
        return lines + ['The latest sweep has incomplete channel counts.']
    peak = max(bins)
    if peak:
        frequencies = [2400 + i for i, v in enumerate(bins) if v == peak]
        extra = f" (+{len(frequencies) - 1} other frequencies)" if len(frequencies) > 1 else ''
        lines.append(f"Peak carrier detections · {peak}/8 windows at {frequencies[0]} MHz{extra}")
    else:
        lines.append('Zero carrier detections in eight receive windows per frequency.')
    lines.append('2400–2480 MHz · dwell per window ' + _measurement(latest.get('rf_dwell_us'), 'µs'))
    if result.get('incomplete_sweeps'):
        lines.append(f"{result['incomplete_sweeps']} additional saved records lack complete channel counts.")
    if result.get('delta') is not None:
        delta = result['delta']
        biggest = max(range(len(delta)), key=lambda i: abs(delta[i]))
        lines.append(f"Largest change from baseline · {delta[biggest]:+d} hits per 8 windows at {2400+biggest} MHz"
                     if delta[biggest] else 'All 81 counts match the saved baseline.')
    elif result.get('baseline'):
        lines.append('Baseline comparison unavailable. Check sweep settings and channel counts.')
    else:
        lines.append('No saved RF baseline.')
    spectrum = ['Carrier hits per 1 MHz bin (0–8)']
    for offset in range(0, len(bins), 10):
        group = bins[offset:offset + 10]
        spectrum.append(f"{2400 + offset} MHz · {' '.join(map(str, group))}")
    lines.append('\n'.join(spectrum))
    return lines


def _wireless_lines(result):
    lines = [f"{_text(result.get('interface'))} · channel {_text(result.get('channel'))}"
             f" · {_measurement(result.get('duration_s'), 's')} listened",
             'Capture finished · ' + _text(result.get('finished_at'))]
    counts = result.get('counts', {})
    duration = result.get('duration_s') or 0
    if 'beacon' in counts and duration > 0:
        lines.append(f"Beacon rate · {counts['beacon'] / duration:.1f}/s")
    lines.append('Frames · ' + ', '.join(f"{kind.replace('_', ' ')} {n}" for kind, n in sorted(counts.items()))
                 if counts else 'No 802.11 frames observed in this window.')
    if result.get('truncated'):
        lines.append('Capture limit reached. Some records may be missing.')
    for ap in result.get('access_points', []):
        lines.append(f"{_text(ap.get('ssid'), 'Hidden or unknown name')} · {_text(ap.get('bssid'))}\n"
                     f"{_signal(ap)} · {_text(ap.get('finding'), 'Security unknown')}")
    if counts.get('deauthentication') or counts.get('disassociation'):
        lines.append('Disconnect frames can also occur during ordinary network operation.')
    for probe in result.get('probes', []):
        lines.append(f"Probe request · {_text(probe.get('ssid'), 'Unspecified network')}\n"
                     f"{_text(probe.get('source'))} · {_signal(probe)}")
    return lines


def _wifi_exercise_lines(scenario):
    lines = ['Simulated exercise · no radio traffic']
    if scenario == 'beacon':
        lines.extend(['Beacon spike · channel 6', 'Reference · 12 beacon frames/s\nExercise · 120 beacon frames/s',
                      'Next check · Compare the BSSIDs with your known access points. A high rate alone does not identify the cause.'])
    elif scenario == 'disconnect':
        lines.extend(['Disconnect spike · channel 6', 'Reference · 0 disconnect frames in 10 s\nExercise · 30 disconnect frames in 10 s',
                      'Next check · Compare the timestamps with client disconnects and router logs.'])
    else:
        lines.append('Choose a scenario to practice interpreting Wi-Fi results.')
    return lines


def _gps_lines(result):
    points = result.get('points') or result.get('receiver_positions') or []
    lines = [f'{len(points)} saved receiver positions']
    if points:
        last = points[-1]
        lines.append(f"Latest fix · {_text(last.get('time'))}\n"
                     f"Latitude {_text(last.get('latitude'))}° · longitude {_text(last.get('longitude'))}°")
        if last.get('speed_m_s') is not None:
            lines.append('Speed · ' + _measurement(last['speed_m_s'], 'm/s'))
        if last.get('course_over_ground_deg') is not None:
            lines.append('Course over ground · ' + _measurement(last['course_over_ground_deg'], 'degrees'))
    if 'scan' in result:
        aps = result['scan'].get('access_points', [])
        lines.append(f'{len(aps)} ESP32 access-point observations during the position window')
        lines.extend(f"{_text(ap.get('ssid'), 'Hidden or unknown name')} · {_text(ap.get('bssid'))}\n"
                     f"{_signal(ap)} · {_advertisement(ap)}" for ap in aps)
    return lines


def _diagnostic_lines(history):
    lines = []
    for row in history:
        test = row['result']
        measurements = test.get('measurements', {})
        details = []
        for key, value in measurements.items():
            label = key.replace('_', ' ')
            if isinstance(value, list):
                value = ', '.join(map(str, value))
            details.append(f'{label} · {_text(value)}')
        title = f"{_text(test.get('component'))} · {_text(test.get('state'))} · {_text(row.get('timestamp'))}"
        lines.append('\n'.join([title, _text(test.get('message')), *details]))
    return lines or ['No saved peripheral diagnostics.']


def tool_lines(path, result):
    """Format the response from a named read-only API endpoint."""
    if path == 'diagnostics/history':
        return _diagnostic_lines(result)
    if path == 'lab/wifi-exercise':
        return _wifi_exercise_lines(result.get('scenario'))
    if result.get('status') in ('NOT_TESTED', 'UNAVAILABLE', 'ERROR', 'CANCELLED'):
        return [_text(result.get('message'), 'No saved observation.' if result['status'] == 'NOT_TESTED'
                      else result['status'].title())]
    if path in ('ble/defense', 'ble/latest'):
        return _ble_lines(result)
    if path == 'rf/history':
        return _rf_lines(result)
    if path in ('wireless/latest', 'wireless/esp-monitor/latest'):
        return _wireless_lines(result)
    if path == 'wireless/interfaces':
        return [f"{_text(r.get('name'))} · {_text(r.get('mode'))} · channel {_text(r.get('channel'))}"
                for r in result.get('interfaces', [])] or ['No wireless interfaces found.']
    if path in ('gps/latest', 'gps/wifi-snapshot/latest'):
        return _gps_lines(result)
    if path == 'system':
        return [f"{_text(result.get('os'))} {_text(result.get('release'))} · {_text(result.get('architecture'))}",
                'CPU in use · ' + _measurement(result.get('cpu_percent'), '%'),
                'Memory in use · ' + _measurement(result.get('memory_percent'), '%'),
                'Free storage · ' + _measurement(result.get('storage_free_gb'), 'GiB'),
                'Battery · ' + _measurement(result.get('battery_percent'), '%')]
    raise ValueError(f'Unknown observation path {path}')
