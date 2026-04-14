#!/usr/bin/env python3
"""Monitor run progress and notify when complete or failed."""

import subprocess
import time
import sys
from pathlib import Path
from datetime import datetime

def check_process_running():
    """Check if run_complete_analysis.py is still running."""
    result = subprocess.run(
        ["pgrep", "-f", "run_complete_analysis.py"],
        capture_output=True,
        text=True
    )
    return bool(result.stdout.strip())

def check_file_updated(filepath, threshold_minutes=2):
    """Check if file was recently modified."""
    if not Path(filepath).exists():
        return False, None
    
    mtime = Path(filepath).stat().st_mtime
    age_minutes = (time.time() - mtime) / 60
    return age_minutes < threshold_minutes, age_minutes

def format_duration(seconds):
    """Format seconds to mm:ss."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}m {secs}s"

def main():
    """Monitor run and notify completion."""
    start_time = time.time()
    gua_file = "/home/ubuntu/sib-work/web/data/guadeloupe-complete-analysis.json"
    mar_file = "/home/ubuntu/sib-work/web/data/martinique-complete-analysis.json"
    
    print("=" * 70)
    print("SIB Complete Analysis Run Monitor")
    print("=" * 70)
    print(f"Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"Monitoring: {gua_file}")
    print(f"           {mar_file}")
    print()
    print("Status updates:")
    
    last_gua_time = None
    last_mar_time = None
    gua_completed = False
    mar_completed = False
    
    while True:
        elapsed = time.time() - start_time
        running = check_process_running()
        
        gua_updated, gua_age = check_file_updated(gua_file)
        mar_updated, mar_age = check_file_updated(mar_file)
        
        if gua_updated and not gua_completed:
            print(f"[{format_duration(elapsed)}] ✓ Guadeloupe completed!")
            gua_completed = True
            last_gua_time = time.time()
        
        if mar_updated and not mar_completed:
            print(f"[{format_duration(elapsed)}] ✓ Martinique completed!")
            mar_completed = True
            last_mar_time = time.time()
        
        if not running and not gua_completed:
            print(f"[{format_duration(elapsed)}] ✗ ERROR: Process died before completing Guadeloupe")
            return 1
        
        if not running and gua_completed and not mar_completed:
            print(f"[{format_duration(elapsed)}] ✗ ERROR: Process died during Martinique")
            return 1
        
        if gua_completed and mar_completed:
            print(f"[{format_duration(elapsed)}] ✓✓ ALL TASKS COMPLETED!")
            print("=" * 70)
            return 0
        
        # Check for timeout (> 40 minutes)
        if elapsed > 2400:  # 40 minutes
            print(f"[{format_duration(elapsed)}] ✗ TIMEOUT: Run exceeded 40 minutes")
            return 1
        
        time.sleep(5)

if __name__ == "__main__":
    sys.exit(main())
