import time
from timeutil import pack_time


TZ_NAME = "Europe/Stockholm"


def clamp_int(x, lo, hi, default):
    try:
        v = int(x)
    except Exception:
        return int(default)
    if v < lo:
        return int(lo)
    if v > hi:
        return int(hi)
    return int(v)


def response_envelope(data, app_version, now_mp_epoch=None, endpoint=None):
    now = int(now_mp_epoch if now_mp_epoch is not None else time.time())
    meta = {
        "app_version": app_version,
        "tz": TZ_NAME,
        "generated": pack_time(now),
    }
    if endpoint:
        meta["endpoint"] = endpoint
    return {"meta": meta, "data": data}