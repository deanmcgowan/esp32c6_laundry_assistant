import socket
import json
import time


def _http_response(status_code, content_type, body_bytes):
    reason = {
        200: "OK",
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


def _html_index():
    # Simple page that polls /api/status every 2s
    html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Laundry Assistant</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 16px; }
    .card { border: 1px solid #ddd; border-radius: 8px; padding: 12px; margin: 12px 0; }
    .k { color: #666; }
    .v { font-weight: 600; }
    pre { background: #f6f6f6; padding: 8px; border-radius: 6px; overflow: auto; }
  </style>
</head>
<body>
  <h1>ESP32‑C6 Laundry Assistant</h1>

  <div class="card">
    <div><span class="k">Device time (UTC epoch):</span> <span class="v" id="epoch">…</span></div>
    <div><span class="k">IP:</span> <span class="v" id="ip">…</span></div>
  </div>

  <div class="card">
    <h2>Ngenic</h2>
    <div><span class="k">Import (kW):</span> <span class="v" id="imp">…</span></div>
    <div><span class="k">Export (kW):</span> <span class="v" id="exp">…</span></div>
    <div><span class="k">Net (kW):</span> <span class="v" id="net">…</span></div>
    <div><span class="k">Age (s):</span> <span class="v" id="age">…</span></div>
    <div><span class="k">Learned interval (s):</span> <span class="v" id="intv">…</span></div>
    <div><span class="k">Import time:</span> <span class="v" id="impt">…</span></div>
    <div><span class="k">Export time:</span> <span class="v" id="expt">…</span></div>
  </div>

  <div class="card">
    <h2>Raw status</h2>
    <pre id="raw">…</pre>
  </div>

<script>
async function refresh() {
  try {
    const r = await fetch('/api/status', { cache: 'no-store' });
    const d = await r.json();

    document.getElementById('epoch').textContent = d.device_epoch_utc;
    document.getElementById('ip').textContent = d.ip || '';
    document.getElementById('imp').textContent = d.ngenic.import_kW;
    document.getElementById('exp').textContent = d.ngenic.export_kW;
    document.getElementById('net').textContent = d.ngenic.net_kW;
    document.getElementById('age').textContent = d.ngenic.age_s;
    document.getElementById('intv').textContent = d.ngenic.learned_interval_s;
    document.getElementById('impt').textContent = d.ngenic.import_time;
    document.getElementById('expt').textContent = d.ngenic.export_time;

    document.getElementById('raw').textContent = JSON.stringify(d, null, 2);
  } catch (e) {
    document.getElementById('raw').textContent = String(e);
  }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""
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

    def poll_once(self, get_status_dict):
        """
        Non-blocking-ish single accept/serve attempt.
        get_status_dict: callable returning a dict to expose at /api/status
        """
        try:
            cl, addr = self._sock.accept()
        except OSError:
            return  # timeout / no connection

        try:
            cl.settimeout(1.0)
            req = cl.recv(1024)
            if not req:
                return

            # Parse first line: b"GET /path HTTP/1.1"
            try:
                line = req.split(b"\r\n", 1)[0].decode("utf-8", "ignore")
                parts = line.split(" ")
                method = parts[0]
                path = parts[1] if len(parts) > 1 else "/"
            except Exception:
                method, path = "GET", "/"

            if method != "GET":
                body = b"Method not allowed"
                cl.send(_http_response(404, "text/plain; charset=utf-8", body))
                return

            if path == "/" or path.startswith("/?"):
                cl.send(_http_response(200, "text/html; charset=utf-8", _html_index()))
                return

            if path.startswith("/api/status"):
                payload = get_status_dict()
                body = json.dumps(payload).encode("utf-8")
                cl.send(_http_response(200, "application/json; charset=utf-8", body))
                return

            body = b"Not found"
            cl.send(_http_response(404, "text/plain; charset=utf-8", body))

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