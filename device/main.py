import time, sys
import machine
import updater

def _load_secrets():
    import json
    with open("/secrets.json", "r") as f:
        return json.load(f)

def _boot_button_held():
    # BOOT on this board is GPIO9 (input, pulled up)
    pin = machine.Pin(9, machine.Pin.IN, machine.Pin.PULL_UP)
    return pin.value() == 0

# Safe window so you can interrupt in Thonny
time.sleep(2)

# Roll back if we crash-loop
updater.maybe_rollback(max_failures=3)

secrets = _load_secrets()

# Hold BOOT to stop everything (recovery mode)
if _boot_button_held():
    print("BOOT held: recovery mode. Not updating, not starting app.")
    while True:
        time.sleep(1)

# OTA check
if secrets.get("check_updates_on_boot", True):
    try:
        updater.connect_wifi(secrets["wifi_ssid"], secrets["wifi_password"])
        updater.check_and_update(secrets["manifest_url"])
    except Exception as e:
        print("OTA check skipped/failed:", repr(e))

# Count this boot attempt; app will clear it when successful
st = updater.load_state()
st["boot_failures"] = int(st.get("boot_failures", 0)) + 1
updater.save_state(st)

# Run /app/app_main.py
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import app_main
