import time
import json
import os
import urequests

from timeutil import parse_iso8601_to_utc_epoch


class OpenMeteoSolarClient:
    """
    Open-Meteo hourly solar forecast.
    We request global_tilted_irradiance using your panel geometry.
    """

    def __init__(
        self,
        lat,
        lon,
        tilt_deg,
        azimuth_deg,
        cache_path="/data/solar_openmeteo.json",
        forecast_hours=36,
        models=None,
    ):
        self.lat = float(lat)
        self.lon = float(lon)
        self.tilt = float(tilt_deg)
        self.azimuth = float(azimuth_deg)
        self.cache_path = cache_path
        self.forecast_hours = int(forecast_hours)
        self.models = models

        self._cache = {
            "provider": "open_meteo",
            "lat": self.lat,
            "lon": self.lon,
            "tilt_deg": self.tilt,
            "azimuth_deg": self.azimuth,
            "fetched_epoch": None,
            "next_fetch_epoch": 0,
            "ok": False,
            "last_error": None,
            "series": [],  # [{start_epoch,end_epoch,values:{...}}]
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
        fetched = out.get("fetched_epoch")
        if fetched is not None:
            out["age_s"] = int(max(0, time.time() - int(fetched)))
        else:
            out["age_s"] = None
        return out

    def refresh_if_due(self, utc_epoch=None, min_interval_s=3600):
        now = int(utc_epoch if utc_epoch is not None else time.time())

        if now < int(self._cache.get("next_fetch_epoch", 0)):
            return self.get_cached()

        headers = {
            "Accept": "application/json",
            "User-Agent": "esp32c6_energy_hub/0.6.1 (Open-Meteo solar)",
        }

        try:
            r = urequests.get(self._url(), headers=headers)
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
            cloud = hourly.get("cloud_cover") or []

            series = []
            n = len(times)
            for i in range(n):
                end_iso = times[i]
                end_epoch = parse_iso8601_to_utc_epoch(end_iso)
                if end_epoch is None:
                    continue

                # Treat each radiation value as the mean over the preceding hour:
                start_epoch = int(end_epoch) - 3600

                values = {
                    "gti_wm2": gti[i] if i < len(gti) else None,
                    "ghi_wm2": ghi[i] if i < len(ghi) else None,
                    "dni_wm2": dni[i] if i < len(dni) else None,
                    "dhi_wm2": dhi[i] if i < len(dhi) else None,
                    "cloud_pct": cloud[i] if i < len(cloud) else None,
                }

                series.append(
                    {"start_epoch": int(start_epoch), "end_epoch": int(end_epoch), "values": values}
                )

            self._cache.update(
                {
                    "fetched_epoch": now,
                    "ok": True,
                    "last_error": None,
                    "series": series,
                    "next_fetch_epoch": now + int(min_interval_s),
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
            self._cache["next_fetch_epoch"] = now + 20 * 60
            try:
                self._save_cache()
            except Exception:
                pass
            return self.get_cached()

    def get_hourly_series(self, hours=24, utc_epoch=None):
        now = int(utc_epoch if utc_epoch is not None else time.time())
        hrs = int(hours)

        out = []
        for it in (self._cache.get("series") or []):
            try:
                if int(it.get("end_epoch")) >= (now - 1800):
                    out.append(it)
            except Exception:
                pass

        out.sort(key=lambda x: int(x.get("end_epoch", 0)))
        return out[:hrs]