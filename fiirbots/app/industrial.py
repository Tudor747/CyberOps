"""Local assessment of observed services and operator-identified OT assets."""
import json
from html import escape
from ipaddress import IPv4Address
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import Field

from .models import StrictModel
from .network_engine import require_target
from .observation_tools import latest


class Asset(StrictModel):
    ip: IPv4Address
    name: str = Field(min_length=1, max_length=80)
    zone: str = Field(min_length=1, max_length=80)
    role: str = Field(max_length=80)
    model: str = Field(default='', max_length=120)
    firmware: str = Field(default='', max_length=80)
    criticality: Literal['Unknown', 'Low', 'Medium', 'High'] = 'Unknown'


def assessment(db, network):
    scans = db.rows("SELECT id,finished_at FROM scan_batches WHERE network=? AND status='COMPLETE' "
                    "ORDER BY rowid DESC LIMIT 1", (network,))
    scan = scans[0] if scans else None
    observations = db.observations(scan['id']) if scan else []
    observed = {row['device_ip']: row for row in observations if row['status'] != 'MISSING'}
    profiles = {row['ip']: json.loads(row['profile']) for row in db.rows(
        'SELECT ip,profile FROM industrial_assets WHERE network=? ORDER BY ip', (network,))}
    rows = []
    for ip in sorted(observed.keys() | profiles.keys(), key=IPv4Address):
        profile = profiles.get(ip)
        evidence = observed.get(ip)
        ports = evidence['open_ports'] if evidence else None
        finding = (
            'Review open TCP ports with the OT team. Confirm the service, intended clients and segmentation.'
            if ports else 'No open ports among the checks performed.' if ports == [] else
            'No observation in a completed scan for this segment.'
        )
        rows.append({'ip': ip, 'profile': profile, 'open_ports': ports,
                     'baseline_status': evidence['status'] if evidence else None,
                     'finding': finding, 'priority': 'High review' if ports and profile and
                     profile['criticality'] == 'High' else 'Review' if ports else 'Information'})
    return {'network': network, 'scan_at': scan['finished_at'] if scan else None,
            'scan_id': scan['id'] if scan else None, 'assets': rows}


def report_html(result):
    def safe(value):
        return escape(str(value))

    cards = []
    for row in sorted(result['assets'], key=lambda row: ((row['profile'] or {}).get('zone', ''), IPv4Address(row['ip']))):
        profile = row['profile'] or {}
        fields = ' · '.join(safe(profile.get(key) or 'Unknown')
                            for key in ('zone', 'role', 'model', 'firmware', 'criticality'))
        ports = row['open_ports']
        evidence = ', '.join(map(str, ports)) if ports else 'None observed' if ports == [] else 'Unavailable'
        cards.append(f"<section><h2>{safe(profile.get('name') or row['ip'])} · {safe(row['ip'])}</h2>"
                     f"<p>{fields}</p><p>Observed open TCP ports: {evidence}</p>"
                     f"<p>LAN baseline status: {safe(row['baseline_status'] or 'Unavailable')}</p>"
                     f"<p>{safe(row['priority'])} · {safe(row['finding'])}</p></section>")
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>FIIRBots OT assessment</title>'
            '<h1>FIIRBots OT / IIoT assessment</h1>'
            f"<p>Segment: {safe(result['network'] or 'Unconfigured')}</p>"
            f"<p>LAN scan time (UTC): {safe(result['scan_at'] or 'Unavailable')}</p>"
            '<p>Asset profiles are operator supplied. Exposure findings require service and firmware verification.</p>'
            + ''.join(cards) + '</html>')


def industrial_routes(controller, operation):
    routes = APIRouter()

    @routes.get('/api/industrial/assessment')
    def current(include_wifi: bool = False, include_ai: bool = False):
        result = assessment(controller.db, controller.settings.network)
        if include_wifi:
            result['wifi_survey'] = latest(controller.db, 'WIFI_SURVEY') or {'status': 'NOT_TESTED'}
        if include_ai:
            result['ai_report'] = controller.db.latest_report(result['scan_id']) if result['scan_id'] else None
        return result

    @routes.put('/api/industrial/assets')
    def save(asset: Asset):
        def store():
            with controller.guard:
                network = controller.settings.network
                require_target(str(asset.ip), network)
                controller.db.execute(
                    'INSERT INTO industrial_assets(network,ip,profile) VALUES(?,?,?) '
                    'ON CONFLICT(network,ip) DO UPDATE SET profile=excluded.profile',
                    (network, str(asset.ip), asset.model_dump_json()))
            return {'status': 'SAVED'}
        return operation(store)

    @routes.get('/api/industrial/report', response_class=HTMLResponse)
    def report():
        return report_html(current())

    return routes
