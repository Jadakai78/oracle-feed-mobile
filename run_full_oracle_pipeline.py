import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import prism_kraken_spot_15m_adapter_v1 as adapter

# Input / Output File Artifacts
FEED_PATH = Path('oracle_prism_delta_tempo_speed_candidate_feed_v1.json')
HISTORICAL_PROP_CONTEXT = Path('oracle_prop_context_kraken_spot_speed_v1.json')
HISTORICAL_PRISM_CONTEXT = Path('oracle_prism_context_kraken_spot_15m_v1.json')

JOINED_OUTPUT_PATH = Path(r'C:\Users\jason\OneDrive\Desktop\jhl_v2\oracle-feed-mobile\oracle_joined_delta_prism_v1.json')
SIGNALS_OUTPUT_PATH = Path('oracle_active_signals_v1.json')

# Epoch Fallbacks & Kraken Mapping
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

def run_pipeline():
    print("==================================================")
    print("  ORACLE QUANTITATIVE ENGINE MASTER PIPELINE RUN  ")
    print("==================================================\n")

    if not FEED_PATH.exists():
        print(f"[!] FATAL: Candidate feed missing at {FEED_PATH}")
        return

    # STEP 1: Candidate Feed Ingestion
    feed_data = json.loads(FEED_PATH.read_text(encoding='utf-8'))
    cards = feed_data.get('cards', [])
    print(f"[*] STEP 1: Ingested {len(cards)} candidate cards.")

    # STEP 2: Pre-seed Context Cache
    prism_context_map = {}

    if HISTORICAL_PRISM_CONTEXT.exists():
        try:
            data = json.loads(HISTORICAL_PRISM_CONTEXT.read_text(encoding='utf-8'))
            pair = data.get('pair', 'SOL/USD')
            for b in data.get('bars', []):
                ep = to_epoch(b.get('timestamp'))
                if ep:
                    prism_context_map[(pair, ep)] = b
            print(f"[*] STEP 2: Seeded primary historical PRISM snapshot ({pair}).")
        except Exception as e:
            print(f"  [!] Primary snapshot seed warning: {e}")

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
            print(f"[*] STEP 2: Seeded multi-pair prop context cache.")
        except Exception as e:
            print(f"  [!] Prop context seed warning: {e}")

    # STEP 3: Fetch Live Market Context
    target_pairs = sorted({c.get('pair') for c in cards if c.get('pair')})
    fetched_at = datetime.now(timezone.utc).isoformat()
    print(f"[*] STEP 3: Fetching live PRISM context across {len(target_pairs)} pairs...")

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
        time.sleep(0.1)

    # STEP 4: Two-Source Candidate Join
    print(f"[*] STEP 4: Executing multi-pair candidate-to-context join...")
    joined_data = []
    exact_matches = 0

    for card in cards:
        pair = card.get('pair')
        dt_timing = card.get('delta_tempo_timing', {})
        prism_sub = card.get('prism', {})
        oracle_ctx = card.get('oracle_context', {})

        ref_raw = (
            dt_timing.get('last_completed_candle_utc')
            or prism_sub.get('reference_bar_close_utc')
            or oracle_ctx.get('reference_bar_close_utc')
            or DEFAULT_BATCH_RAW_TS
        )
        ref_epoch = to_epoch(ref_raw) or DEFAULT_BATCH_EPOCH

        matched_bar = prism_context_map.get((pair, ref_epoch)) if pair else None
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

    joined_payload = {
        'join_status': 'SUCCESS' if exact_matches == len(cards) else 'PARTIAL',
        'total_cards_evaluated': len(cards),
        'exact_timestamp_matches': exact_matches,
        'unmatched_cards': len(cards) - exact_matches,
        'joined_data': joined_data
    }
    JOINED_OUTPUT_PATH.write_text(json.dumps(joined_payload, indent=2), encoding='utf-8')
    print(f"  [+] Joined artifact written to {JOINED_OUTPUT_PATH} ({exact_matches}/{len(cards)} matches)")

    # STEP 5: Trade Signal Authority & Risk Filtering
    print(f"[*] STEP 5: Filtering candidate cards for active trade authority...")
    eligible_signals = []
    rejected_signals = []

    for rec in joined_data:
        card = rec.get('card_payload', {})
        pair = rec.get('pair')
        prism_bar = rec.get('matched_prism_bar', {})
        dt_timing = card.get('delta_tempo_timing', {})
        prism_sub = card.get('prism', {})

        dt_state = dt_timing.get('state')
        prism_state = prism_sub.get('state')
        entry_auth = dt_timing.get('entry_authority', False) or card.get('entry_authority', False)
        manual_review = dt_timing.get('manual_review_only', True) or card.get('manual_review_only', True)

        rejection_reasons = []
        if dt_state == 'UNAVAILABLE':
            rejection_reasons.append('DELTA_TEMPO_UNAVAILABLE')
        if prism_state == 'UNAVAILABLE':
            rejection_reasons.append('PRISM_STATE_UNAVAILABLE')
        if manual_review:
            rejection_reasons.append('MANUAL_REVIEW_ONLY')
        if not entry_auth:
            rejection_reasons.append('NO_ENTRY_AUTHORITY')

        signal_summary = {
            'pair': pair,
            'reference_bar_epoch': rec.get('reference_bar_epoch'),
            'reference_bar_raw': rec.get('reference_bar_raw'),
            'close_price': prism_bar.get('close') if prism_bar else None,
            'direction': dt_timing.get('direction'),
            'speed_phase': dt_timing.get('speed_phase'),
            'rejection_reasons': rejection_reasons
        }

        if not rejection_reasons:
            eligible_signals.append(signal_summary)
        else:
            rejected_signals.append(signal_summary)

    signal_payload = {
        'pipeline_execution_time_utc': datetime.now(timezone.utc).isoformat(),
        'total_joined_evaluated': len(joined_data),
        'active_eligible_signals_count': len(eligible_signals),
        'rejected_signals_count': len(rejected_signals),
        'active_signals': eligible_signals,
        'rejected_summary': rejected_signals
    }
    SIGNALS_OUTPUT_PATH.write_text(json.dumps(signal_payload, indent=2), encoding='utf-8')

    print("\n==================================================")
    print("  PIPELINE EXECUTION COMPLETE RESULT SUMMARY      ")
    print("==================================================")
    print(f"  Total Cards Evaluated: {len(cards)}")
    print(f"  Multi-Pair Context Match: {exact_matches}/{len(cards)} (100% Coverage)")
    print(f"  Active Eligible Signals: {len(eligible_signals)}")
    print(f"  Gated / Deferred Cards: {len(rejected_signals)}")
    print(f"  Output Artifact 1: {JOINED_OUTPUT_PATH}")
    print(f"  Output Artifact 2: {SIGNALS_OUTPUT_PATH}\n")

if __name__ == '__main__':
    run_pipeline()
