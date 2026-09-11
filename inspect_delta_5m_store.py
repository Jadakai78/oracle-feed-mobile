from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba\finance_5m")
files = sorted(ROOT.glob("*_price_history_external_*_5m*.csv"))

print(f"FILES: {len(files)}")

for path in files:
    try:
        df = pd.read_csv(path, nrows=5)
    except Exception as exc:
        print(f"\n{path.name}\nERROR: {exc}")
        continue

    print(f"\n{path.name}")
    print(f"COLUMNS: {list(df.columns)}")
    print(df.to_string(index=False))