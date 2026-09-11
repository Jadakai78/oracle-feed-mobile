from pathlib import Path
import pandas as pd

PATH = Path(
    r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba"
    r"\corrected_delta_response_ledger.csv"
)

df = pd.read_csv(PATH)

for col in ["mfe_pct", "mae_pct", "horizon_bars"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df = df.dropna(subset=["pair", "delta_direction", "horizon_bars", "mfe_pct", "mae_pct"])

# A positive MFE means the price moved in the candidate's stated direction.
df["favorable"] = df["mfe_pct"] > 0
df["failed"] = df["response_label"].astype(str).str.upper().eq("FAILED")
df["net_proxy_pct"] = df["mfe_pct"] + df["mae_pct"]

def score(group_name, x):
    n = len(x)
    favorable = 100 * x["favorable"].mean() if n else 0
    failed = 100 * x["failed"].mean() if n else 0
    print(
        f"{group_name:48} "
        f"N={n:5} "
        f"Fav={favorable:6.2f}% "
        f"Failed={failed:6.2f}% "
        f"MeanMFE={x['mfe_pct'].mean():8.4f}% "
        f"MedMFE={x['mfe_pct'].median():8.4f}% "
        f"MeanMAE={x['mae_pct'].mean():8.4f}% "
        f"MedMAE={x['mae_pct'].median():8.4f}%"
    )

print("\nDELTA RESPONSE SCORECARD")
print("-" * 165)

for horizon, x in df.groupby("horizon_bars"):
    score(f"ALL | {int(horizon)} bars", x)

print("\nBY DIRECTION AND HORIZON")
for (direction, horizon), x in df.groupby(["delta_direction", "horizon_bars"]):
    score(f"{direction} | {int(horizon)} bars", x)

print("\nBY PAIR, DIRECTION, AND 12-BAR HORIZON")
x12 = df[df["horizon_bars"] == 12]
for (pair, direction), x in x12.groupby(["pair", "delta_direction"]):
    score(f"{pair} | {direction} | 12 bars", x)