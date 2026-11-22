'use strict';
async function toolAction(status, action) {
  try { await action(); } catch (error) { $(status).textContent = error.message; }
}
$('wireless-interfaces').onclick=()=>toolAction('wireless-status',async()=>{
  const result=await api('/api/wireless/interfaces');
  const select=$('wireless-interface');select.replaceChildren();
  for(const row of result.interfaces.filter(r=>r.mode==='monitor')){
    const option=element('option',row.name+' / channel '+(row.channel??'unknown'));option.value=row.name;select.append(option);
  }
  if(!select.options.length){const option=element('option','No monitor interface available');option.value='';select.append(option);}
  $('wireless-status').textContent=result.message;
});
$('wireless-form').onsubmit=event=>{
  event.preventDefault();toolAction('wireless-status',async()=>{
    await api('/api/wireless/scan','POST',{interface:$('wireless-interface').value,duration_s:Number($('wireless-duration').value)});
    $('wireless-status').textContent='Observation started. Refresh saved results after completion; Stop cancels without replacing the previous result.';
  });
};
$('wireless-refresh').onclick=()=>toolAction('wireless-status',async()=>{
  const result=await api('/api/wireless/latest');
  $('wireless-status').textContent=result.status+' / '+(result.finished_at||'No completed observation');
  $('wireless-output').textContent=JSON.stringify(result,null,2);
  const root=$('wireless-summary');root.replaceChildren();
  for(const [kind,count] of Object.entries(result.counts||{}))root.append(element('p',kind.replaceAll('_',' ')+': '+count));
});
async function compareBle(){
  const result=await api('/api/ble/defense');
  $('ble-defense-status').textContent=result.status+' / '+(result.finished_at||'No scan')+' / '+result.message;
  const root=$('ble-defense-devices');root.replaceChildren();
  for(const device of result.devices){
    const row=element('div',undefined,'ble-row');
    row.append(element('span',(device.name||'Unnamed')+' / '+device.address+' / '+device.comparison));
    row.append(button('Enroll / update',()=>toolAction('ble-defense-status',async()=>{
      await api('/api/ble/baseline','PUT',{scan_id:result.scan_id,addresses:[device.address]});await compareBle();
    })));root.append(row);
  }
  for(const device of result.not_observed)root.append(element('p','Not observed: '+(device.name||'Unnamed')+' / '+device.address,'hint'));
}
$('ble-defense-refresh').onclick=()=>toolAction('ble-defense-status',compareBle);
$('ble-baseline-clear').onclick=()=>{
  if(confirm('Clear the enrolled BLE baseline? Saved scan history will remain.'))toolAction('ble-defense-status',async()=>{
    await api('/api/ble/baseline','DELETE');await compareBle();
  });
};
async function renderRfHistory(){
  const result=await api('/api/rf/history');const canvas=$('rf-waterfall'),ctx=canvas.getContext('2d');
  ctx.clearRect(0,0,canvas.width,canvas.height);
  const height=canvas.height/Math.max(1,result.samples.length);
  result.samples.forEach((sample,y)=>sample.bins.forEach((value,x)=>{
    ctx.fillStyle=`hsl(${210-value*15} 65% ${10+value*6}%)`;ctx.fillRect(x*10,y*height,10,Math.ceil(height));
  }));
  $('rf-history-status').textContent=result.samples.length?`${result.samples.length} saved samples / ${result.samples[0].recorded_at} to ${result.samples.at(-1).recorded_at} UTC. Latest row is at the bottom.`:'No valid RF samples saved. Connect working nRF24 hardware.';
  $('rf-delta').textContent=result.delta?`Difference from baseline (detections per bin, 2400–2480 MHz):\n${result.delta.join(', ')}`:'No saved baseline comparison.';
}
$('rf-history-refresh').onclick=()=>toolAction('rf-history-status',renderRfHistory);
$('rf-baseline-save').onclick=()=>toolAction('rf-history-status',async()=>{
  await api('/api/rf/baseline','PUT');await renderRfHistory();
});
let gpsTrack=null, labObservation=null;
$('gps-snapshot').onclick = () => toolAction('snapshot-status', async () => {
  await api('/api/gps/wifi-snapshot','POST');
  $('snapshot-status').textContent = 'Recording. Check the operation status before downloading the last saved snapshot.';
});
$('gps-observe').onclick=()=>toolAction('gps-status',async()=>{
  await api('/api/gps/observe','POST',{duration_s:5});$('gps-status').textContent='Recording fresh fixes for 5 seconds. Refresh after completion.';
});
$('gps-refresh').onclick=()=>toolAction('gps-status',async()=>{
  gpsTrack=await api('/api/gps/latest');$('gps-status').textContent=gpsTrack.status+' / '+(gpsTrack.finished_at||'No completed track');
  $('gps-output').textContent=JSON.stringify(gpsTrack,null,2);
});
$('gps-waypoint-form').onsubmit=event=>{
  event.preventDefault();toolAction('gps-status',async()=>{
    if(!gpsTrack?.id)throw Error('Refresh a completed GPS track first');
    await api('/api/gps/waypoint','PUT',{track_id:gpsTrack.id,label:$('gps-waypoint-label').value});
    $('gps-status').textContent='Waypoint saved at the last recorded position (see track timestamp).';
  });
};
$('lab-targets-refresh').onclick=()=>toolAction('lab-status',async()=>{
  labObservation=await api('/api/wireless/latest');const select=$('lab-target');select.replaceChildren();
  for(const [index,pair] of (labObservation.clients||[]).entries()){
    const option=element('option',pair.bssid+' / '+pair.client);option.value=String(index);select.append(option);
  }
  if(!select.options.length){const option=element('option','No observed AP/client pairs');option.value='';select.append(option);}
  $('lab-confirm').checked=false;
  $('lab-status').textContent='Observation: '+(labObservation.finished_at||'none')+'. Only observations within five minutes are accepted.';
});
$('lab-deauth-form').onsubmit=event=>{
  event.preventDefault();toolAction('lab-status',async()=>{
    const pair=labObservation?.clients?.[Number($('lab-target').value)];
    if(!pair||$('lab-target').value==='')throw Error('Load a completed observation containing the lab pair first');
    await api('/api/lab/deauth','POST',{scan_id:labObservation.id,interface:labObservation.interface,...pair,
      frames:Number($('lab-frames').value),isolated_lab_confirmed:$('lab-confirm').checked});
    $('lab-status').textContent='Bounded test started. Verify the client independently; use Stop to cancel.';
    $('lab-confirm').checked=false;
  });
};
$('lab-result-refresh').onclick=()=>toolAction('lab-status',async()=>{
  const result=await api('/api/lab/latest');$('lab-status').textContent=result.status+' / effect '+result.effect;
  $('lab-output').textContent=JSON.stringify(result,null,2);
});
let probeObservation=null, namedLabProbes=[];
$('lab-probes-refresh').onclick=()=>toolAction('lab-beacon-status',async()=>{
  probeObservation=await api('/api/wireless/latest');
  namedLabProbes=(probeObservation.probes||[]).filter(p=>p.ssid&&p.source);
  const select=$('lab-probe');select.replaceChildren();
  namedLabProbes.forEach((probe,index)=>{const option=element('option',probe.source+' / '+probe.ssid);option.value=String(index);select.append(option);});
  if(!select.options.length){const option=element('option','No named probes observed');option.value='';select.append(option);}
  $('lab-beacon-confirm').checked=false;
  $('lab-beacon-status').textContent='Observation: '+(probeObservation.finished_at||'none')+'. Maximum age: five minutes.';
});
$('lab-beacon-form').onsubmit=event=>{
  event.preventDefault();toolAction('lab-beacon-status',async()=>{
    const probe=namedLabProbes[Number($('lab-probe').value)];
    if(!probe||$('lab-probe').value==='')throw Error('Load a named lab probe first');
    await api('/api/lab/beacon','POST',{scan_id:probeObservation.id,interface:probeObservation.interface,
      source:probe.source,ssid:probe.ssid,frames:Number($('lab-beacon-frames').value),isolated_lab_confirmed:$('lab-beacon-confirm').checked});
    $('lab-beacon-status').textContent='Bounded beacon test started. Verify reception independently.';$('lab-beacon-confirm').checked=false;
  });
};
$('lab-beacon-result').onclick=()=>toolAction('lab-beacon-status',async()=>{
  const result=await api('/api/lab/beacon/latest');$('lab-beacon-status').textContent=result.status+' / effect '+result.effect;
  $('lab-beacon-output').textContent=JSON.stringify(result,null,2);
});
