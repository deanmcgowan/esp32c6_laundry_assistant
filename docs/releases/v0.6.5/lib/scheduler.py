from timeutil import utc_to_stockholm_tuple, pack_time
from spotprice.pricing import flatten_slots, price_at_utc, avg_price_for_window


def _fmt_stockholm_hm(utc_epoch):
    t = utc_to_stockholm_tuple(int(utc_epoch))
    return "%02d:%02d" % (t[3], t[4])


def _delay_options_washer(max_hours=12):
    mins = [0, 30, 60, 90]
    for h in range(2, int(max_hours) + 1):
        mins.append(h * 60)
    return mins


def _delay_options_hourly(max_hours=12):
    return [h * 60 for h in range(0, int(max_hours) + 1)]


def _r2(x):
    if x is None:
        return None
    try:
        return round(float(x), 2)
    except Exception:
        return None


def _safe_float(x, default=0.0):
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _pv_rows_to_hourly(pv_series):
    rows = []
    for r in pv_series or []:
        try:
            s = int((r.get("start") or {}).get("device_epoch"))
            e = int((r.get("end") or {}).get("device_epoch"))
            if e <= s:
                continue
            pv_kw = r.get("pv_kw_est_simple")
            if pv_kw is None:
                pv_kw = r.get("pv_kwh_est_simple")
            pv_kw = _safe_float(pv_kw, default=0.0)
            if pv_kw < 0:
                pv_kw = 0.0
            rows.append({"start": s, "end": e, "pv_kw": pv_kw})
        except Exception:
            pass
    return rows


def _pv_usable_kwh(window_start, duration_s, hourly_rows, baseline_import_kw, mode):
    if duration_s <= 0:
        return 0.0

    w0 = int(window_start)
    w1 = int(window_start + duration_s)
    if w1 <= w0:
        return 0.0

    usable = 0.0
    for r in hourly_rows:
        s = int(r["start"])
        e = int(r["end"])
        if e <= w0 or s >= w1:
            continue
        overlap_s = min(e, w1) - max(s, w0)
        if overlap_s <= 0:
            continue

        pv_kw = _safe_float(r.get("pv_kw"), default=0.0)
        if mode == "exporting_now":
            avail_kw = pv_kw
        else:
            avail_kw = max(0.0, pv_kw - baseline_import_kw)
        usable += avail_kw * (float(overlap_s) / 3600.0)

    return usable


def _grid_cost_sek(avg_price, assumed_kwh, pv_usable_kwh):
    if avg_price is None:
        return None
    grid_kwh = max(0.0, float(assumed_kwh) - max(0.0, float(pv_usable_kwh)))
    return grid_kwh * float(avg_price), grid_kwh


def _mode_from_ngenic(ngenic_cache):
    imp = _safe_float((ngenic_cache or {}).get("import_kW"), default=0.0)
    exp = _safe_float((ngenic_cache or {}).get("export_kW"), default=0.0)
    net = (ngenic_cache or {}).get("net_kW")
    if net is None:
        net = imp - exp
    net = _safe_float(net, default=0.0)

    if exp >= 0.15:
        mode = "exporting_now"
    elif imp >= 0.15 or net > 0.15:
        mode = "importing_now"
    else:
        mode = "balanced_now"

    baseline_import_kw = max(0.0, net)
    return mode, imp, exp, net, baseline_import_kw


