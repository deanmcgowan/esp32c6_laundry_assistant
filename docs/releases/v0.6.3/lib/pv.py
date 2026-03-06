from timeutil import pack_time


def _safe_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def build_pv_hourly_series(weather_series, solar_series, kwp=9.7, loss_factor=0.86):
    """
    Merge hourly weather + solar by matching end_epoch.

    Output rows:
      [{
        start, end (pack_time),
        t_air_c, wind_mps,
        gti_wm2,
        pv_kw_est_simple,
        pv_kwh_est_simple
      }, ...]
    """
    kwp = float(kwp)
    loss_factor = float(loss_factor)

    w_by_end = {}
    for w in weather_series or []:
        try:
            w_by_end[int(w.get("end_epoch"))] = w
        except Exception:
            pass

    out = []
    for s in solar_series or []:
        try:
            end_epoch = int(s.get("end_epoch"))
            start_epoch = int(s.get("start_epoch"))
        except Exception:
            continue

        w = w_by_end.get(end_epoch)
        wvals = (w.get("values") if w else {}) or {}
        svals = (s.get("values") or {}) or {}

        t_air = _safe_float(wvals.get("t_air_c"))
        wind = _safe_float(wvals.get("wind_mps"))
        gti = _safe_float(svals.get("gti_wm2"))

        pv_kw = None
        pv_kwh = None
        if gti is not None:
            pv_kw = kwp * (gti / 1000.0) * loss_factor
            if pv_kw < 0:
                pv_kw = 0.0
            pv_kwh = pv_kw  # 1 hour bucket

        out.append(
            {
                "start": pack_time(start_epoch),
                "end": pack_time(end_epoch),
                "t_air_c": t_air,
                "wind_mps": wind,
                "gti_wm2": gti,
                "pv_kw_est_simple": pv_kw,
                "pv_kwh_est_simple": pv_kwh,
            }
        )

    return out