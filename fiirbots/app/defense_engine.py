"""Operator-led remediation verification. Standalone mode never installs firewall rules."""
from .network_engine import probe, require_target, ScanCancelled


def retest(db, settings, request, cancel, probe_fn=probe):
    ip, port = str(request.target_ip), request.target_port
    require_target(ip, settings.network)
    batch = db.latest_scan()
    if not batch or batch['status'] != 'COMPLETE':
        raise ValueError('Complete a scan before requesting a retest')
    previous = next((r for r in batch['devices'] if r['device_ip'] == ip), None)
    if not previous or port not in previous['open_ports']:
        raise ValueError('Retest requires a port observed open in the latest scan')
    after = probe_fn(ip, port, cancel)
    if cancel.is_set():
        raise ScanCancelled()
    # Timeout is inconclusive: do not label it FILTERED or remediation success.
    success = 1 if after == 'CLOSED' else (0 if after == 'OPEN' else None)
    db.execute('''INSERT INTO remediation_logs
      (target_ip,target_port,action_taken,status_before,status_after,is_success) VALUES(?,?,?,?,?,?)''',
      (ip, port, 'OPERATOR_RETEST', 'OPEN', after, success))
    return {'target_ip': ip, 'target_port': port, 'before': 'OPEN', 'after': after,
            'is_success': success, 'action': 'OPERATOR_RETEST'}
