import json
import time
import os

import urequests

from timeutil import (
    utc_to_stockholm_tuple,
    stockholm_today_tomorrow_ymd,
    parse_iso8601_to_utc_epoch,
)


class SpotPriceClient:
    """
    Fetches spot prices from elprisetjustnu and caches only:
      - today (Europe/Stockholm date)
      - tomorrow (when available)
    Cache is stored outside /app so it survives OTA swaps: /data/spotprices_SE3.json

    Behaviour:
      - today is always fetched if missing
      - tomorrow is only attempted after ~13:05 local time
      - cache is trimmed to (today, tomorrow) every time, so it never grows unbounded
    """

    def __init__(self, area="SE3", cache_path=None):
        self.area = area
        self.cache_path = cache_path or ("/data/spotprices_%s.json" % area)

        self._cache = {
            "area": area,
            "fetched_epoch": None,
            "age_s": None,
            "days": {},          # {"YYYY-MM-DD": [slots...]}
            "last_error": None,
            "next_fetch_epoch": 0,
        }

    def load_cache(self):
        try:
            with open(self.cache_path, "r") as f:
                self._cache = json.load(f)
        except OSError:
            pass
        return self.get_cached()

    def _ensure_data_dir(self):
        try:
            os.mkdir("/data")
        except OSError:
            pass

    def _save_cache(self):
        self._ensure_data_dir()
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f)

    def _trim_days(self, today_ymd, tomorrow_ymd):
        days = self._cache.get("days", {})
        keep = {}
        if today_ymd in days:
            keep[today_ymd] = days[today_ymd]
        if tomorrow_ymd in days:
            keep[tomorrow_ymd] = days[tomorrow_ymd]
        self._cache["days"] = keep

    def get_cached(self):
        out = dict(self._cache)
        if out.get("fetched_epoch") is not None:
            out["age_s"] = int(max(0, time.time() - out["fetched_epoch"]))
        else:
            out["age_s"] = None
        return out

    def _url_for_local_date(self, ymd):
        # ymd: YYYY-MM-DD
        year = ymd[0:4]
        mmdd = ymd[5:7] + "-" + ymd[8:10]
        return "https://www.elprisetjustnu.se/api/v1/prices/%s/%s_%s.json" % (year, mmdd, self.area)

    def _fetch_day(self, ymd):
        url = self._url_for_local_date(ymd)
        r = urequests.get(url)
        try:
            if r.status_code != 200:
                raise RuntimeError("HTTP %d" % r.status_code)

            arr = r.json()
            slots = []
            for it in arr:
                ts = it.get("time_start")
                te = it.get("time_end")
                slots.append({
                    "start_utc": parse_iso8601_to_utc_epoch(ts),
                    "end_utc": parse_iso8601_to_utc_epoch(te),
                    "sek_per_kwh": it.get("SEK_per_kWh"),
                    "eur_per_kwh": it.get("EUR_per_kWh"),
                    "time_start": ts,
                    "time_end": te,
                })
            return slots
        finally:
            r.close()

    def refresh_if_due(self, utc_epoch=None):
        now = utc_epoch if utc_epoch is not None else time.time()

        # Backoff window
        if now < self._cache.get("next_fetch_epoch", 0):
            return self.get_cached()

        today, tomorrow = stockholm_today_tomorrow_ymd(now)

        # Trim cache aggressively so it never grows
        self._trim_days(today, tomorrow)

        need_today = today not in self._cache["days"]

        t_loc = utc_to_stockholm_tuple(now)
        after_1305 = (t_loc[3] > 13) or (t_loc[3] == 13 and t_loc[4] >= 5)
        need_tomorrow = after_1305 and (tomorrow not in self._cache["days"])

        if not need_today and not need_tomorrow:
            return self.get_cached()

        today_ok = False

        try:
            if need_today:
                self._cache["days"][today] = self._fetch_day(today)
            today_ok = True
        except Exception as e:
            # If today fails, that's a real problem.
            self._cache["last_error"] = "today fetch failed: " + repr(e)
            self._cache["next_fetch_epoch"] = now + 10 * 60  # retry in 10 minutes
            self._trim_days(today, tomorrow)
            try:
                self._save_cache()
            except Exception:
                pass
            return self.get_cached()

        # Tomorrow is optional; a 404 should not poison the whole cache.
        if need_tomorrow:
            try:
                self._cache["days"][tomorrow] = self._fetch_day(tomorrow)
            except Exception as e:
                self._cache["last_error"] = "tomorrow fetch failed: " + repr(e)
                self._cache["next_fetch_epoch"] = now + 30 * 60  # retry tomorrow in 30 minutes
            else:
                # Tomorrow fetched OK
                self._cache["last_error"] = None
                self._cache["next_fetch_epoch"] = 0
        else:
            # Nothing to do for tomorrow right now
            self._cache["last_error"] = None
            self._cache["next_fetch_epoch"] = 0

        if today_ok:
            self._cache["fetched_epoch"] = now

        self._trim_days(today, tomorrow)
        try:
            self._save_cache()
        except Exception:
            pass

        return self.get_cached()