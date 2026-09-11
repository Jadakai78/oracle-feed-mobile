import json
from pathlib import Path

JOINED_PATH = Path('oracle_joined_delta_prism_v1.json')
OUTPUT_SIGNALS_PATH = Path('oracle_active_signals_v1.json')

def main():
    if not JOINED_PATH.exists():
        print(f"Error: {JOINED_PATH} not found.")
        return

    data = json.loads(JOINED_PATH.read_text(encoding='utf-8'))
    joined_records = data.get('joined_data', [])

    eligible_signals = []
    rejected_signals = []

    for rec in joined_records:
        card = rec.get('card_payload', {})
        pair = rec.get('pair')
        prism_bar = rec.get('matched_prism_bar', {})

        dt_timing = card.get('delta_tempo_timing', {})
        prism_sub = card.get('prism', {})

        # Extract flags
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
        'total_joined_evaluated': len(joined_records),
        'active_eligible_signals_count': len(eligible_signals),
        'rejected_signals_count': len(rejected_signals),
        'active_signals': eligible_signals,
        'rejected_summary': rejected_signals
    }

    OUTPUT_SIGNALS_PATH.write_text(json.dumps(signal_payload, indent=2), encoding='utf-8')

    print(f"=== SIGNAL GENERATION COMPLETE ===")
    print(f"Total Evaluated: {len(joined_records)}")
    print(f"Active Eligible Signals: {len(eligible_signals)}")
    print(f"Rejected / Deferred Cards: {len(rejected_signals)}")
    print(f"Signal artifact saved to: {OUTPUT_SIGNALS_PATH}")

if __name__ == '__main__':
    main()
