import socket
import json


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
    html = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Laundry Assistant</title>
  <style>
    :root{
      --bg: #0b0f14;
      --panel: rgba(255,255,255,0.06);
      --panel2: rgba(255,255,255,0.09);
      --text: rgba(255,255,255,0.92);
      --muted: rgba(255,255,255,0.62);
      --hair: rgba(255,255,255,0.12);
      --accent: #60a5fa;
      --good: #34d399;
      --warn: #fbbf24;
      --bad: #f87171;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
    *{ box-sizing:border-box; }
    body{
      margin:0;
      background: radial-gradient(1200px 800px at 10% 0%, rgba(96,165,250,0.20), transparent 60%),
                  radial-gradient(900px 700px at 90% 10%, rgba(52,211,153,0.16), transparent 55%),
                  var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }
    .wrap{ max-width: 980px; margin: 0 auto; padding: 18px; }
    header{ display:flex; align-items:flex-end; justify-content:space-between; gap:12px; }
    h1{ font-size: 22px; margin: 0; letter-spacing: 0.2px; }
    .sub{ color: var(--muted); font-size: 13px; margin-top: 6px; }
    .pill{
      display:inline-flex; gap:8px; align-items:center;
      padding:8px 10px;
      border:1px solid var(--hair);
      background: var(--panel);
      border-radius: 999px;
      font-size: 12px;
      color: var(--muted);
      white-space:nowrap;
    }
    .dot{ width:8px; height:8px; border-radius:50%; background: var(--muted); }
    .dot.ok{ background: var(--good); }
    .dot.warn{ background: var(--warn); }
    .dot.bad{ background: var(--bad); }

    .tabs{
      margin-top: 14px;
      display:flex;
      gap:8px;
      padding:6px;
      border:1px solid var(--hair);
      background: var(--panel);
      border-radius: 12px;
    }
    .tabbtn{
      flex: 1;
      padding:10px 12px;
      border:1px solid transparent;
      background: transparent;
      color: var(--muted);
      border-radius: 10px;
      font-weight: 600;
      cursor: pointer;
    }
    .tabbtn.active{
      background: var(--panel2);
      border-color: var(--hair);
      color: var(--text);
    }

    .grid{
      margin-top: 14px;
      display:grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .card{
      grid-column: span 12;
      border: 1px solid var(--hair);
      background: var(--panel);
      border-radius: 14px;
      padding: 14px;
    }
    @media (min-width: 860px){
      .half{ grid-column: span 6; }
    }
    .card h2{
      margin: 0 0 10px 0;
      font-size: 15px;
      letter-spacing: 0.2px;
    }
    .kv{ display:grid; grid-template-columns: 170px 1fr; row-gap: 6px; column-gap: 10px; }
    .k{ color: var(--muted); font-size: 13px; }
    .v{ font-size: 14px; font-weight: 650; }
    .mono{ font-family: var(--mono); font-weight: 600; font-size: 13px; color: rgba(255,255,255,0.86); }

    table{
      width:100%;
      border-collapse: collapse;
      overflow:hidden;
      border-radius: 12px;
      border: 1px solid var(--hair);
    }
    th, td{
      text-align:left;
      padding:10px 10px;
      border-bottom: 1px solid var(--hair);
      font-size: 13px;
    }
    th{ color: var(--muted); font-weight: 650; background: rgba(255,255,255,0.04); }
    tr:last-child td{ border-bottom:none; }
    .badge{
      display:inline-flex;
      padding:2px 8px;
      border-radius: 999px;
      border: 1px solid var(--hair);
      background: rgba(255,255,255,0.05);
      font-size: 12px;
      color: rgba(255,255,255,0.85);
      font-weight: 650;
    }
    .muted{ color: var(--muted); }
    .err{
      color: var(--bad);
      font-family: var(--mono);
      font-size: 12px;
      margin-top: 8px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .hidden{ display:none; }
    .foot{
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
    }
  </style>
</head>

<body>
<div class="wrap">
  <header>
    <div>
      <h1>ESP32‑C6 Laundry Assistant</h1>
      <div class="sub">Local web UI (LAN). Data is cached; values may update ~once per minute.</div>
    </div>
    <div class="pill" title="Ngenic freshness">
      <span class="dot" id="freshDot"></span>
      <span id="freshText">…</span>
    </div>
  </header>

  <div class="tabs">
    <button class="tabbtn active" id="tabEnergyBtn" onclick="showTab('energy')">Energy</button>
    <button class="tabbtn" id="tabApplBtn" onclick="showTab('appliances')">Appliances</button>
  </div>

  <div id="tabEnergy">
    <div class="grid">
      <div class="card half">
        <h2>Device</h2>
        <div class="kv">
          <div class="k">IP</div><div class="v mono" id="ip">…</div>
          <div class="k">Device time (UTC epoch)</div><div class="v mono" id="epoch">…</div>
        </div>
      </div>

      <div class="card half">
        <h2>Spot price (SE3)</h2>
        <div class="kv">
          <div class="k">Current price</div><div class="v"><span class="mono" id="spotNow">…</span> <span class="muted">SEK/kWh</span></div>
          <div class="k">Prices cached</div><div class="v mono" id="pricesDays">…</div>
          <div class="k">Cache age</div><div class="v"><span class="mono" id="pricesAge">…</span> <span class="muted">s</span></div>
          <div class="k">Tomorrow</div><div class="v mono" id="tomorrowStatus">…</div>
        </div>
        <div class="err hidden" id="pricesErr"></div>
      </div>

      <div class="card">
        <h2>Ngenic</h2>
        <div class="kv">
          <div class="k">Import</div><div class="v"><span class="mono" id="imp">…</span> <span class="muted">kW</span></div>
          <div class="k">Export</div><div class="v"><span class="mono" id="exp">…</span> <span class="muted">kW</span></div>
          <div class="k">Net</div><div class="v"><span class="mono" id="net">…</span> <span class="muted">kW</span></div>
          <div class="k">Age</div><div class="v"><span class="mono" id="age">…</span> <span class="muted">s</span></div>
          <div class="k">Update interval (learned)</div><div class="v"><span class="mono" id="intv">…</span> <span class="muted">s</span></div>
          <div class="k">Import time</div><div class="v mono" id="impt">…</div>
          <div class="k">Export time</div><div class="v mono" id="expt">…</div>
        </div>
        <div class="err hidden" id="ngenicErr"></div>
      </div>
    </div>
  </div>

  <div id="tabAppliances" class="hidden">
    <div class="grid">
      <div class="card">
        <h2>Delayed start recommendations (spot price only)</h2>
        <div class="muted" style="font-size:12px; margin-top:6px;">
          Savings use default kWh assumptions per cycle (configurable later).
        </div>
        <div style="margin-top:10px; overflow:auto;">
          <table>
            <thead>
              <tr>
                <th>Appliance</th>
                <th>Recommended delay</th>
                <th>Starts at</th>
                <th>Avg price now</th>
                <th>Avg price recommended</th>
                <th>Est. saving</th>
              </tr>
            </thead>
            <tbody id="applRows">
              <tr><td colspan="6" class="muted">Loading…</td></tr>
            </tbody>
          </table>
        </div>
        <div class="err hidden" id="recoErr"></div>
      </div>
    </div>
  </div>

  <div class="foot">
    Endpoints: <span class="mono">/api/status</span>, <span class="mono">/api/prices</span>, <span class="mono">/api/recommendations</span>
  </div>
</div>

<script>
let currentTab = 'energy';

function showTab(name){
  currentTab = name;
  document.getElementById('tabEnergy').classList.toggle('hidden', name !== 'energy');
  document.getElementById('tabAppliances').classList.toggle('hidden', name !== 'appliances');
  document.getElementById('tabEnergyBtn').classList.toggle('active', name === 'energy');
  document.getElementById('tabApplBtn').classList.toggle('active', name === 'appliances');
}

function setErr(id, msg){
  const el = document.getElementById(id);
  if(!msg){
    el.classList.add('hidden');
    el.textContent = '';
  } else {
    el.classList.remove('hidden');
    el.textContent = msg;
  }
}

function dotState(state){
  const dot = document.getElementById('freshDot');
  dot.className = 'dot ' + (state || '');
}

function fmt2(x){
  if(x === null || x === undefined) return '—';
  if(typeof x === 'number') return x.toFixed(2);
  return String(x);
}

function fmtDelayMin(mins){
  if(mins === null || mins === undefined) return '—';
  if(mins === 0) return 'None';
  if(mins % 60 === 0) return (mins/60) + ' h';
  return mins + ' min';
}

async function refreshOnce(){
  // Status
  try{
    const rs = await fetch('/api/status', { cache: 'no-store' });
    const s = await rs.json();

    document.getElementById('epoch').textContent = s.device_epoch_utc;
    document.getElementById('ip').textContent = s.ip || '—';

    const n = s.ngenic || {};
    document.getElementById('imp').textContent = fmt2(n.import_kW);
    document.getElementById('exp').textContent = fmt2(n.export_kW);
    document.getElementById('net').textContent = fmt2(n.net_kW);
    document.getElementById('age').textContent = (n.age_s ?? '—');
    document.getElementById('intv').textContent = fmt2(n.learned_interval_s);
    document.getElementById('impt').textContent = n.import_time || '—';
    document.getElementById('expt').textContent = n.export_time || '—';
    setErr('ngenicErr', n.ok === false ? (n.last_error || 'Ngenic error') : '');

    const age = n.age_s;
    if(age === null || age === undefined){
      dotState('warn'); document.getElementById('freshText').textContent = 'Ngenic: unknown age';
    } else if(age <= 30){
      dotState('ok'); document.getElementById('freshText').textContent = 'Ngenic: fresh (' + age + 's)';
    } else if(age <= 120){
      dotState('warn'); document.getElementById('freshText').textContent = 'Ngenic: stale (' + age + 's)';
    } else {
      dotState('bad'); document.getElementById('freshText').textContent = 'Ngenic: very stale (' + age + 's)';
    }
  }catch(e){
    setErr('ngenicErr', String(e));
  }

  // Prices
  try{
    const rp = await fetch('/api/prices', { cache: 'no-store' });
    const p = await rp.json();

    document.getElementById('pricesAge').textContent = (p.age_s ?? '—');
    document.getElementById('pricesDays').textContent = Object.keys(p.days || {}).join(', ') || '—';
    document.getElementById('tomorrowStatus').textContent = p.tomorrow_status || '—';
    setErr('pricesErr', p.last_error ? String(p.last_error) : '');
  }catch(e){
    setErr('pricesErr', String(e));
  }

  // Recommendations
  try{
    const rr = await fetch('/api/recommendations', { cache: 'no-store' });
    const r = await rr.json();

    document.getElementById('spotNow').textContent = fmt2(r.current_spot_sek_per_kwh);

    const rows = r.appliances || [];
    const tbody = document.getElementById('applRows');

    if(!rows.length){
      tbody.innerHTML = '<tr><td colspan="6" class="muted">No recommendations available (missing prices?).</td></tr>';
    } else {
      tbody.innerHTML = rows.map(x => {
        return `
          <tr>
            <td><span class="badge">${x.name}</span></td>
            <td>${fmtDelayMin(x.recommended_delay_min)}</td>
            <td class="mono">${x.recommended_start_local || '—'}</td>
            <td class="mono">${fmt2(x.avg_price_now_sek_per_kwh)} SEK/kWh</td>
            <td class="mono">${fmt2(x.avg_price_recommended_sek_per_kwh)} SEK/kWh</td>
            <td class="mono">${fmt2(x.estimated_saving_sek)} SEK</td>
          </tr>
        `;
      }).join('');
    }

    setErr('recoErr', r.error ? String(r.error) : '');
  }catch(e){
    setErr('recoErr', String(e));
  }
}

refreshOnce();
setInterval(refreshOnce, 2500);
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

    def poll_once(self, get_status_dict, get_prices_dict, get_reco_dict):
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
                path = parts[1] if len(parts) > 1 else "/"
            except Exception:
                method, path = "GET", "/"

            if method != "GET":
                cl.send(_http_response(404, "text/plain; charset=utf-8", b"Not found"))
                return

            if path == "/" or path.startswith("/?"):
                cl.send(_http_response(200, "text/html; charset=utf-8", _html_index()))
                return

            if path.startswith("/api/status"):
                payload = get_status_dict()
                body = json.dumps(payload).encode("utf-8")
                cl.send(_http_response(200, "application/json; charset=utf-8", body))
                return

            if path.startswith("/api/prices"):
                payload = get_prices_dict()
                body = json.dumps(payload).encode("utf-8")
                cl.send(_http_response(200, "application/json; charset=utf-8", body))
                return

            if path.startswith("/api/recommendations"):
                payload = get_reco_dict()
                body = json.dumps(payload).encode("utf-8")
                cl.send(_http_response(200, "application/json; charset=utf-8", body))
                return

            cl.send(_http_response(404, "text/plain; charset=utf-8", b"Not found"))

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