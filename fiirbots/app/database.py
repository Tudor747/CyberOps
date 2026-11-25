import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS industrial_assets (
 network TEXT NOT NULL, ip TEXT NOT NULL, profile TEXT NOT NULL,
 PRIMARY KEY (network, ip));
CREATE TABLE IF NOT EXISTS baseline_inventory (
 id INTEGER PRIMARY KEY, device_ip TEXT UNIQUE NOT NULL, mac_address TEXT,
 device_name TEXT, role TEXT, authorized_ports TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS scan_batches (
 id TEXT PRIMARY KEY, network TEXT NOT NULL, status TEXT NOT NULL,
 error TEXT, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS network_scans (
 id INTEGER PRIMARY KEY, scan_batch_id TEXT NOT NULL, device_ip TEXT NOT NULL,
 mac_address TEXT, open_ports TEXT, detected_services TEXT, status TEXT NOT NULL,
 timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS scans_batch ON network_scans(scan_batch_id);
CREATE TABLE IF NOT EXISTS hardware_events (
 id INTEGER PRIMARY KEY, source_module TEXT NOT NULL, event_type TEXT NOT NULL,
 payload_data TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS remediation_logs (
 id INTEGER PRIMARY KEY, target_ip TEXT NOT NULL, target_port INTEGER NOT NULL,
 action_taken TEXT NOT NULL, status_before TEXT, status_after TEXT,
 is_success INTEGER, executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ai_analysis_reports (
 id INTEGER PRIMARY KEY, scan_batch_id TEXT NOT NULL, overall_threat_score INTEGER NOT NULL,
 report_json TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
'''


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript(SCHEMA)
            conn.execute("UPDATE scan_batches SET status='INTERRUPTED', finished_at=CURRENT_TIMESTAMP WHERE status='RUNNING'")

    def rows(self, sql, args=()):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.connect() as conn:
            return conn.execute(sql, args).lastrowid

    def baseline(self):
        rows = self.rows('SELECT * FROM baseline_inventory ORDER BY device_ip')
        for r in rows:
            r['authorized_ports'] = json.loads(r['authorized_ports'])
        return rows

    def save_baseline(self, device):
        self.execute('''INSERT INTO baseline_inventory(device_ip,mac_address,device_name,role,authorized_ports)
          VALUES(?,?,?,?,?) ON CONFLICT(device_ip) DO UPDATE SET mac_address=excluded.mac_address,
          device_name=excluded.device_name,role=excluded.role,authorized_ports=excluded.authorized_ports''',
          (str(device.device_ip), device.mac_address, device.device_name, device.role, json.dumps(device.authorized_ports)))

    def latest_scan(self):
        rows = self.rows('SELECT * FROM scan_batches ORDER BY rowid DESC LIMIT 1')
        if not rows:
            return None
        batch = rows[0]
        batch['devices'] = self.observations(batch['id'])
        return batch

    def observations(self, batch):
        rows = self.rows('SELECT * FROM network_scans WHERE scan_batch_id=? ORDER BY id', (batch,))
        for r in rows:
            r['open_ports'] = json.loads(r['open_ports'])
            r['detected_services'] = json.loads(r['detected_services'])
        return rows

    def save_scan(self, batch, rows):
        with self.connect() as conn:
            conn.executemany('''INSERT INTO network_scans
                (scan_batch_id,device_ip,mac_address,open_ports,detected_services,status) VALUES(?,?,?,?,?,?)''',
                [(batch, r['device_ip'], r.get('mac_address'), json.dumps(r['open_ports']),
                  json.dumps(r['detected_services']), r['status']) for r in rows])
            conn.execute("UPDATE scan_batches SET status='COMPLETE', finished_at=CURRENT_TIMESTAMP WHERE id=?", (batch,))

    def event(self, module, event, payload):
        self.execute('INSERT INTO hardware_events(source_module,event_type,payload_data) VALUES(?,?,?)',
                     (module, event, json.dumps(payload)))

    def events(self, limit=50):
        rows = self.rows('SELECT * FROM hardware_events ORDER BY id DESC LIMIT ?', (limit,))
        for r in rows:
            r['payload_data'] = json.loads(r['payload_data'])
        return rows

    def latest_report(self, scan_id=None):
        query = 'SELECT * FROM ai_analysis_reports'
        params = ()
        if scan_id is not None:
            query += ' WHERE scan_batch_id=?'
            params = (scan_id,)
        rows = self.rows(query + ' ORDER BY id DESC LIMIT 1', params)
        if not rows:
            return None
        rows[0]['report'] = json.loads(rows[0].pop('report_json'))
        return rows[0]
