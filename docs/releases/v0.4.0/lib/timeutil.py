import time

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

def stockholm_offset_s(utc_epoch):
    """
    EU DST for Europe/Stockholm:
      - starts last Sunday of March at 01:00 UTC
      - ends   last Sunday of October at 01:00 UTC
    Returns offset seconds from UTC (3600 or 7200).
    """
    y = time.gmtime(utc_epoch)[0]

    d = _last_sunday(y, 3)
    dst_start = time.mktime((y, 3, d, 1, 0, 0, 0, 0))

    d = _last_sunday(y, 10)
    dst_end = time.mktime((y, 10, d, 1, 0, 0, 0, 0))

    if dst_start <= utc_epoch < dst_end:
        return 2 * 3600
    return 1 * 3600

def utc_to_stockholm_tuple(utc_epoch):
    off = stockholm_offset_s(utc_epoch)
    return time.gmtime(utc_epoch + off)

def stockholm_ymd(utc_epoch):
    t = utc_to_stockholm_tuple(utc_epoch)
    return "%04d-%02d-%02d" % (t[0], t[1], t[2])

def stockholm_hms(utc_epoch):
    t = utc_to_stockholm_tuple(utc_epoch)
    return "%02d:%02d:%02d" % (t[3], t[4], t[5])

def add_days_ymd(ymd, days=1):
    """
    Add days to a YYYY-MM-DD date string (calendar arithmetic).
    Only supports positive days (we only need +1).
    """
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

def stockholm_today_tomorrow_ymd(utc_epoch):
    """
    Returns (today_ymd, tomorrow_ymd) in Europe/Stockholm local calendar terms.
    This avoids the 'now + 36h' bug late in the day.
    """
    today = stockholm_ymd(utc_epoch)
    tomorrow = add_days_ymd(today, 1)
    return today, tomorrow

def parse_iso8601_to_utc_epoch(s):
    """
    Parses:
      - 2026-03-01T13:28:32 Etc/UTC  (treated as UTC)
      - 2026-03-01T14:00:00+01:00
    Returns UTC epoch seconds (MicroPython epoch, typically set to UTC by NTP).
    """
    if not s:
        return None

    if " " in s and s[10] == "T":
        base = s.split(" ", 1)[0]
        y = int(base[0:4]); mo = int(base[5:7]); d = int(base[8:10])
        hh = int(base[11:13]); mm = int(base[14:16]); ss = int(base[17:19])
        return time.mktime((y, mo, d, hh, mm, ss, 0, 0))

    base = s[0:19]
    y = int(base[0:4]); mo = int(base[5:7]); d = int(base[8:10])
    hh = int(base[11:13]); mm = int(base[14:16]); ss = int(base[17:19])

    off = 0
    if len(s) >= 25 and (s[19] == "+" or s[19] == "-"):
        sign = 1 if s[19] == "+" else -1
        off_h = int(s[20:22])
        off_m = int(s[23:25])
        off = sign * (off_h * 3600 + off_m * 60)

    local_epoch = time.mktime((y, mo, d, hh, mm, ss, 0, 0))
    return local_epoch - off