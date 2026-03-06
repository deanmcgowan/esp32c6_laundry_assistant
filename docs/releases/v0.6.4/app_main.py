import sys
import time
import json
import socket
import ntptime
import updater

# Ensure /app/lib is importable
if "/app/lib" not in sys.path:
    sys.path.insert(0, "/app/lib")

try:
    from web.server import WebServer  # noqa: E402
    _WEB_IMPORT_ERROR = None
except Exception as e:
    WebServer = None
    _WEB_IMPORT_ERROR = repr(e)
from ngenic.ngenic_client import NgenicClient  # noqa: E402
from spotprice.elprisetjustnu import SpotPriceClient  # noqa: E402
from scheduler import compute_recommendations  # noqa: E402

from apiutil import response_envelope, clamp_int  # noqa: E402
from timeutil import pack_time  # noqa: E402

from weather.smhi_snow1g import SmhiSnow1gClient  # noqa: E402
from solar.openmeteo import OpenMeteoSolarClient  # noqa: E402
from weather.metno_locationforecast import MetNoLocationForecastClient  # noqa: E402
from pv import build_pv_hourly_series  # noqa: E402


APP_VERSION = "0.6.4"

# Single-site installation:
SITE_LAT = 60.04333
SITE_LON = 17.54466

# PV geometry:
# Open-Meteo azimuth convention: 0° = South, -90° = East, 90° = West, ±180° = North
PV_KWP = 9.7
PV_TILT_DEG = 20.0
PV_AZIMUTH_DEG = 0.0  # due south

SYNC_INTERVAL_MS = 60 * 60 * 1000  # 1 hour


def _r2(x):
    if x is None:
        return None
    try:
        return round(float(x), 2)
    except Exception:
        return None


class _NoopNgenicClient:
    def __init__(self, reason):
        self._reason = reason
        self._cache = {
            "import_kW": None,
            "export_kW": None,
            "net_kW": None,
            "age_s": None,
            "learned_interval_s": None,
            "ok": False,
            "import_time": None,
            "export_time": None,
            "updated_epoch": None,
            "ngenic_time_changed_epoch": None,
            "last_error": reason,
        }

    def get_cached(self):
        return dict(self._cache)

    def refresh_if_due(self, force=False):
        return self.get_cached()


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


class _FallbackWebServer:
    def __init__(self, host="0.0.0.0", port=80, reason=""):
        self._reason = reason or "fallback server"
        self._sock = socket.socket()
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass

        addr = None
        try:
            addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
        except Exception:
            addr = (host, port)

        self._sock.bind(addr)
        self._sock.listen(1)
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
            req = cl.recv(512)
            line = req.split(b"\r\n", 1)[0].decode("utf-8", "ignore") if req else ""
            parts = line.split(" ")
            path = parts[1] if len(parts) > 1 else "/"

            if path.startswith("/api/status") and "/api/status" in handlers:
                payload = handlers["/api/status"]({})
                body = json.dumps(payload).encode("utf-8")
                cl.send(_http_response(200, "application/json; charset=utf-8", body))
                return

            body = (
                "<html><body><h1>ESP32-C6 Energy Hub</h1>"
                "<p>Fallback web server active.</p>"
                "<p class='mono'>%s</p>"
                "</body></html>" % self._reason
            ).encode("utf-8")
            cl.send(_http_response(200, "text/html; charset=utf-8", body))
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


def _start_server():
    errors = []
    if WebServer is not None:
        try:
            return WebServer(port=80), 80
        except Exception as e:
            errors.append("WebServer(80): " + repr(e))
            print("WebServer init failed:", repr(e))
    else:
        errors.append("web import: " + str(_WEB_IMPORT_ERROR))
        print("Web server import failed:", _WEB_IMPORT_ERROR)

    for p in (80, 8080):
        try:
            reason = "; ".join(errors) if errors else "fallback requested"
            return _FallbackWebServer(port=p, reason=reason), p
        except Exception as e:
            errors.append("Fallback(%d): %r" % (p, e))

    raise RuntimeError("Cannot start HTTP server: " + "; ".join(errors))


def load_secrets():
    with open("/secrets.json", "r") as f:
        return json.load(f)


def wifi_up():
    sec = load_secrets()
    wlan = updater.connect_wifi(sec["wifi_ssid"], sec["wifi_password"], timeout_s=20)
    return wlan.ifconfig()[0]


def sync_time():
    # Keep 0.5.1 behaviour: ensure Wi-Fi before NTP.
    wifi_up()
    ntptime.settime()  # sets UTC (device epoch)


