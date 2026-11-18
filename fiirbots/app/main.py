from contextlib import asynccontextmanager
from ipaddress import IPv4Address
from pathlib import Path
import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import Settings
from .controller import Controller
from .models import BaselineDevice, RetestRequest, DiagnosticRequest, NetworkSelection
from . import desktop_tools
from .network_engine import require_target
from .ai_analyzer import check_connection

ROOT = Path(__file__).resolve().parent.parent


def create_app(settings=None):
    controller = Controller(settings or Settings())
    token = secrets.token_hex(32)

    @asynccontextmanager
    async def lifespan(app):
        controller.start()
        yield
        controller.close()

    app = FastAPI(title='FIIRBots Monitor', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.controller = controller
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])
    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.middleware('http')
    async def local_actions(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not secrets.compare_digest(request.headers.get('x-fiirbots-token', ''), token):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail': 'Reload the local dashboard before performing this action'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; connect-src 'self'; base-uri 'none'"
        return response

    def operation(fn):
        try:
            return fn()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/', response_class=HTMLResponse)
    def home():
        return (ROOT / 'templates/index.html').read_text(encoding='utf-8').replace('__ACTION_TOKEN__', token)

    @app.get('/api/health')
    def health():
        return {'status': 'OK', 'mode': 'monitor'}

    @app.get('/api/state')
    def state():
        return controller.snapshot()

    @app.get('/api/events')
    def events(after: int = 0):
        with controller.guard:
            return {'cursor': controller.event_id, 'events': [e for e in controller.events if e['id'] > after]}

    @app.get('/api/network/adapters')
    def network_adapters():
        return desktop_tools.adapters()

    @app.put('/api/network/configure')
    def network_configure(selection: NetworkSelection):
        def configure():
            with controller.guard:
                if controller.locked or (controller.worker and controller.worker.is_alive()):
                    raise ValueError('Stop the current operation and release the hardware lock first')
                desktop_tools.validate_selection(selection.network, selection.interface)
                controller.settings.network = selection.network
                controller.settings.interface = selection.interface
            return {'network': selection.network, 'interface': selection.interface}
        return operation(configure)

    @app.post('/api/wifi')
    def wifi():
        return desktop_tools.wifi_observation()

    @app.get('/api/system')
    def system():
        return desktop_tools.system_status(controller.settings.database.resolve().parent)

    @app.post('/api/scan', status_code=202)
    def scan():
        return {'batch': operation(controller.start_scan)}

    @app.post('/api/stop')
    def stop():
        controller.cancel.set()
        return {'status': 'STOP_REQUESTED'}

    @app.post('/api/analyze', status_code=202)
    def analyze():
        operation(controller.start_analysis)
        return {'status': 'STARTED'}

    @app.post('/api/ai/check')
    def ai_check():
        return check_connection(controller.settings)

    @app.post('/api/retest', status_code=202)
    def retest(request: RetestRequest):
        operation(lambda: controller.start_retest(request))
        return {'status': 'STARTED'}

    @app.post('/api/diagnostics', status_code=202)
    def diagnostic(request: DiagnosticRequest):
        operation(lambda: controller.start_diagnostic(request))
        return {'status': 'STARTED'}

    @app.get('/api/diagnostics/history')
    def diagnostic_history():
        import json
        rows = controller.db.rows("SELECT id,payload_data,timestamp FROM hardware_events WHERE event_type='MANUAL_TEST' ORDER BY id DESC LIMIT 50")
        return [{'id': r['id'], 'timestamp': r['timestamp'], 'result': json.loads(r['payload_data'])} for r in rows]

    @app.put('/api/baseline')
    def baseline(device: BaselineDevice):
        operation(lambda: require_target(str(device.device_ip), controller.settings.network))
        controller.db.save_baseline(device)
        return {'status': 'SAVED'}

    @app.delete('/api/baseline/{ip}')
    def delete_baseline(ip: IPv4Address):
        controller.db.execute('DELETE FROM baseline_inventory WHERE device_ip=?', (str(ip),))
        return {'status': 'DELETED'}

    @app.get('/api/report/export')
    def export():
        return {'scan': controller.db.latest_scan(), 'baseline': controller.db.baseline(),
                'ai': controller.db.latest_report(), 'hardware_events': controller.db.events(100),
                'retests': controller.db.rows('SELECT * FROM remediation_logs ORDER BY id DESC LIMIT 100')}

    return app


app = create_app()
