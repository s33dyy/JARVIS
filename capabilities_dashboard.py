import json
import os
from pathlib import Path

def print_dashboard():
    # Load memory
    mem_path = Path(os.path.expanduser("~/.jarvis/memory.json"))
    if not mem_path.exists():
        print("No JARVIS memory found.")
        return

    try:
        with open(mem_path, "r", encoding="utf-8") as f:
            mem = json.load(f)
    except Exception as e:
        print(f"Error loading memory: {e}")
        return

    caps = mem.get("capabilities", {})
    bugs = mem.get("bug_log", {})

    print("="*60)
    print(" JARVIS CAPABILITIES DASHBOARD ".center(60, "="))
    print("="*60)
    
    if not caps:
        print("\n  No active capabilities registered yet.\n")
    else:
        print("\n--- ACTIVE CAPABILITIES ---")
        for cid, cap in caps.items():
            status = cap.get("status", "Unknown")
            marker = "🟢" if status.lower() == "active" else "🟡"
            print(f"{marker} {cid}: {cap.get('name')} [{status.upper()}]")
            print(f"    Trigger : {cap.get('trigger')}")
            print(f"    Behavior: {cap.get('behavior')[:60]}...")
            print(f"    Risk    : {cap.get('risk_level')}")
            print("-" * 40)

    print("\n--- BUG LOG (MONITORING) ---")
    open_bugs = {bid: b for bid, b in bugs.items() if b.get("status") != "PATCHED"}
    if not open_bugs:
        print("  🟢 No open bugs. System nominal.")
    else:
        for bid, b in open_bugs.items():
            sev = b.get("severity", "LOW")
            marker = "🔴" if sev in ("HIGH", "CRITICAL") else "🟡"
            print(f"{marker} {bid} [{sev}]: {b.get('type')}")
            print(f"    Failed: {b.get('what_failed')}")
            print("-" * 40)

    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    print_dashboard()
