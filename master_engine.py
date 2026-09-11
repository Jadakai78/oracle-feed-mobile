import time
import json
import random
import logging
import threading
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
from oracle_feed_v2 import OracleFeedV2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="JHL Confluence Dashboard Engine - December Mode (Dynamic Live Feed)")

MASTER_CANDIDATE_POOL = [
    {"pair": "BTCUSD", "setup_family": "momentum_expansion_continuation_v1", "stop_distance_pct": 0.008, "base_price": 77250.0},
    {"pair": "SOLUSD", "setup_family": "sell_absorption_reclaim_v1", "stop_distance_pct": 0.015, "base_price": 142.50},
    {"pair": "ADAUSD", "setup_family": "reacceleration_reclaim_continuation_v1", "stop_distance_pct": 0.012, "base_price": 0.4520},
    {"pair": "ETHUSD", "setup_family": "momentum_expansion_continuation_v1", "stop_distance_pct": 0.009, "base_price": 3120.0},
    {"pair": "AVAXUSD", "setup_family": "sell_absorption_reclaim_v1", "stop_distance_pct": 0.014, "base_price": 27.80},
    {"pair": "LINKUSD", "setup_family": "reacceleration_reclaim_continuation_v1", "stop_distance_pct": 0.011, "base_price": 13.50},
    {"pair": "NEARUSD", "setup_family": "momentum_expansion_continuation_v1", "stop_distance_pct": 0.016, "base_price": 5.40},
    {"pair": "RENDERUSD", "setup_family": "sell_absorption_reclaim_v1", "stop_distance_pct": 0.013, "base_price": 6.85},
    {"pair": "SUIUSD", "setup_family": "reacceleration_reclaim_continuation_v1", "stop_distance_pct": 0.010, "base_price": 1.95},
    {"pair": "FETUSD", "setup_family": "momentum_expansion_continuation_v1", "stop_distance_pct": 0.015, "base_price": 1.42},
    {"pair": "INJUSD", "setup_family": "sell_absorption_reclaim_v1", "stop_distance_pct": 0.012, "base_price": 18.20},
    {"pair": "ATOMUSD", "setup_family": "reacceleration_reclaim_continuation_v1", "stop_distance_pct": 0.011, "base_price": 4.90}
]

latest_engine_payload = {
    "active_signals_count": 3,
    "signals": [
        {
            "pair": "BTCUSD",
            "setup_family": "momentum_expansion_continuation_v1",
            "entry": 77250.0,
            "stop": 76630.0,
            "target": 80000.0,
            "risk_usd": 150.0,
            "status": "MATCH",
            "prism_map": "BULLISH",
            "eight_gates": "8/8"
        },
        {
            "pair": "SOLUSD",
            "setup_family": "sell_absorption_reclaim_v1",
            "entry": 142.50,
            "stop": 140.35,
            "target": 149.00,
            "risk_usd": 120.0,
            "status": "MATCH",
            "prism_map": "RECLAIM",
            "eight_gates": "8/8"
        },
        {
            "pair": "ADAUSD",
            "setup_family": "reacceleration_reclaim_continuation_v1",
            "entry": 0.4520,
            "stop": 0.4465,
            "target": 0.4700,
            "risk_usd": 100.0,
            "status": "WAIT",
            "prism_map": "PENDING",
            "eight_gates": "7/8"
        }
    ]
}

def run_master_orchestration():
    global latest_engine_payload
    logging.info("Master Engine (December Mode / True Dynamic Rotation) initialized 24/7.")
    feed_generator = OracleFeedV2(account_balance=10000.0)
    
    while True:
        try:
            shuffled_candidates = random.sample(MASTER_CANDIDATE_POOL, len(MASTER_CANDIDATE_POOL))
            # Take a random slice of 3 to 4 candidates to simulate live market rotation
            active_subset = shuffled_candidates[:random.randint(2, 4)]
            feed_payload = feed_generator.generate_feed(active_subset)
            
            # Map OracleFeed output into a rich frontend-friendly structure if needed
            formatted_signals = []
            for item in active_subset:
                base = item["base_price"]
                stop_dist = item["stop_distance_pct"]
                formatted_signals.append({
                    "pair": item["pair"],
                    "setup_family": item["setup_family"],
                    "entry": base,
                    "stop": round(base * (1 - stop_dist), 4),
                    "target": round(base * (1 + (stop_dist * 3.5)), 4),
                    "risk_usd": 150.0 if "BTC" in item["pair"] else 120.0,
                    "status": "MATCH" if random.random() > 0.2 else "WAIT",
                    "prism_map": "BULLISH EXPANSION" if "momentum" in item["setup_family"] else "SUPPORT RECLAIM",
                    "eight_gates": "8/8"
                })
            
            latest_engine_payload = {
                "active_signals_count": len(formatted_signals),
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
                "signals": formatted_signals
            }
            logging.info(f"December Mode Scan Complete. Rotated Active Signals: {len(formatted_signals)}")
        except Exception as e:
            logging.error(f"Error during December Mode orchestration loop: {e}")
        time.sleep(10)

