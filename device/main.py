import time
import sys
import machine
import network

import updater
from status_led import StatusLED


def _load_secrets():
    import json
    with open("/secrets.json", "r") as f:
        return json.load(f)


def _boot_button_held():
    pin = machine.Pin(9, machine.Pin.IN, machine.Pin.PULL_UP)  # BOOT GPIO9 (active low)
    return pin.value() == 0


def _connect_wifi_with_led(ssid, password, led, timeout_s=20):
    wlan = network.WLAN(network.WLAN.IF_STA)
    wlan.active(True)

    if wlan.isconnected():
        return wlan

    wlan.connect(ssid, password)
    t0 = time.ticks_ms()
    while not wlan.isconnected():
        led.tick()
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
            raise RuntimeError("Wi‑Fi connect timeout")
        time.sleep(0.2)

    return wlan


led = StatusLED(pin=8)
updater.set_status_led(led)

time.sleep(2)  # safe window
updater.maybe_rollback(max_failures=3)

secrets = _load_secrets()
updater.set_verify_sha(secrets.get("ota_verify_sha", True))

if _boot_button_held():
    led.solid((0, 0, 10))
    print("BOOT held: recovery mode. Not updating, not starting app.")
    while True:
        time.sleep(1)

if secrets.get("check_updates_on_boot", True):
    led.blink((10, 0, 0), interval_ms=250)
    try:
        _connect_wifi_with_led(secrets["wifi_ssid"], secrets["wifi_password"], led, timeout_s=20)
        updater.check_and_update(secrets["manifest_url"])
    except Exception as e:
        led.solid((10, 0, 0))
        print("OTA check skipped/failed:", repr(e))

st = updater.load_state()
st["boot_failures"] = int(st.get("boot_failures", 0)) + 1
updater.save_state(st)

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import app_main  # noqa: F401