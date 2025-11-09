# worker.py
import time
import os
import traceback

from db import create_schema, get_all_monitors, update_monitor_content
from utils import fetch_html, extract_with_selector, compute_hash, notify_placeholder

CHECK_INTERVAL_SECONDS = 0  # In Phase 1 we run once and exit. Set >0 to loop.

def process_once():
    monitors = get_all_monitors()
    if not monitors:
        print("No monitors found in DB. Add one manually (see README).")
        return

    for m in monitors:
        mid = m["id"]
        url = m["url"]
        selector = m["css_selector"]
        email = m["user_email"]
        last_content = m.get("last_content") or ""

        print(f"Checking monitor id={mid} url={url} selector={selector}")

        try:
            html = fetch_html(url)
            new_text = extract_with_selector(html, selector)
            if new_text is None:
                new_text = ""
            # Compare
            if last_content.strip() == "":
                # First run for this monitor: update stored content but don't notify.
                print(f"Monitor {mid}: first snapshot recorded (no alert).")
                update_monitor_content(mid, new_text)
            else:
                if compute_hash(new_text) != compute_hash(last_content):
                    print(f"Change detected for monitor id={mid}!")
                    # Phase 1: placeholder notification (print)
                    notify_placeholder(email, url, last_content, new_text)
                    # Update DB with new content
                    update_monitor_content(mid, new_text)
                else:
                    print(f"No change for monitor id={mid}.")
        except Exception as exc:
            print(f"Error while checking monitor id={mid} url={url}: {exc}")
            traceback.print_exc()

def main():
    print("=== Niche-Notify worker (Phase 1) ===")
    # ensure schema exists
    create_schema()
    # single run: fetch monitors and check once
    process_once()

    # if you want continuous loop locally, set CHECK_INTERVAL_SECONDS > 0
    if CHECK_INTERVAL_SECONDS > 0:
        print(f"Entering continuous loop, interval={CHECK_INTERVAL_SECONDS}s")
        try:
            while True:
                time.sleep(CHECK_INTERVAL_SECONDS)
                process_once()
        except KeyboardInterrupt:
            print("Worker interrupted by user. Exiting.")

if __name__ == "__main__":
    main()
