# ESP32‑C6 Laundry Assistant

A MicroPython project for an ESP32‑C6. The end goal is a small “laundry assistant” that can help optimise when to run washing/drying loads based on information such as spot prices and local generation.

At the moment this repository is mainly about getting solid foundations in place: a simple, robust over‑the‑air (OTA) code update mechanism using a versioned manifest hosted on GitHub Pages.

## Hardware / firmware / tooling

- Board: Waveshare **ESP32‑C6‑Zero‑M**
- Firmware: **MicroPython v1.27.0 (2025‑12‑09)**, build `ESP32_GENERIC_C6`
- IDE: **Thonny** over USB‑C (USB Serial/JTAG / CDC‑ACM)

Quick firmware check in the Thonny REPL:

```python
import sys
print(sys.implementation)
print(sys.version)
```

## Repository layout

- `device/`  
  Files intended to be copied to the ESP32 filesystem (use Thonny’s file browser):
  - `boot.py` – kept minimal for recoverability
  - `main.py` – launcher (safe delay, recovery mode, update check, then runs the app)
  - `updater.py` – OTA updater (manifest fetch, SHA‑256 check, staging swap, rollback)

- `docs/`  
  Files hosted via GitHub Pages:
  - `docs/stable/manifest.json` – the “stable channel” manifest
  - `docs/releases/vX.Y.Z/…` – versioned release payloads (e.g. `app_main.py`)

## How OTA updates work

On boot:

1. `main.py` waits briefly so you can interrupt it in Thonny if you’ve deployed a bad change.
2. If the BOOT button is held, it enters recovery mode (no OTA and no app start).
3. It connects to Wi‑Fi using `/secrets.json`.
4. It fetches the manifest (`stable/manifest.json`).
5. If the manifest version is newer than what’s installed:
   - downloads files into `/next/`
   - verifies each file using SHA‑256
   - swaps `/next` → `/app` and keeps the previous app in `/app_prev`
   - reboots
6. The app should call `updater.mark_boot_success()` once it has started cleanly. If the app crashes repeatedly, the launcher rolls back to `/app_prev`.

This is release‑style OTA: the device installs an explicit version, rather than tracking whatever happens to be on the default branch.

## GitHub Pages

GitHub Pages is configured to serve the `docs/` directory, giving a stable HTTPS endpoint the device can poll.

Stable manifest URL:

```text
https://deanmcgowan.github.io/esp32c6_laundry_assistant/stable/manifest.json
```

Edits to `docs/…` are not always served immediately; GitHub Pages can take a short while to deploy changes.

## Device setup (first install)

### 1) Copy launcher files to the ESP32

Using Thonny’s file browser, copy these to the device root:

- `device/boot.py` → `/boot.py`
- `device/main.py` → `/main.py`
- `device/updater.py` → `/updater.py`

### 2) Install `urequests` (one‑off)

In the Thonny REPL:

```python
import mip
mip.install("urequests")
```

### 3) Create `/secrets.json` on the device

Create a file called `/secrets.json` on the device (do not commit your real Wi‑Fi details):

```json
{
  "wifi_ssid": "YOUR_WIFI_NAME",
  "wifi_password": "YOUR_WIFI_PASSWORD",
  "manifest_url": "https://deanmcgowan.github.io/esp32c6_laundry_assistant/stable/manifest.json",
  "check_updates_on_boot": true
}
```

### 4) Create a local fallback app (recommended)

Create `/app/app_main.py` on the device so there is always something runnable even if Wi‑Fi/OTA fails:

```python
import time
import updater

print("Local fallback app (before OTA)")

updater.mark_boot_success()

while True:
    print("tick local")
    time.sleep(5)
```

### 5) Reboot and watch the console

Press RESET. You should see either the fallback app (if OTA fails) or the GitHub‑hosted release app once the OTA update succeeds.

## Publishing a new release (v0.1.1, v0.1.2, …)

1. Add your new release payload under `docs/releases/vX.Y.Z/`  
   Example: `docs/releases/v0.1.1/app_main.py`

2. Compute SHA‑256 for the bytes that will actually be served. A reliable method is to hash the hosted file from the device:

```python
import urequests, uhashlib, ubinascii

url = "https://deanmcgowan.github.io/esp32c6_laundry_assistant/releases/v0.1.1/app_main.py"

r = urequests.get(url)
h = uhashlib.sha256()

while True:
    chunk = r.raw.read(1024)
    if not chunk:
        break
    h.update(chunk)

r.close()
print(ubinascii.hexlify(h.digest()).decode())
```

3. Update `docs/stable/manifest.json` last (new version, new URL, new SHA‑256).

4. Wait for GitHub Pages to deploy, then reboot the ESP32.

## Recovery / “I’ve broken it”

- Hold BOOT during reset/boot to enter recovery mode (no OTA, no app start).
- If Thonny won’t reconnect after experimenting, unplug/replug USB‑C.
- Avoid using GPIO12/13 (USB D−/D+) for application I/O if you rely on USB Serial/JTAG for development.

## Notes

- This OTA mechanism updates the application files on the filesystem, not the MicroPython firmware image.
- On this board: GPIO8 drives the onboard WS2812 LED; GPIO9 is BOOT/strapping.