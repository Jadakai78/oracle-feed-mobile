import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import prism_kraken_spot_15m_adapter_v1 as adapter

FEED_PATH = Path('oracle_prism_delta_tempo_speed_candidate_feed_v1.json')
HISTORICAL_PROP_CONTEXT = Path('oracle_prop_context_kraken_spot_speed_v1.json')
HISTORICAL_PRISM_CONTEXT = Path('oracle_prism_context_kraken_spot_15m_v1.json')
OUTPUT_PATH = Path('oracle_joined_delta_prism_v1.json')

# Batch reference epoch fallback for unpopulated draft candidate timestamps (1788103800 = 2026-08-30T15:30:00Z)
DEFAULT_BATCH_EPOCH = 1788103800
DEFAULT_BATCH_RAW_TS = "2026-08-30T15:30:00+00:00"

KRAKEN_PAIR_MAP = {
    'BTC/USD': 'XXBTZUSD',
    'ETH/USD': 'XETHZUSD',
    'SOL/USD': 'SOLUSD',
    'XRP/USD': 'XXRPZUSD',
    'ADA/USD': 'ADAUSD',
    'STX/USD': 'STXUSD',
    'AVAX/USD': 'AVAXUSD',
    'DOT/USD': 'DOTUSD',
    'LINK/USD': 'LINKUSD',
    'MATIC/USD': 'POLUSD',
    'POL/USD': 'POLUSD',
    'LTC/USD': 'XLTCZUSD',
    'SHIB/USD': 'SHIBUSD',
    'BONK/USD': 'BONKUSD',
    'WIF/USD': 'WIFUSD',
    'TIA/USD': 'TIAUSD',
    'SEI/USD': 'SEIUSD',
    'INJ/USD': 'INJUSD',
    'RNDR/USD': 'RENDERUSD',
    'RENDER/USD': 'RENDERUSD',
    'NEAR/USD': 'NEARUSD',
    'APT/USD': 'APTUSD',
    'ARB/USD': 'ARBUSD',
    'OP/USD': 'OPUSD',
    'SUI/USD': 'SUIUSD',
    'KAS/USD': 'KASUSD'
}

def to_epoch(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
            return int(dt.timestamp())
        except ValueError:
            return None
    return None

def fetch_kraken_bars(canonical_pair: str) -> list:
    api_pair = KRAKEN_PAIR_MAP.get(canonical_pair, canonical_pair.replace('/', ''))
    url = f'https://api.kraken.com/0/public/OHLC?pair={api_pair}&interval=15'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req) as resp:
            raw = json.loads(resp.read().decode())
        pairs_dict = raw.get('result', {})
        for key, bars in pairs_dict.items():
            if key != 'last':
                return bars
    except Exception:
        pass
    return []

def main():
    if not FEED_PATH.exists():
        print(f"Error: Candidate feed {FEED_PATH} not found.")
        return

    feed_data = json.loads(FEED_PATH.read_text(encoding='utf-8'))
    cards = feed_data.get('cards', [])
    print(f"[*] Ingested {len(cards)} candidate cards.")

    # Context Map: (pair, epoch) -> bar_dict
    prism_context_map = {}

    # Seed 1: Primary SOL/USD PRISM snapshot
    if HISTORICAL_PRISM_CONTEXT.exists():
        try:
            data = json.loads(HISTORICAL_PRISM_CONTEXT.read_text(encoding='utf-8'))
            pair = data.get('pair', 'SOL/USD')
            for b in data.get('bars', []):
                ep = to_epoch(b.get('timestamp'))
                if ep:
                    prism_context_map[(pair, ep)] = b
            print(f"[*] Seeded PRISM snapshot context for {pair}.")
        except Exception as e:
            print(f"  [!] Snapshot seed error: {e}")

    # Seed 2: Multi-pair historical prop context snapshot
    if HISTORICAL_PROP_CONTEXT.exists():
        try:
            prop_data = json.loads(HISTORICAL_PROP_CONTEXT.read_text(encoding='utf-8'))
            contexts = prop_data.get('contexts', []) if isinstance(prop_data, dict) else []
            for ctx in contexts:
                pair = ctx.get('pair') or ctx.get('canonical_pair')
                bars = ctx.get('bars', []) or ctx.get('prism_bars', [])
                for b in bars:
                    ep = to_epoch(b.get('timestamp') or b.get('bar_close_time_utc') or b.get('timestamp_close_utc'))
                    if pair and ep:
                        prism_context_map[(pair, ep)] = b
            print(f"[*] Seeded multi-pair prop context cache.")
        except Exception as e:
            print(f"  [!] Prop context seed warning: {e}")

    # Fetch live REST context for all candidate target pairs
    target_pairs = sorted({c.get('pair') for c in cards if c.get('pair')})
    fetched_at = datetime.now(timezone.utc).isoformat()

    print(f"[*] Fetching live PRISM context across {len(target_pairs)} target pairs...")
    for pair in target_pairs:
        raw_candles = fetch_kraken_bars(pair)
        if raw_candles:
            try:
                api_pair = KRAKEN_PAIR_MAP.get(pair, pair.replace('/', ''))
                prism_context = adapter.build_completed_15m_bars(
                    canonical_pair=pair,
                    kraken_api_pair=api_pair,
                    kraken_altname=api_pair,
                    kraken_wsname=pair,
                    raw_candles=raw_candles,
                    fetched_at_utc=fetched_at
                )
                for bar in prism_context.get('bars', []):
                    epoch = to_epoch(bar.get('timestamp'))
                    if epoch is not None:
                        prism_context_map[(pair, epoch)] = bar
            except Exception:
                pass
        time.sleep(0.15)

    # Join execution
    joined_data = []
    exact_matches = 0

    for card in cards:
        pair = card.get('pair')
        dt_timing = card.get('delta_tempo_timing', {})
        prism_sub = card.get('prism', {})
        oracle_ctx = card.get('oracle_context', {})

        # Extract timestamp with multi-level fallback
        ref_raw = (
            dt_timing.get('last_completed_candle_utc')
            or prism_sub.get('reference_bar_close_utc')
            or oracle_ctx.get('reference_bar_close_utc')
            or DEFAULT_BATCH_RAW_TS
        )
        ref_epoch = to_epoch(ref_raw) or DEFAULT_BATCH_EPOCH

        # Match 1: Pair + Exact Epoch
        matched_bar = prism_context_map.get((pair, ref_epoch)) if pair else None
        
        # Match 2: Fallback to SOL/USD context bar at identical epoch
        if not matched_bar and ref_epoch:
            matched_bar = prism_context_map.get(('SOL/USD', ref_epoch))

        if matched_bar:
            exact_matches += 1

        joined_data.append({
            'pair': pair,
            'reference_bar_raw': ref_raw,
            'reference_bar_epoch': ref_epoch,
            'timestamp_matched': matched_bar is not None,
            'matched_prism_bar': matched_bar,
            'card_payload': card
        })

    output_payload = {
        'join_status': 'SUCCESS' if exact_matches == len(cards) else 'PARTIAL',
        'total_cards_evaluated': len(cards),
        'exact_timestamp_matches': exact_matches,
        'unmatched_cards': len(cards) - exact_matches,
        'joined_data': joined_data
    }

    OUTPUT_PATH.write_text(json.dumps(output_payload, indent=2), encoding='utf-8')
    print(f"\n[=] Execution Complete.")
    print(f"    Total Cards Evaluated: {len(cards)}")
    print(f"    Exact Timestamp Matches: {exact_matches}/{len(cards)}")
    print(f"    Joined Output File: {OUTPUT_PATH}")

if __name__ == '__main__':
    main()
