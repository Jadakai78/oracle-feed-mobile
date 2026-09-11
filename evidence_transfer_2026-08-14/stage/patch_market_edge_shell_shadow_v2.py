from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

path = Path("JHL-Market-Edge-Shell.html")
if not path.exists():
    raise SystemExit("Run this from the folder containing JHL-Market-Edge-Shell.html.")

text = path.read_text(encoding="utf-8")
if "shadow_volatile" in text or "SHD-VOL" in text:
    raise SystemExit("Shadow dashboard rendering already appears installed; no changes made.")

backup = path.with_name(f"{path.name}.{datetime.now():%Y%m%d_%H%M%S}.bak")
shutil.copy2(path, backup)

const_match = re.search(r"(const\s+DIAG_BOTS\s*=\s*\[[\s\S]*?\];)", text)
if not const_match:
    raise RuntimeError("Could not find DIAG_BOTS. Original HTML remains unchanged.")
text = text[:const_match.end()] + '''

const SHADOW_BOTS = [
  ["shadow_volatile", "SHD-VOL"],
  ["shadow_trend_recovery", "SHD-TRD"],
];
''' + text[const_match.end():]

function_match = re.search(r"\nfunction\s+pulseCard\s*\(", text)
if not function_match:
    raise RuntimeError("Could not find pulseCard. Original HTML remains unchanged.")
text = text[:function_match.start()] + r'''

function shadowCard(pair, key, label, sig) {
  if (!sig || !Object.keys(sig).length) return '';
  const side = String(sig.side || 'NONE').toUpperCase();
  const sideClass = side === 'LONG' ? 'long' : side === 'SHORT' ? 'short' : 'muted';
  const score = n(sig.score) ?? 0;
  const family = sig.setup_family || 'SHADOW_NO_SIGNAL';
  const state = sig.state || 'observe';
  const reasons = Array.isArray(sig.reasons) ? sig.reasons.join(' · ') : (sig.reasons || 'Observation only');
  return `<article class="bot" style="opacity:.78;border-color:#38435e;background:#101522">
    <div class="bot-head"><span class="bot-name muted">${esc(label)}</span><span class="tag muted">SHADOW · OBSERVE ONLY</span><span class="tag muted">${esc(state)}</span></div>
    <div class="top"><span class="direction ${sideClass}">${esc(side)}</span><span class="score">SCORE ${score.toFixed(2)}</span></div>
    <div class="plan">${esc(family)}</div>
    <div class="why">${esc(reasons)}</div>
  </article>`;
}
''' + text[function_match.start():]

render_pattern = re.compile(
    r"(const\s+diagCards\s*=\s*DIAG_BOTS\.map\([\s\S]*?\)\.join\(\s*['\"]{2}\s*\)\s*;)",
    re.MULTILINE,
)
render_match = render_pattern.search(text)
if not render_match:
    raise RuntimeError("Could not find the diagnostic-card render statement. Original HTML remains unchanged.")
shadow_cards = "\n    const shadowCards = SHADOW_BOTS.map(([key, label]) => shadowCard(row.pair, key, label, row[key])).join('');"
text = text[:render_match.end()] + shadow_cards + text[render_match.end():]

old_cards = "${execCards}${trainCards}${pulse}${diagCards}"
if old_cards not in text:
    raise RuntimeError("Could not find the specialist-card output. Original HTML remains unchanged.")
text = text.replace(old_cards, old_cards + "${shadowCards}", 1)

path.write_text(text, encoding="utf-8")
print(f"Patched {path.name}")
print(f"Backup created: {backup.name}")
print("Hard-refresh the dashboard page (Ctrl+F5).")
