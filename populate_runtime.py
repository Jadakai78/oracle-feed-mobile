from pathlib import Path
import shutil

legacy_fixtures = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba\fixtures")
runtime_dir = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\oracle-feed-mobile\runtime")
runtime_dir.mkdir(parents=True, exist_ok=True)

# Map legacy fixtures to mobile runtime artifact names
artifacts = {
    "oracle_available.json": "prism_kraken_spot_15m_latest.json",
    "delta_v2_available.json": "delta_tempo_envelope_latest.json",
}

for src_name, dst_name in artifacts.items():
    src_path = legacy_fixtures / src_name
    if src_path.exists():
        shutil.copy(src_path, runtime_dir / dst_name)
        print(f"[✓] Copied {src_name} -> {dst_name}")

print("[+] Runtime folder populated. Ready for local fetch cycle.")
