# ngenic_probe.py
# Probe Ngenic Tune API endpoints using HTTP/1.1 (avoids urequests HTTP/1.0 issues / 426).
#
# Usage:
#   import ngenic_probe
#   ngenic_probe.run()
#
# Requirements:
#   - Wi-Fi connected OR provide ssid/password in /secrets.json and call connect_wifi() first.
#   - /secrets.json contains: {"ngenic_token": "..."}
#
# Notes:
#   - This is intentionally defensive: it prints status + small body snippets only.
#   - If you get 401/403 on most endpoints, token/subscription scope is the issue.
#   - If you still get 426 here, it’s likely a server-side policy beyond HTTP/1.1.

import json
import time
import socket

try:
    import ussl as ssl
except ImportError:
    import ssl  # pragma: no cover (unlikely on ESP32)

import network


HOST = "app.ngenic.se"
PORT = 443
BASE = "/api/v3"
SNIP = 300  # body snippet length


def _load_secrets():
    with open("/secrets.json", "r") as f:
        return json.load(f)


def connect_wifi(timeout_s=20):
    sec = _load_secrets()
    ssid = sec.get("wifi_ssid")
    pw = sec.get("wifi_password")
    if not ssid:
        raise RuntimeError("No wifi_ssid in /secrets.json")

    wlan = network.WLAN(network.WLAN.IF_STA)
    wlan.active(True)
    if wlan.isconnected():
        return wlan

    wlan.connect(ssid, pw)
    t0 = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
            raise RuntimeError("Wi-Fi connect timeout")
        time.sleep(0.2)
    return wlan


def _recv_all(s):
    # Read until close
    chunks = []
    while True:
        data = s.read(1024)
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


def _parse_headers(header_bytes):
    # Returns: (status_code, headers_dict)
    text = header_bytes.decode("utf-8", "ignore")
    lines = text.split("\r\n")
    status_line = lines[0]
    parts = status_line.split(" ", 2)
    code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    hdrs = {}
    for ln in lines[1:]:
        if not ln or ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        hdrs[k.strip().lower()] = v.strip()
    return code, hdrs


def _decode_chunked(body):
    # Minimal chunked decoder
    out = b""
    i = 0
    n = len(body)
    while True:
        j = body.find(b"\r\n", i)
        if j < 0:
            break
        line = body[i:j].split(b";", 1)[0].strip()
        try:
            chunk_len = int(line, 16)
        except ValueError:
            break
        i = j + 2
        if chunk_len == 0:
            break
        if i + chunk_len > n:
            break
        out += body[i:i + chunk_len]
        i += chunk_len + 2  # skip data + CRLF
    return out


