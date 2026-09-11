import os
import subprocess
import sys
from pathlib import Path

current_dir = Path.cwd()
output_file = current_dir / "smoke_oracle_prism_bar_snapshot.json"

print(f"Working Directory: {current_dir}")
print(f"Target Output Path: {output_file}")

script_name = "produce_kraken_snapshot.py" 

if not (current_dir / script_name).exists():
    print(f"ERROR: Could not find '{script_name}' in {current_dir}")
    sys.exit(1)

cmd = [sys.executable, script_name, "--pair", "SOL/USD", "--output", str(output_file)]

print(f"\nRunning command: {' '.join(cmd)}\n" + "-" * 50)
result = subprocess.run(cmd, capture_output=True, text=True)

print(f"Exit Code: {result.returncode}")
if result.stdout:
    print(f"STDOUT:\n{result.stdout}")
if result.stderr:
    print(f"STDERR:\n{result.stderr}")

if output_file.exists():
    print(f"\nSUCCESS: Snapshot created at {output_file} ({output_file.stat().st_size} bytes)")
else:
    print("\nFAILURE: Exit code captured, but no output JSON was created on disk.")
