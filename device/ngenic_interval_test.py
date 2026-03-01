# ngenic_interval_test.py
# Prompts you to toggle "Emergency charge" ON/OFF while logging Ngenic power.
# Stop with Ctrl+C in Thonny.

import time
from ngenic_client import NgenicClient

# How often to *attempt* refreshes during the test (seconds).
# Keep this >= 5 to be polite to the API.
TEST_REFRESH_S = 10

# Prompt schedule (seconds from start)
# Each cycle: wait, prompt ON, wait, prompt OFF, rest
CYCLES = 5
WARMUP_S = 60
ON_AFTER_S = 30
OFF_AFTER_S = 45
REST_S = 60

def run():
    ng = NgenicClient()
    ng.set_polling_mode_fast(TEST_REFRESH_S)   # fast-ish polling for the test

    t0 = time.time()
    next_refresh = t0

    # Build prompt timeline
    prompts = []
    t = t0 + WARMUP_S
    prompts.append((t, "READY. Starting toggles soon."))
    for i in range(CYCLES):
        t_on = t + ON_AFTER_S
        t_off = t_on + OFF_AFTER_S
        prompts.append((t_on, f"== ACTION: TURN ON emergency charge (cycle {i+1}/{CYCLES}) =="))
        prompts.append((t_off, f"== ACTION: TURN OFF emergency charge (cycle {i+1}/{CYCLES}) =="))
        t = t_off + REST_S

    prompt_i = 0

    print("device_epoch,import_kW,export_kW,net_kW,import_time,export_time,ok,last_error")

    while True:
        now = time.time()

        # Print prompts at scheduled times
        while prompt_i < len(prompts) and now >= prompts[prompt_i][0]:
            print(prompts[prompt_i][1])
            prompt_i += 1

        # Refresh on schedule
        if now >= next_refresh:
            ng.refresh_if_due(force=True)  # force during the test
            next_refresh = now + TEST_REFRESH_S

        st = ng.get_cached()
        print("{},{},{},{},{},{},{},{}".format(
            st.get("updated_epoch"),
            st.get("import_kW"),
            st.get("export_kW"),
            st.get("net_kW"),
            st.get("import_time"),
            st.get("export_time"),
            st.get("ok"),
            st.get("last_error"),
        ))

        time.sleep(1)

run()