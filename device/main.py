import time
import sys
import machine

import updater
from status_led import StatusLED


def _load_secrets():
    import json
    with open("/secrets.json", "r") as f:
        return json.load(f)


def _boot_button_held():
    # BOOT on Waveshare ESP32‑C6‑Zero‑M is GPIO9 (active low).
    pin = machine.Pin(9, machine.Pin.IN, machine.Pin.PULL_UP)
    return pin.value() == 0


led = StatusLED(pin=8)
updater.set_status_led(led)

# Safe window so you can interrupt from Thonny if needed.
time.sleep(2)

# Roll back automatically if we’re crash-looping.
updater.maybe_rollback(max_failures=3)

secrets = _load_secrets()

# Recovery mode: hold BOOT during reset/boot to stop OTA + app start.
if _boot_button_held():
    # Optional: indicate recovery with a dim blue
    led.solid((0, 0, 10))
    print("BOOT held: recovery mode. Not updating, not starting app.")
    while True:
        time.sleep(1)

# Blink red while we attempt OTA (connect + fetch + download)
led.blink((10, 0, 0), interval_ms=250)

if secrets.get("check_updates_on_boot", True):
    try:
        updater.connect_wifi(secrets["wifi_ssid"], secrets["wifi_password"])
        updater.check_and_update(secrets["manifest_url"])
    except Exception as e:
        # Optional: solid red if OTA failed (still boots local app)
        led.solid((10, 0, 0))
        print("OTA check skipped/failed:", repr(e))

# If we’re here, we’re about to start the app.
# Turn LED off; the app will set it to green once fully started.
led.off()

# Count this boot attempt; the app should clear this via updater.mark_boot_success().
st = updater.load_state()
st["boot_failures"] = int(st.get("boot_failures", 0)) + 1
updater.save_state(st)

# Run /app/app_main.py
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import app_main  # noqa: F401