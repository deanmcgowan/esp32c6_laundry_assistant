import sys
import time
import json
import ntptime
import updater

from status_led import StatusLED

# Ensure /app/lib is importable
if "/app/lib" not in sys.path:
    sys.path.insert(0, "/app/lib")

from web.server import WebServer  # noqa: E402
from ngenic.ngenic_client import NgenicClient  # noqa: E402
from spotprice.elprisetjustnu import SpotPriceClient  # noqa: E402
from scheduler import compute_recommendations  # noqa: E402

from apiutil import response_envelope, clamp_int  # noqa: E402
from timeutil import pack_time  # noqa: E402

from weather.smhi_snow1g import SmhiSnow1gClient  # noqa: E402
from solar.openmeteo import OpenMeteoSolarClient  # noqa: E402
from weather.metno_locationforecast import MetNoLocationForecastClient  # noqa: E402
from pv import build_pv_hourly_series  # noqa: E402


APP_VERSION = "0.6.0"

# Your site
SITE_LAT = 60.04333
SITE_LON = 17.54466

# Your PV system (Open-Meteo azimuth convention: 0° = south)
PV_KWP = 9.7
PV_TILT_DEG = 20.0
PV_AZIMUTH_DEG = 0.0

SYNC_INTERVAL_MS = 60 * 60 * 1000  # 1 hour


def _r2(x):
    if x is None:
        return None
    try:
        return round(float(x), 2)
    except Exception:
        return None


def load_secrets():
    with open("/secrets.json", "r") as f:
        return json.load(f)


def wifi_up(secrets):
    wlan = updater.connect_wifi(secrets["wifi_ssid"], secrets["wifi_password"], timeout_s=20)
    return wlan.ifconfig()[0]


def sync_time():
    ntptime.settime()  # sets UTC


