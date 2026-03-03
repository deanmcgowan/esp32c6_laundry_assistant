import time
import json
import os
import urequests

from timeutil import parse_iso8601_to_utc_mp_epoch


class SmhiSnow1gClient:
    """
    SMHI Meteorological Forecast API (SNOW1g v1), point endpoint.

    Stores a normalized hourly series with explicit interval start/end (MP epoch).
    """

    def __init__(
        self,
        lat,
        lon,
        parameters=None,
        timeseries=36,
        cache_path="/data/weather_smhi_snow1g.json",
    ):
        self.lat = float(lat)
        self.lon = float(lon)
        self.parameters = parameters or ["air_temperature", "wind_speed"]
        self.timeseries = int(timeseries)
        self.cache_path = cache_path

        self._cache = {
            "provider": "smhi_snow1g_v1",
            "lat": self.lat,
            "lon": self.lon,
            "grid_coordinates": None,
            "createdTime": None,
            "referenceTime": None,
            "fetched_mp_epoch": None,
            "next_fetch_mp_epoch": 0,
            "age_s": None,
            "ok": False,
            "last_error": None,
            "series": [],  # [{start_mp, end_mp, values:{...}}]
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
        # Example endpoint (point):
        # https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/{lon}/lat/{lat}/data.json
        params = ",".join(self.parameters)
        return (
            "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/"
            "geotype/point/lon/%s/lat/%s/data.json?timeseries=%d&parameters=%s"
            % (self.lon, self.lat, self.timeseries, params)
        )

    def get_cached(self):
        out = dict(self._cache)
        fetched = out.get("fetched_mp_epoch")
        if fetched is not None:
            out["age_s"] = int(max(0, time.time() - fetched))
        else:
            out["age_s"] = None
        return out

    def refresh_if_due(self, now_mp_epoch=None, min_interval_s=1800):
        now = int(now_mp_epoch if now_mp_epoch is not None else time.time())

        if now < int(self._cache.get("next_fetch_mp_epoch", 0)):
            return self.get_cached()

        fetched = self._cache.get("fetched_mp_epoch")
        if fetched is not None and (now - int(fetched)) < int(min_interval_s):
            self._cache["next_fetch_mp_epoch"] = int(fetched) + int(min_interval_s)
            return self.get_cached()

        url = self._url()
        headers = {
            "Accept": "application/json",
            "User-Agent": "esp32c6_laundry_assistant/0.6.0 (SMHI SNOW1g client)",
        }

        try:
            r = urequests.get(url, headers=headers)
            try:
                if r.status_code != 200:
                    raise Exception("SMHI HTTP %d" % r.status_code)
                payload = r.json()
            finally:
                r.close()

            created = payload.get("createdTime")
            ref = payload.get("referenceTime")
            geom = payload.get("geometry") or {}
            coords = None
            if geom.get("type") == "Point":
                coords = geom.get("coordinates")

            series = []
            ts = payload.get("timeSeries") or []
            for it in ts:
                end_iso = it.get("time")
                start_iso = it.get("intervalParametersStartTime")
                data = (it.get("data") or {})

                start_mp = parse_iso8601_to_utc_mp_epoch(start_iso)
                end_mp = parse_iso8601_to_utc_mp_epoch(end_iso)
                if start_mp is None or end_mp is None:
                    continue
                if end_mp <= start_mp:
                    continue

                values = {}
                # Keep naming consistent in our internal API
                if "air_temperature" in data:
                    values["t_air_c"] = data.get("air_temperature")
                if "wind_speed" in data:
                    values["wind_mps"] = data.get("wind_speed")

                series.append({"start_mp": start_mp, "end_mp": end_mp, "values": values})

            self._cache.update(
                {
                    "grid_coordinates": coords,
                    "createdTime": created,
                    "referenceTime": ref,
                    "fetched_mp_epoch": now,
                    "ok": True,
                    "last_error": None,
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
            # backoff a bit
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