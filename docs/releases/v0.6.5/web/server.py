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
    for p in qs.split("&"):
        if not p:
            continue
        if "=" in p:
            k, v = p.split("=", 1)
        else:
            k, v = p, ""
        out[k] = v
    return out


def _html_index():
    html = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ESP32-C6 Energy Hub</title>
  <style>
    :root { --bg:#0b1220; --card:#121c33; --muted:#9fb0d0; --text:#e7eefc; --accent:#5aa2ff; --warn:#ffcc66; }
    body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:var(--bg); color:var(--text); }
    header { padding:14px 16px; border-bottom:1px solid rgba(255,255,255,0.08); }
    header h1 { margin:0; font-size:16px; font-weight:600; }
    header .sub { margin-top:4px; color:var(--muted); font-size:12px; }
    nav { display:flex; gap:8px; padding:10px 12px; border-bottom:1px solid rgba(255,255,255,0.08); }
    nav button { background:transparent; color:var(--muted); border:1px solid rgba(255,255,255,0.12); padding:8px 10px; border-radius:10px; cursor:pointer; }
    nav button.active { color:var(--text); border-color:rgba(90,162,255,0.8); box-shadow: 0 0 0 1px rgba(90,162,255,0.35) inset; }
    main { padding:12px; max-width: 980px; margin: 0 auto; }
    .grid { display:grid; grid-template-columns: repeat(12, 1fr); gap:10px; }
    .card { grid-column: span 12; background:var(--card); border:1px solid rgba(255,255,255,0.08); border-radius:14px; padding:12px; }
    @media (min-width: 760px) {
      .card.half { grid-column: span 6; }
      .card.third { grid-column: span 4; }
    }
    .kpi { display:flex; gap:10px; align-items: baseline; flex-wrap: wrap; }
    .kpi .label { color:var(--muted); font-size:12px; }
    .kpi .value { font-size:22px; font-weight:700; }
    .kpi .unit { color:var(--muted); font-size:12px; margin-left:6px; }
    .row { display:flex; justify-content: space-between; gap:12px; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.06); }
    .row:last-child { border-bottom:0; }
    .row .l { color:var(--muted); font-size:12px; }
    .row .r { font-size:12px; }
    .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; border:1px solid rgba(255,255,255,0.12); color: var(--muted); }
    .pill.ok { color: #a7ffb7; border-color: rgba(167,255,183,0.22); }
    .pill.warn { color: var(--warn); border-color: rgba(255,204,102,0.25); }
    table { width:100%; border-collapse: collapse; font-size:12px; }
    th, td { text-align:left; padding:8px 6px; border-bottom:1px solid rgba(255,255,255,0.08); }
    th { color:var(--muted); font-weight:600; }
    .actions { display:flex; gap:8px; align-items:center; margin-top:8px; }
    .actions button { background: rgba(90,162,255,0.15); border:1px solid rgba(90,162,255,0.35); color:var(--text); padding:7px 10px; border-radius:10px; cursor:pointer; }
    .small { color:var(--muted); font-size:12px; }
    .tab { display:none; }
    .tab.active { display:block; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

    .reco-grid { display:grid; grid-template-columns: repeat(12, 1fr); gap:10px; margin-top:10px; }
    .reco-card {
      grid-column: span 12;
      border:1px solid rgba(255,255,255,0.08);
      border-radius:12px;
      padding:10px;
      background: linear-gradient(160deg, rgba(90,162,255,0.08), rgba(90,162,255,0.02));
    }
    .reco-head { display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
    .reco-name { font-size:14px; font-weight:600; }
    .reco-sub { color:var(--muted); font-size:12px; margin-top:2px; }
    .reco-delay { font-size:20px; font-weight:700; }
    .reco-bars { margin-top:8px; }
    .bar-row { margin-top:6px; }
    .bar-label { color:var(--muted); font-size:11px; margin-bottom:3px; }
    .bar-track { width:100%; height:8px; background:rgba(255,255,255,0.08); border-radius:999px; overflow:hidden; }
    .bar-fill { height:100%; background:linear-gradient(90deg, #ff9f4a, #5aa2ff); }
    .reco-nums { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:8px; margin-top:8px; }
    .mini { border:1px solid rgba(255,255,255,0.07); border-radius:10px; padding:6px 8px; }
    .mini .k { color:var(--muted); font-size:11px; }
    .mini .v { font-size:13px; margin-top:2px; }
    @media (min-width: 900px) {
      .reco-card { grid-column: span 4; }
    }
  </style>
</head>
<body>
  <header>
    <h1>ESP32-C6 Energy Hub</h1>
    <div class="sub">Live power every 5s. Prices and forecasts refresh less frequently.</div>
  </header>

  <nav>
    <button id="btn-energy" class="active" onclick="showTab('energy')">Energy</button>
    <button id="btn-whiteware" onclick="showTab('whiteware')">Whiteware</button>
    <button id="btn-forecast" onclick="showTab('forecast')">Forecast</button>
  </nav>

  <main>
    <section id="tab-energy" class="tab active">
      <div class="grid">
        <div class="card third">
          <div class="kpi">
            <div class="label">Import</div>
            <div class="value" id="imp">-</div><div class="unit">kW</div>
          </div>
          <div class="row"><div class="l">Export</div><div class="r"><span id="exp">-</span> kW</div></div>
          <div class="row"><div class="l">Net</div><div class="r"><span id="net">-</span> kW</div></div>
          <div class="row"><div class="l">Freshness</div><div class="r"><span id="ng-pill" class="pill">-</span></div></div>
        </div>

        <div class="card third">
          <div class="kpi">
            <div class="label">Spot price (SE3)</div>
            <div class="value" id="spot">-</div><div class="unit">SEK/kWh</div>
          </div>
          <div class="row"><div class="l">Cached</div><div class="r"><span id="price-pill" class="pill">-</span></div></div>
          <div class="row"><div class="l">Tomorrow</div><div class="r" id="tomorrow">-</div></div>
          <div class="actions">
            <button onclick="refreshPricesNow()">Refresh prices</button>
          </div>
          <div class="small">Price view refreshes about every 15 minutes in UI.</div>
        </div>

        <div class="card third">
          <div class="kpi">
            <div class="label">PV next 24h (est.)</div>
            <div class="value" id="pv24">-</div><div class="unit">kWh</div>
          </div>
          <div class="row"><div class="l">Next hour</div><div class="r"><span id="pv1">-</span> kW</div></div>
          <div class="row"><div class="l">Cached</div><div class="r"><span id="pv-pill" class="pill">-</span></div></div>
          <div class="actions">
            <button onclick="refreshPvNow()">Refresh PV</button>
          </div>
          <div class="small">Simple PV estimate using irradiance and fixed loss factor.</div>
        </div>
      </div>
    </section>

    <section id="tab-whiteware" class="tab">
      <div class="card">
        <div class="kpi">
          <div class="label">Delayed start suggestions</div>
          <div class="value">Whiteware planner</div>
        </div>
        <div class="small">Combines spot prices, live import/export and PV forecast to minimise expected grid cost.</div>
        <div class="actions">
          <button onclick="refreshRecoNow()">Refresh suggestions</button>
          <span class="pill" id="reco-pill">-</span>
        </div>
        <div id="reco-summary" class="small" style="margin-top:8px;">Loading strategy...</div>
        <div id="reco-grid" class="reco-grid">
          <div class="reco-card small">Loading recommendations...</div>
        </div>
      </div>
    </section>

    <section id="tab-forecast" class="tab">
      <div class="grid">
        <div class="card half">
          <div class="kpi">
            <div class="label">Temperature (SMHI) next 24h</div>
            <div class="value">Forecast</div>
          </div>
          <div class="actions">
            <button onclick="refreshWeatherNow()">Refresh weather</button>
            <span class="pill" id="wx-pill">-</span>
          </div>
          <div style="overflow:auto; margin-top:10px;">
            <table>
              <thead><tr><th>End</th><th>T (C)</th><th>Wind (m/s)</th></tr></thead>
              <tbody id="wx-body"><tr><td colspan="3" class="small">Loading...</td></tr></tbody>
            </table>
          </div>
        </div>

        <div class="card half">
          <div class="kpi">
            <div class="label">Solar (Open-Meteo) next 24h</div>
            <div class="value">Irradiance</div>
          </div>
          <div class="actions">
            <button onclick="refreshSolarNow()">Refresh solar</button>
            <span class="pill" id="sol-pill">-</span>
          </div>
          <div style="overflow:auto; margin-top:10px;">
            <table>
              <thead><tr><th>End</th><th>GTI (W/m2)</th><th>Cloud (%)</th></tr></thead>
              <tbody id="sol-body"><tr><td colspan="3" class="small">Loading...</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </section>

    <div class="small" style="margin-top:10px;">
      Live power: 5s | Prices: 15m | Suggestions: 15m | PV: 30m
    </div>
  </main>

<script>
  let currentTab = 'energy';

  function showTab(name) {
    currentTab = name;
    for (const t of ['energy','whiteware','forecast']) {
      document.getElementById('tab-' + t).classList.toggle('active', t === name);
      document.getElementById('btn-' + t).classList.toggle('active', t === name);
    }
    if (name === 'forecast') {
      refreshWeatherNow();
      refreshSolarNow();
    }
  }

  function fmtNum(x, dp) {
    if (x === null || x === undefined) return "-";
    const n = Number(x);
    if (Number.isNaN(n)) return "-";
    return (dp === null || dp === undefined) ? String(n) : n.toFixed(dp);
  }

  function fmtDelay(mins) {
    if (mins === null || mins === undefined) return "-";
    const m = Number(mins);
    if (!Number.isFinite(m)) return "-";
    if (m === 0) return "Start now";
    if (m < 60) return String(m) + " min";
    const h = Math.floor(m / 60);
    const r = m % 60;
    if (r === 0) return String(h) + " h";
    return String(h) + " h " + String(r) + " min";
  }

  function pct(v, maxv) {
    if (!Number.isFinite(v) || !Number.isFinite(maxv) || maxv <= 0) return 0;
    const p = (v / maxv) * 100;
    if (p < 0) return 0;
    if (p > 100) return 100;
    return p;
  }

  function setText(id, txt) {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  }

  function setPill(id, state, text) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('ok');
    el.classList.remove('warn');
    if (state === 'ok') el.classList.add('ok');
    if (state === 'warn') el.classList.add('warn');
    el.textContent = text;
  }

  async function getJson(url, timeoutMs) {
    timeoutMs = timeoutMs || 2500;
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const r = await fetch(url, {signal: ctrl.signal, cache: "no-store"});
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    } finally {
      clearTimeout(t);
    }
  }

  function okEnvelope(env) {
    return env && env.meta && env.data;
  }

  async function refreshStatusNow() {
    const env = await getJson('/api/status', 1500);
    if (!okEnvelope(env)) { setPill('ng-pill', 'warn', 'offline'); return; }
    const ng = (env.data && env.data.ngenic) ? env.data.ngenic : {};
    setText('imp', fmtNum(ng.import_kW, 2));
    setText('exp', fmtNum(ng.export_kW, 2));
    setText('net', fmtNum(ng.net_kW, 2));
    const age = ng.age_s;
    if (age === null || age === undefined) setPill('ng-pill', 'warn', 'unknown');
    else if (age <= 120) setPill('ng-pill', 'ok', 'ok (' + age + 's)');
    else setPill('ng-pill', 'warn', 'stale (' + age + 's)');
  }

  async function refreshPricesNow() {
    const env = await getJson('/api/prices', 3000);
    if (!okEnvelope(env)) { setPill('price-pill', 'warn', 'offline'); return; }
    const d = env.data || {};
    const cur = d.current || {};
    setText('spot', fmtNum(cur.sek_per_kwh, 3));
    const a = d.cache_age_s;
    if (a === null || a === undefined) setPill('price-pill', 'warn', 'unknown');
    else setPill('price-pill', a < 7200 ? 'ok' : 'warn', 'age ' + a + 's');
    setText('tomorrow', d.tomorrow_status || '-');
  }

  async function refreshRecoNow() {
    const env = await getJson('/api/recommendations', 3000);
    if (!okEnvelope(env)) { setPill('reco-pill', 'warn', 'offline'); return; }
    const d = env.data || {};
    if (d.error) { setPill('reco-pill', 'warn', 'no data'); return; }

    const strategy = d.strategy || {};
    setPill('reco-pill', 'ok', (strategy.mode || 'ok').replace('_', ' '));

    const summary = document.getElementById('reco-summary');
    if (summary) {
      let line = strategy.reason || 'Expected grid cost optimisation.';
      if (strategy.max_delay_hours !== null && strategy.max_delay_hours !== undefined) {
        line += ' Max delay window: ' + strategy.max_delay_hours + 'h.';
      }
      summary.textContent = line;
    }

    const grid = document.getElementById('reco-grid');
    if (!grid) return;
    grid.innerHTML = '';

    const rows = d.appliances || [];
    if (!rows.length) {
      grid.innerHTML = '<div class="reco-card small">No recommendations available.</div>';
      return;
    }

    for (const r of rows) {
      const scoreNow = Number(r.score_now_sek || 0);
      const scoreBest = Number(r.score_recommended_sek || 0);
      const scoreMax = Math.max(scoreNow, scoreBest, 0.01);
      const nowBar = pct(scoreNow, scoreMax);
      const recBar = pct(scoreBest, scoreMax);
      const basis = (r.decision_basis || 'mixed').replace('_', ' ');

      const card = document.createElement('div');
      card.className = 'reco-card';
      card.innerHTML =
        '<div class="reco-head">' +
          '<div>' +
            '<div class="reco-name">' + (r.name || 'Appliance') + '</div>' +
            '<div class="reco-sub">Start at ' + (r.recommended_start_local || '-') + ' | basis: ' + basis + '</div>' +
          '</div>' +
          '<div class="reco-delay">' + fmtDelay(r.recommended_delay_min) + '</div>' +
        '</div>' +
        '<div class="reco-bars">' +
          '<div class="bar-row">' +
            '<div class="bar-label">Estimated grid cost now: ' + fmtNum(r.score_now_sek, 2) + ' SEK</div>' +
            '<div class="bar-track"><div class="bar-fill" style="width:' + nowBar + '%"></div></div>' +
          '</div>' +
          '<div class="bar-row">' +
            '<div class="bar-label">Estimated grid cost recommended: ' + fmtNum(r.score_recommended_sek, 2) + ' SEK</div>' +
            '<div class="bar-track"><div class="bar-fill" style="width:' + recBar + '%"></div></div>' +
          '</div>' +
        '</div>' +
        '<div class="reco-nums">' +
          '<div class="mini"><div class="k">Avg price now</div><div class="v">' + fmtNum(r.avg_price_now_sek_per_kwh, 2) + ' SEK/kWh</div></div>' +
          '<div class="mini"><div class="k">Avg price recommended</div><div class="v">' + fmtNum(r.avg_price_recommended_sek_per_kwh, 2) + ' SEK/kWh</div></div>' +
          '<div class="mini"><div class="k">PV energy used</div><div class="v">' + fmtNum(r.estimated_pv_kwh_recommended, 2) + ' kWh</div></div>' +
          '<div class="mini"><div class="k">Grid energy used</div><div class="v">' + fmtNum(r.estimated_grid_kwh_recommended, 2) + ' kWh</div></div>' +
        '</div>' +
        '<div class="small" style="margin-top:8px;">Estimated saving: ' + fmtNum(r.estimated_saving_sek, 2) + ' SEK</div>';
      grid.appendChild(card);
    }
  }

  async function refreshWeatherNow() {
    const env = await getJson('/api/weather_hourly?hours=24', 4500);
    if (!okEnvelope(env)) { setPill('wx-pill', 'warn', 'offline'); return; }
    const d = env.data || {};
    const ok = d.primary && d.primary.ok;
    setPill('wx-pill', ok ? 'ok' : 'warn', ok ? 'ok' : 'stale');
    const body = document.getElementById('wx-body');
    body.innerHTML = '';
    const series = (d.primary && d.primary.series) ? d.primary.series : [];
    for (const it of series) {
      const end = (it.end && it.end.stockholm) ? it.end.stockholm : '-';
      const v = it.values || {};
      const tr = document.createElement('tr');
      tr.innerHTML = '<td class="mono"></td><td></td><td></td>';
      tr.children[0].textContent = end.slice(11, 16);
      tr.children[1].textContent = fmtNum(v.t_air_c, 1);
      tr.children[2].textContent = fmtNum(v.wind_mps, 1);
      body.appendChild(tr);
    }
  }

  async function refreshSolarNow() {
    const env = await getJson('/api/solar_hourly?hours=24', 4500);
    if (!okEnvelope(env)) { setPill('sol-pill', 'warn', 'offline'); return; }
    const d = env.data || {};
    setPill('sol-pill', d.ok ? 'ok' : 'warn', d.ok ? 'ok' : 'stale');
    const body = document.getElementById('sol-body');
    body.innerHTML = '';
    const series = d.series || [];
    for (const it of series) {
      const end = (it.end && it.end.stockholm) ? it.end.stockholm : '-';
      const v = it.values || {};
      const tr = document.createElement('tr');
      tr.innerHTML = '<td class="mono"></td><td></td><td></td>';
      tr.children[0].textContent = end.slice(11, 16);
      tr.children[1].textContent = fmtNum(v.gti_wm2, 0);
      tr.children[2].textContent = fmtNum(v.cloud_pct, 0);
      body.appendChild(tr);
    }
  }

  async function refreshPvNow() {
    const env = await getJson('/api/pv_hourly?hours=24', 4500);
    if (!okEnvelope(env)) { setPill('pv-pill', 'warn', 'offline'); return; }
    const d = env.data || {};
    setPill('pv-pill', 'ok', 'ok');
    const s = d.series || [];
    let total = 0.0;
    let nextKw = null;
    for (let i = 0; i < s.length; i++) {
      const kwh = s[i].pv_kwh_est_simple;
      if (kwh !== null && kwh !== undefined) total += Number(kwh) || 0;
      if (i === 0) nextKw = s[i].pv_kw_est_simple;
    }
    setText('pv24', fmtNum(total, 1));
    setText('pv1', fmtNum(nextKw, 2));
  }

  refreshStatusNow();
  refreshPricesNow();
  refreshRecoNow();
  refreshPvNow();

  setInterval(() => { if (document.visibilityState === 'visible') refreshStatusNow(); }, 5000);
  setInterval(() => { if (document.visibilityState === 'visible') refreshPricesNow(); }, 15 * 60 * 1000);
  setInterval(() => { if (document.visibilityState === 'visible') refreshRecoNow(); }, 15 * 60 * 1000);
  setInterval(() => { if (document.visibilityState === 'visible') refreshPvNow(); }, 30 * 60 * 1000);
</script>

</body>
</html>
"""
    return html.encode("utf-8")


class WebServer:
    def __init__(self, host="0.0.0.0", port=80):
        self._sock = socket.socket()
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass

        bind_errors = []
        bind_ok = False
        for cand_host in (host, "0.0.0.0"):
            try:
                addr = socket.getaddrinfo(cand_host, int(port), 0, socket.SOCK_STREAM)[0][-1]
            except Exception:
                addr = (cand_host, int(port))
            try:
                self._sock.bind(addr)
                bind_ok = True
                break
            except Exception as e:
                bind_errors.append("%s:%s => %r" % (cand_host, port, e))

        if not bind_ok:
            self._sock.close()
            raise RuntimeError("bind failed: " + "; ".join(bind_errors))

        try:
            self._sock.listen(2)
        except TypeError:
            self._sock.listen()
        self._sock.settimeout(0.2)

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass

    def poll_once(self, handlers):
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

            if path == "/" or path == "" or path.startswith("/?"):
                cl.send(_http_response(200, "text/html; charset=utf-8", _html_index()))
                return

            fn = handlers.get(path)
            if fn is None:
                cl.send(_http_response(404, "text/plain; charset=utf-8", b"Not found"))
                return

            payload = fn(query)
            body = json.dumps(payload).encode("utf-8")
            cl.send(_http_response(200, "application/json; charset=utf-8", body))

        except Exception:
            try:
                cl.send(_http_response(500, "text/plain; charset=utf-8", b"Server error"))
            except Exception:
                pass
        finally:
            try:
                cl.close()
            except Exception:
                pass
