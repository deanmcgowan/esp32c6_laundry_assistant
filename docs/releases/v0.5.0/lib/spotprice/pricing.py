def flatten_slots(prices_cache):
    """
    prices_cache: dict returned by SpotPriceClient.get_cached()
    returns list of slots sorted by start_utc
    slot must contain: start_utc, end_utc, sek_per_kwh
    """
    out = []
    days = (prices_cache or {}).get("days") or {}
    for _ymd, slots in days.items():
        if not isinstance(slots, list):
            continue
        for s in slots:
            try:
                if s.get("start_utc") is None or s.get("end_utc") is None:
                    continue
                if s.get("sek_per_kwh") is None:
                    continue
                out.append(s)
            except Exception:
                pass
    out.sort(key=lambda x: x["start_utc"])
    return out


def price_at_utc(slots, utc_epoch):
    """
    Returns sek_per_kwh for the slot containing utc_epoch, or None.
    """
    for s in slots:
        if s["start_utc"] <= utc_epoch < s["end_utc"]:
            return s["sek_per_kwh"]
    return None


def align_up(utc_epoch, step_s):
    """
    Round up utc_epoch to next multiple of step_s.
    """
    r = utc_epoch % step_s
    if r == 0:
        return utc_epoch
    return utc_epoch + (step_s - r)


def avg_price_for_window(slots, start_utc, duration_s):
    """
    Weighted average SEK/kWh across [start_utc, start_utc+duration_s).
    Returns None if window not fully covered by slots.
    """
    end_utc = start_utc + duration_s
    total_w = 0
    total = 0.0

    t = start_utc
    while t < end_utc:
        found = None
        for s in slots:
            if s["start_utc"] <= t < s["end_utc"]:
                found = s
                break
        if not found:
            return None

        seg_end = min(found["end_utc"], end_utc)
        w = seg_end - t
        total += float(found["sek_per_kwh"]) * w
        total_w += w
        t = seg_end

    if total_w <= 0:
        return None
    return total / total_w