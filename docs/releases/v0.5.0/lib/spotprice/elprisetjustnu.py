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

    Cache location (survives OTA swaps):
      /data/spotprices_<AREA>.json

    Changes vs v0.4.1:
      - Tomorrow HTTP 404 is treated as NOT READY (normal), not an error.
      - fetched_epoch is always kept meaningful once today's prices exist.
      - Cache trimmed to (today, tomorrow) every time (bounded file size).
    """

    def __init__(self, area="SE3", cache_path=None):
        self.area = area
        self.cache_path = cache_path or ("/data/spotprices_%s.json" % area)

        self._cache = {
            "area": area,
            "fetched_epoch": None,
            "age_s": None,
            "days": {},  # {"YYYY-MM-DD": [slots...]}
            "last_error": None,
            "next_fetch_epoch": 0,

            # extra helpful fields for UI/debug
            "today_ymd": None,
            "tomorrow_ymd": None,
            "tomorrow_status": None,  # ok | not_ready | skipped | error
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
        year = ymd[0:4]
        mmdd = ymd[5:7] + "-" + ymd[8:10]
        return "https://www.elprisetjustnu.se/api/v1/prices/%s/%s_%s.json" % (year, mmdd, self.area)

    def _fetch_day(self, ymd):
        """
        Returns: (status_code:int, slots:list|None)
        """
        url = self._url_for_local_date(ymd)
        r = urequests.get(url)
        try:
            if r.status_code != 200:
                return r.status_code, None

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
            return 200, slots
        finally:
            r.close()

    def refresh_if_due(self, utc_epoch=None):
        now = utc_epoch if utc_epoch is not None else time.time()

        # Backoff window
        if now < self._cache.get("next_fetch_epoch", 0):
            return self.get_cached()

        today, tomorrow = stockholm_today_tomorrow_ymd(now)
        self._cache["today_ymd"] = today
        self._cache["tomorrow_ymd"] = tomorrow

        # Always keep cache bounded
        self._trim_days(today, tomorrow)

        need_today = today not in self._cache["days"]

        t_loc = utc_to_stockholm_tuple(now)
        after_1305 = (t_loc[3] > 13) or (t_loc[3] == 13 and t_loc[4] >= 5)
        need_tomorrow = after_1305 and (tomorrow not in self._cache["days"])

        # If today is already present, keep fetched_epoch meaningful
        if (not need_today) and (self._cache.get("fetched_epoch") is None):
            self._cache["fetched_epoch"] = now

        # Nothing to do
        if not need_today and not need_tomorrow:
            self._cache["tomorrow_status"] = "skipped"
            self._cache["last_error"] = None
            return self.get_cached()

        # --- Fetch today (required) ---
        if need_today:
            code, slots = self._fetch_day(today)
            if code != 200:
                self._cache["last_error"] = "today fetch failed: HTTP %d" % code
                self._cache["next_fetch_epoch"] = now + 10 * 60
                self._cache["tomorrow_status"] = "skipped"
                self._trim_days(today, tomorrow)
                try:
                    self._save_cache()
                except Exception:
                    pass
                return self.get_cached()

            self._cache["days"][today] = slots
            self._cache["fetched_epoch"] = now
            self._cache["last_error"] = None
            self._cache["next_fetch_epoch"] = 0

        # --- Fetch tomorrow (optional) ---
        if need_tomorrow:
            code, slots = self._fetch_day(tomorrow)
            if code == 200:
                self._cache["days"][tomorrow] = slots
                self._cache["tomorrow_status"] = "ok"
                self._cache["last_error"] = None
                self._cache["next_fetch_epoch"] = 0
            elif code == 404:
                # Normal: tomorrow not published yet
                self._cache["tomorrow_status"] = "not_ready"
                self._cache["last_error"] = None
                self._cache["next_fetch_epoch"] = now + 30 * 60
            else:
                self._cache["tomorrow_status"] = "error"
                self._cache["last_error"] = "tomorrow fetch failed: HTTP %d" % code
                self._cache["next_fetch_epoch"] = now + 30 * 60
        else:
            self._cache["tomorrow_status"] = "skipped"

        self._trim_days(today, tomorrow)
        try:
            self._save_cache()
        except Exception:
            pass

        return self.get_cached()