import time
import updater


def main():
    print("Laundry assistant v0.1.1 from GitHub Pages")

    # Mark boot successful after startup has completed without crashing.
    updater.mark_boot_success()

    while True:
        print("tick v0.1.1")
        time.sleep(5)


main()