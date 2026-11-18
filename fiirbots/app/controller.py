import logging
import subprocess
import threading
from collections import deque
from uuid import uuid4
from . import ai_analyzer, defense_engine, network_engine, diagnostics
from .database import Database
from .hardware_buttons import HardwareButtons
from .serial_link import SerialLink

log = logging.getLogger(__name__)


class Controller:
    def __init__(self, settings):
        self.settings = settings
        self.db = Database(settings.database)
        self.guard = threading.RLock()
        self.cancel = threading.Event()
        self.locked = settings.gpio_enabled  # Remain closed until GPIO state is read.
        self.job = {'kind': None, 'status': 'IDLE', 'message': 'Ready', 'progress': 0}
        self.worker = None
        self.diagnostic = None
        self.gpio_status = 'Starting'
        self.events = deque(maxlen=100)
        self.event_id = 0
        self.serial = SerialLink(settings.serial_port, self.db, lambda: self.locked)
        self.buttons = HardwareButtons(self)

    def start(self):
        self.db.initialize()
        self.buttons.start()
        self.serial.start()

    def close(self):
        self.lock_operations()
        self.buttons.close()
        self.serial.close()
        if self.worker:
            self.worker.join(timeout=3)

    def emit(self, action):
        with self.guard:
            self.event_id += 1
            self.events.append({'id': self.event_id, 'action': action})

    def button(self, action):
        if action == 'AI':
            try:
                self.start_analysis()
            except ValueError as exc:
                self.emit(str(exc))
        else:
            if action == 'BACK':
                self.cancel.set()
            self.emit(action)

    def lock_operations(self):
        with self.guard:
            self.locked = True
            self.cancel.set()

    def unlock_operations(self):
        with self.guard:
            self.locked = False

    def request_reboot(self):
        def reboot():
            self.serial.stop_hardware()
            try:
                self.db.event('S1', 'REBOOT_REQUEST', {'scan_stopped': True})
            except Exception:
                log.exception('Could not record S1 event')
            try:
                if self.settings.reboot_enabled:
                    subprocess.run(['/usr/bin/sudo', '-n', '/usr/bin/systemctl', 'reboot'],
                                   check=True, timeout=10, capture_output=True)
                else:
                    self.emit('Reboot disabled in development mode')
            except Exception:
                self.emit('Reboot failed; scans remain stopped')
                log.exception('Reboot request failed')
        threading.Thread(target=reboot, daemon=True, name='s1-reboot').start()

    def launch(self, kind, work):
        with self.guard:
            if self.locked:
                raise ValueError('Operations locked by S1 or GPIO fault')
            if self.worker and self.worker.is_alive():
                raise ValueError('An operation is already running')
            self.cancel = threading.Event()
            self.job = {'kind': kind, 'status': 'RUNNING', 'message': kind, 'progress': 0}
            cancel = self.cancel
            def run():
                try:
                    work(cancel)
                    with self.guard:
                        self.job.update(status='CANCELLED' if cancel.is_set() else 'COMPLETE',
                                        message='Stopped' if cancel.is_set() else 'Complete')
                except network_engine.ScanCancelled:
                    with self.guard:
                        self.job.update(status='CANCELLED', message='Stopped')
                except Exception as exc:
                    log.exception('Operation failed')
                    with self.guard:
                        message = str(exc) if isinstance(exc, ValueError) else 'Operation failed; check the Pi service log'
                        self.job.update(status='ERROR', message=message)
            self.worker = threading.Thread(target=run, daemon=True, name=kind)
            self.worker.start()

    def start_scan(self):
        network_engine.scope(self.settings.network)
        batch = uuid4().hex
        def work(cancel):
            self.db.execute("INSERT INTO scan_batches(id,network,status) VALUES(?,?,'RUNNING')", (batch, self.settings.network))
            try:
                with self.guard:
                    self.job.update(message='Discovering local ARP neighbors; TCP checks follow')
                def progress(done, total):
                    with self.guard:
                        self.job.update(progress=round(done / total * 100), message=f'Checking host {done} / {total}')
                rows = network_engine.scan(self.settings.network, self.settings.interface, self.db.baseline(), cancel, progress)
                with self.guard:
                    if cancel.is_set():
                        raise network_engine.ScanCancelled()
                    self.db.save_scan(batch, rows)
            except Exception as exc:
                status = 'CANCELLED' if isinstance(exc, network_engine.ScanCancelled) else 'ERROR'
                self.db.execute('UPDATE scan_batches SET status=?,error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?',
                                (status, type(exc).__name__, batch))
                raise
        self.launch('Network scan', work)
        return batch

    def start_analysis(self):
        if not self.settings.api_key:
            raise ValueError('AI is not configured: set GEMINI_API_KEY on the Pi')
        batch = self.db.latest_scan()
        if not batch or batch['status'] != 'COMPLETE':
            raise ValueError('Complete a network scan first')
        def work(cancel):
            if cancel.is_set():
                raise network_engine.ScanCancelled()
            report = ai_analyzer.analyze(self.settings, batch, self.db.baseline(), self.db.events(20))
            with self.guard:
                if cancel.is_set():
                    raise network_engine.ScanCancelled()
                self.db.execute('INSERT INTO ai_analysis_reports(scan_batch_id,overall_threat_score,report_json) VALUES(?,?,?)',
                                (batch['id'], report.overall_threat_score, report.model_dump_json()))
        self.launch('AI analysis', work)

    def start_retest(self, request):
        network_engine.require_target(str(request.target_ip), self.settings.network)
        self.launch('Port retest', lambda cancel: defense_engine.retest(self.db, self.settings, request, cancel))

    def start_diagnostic(self, request):
        self.launch('Hardware test', lambda cancel: diagnostics.run_test(self, request, cancel))

    def snapshot(self):
        with self.guard:
            job, locked = dict(self.job), self.locked
            diagnostic = dict(self.diagnostic) if self.diagnostic else None
        return {'mode': 'STANDALONE MONITOR', 'network': self.settings.network,
                'interface': self.settings.interface, 'locked': locked, 'gpio': self.gpio_status,
                'ai_configured': bool(self.settings.api_key), 'job': job,
                'diagnostic': diagnostic,
                'hardware': self.serial.snapshot(), 'scan': self.db.latest_scan(),
                'baseline': self.db.baseline(), 'report': self.db.latest_report(),
                'retests': self.db.rows('SELECT * FROM remediation_logs ORDER BY id DESC LIMIT 30')}
