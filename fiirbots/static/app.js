'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="action-token"]').content;
let state, cursor = 0, initializedEvents = false, toastTimer;
const titles = {overview: 'Control deck', network: 'Network observation', hardware: 'Hardware telemetry', inventory: 'Baseline inventory', reports: 'Analysis & reports', config: 'Configuration & tests', tools: 'Cyberdeck tool library'};
function toast(message) {$('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 6000);}
async function api(path, method = 'GET', body) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json', 'X-FIIRBots-Token': token}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the entered values');
  return data;
}
function tab(name) {
  document.querySelectorAll('.view').forEach(v => v.hidden = v.id !== name);
  document.querySelectorAll('.nav').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $('page-title').textContent = titles[name]; $('eyebrow').textContent = 'SYSTEM / ' + name.toUpperCase();
  if(name==='tools')renderToolCatalog();
}
function element(tag, text, className) {const e = document.createElement(tag); if(text !== undefined) e.textContent = text; if(className) e.className = className; return e;}
function cell(row, text) {const c = element('td', text); row.append(c); return c;}
function button(text, action) {const b = element('button', text); b.type = 'button'; b.onclick = action; return b;}
function empty(tbody, text, columns = 4) {const r=element('tr'), c=cell(r,text); c.colSpan=columns;c.className='empty';tbody.append(r);}
function enroll(device = {}) {
  const form = $('device-form'); form.reset();
  for(const key of ['device_ip','device_name','role','mac_address']) if(device[key]) form.elements[key].value = device[key];
  form.elements.ports.value = (device.authorized_ports || device.open_ports || []).join(', ');
  $('device-dialog').showModal();
}
function renderTables() {
  const network = $('network-rows'); network.replaceChildren();
  const devices = state.scan?.devices || [];
  for(const d of devices) {
    const r=element('tr'), name=cell(r, d.device_ip); name.append(element('small',d.mac_address || 'MAC not observed'));
    const ports=cell(r,'');
    if(!d.open_ports.length) ports.textContent='—';
    for(const p of d.open_ports) {const b=button(String(p),async()=>{try{await api('/api/retest','POST',{target_ip:d.device_ip,target_port:p});toast('Retest started');}catch(e){toast(e.message);}});b.title='Retest port '+p;b.disabled=state.locked || state.job.status==='RUNNING';ports.append(b);}
    const status=element('span',d.status,'status '+(d.status==='UNAUTHORIZED'?'bad':d.status==='ONLINE'?'':'warn'));cell(r,'').append(status);
    cell(r,'').append(button('Enroll',()=>enroll(d)));network.append(r);
  }
  if(!devices.length) empty(network,state.scan?.status==='RUNNING'?'Discovery in progress. Results appear when the complete scan is saved.':state.scan?.status==='ERROR'?'Scan failed. Check the operation message above.':state.scan?.status==='COMPLETE'?'No devices responded. Check the subnet and interface.':'Run a scan to observe your network.');
  const inventory=$('inventory-rows');inventory.replaceChildren();
  for(const d of state.baseline) {
    const r=element('tr'),name=cell(r,d.device_name);name.append(element('small',d.device_ip));cell(r,d.role);cell(r,d.authorized_ports.join(', ')||'None');
    const actions=cell(r,'');actions.append(button('Edit',()=>enroll(d)),button('Remove',async()=>{if(!confirm('Remove '+d.device_name+' from the authorized inventory?'))return;try{await api('/api/baseline/'+d.device_ip,'DELETE');await refresh();}catch(e){toast(e.message);}}));inventory.append(r);
  }
  if(!state.baseline.length) empty(inventory,'Enroll known devices to establish your baseline.');
}
function render() {
  const complete=state.scan?.status==='COMPLETE', devices=state.scan?.devices || [];
  $('connection').textContent='Local service online';$('connection-dot').className='';
  $('device-count').textContent=complete?devices.filter(d=>d.status!=='MISSING').length:'—';
  $('alert-count').textContent=complete?devices.filter(d=>d.status!=='ONLINE').length:'—';
  $('scan-age').textContent=state.scan ? state.scan.status+' · '+state.scan.started_at+' UTC':'No completed scan';
  $('risk-score').replaceChildren(document.createTextNode(state.report?.report.overall_threat_score ?? '—'),element('em','/100'));
  const current=state.report?.scan_batch_id===state.scan?.id;
  $('ai-state').textContent=state.report?(current?'Latest scan analyzed':'Previous scan report'):state.ai_configured?'Ready on demand':'API key not configured';
  $('deck-ai-summary').textContent=state.report ? (current?'':'Previous scan \u00b7 ')+state.report.report.summary : state.ai_configured ? 'Analyst ready. Complete a scan, then request an AI report.' : 'Add GEMINI_API_KEY to .env to enable the analyst.';
  $('scope').textContent=state.network||'Subnet not configured';$('interface').textContent=state.interface+' · ARP discovery + TCP checks';
  $('job-message').textContent=state.job.message;$('progress').value=state.job.progress;
  $('lock-banner').hidden=!state.locked;$('gpio-state').textContent=state.gpio;
  $('operation-status').hidden=!['RUNNING','ERROR','CANCELLED'].includes(state.job.status);
  $('operation-status').textContent=state.job.status+' / '+state.job.message+(state.job.status==='RUNNING'?' / '+state.job.progress+'%':'');
  $('apply-network').disabled=state.locked || state.job.status==='RUNNING' || !networkAdapters.length;
  $('footer-state').textContent=state.locked?'S1 / LOCKED':state.job.status;
  document.querySelectorAll('[data-action="scan"]').forEach(b=>b.disabled=state.locked || state.job.status==='RUNNING' || !state.network);
  document.querySelectorAll('[data-action="analyze"]').forEach(b=>b.disabled=state.locked || state.job.status==='RUNNING' || !state.ai_configured || !complete);
  $('batch-label').textContent=state.scan?state.scan.status+' · '+state.scan.started_at+' UTC':'No scan yet';
  const hw=state.hardware,live=hw.connected&&hw.status==='OK';
  $('esp-status').textContent=hw.connected?'USB · '+hw.status:'USB · disconnected';
  $('hardware-message').textContent=hw.connected?'115200 baud · '+hw.status+' · Live readings from ESP32':hw.message;
  $('nrf-state').textContent=live?hw.nrf24_status:'No fresh sample';
  $('subghz').textContent=live&&hw.rf_subghz_rssi!=null?hw.rf_subghz_rssi+' dBm':'Unknown';
  $('radar').textContent=live&&hw.radar_presence!=null?(hw.radar_presence?'Detected':'Clear'):'Unknown';
  $('rfid').textContent=live?hw.last_rfid||'None observed':'—';$('ir').textContent=live?hw.ir_last_code||'None observed':'—';
  $('ethernet').textContent=live?hw.ethernet_status||'Unknown':'Unknown';
  $('rf-chart').replaceChildren();
  if(live&&Array.isArray(hw.rf_bins)) for(const value of hw.rf_bins) {const bar=element('div',undefined,'bar');bar.style.height=Math.max(2,Math.min(100,Number(value)*100/8))+'%';$('rf-chart').append(bar);}
  else $('rf-chart').append(element('span','No RF data','hint'));
  $('report-date').textContent=state.report?(current?'Latest scan':'Previous scan')+' · '+state.report.created_at+' UTC':'No AI report yet';
  $('report-summary').textContent=state.report?.report.summary || 'Complete a scan, then request an analysis. Recommendations are for the operator; this device does not block network traffic.';
  $('findings').replaceChildren();
  for(const f of state.report?.report.findings || []) {const a=element('div',undefined,'finding');a.append(element('small',f.risk_level+' · '+f.target_ip),element('p',f.description),element('div',f.recommended_remediation));$('findings').append(a);}
  $('retests').replaceChildren();
  for(const r of state.retests) $('retests').append(element('p',r.target_ip+':'+r.target_port+' · '+r.status_before+' → '+r.status_after+' · '+r.executed_at+' UTC'));
  if(!state.retests.length)$('retests').textContent='No retests recorded. Tap an open port in Network after an operator intervention.';
  // Avoid destroying the focused table action during physical-button navigation.
  if(!document.activeElement?.closest('tbody')) renderTables();
  renderDiagnostic();
}
function navigate(action) {
  if(action==='BACK'){if($('device-dialog').open)$('device-dialog').close();else tab('overview');return;}
  const root=$('device-dialog').open?$('device-dialog'):document;
  const controls=[...root.querySelectorAll('button:not(:disabled),a.button,input,select')].filter(e=>e.getClientRects().length);
  let index=controls.indexOf(document.activeElement);
  if(action==='NEXT'||action==='PREV'){index=(index+(action==='NEXT'?1:-1)+controls.length)%controls.length;controls[index]?.focus();}
  else if(action==='SELECT')document.activeElement?.click();
  else toast(action);
}
async function refresh() {state=await api('/api/state');render();}
async function poll() {
  try {await refresh();const e=await api('/api/events?after='+cursor);if(initializedEvents)e.events.forEach(v=>navigate(v.action));cursor=e.cursor;initializedEvents=true;}
  catch(e){$('connection').textContent='Service unavailable';$('connection-dot').className='offline';document.querySelectorAll('[data-action]').forEach(b=>b.disabled=true);}
  $('clock').textContent=new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});
  setTimeout(poll,1000);
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>tab(b.dataset.open));
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{try{await api('/api/'+b.dataset.action,'POST');await refresh();}catch(e){toast(e.message);}});
$('add-device').onclick=()=>enroll();$('cancel-device').onclick=()=>$('device-dialog').close();
$('device-form').onsubmit=async e=>{e.preventDefault();const f=e.target.elements;const ports=f.ports.value.trim()?f.ports.value.split(',').map(p=>Number(p.trim())):[];if(ports.some(p=>!Number.isInteger(p)||p<1||p>65535)){toast('Enter comma-separated ports between 1 and 65535');return;}try{await api('/api/baseline','PUT',{device_ip:f.device_ip.value,device_name:f.device_name.value,role:f.role.value,mac_address:f.mac_address.value||null,authorized_ports:ports});$('device-dialog').close();toast('Baseline saved');await refresh();}catch(e){toast(e.message);}};
let selectedComponent='rfid', historyResult=null, lastTestId=null, displayedTest=null;
const testHelp={
  rfid:'Hold one 13.56 MHz ISO14443A tag close to the RC522. Read UID, type and 16 bytes: a Classic block with factory Key A, or four unprotected Ultralight/NTAG pages. Protected memory is reported explicitly.',
  cc1101:'Receive only. Activate your test sensor while listening. Select its frequency and modulation. Raw edges and RSSI are evidence, not universal industrial protocol decoding. Profile: 270.83 kHz bandwidth, 4.8 kbaud.',
  ir_rx:'Point a remote at KY-022 and press a button. Shows protocol, code, bit count and raw pulse timings. A silent receiver cannot be distinguished from no IR source by software alone.',
  ir_tx:'Bench loopback: point KY-005 directly at KY-022 before starting. Emits one 38 kHz NEC diagnostic frame (0xF1A500FF). PASS requires the receiver to observe the matching code.',
  nrf1:'Checks nRF24 #1 over SPI and samples carrier activity across 2400–2480 MHz. SPI response alone does not verify antenna sensitivity.',
  nrf2:'Checks nRF24 #2 independently over SPI and samples carrier activity. No radio packets are transmitted.',
  radar:'Move in front of LD2420. Waits for a fresh ON/OFF UART report; compare reported presence with the room. Silent or unsupported report modes produce NO SIGNAL.',
  ethernet:'Connect W5500 to a powered switch using an Ethernet cable. Checks chip version and physical link. This does not test DHCP, IP connectivity or routing.'
};
function chooseComponent(component) {
  selectedComponent=component;historyResult=null;
  document.querySelectorAll('[data-component]').forEach(b=>b.classList.toggle('selected',b.dataset.component===component));
  $('test-instructions').textContent=testHelp[component];
  $('rfid-options').hidden=component!=='rfid';$('radio-options').hidden=component!=='cc1101';
  $('start-test').textContent=component==='rfid'?'Read tag':component==='cc1101'?'Listen for signal':component==='ir_tx'?'Emit & verify loopback':'Start component test';
}
function renderDiagnostic() {
  if(state.diagnostic?.test_id!==lastTestId){historyResult=null;lastTestId=state.diagnostic?.test_id;}
  const r=historyResult || state.diagnostic;displayedTest=r;
  $('start-test').disabled=state.locked || state.job.status==='RUNNING' || !state.hardware.connected;
  $('export-test').disabled=!r || r.state==='RUNNING';
  if(!r)return;
  $('test-state').textContent=r.state;
  $('test-state').className='status '+(r.state==='FAIL'?'bad':r.state==='PASS'?'':'warn');
  $('test-message').textContent=r.message;
  $('test-code').textContent=r.component+' / '+r.code+(r.elapsed_ms!=null?' / '+(r.elapsed_ms/1000).toFixed(1)+' s':'')+(historyResult?' / saved result':'');
  $('test-measurements').replaceChildren();
  const raw=[];
  for(const [key,value] of Object.entries(r.measurements || {})) {
    if(key==='pulse_us'){raw.push('Pulse durations (microseconds):\n'+value.join(', '));continue;}
    const label=key.replaceAll('_',' ');
    $('test-measurements').append(element('dt',label),element('dd',typeof value==='object'?JSON.stringify(value):String(value)));
  }
  $('test-data').hidden=!raw.length;$('test-data').textContent=raw.join('\n\n');
}
document.querySelectorAll('[data-component]').forEach(b=>b.onclick=()=>chooseComponent(b.dataset.component));
$('test-form').onsubmit=async e=>{
  e.preventDefault();historyResult=null;
  try {
    await api('/api/diagnostics','POST',{component:selectedComponent,duration_s:Number($('test-duration').value),
      address:Number($('test-address').value),frequency_mhz:Number($('test-frequency').value),modulation:$('test-modulation').value});
    await refresh();
  } catch(error){toast(error.message);}
};
$('export-test').onclick=()=>{
  if(!displayedTest)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(displayedTest,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='fiirbots-'+displayedTest.component+'-'+displayedTest.test_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('test-history-refresh').onclick=async()=>{
  try {
    const rows=await api('/api/diagnostics/history');$('test-history').hidden=false;$('test-history-list').replaceChildren();
    for(const row of rows)$('test-history-list').append(button(row.timestamp+' UTC · '+row.result.component+' · '+row.result.state,()=>{historyResult=row.result;renderDiagnostic();}));
    if(!rows.length)$('test-history-list').append(element('p','No manual tests recorded yet.','hint'));
  }catch(error){toast(error.message);}
};
chooseComponent('rfid');
poll();

$('ai-check').onclick=async()=>{
  const b=$('ai-check');b.disabled=true;$('ai-check-result').textContent='Testing live generation...';
  try {const result=await api('/api/ai/check','POST');$('ai-check-result').textContent=result.status+' / '+result.message+(result.model?' / '+result.model:'');}
  catch(e){$('ai-check-result').textContent=e.message;}
  finally{b.disabled=false;}
};
document.querySelectorAll('[data-test-module]').forEach(b=>b.onclick=()=>{chooseComponent(b.dataset.testModule);tab('config');});
// Feature parity catalog: availability is explicit; unavailable tools never fabricate results.
const toolCatalog = [
  ['Network','LAN discovery','PC','ARP + bounded TCP checks on a selected local adapter.','network'],
  ['Wi-Fi','WiFi Scanner','PC','OS-provided SSID, BSSID, channel, signal and security output. Location permissions may be required.','wifi'],
  ['Wi-Fi','Threat Monitor','NOT_PORTED','The original Wi-Fi event monitor is not ported. LAN baseline alerts are a separate feature.'],
  ['Wi-Fi','WiFi Audit','NOT_PORTED','Dedicated wireless audit is not ported. AI currently analyzes LAN scans and hardware events.'],
  ['Wi-Fi','Probe Sniffer','NOT_PORTED','Requires a capture backend and a compatible monitor-mode adapter.'],
  ['Wi-Fi','Beacon Spam','NOT_PORTED','Original firmware transmission tool; no desktop implementation.'],
  ['Wi-Fi','Deauther','NOT_PORTED','Original firmware transmission tool; no desktop implementation.'],
  ['Wi-Fi','Evil Portal','NOT_PORTED','Original firmware portal tool; no desktop implementation.'],
  ['Wi-Fi','KARMA','NOT_PORTED','Original firmware access-point tool; no desktop implementation.'],
  ['Radio','2.4 GHz spectrum','HARDWARE','Live carrier detections from ESP32 + nRF24. Values are not dBm.','hardware'],
  ['Radio','Waterfall / WiFi Channels','NOT_PORTED','Additional spectrum visualization modes are not ported.'],
  ['Radio','RF Baseline','NOT_PORTED','Persistent RF baseline comparison is not implemented.'],
  ['Radio','nRF24 #1 diagnostics','HARDWARE','SPI checks and receive activity through the FIIRBots ESP32 firmware.','nrf1'],
  ['Radio','nRF24 #2 diagnostics','HARDWARE','Independent second-module checks.','nrf2'],
  ['Radio','Channel jammer','NOT_PORTED','Original firmware transmission tool; no desktop implementation.'],
  ['Bluetooth','BLE Scanner','NOT_PORTED','Bluetooth scan backend is not connected to this application.'],
  ['Bluetooth','BLE Defense','NOT_PORTED','BLE inventory and comparison backend is not ported.'],
  ['Bluetooth','BLE Spam','NOT_PORTED','Original advertising test tool; no desktop implementation.'],
  ['Bluetooth','BT Disruptor','NOT_PORTED','Original radio tool; no desktop implementation.'],
  ['Bluetooth','BT Jammer','NOT_PORTED','Original radio tool; no desktop implementation.'],
  ['Monitor','Packet Monitor','NOT_PORTED','No raw Wi-Fi packet capture backend is configured.'],
  ['Monitor','Activity indicators / buzzer','NOT_PORTED','Original packet-rate indicators and buzzer are not ported.'],
  ['System','Mission Dashboard','PC','Real scan state, inventory, job progress and AI summary.','overview'],
  ['System','Audit Reports / AI','PC','Gemini reports for completed LAN scans, recent hardware events and JSON export.','reports'],
  ['System','Settings / System Info','PC','Adapter selection and real host CPU, RAM, disk and battery readings.','system'],
  ['GPS','GPS dashboard / NMEA','NOT_PORTED','Requires GPS hardware and a new serial/NMEA backend.'],
  ['GPS','Track logger / waypoints / compass','NOT_PORTED','GPS persistence and map views are not ported.'],
  ['GPS','Snapshot / wardriving','NOT_PORTED','Requires combined GPS and wireless logging; not ported.'],
  ['System','MicroSD Manager / Info','NOT_PORTED','The original ESP32 microSD filesystem is not exposed to the app.'],
  ['System','Battery ADC','NOT_PORTED','ESP32 ADC battery data is not exposed. Host battery is shown separately.'],
  ['System','Clock','PC','Computer-local clock in the dashboard header.','overview'],
  ['System','Weather / on-screen keyboard','NOT_PORTED','Weather integration is not ported; use the OS touch keyboard.'],
  ['System','About / reference','PC','Feature catalog based on the adjacent CYBERDECK MINI ESP32 V2 repository.','tools'],
  ['FIIRBots extras','RFID / NFC','HARDWARE','RC522 tag identity and supported memory reads.','rfid'],
  ['FIIRBots extras','433 MHz receive','HARDWARE','CC1101 receiver diagnostics and raw pulse observations.','cc1101'],
  ['FIIRBots extras','IR receive','HARDWARE','KY-022 remote code and pulse observations.','ir_rx'],
  ['FIIRBots extras','IR loopback','HARDWARE','KY-005 emitter and KY-022 matching-frame test.','ir_tx'],
  ['FIIRBots extras','Radar','HARDWARE','LD2420 serial presence observations.','radar'],
  ['FIIRBots extras','W5500','HARDWARE','External Ethernet module SPI and link checks.','ethernet'],
  ['FIIRBots extras','Baseline inventory','PC','Enroll recognized devices and compare MAC addresses and ports.','inventory']
];
function renderToolCatalog(){
  const root=$('tool-catalog');root.replaceChildren();const filter=$('tool-filter').value;
  for(const [group,name,status,description,target] of toolCatalog){
    if(filter!=='all'&&filter!==status)continue;
    const card=element('article',undefined,'panel tool-card');
    card.append(element('small',group+' / '+status,'status '+(status==='PC'?'':'warn')),element('h2',name),element('p',description,'hint'));
    if(target){
      const b=button(status==='HARDWARE'?'Inspect test requirements':'Open tool',()=>{
        if(target==='wifi'){$('wifi-scan').focus();$('wifi-scan').scrollIntoView({block:'center'});}
        else if(target==='system'){$('system-refresh').click();}
        else if(testHelp[target]){chooseComponent(target);tab('config');}
        else tab(target);
      });card.append(b);
    }else card.append(element('span','Not implemented in this application','hint'));
    root.append(card);
  }
}
$('tool-filter').onchange=renderToolCatalog;
let networkAdapters=[];
async function loadAdapters(){
  const select=$('network-adapter');const previous=select.value;
  try{
    if(!state)await refresh();
    networkAdapters=await api('/api/network/adapters');select.replaceChildren();
    networkAdapters.forEach((a,i)=>{const o=element('option',a.interface+' / '+a.address+' / '+a.network);o.value=String(i);select.append(o);});
    if(!networkAdapters.length){select.append(element('option','No active private IPv4 adapters'));$('apply-network').disabled=true;return;}
    $('apply-network').disabled=false;
    const configured=networkAdapters.findIndex(a=>a.interface===state?.interface);
    select.value=configured>=0?String(configured):networkAdapters[Number(previous)]?previous:'0';
    $('network-scope').value=state?.network||networkAdapters[Number(select.value)].suggested_scope;
  }catch(e){$('network-config-status').textContent=e.message;}
}
$('refresh-adapters').onclick=loadAdapters;
$('network-adapter').onchange=()=>{$('network-scope').value=networkAdapters[Number($('network-adapter').value)]?.suggested_scope||'';};
$('network-config-form').onsubmit=async e=>{
  e.preventDefault();const a=networkAdapters[Number($('network-adapter').value)];if(!a)return;
  try{const result=await api('/api/network/configure','PUT',{network:$('network-scope').value.trim(),interface:a.interface});$('network-config-status').textContent='Selected '+result.network+' via '+result.interface+'. Press Scan to discover devices.';await refresh();}
  catch(error){$('network-config-status').textContent=error.message;}
};
$('wifi-scan').onclick=async()=>{
  const b=$('wifi-scan');b.disabled=true;$('wifi-status').textContent='Requesting Wi-Fi observation...';
  try{const r=await api('/api/wifi','POST');$('wifi-status').textContent=r.status+' / '+r.message+(r.observed_at?' / '+r.observed_at:'');$('wifi-output').textContent=r.output||'No observations available.';}
  catch(e){$('wifi-status').textContent=e.message;}
  finally{b.disabled=false;}
};
$('system-refresh').onclick=async()=>{
  try{const r=await api('/api/system');const list=$('system-info');list.replaceChildren();
    for(const [k,v] of Object.entries(r))list.append(element('dt',k.replaceAll('_',' ')),element('dd',v===null?'Not available':String(v)));
  }catch(e){toast(e.message);}
};
loadAdapters();
