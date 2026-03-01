import time
import json

import ntptime

import updater
from status_led import StatusLED


SYNC_INTERVAL_MS = 60 * 60 * 1000  # 1 hour


def load_secrets():
    with open("/secrets.json", "r") as f:
        return json.load(f)


def sync_time():
    # Ensure Wi‑Fi is up (uses same creds as OTA)
    sec = load_secrets()
    updater.connect_wifi(sec["wifi_ssid"], sec["wifi_password"], timeout_s=20)

    # Sets RTC to UTC (epoch time). If you want local time, apply an offset when displaying.
    ntptime.settime()


def main():
    led = StatusLED(pin=8)

    # We’re now “in the application”: show solid green.
    led.solid((0, 10, 0))

    # Do NTP sync on start (don’t crash the app if NTP fails).
    try:
        sync_time()
    except Exception as e:
        print("NTP sync failed:", repr(e))

    # Mark boot successful after startup completes.
    updater.mark_boot_success()

    last_sync_ms = time.ticks_ms()

    while True:
        # Re-sync once per hour
        if time.ticks_diff(time.ticks_ms(), last_sync_ms) >= SYNC_INTERVAL_MS:
            try:
                sync_time()
                last_sync_ms = time.ticks_ms()
                print("Time re-synchronised (NTP).")
            except Exception as e:
                print("Hourly NTP sync failed:", repr(e))

        # Your normal application work goes here
        print("tick", time.time())
        time.sleep(5)


main()