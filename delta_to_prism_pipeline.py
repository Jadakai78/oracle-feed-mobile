"""
Pipeline Entrypoint
Wires the high-speed Delta Engine directly to the local PRISM publisher script.
"""
import time
from delta_engine import SpeedDeltaEngine
from publish_oracle_prop_feed_v1 import main as publish_feed

def main():
    # Instantiate engine with 8 workers tied directly to your publisher
    engine = SpeedDeltaEngine(publisher_func=publish_feed, max_workers=8)
    
    print("[+] Delta to PRISM high-speed engine active. Waiting for ticks...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[-] Shutting down engine...")
        engine.shutdown()

if __name__ == "__main__":
    main()
