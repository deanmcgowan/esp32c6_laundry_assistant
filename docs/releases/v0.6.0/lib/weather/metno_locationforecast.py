import time
import json
import os
import urequests

from timeutil import parse_iso8601_to_utc_mp_epoch


class MetNoLocationForecastClient:
    """
    MET Norway Locationforecast/2.0 compact (fallback provider).
    Requires a good User-Agent (MET enforces this).
    """

    def __init__(
        self,
        lat,
        lon,
        user_agent,
        cache_path="/data/weather_metno_locationforecast.json",
    ):
        self.lat = float(lat)
        self.lon = float(lon)
        self.user_agent = user_agent
        self.cache_path = cache_path

        self._cache = {
            "provider": "metno_locationforecast_2.0_compact",
            "lat": self.lat,
            "lon": self.lon,
            "fetched_mp_epoch": None,
            "next_fetch_mp_epoch": 0,
            "ok": False,
            "last_error": None,
            "series": [],  # normalized as [{start_mp,end_mp,values:{...}}]
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
        return (
            "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=%s&lon=%s"
            % (self.lat, self.lon)
        )

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

        if not self.user_agent:
            self._cache["ok"] = False
            self._cache["last_error"] = "metno disabled: missing user_agent"
            return self.get_cached()

        if now < int(self._cache.get("next_fetch_mp_epoch", 0)):
            return self.get_cached()

        url = self._url()
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }

        try:
            r = urequests.get(url, headers=headers)
            try:
                if r.status_code != 200:
                    raise Exception("MET Norway HTTP %d" % r.status_code)
                payload = r.json()
            finally:
                r.close()

            props = (payload.get("properties") or {})
            timeseries = props.get("timeseries") or []

            series = []
            # For the first ~48h, met.no provides hourly points.
            # We'll treat each timestamp as an "instant" valid at that time and create
            # a 1h bucket [t, t+3600) for consistency with other endpoints.
            for it in timeseries[:72]:
                t_iso = it.get("time")
                t_mp = parse_iso8601_to_utc_mp_epoch(t_iso)
                if t_mp is None:
                    continue

                details = (((it.get("data") or {}).get("instant") or {}).get("details") or {})
                values = {}
                if "air_temperature" in details:
                    values["t_air_c"] = details.get("air_temperature")
                if "wind_speed" in details:
                    values["wind_mps"] = details.get("wind_speed")
                if "cloud_area_fraction" in details:
                    values["cloud_pct"] = details.get("cloud_area_fraction")

                series.append(
                    {
                        "start_mp": int(t_mp),
                        "end_mp": int(t_mp) + 3600,
                        "values": values,
                    }
                )

            self._cache.update(
                {
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

        out.sort(key=lambda x: int(x.get("start_mp", 0)))
        return out[:hrs]