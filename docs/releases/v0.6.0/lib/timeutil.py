import time

# MicroPython on ESP32 ports typically uses an epoch of 2000-01-01.
# Unix epoch is 1970-01-01.
# 1970-01-01 -> 2000-01-01 = 946684800 seconds.
UNIX_EPOCH_OFFSET_S = 946684800


def mp_to_unix(mp_epoch):
    if mp_epoch is None:
        return None
    return int(mp_epoch) + UNIX_EPOCH_OFFSET_S


def unix_to_mp(unix_epoch):
    if unix_epoch is None:
        return None
    return int(unix_epoch) - UNIX_EPOCH_OFFSET_S


def _is_leap(year):
    return (year % 4 == 0) and ((year % 100 != 0) or (year % 400 == 0))


def _days_in_month(year, month):
    if month in (1, 3, 5, 7, 8, 10, 12):
        return 31
    if month in (4, 6, 9, 11):
        return 30
    return 29 if _is_leap(year) else 28


def _last_sunday(year, month):
    last = _days_in_month(year, month)
    # weekday: Mon=0..Sun=6
    t = time.mktime((year, month, last, 12, 0, 0, 0, 0))
    w = time.localtime(t)[6]
    delta = (w - 6) % 7
    return last - delta


def stockholm_offset_s(utc_mp_epoch):
    """
    EU DST for Europe/Stockholm:
      - starts last Sunday of March at 01:00 UTC
      - ends last Sunday of October at 01:00 UTC
    Returns offset seconds from UTC (3600 or 7200).
    """
    y = time.gmtime(int(utc_mp_epoch))[0]

    d = _last_sunday(y, 3)
    dst_start = time.mktime((y, 3, d, 1, 0, 0, 0, 0))

    d = _last_sunday(y, 10)
    dst_end = time.mktime((y, 10, d, 1, 0, 0, 0, 0))

    if dst_start <= utc_mp_epoch < dst_end:
        return 2 * 3600
    return 1 * 3600


def utc_to_stockholm_tuple(utc_mp_epoch):
    off = stockholm_offset_s(utc_mp_epoch)
    return time.gmtime(int(utc_mp_epoch) + off)


def stockholm_ymd(utc_mp_epoch):
    t = utc_to_stockholm_tuple(utc_mp_epoch)
    return "%04d-%02d-%02d" % (t[0], t[1], t[2])


def stockholm_hms(utc_mp_epoch):
    t = utc_to_stockholm_tuple(utc_mp_epoch)
    return "%02d:%02d:%02d" % (t[3], t[4], t[5])


def add_days_ymd(ymd, days=1):
    """Add days to a YYYY-MM-DD date string (calendar arithmetic)."""
    y = int(ymd[0:4])
    m = int(ymd[5:7])
    d = int(ymd[8:10])
    n = int(days)
    if n < 0:
        raise ValueError("add_days_ymd only supports positive days")
    while n > 0:
        dim = _days_in_month(y, m)
        if d < dim:
            d += 1
        else:
            d = 1
            if m < 12:
                m += 1
            else:
                m = 1
                y += 1
        n -= 1
    return "%04d-%02d-%02d" % (y, m, d)


def stockholm_today_tomorrow_ymd(utc_mp_epoch):
    """
    Returns (today_ymd, tomorrow_ymd) in Europe/Stockholm local calendar terms.
    """
    today = stockholm_ymd(utc_mp_epoch)
    tomorrow = add_days_ymd(today, 1)
    return today, tomorrow


def utc_mp_epoch_to_iso8601_z(utc_mp_epoch):
    t = time.gmtime(int(utc_mp_epoch))
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (t[0], t[1], t[2], t[3], t[4], t[5])


def utc_mp_epoch_to_stockholm_iso8601(utc_mp_epoch):
    off = stockholm_offset_s(utc_mp_epoch)
    t = time.gmtime(int(utc_mp_epoch) + off)
    sign = "+"
    hh = int(off // 3600)
    mm = int((off % 3600) // 60)
    return "%04d-%02d-%02dT%02d:%02d:%02d%s%02d:%02d" % (
        t[0], t[1], t[2], t[3], t[4], t[5], sign, hh, mm
    )


def pack_time(utc_mp_epoch):
    """
    Consistent time object used throughout internal APIs.
    - mp: MicroPython epoch seconds (typically since 2000-01-01)
    - unix: Unix epoch seconds (since 1970-01-01)
    - utc: ISO8601 in UTC with Z
    - local: ISO8601 in Europe/Stockholm with explicit offset
    """
    mp = int(utc_mp_epoch)
    return {
        "mp": mp,
        "unix": mp_to_unix(mp),
        "utc": utc_mp_epoch_to_iso8601_z(mp),
        "local": utc_mp_epoch_to_stockholm_iso8601(mp),
    }


def parse_iso8601_to_utc_mp_epoch(s):
    """
    Parses ISO8601-ish timestamps into UTC MicroPython epoch seconds.

    Supports:
      - 2026-03-01T13:28
      - 2026-03-01T13:28:32
      - 2026-03-01T13:28:32Z
      - 2026-03-01T13:28+01:00
      - 2026-03-01T13:28:32+01:00
      - 2026-03-01T13:28:32.123Z  (fractional seconds ignored)
    """
    if not s:
        return None

    s = s.strip()

    # Handle "YYYY-MM-DDTHH:MM:SS Etc/UTC" style
    if " " in s and len(s) >= 19 and s[10] == "T":
        s = s.split(" ", 1)[0]

    # Strip trailing Z (UTC)
    if s.endswith("Z"):
        s = s[:-1]

    # Extract timezone offset if present (+HH:MM or -HH:MM)
    off_s = 0
    if len(s) >= 6 and (s[-6] == "+" or s[-6] == "-") and s[-3] == ":":
        sign = 1 if s[-6] == "+" else -1
        try:
            off_h = int(s[-5:-3])
            off_m = int(s[-2:])
            off_s = sign * (off_h * 3600 + off_m * 60)
            s = s[:-6]
        except Exception:
            off_s = 0  # fall back to no offset

    # Drop fractional seconds if present
    if "." in s:
        s = s.split(".", 1)[0]

    # Now s is either YYYY-MM-DDTHH:MM or YYYY-MM-DDTHH:MM:SS
    if "T" not in s or len(s) < 16:
        return None

    y = int(s[0:4])
    mo = int(s[5:7])
    d = int(s[8:10])
    hh = int(s[11:13])
    mm = int(s[14:16])
    ss = 0
    if len(s) >= 19:
        ss = int(s[17:19])

    local_epoch = time.mktime((y, mo, d, hh, mm, ss, 0, 0))
    return int(local_epoch - off_s)