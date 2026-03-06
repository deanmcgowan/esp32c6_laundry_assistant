import time
from timeutil import pack_time, epoch_base_year, unix_offset_s

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


def response_envelope(data, app_version, now_epoch=None, endpoint=None):
    now = int(now_epoch if now_epoch is not None else time.time())
    meta = {
        "app_version": app_version,
        "tz": TZ_NAME,
        "epoch_base_year": epoch_base_year(),
        "unix_offset_s": unix_offset_s(),
        "generated": pack_time(now),
    }
    if endpoint:
        meta["endpoint"] = endpoint
    return {"meta": meta, "data": data}