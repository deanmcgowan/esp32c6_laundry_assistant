import time
from ngenic_client import NgenicClient

ng = NgenicClient()

print("device_epoch,import_kW,export_kW,net_kW,age_s,learned_interval_s,import_time,export_time,ok,last_error")

while True:
    st = ng.refresh_if_due()
    print("{},{},{},{},{},{},{},{},{},{}".format(
        st.get("updated_epoch"),
        st.get("import_kW"),
        st.get("export_kW"),
        st.get("net_kW"),
        st.get("age_s"),
        st.get("learned_interval_s"),
        st.get("import_time"),
        st.get("export_time"),
        st.get("ok"),
        st.get("last_error"),
    ))
    time.sleep(1)