def _norm_ngenic(st):
    updated = st.get("updated_epoch")
    changed = st.get("ngenic_time_changed_epoch")
    return {
        "import_kW": _r2(st.get("import_kW")),
        "export_kW": _r2(st.get("export_kW")),
        "net_kW": _r2(st.get("net_kW")),
        "age_s": st.get("age_s"),
        "learned_interval_s": _r2(st.get("learned_interval_s")),
        "ok": bool(st.get("ok")),
        "import_time": st.get("import_time"),
        "export_time": st.get("export_time"),
        "updated": pack_time(updated) if updated is not None else None,
        "upstream_changed": pack_time(changed) if changed is not None else None,
    }


def _norm_prices(cache, now):
    out = {
        "area": cache.get("area"),
        "today_ymd": cache.get("today_ymd"),
        "tomorrow_ymd": cache.get("tomorrow_ymd"),
        "tomorrow_status": cache.get("tomorrow_status"),
        "cache_age_s": cache.get("age_s"),
        "fetched": pack_time(cache["fetched_epoch"]) if cache.get("fetched_epoch") is not None else None,
        "current": {"sek_per_kwh": None, "slot": None},
        "days": cache.get("days") or {},
    }

    days = out["days"]
    cur_slot = None
    cur_price = None
    try:
        for _ymd, slots in days.items():
            if not isinstance(slots, list):
                continue
            for s in slots:
                try:
                    a = s.get("start_utc")
                    b = s.get("end_utc")
                    p = s.get("sek_per_kwh")
                    if a is None or b is None or p is None:
                        continue
                    if int(a) <= int(now) < int(b):
                        cur_slot = {"start": pack_time(int(a)), "end": pack_time(int(b))}
                        cur_price = p
                        raise StopIteration()
                except StopIteration:
                    raise
                except Exception:
                    pass
    except StopIteration:
        pass

    out["current"]["sek_per_kwh"] = cur_price
    out["current"]["slot"] = cur_slot
    return out


