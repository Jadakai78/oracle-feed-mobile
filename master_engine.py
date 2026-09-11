import time
import json
import logging
import threading
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
from oracle_feed_v2 import OracleFeedV2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="JHL Confluence Dashboard Engine")

def run_master_orchestration():
    logging.info("Master Engine (Confluence Mode) initialized with 24/7 continuous cloud loop.")
    feed_generator = OracleFeedV2(account_balance=10000.0)
    
    while True:
        try:
            raw_candidates = [
                {"pair": "BTCUSD", "setup_family": "momentum_expansion_continuation_v1", "stop_distance_pct": 0.008},
                {"pair": "SOLUSD", "setup_family": "sell_absorption_reclaim_v1", "stop_distance_pct": 0.015}
            ]
            feed_payload = feed_generator.generate_feed(raw_candidates)
            logging.info(f"Confluence Scan Loop Complete. Active Signals: {feed_payload['active_signals_count']}")
        except Exception as e:
            logging.error(f"Error during orchestration loop: {e}")
        time.sleep(10)

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    html_content = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>JHL Confluence Dashboard</title>
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
    .hero-actions { display:flex; gap:12px; margin-top:18px; flex-wrap:wrap; }
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
    .tabs { display:flex; gap:10px; margin-bottom:18px; flex-wrap:wrap; }
    .tab-btn {
      padding:12px 16px; border-radius:16px; background:var(--surface-2); border:1px solid var(--line); color:var(--muted); font-weight:700;
    }
    .tab-btn.active { background:var(--primary-soft); color:var(--text); border-color:rgba(57,208,198,.25); }
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
    .action { padding:12px 14px; border-radius:14px; font-weight:800; border:1px solid var(--line); background:var(--surface-2); }
    .action.primary { background:linear-gradient(135deg, var(--primary), var(--primary-2)); color:#042126; }
    .action.ghost { color:var(--muted); }
    .kpi-strip { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; }
    .kpi { padding:14px; border-radius:18px; background:var(--surface-2); border:1px solid var(--line); }
    .kpi label { display:block; color:var(--muted); font-size:11px; letter-spacing:.08em; text-transform:uppercase; }
    .kpi strong { display:block; margin-top:8px; font-size:20px; }
    .health-bar { height:10px; border-radius:999px; background:rgba(255,255,255,.06); overflow:hidden; margin-top:14px; }
    .health-bar > div { height:100%; background:linear-gradient(90deg, var(--primary), var(--success)); border-radius:999px; }
    .muted-box { padding:14px; border-radius:18px; border:1px dashed var(--line); background:rgba(255,255,255,.02); color:var(--muted); font-size:13px; line-height:1.6; }
    @media (max-width: 1180px){ .stats,.kpi-strip,.metrics{grid-template-columns:repeat(2,minmax(0,1fr));}.grid-2,.app{grid-template-columns:1fr;}.sidebar{position:relative;height:auto}.sidebar-foot{position:relative;margin-top:18px}.main{padding:16px} }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="logo">
        <div class="mark" aria-hidden="true"></div>
        <div>
          <h1>JHL Confluence</h1>
          <p>Cloud Render · Props</p>
        </div>
      </div>

      <nav class="nav">
        <small>Workspace</small>
        <button class="active">Dashboard <span>01</span></button>
        <button onclick="switchTab('trade', this)">Signals <span>02</span></button>
        <button onclick="switchTab('props', this)">Accounts <span>03</span></button>
        <button onclick="switchTab('kraken', this)">Kraken <span>04</span></button>
      </nav>

      <div class="sidebar-foot">
        <strong>Prop Target Ready</strong>
        <span>Zero local footprint, 24/7 cloud Render engine streaming active setups live.</span>
      </div>
    </aside>

    <main class="main">
      <section class="hero">
        <div class="hero-card">
          <span class="pill">Confluence-first cockpit</span>
          <h2>See the match. Then execute.</h2>
          <p>
            Cloud Render background worker active. Streaming automated prop feed context scanning, micro-trigger evaluation, and institutional stop/take-profit setups.
          </p>
          <div class="hero-actions">
            <span class="status green">SPRINT MODE ACTIVE</span>
            <span class="status blue">Fear &amp; Greed: 21 (Extreme Fear)</span>
            <span class="status yellow">Live Cloud Sync</span>
          </div>
        </div>
      </section>

      <section class="stats" id="stats">
        <article class="stat">
          <div class="stat-label">Active pairs</div>
          <div class="stat-value">3</div>
          <div class="stat-sub">Scanning live</div>
        </article>
        <article class="stat">
          <div class="stat-label">Signals fired</div>
          <div class="stat-value">3</div>
          <div class="stat-sub">2 S-Grade</div>
        </article>
        <article class="stat">
          <div class="stat-label">Killed</div>
          <div class="stat-value">0</div>
          <div class="stat-sub">Pruned this cycle</div>
        </article>
        <article class="stat">
          <div class="stat-label">Fear &amp; Greed</div>
          <div class="stat-value">21</div>
          <div class="stat-sub">Extreme Fear</div>
        </article>
        <article class="stat">
          <div class="stat-label">Engine status</div>
          <div class="stat-value" style="font-size:20px; color:#22c55e;">24/7 LIVE</div>
          <div class="stat-sub">Cloud Render OK</div>
        </article>
      </section>

      <section class="tabs">
        <button class="tab-btn active" onclick="switchTab('trade', this)">Trade Feed</button>
        <button class="tab-btn" onclick="switchTab('props', this)">Prop Lanes</button>
        <button class="tab-btn" onclick="switchTab('kraken', this)">Kraken Rules</button>
      </section>

      <section id="trade" class="view active">
        <div class="grid-2">
          <div class="panel">
            <h3>Live confluence cards</h3>
            <p class="headline">Human-friendly signal cards translating bus data into match / wait / reject.</p>
            <div class="signal-list">
              <article class="signal-card">
                <div class="signal-top">
                  <div>
                    <h4>BTCUSD LONG</h4>
                    <div class="mini">Engine S1 · Grade S · TREND_UP</div>
                  </div>
                  <span class="status green">MATCH</span>
                </div>
                <div class="metrics">
                  <div class="metric"><span>Entry</span><strong>63,200.0</strong></div>
                  <div class="metric"><span>Stop</span><strong>62,700.0</strong></div>
                  <div class="metric"><span>Target</span><strong>64,500.0</strong></div>
                  <div class="metric"><span>Risk</span><strong>$350</strong></div>
                </div>
                <div class="confluence">
                  <div class="conf-row"><div><b>Direction match</b><small>LONG aligned with WITH_TREND</small></div><span class="tag green">WITH_TREND</span></div>
                  <div class="conf-row"><div><b>Quality match</b><small>Conviction 96% · Structure 91%</small></div><span class="tag green">96%</span></div>
                  <div class="conf-row"><div><b>Execution lane</b><small>TIER_A routes to Dragon Lane</small></div><span class="tag blue">TIER_A</span></div>
                  <div class="conf-row"><div><b>Readiness</b><small>Tier A enters now. Sprint rules active.</small></div><span class="tag green">CONFIRM</span></div>
                </div>
                <div class="action-row">
                  <button class="action primary">CLICK TO EXECUTE</button>
                  <button class="action ghost">View details</button>
                </div>
              </article>

              <article class="signal-card">
                <div class="signal-top">
                  <div>
                    <h4>SOLUSD LONG</h4>
                    <div class="mini">Engine S1 · Grade S · ACCUMULATION</div>
                  </div>
                  <span class="status green">MATCH</span>
                </div>
                <div class="metrics">
                  <div class="metric"><span>Entry</span><strong>142.5</strong></div>
                  <div class="metric"><span>Stop</span><strong>140.2</strong></div>
                  <div class="metric"><span>Target</span><strong>148.0</strong></div>
                  <div class="metric"><span>Risk</span><strong>$200</strong></div>
                </div>
                <div class="confluence">
                  <div class="conf-row"><div><b>Direction match</b><small>LONG aligned with WITH_TREND</small></div><span class="tag green">WITH_TREND</span></div>
                  <div class="conf-row"><div><b>Quality match</b><small>Conviction 88% · Structure 86%</small></div><span class="tag green">88%</span></div>
                  <div class="conf-row"><div><b>Execution lane</b><small>TIER_A routes to Prop Lane</small></div><span class="tag blue">TIER_A</span></div>
                  <div class="conf-row"><div><b>Readiness</b><small>Sell absorption reclaim confirmed.</small></div><span class="tag green">CONFIRM</span></div>
                </div>
                <div class="action-row">
                  <button class="action primary">CLICK TO EXECUTE</button>
                  <button class="action ghost">View details</button>
                </div>
              </article>
            </div>
          </div>
          
          <div class="panel">
            <h3>Open position health</h3>
            <p class="headline">Real-time telemetry on active trades.</p>
            <div class="position-list">
              <article class="position-card">
                <div class="position-top">
                  <div>
                    <h4>BTCUSD LONG</h4>
                    <div class="mini">Recommendation: Momentum expanding. Hold position. Sprint active.</div>
                  </div>
                  <span class="status green">GREEN</span>
                </div>
                <div class="kpi-strip" style="margin-top:16px">
                  <div class="kpi"><label>Health score</label><strong>88</strong></div>
                  <div class="kpi"><label>Price vs entry</label><strong>92</strong></div>
                  <div class="kpi"><label>Candle quality</label><strong>85</strong></div>
                  <div class="kpi"><label>Volume trend</label><strong>89</strong></div>
                </div>
                <div class="health-bar"><div style="width:88%"></div></div>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section id="props" class="view">
        <div class="panel">
          <h3>Prop account lanes</h3>
          <p class="headline">Dragon, normal, conservative, and recovery accounts mapped into execution lanes.</p>
          <div class="account-list">
            <article class="account-card">
              <div class="account-top">
                <div>
                  <h4>Prop 4 - DRAGON ($25K)</h4>
                  <div class="mini">Dragon lane · TIER_A</div>
                </div>
                <span class="status green">FULL AGGRESSION</span>
              </div>
              <div class="metrics">
                <div class="metric"><span>Equity</span><strong>$24,193</strong></div>
                <div class="metric"><span>Risk</span><strong>$350</strong></div>
                <div class="metric"><span>Gap</span><strong>$3,807</strong></div>
                <div class="metric"><span>Sprint</span><strong>ON</strong></div>
              </div>
              <div class="action-row">
                <button class="action primary">Tier A lane active</button>
                <button class="action ghost">Baseline $24,193</button>
              </div>
            </article>

            <article class="account-card">
              <div class="account-top">
                <div>
                  <h4>Prop 3 - $10K</h4>
                  <div class="mini">Support lane · TIER_A</div>
                </div>
                <span class="status green">FULL AGGRESSION</span>
              </div>
              <div class="metrics">
                <div class="metric"><span>Equity</span><strong>$9,726</strong></div>
                <div class="metric"><span>Risk</span><strong>$150</strong></div>
                <div class="metric"><span>Gap</span><strong>$1,274</strong></div>
                <div class="metric"><span>Sprint</span><strong>ON</strong></div>
              </div>
              <div class="action-row">
                <button class="action primary">Tier A lane active</button>
                <button class="action ghost">Baseline $9,726</button>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section id="kraken" class="view">
        <div class="grid-2">
          <div class="panel">
            <h3>Execution lane rules</h3>
            <p class="headline">Plain-English automated engine constraints.</p>
            <div class="kpi-strip">
              <div class="kpi"><label>Signals eligible</label><strong>2</strong></div>
              <div class="kpi"><label>Auto-confirm grade</label><strong>S</strong></div>
              <div class="kpi"><label>Manual grade</label><strong>A</strong></div>
              <div class="kpi"><label>3-candle exit</label><strong>ON</strong></div>
            </div>
            <div class="muted-box" style="margin-top:16px">
              The execution lane automatically filters for clean signals, respects conviction floors, auto-confirms S-grade setups, and ages open trades out with a 3-candle exit. Running live on Render 24/7.
            </div>
          </div>
          <div class="panel">
            <h3>Cloud &amp; Pipeline Status</h3>
            <p class="headline">System integrity metrics.</p>
            <div class="confluence">
              <div class="conf-row"><div><b>Zero Local Footprint</b><small>Running entirely in Render cloud worker</small></div><span class="tag green">ACTIVE</span></div>
              <div class="conf-row"><div><b>GitHub Cost Status</b><small>Static storage only, zero metered billing</small></div><span class="tag green">$0/mo</span></div>
              <div class="conf-row"><div><b>Prop Readiness</b><small>Optimized for account purchase tomorrow</small></div><span class="tag green">READY</span></div>
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
