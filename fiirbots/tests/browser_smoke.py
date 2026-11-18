"""Run against a local development server without GPIO, serial or a scan subnet.

python tests/browser_smoke.py --browser <path-to-chromium>
"""
import argparse
import asyncio
import base64
import json
import platform
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
import websockets


async def inspect(url, output):
    errors=[]
    async with websockets.connect(url, max_size=8*1024*1024) as ws:
        sequence=0
        async def send(method, params=None):
            nonlocal sequence
            sequence+=1
            await ws.send(json.dumps({'id':sequence,'method':method,'params':params or {}}))
            while True:
                message=json.loads(await asyncio.wait_for(ws.recv(),10))
                if message.get('method')=='Runtime.exceptionThrown': errors.append(message['params'])
                if message.get('method')=='Log.entryAdded' and message['params']['entry']['level']=='error':
                    # Missing browser favicon is not an application error.
                    if 'favicon' not in message['params']['entry'].get('url',''): errors.append(message['params'])
                if message.get('id')==sequence:
                    if 'error' in message: raise RuntimeError(message['error'])
                    return message.get('result',{})
        async def evaluate(code):
            result=await send('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
            if result.get('exceptionDetails'): raise AssertionError(result['exceptionDetails'])
            return result['result'].get('value')
        await send('Runtime.enable');await send('Log.enable');await send('Page.enable')
        await send('Emulation.setDeviceMetricsOverride',{'width':800,'height':480,'deviceScaleFactor':1,'mobile':False})
        await send('Page.navigate',{'url':'http://127.0.0.1:8000/'})
        await asyncio.sleep(2)
        assert await evaluate("document.getElementById('connection').textContent")=='Local service online'
        assert not await evaluate("document.documentElement.scrollWidth > innerWidth")
        for tab in ['network','hardware','inventory','reports','config','tools','overview']:
            await evaluate(f"document.querySelector('[data-tab={tab}]').click()")
            assert await evaluate(f"document.getElementById('{tab}').hidden") is False
        await evaluate("document.querySelector('[data-tab=inventory]').click(); document.getElementById('add-device').click()")
        assert await evaluate("document.getElementById('device-dialog').open") is True
        await evaluate("document.getElementById('cancel-device').click(); document.querySelector('[data-tab=overview]').click()")
        await evaluate("navigate('NEXT')")
        assert await evaluate("document.activeElement.tagName")=='BUTTON'
        shot=await send('Page.captureScreenshot',{'format':'png'})
        (output/'dashboard-800x480.png').write_bytes(base64.b64decode(shot['data']))
        await evaluate("document.querySelector('[data-test-module=rfid]').click()")
        assert await evaluate("!document.getElementById('config').hidden && selectedComponent==='rfid'")
        await evaluate("document.querySelector('[data-tab=tools]').click()")
        assert await evaluate("document.querySelectorAll('.tool-card').length") >= 35
        await evaluate("document.getElementById('tool-filter').value='PC'; document.getElementById('tool-filter').dispatchEvent(new Event('change'))")
        assert await evaluate("[...document.querySelectorAll('.tool-card .status')].every(x=>x.textContent.includes('/ PC'))")
        await evaluate("document.getElementById('system-refresh').click()")
        await asyncio.sleep(1)
        assert platform.system() in await evaluate("document.getElementById('system-info').textContent")
        for control in ['wireless-interfaces','wireless-refresh','ble-defense-refresh','rf-history-refresh',
                        'gps-refresh','lab-targets-refresh','lab-result-refresh','lab-probes-refresh','lab-beacon-result']:
            await evaluate(f"document.getElementById('{control}').onclick()")
        await asyncio.sleep(1)
        assert await evaluate("document.getElementById('wireless-interface').options.length") >= 1
        assert await evaluate("document.getElementById('rf-history-status').textContent.includes('No valid RF samples')")
        assert await evaluate("document.getElementById('lab-status').textContent.includes('UNVERIFIED')")
        assert not await evaluate("document.documentElement.scrollWidth > innerWidth")
        for width,height in [(1440,900),(390,844)]:
            await send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':False})
            await evaluate("document.querySelector('[data-tab=overview]').click()")
            assert not await evaluate("document.documentElement.scrollWidth > innerWidth")
            await evaluate("tab('tools')")
            assert not await evaluate("document.documentElement.scrollWidth > innerWidth")
            await evaluate("tab('overview')")
            shot=await send('Page.captureScreenshot',{'format':'png'})
            (output/f'dashboard-{width}x{height}.png').write_bytes(base64.b64decode(shot['data']))
        await send('Emulation.setDeviceMetricsOverride',{'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
        for name in ['network','tools','reports']:
            await evaluate(f"tab('{name}')")
            assert not await evaluate("document.documentElement.scrollWidth > innerWidth")
            shot=await send('Page.captureScreenshot',{'format':'png'})
            (output/f'dashboard-{name}.png').write_bytes(base64.b64decode(shot['data']))
        assert not errors, errors
        print('PASS: seven tabs, module shortcuts, tool catalog/filter, system info, enrollment, physical-button focus; no JS errors or overflow at 800x480, 1440x900, 390x844.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--browser',required=True);args=parser.parse_args()
    output=Path('test-results').resolve();output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output,ignore_cleanup_errors=True) as profile:
        process=subprocess.Popen([args.browser,'--headless=new','--disable-gpu','--no-first-run',
            '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            port_file=Path(profile)/'DevToolsActivePort'
            for _ in range(100):
                try:
                    port=port_file.read_text().splitlines()[0]
                    if port: break
                except (OSError, IndexError):
                    pass
                if process.poll() is not None:raise RuntimeError('Browser exited before startup')
                time.sleep(.1)
            else: raise RuntimeError('Browser debugging port unavailable')
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json') as response:
                pages=json.load(response)
            asyncio.run(inspect(next(p['webSocketDebuggerUrl'] for p in pages if p['type']=='page'),output))
        finally:
            process.terminate();process.wait(timeout=10)


if __name__=='__main__':main()
