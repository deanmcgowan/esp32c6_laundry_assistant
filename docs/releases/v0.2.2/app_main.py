import sys
import time
import json
import ntptime

import updater
from status_led import StatusLED

# Ensure /app/lib is importable
if "/app/lib" not in sys.path:
    sys.path.insert(0, "/app/lib")

from ngenic.ngenic_client import NgenicClient  # <-- changed


SYNC_INTERVAL_MS = 60 * 60 * 1000  # 1 hour


def load_secrets():
    with open("/secrets.json", "r") as f:
        return json.load(f)


def sync_time():
    sec = load_secrets()
    updater.connect_wifi(sec["wifi_ssid"], sec["wifi_password"], timeout_s=20)
    ntptime.settime()  # sets UTC


def main():
    led = StatusLED(pin=8)
    led.solid((0, 10, 0))  # green = app running

    # Time sync (non-fatal)
    try:
        sync_time()
    except Exception as e:
        print("NTP sync failed:", repr(e))

    updater.mark_boot_success()

    ng = NgenicClient()
    last_sync_ms = time.ticks_ms()

    while True:
        # hourly time re-sync
        if time.ticks_diff(time.ticks_ms(), last_sync_ms) >= SYNC_INTERVAL_MS:
            try:
                sync_time()
                last_sync_ms = time.ticks_ms()
                print("Time re-synchronised (NTP).")
            except Exception as e:
                print("Hourly NTP sync failed:", repr(e))

        st = ng.refresh_if_due()
        print(
            "ngenic import_kW=", st.get("import_kW"),
            " export_kW=", st.get("export_kW"),
            " net_kW=", st.get("net_kW"),
            " age_s=", st.get("age_s"),
            " learned_interval_s=", st.get("learned_interval_s"),
        )
        time.sleep(1)


main()