from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json
import shutil

root = Path.cwd()
out = root / "evidence_transfer_2026-08-14"
stage = out / "stage"
out.mkdir(exist_ok=True)
stage.mkdir(exist_ok=True)

wanted = {
    "gimba_drive.jsonl",
    "ltf_shadow_5m.jsonl",
    "ltf_shadow_5m_v2.jsonl",
    "shadow_trend_recovery.jsonl",
    "delta_tempo_shadow_recorder_spec_addendum.md",
    "knn_engine.py",
    "gimba_volume_flow.py",
    "market_timing.py",
    "market_state_engine.py",
    "outcome_evaluator.py",
    "scanner.py",
    "scanner-2.py",
    "read.py",
    "market_reader-4.py",
}

keywords = (
    "delta", "tempo", "shadow", "knn", "outcome",
    "candle", "ohlcv", "price_history", "volume_flow",
    "market_state", "timing"
)

extensions = {
    ".jsonl", ".csv", ".json", ".py", ".md", ".txt",
    ".parquet", ".feather"
}

skip_dirs = {
    ".git", "pycache", ".venv", "venv",
    "node_modules", "evidence_transfer_2026-08-14"
}

files = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    if any(part in skip_dirs for part in path.parts):
        continue
    name = path.name.lower()
    if (
        name in wanted
        or (
            path.suffix.lower() in extensions
            and any(word in name for word in keywords)
        )
    ):
        files.append(path)

manifest = []
for source in sorted(set(files)):
    relative = source.relative_to(root)
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    manifest.append({
        "path": str(relative),
        "size_bytes": source.stat().st_size
    })

manifest_path = out / "manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

zip_path = out / "delta_anti_delta_knn_evidence_bundle.zip"
with ZipFile(zip_path, "w", ZIP_DEFLATED) as z:
    for path in stage.rglob("*"):
        if path.is_file():
            z.write(path, path.relative_to(stage))
    z.write(manifest_path, "manifest.json")

report = [
    "DELTA / ANTI-DELTA / KNN EVIDENCE TRANSFER",
    f"Project root: {root}",
    f"Included files: {len(manifest)}",
    f"Bundle size: {zip_path.stat().st_size / (1024 * 1024):.2f} MB",
    "",
    "INCLUDED:"
]
report.extend(
    f"{x['size_bytes'] / 1024:.1f} KB  {x['path']}"
    for x in manifest
)

report_path = out / "inventory_report.txt"
report_path.write_text("\n".join(report), encoding="utf-8")

print("DONE")
print(f"Bundle for Telegram: {zip_path}")
print(f"Inventory report: {report_path}")
print(f"Included files: {len(manifest)}")
print(f"Bundle size: {zip_path.stat().st_size / (1024 * 1024):.2f} MB")
