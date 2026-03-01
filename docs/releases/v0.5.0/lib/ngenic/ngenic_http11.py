# ngenic_http11.py
# Minimal HTTP/1.1 over TLS client for MicroPython (avoids urequests 426 issues)

import socket
import json

try:
    import ussl as ssl
except ImportError:
    import ssl  # unlikely on ESP32


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
        i += chunk_len + 2  # skip data + CRLF
    return out


def _parse_headers(header_text):
    lines = header_text.split("\r\n")
    status_line = lines[0]
    parts = status_line.split(" ", 2)
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    hdrs = {}
    for ln in lines[1:]:
        if not ln or ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        hdrs[k.strip().lower()] = v.strip()
    return status, hdrs


def get_json(host, path, headers=None, port=443, timeout_s=20, server_hostname=None):
    """
    Returns: (status:int, resp_headers:dict, parsed_json|None, body_bytes:bytes)
    """
    if headers is None:
        headers = {}

    addr = socket.getaddrinfo(host, port)[0][-1]
    sock = socket.socket()
    sock.settimeout(timeout_s)
    sock.connect(addr)
    s = ssl.wrap_socket(sock, server_hostname=server_hostname or host)

    req = "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n".format(path, host)
    for k, v in headers.items():
        req += "{}: {}\r\n".format(k, v)
    req += "\r\n"

    s.write(req.encode("utf-8"))

    # read all until close
    raw = b""
    while True:
        data = s.read(1024)
        if not data:
            break
        raw += data

    try:
        s.close()
    except Exception:
        pass

    sep = raw.find(b"\r\n\r\n")
    if sep < 0:
        return 0, {}, None, raw

    header_text = raw[:sep].decode("utf-8", "ignore")
    body = raw[sep + 4:]

    status, resp_headers = _parse_headers(header_text)

    if resp_headers.get("transfer-encoding", "").lower() == "chunked":
        body = _decode_chunked(body)

    parsed = None
    # Best effort JSON parse
    try:
        parsed = json.loads(body.decode("utf-8"))
    except Exception:
        parsed = None

    return status, resp_headers, parsed, body