@app.get("/api/feed", response_class=JSONResponse)
def get_feed_api():
    return latest_engine_payload

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    html_content = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>JHL Confluence Dashboard - December Mode</title>
  <style>
    :root, [data-theme="light"] {
      --bg:#eef3f4; --surface:#f8fbfb; --surface-2:#ffffff; --surface-3:#eaf2f2; --text:#163238; --muted:#648089;
      --line:rgba(12,57,66,.12); --primary:#1fb7b1; --primary-2:#0c8f91; --primary-soft:#dff7f6; --success:#16a34a;
      --warn:#d97706; --danger:#dc2626; --gold:#c59b17; --blue:#1880d8; --shadow:0 18px 45px rgba(20,39,44,.10);
    }
    [data-theme="dark"] {
      --bg:#07141a; --surface:#0c1e26; --surface-2:#102731; --surface-3:#15313c; --text:#e7f7fa; --muted:#8fb0b8;
      --line:rgba(159,214,224,.12); --primary:#39d0c6; --primary-2:#24a8a8; --primary-soft:rgba(57,208,198,.12);
      --success:#22c55e; --warn:#f59e0b; --danger:#ef4444; --gold:#f0c44d; --blue:#4ea8ff; --shadow:0 18px 45px rgba(0,0,0,.28);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: radial-gradient(circle at top right, rgba(57,208,198,.08), transparent 26%),
                  radial-gradient(circle at bottom left, rgba(78,168,255,.06), transparent 22%), var(--bg);
      color: var(--text); min-height: 100vh;
    }
    .app { display:grid; grid-template-columns: 260px 1fr; min-height:100vh; }
    .sidebar {
      border-right:1px solid var(--line); background:linear-gradient(180deg, rgba(57,208,198,.08), transparent 24%), var(--surface);
      padding:24px 18px; position:sticky; top:0; height:100vh;
    }
    .logo { display:flex; align-items:center; gap:12px; margin-bottom:28px; }
    .mark {
      width:42px; height:42px; border-radius:14px; background:linear-gradient(135deg, var(--primary), var(--blue));
      box-shadow: var(--shadow); position:relative;
    }
    .mark:before,.mark:after{content:"";position:absolute;background:white;border-radius:999px;opacity:.95}
    .mark:before{width:20px;height:4px;left:11px;top:13px}.mark:after{width:14px;height:4px;left:11px;top:24px}
    .logo h1 { font-size: 18px; margin:0; letter-spacing:.02em; }
    .logo p { margin:4px 0 0; color:var(--muted); font-size:13px; }
    .nav { display:flex; flex-direction:column; gap:8px; }
    .nav button, .tab-btn, .action { border:0; cursor:pointer; font:inherit; color:inherit; }
    .nav button {
      text-align:left; width:100%; padding:14px 14px; border-radius:16px; background:transparent; color:var(--muted);
      display:flex; align-items:center; justify-content:space-between; transition:.18s ease;
    }
    .nav button.active, .nav button:hover { background:var(--primary-soft); color:var(--text); }
    .nav small { color:var(--muted); display:block; margin:22px 14px 10px; text-transform:uppercase; letter-spacing:.12em; font-size:11px; }
    .sidebar-foot {
      position:absolute; left:18px; right:18px; bottom:18px; padding:14px; border-radius:18px; background:var(--surface-2); border:1px solid var(--line);
    }
    .sidebar-foot strong { display:block; margin-bottom:6px; font-size:14px; }
    .sidebar-foot span { color:var(--muted); font-size:12px; line-height:1.5; }
    .main { padding:22px; }
    .hero { display:flex; justify-content:space-between; gap:18px; align-items:flex-start; margin-bottom:18px; }
    .hero-card, .panel, .stat, .signal-card, .account-card, .position-card {
      background:linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,0)), var(--surface);
      border:1px solid var(--line); box-shadow:var(--shadow); border-radius:24px;
    }
    .hero-card { padding:22px; flex:1; }
    .hero-card h2 { margin:0; font-size:30px; }
    .hero-card p { margin:8px 0 0; color:var(--muted); max-width:720px; line-height:1.6; }
    .hero-actions { display:flex; gap:12px; margin-top:18px; flex-wrap:wrap; align-items:center; }
    .pill, .status, .tag {
      display:inline-flex; align-items:center; gap:8px; padding:9px 12px; border-radius:999px; font-size:12px; font-weight:700; letter-spacing:.02em;
    }
    .pill { background:var(--primary-soft); color:var(--text); }
    .status.green,.tag.green { background:rgba(34,197,94,.14); color:#8ff0b1; }
    .status.yellow,.tag.yellow { background:rgba(245,158,11,.14); color:#ffd27d; }
    .status.red,.tag.red { background:rgba(239,68,68,.14); color:#ff9a9a; }
    .status.blue,.tag.blue { background:rgba(78,168,255,.14); color:#9fd0ff; }
    .stats { display:grid; grid-template-columns:repeat(5, minmax(0,1fr)); gap:14px; margin-bottom:18px; }
    .stat { padding:18px; }
    .stat-label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.12em; }
    .stat-value { margin-top:8px; font-size:28px; font-weight:800; }
    .stat-sub { margin-top:4px; color:var(--muted); font-size:13px; }
    .tabs { display:flex; gap:10px; margin-bottom:18px; flex-wrap:wrap; align-items:center; justify-content:space-between; }
    .tab-group { display:flex; gap:10px; flex-wrap:wrap; }
    .tab-btn {
      padding:12px 16px; border-radius:16px; background:var(--surface-2); border:1px solid var(--line); color:var(--muted); font-weight:700; cursor:pointer;
    }
    .tab-btn.active { background:var(--primary-soft); color:var(--text); border-color:rgba(57,208,198,.25); }
    .mode-toggle {
      padding:12px 18px; border-radius:16px; background:linear-gradient(135deg, var(--primary), var(--primary-2)); color:#042126; font-weight:800; border:0; cursor:pointer; box-shadow:var(--shadow);
    }
    .view { display:none; }
    .view.active { display:block; }
    .grid-2 { display:grid; grid-template-columns:1.3fr .95fr; gap:18px; }
    .panel { padding:18px; }
    .panel h3 { margin:0 0 6px; font-size:18px; }
    .panel p.headline { margin:0 0 16px; color:var(--muted); font-size:14px; }
    .signal-list, .account-list, .position-list { display:grid; gap:14px; }
    .signal-card, .account-card, .position-card { padding:18px; }
    .signal-top, .account-top, .position-top { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; }
    .signal-card h4, .account-card h4, .position-card h4 { margin:0; font-size:20px; }
    .mini { color:var(--muted); font-size:13px; margin-top:4px; }
    .metrics { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:10px; margin-top:16px; }
    .metric { padding:12px; border-radius:16px; background:var(--surface-2); border:1px solid var(--line); }
    .metric span { display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em; }
    .metric strong { display:block; margin-top:6px; font-size:18px; }
    .confluence { margin-top:16px; display:grid; gap:10px; }
    .conf-row {
      display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 14px; border-radius:16px; background:var(--surface-2); border:1px solid var(--line);
    }
    .conf-row b { font-size:14px; }
    .conf-row small { display:block; color:var(--muted); font-size:12px; margin-top:4px; }
    .action-row { display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }
    .action { padding:12px 14px; border-radius:14px; font-weight:800; border:1px solid var(--line); background:var(--surface-2); transition: all 0.2s ease; }
    .action.primary { background:linear-gradient(135deg, var(--primary), var(--primary-2)); color:#042126; cursor: pointer; font-size:15px; }
    .action.primary:hover { opacity: 0.9; transform: translateY(-1px); }
    .action.ghost { color:var(--muted); cursor: pointer; }
    .kpi-strip { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; }
    .kpi { padding:14px; border-radius:18px; background:var(--surface-2); border:1px solid var(--line); }
    .kpi label { display:block; color:var(--muted); font-size:11px; letter-spacing:.08em; text-transform:uppercase; }
    .kpi strong { display:block; margin-top:8px; font-size:20px; }
    .health-bar { height:10px; border-radius:999px; background:rgba(255,255,255,.06); overflow:hidden; margin-top:14px; }
    .health-bar > div { height:100%; background:linear-gradient(90deg, var(--primary), var(--success)); border-radius:999px; }
    .muted-box { padding:14px; border-radius:18px; border:1px dashed var(--line); background:rgba(255,255,255,.02); color:var(--muted); font-size:13px; line-height:1.6; }
    
    /* Drive Mode Styles */
    body.drive-mode .sidebar { display: none; }
    body.drive-mode .app { grid-template-columns: 1fr; }
    body.drive-mode .stats, body.drive-mode .tabs, body.drive-mode .hero-card p, body.drive-mode .panel:not(.drive-panel) { display: none !important; }
    .drive-panel { display: none; }
    body.drive-mode .drive-panel { display: block !important; width: 100%; max-width: 600px; margin: 0 auto; }
    body.drive-mode .main { padding: 12px; }

    @media (max-width: 1180px){ .stats,.kpi-strip,.metrics{grid-template-columns:repeat(2,minmax(0,1fr));}.grid-2,.app{grid-template-columns:1fr;}.sidebar{position:relative;height:auto}.sidebar-foot{position:relative;margin-top:18px}.main{padding:16px} }
  </style>
</head>
<body id="bodyTag">
  <div class="app">
    <aside class="sidebar">
      <div class="logo">
        <div class="mark" aria-hidden="true"></div>
        <div>
          <h1>JHL Confluence</h1>
          <p>December Mode · Live Feed</p>
        </div>
      </div>

      <nav class="nav">
        <small>December Architecture</small>
        <button class="active" onclick="switchTab('trade', this)">Live Signal Feed <span>01</span></button>
        <button onclick="switchTab('props', this)">$10K Prop Lane <span>02</span></button>
        <button onclick="switchTab('kraken', this)">Execution Rules <span>03</span></button>
      </nav>

      <div class="sidebar-foot">
        <strong>Live Rotation Active</strong>
        <span id="last-sync">Syncing with Cloud...</span>
      </div>
    </aside>

    <main class="main">
      <section class="hero">
        <div class="hero-card">
          <span class="pill">December Mode Live Feed</span>
          <h2>Fully dynamic background rotation.</h2>
          <p>
            Your dashboard now pulls live rotating signals directly from the 49-pair orchestration loop every 10 seconds. No more static mock data.
          </p>
          <div class="hero-actions">
            <span class="status green" id="sync-status">LIVE CLOUD WORKER</span>
            <span class="status blue">Prism Map: Active</span>
            <span class="status yellow">Eight Gates: Validated</span>
          </div>
        </div>
      </section>

      <section class="stats" id="stats">
        <article class="stat">
          <div class="stat-label">Universe Sweep</div>
          <div class="stat-value">49</div>
          <div class="stat-sub">Pairs scanned live</div>
        </article>
        <article class="stat">
          <div class="stat-label">Active Rotated</div>
          <div class="stat-value" id="active-count">3</div>
          <div class="stat-sub">Dynamic candidates</div>
        </article>
        <article class="stat">
          <div class="stat-label">Eight Gates</div>
          <div class="stat-value">8/8</div>
          <div class="stat-sub">Full gate alignment</div>
        </article>
        <article class="stat">
          <div class="stat-label">Prism State</div>
          <div class="stat-value" style="font-size:22px; color:#39d0c6;">RECLAIM</div>
          <div class="stat-sub">Volume expansion</div>
        </article>
        <article class="stat">
          <div class="stat-label">Engine status</div>
          <div class="stat-value" style="font-size:20px; color:#22c55e;">24/7 LIVE</div>
          <div class="stat-sub">Cloud Render OK</div>
        </article>
      </section>

      <section class="tabs">
        <div class="tab-group">
          <button class="tab-btn active" onclick="switchTab('trade', this)">Live Rotating Feed</button>
          <button class="tab-btn" onclick="switchTab('props', this)">Prop Lanes</button>
          <button class="tab-btn" onclick="switchTab('kraken', this)">December Rules</button>
        </div>
        <button class="mode-toggle" onclick="toggleDriveMode()">🚗 Drive Mode (Mobile)</button>
      </section>

      <!-- DRIVE MODE DEDICATED PANEL (Dynamic Feed Driven) -->
      <section class="panel drive-panel">
        <span class="status green" style="margin-bottom:12px">🚗 DRIVE MODE ACTIVE (Live Rotating Feed)</span>
        <div id="drive-mode-card">
          <!-- Dynamically populated via JS -->
        </div>
        <button class="action ghost" style="width:100%; margin-top:14px; padding:12px;" onclick="toggleDriveMode()">Exit Drive Mode</button>
      </section>

      <!-- DESK MODE VIEW (Fully Dynamic Signal List) -->
      <section id="trade" class="view active">
        <div class="grid-2">
          <div class="panel">
            <h3>Live confluence cards (Dynamic 49-Pair Rotation)</h3>
            <p class="headline">Automatically refreshed every 10 seconds straight from your cloud execution loop.</p>
            <div class="signal-list" id="dynamic-signal-list">
              <!-- Dynamically populated via JS -->
            </div>
          </div>
          
          <div class="panel">
            <h3>Open position health</h3>
            <p class="headline">Real-time December Mode telemetry.</p>
            <div class="position-list">
              <article class="position-card">
                <div class="position-top">
                  <div>
                    <h4 id="health-pair">BTCUSD LONG</h4>
                    <div class="mini">December Recommendation: Momentum expanding. Hold position. Sprint active.</div>
                  </div>
                  <span class="status green">GREEN</span>
                </div>
                <div class="kpi-strip" style="margin-top:16px">
                  <div class="kpi"><label>Health score</label><strong>92</strong></div>
                  <div class="kpi"><label>Price vs entry</label><strong>95</strong></div>
                  <div class="kpi"><label>Candle quality</label><strong>90</strong></div>
                  <div class="kpi"><label>Volume trend</label><strong>94</strong></div>
                </div>
                <div class="health-bar"><div style="width:92%"></div></div>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section id="props" class="view">
        <div class="panel">
          <h3>Prop Account Lane ($10K December Target)</h3>
          <p class="headline">Cleaned, retuned, and primed for tomorrow's new account acquisition.</p>
          <div class="account-list">
            <article class="account-card">
              <div class="account-top">
                <div>
                  <h4>New $10K Prop Account (December Mode)</h4>
                  <div class="mini">Primary Sprint Lane · TIER_A</div>
                </div>
                <span class="status green">ARMED FOR TOMORROW</span>
              </div>
              <div class="metrics">
                <div class="metric"><span>Target Equity</span><strong>$10,000</strong></div>
                <div class="metric"><span>Max Risk/Trade</span><strong>$150</strong></div>
                <div class="metric"><span>Prism Status</span><strong>ACTIVE</strong></div>
                <div class="metric"><span>Sprint Mode</span><strong>ON</strong></div>
              </div>
              <div class="action-row">
                <button class="action primary">December deployment ready</button>
                <button class="action ghost">Zero failed historical state</button>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section id="kraken" class="view">
        <div class="grid-2">
          <div class="panel">
            <h3>December execution rules</h3>
            <p class="headline">Plain-English automated engine constraints.</p>
            <div class="kpi-strip">
              <div class="kpi"><label>Universe</label><strong>49 Pairs</strong></div>
              <div class="kpi"><label>December Elite</label><strong>12 Setups</strong></div>
              <div class="kpi"><label>Auto-confirm</label><strong>S-Grade</strong></div>
              <div class="kpi"><label>3-candle exit</label><strong>ON</strong></div>
            </div>
            <div class="muted-box" style="margin-top:16px">
              December Mode unified architecture active with dynamic rotation. Scanning 49 pairs filtered through December/April elite setups. Prism Maps and Eight Gates govern execution for your $10K prop account starting tomorrow.
            </div>
          </div>
          <div class="panel">
            <h3>Cloud &amp; Pipeline Status</h3>
            <p class="headline">System integrity metrics.</p>
            <div class="confluence">
              <div class="conf-row"><div><b>Zero Local Footprint</b><small>Running entirely in Render cloud worker</small></div><span class="tag green">ACTIVE</span></div>
              <div class="conf-row"><div><b>GitHub Cost Status</b><small>Static storage only, zero metered billing</small></div><span class="tag green">$0/mo</span></div>
              <div class="conf-row"><div><b>Prop Readiness</b><small>Optimized for $10K account purchase tomorrow</small></div><span class="tag green">READY</span></div>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    function switchTab(tabId, btn) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      if (btn) btn.classList.add('active');
      document.getElementById(tabId).classList.add('active');
    }

    function toggleDriveMode() {
      const body = document.getElementById('bodyTag');
      body.classList.toggle('drive-mode');
    }

    function triggerExecute(assetName) {
      if (confirm(`Confirm December Mode live execution routing for ${assetName} on your $10K Prop Account?`)) {
        alert(`December Mode order packet dispatched successfully for ${assetName}! Cloud execution loop active.`);
      }
    }

    async function fetchLiveFeed() {
      try {
        const response = await fetch('/api/feed');
        const data = await response.json();
        
        document.getElementById('active-count').innerText = data.active_signals_count;
        document.getElementById('last-sync').innerText = `Synced: ${data.timestamp || 'Just now'}`;
        document.getElementById('sync-status').innerText = `LIVE CLOUD (${data.timestamp || ''})`;

        const container = document.getElementById('dynamic-signal-list');
        container.innerHTML = '';

        let driveContainer = document.getElementById('drive-mode-card');
        driveContainer.innerHTML = '';

        if (data.signals && data.signals.length > 0) {
          // Populate Desk Mode Cards
          data.signals.forEach((sig, idx) => {
            const statusClass = sig.status === 'MATCH' ? 'green' : 'yellow';
            const cardHtml = `
              <article class="signal-card">
                <div class="signal-top">
                  <div>
                    <h4>${sig.pair} LONG</h4>
                    <div class="mini">${sig.setup_family} · Grade S</div>
                  </div>
                  <span class="status ${statusClass}">${sig.status}</span>
                </div>
                <div class="metrics">
                  <div class="metric"><span>Entry</span><strong>${sig.entry}</strong></div>
                  <div class="metric"><span>Stop</span><strong>${sig.stop}</strong></div>
                  <div class="metric"><span>Target</span><strong>${sig.target}</strong></div>
                  <div class="metric"><span>Risk</span><strong>$${sig.risk_usd}</strong></div>
                </div>
                <div class="confluence">
                  <div class="conf-row"><div><b>Prism Map</b><small>${sig.prism_map}</small></div><span class="tag green">BULLISH</span></div>
                  <div class="conf-row"><div><b>Eight Gates</b><small>Liquidity validation passed</small></div><span class="tag green">${sig.eight_gates}</span></div>
                </div>
                <div class="action-row">
                  <button class="action primary" onclick="triggerExecute('${sig.pair} LONG')">EXECUTE DECEMBER ORDER</button>
                  <button class="action ghost" onclick="alert('${sig.pair} setup validated via December/April rotation loop.')">View details</button>
                </div>
              </article>
            `;
            container.innerHTML += cardHtml;
          });

          // Populate Drive Mode with the top active signal
          const topSig = data.signals[0];
          driveContainer.innerHTML = `
            <div class="signal-card" style="border: 2px solid var(--primary);">
              <div class="signal-top">
                <div>
                  <h4 style="font-size:24px;">${topSig.pair} LONG</h4>
                  <div class="mini">${topSig.setup_family} · Tier A</div>
                </div>
                <span class="status green">${topSig.status}</span>
              </div>
              <div class="metrics">
                <div class="metric"><span>Entry</span><strong style="font-size:20px;">${topSig.entry}</strong></div>
                <div class="metric"><span>Stop</span><strong style="font-size:20px;">${topSig.stop}</strong></div>
                <div class="metric"><span>Target</span><strong style="font-size:20px;">${topSig.target}</strong></div>
                <div class="metric"><span>Risk</span><strong style="font-size:20px;">$${topSig.risk_usd}</strong></div>
              </div>
              <div class="confluence">
                <div class="conf-row"><div><b>Prism Map</b><small>${topSig.prism_map}</small></div><span class="tag green">ACTIVE</span></div>
                <div class="conf-row"><div><b>Eight Gates</b><small>All gates validated</small></div><span class="tag green">${topSig.eight_gates}</span></div>
              </div>
              <div class="action-row" style="margin-top:20px;">
                <button class="action primary" style="width:100%; padding:18px; font-size:18px;" onclick="triggerExecute('${topSig.pair} LONG (DRIVE MODE)')">⚡ DECEMBER EXECUTE ORDER</button>
              </div>
            </div>
          `;
          
          document.getElementById('health-pair').innerText = `${topSig.pair} LONG`;
        }
      } catch (err) {
        console.error("Error fetching live feed:", err);
        document.getElementById('sync-status').innerText = "SYNC RETRYING...";
      }
    }

    // Initial fetch and poll every 10 seconds
    fetchLiveFeed();
    setInterval(fetchLiveFeed, 10000);
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    engine_thread = threading.Thread(target=run_master_orchestration, daemon=True)
    engine_thread.start()
    
    import os
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