def main():
    ip = None
    http_port = None
    last_ntp_sync_epoch = None

    try:
        ip = wifi_up()
        print("Energy Hub UI: http://%s/" % ip)
    except Exception as e:
        print("Wi-Fi failed:", repr(e))

    try:
        sync_time()
        last_ntp_sync_epoch = int(time.time())
    except Exception as e:
        print("NTP sync failed:", repr(e))

    secrets = {}
    try:
        secrets = load_secrets()
    except Exception:
        secrets = {}

    try:
        ng = NgenicClient()
    except Exception as e:
        reason = "ngenic disabled: " + repr(e)
        print(reason)
        ng = _NoopNgenicClient(reason)

    prices = SpotPriceClient(area="SE3")
    prices.load_cache()
    try:
        prices.refresh_if_due()
    except Exception as e:
        print("Spot price startup refresh failed:", repr(e))

    smhi = SmhiSnow1gClient(
        lat=SITE_LAT,
        lon=SITE_LON,
        parameters=["air_temperature", "wind_speed"],
        timeseries=48,
    )
    smhi.load_cache()
    try:
        smhi.refresh_if_due()
    except Exception as e:
        print("SMHI startup refresh failed:", repr(e))

    solar = OpenMeteoSolarClient(
        lat=SITE_LAT,
        lon=SITE_LON,
        tilt_deg=PV_TILT_DEG,
        azimuth_deg=PV_AZIMUTH_DEG,
        forecast_hours=36,
    )
    solar.load_cache()
    try:
        solar.refresh_if_due()
    except Exception as e:
        print("Solar startup refresh failed:", repr(e))

    metno = MetNoLocationForecastClient(
        lat=SITE_LAT,
        lon=SITE_LON,
        user_agent=secrets.get("metno_user_agent"),
    )
    metno.load_cache()
    try:
        metno.refresh_if_due()
    except Exception as e:
        print("MET Norway startup refresh failed:", repr(e))

    srv, http_port = _start_server()
    print("HTTP server listening on port", http_port)
    if ip:
        if int(http_port) == 80:
            print("Energy Hub UI: http://%s/" % ip)
        else:
            print("Energy Hub UI: http://%s:%d/" % (ip, int(http_port)))
    # Only mark boot successful after core services are initialised.
    updater.mark_boot_success()
    last_sync_ms = time.ticks_ms()

    def api_status(_q):
        now = int(time.time())
        data = {
            "device_time": pack_time(now),
            "ip": ip,
            "http_port": http_port,
            "last_ntp_sync": pack_time(last_ntp_sync_epoch) if last_ntp_sync_epoch else None,
            "site": {"lat": SITE_LAT, "lon": SITE_LON},
            "pv": {"kwp": PV_KWP, "tilt_deg": PV_TILT_DEG, "azimuth_deg": PV_AZIMUTH_DEG},
            "ngenic": _norm_ngenic(ng.get_cached()),
        }
        return response_envelope(data, app_version=APP_VERSION, now_epoch=now, endpoint="/api/status")

    def api_prices(_q):
        now = int(time.time())
        data = _norm_prices(prices.get_cached(), now)
        return response_envelope(data, app_version=APP_VERSION, now_epoch=now, endpoint="/api/prices")

    def api_recommendations(_q):
        now = int(time.time())
        reco = compute_recommendations(prices.get_cached(), now)
        return response_envelope(reco, app_version=APP_VERSION, now_epoch=now, endpoint="/api/recommendations")

    def api_weather_hourly(q):
        now = int(time.time())
        hours = clamp_int(q.get("hours"), 1, 72, 24)
        smhi_series = smhi.get_hourly_series(hours=hours, utc_epoch=now)
        metno_series = metno.get_hourly_series(hours=hours, utc_epoch=now)

        data = {
            "location": {"lat": SITE_LAT, "lon": SITE_LON},
            "hours": hours,
            "primary": {
                "provider": smhi.get_cached().get("provider"),
                "referenceTime": smhi.get_cached().get("referenceTime"),
                "createdTime": smhi.get_cached().get("createdTime"),
                "ok": smhi.get_cached().get("ok"),
                "series": [
                    {"start": pack_time(it["start_epoch"]), "end": pack_time(it["end_epoch"]), "values": it.get("values") or {}}
                    for it in smhi_series
                ],
            },
            "fallback": {
                "provider": metno.get_cached().get("provider"),
                "ok": metno.get_cached().get("ok"),
                "series": [
                    {"start": pack_time(it["start_epoch"]), "end": pack_time(it["end_epoch"]), "values": it.get("values") or {}}
                    for it in metno_series
                ],
            },
            "units": {"t_air_c": "°C", "wind_mps": "m/s", "cloud_pct": "%"},
        }
        return response_envelope(data, app_version=APP_VERSION, now_epoch=now, endpoint="/api/weather_hourly")

    def api_solar_hourly(q):
        now = int(time.time())
        hours = clamp_int(q.get("hours"), 1, 72, 24)
        sol_series = solar.get_hourly_series(hours=hours, utc_epoch=now)

        data = {
            "location": {"lat": SITE_LAT, "lon": SITE_LON},
            "hours": hours,
            "provider": solar.get_cached().get("provider"),
            "ok": solar.get_cached().get("ok"),
            "tilt_deg": PV_TILT_DEG,
            "azimuth_deg": PV_AZIMUTH_DEG,
            "series": [
                {"start": pack_time(it["start_epoch"]), "end": pack_time(it["end_epoch"]), "values": it.get("values") or {}}
                for it in sol_series
            ],
            "units": {"gti_wm2": "W/m²", "ghi_wm2": "W/m²", "dni_wm2": "W/m²", "dhi_wm2": "W/m²"},
        }
        return response_envelope(data, app_version=APP_VERSION, now_epoch=now, endpoint="/api/solar_hourly")

    def api_pv_hourly(q):
        now = int(time.time())
        hours = clamp_int(q.get("hours"), 1, 72, 24)

        kwp = q.get("kwp")
        try:
            kwp = float(kwp) if kwp is not None else PV_KWP
        except Exception:
            kwp = PV_KWP

        rows = build_pv_hourly_series(
            smhi.get_hourly_series(hours=hours, utc_epoch=now),
            solar.get_hourly_series(hours=hours, utc_epoch=now),
            kwp=kwp,
            loss_factor=0.86,
        )

        data = {
            "location": {"lat": SITE_LAT, "lon": SITE_LON},
            "hours": hours,
            "assumptions": {"kwp": kwp, "loss_factor": 0.86},
            "series": rows,
            "units": {
                "t_air_c": "°C",
                "wind_mps": "m/s",
                "gti_wm2": "W/m²",
                "pv_kw_est_simple": "kW",
                "pv_kwh_est_simple": "kWh",
            },
        }
        return response_envelope(data, app_version=APP_VERSION, now_epoch=now, endpoint="/api/pv_hourly")

    handlers = {
        "/api/status": api_status,
        "/api/prices": api_prices,
        "/api/recommendations": api_recommendations,
        "/api/weather_hourly": api_weather_hourly,
        "/api/solar_hourly": api_solar_hourly,
        "/api/pv_hourly": api_pv_hourly,
    }

    try:
        while True:
            # Prioritise serving the UI even if upstream refreshes are slow.
            srv.poll_once(handlers)

            try:
                ng.refresh_if_due()
            except Exception:
                pass

            try:
                prices.refresh_if_due()
            except Exception:
                pass

            try:
                smhi.refresh_if_due()
            except Exception:
                pass

            try:
                solar.refresh_if_due()
            except Exception:
                pass

            try:
                metno.refresh_if_due()
            except Exception:
                pass

            if time.ticks_diff(time.ticks_ms(), last_sync_ms) >= SYNC_INTERVAL_MS:
                try:
                    sync_time()
                    last_ntp_sync_epoch = int(time.time())
                    last_sync_ms = time.ticks_ms()
                    print("Time re-synchronised (NTP).")
                except Exception:
                    pass

            time.sleep(0.05)
    finally:
        srv.close()


main()

