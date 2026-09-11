from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "JHL-Market-Edge-Shell.html"

if not TARGET.exists():
    raise SystemExit(f"JHL-Market-Edge-Shell.html not found beside this patch script: {TARGET}")

source = TARGET.read_text(encoding="utf-8")

if "DELTA 2.0 FIELD FEED" in source:
    raise SystemExit("Delta 2.0 field-feed patch already appears to be installed. Nothing changed.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"JHL-Market-Edge-Shell.pre_delta2_{stamp}.html")
shutil.copy2(TARGET, backup)

html = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a1015">
<title>JHL Market Edge — Delta 2.0</title>
<style>
:root{--bg:#081015;--panel:#0e1a22;--line:#263743;--text:#e7f0f4;--muted:#91a6b2;--good:#40dfaa;--warn:#ffbf5a;--bad:#ff6876;--blue:#70b9ff;--violet:#b293ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#132632 0,#081015 42rem);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:5;background:rgba(8,16,21,.94);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:14px max(14px,calc((100vw - 1120px)/2));display:flex;justify-content:space-between;gap:12px;align-items:center}
h1{font-size:18px;letter-spacing:.1em;margin:0}.sub,.small{color:var(--muted);font-size:12px}.status{color:var(--blue);font-size:12px}button{color:var(--text);background:#142732;border:1px solid #345060;border-radius:8px;padding:8px 11px;font-weight:700}
main{max-width:1120px;margin:auto;padding:16px}.banner{border:1px solid #405969;background:#10222c;color:#d7efff;border-radius:12px;padding:10px 12px;margin-bottom:14px;font-weight:700}.tabs{display:flex;gap:8px;overflow:auto;padding-bottom:10px}.tab{white-space:nowrap}.tab.active{border-color:var(--good);color:var(--good);background:#102820}
#summary{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 14px}.pill{border:1px solid var(--line);border-radius:999px;padding:5px 9px;color:var(--muted);font-size:12px}.pill b{color:var(--text)}
.card{background:linear-gradient(145deg,#10202a,#0c161d);border:1px solid var(--line);border-radius:15px;padding:15px;margin:0 0 12px;box-shadow:0 8px 28px rgba(0,0,0,.18)}.top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.pair{font-size:21px;font-weight:800;letter-spacing:.02em}.event{color:var(--blue);font-weight:700;font-size:12px}.badge{display:inline-block;border-radius:999px;padding:5px 8px;font-size:11px;font-weight:800;letter-spacing:.05em;border:1px solid var(--line)}.EXECUTION_ELIGIBLE{color:var(--good);border-color:var(--good);background:#0c2a20}.ELIGIBLE_WATCH{color:var(--warn);border-color:var(--warn);background:#2a210d}.BUILDING{color:var(--blue);border-color:var(--blue);background:#102436}.REJECTED,.NO_DATA{color:var(--bad);border-color:var(--bad);background:#32151a}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:13px 0}.metric{border:1px solid #223640;background:#0a151c;border-radius:10px;padding:9px}.metric label{display:block;color:var(--muted);font-size:10px;letter-spacing:.08em}.metric strong{font-size:15px}.row{display:flex;justify-content:space-between;gap:12px;border-top:1px solid #1f313b;padding:9px 0}.row span:first-child{color:var(--muted);white-space:nowrap}.row span:last-child{text-align:right;word-break:break-word}.clear{color:var(--good);font-weight:800}.shield{color:#ffc0c5}.fix{color:#d6e8f2}.empty{border:1px dashed #2d4755;border-radius:12px;padding:20px;color:var(--muted);text-align:center}.foot{color:var(--muted);font-size:11px;margin-top:8px}.hidden{display:none}
@media(min-width:760px){.grid{grid-template-columns:repeat(4,minmax(0,1fr))}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.cards .card{margin:0}}
</style>
</head>
<body>
<header>
 <div><h1>JHL MARKET EDGE</h1><div class="sub">DELTA 2.0 FIELD FEED · manual decision support</div></div>
 <div><span id="feed" class="status">Waiting for signals.json</span> <button id="refresh">Refresh</button></div>
</header>
<main>
 <div class="banner">ORDERS DISABLED · EXECUTION_ELIGIBLE means alert and manual review only.</div>
 <div id="summary"></div>
 <div class="tabs" id="tabs">
  <button class="tab active" data-tier="ALL">All</button><button class="tab" data-tier="EXECUTION_ELIGIBLE">Ready</button><button class="tab" data-tier="ELIGIBLE_WATCH">Watch</button><button class="tab" data-tier="BUILDING">Building</button><button class="tab" data-tier="REJECTED">Rejected</button><button class="tab" data-tier="NO_DATA">No data</button>
 </div>
 <section id="cards" class="cards"><div class="empty">Loading live Delta cards…</div></section>
 <div class="foot">Auto-refreshes every 15 seconds. Uses the latest completed 15m scanner snapshot.</div>
</main>
<script>
const el=id=>document.getElementById(id);let allRows=[],activeTier='ALL';
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=(v,d=6)=>v===null||v===undefined||v===''?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
function deltaSide(d){const e=String(d.event||'');return e.startsWith('DELTA_LONG')?'LONG':e.startsWith('DELTA_SHORT')?'SHORT':String(d.side||'NONE')}
function eligibility(row){const d=row.delta_tempo||{};return d.eligibility||{eligibility_state:'BUILDING',eligibility_blockers:['legacy_feed'],eligibility_reason:'Awaiting Delta 2.0 eligibility snapshot',side:deltaSide(d)}}
function card(row){const d=row.delta_tempo||{},s=row.structure||{},f=row.volume_flow||{},t=row.market_timing||{},noise=row.market_noise||{},e=eligibility(row);const state=String(e.eligibility_state||'BUILDING');const blockers=(e.eligibility_blockers||[]).join(', ')||'CLEAR';const shield=(d.shield||[]);const shieldText=Array.isArray(shield)?shield.join(', '):String(shield||'clear');const fix=d.repair_text||d.next_condition||'Continue observing';const room=d.room_to_risk;const geom=d.geometry_status||'PENDING';
 return `<article class="card"><div class="top"><div><div class="pair">${esc(row.pair)} <span class="event">${esc(deltaSide(d))}</span></div><div class="event">${esc(d.event||'NO_DELTA')} · ${esc(d.radar_state||'NO_TARGET')}</div></div><span class="badge ${esc(state)}">${esc(state)}</span></div>
 <div class="grid"><div class="metric"><label>ENTRY</label><strong>${n(d.entry,8)}</strong></div><div class="metric"><label>STOP</label><strong>${n(d.sl,8)}</strong></div><div class="metric"><label>TARGET</label><strong>${n(d.tp,8)}</strong></div><div class="metric"><label>GEOMETRY</label><strong>${room==null?esc(geom):n(room,2)+'R'}</strong></div></div>
 <div class="row"><span>Structure</span><span>${esc(s.market_condition||'UNKNOWN')} · ${esc(s.trend||'unknown')} · ${esc(s.zone||'neutral')}</span></div>
 <div class="row"><span>Execution</span><span>${esc(d.executioner_state||'NO_TRADE')} · BOS ${d.bos?'YES':'NO'}</span></div>
 <div class="row"><span>Gates</span><span class="${blockers==='CLEAR'?'clear':''}">${esc(blockers)}</span></div>
 <div class="row"><span>Shield</span><span class="${shieldText==='clear'?'clear':'shield'}">${esc(shieldText)}</span></div>
 <div class="row"><span>FIX</span><span class="fix">${esc(fix)}</span></div>
 <div class="row"><span>Context</span><span>${esc(t.timing_state||'OBSERVE')} · ${esc(noise.regime||'unavailable')} ${noise.noise_score==null?'':n(noise.noise_score,2)} · Flow ${f.ready?'READY':'OFF'}</span></div></article>`}
function render(){const rows=activeTier==='ALL'?allRows:allRows.filter(r=>String(eligibility(r).eligibility_state||'BUILDING')===activeTier);el('cards').innerHTML=rows.length?rows.map(card).join(''):`<div class="empty">No ${esc(activeTier==='ALL'?'live cards':activeTier+' cards')} in this completed-bar snapshot.</div>`;const counts={};allRows.forEach(r=>{const k=eligibility(r).eligibility_state||'BUILDING';counts[k]=(counts[k]||0)+1});el('summary').innerHTML=['EXECUTION_ELIGIBLE','ELIGIBLE_WATCH','BUILDING','REJECTED','NO_DATA'].map(k=>`<span class="pill"><b>${counts[k]||0}</b> ${k.replace('_',' ')}</span>`).join('')}
async function load(){try{const r=await fetch('./signals.json?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const p=await r.json();allRows=Array.isArray(p.signals)?p.signals:[];allRows.sort((a,b)=>{const order={EXECUTION_ELIGIBLE:0,ELIGIBLE_WATCH:1,BUILDING:2,REJECTED:3,NO_DATA:4};return (order[eligibility(a).eligibility_state]??9)-(order[eligibility(b).eligibility_state]??9)});el('feed').textContent=`Live ${p.ts||new Date().toISOString()} · ${allRows.length} pairs`;render()}catch(err){el('feed').textContent='Feed error: '+err.message;el('cards').innerHTML='<div class="empty">Waiting for signals.json. Keep the scanner and local web server running.</div>'}}
el('refresh').onclick=load;el('tabs').onclick=e=>{const b=e.target.closest('[data-tier]');if(!b)return;activeTier=b.dataset.tier;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===b));render()};load();setInterval(load,15000);
</script>
</body>
</html>
'''

TARGET.write_text(html, encoding="utf-8")
print(f"Patched: {TARGET.name}")
print(f"Backup:  {backup.name}")
print("Delta 2.0 field feed installed. No scanner, alert, or execution logic changed.")
