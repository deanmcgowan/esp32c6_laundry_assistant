from timeutil import utc_to_stockholm_tuple
from spotprice.pricing import flatten_slots, price_at_utc, align_up, avg_price_for_window


def _fmt_stockholm_hm(utc_epoch):
    t = utc_to_stockholm_tuple(int(utc_epoch))
    return "%02d:%02d" % (t[3], t[4])


def _delay_options_washer(max_hours=12):
    # [0, 30m, 1h, 90m, 2h, 3h, ...]
    mins = [0, 30, 60, 90]
    for h in range(2, max_hours + 1):
        mins.append(h * 60)
    return mins


def _delay_options_hourly(max_hours=12):
    return [h * 60 for h in range(0, max_hours + 1)]


def _r2(x):
    if x is None:
        return None
    try:
        return round(float(x), 2)
    except Exception:
        return None


def compute_recommendations(prices_cache, now_utc):
    """
    Returns dict suitable for /api/recommendations.
    Uses spot prices only; assumes default cycle kWh values (labelled in output).

    Output rounding policy (v0.5.1+):
      - SEK/kWh: 2dp
      - kWh: left as-is (defaults are simple numbers)
      - SEK savings: 2dp
    """
    slots = flatten_slots(prices_cache)
    cur_price = price_at_utc(slots, now_utc)

    if not slots:
        return {
            "current_spot_sek_per_kwh": None,
            "appliances": [],
            "error": "No spot price slots available yet."
        }

    # Align start times to 15-minute boundaries (900s)
    step_s = 900

    appliances = [
        {
            "name": "Washing machine",
            "duration_s": 60 * 60,
            "delay_mins": _delay_options_washer(12),
            "assumed_kwh": 1.0,
        },
        {
            "name": "Dishwasher",
            "duration_s": 60 * 60,
            "delay_mins": _delay_options_hourly(12),
            "assumed_kwh": 1.0,
        },
        {
            "name": "Dryer",
            "duration_s": 4 * 60 * 60,   # 4 hours (as requested)
            "delay_mins": _delay_options_hourly(12),
            "assumed_kwh": 2.5,
        },
    ]

    results = []
    for a in appliances:
        duration_s = a["duration_s"]
        assumed_kwh = a["assumed_kwh"]

        base_start = align_up(now_utc, step_s)
        base_avg = avg_price_for_window(slots, base_start, duration_s)

        best = None
        for dm in a["delay_mins"]:
            start = align_up(now_utc + dm * 60, step_s)
            avgp = avg_price_for_window(slots, start, duration_s)
            if avgp is None:
                continue
            if (best is None) or (avgp < best["avgp"]):
                best = {"delay_min": dm, "start": start, "avgp": avgp}

        if best is None or base_avg is None:
            results.append({
                "name": a["name"],
                "recommended_delay_min": None,
                "recommended_start_local": None,
                "avg_price_now_sek_per_kwh": _r2(base_avg),
                "avg_price_recommended_sek_per_kwh": None,
                "estimated_saving_sek": None,
                "assumed_kwh_per_cycle": assumed_kwh,
            })
            continue

        saving = (base_avg - best["avgp"]) * assumed_kwh
        if saving < 0:
            saving = 0.0

        results.append({
            "name": a["name"],
            "recommended_delay_min": int(best["delay_min"]),
            "recommended_start_local": _fmt_stockholm_hm(best["start"]),
            "avg_price_now_sek_per_kwh": _r2(base_avg),
            "avg_price_recommended_sek_per_kwh": _r2(best["avgp"]),
            "estimated_saving_sek": _r2(saving),
            "assumed_kwh_per_cycle": assumed_kwh,
        })

    return {
        "current_spot_sek_per_kwh": _r2(cur_price),
        "appliances": results,
        "error": None,
    }