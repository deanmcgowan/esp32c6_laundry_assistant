# updater.py — ESP32_GENERIC_C6 / MicroPython v1.27.0
#
# OTA updater with:
# - Manifest-driven file list
# - SHA-256 integrity checks (MicroPython-safe; no .hexdigest())
# - Staging directory (/next) then swap to (/app); keep (/app_prev)
# - Rollback after repeated boot failures
# - Optional status LED blinking support (WS2812 on GPIO8)

import os
import json
import time
import machine
import network
import ubinascii
import urequests as requests

try:
    import uhashlib as hashlib  # MicroPython
except ImportError:
    import hashlib  # Fallback


STATE_PATH = "/state.json"
CHUNK_SIZE = 1024

_status_led = None


def set_status_led(led):
    # led is expected to have .tick() method (see status_led.StatusLED)
    global _status_led
    _status_led = led


def _led_tick():
    try:
        if _status_led:
            _status_led.tick()
    except Exception:
        # Never let LED issues break OTA
        pass


def _load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except OSError:
        return default


def _save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def _parse_ver(v):
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0,)


def _mkdirs(path):
    parts = [p for p in path.split("/") if p]
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            os.mkdir(cur)
        except OSError:
            pass


def _rmtree(path):
    try:
        os.stat(path)
    except OSError:
        return

    try:
        for name, typ, *_ in os.ilistdir(path):
            p = path.rstrip("/") + "/" + name
            if typ == 0x4000:
                _rmtree(p)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
        os.rmdir(path)
    except OSError:
        try:
            os.remove(path)
        except OSError:
            pass


def connect_wifi(ssid, password, timeout_s=20):
    wlan = network.WLAN(network.WLAN.IF_STA)
    wlan.active(True)

    if wlan.isconnected():
        return wlan

    wlan.connect(ssid, password)
    t0 = time.ticks_ms()
    while not wlan.isconnected():
        _led_tick()
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
            raise RuntimeError("Wi-Fi connect timeout")
        time.sleep(0.2)

    return wlan


def _http_get_json(url):
    r = requests.get(url)
    try:
        if r.status_code != 200:
            raise RuntimeError("HTTP %d for %s" % (r.status_code, url))
        return r.json()
    finally:
        try:
            r.close()
        except Exception:
            pass


def _sha256_stream_to_file(resp, dest_path):
    h = hashlib.sha256()

    parent = dest_path.rsplit("/", 1)[0]
    if parent:
        _mkdirs(parent)

    raw = getattr(resp, "raw", None)
    with open(dest_path, "wb") as f:
        if raw and hasattr(raw, "read"):
            while True:
                _led_tick()
                chunk = raw.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
                f.write(chunk)
        else:
            data = resp.content
            h.update(data)
            f.write(data)

    return ubinascii.hexlify(h.digest()).decode().lower()


def _download_with_hash(url, dest_path, expected_sha256, retries=2):
    expected = (expected_sha256 or "").strip().lower()
    last_err = None

    for attempt in range(retries + 1):
        try:
            _led_tick()
            r = requests.get(url)
            try:
                if r.status_code != 200:
                    raise RuntimeError("HTTP %d for %s" % (r.status_code, url))
                got = _sha256_stream_to_file(r, dest_path)
            finally:
                try:
                    r.close()
                except Exception:
                    pass

            if expected and got != expected:
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
                raise RuntimeError("SHA256 mismatch for %s" % dest_path)

            return

        except Exception as e:
            last_err = e
            try:
                os.remove(dest_path)
            except OSError:
                pass
            time.sleep(0.5 + 0.5 * attempt)

    raise last_err


def load_state():
    return _load_json(
        STATE_PATH,
        {"installed_version": "0.0.0", "boot_failures": 0, "pending_version": None},
    )


def save_state(st):
    _save_json(STATE_PATH, st)


def mark_boot_success():
    st = load_state()
    st["boot_failures"] = 0
    st["pending_version"] = None
    save_state(st)


def maybe_rollback(max_failures=3):
    st = load_state()
    if int(st.get("boot_failures", 0)) < max_failures:
        return False

    try:
        os.stat("/app_prev")
    except OSError:
        return False

    _rmtree("/app_bad")
    try:
        os.rename("/app", "/app_bad")
    except OSError:
        pass
    os.rename("/app_prev", "/app")

    st["boot_failures"] = 0
    st["pending_version"] = None
    save_state(st)

    machine.reset()
    return True


def apply_update(manifest):
    new_ver = manifest["version"]
    files = manifest.get("files", [])
    if not files:
        raise RuntimeError("Manifest has no files")

    _rmtree("/next")
    try:
        os.mkdir("/next")
    except OSError:
        pass

    for item in files:
        rel = item["path"].lstrip("/")
        url = item["url"]
        sha = item.get("sha256", "")
        dest = "/next/" + rel
        _download_with_hash(url, dest, sha, retries=2)

    _rmtree("/app_prev")
    try:
        os.rename("/app", "/app_prev")
    except OSError:
        pass
    os.rename("/next", "/app")

    st = load_state()
    st["installed_version"] = new_ver
    st["pending_version"] = new_ver
    st["boot_failures"] = 0
    save_state(st)

    machine.reset()


def check_and_update(manifest_url):
    st = load_state()
    manifest = _http_get_json(manifest_url)

    new_ver = manifest.get("version", "0.0.0")
    cur_ver = st.get("installed_version", "0.0.0")

    if _parse_ver(new_ver) <= _parse_ver(cur_ver):
        return False

    apply_update(manifest)
    return True
