import json
import time
import socket
import network

try:
    import ussl as ssl
except ImportError:
    import ssl  # unlikely on ESP32

HOST = "app.ngenic.se"
PORT = 443
BASE = "/api/v3"
CHUNK = 1024


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
    chunks = []
    while True:
        data = s.read(CHUNK)
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


def _decode_chunked(body):
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
        i += chunk_len + 2
    return out


def http11_get_json(path, token, timeout_s=20):
    addr = socket.getaddrinfo(HOST, PORT)[0][-1]
    sock = socket.socket()
    sock.settimeout(timeout_s)
    sock.connect(addr)
    s = ssl.wrap_socket(sock, server_hostname=HOST)

    req = (
        "GET {path} HTTP/1.1\r\n"
        "Host: {host}\r\n"
        "User-Agent: ESP32C6-MicroPython/1.27 ngenic-probe\r\n"
        "Accept: application/json\r\n"
        "Authorization: Bearer {token}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(path=path, host=HOST, token=token)

    s.write(req.encode("utf-8"))
    raw = _recv_all(s)
    try:
        s.close()
    except Exception:
        pass

    sep = raw.find(b"\r\n\r\n")
    if sep < 0:
        return 0, None, b""

    header = raw[:sep].decode("utf-8", "ignore")
    body = raw[sep + 4:]

    # status code
    first = header.split("\r\n", 1)[0]
    parts = first.split(" ")
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    # chunked?
    if "\r\ntransfer-encoding: chunked" in header.lower():
        body = _decode_chunked(body)

    parsed = None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except Exception:
        parsed = None

    return status, parsed, body


def _type_to_str(t):
    # types may come back as strings or dicts; handle both
    if isinstance(t, str):
        return t
    if isinstance(t, dict):
        # guess likely keys
        return t.get("type") or t.get("name") or t.get("id") or t.get("uuid") or str(t)
    return str(t)


def run():
    connect_wifi()

    sec = _load_secrets()
    token = sec.get("ngenic_token", "")
    if not token:
        raise RuntimeError("Missing ngenic_token in /secrets.json")

    st, tunes, body = http11_get_json(BASE + "/tunes", token)
    print("tunes status:", st)
    if st != 200 or not tunes:
        print("tunes body:", body[:300])
        return

    tune = tunes[0]
    tune_uuid = tune.get("tuneUuid") or tune.get("uuid") or tune.get("id")
    print("tune_uuid:", tune_uuid)

    st, nodes, body = http11_get_json(f"{BASE}/tunes/{tune_uuid}/gateway/nodes", token)
    print("nodes status:", st)
    if st != 200 or nodes is None:
        print("nodes body:", body[:300])
        return

    print("node count:", len(nodes))

    # Try nodestatus too (sometimes useful)
    st_ns, nodestatus, body_ns = http11_get_json(f"{BASE}/tunes/{tune_uuid}/nodestatus", token)
    print("nodestatus status:", st_ns)
    if st_ns == 200 and nodestatus is not None:
        if isinstance(nodestatus, list):
            print("nodestatus list len:", len(nodestatus))
        elif isinstance(nodestatus, dict):
            print("nodestatus keys:", list(nodestatus.keys())[:25])

    # For each node: list types and fetch latest?type=...
    for n in nodes:
        node_uuid = n.get("uuid")
        node_type = n.get("type")
        dev = n.get("device", {})
        dev_name = dev.get("name") or dev.get("model") or ""
        print("\n---")
        print("node_uuid:", node_uuid)
        print("node_type:", node_type, "device:", dev_name)

        st_t, types, body_t = http11_get_json(
            f"{BASE}/tunes/{tune_uuid}/measurements/{node_uuid}/types",
            token
        )
        print("types status:", st_t)
        if st_t != 200 or types is None:
            print("types body:", body_t[:200])
            continue

        type_list = [_type_to_str(x) for x in types]
        print("types:", type_list)

        for t in type_list:
            # note: types are usually safe strings like temperature_C, power_W, etc.
            path = f"{BASE}/tunes/{tune_uuid}/measurements/{node_uuid}/latest?type={t}"
            st_l, latest, body_l = http11_get_json(path, token)
            print(" latest", t, "status:", st_l)
            if st_l == 200 and latest is not None:
                print("  value:", latest)
            else:
                print("  body:", body_l[:120])

            time.sleep(0.1)


# If you want it to auto-run on import, uncomment:
# run()