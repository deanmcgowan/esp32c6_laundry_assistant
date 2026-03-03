import time
import json
import os
import urequests

from timeutil import parse_iso8601_to_utc_mp_epoch


class OpenMeteoSolarClient:
    """
    Open-Meteo forecast API for solar radiation.
    We use global_tilted_irradiance (GTI) to avoid doing PV transposition math on-device.

    Notes from Open-Meteo docs:
    - Radiation hourly variables are typically "preceding hour mean".
    - Azimuth convention: 0° = South, -90° = East, 90° = West, ±180° = North.
    """

    def __init__(
        self,
        lat,
        lon,
        tilt_deg,
        azimuth_deg,
        cache_path="/data/solar_openmeteo.json",
        forecast_hours=48,
        models=None,
    ):
        self.lat = float(lat)
        self.lon = float(lon)
        self.tilt = float(tilt_deg)
        self.azimuth = float(azimuth_deg)
        self.cache_path = cache_path
        self.forecast_hours = int(forecast_hours)
        self.models = models  # optional: comma-separated list per Open-Meteo docs

        self._cache = {
            "provider": "open_meteo",
            "lat": self.lat,
            "lon": self.lon,
            "tilt_deg": self.tilt,
            "azimuth_deg": self.azimuth,
            "fetched_mp_epoch": None,
            "next_fetch_mp_epoch": 0,
            "ok": False,
            "last_error": None,
            "utc_offset_seconds": None,
            "timezone": None,
            "series": [],  # [{start_mp,end_mp,values:{...}}]
        }

    def _ensure_data_dir(self):
        try:
            os.mkdir("/data")
        except OSError:
            pass

    def load_cache(self):
        try:
            with open(self.cache_path, "r") as f:
                self._cache = json.load(f)
        except OSError:
            pass
        return self.get_cached()

    def _save_cache(self):
        self._ensure_data_dir()
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f)

    def _url(self):
        hourly = ",".join(
            [
                "global_tilted_irradiance",
                "shortwave_radiation",
                "direct_normal_irradiance",
                "diffuse_radiation",
                "temperature_2m",
                "wind_speed_10m",
                "cloud_cover",
            ]
        )
        base = (
            "https://api.open-meteo.com/v1/forecast?"
            "latitude=%s&longitude=%s"
            "&hourly=%s"
            "&forecast_hours=%d"
            "&timezone=GMT"
            "&timeformat=iso8601"
            "&tilt=%s&azimuth=%s"
            % (self.lat, self.lon, hourly, self.forecast_hours, self.tilt, self.azimuth)
        )
        if self.models:
            base += "&models=%s" % self.models
        return base

    def get_cached(self):
        out = dict(self._cache)
        fetched = out.get("fetched_mp_epoch")
        if fetched is not None:
            out["age_s"] = int(max(0, time.time() - int(fetched)))
        else:
            out["age_s"] = None
        return out

    def refresh_if_due(self, now_mp_epoch=None, min_interval_s=1800):
        now = int(now_mp_epoch if now_mp_epoch is not None else time.time())

        if now < int(self._cache.get("next_fetch_mp_epoch", 0)):
            return self.get_cached()

        url = self._url()
        headers = {
            "Accept": "application/json",
            "User-Agent": "esp32c6_laundry_assistant/0.6.0 (Open-Meteo solar client)",
        }

        try:
            r = urequests.get(url, headers=headers)
            try:
                if r.status_code != 200:
                    raise Exception("Open-Meteo HTTP %d" % r.status_code)
                payload = r.json()
            finally:
                r.close()

            hourly = payload.get("hourly") or {}
            times = hourly.get("time") or []

            gti = hourly.get("global_tilted_irradiance") or []
            ghi = hourly.get("shortwave_radiation") or []
            dni = hourly.get("direct_normal_irradiance") or []
            dhi = hourly.get("diffuse_radiation") or []
            t2m = hourly.get("temperature_2m") or []
            w10 = hourly.get("wind_speed_10m") or []
            cloud = hourly.get("cloud_cover") or []

            series = []
            n = len(times)
            for i in range(n):
                end_iso = times[i]
                end_mp = parse_iso8601_to_utc_mp_epoch(end_iso)
                if end_mp is None:
                    continue
                start_mp = int(end_mp) - 3600

                values = {
                    "gti_wm2": gti[i] if i < len(gti) else None,
                    "ghi_wm2": ghi[i] if i < len(ghi) else None,
                    "dni_wm2": dni[i] if i < len(dni) else None,
                    "dhi_wm2": dhi[i] if i < len(dhi) else None,
                    "t_air_c": t2m[i] if i < len(t2m) else None,
                    "wind_mps": w10[i] if i < len(w10) else None,
                    "cloud_pct": cloud[i] if i < len(cloud) else None,
                }

                series.append({"start_mp": start_mp, "end_mp": int(end_mp), "values": values})

            self._cache.update(
                {
                    "fetched_mp_epoch": now,
                    "ok": True,
                    "last_error": None,
                    "utc_offset_seconds": payload.get("utc_offset_seconds"),
                    "timezone": payload.get("timezone"),
                    "series": series,
                    "next_fetch_mp_epoch": now + int(min_interval_s),
                }
            )

            try:
                self._save_cache()
            except Exception:
                pass

            return self.get_cached()

        except Exception as e:
            self._cache["ok"] = False
            self._cache["last_error"] = repr(e)
            self._cache["next_fetch_mp_epoch"] = now + 10 * 60
            try:
                self._save_cache()
            except Exception:
                pass
            return self.get_cached()

    def get_hourly_series(self, hours=24, now_mp_epoch=None):
        now = int(now_mp_epoch if now_mp_epoch is not None else time.time())
        hrs = int(hours)

        out = []
        for it in (self._cache.get("series") or []):
            try:
                if int(it.get("end_mp")) >= (now - 1800):
                    out.append(it)
            except Exception:
                pass

        out.sort(key=lambda x: int(x.get("end_mp", 0)))
        return out[:hrs]