def compute_recommendations(prices_cache, now_utc, ngenic_cache=None, pv_series=None):
    slots = flatten_slots(prices_cache)
    cur_price = price_at_utc(slots, now_utc)

    if not slots:
        return {
            "current_spot_sek_per_kwh": None,
            "strategy": {"mode": "price_only", "reason": "No spot price slots available yet."},
            "appliances": [],
            "error": "No spot price slots available yet.",
        }

    mode, imp, exp, net, baseline_import_kw = _mode_from_ngenic(ngenic_cache or {})
    pv_hourly = _pv_rows_to_hourly(pv_series or [])
    has_pv_forecast = len(pv_hourly) > 0

    max_delay_h = 12
    appliances = [
        {
            "name": "Washing machine",
            "duration_s": 60 * 60,
            "delay_mins": _delay_options_washer(max_delay_h),
            "assumed_kwh": 1.0,
        },
        {
            "name": "Dishwasher",
            "duration_s": 60 * 60,
            "delay_mins": _delay_options_hourly(max_delay_h),
            "assumed_kwh": 1.0,
        },
        {
            "name": "Dryer",
            "duration_s": 4 * 60 * 60,
            "delay_mins": _delay_options_hourly(max_delay_h),
            "assumed_kwh": 2.5,
        },
    ]

    results = []
    for a in appliances:
        duration_s = int(a["duration_s"])
        assumed_kwh = float(a["assumed_kwh"])
        delay_mins = a["delay_mins"]

        base_start = int(now_utc)
        base_avg = avg_price_for_window(slots, base_start, duration_s)
        base_pv_kwh = _pv_usable_kwh(base_start, duration_s, pv_hourly, baseline_import_kw, mode)
        base_score = _grid_cost_sek(base_avg, assumed_kwh, base_pv_kwh)
        base_cost = base_score[0] if base_score else None
        base_grid_kwh = base_score[1] if base_score else None

        best = None
        for dm in delay_mins:
            start = int(now_utc + int(dm) * 60)
            avgp = avg_price_for_window(slots, start, duration_s)
            if avgp is None:
                continue

            pv_kwh = _pv_usable_kwh(start, duration_s, pv_hourly, baseline_import_kw, mode)
            score_out = _grid_cost_sek(avgp, assumed_kwh, pv_kwh)
            if not score_out:
                continue
            score, grid_kwh = score_out

            # Small delay penalty to avoid unnecessary waiting when scores are close.
            score_with_delay_penalty = float(score) + (float(dm) / 60.0) * 0.003

            cand = {
                "delay_min": int(dm),
                "start": int(start),
                "avgp": float(avgp),
                "score": float(score),
                "score_pen": float(score_with_delay_penalty),
                "pv_kwh": float(pv_kwh),
                "grid_kwh": float(grid_kwh),
            }
            if (best is None) or (cand["score_pen"] < best["score_pen"]):
                best = cand

        if best is None or base_avg is None or base_cost is None:
            results.append(
                {
                    "name": a["name"],
                    "delay_options_min": delay_mins,
                    "recommended_delay_min": None,
                    "recommended_start_local": None,
                    "recommended_start": None,
                    "avg_price_now_sek_per_kwh": _r2(base_avg),
                    "avg_price_recommended_sek_per_kwh": None,
                    "estimated_saving_sek": None,
                    "assumed_kwh_per_cycle": _r2(assumed_kwh),
                    "estimated_grid_kwh_now": _r2(base_grid_kwh),
                    "estimated_grid_kwh_recommended": None,
                    "estimated_pv_kwh_now": _r2(base_pv_kwh),
                    "estimated_pv_kwh_recommended": None,
                    "score_now_sek": _r2(base_cost),
                    "score_recommended_sek": None,
                    "decision_basis": "insufficient_data",
                }
            )
            continue

        saving = max(0.0, float(base_cost) - float(best["score"]))
        price_delta = float(best["avgp"]) - float(base_avg)
        pv_delta = float(best["pv_kwh"]) - float(base_pv_kwh)

        if pv_delta > 0.15 and price_delta > 0.02:
            basis = "pv_override"
        elif price_delta < -0.02 and pv_delta <= 0.15:
            basis = "price_optimised"
        else:
            basis = "mixed"

        results.append(
            {
                "name": a["name"],
                "delay_options_min": delay_mins,
                "recommended_delay_min": int(best["delay_min"]),
                "recommended_start_local": _fmt_stockholm_hm(best["start"]),
                "recommended_start": pack_time(best["start"]),
                "avg_price_now_sek_per_kwh": _r2(base_avg),
                "avg_price_recommended_sek_per_kwh": _r2(best["avgp"]),
                "estimated_saving_sek": _r2(saving),
                "assumed_kwh_per_cycle": _r2(assumed_kwh),
                "estimated_grid_kwh_now": _r2(base_grid_kwh),
                "estimated_grid_kwh_recommended": _r2(best["grid_kwh"]),
                "estimated_pv_kwh_now": _r2(base_pv_kwh),
                "estimated_pv_kwh_recommended": _r2(best["pv_kwh"]),
                "score_now_sek": _r2(base_cost),
                "score_recommended_sek": _r2(best["score"]),
                "decision_basis": basis,
            }
        )

    if mode == "exporting_now":
        reason = "Currently exporting. Prefer windows where own PV can cover appliance load."
    elif mode == "importing_now":
        reason = "Currently importing. Compare future PV offset against low-price slots."
    else:
        reason = "Balanced flow now. Optimise for expected grid cost (price minus PV offset)."

    return {
        "current_spot_sek_per_kwh": _r2(cur_price),
        "strategy": {
            "mode": mode,
            "reason": reason,
            "max_delay_hours": max_delay_h,
            "has_pv_forecast": bool(has_pv_forecast),
            "import_kW": _r2(imp),
            "export_kW": _r2(exp),
            "net_kW": _r2(net),
            "baseline_import_kW": _r2(baseline_import_kw),
        },
        "appliances": results,
        "error": None,
    }
