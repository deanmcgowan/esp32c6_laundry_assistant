# ngenic_poll_csv.py
# Poll Ngenic instantaneous power values every 5s and print CSV.
#
# Prereqs:
#   - Wi-Fi credentials + ngenic_token in /secrets.json
#   - ngenic_tune_uuid and ngenic_grid_node_uuid in /secrets.json (recommended)
#
# If the UUIDs are missing, this script will attempt to discover them (slower).
#
# Stop with Ctrl+C in Thonny.

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


def load_secrets():
    with open("/secrets.json", "r") as f:
        return json.load(f)


def connect_wifi(timeout_s=20):
    sec = load_secrets()
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
        "User-Agent: ESP32C6-MicroPython/1.27 ngenic-poll\r\n"
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


def discover_tune_and_node(token):
    # Tune UUID
    st, tunes, body = http11_get_json(BASE + "/tunes", token)
    if st != 200 or not tunes:
        raise RuntimeError("Unable to list tunes: status=%s body=%s" % (st, body[:120]))

    tune = tunes[0]
    tune_uuid = tune.get("tuneUuid") or tune.get("uuid") or tune.get("id")
    if not tune_uuid:
        raise RuntimeError("Unable to find tuneUuid in /tunes response")

    # Find the node that offers power_kW / produced_power_kW types
    st, nodes, body = http11_get_json(f"{BASE}/tunes/{tune_uuid}/gateway/nodes", token)
    if st != 200 or nodes is None:
        raise RuntimeError("Unable to list nodes: status=%s body=%s" % (st, body[:120]))

    for n in nodes:
        node_uuid = n.get("uuid")
        if not node_uuid:
            continue
        stt, types, bodyt = http11_get_json(f"{BASE}/tunes/{tune_uuid}/measurements/{node_uuid}/types", token)
        if stt != 200 or not isinstance(types, list):
            continue
        if ("power_kW" in types) and ("produced_power_kW" in types):
            return tune_uuid, node_uuid

    raise RuntimeError("Could not find a node with both power_kW and produced_power_kW")


def latest_value(token, tune_uuid, node_uuid, typ):
    st, obj, body = http11_get_json(
        f"{BASE}/tunes/{tune_uuid}/measurements/{node_uuid}/latest?type={typ}",
        token,
    )
    if st == 200 and isinstance(obj, dict):
        if obj.get("hasValue"):
            return obj.get("value")
        return None
    if st == 204:
        return None
    return None


def hhmmss_local():
    # Best effort. If NTP has been set, this will reflect correct localtime
    # only if the system timezone has been configured elsewhere. Otherwise it is UTC.
    t = time.localtime()
    return "%02d:%02d:%02d" % (t[3], t[4], t[5])


def run():
    connect_wifi()

    sec = load_secrets()
    token = sec.get("ngenic_token", "")
    if not token:
        raise RuntimeError("Missing ngenic_token in /secrets.json")

    tune_uuid = sec.get("ngenic_tune_uuid")
    node_uuid = sec.get("ngenic_grid_node_uuid")

    if not tune_uuid or not node_uuid:
        print("No ngenic_tune_uuid/ngenic_grid_node_uuid in secrets; discovering...")
        tune_uuid, node_uuid = discover_tune_and_node(token)
        print("Discovered tune_uuid:", tune_uuid)
        print("Discovered node_uuid:", node_uuid)
        print("Tip: store these in /secrets.json as ngenic_tune_uuid and ngenic_grid_node_uuid")

    # Header row (makes copy/paste into a spreadsheet easier)
    print(
        "epoch_utc,hhmmss_local,import_kW,export_kW,net_kW,"
        "L1_A,L2_A,L3_A,L1_V,L2_V,L3_V"
    )

    while True:
        t_epoch = time.time()

        import_kw = latest_value(token, tune_uuid, node_uuid, "power_kW")
        export_kw = latest_value(token, tune_uuid, node_uuid, "produced_power_kW")

        l1a = latest_value(token, tune_uuid, node_uuid, "L1_current_A")
        l2a = latest_value(token, tune_uuid, node_uuid, "L2_current_A")
        l3a = latest_value(token, tune_uuid, node_uuid, "L3_current_A")

        l1v = latest_value(token, tune_uuid, node_uuid, "L1_voltage_V")
        l2v = latest_value(token, tune_uuid, node_uuid, "L2_voltage_V")
        l3v = latest_value(token, tune_uuid, node_uuid, "L3_voltage_V")

        # net = import - export (both expected non-negative)
        net_kw = None
        if (import_kw is not None) or (export_kw is not None):
            net_kw = (import_kw or 0.0) - (export_kw or 0.0)

        def fmt(x):
            return "" if x is None else str(x)

        line = ",".join([
            str(t_epoch),
            hhmmss_local(),
            fmt(import_kw),
            fmt(export_kw),
            fmt(net_kw),
            fmt(l1a), fmt(l2a), fmt(l3a),
            fmt(l1v), fmt(l2v), fmt(l3v),
        ])
        print(line)

        time.sleep(5)


# Run immediately if executed as a script
run()