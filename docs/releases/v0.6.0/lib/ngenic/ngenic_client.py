# ngenic_client.py
# Ngenic Tune API v3 client (instantaneous import/export power) using HTTP/1.1 TLS.
#
# Adaptive polling strategy:
# - Empirically, Ngenic "latest" values update roughly once per minute (sometimes ~90s gaps).
# - We therefore avoid constant polling; we predict the next update and only poll
#   frequently in a short "chase window" around that time.
#
# Adds:
# - caching
# - backoff (429 Retry-After respected if present)
# - age_s: seconds since last observed upstream sample change (or since last refresh as fallback)
#
# Requires /secrets.json keys:
#   ngenic_token
#   ngenic_tune_uuid
#   ngenic_grid_node_uuid

import time
import json
from ngenic.ngenic_http11 import get_json

HOST = "app.ngenic.se"
BASE = "/api/v3"


class NgenicClient:
    def __init__(self, secrets_path="/secrets.json"):
        with open(secrets_path, "r") as f:
            sec = json.load(f)

        self.token = sec["ngenic_token"]
        self.tune_uuid = sec["ngenic_tune_uuid"]
        self.node_uuid = sec["ngenic_grid_node_uuid"]

        self._cache = {
            "import_kW": None,
            "export_kW": None,
            "net_kW": None,
            "import_time": None,       # Ngenic timestamp string
            "export_time": None,       # Ngenic timestamp string
            "updated_epoch": None,     # device epoch when refreshed (time.time())
            "ok": False,
            "last_error": None,

            # Telemetry for freshness / cadence
            "ngenic_time_changed_epoch": None,  # device epoch when we first observed a new Ngenic time stamp
            "learned_interval_s": None,
        }

        # Backoff control (errors / 429)
        self._next_allowed_ms = time.ticks_ms()
        self._fail_count = 0

        # Learning / cadence tracking (based on changes in Ngenic's "time" string)
        self._last_time_str = None
        self._last_change_epoch = None  # device epoch when time_str last changed

        # Rolling interval estimate (seconds). Start with what your logs show most often.
        self._interval_est_s = 60.0

        # Polling knobs (defaults)
        self._fast_boot_polls = 6           # first few polls: more eager to get initial values
        self._boot_poll_s = 10              # during boot eager phase
        self._idle_poll_s = 60              # when far from expected boundary
        self._lead_s = 8                    # start chasing this many seconds before expected update
        self._chase_poll_s = 5              # poll every 5s while chasing
        self._chase_window_s = 40           # keep chasing up to this long past expected time

    # --- Optional knobs (useful for short tests) ---
    def set_polling_mode_fast(self, poll_s=10):
        """
        For short tests only. Makes the client behave more like fixed-interval polling.
        Still honours backoff windows.
        """
        poll_s = int(max(5, poll_s))
        self._fast_boot_polls = 999999
        self._boot_poll_s = poll_s
        self._idle_poll_s = poll_s
        self._lead_s = 0
        self._chase_poll_s = poll_s
        self._chase_window_s = 300

    def set_polling_mode_default(self):
        """Return to conservative adaptive defaults."""
        self._fast_boot_polls = 6
        self._boot_poll_s = 10
        self._idle_poll_s = 60
        self._lead_s = 8
        self._chase_poll_s = 5
        self._chase_window_s = 40

    # --- Public API ---
    def get_cached(self):
        d = dict(self._cache)
        d["age_s"] = self._compute_age_s()
        return d

    def refresh_if_due(self, force=False):
        """
        Call frequently (e.g. once per second from your main loop).
        It will decide whether to hit the Ngenic API or just return cached values.

        force=True:
          - still honours backoff windows
          - otherwise bypasses adaptive scheduling and polls now
        """
        if self._in_backoff():
            return self.get_cached()

        now_epoch = time.time()

        if not force:
            if not self._should_poll_now(now_epoch):
                return self.get_cached()

        try:
            imp_val, imp_time = self._fetch_value_and_time("power_kW")
            exp_val, exp_time = self._fetch_value_and_time("produced_power_kW")

            net = None
            if (imp_val is not None) or (exp_val is not None):
                net = (imp_val or 0.0) - (exp_val or 0.0)

            # Track cadence using whichever time string we got (prefer import_time).
            time_str = imp_time or exp_time
            self._observe_time_string_change(time_str, now_epoch)

            self._cache.update({
                "import_kW": imp_val,
                "export_kW": exp_val,
                "net_kW": net,
                "import_time": imp_time,
                "export_time": exp_time,
                "updated_epoch": now_epoch,
                "ok": True,
                "last_error": None,
                "ngenic_time_changed_epoch": self._last_change_epoch,
                "learned_interval_s": round(self._interval_est_s, 1),
            })

            self._fail_count = 0
            return self.get_cached()

        except Exception as e:
            self._fail_count += 1
            self._cache["ok"] = False
            self._cache["last_error"] = repr(e)

            # Exponential-ish backoff on errors (capped)
            backoff_s = min(120, 5 * (2 ** min(self._fail_count - 1, 4)))
            self._set_backoff(backoff_s)

            return self.get_cached()

    # --- Internals ---
    def _compute_age_s(self):
        now_epoch = time.time()
        # Prefer "time changed" moment (freshness of upstream), otherwise fall back to our last refresh time.
        ref = self._cache.get("ngenic_time_changed_epoch") or self._cache.get("updated_epoch")
        if ref is None:
            return None
        age = now_epoch - ref
        if age < 0:
            age = 0
        return int(age)

    def _headers(self):
        return {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/json",
            "User-Agent": "ESP32C6-MicroPython/1.27 ngenic-client",
        }

    def _set_backoff(self, seconds):
        self._next_allowed_ms = time.ticks_add(time.ticks_ms(), int(seconds * 1000))

    def _in_backoff(self):
        return time.ticks_diff(time.ticks_ms(), self._next_allowed_ms) < 0

    def _should_poll_now(self, now_epoch):
        # If we've never successfully updated, be eager.
        if self._cache["updated_epoch"] is None:
            return True

        # Initial eager polling for a few cycles
        if self._fast_boot_polls > 0:
            return (now_epoch - self._cache["updated_epoch"]) >= self._boot_poll_s

        # If we don't yet have a change reference, just idle poll.
        if self._last_change_epoch is None:
            return (now_epoch - self._cache["updated_epoch"]) >= self._idle_poll_s

        # Predict next update based on last observed change and interval estimate
        expected = self._last_change_epoch + self._interval_est_s
        dt = now_epoch - expected  # negative => before expected; positive => after expected

        # If we're far from the boundary, idle poll occasionally
        if dt < -self._lead_s:
            return (now_epoch - self._cache["updated_epoch"]) >= self._idle_poll_s

        # Near/after boundary: chase until we see the time string change
        if dt <= self._chase_window_s:
            return (now_epoch - self._cache["updated_epoch"]) >= self._chase_poll_s

        # Way past expected and still no update: revert to idle polling
        return (now_epoch - self._cache["updated_epoch"]) >= self._idle_poll_s

    def _observe_time_string_change(self, time_str, now_epoch):
        if not time_str:
            return

        # First time we see a time string
        if self._last_time_str is None:
            self._last_time_str = time_str
            self._last_change_epoch = now_epoch
            return

        # Detect change
        if time_str != self._last_time_str:
            # We saw a new upstream sample
            if self._last_change_epoch is not None:
                observed = now_epoch - self._last_change_epoch
                # Ignore nonsense deltas
                if 10 <= observed <= 300:
                    # Update estimate gently (EWMA) so it can adapt but not bounce
                    alpha = 0.25
                    self._interval_est_s = (1 - alpha) * self._interval_est_s + alpha * observed

            self._last_time_str = time_str
            self._last_change_epoch = now_epoch

            # Boot eager phase counts down on actual upstream changes
            if self._fast_boot_polls > 0:
                self._fast_boot_polls -= 1

        else:
            # No upstream change; count down boot eager phase slowly (we've at least polled)
            if self._fast_boot_polls > 0:
                self._fast_boot_polls -= 1

    def _latest(self, typ, timeout_s=20):
        path = "{}/tunes/{}/measurements/{}/latest?type={}".format(
            BASE, self.tune_uuid, self.node_uuid, typ
        )
        status, hdrs, parsed, body = get_json(
            HOST, path, headers=self._headers(), timeout_s=timeout_s, server_hostname=HOST
        )
        return status, hdrs, parsed, body

    def _fetch_value_and_time(self, typ):
        status, hdrs, parsed, body = self._latest(typ)

        if status == 204:
            return None, None

        if status == 429:
            ra = hdrs.get("retry-after")
            try:
                wait_s = int(ra) if ra else 60
            except Exception:
                wait_s = 60
            self._set_backoff(wait_s)
            raise RuntimeError("Rate limited (429), retry-after={}".format(ra))

        if status != 200 or not isinstance(parsed, dict):
            snip = body[:120]
            raise RuntimeError("HTTP {} for {} body={}".format(status, typ, snip))

        # parsed: {'hasValue': True/False, 'time': '...', 'value': ...}
        if not parsed.get("hasValue", False):
            return None, parsed.get("time")

        return parsed.get("value"), parsed.get("time")