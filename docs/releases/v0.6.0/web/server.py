import socket
import json


def _http_response(status_code, content_type, body_bytes):
    reason = {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        500: "Internal Server Error",
    }.get(status_code, "OK")

    hdr = (
        "HTTP/1.1 {code} {reason}\r\n"
        "Content-Type: {ct}\r\n"
        "Content-Length: {n}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(code=status_code, reason=reason, ct=content_type, n=len(body_bytes))

    return hdr.encode("utf-8") + body_bytes


def _split_path_query(path):
    if not path:
        return "/", ""
    if "?" not in path:
        return path, ""
    a, b = path.split("?", 1)
    return a or "/", b or ""


def _parse_query(qs):
    out = {}
    if not qs:
        return out
    parts = qs.split("&")
    for p in parts:
        if not p:
            continue
        if "=" in p:
            k, v = p.split("=", 1)
        else:
            k, v = p, ""
        out[k] = v
    return out


def _html_index():
    html = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Laundry Assistant</title></head>
<body>
<h1>ESP32-C6 Laundry Assistant</h1>
<p>Internal endpoints:</p>
<ul>
  <li><a href="/api/status">/api/status</a></li>
  <li><a href="/api/prices">/api/prices</a></li>
  <li><a href="/api/recommendations">/api/recommendations</a></li>
  <li><a href="/api/weather/hourly">/api/weather/hourly</a></li>
  <li><a href="/api/solar/hourly">/api/solar/hourly</a></li>
  <li><a href="/api/pv/hourly">/api/pv/hourly</a></li>
</ul>
<p>Query params: <code>?hours=24</code>, <code>/api/pv/hourly?kwp=9.7</code></p>
</body>
</html>
"""
    return html.encode("utf-8")


class WebServer:
    def __init__(self, host="0.0.0.0", port=80):
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(2)
        self._sock.settimeout(0.2)

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass

    def poll_once(self, handlers):
        """
        handlers: dict mapping path -> callable(query_dict) -> python obj (JSON serializable)
        """
        try:
            cl, _addr = self._sock.accept()
        except OSError:
            return

        try:
            cl.settimeout(1.0)
            req = cl.recv(1024)
            if not req:
                return

            try:
                line = req.split(b"\r\n", 1)[0].decode("utf-8", "ignore")
                parts = line.split(" ")
                method = parts[0]
                raw_path = parts[1] if len(parts) > 1 else "/"
            except Exception:
                method, raw_path = "GET", "/"

            if method != "GET":
                cl.send(_http_response(404, "text/plain; charset=utf-8", b"Not found"))
                return

            path, qs = _split_path_query(raw_path)
            query = _parse_query(qs)

            if path == "/" or path == "":
                cl.send(_http_response(200, "text/html; charset=utf-8", _html_index()))
                return

            fn = handlers.get(path)
            if fn is None:
                # Simple prefix fallback for endpoints that might be extended later
                cl.send(_http_response(404, "text/plain; charset=utf-8", b"Not found"))
                return

            payload = fn(query)
            body = json.dumps(payload).encode("utf-8")
            cl.send(_http_response(200, "application/json; charset=utf-8", body))

        except Exception as e:
            try:
                body = ("Server error: %r" % e).encode("utf-8")
                cl.send(_http_response(500, "text/plain; charset=utf-8", body))
            except Exception:
                pass
        finally:
            try:
                cl.close()
            except Exception:
                pass