def main():
    led = StatusLED(pin=8)
    led.solid((0, 10, 0))  # green = app running

    secrets = load_secrets()

    ip = None
    last_ntp_sync_mp = None

    try:
        ip = wifi_up(secrets)
        print("Web UI: http://%s/" % ip)
    except Exception as e:
        print("Wi-Fi failed:", repr(e))

    try:
        sync_time()
        last_ntp_sync_mp = int(time.time())
    except Exception as e:
        print("NTP sync failed:", repr(e))

    updater.mark_boot_success()

    ng = NgenicClient()
    prices = SpotPriceClient(area="SE3")
    prices.load_cache()
    prices.refresh_if_due()

    smhi = SmhiSnow1gClient(
        lat=SITE_LAT,
        lon=SITE_LON,
        parameters=["air_temperature", "wind_speed"],
        timeseries=48,
    )
    smhi.load_cache()
    smhi.refresh_if_due()

    solar = OpenMeteoSolarClient(
        lat=SITE_LAT,
        lon=SITE_LON,
        tilt_deg=PV_TILT_DEG,
        azimuth_deg=PV_AZIMUTH_DEG,
        forecast_hours=48,
    )
    solar.load_cache()
    solar.refresh_if_due()

    # Optional redundancy (requires metno_user_agent in secrets.json)
    metno_ua = secrets.get("metno_user_agent")
    metno = MetNoLocationForecastClient(
        lat=SITE_LAT,
        lon=SITE_LON,
        user_agent=metno_ua,
    )
    metno.load_cache()
    metno.refresh_if_due()

    srv = WebServer(port=80)
    last_sync_ms = time.ticks_ms()

    def get_status(_q):
        now = int(time.time())
        st = ng.get_cached()
        data = {
            "device_time": pack_time(now),
            "ip": ip,
            "last_ntp_sync": pack_time(last_ntp_sync_mp) if last_ntp_sync_mp else None,
            "site": {"lat": SITE_LAT, "lon": SITE_LON},
            "pv": {"kwp": PV_KWP, "tilt_deg": PV_TILT_DEG, "azimuth_deg": PV_AZIMUTH_DEG},
            "ngenic": {
                "import_kW": _r2(st.get("import_kW")),
                "export_kW": _r2(st.get("export_kW")),
                "net_kW": _r2(st.get("net_kW")),
                "age_s": st.get("age_s"),
                "learned_interval_s": _r2(st.get("learned_interval_s")),
                "import_time": st.get("import_time"),
                "export_time": st.get("export_time"),
                "ok": st.get("ok"),
                "last_error": st.get("last_error"),
            },
        }
        return response_envelope(data, app_version=APP_VERSION, now_mp_epoch=now, endpoint="/api/status")

    def get_prices(_q):
        now = int(time.time())
        # Return cache as-is but wrapped consistently (slots still contain internal MP epochs).
        # If you want, we can add a normalizer later; for now, meta carries explicit time formats.
        return response_envelope(prices.get_cached(), app_version=APP_VERSION, now_mp_epoch=now, endpoint="/api/prices")

    def get_reco(_q):
        now = int(time.time())
        reco = compute_recommendations(prices.get_cached(), now)
        return response_envelope(reco, app_version=APP_VERSION, now_mp_epoch=now, endpoint="/api/recommendations")

    def get_weather_hourly(q):
        now = int(time.time())
        hours = clamp_int(q.get("hours"), 1, 72, 24)
        smhi_series = smhi.get_hourly_series(hours=hours, now_mp_epoch=now)
        metno_series = metno.get_hourly_series(hours=hours, now_mp_epoch=now)

        data = {
            "location": {"lat": SITE_LAT, "lon": SITE_LON},
            "hours": hours,
            "primary": {
                "provider": smhi.get_cached().get("provider"),
                "referenceTime": smhi.get_cached().get("referenceTime"),
                "createdTime": smhi.get_cached().get("createdTime"),
                "grid_coordinates": smhi.get_cached().get("grid_coordinates"),
                "ok": smhi.get_cached().get("ok"),
                "last_error": smhi.get_cached().get("last_error"),
                "series": [
                    {"start": pack_time(it["start_mp"]), "end": pack_time(it["end_mp"]), "values": it.get("values")}
                    for it in smhi_series
                ],
            },
            "fallback": {
                "provider": metno.get_cached().get("provider"),
                "ok": metno.get_cached().get("ok"),
                "last_error": metno.get_cached().get("last_error"),
                "series": [
                    {"start": pack_time(it["start_mp"]), "end": pack_time(it["end_mp"]), "values": it.get("values")}
                    for it in metno_series
                ],
            },
            "units": {"t_air_c": "°C", "wind_mps": "m/s", "cloud_pct": "%"},
        }
        return response_envelope(data, app_version=APP_VERSION, now_mp_epoch=now, endpoint="/api/weather/hourly")

    def get_solar_hourly(q):
        now = int(time.time())
        hours = clamp_int(q.get("hours"), 1, 72, 24)
        sol_series = solar.get_hourly_series(hours=hours, now_mp_epoch=now)
        data = {
            "location": {"lat": SITE_LAT, "lon": SITE_LON},
            "hours": hours,
            "provider": solar.get_cached().get("provider"),
            "ok": solar.get_cached().get("ok"),
            "last_error": solar.get_cached().get("last_error"),
            "tilt_deg": PV_TILT_DEG,
            "azimuth_deg": PV_AZIMUTH_DEG,
            "series": [
                {"start": pack_time(it["start_mp"]), "end": pack_time(it["end_mp"]), "values": it.get("values")}
                for it in sol_series
            ],
            "units": {
                "gti_wm2": "W/m²",
                "ghi_wm2": "W/m²",
                "dni_wm2": "W/m²",
                "dhi_wm2": "W/m²",
            },
        }
        return response_envelope(data, app_version=APP_VERSION, now_mp_epoch=now, endpoint="/api/solar/hourly")

    def get_pv_hourly(q):
        now = int(time.time())
        hours = clamp_int(q.get("hours"), 1, 72, 24)
        kwp = q.get("kwp")
        try:
            kwp = float(kwp) if kwp is not None else PV_KWP
        except Exception:
            kwp = PV_KWP

        w_series = smhi.get_hourly_series(hours=hours, now_mp_epoch=now)
        s_series = solar.get_hourly_series(hours=hours, now_mp_epoch=now)

        rows = build_pv_hourly_series(w_series, s_series, kwp=kwp, loss_factor=0.86)

        data = {
            "location": {"lat": SITE_LAT, "lon": SITE_LON},
            "hours": hours,
            "sources": {
                "weather": smhi.get_cached().get("provider"),
                "solar": solar.get_cached().get("provider"),
            },
            "assumptions": {
                "kwp": kwp,
                "loss_factor": 0.86,
                "note": "pv_*_est_simple is a rough estimate from GTI only; temperature effects & inverter clipping not modelled.",
            },
            "series": rows,
            "units": {
                "t_air_c": "°C",
                "wind_mps": "m/s",
                "gti_wm2": "W/m²",
                "pv_kw_est_simple": "kW",
                "pv_kwh_est_simple": "kWh",
            },
        }
        return response_envelope(data, app_version=APP_VERSION, now_mp_epoch=now, endpoint="/api/pv/hourly")

    handlers = {
        "/api/status": get_status,
        "/api/prices": get_prices,
        "/api/recommendations": get_reco,
        "/api/weather/hourly": get_weather_hourly,
        "/api/solar/hourly": get_solar_hourly,
        "/api/pv/hourly": get_pv_hourly,
    }

    try:
        while True:
            ng.refresh_if_due()
            prices.refresh_if_due()
            smhi.refresh_if_due()
            solar.refresh_if_due()
            metno.refresh_if_due()

            if time.ticks_diff(time.ticks_ms(), last_sync_ms) >= SYNC_INTERVAL_MS:
                try:
                    sync_time()
                    last_ntp_sync_mp = int(time.time())
                    last_sync_ms = time.ticks_ms()
                    print("Time re-synchronised (NTP).")
                except Exception as e:
                    print("Hourly NTP sync failed:", repr(e))

            srv.poll_once(handlers)
            time.sleep(0.05)
    finally:
        srv.close()


main()