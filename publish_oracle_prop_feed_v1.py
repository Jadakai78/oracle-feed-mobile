import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# CONFIGURATION & PATHS
# ---------------------------------------------------------------------------
SOURCE_FILE = r"C:\Users\jason\OneDrive\Desktop\jhl_v2\oracle-feed-mobile\oracle_joined_delta_prism_v1.json"
TARGET_REPO = r"C:\Users\jason\OneDrive\Desktop\jhl_v2\oracle-feed-mobile"

# Pushover API Credentials (Paste your keys or set environment variables)
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "u4v2rgci4vm95ezqx4czssz2t2du6a")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN", "a144kiwuifpzpjmbpjfei63dvyqfuu")

# Track notified pairs in memory during runtime to prevent spamming
NOTIFIED_EXECUTE_PAIRS = set()

# ---------------------------------------------------------------------------
# PUSHOVER NOTIFICATION ENGINE
# ---------------------------------------------------------------------------
def send_pushover_alert(pair, direction, entry, sl, tp, rr):
    """Fires high-priority mobile push notifications via Pushover REST API."""
    if PUSHOVER_USER_KEY.startswith("YOUR_") or PUSHOVER_API_TOKEN.startswith("YOUR_"):
        print(f"[!] Pushover Alert Skipped for {pair}: Keys not configured.")
        return

    title = f"🚨 EXECUTE NOW: {pair} ({direction})"
    message = (
        f"Entry: ${entry}\n"
        f"Stop Loss: ${sl}\n"
        f"Take Profit: ${tp}\n"
        f"R:R Ratio: {rr}\n"
        f"Timestamp: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )

    payload = urllib.parse.urlencode({
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "title": title,
        "message": message,
        "priority": 1,  # High priority (bypasses quiet hours)
        "sound": "persistent"
    }).encode("utf-8")

    try:
        req = urllib.request.Request("https://api.pushover.net/1/messages.json", data=payload)
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                print(f"[✓] PUSHOVER ALERT SENT: {pair} ({direction})")
    except Exception as e:
        print(f"[-] Failed to send Pushover alert for {pair}: {e}")

# ---------------------------------------------------------------------------
# TRADE LEVEL & TIER EVALUATION (RTS Liquidation & Anti-Delta Integrated)
# ---------------------------------------------------------------------------
def calculate_trade_levels(item):
    """Computes dynamic ATR-scaled Stop Loss, Take Profit, and Risk:Reward ratio."""
    card = item.get("card_payload") or {}
    prism_bar = item.get("matched_prism_bar") or {}
    dt = card.get("delta_tempo_timing") or {}
    
    raw_dir = dt.get("direction") if isinstance(dt, dict) else None
    direction = str(raw_dir).upper() if raw_dir else "NEUTRAL"
    
    close_price = float(prism_bar.get("close", 0) or 0)
    high_price = float(prism_bar.get("high", 0) or 0)
    low_price = float(prism_bar.get("low", 0) or 0)

    if close_price <= 0:
        return card

    bar_range = max(high_price - low_price, close_price * 0.005)

    # Dynamic scaling based on structure rather than a flat 2x multiple
    if direction == "SHORT":
        stop_loss = round(high_price + (bar_range * 0.35), 4)
        risk = stop_loss - close_price
        take_profit = round(close_price - (risk * 4.5), 4)
    elif direction == "LONG":
        stop_loss = round(low_price - (bar_range * 0.35), 4)
        risk = close_price - stop_loss
        take_profit = round(close_price + (risk * 4.5), 4)
    else:
        stop_loss = close_price
        take_profit = close_price

    card["stop_loss"] = stop_loss
    card["take_profit"] = take_profit
    card["calculated_rr"] = "1:4.5"
    
    return card

def evaluate_tier(item):
    """Extracts execution tier incorporating RTS liquidation safety and Anti-Delta checks."""
    card = item.get("card_payload") or {}
    dt = card.get("delta_tempo_timing") or {}
    speed_obj = dt.get("speed_phase") or {}
    
    # 1. Enforce RTS Liquidation Filter (Drop execution if flagged)
    rts_state = item.get("rts_state") or card.get("rts_state") or "NEUTRAL"
    if rts_state == "LIQUIDATION_WARNING":
        return "STAND_DOWN_RTS_RISK"

    phase = ""
    if isinstance(speed_obj, str):
        phase = speed_obj.upper()
    elif isinstance(speed_obj, dict):
        phase = str(speed_obj.get("phase") or speed_obj.get("speed_phase") or "").upper()
        
    matched = item.get("timestamp_matched", False)
    state = str(dt.get("state") or "").upper()

    # 2. Enforce Anti-Delta Absorption / Momentum rules
    absorption_flag = card.get("absorption_detected", False)
    delta_net = card.get("delta_net_state", "NEUTRAL")

    if matched and state != "GATED":
        if absorption_flag:
            if delta_net == "BUY" and phase in ["DECAY", "FLAT"]:
                return "EXECUTE"
            elif delta_net == "SELL" and card.get("reclaim_confirmed", False):
                return "EXECUTE"
        elif phase in ["ACCELERATING", "IMPULSE", "EXPANDING", "REACCELERATION"]:
            return "EXECUTE"

    return "OTHER"

# ---------------------------------------------------------------------------
# PIPELINE EXECUTION
# ---------------------------------------------------------------------------
def process_and_enrich_feed():
    if not os.path.exists(SOURCE_FILE):
        print(f"[-] Source file not found: {SOURCE_FILE}")
        return False

    with open(SOURCE_FILE, "r") as f:
        data = json.load(f)

    joined_data = data.get("joined_data", [])
    current_execute_pairs = set()
    
    for item in joined_data:
        item["card_payload"] = calculate_trade_levels(item)
        pair = item.get("pair", "UNKNOWN")
        tier = evaluate_tier(item)
        
        # Inject evaluation results back into the item for client rendering
        item["evaluation_tier"] = tier

        if tier == "EXECUTE":
            current_execute_pairs.add(pair)
            if pair not in NOTIFIED_EXECUTE_PAIRS:
                card = item.get("card_payload", {})
                prism_bar = item.get("matched_prism_bar", {})
                dt = card.get("delta_tempo_timing", {})
                
                send_pushover_alert(
                    pair=pair,
                    direction=dt.get("direction", "LONG"),
                    entry=prism_bar.get("close", 0),
                    sl=card.get("stop_loss", 0),
                    tp=card.get("take_profit", 0),
                    rr=card.get("calculated_rr", "1:4.5")
                )
                NOTIFIED_EXECUTE_PAIRS.add(pair)

    # Clean up stale pairs no longer in EXECUTE state
    for pair in list(NOTIFIED_EXECUTE_PAIRS):
        if pair not in current_execute_pairs:
            NOTIFIED_EXECUTE_PAIRS.remove(pair)

    # Refresh root timestamps to clear stale feed flags
    data["generated_at_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    data["context_generated_at_utc"] = data["generated_at_utc"]

    with open(SOURCE_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"[+] Enriched {len(joined_data)} candidate cards with RTS & Anti-Delta logic.")
    return True

def run_git_sync():
    print("[+] Syncing enriched feed to remote GitHub repository...")
    os.chdir(TARGET_REPO)
    
    try:
        subprocess.run(["git", "add", "."], check=True)
        commit_res = subprocess.run(["git", "commit", "-m", "Auto-update feed with RTS and Anti-Delta filters enabled"], capture_output=True, text=True)
        push_res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
        if push_res.returncode == 0:
            print("[✓] PUBLISH COMPLETE: Enriched feed live on GitHub Pages.")
    except Exception as e:
        print(f"[-] Git Sync Error: {e}")

if __name__ == "__main__":
    if process_and_enrich_feed():
        run_git_sync()
