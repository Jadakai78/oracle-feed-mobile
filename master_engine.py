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

app = FastAPI(title="Oracle Apex Live Engine")

# Global state to hold the latest feed payload for the web dashboard
latest_feed_state = {
    "status": "INITIALIZING",
    "last_updated": None,
    "active_signals_count": 0,
    "signals": []
}

def run_master_orchestration():
    global latest_feed_state
    logging.info("Master Engine (Unified December/April Mode) initialized successfully with 24/7 continuous cloud loop.")
    
    feed_generator = OracleFeedV2(account_balance=10000.0)
    
    while True:
        try:
            raw_candidates = [
                {"pair": "BTCUSD", "setup_family": "momentum_expansion_continuation_v1", "stop_distance_pct": 0.008},
                {"pair": "SOLUSD", "setup_family": "sell_absorption_reclaim_v1", "stop_distance_pct": 0.015},
                {"pair": "ADA/USD", "setup_family": "reacceleration_reclaim_continuation_v1", "stop_distance_pct": 0.012}
            ]
            
            feed_payload = feed_generator.generate_feed(raw_candidates)
            latest_feed_state = feed_payload
            latest_feed_state["status"] = "LIVE_AND_ARMED"
            
            logging.info(f"Feed Scan Complete. Active Signals: {feed_payload['active_signals_count']} | Timestamp: {feed_payload['generated_at_utc']}")
            
        except Exception as e:
            logging.error(f"Error during orchestration loop execution: {e}")
            
        time.sleep(10)

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    signals_html = ""
    for sig in latest_feed_state.get("signals", []):
        signals_html += f"""
        <div class="signal-card">
            <div class="meta">Asset: {sig['pair']} | Setup: {sig['setup_family']} ({sig['parameters']['sl_tp_multiplier']}x)</div>
            <pre>{json.dumps(sig, indent=2)}</pre>
        </div>
        """
    
    if not signals_html:
        signals_html = "<p>Scanning market candidates...</p>"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Oracle Apex Live Feed v2</title>
        <style>
            body {{ font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }}
            .container {{ max-width: 800px; margin: auto; background: #161b22; padding: 20px; border-radius: 8px; border: 1px solid #30363d; }}
            h1 {{ color: #58a6ff; font-size: 20px; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
            .signal-card {{ background: #21262d; border-left: 4px solid #238636; padding: 15px; margin-top: 15px; border-radius: 4px; }}
            .meta {{ color: #8b949e; font-size: 12px; margin-bottom: 8px; }}
            pre {{ background: #0d1117; padding: 10px; border-radius: 4px; overflow-x: auto; color: #7ee787; }}
            .status-badge {{ background: #238636; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; }}
        </style>
        <meta http-equiv="refresh" content="5">
    </head>
    <body>
        <div class="container">
            <h1>⚡ Oracle Apex Live Feed v2 (Unified December/April)</h1>
            <div class="meta">Status: <span class="status-badge">{latest_feed_state.get('status')}</span> | Last Updated: {latest_feed_state.get('generated_at_utc', 'N/A')} | Auto-refreshing every 5s</div>
            <div id="feed-content">
                {signals_html}
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    # Start the trading engine loop in a background daemon thread
    engine_thread = threading.Thread(target=run_master_orchestration, daemon=True)
    engine_thread.start()
    
    # Start FastAPI web server on Render's required port setup (defaulting to 10000)
    import os
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
