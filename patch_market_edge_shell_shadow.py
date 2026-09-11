from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

path = Path("JHL-Market-Edge-Shell.html")
if not path.exists():
    raise SystemExit("Run this script from the folder containing JHL-Market-Edge-Shell.html.")

text = path.read_text(encoding="utf-8")
if "shadow_volatile" in text or "SHD-VOL" in text:
    raise SystemExit("Shadow dashboard rendering already appears to be installed; no changes made.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = path.with_name(f"{path.name}.{stamp}.bak")
shutil.copy2(path, backup)

shadow_const = '''

const SHADOW_BOTS = [
  ["shadow_volatile", "SHD-VOL"],
  ["shadow_trend_recovery", "SHD-TRD"],
];
'''

match = re.search(r"(const\s+DIAG_BOTS\s*=\s*\[[\s\S]*?\];)", text)
if not match:
    raise RuntimeError("Could not find DIAG_BOTS. Restoring backup; no patch applied.")
text = text[:match.end()] + shadow_const + text[match.end():]

shadow_function = r'''

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
'''

match = re.search(r"\nfunction\s+pulseCard\s*\(", text)
if not match:
    raise RuntimeError("Could not find pulseCard. Restoring backup; no patch applied.")
text = text[:match.start()] + shadow_function + text[match.start():]

needle = "const diagCards = DIAG_BOTS.map(([key, label]) => diagCard(row.pair, key, label, row[key])).join('');"
replacement = needle + "\n    const shadowCards = SHADOW_BOTS.map(([key, label]) => shadowCard(row.pair, key, label, row[key])).join('');"
if needle not in text:
    raise RuntimeError("Could not find the specialist rendering block. Restoring backup; no patch applied.")
text = text.replace(needle, replacement, 1)

needle = "return `<div class=\"row\"><div class=\"top\"><span class=\"pair\">${esc(row.pair)}</span><span class=\"muted\">SPECIALIST READS</span></div>${execCards}${trainCards}${pulse}${diagCards}</div>`;"
replacement = "return `<div class=\"row\"><div class=\"top\"><span class=\"pair\">${esc(row.pair)}</span><span class=\"muted\">SPECIALIST READS</span></div>${execCards}${trainCards}${pulse}${diagCards}${shadowCards}</div>`;"
if needle not in text:
    raise RuntimeError("Could not find the specialist card return line. Restoring backup; no patch applied.")
text = text.replace(needle, replacement, 1)

path.write_text(text, encoding="utf-8")
print(f"Patched {path.name}")
print(f"Backup created: {backup.name}")
print("Refresh the browser page; SHD-VOL and SHD-TRD will appear under SPECIALIST READS.")