def http11_get_json_or_text(path, token=None, extra_headers=None, timeout_s=20):
    addr = socket.getaddrinfo(HOST, PORT)[0][-1]
    sock = socket.socket()
    sock.settimeout(timeout_s)
    sock.connect(addr)
    s = ssl.wrap_socket(sock, server_hostname=HOST)

    headers = {
        "Host": HOST,
        "User-Agent": "ESP32C6-MicroPython/1.27 ngenic-probe",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.1",
        "Connection": "close",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    if extra_headers:
        headers.update(extra_headers)

    req = "GET {} HTTP/1.1\r\n".format(path)
    for k, v in headers.items():
        req += "{}: {}\r\n".format(k, v)
    req += "\r\n"

    s.write(req.encode("utf-8"))
    raw = _recv_all(s)
    try:
        s.close()
    except Exception:
        pass

    # Split headers/body
    sep = raw.find(b"\r\n\r\n")
    if sep < 0:
        return 0, {}, b"", None

    header_bytes = raw[:sep]
    body = raw[sep + 4:]

    status, hdrs = _parse_headers(header_bytes)

    if hdrs.get("transfer-encoding", "").lower() == "chunked":
        body = _decode_chunked(body)

    # Try JSON parse (best effort)
    parsed = None
    ct = hdrs.get("content-type", "")
    if "json" in ct or (body[:1] in (b"{", b"[")):
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            parsed = None

    return status, hdrs, body, parsed


def _print_result(path, status, hdrs, body, parsed):
    clen = hdrs.get("content-length", "")
    ct = hdrs.get("content-type", "")
    print("\n==", path)
    print("status:", status, "content-type:", ct, "content-length:", clen, "bytes:", len(body))

    if parsed is not None:
        # Print a small summary of JSON structure
        if isinstance(parsed, dict):
            keys = list(parsed.keys())
            print("json: dict keys:", keys[:20])
        elif isinstance(parsed, list):
            print("json: list len:", len(parsed))
            if len(parsed) > 0 and isinstance(parsed[0], dict):
                print("json: first item keys:", list(parsed[0].keys())[:20])
    else:
        # Print body snippet as text
        txt = body.decode("utf-8", "ignore")
        print("body (snippet):", txt[:SNIP])


def _probe_paths(paths, token):
    results = []
    for p in paths:
        try:
            status, hdrs, body, parsed = http11_get_json_or_text(p, token=token)
            _print_result(p, status, hdrs, body, parsed)
            results.append((p, status, hdrs.get("content-type", ""), len(body)))
        except Exception as e:
            print("\n==", p)
            print("error:", repr(e))
            results.append((p, -1, "", 0))
        time.sleep(0.2)
    return results


def run():
    # Ensure Wi-Fi is up (optional; remove if you connect elsewhere)
    try:
        connect_wifi()
    except Exception as e:
        print("Wi-Fi connect skipped/failed:", repr(e))
        # Continue anyway in case you're already connected

    sec = _load_secrets()
    token = sec.get("ngenic_token", "")
    if not token:
        raise RuntimeError("Missing ngenic_token in /secrets.json")

    # “Wide net” probe:
    # - Some are expected to 404; that’s fine.
    # - The aim is to learn what your account/token can see (200 vs 401/403),
    #   and whether the server still returns 426 for any reason.
    paths = [
        # Root-ish
        "/",
        BASE,
        BASE + "/",
        BASE + "/health",
        BASE + "/status",
        BASE + "/version",
        BASE + "/me",
        BASE + "/user",
        BASE + "/users/me",
        BASE + "/account",
        BASE + "/accounts",

        # Primary object in Tune API
        BASE + "/tunes",
        BASE + "/tunes/",
    ]

    results = _probe_paths(paths, token)

    # If we can list tunes, attempt deeper discovery automatically.
    tune_uuid = None
    try:
        status, hdrs, body, parsed = http11_get_json_or_text(BASE + "/tunes/", token=token)
        if status == 200 and parsed is not None:
            # parsed may be list or {"items":[...]}
            items = None
            if isinstance(parsed, dict) and "items" in parsed:
                items = parsed.get("items")
            elif isinstance(parsed, list):
                items = parsed
            if items and isinstance(items, list) and len(items) > 0:
                t0 = items[0]
                tune_uuid = t0.get("uuid") or t0.get("tuneUuid") or t0.get("id")
    except Exception:
        tune_uuid = None

    if not tune_uuid:
        print("\nNo tune UUID discovered. That likely means subscription/token scope limits (or 401/403).")
        print("Summary (path, status):")
        for p, st, ct, n in results:
            print(st, p)
        return

    print("\nDiscovered tune_uuid:", tune_uuid)

    deep_paths = [
        # Nodes / gateway
        f"{BASE}/tunes/{tune_uuid}/gateway",
        f"{BASE}/tunes/{tune_uuid}/gateway/",
        f"{BASE}/tunes/{tune_uuid}/gateway/nodes",
        f"{BASE}/tunes/{tune_uuid}/gateway/nodes/",
        f"{BASE}/tunes/{tune_uuid}/nodes",
        f"{BASE}/tunes/{tune_uuid}/nodes/",

        # Often useful
        f"{BASE}/tunes/{tune_uuid}/rooms",
        f"{BASE}/tunes/{tune_uuid}/rooms/",
        f"{BASE}/tunes/{tune_uuid}/weather",
        f"{BASE}/tunes/{tune_uuid}/settings",
    ]

    _probe_paths(deep_paths, token)

    # Try to discover a node UUID for measurements
    node_uuid = None
    for nodes_path in (f"{BASE}/tunes/{tune_uuid}/gateway/nodes/", f"{BASE}/tunes/{tune_uuid}/nodes/"):
        try:
            st, hdrs, body, parsed = http11_get_json_or_text(nodes_path, token=token)
            if st != 200 or parsed is None:
                continue
            items = None
            if isinstance(parsed, dict) and "items" in parsed:
                items = parsed.get("items")
            elif isinstance(parsed, list):
                items = parsed
            if items and isinstance(items, list) and len(items) > 0 and isinstance(items[0], dict):
                node_uuid = items[0].get("uuid") or items[0].get("nodeUuid") or items[0].get("id")
                if node_uuid:
                    break
        except Exception:
            pass

    if not node_uuid:
        print("\nCould not discover a node UUID for measurements.")
        print("If nodes are visible but structure differs, paste the 'nodes' JSON keys and we’ll adjust.")
        return

    print("\nDiscovered node_uuid:", node_uuid)

    meas_paths = [
        f"{BASE}/tunes/{tune_uuid}/measurements/{node_uuid}/types",
        f"{BASE}/tunes/{tune_uuid}/measurements/{node_uuid}/types/",
        f"{BASE}/tunes/{tune_uuid}/measurements/{node_uuid}/latest",
        f"{BASE}/tunes/{tune_uuid}/measurements/{node_uuid}/latest/",
    ]
    _probe_paths(meas_paths, token)

    print("\nDone.")