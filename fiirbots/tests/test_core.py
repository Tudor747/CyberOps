import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import Settings
from app.database import Database
from app.defense_engine import retest
from app.hardware_buttons import SwitchLatch
from app.main import create_app
from app.models import BaselineDevice, RetestRequest, AIAnalysisReport
from app.network_engine import scan, scope, require_target, ScanCancelled
from app.serial_link import decode_response


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(database=Path(self.temp.name)/'test.db', network='192.168.50.0/30',
                                 gpio_enabled=False, serial_port='', reboot_enabled=False, api_key='')
        self.db = Database(self.settings.database)
        self.db.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_scope_rejects_public_and_large_subnets(self):
        for value in ('8.8.8.0/24','192.168.0.0/16','127.0.0.0/24','bad','192.168.50.1/24'):
            with self.assertRaises(ValueError): scope(value)
        with self.assertRaises(ValueError): require_target('192.168.51.1',self.settings.network)
        with self.assertRaises(ValueError): require_target('192.168.50.3',self.settings.network)

    def test_baseline_diff_and_no_response(self):
        self.db.save_baseline(BaselineDevice(device_ip='192.168.50.1', device_name='PLC', authorized_ports=[502]))
        rows=scan(self.settings.network,'fake',self.db.baseline(),threading.Event(),lambda *_:None,
                  discover_fn=lambda *_:{'192.168.50.1':'AA:BB:CC:DD:EE:FF'},
                  probe_fn=lambda ip,p,c:'OPEN' if ip.endswith('.1') and p==23 else 'NO_RESPONSE')
        self.assertEqual(rows[0]['status'],'CONFIG_CHANGED')
        self.assertEqual(rows[0]['open_ports'],[23])
        rows=scan(self.settings.network,'fake',self.db.baseline(),threading.Event(),lambda *_:None,
                  discover_fn=lambda *_:{},probe_fn=lambda *_:'NO_RESPONSE')
        self.assertEqual(rows[0]['status'],'MISSING')
        self.assertEqual(len(rows),1)

    def test_cancel_does_not_produce_missing_devices(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(ScanCancelled):
            scan(self.settings.network,'fake',[],cancel,lambda *_:None,discover_fn=lambda *_:{})

    def test_retest_timeout_is_not_success(self):
        self.db.execute("INSERT INTO scan_batches(id,network,status) VALUES('batch',?,'RUNNING')",(self.settings.network,))
        self.db.save_scan('batch',[{'device_ip':'192.168.50.1','open_ports':[23],'detected_services':{'23':'Telnet'},'status':'UNAUTHORIZED'}])
        request=RetestRequest(target_ip='192.168.50.1',target_port=23)
        result=retest(self.db,self.settings,request,threading.Event(),probe_fn=lambda *_:'NO_RESPONSE')
        self.assertIsNone(result['is_success'])
        self.assertEqual(result['after'],'NO_RESPONSE')
        self.assertEqual(self.db.rows('SELECT action_taken FROM remediation_logs')[0]['action_taken'],'OPERATOR_RETEST')

    def test_switch_does_not_reboot_loop_when_held(self):
        calls=[]
        switch=SwitchLatch(True,lambda:calls.append('lock'),lambda:calls.append('release'),lambda:calls.append('reboot'))
        switch.activate();switch.activate()
        self.assertNotIn('reboot',calls)
        switch.release();switch.activate();switch.activate();switch.release();switch.activate()
        self.assertEqual(calls.count('reboot'),1)

    def test_serial_framing(self):
        payload={'request_id':'42','status':'OK','radar_presence':None,'last_rfid':None,
                 'ir_activity':False,'rf_subghz_rssi':None,'nrf24_status':'NOT FOUND'}
        self.assertEqual(decode_response(json.dumps(payload),'42')['status'],'OK')
        payload['radar_presence']='false'
        with self.assertRaises(ValueError):decode_response(json.dumps(payload),'42')
        for line in (b'boot text',b'[]',b'{"request_id":"old","status":"OK"}',b'x'*17000):
            with self.assertRaises(ValueError):decode_response(line,'42')

    def test_report_score_bounds(self):
        with self.assertRaises(ValueError): AIAnalysisReport(overall_threat_score=101,summary='Invalid',findings=[])

    def test_api_baseline_security_and_locked_scan(self):
        app=create_app(self.settings)
        with TestClient(app) as client:
            page=client.get('/')
            self.assertEqual(page.status_code,200)
            self.assertIn('lang="en"',page.text)
            token=re.search(r'name="action-token" content="([a-f0-9]+)"',page.text)[1]
            self.assertEqual(client.post('/api/scan').status_code,403)
            headers={'X-FIIRBots-Token':token}
            device={'device_ip':'192.168.50.1','device_name':'PLC','authorized_ports':[502]}
            self.assertEqual(client.put('/api/baseline',json=device,headers=headers).status_code,200)
            self.assertEqual(client.get('/api/state').json()['baseline'][0]['authorized_ports'],[502])
            app.state.controller.lock_operations()
            self.assertEqual(client.post('/api/scan',headers=headers).status_code,409)
            self.assertEqual(client.post('/api/analyze',headers=headers).status_code,409)
            self.assertEqual(client.get('/api/report/export').status_code,200)
            self.assertNotIn('api_key',client.get('/api/state').text)
            self.assertEqual(client.get('/',headers={'Host':'evil.example'}).status_code,400)

    def test_cancelled_batch_is_not_complete(self):
        app=create_app(self.settings)
        with TestClient(app):
            controller=app.state.controller
            with patch('app.network_engine.scan',side_effect=ScanCancelled):
                controller.start_scan();controller.worker.join(2)
            self.assertEqual(controller.db.latest_scan()['status'],'CANCELLED')
            self.assertEqual(controller.db.latest_scan()['devices'],[])

    def test_in_progress_batch_interrupted_on_restart(self):
        self.db.execute("INSERT INTO scan_batches(id,network,status) VALUES('x',?,'RUNNING')",(self.settings.network,))
        self.db.initialize()
        self.assertEqual(self.db.latest_scan()['status'],'INTERRUPTED')

    def test_serial_cannot_resume_after_s1_lock(self):
        from app.serial_link import SerialLink
        class Wire:
            def write(self, data): self.sent=json.loads(data)
            def read_until(self, *args):
                return (json.dumps({'request_id':self.sent['request_id'],'status':'STOPPED'}) + '\n').encode()
        wire=Wire()
        link=SerialLink('',self.db,lambda:True)
        link.connection=wire
        link.request('POLL_HARDWARE')
        self.assertEqual(wire.sent['cmd'],'STOP')

    def test_ai_result_discarded_when_cancelled(self):
        app=create_app(self.settings)
        with TestClient(app):
            controller=app.state.controller
            controller.settings.api_key='test-only'
            controller.db.execute("INSERT INTO scan_batches(id,network,status) VALUES('batch',?,'COMPLETE')",(self.settings.network,))
            def cancelled_analysis(*args):
                controller.lock_operations()
                return AIAnalysisReport(overall_threat_score=0,summary='Discard me',findings=[])
            with patch('app.ai_analyzer.analyze',side_effect=cancelled_analysis):
                controller.start_analysis();controller.worker.join(2)
            self.assertIsNone(controller.db.latest_report())
            self.assertEqual(controller.job['status'],'CANCELLED')


if __name__=='__main__':unittest.main()
