import sys
import time
import json
import ntptime

import updater
from status_led import StatusLED

# Ensure /app/lib is importable
if "/app/lib" not in sys.path:
    sys.path.insert(0, "/app/lib")

from web.server import WebServer  # noqa: E402
from ngenic.ngenic_client import NgenicClient  # noqa: E402
from spotprice.elprisetjustnu import SpotPriceClient  # noqa: E402


SYNC_INTERVAL_MS = 60 * 60 * 1000  # 1 hour


def load_secrets():
    with open("/secrets.json", "r") as f:
        return json.load(f)


def wifi_up():
    sec = load_secrets()
    wlan = updater.connect_wifi(sec["wifi_ssid"], sec["wifi_password"], timeout_s=20)
    return wlan.ifconfig()[0]


def sync_time():
    wifi_up()
    ntptime.settime()  # sets UTC


def main():
    led = StatusLED(pin=8)
    led.solid((0, 10, 0))  # green = app running

    ip = None
    try:
        ip = wifi_up()
        print("Web UI: http://%s/" % ip)
    except Exception as e:
        print("Wi‑Fi failed:", repr(e))

    try:
        sync_time()
    except Exception as e:
        print("NTP sync failed:", repr(e))

    updater.mark_boot_success()

    ng = NgenicClient()
    prices = SpotPriceClient(area="SE3")
    prices.load_cache()
    prices.refresh_if_due()  # try once at boot

    srv = WebServer(port=80)
    last_sync_ms = time.ticks_ms()

    def get_status():
        st = ng.get_cached()
        return {
            "device_epoch_utc": time.time(),
            "ip": ip,
            "ngenic": {
                "import_kW": st.get("import_kW"),
                "export_kW": st.get("export_kW"),
                "net_kW": st.get("net_kW"),
                "age_s": st.get("age_s"),
                "learned_interval_s": st.get("learned_interval_s"),
                "import_time": st.get("import_time"),
                "export_time": st.get("export_time"),
                "ok": st.get("ok"),
                "last_error": st.get("last_error"),
            },
        }

    def get_prices():
        return prices.get_cached()

    try:
        while True:
            ng.refresh_if_due()
            prices.refresh_if_due()

            if time.ticks_diff(time.ticks_ms(), last_sync_ms) >= SYNC_INTERVAL_MS:
                try:
                    sync_time()
                    last_sync_ms = time.ticks_ms()
                    print("Time re-synchronised (NTP).")
                except Exception as e:
                    print("Hourly NTP sync failed:", repr(e))

            srv.poll_once(get_status, get_prices)
            time.sleep(0.05)

    finally:
        srv.close()


main()