# status_led.py — WS2812 status LED on GPIO8 (Waveshare ESP32‑C6‑Zero‑M)
# Note: Many WS2812 devices use GRB colour order.

import time
import machine
import neopixel


class StatusLED:
    def __init__(self, pin=8, n=1, order="GRB"):
        self._np = neopixel.NeoPixel(machine.Pin(pin), n)
        self._order = order.upper()  # "RGB" or "GRB"

        self._mode = "off"          # off | solid | blink
        self._solid = (0, 0, 0)
        self._blink = (0, 0, 0)
        self._interval_ms = 250
        self._last_ms = time.ticks_ms()
        self._is_on = False
        self.off()

    def _map(self, rgb):
        r, g, b = rgb
        if self._order == "GRB":
            return (g, r, b)
        return (r, g, b)

    def _write(self, rgb):
        self._np[0] = self._map(rgb)
        self._np.write()

    def off(self):
        self._mode = "off"
        self._solid = (0, 0, 0)
        self._is_on = False
        self._write((0, 0, 0))

    def solid(self, rgb):
        self._mode = "solid"
        self._solid = rgb
        self._is_on = True
        self._write(rgb)

    def blink(self, rgb, interval_ms=250):
        self._mode = "blink"
        self._blink = rgb
        self._interval_ms = int(interval_ms)
        self._last_ms = time.ticks_ms()
        self._is_on = True
        self._write(rgb)

    def tick(self):
        # Call frequently from long loops (Wi‑Fi connect, file download, etc.)
        if self._mode != "blink":
            return

        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_ms) < self._interval_ms:
            return

        self._last_ms = now
        self._is_on = not self._is_on
        self._write(self._blink if self._is_on else (0, 0, 0))