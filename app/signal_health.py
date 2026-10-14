# Volition — Copyright (c) 2026 Adhrit Pradeep. Licensed under GPL-3.0 (see LICENSE).
# Built on NPG-Lite-SNES by Upside Down Labs (GPL-3.0).
"""
Volition - Signal Health Monitor
==================================
Watches RAW ADC samples (before any filtering) per channel to detect
hardware and contact problems that the classifier would otherwise
mistake for real gestures:

  CALIBRATING — still collecting the initial baseline window
  OK          — normal operating range
  NO_SIGNAL   — flat line (near-zero peak-to-peak swing) — electrode
                not touching skin, dry contact, oxidized snap, or
                channel not transmitting at all
  SATURATED   — values pinned near the ADC rails (0 or 4095 for a
                12-bit ADC) for a sustained fraction of the window —
                amplifier railing, short circuit, or very bad contact
  NOISY       — excessive peak-to-peak swing with no coherent
                envelope — loose electrode, movement artifact, or a
                failing snap connector

Raw ADC range assumed: 0–4095 (12-bit), AC-coupled around a DC midpoint,
matching the NPG Lite's protocol (per npg_protocol.py / BLE packet spec).

Used to VETO intent firing on a channel that's clearly broken — a
saturated or noisy channel would otherwise trip the adaptive thresholds
and produce false gestures that look identical to real ones.
"""

import time
from collections import deque


class SignalHealthMonitor:

    WINDOW_SIZE      = 150    # raw samples at 500Hz ≈ 0.3s of data
    NO_SIGNAL_PP     = 4      # peak-to-peak swing below this = flatline
    SATURATION_LOW   = 40     # raw value at/below this = railed low
    SATURATION_HIGH  = 4055   # raw value at/above this = railed high
    SATURATION_FRAC  = 0.30   # fraction of window pinned at a rail → SATURATED
    NOISY_PP         = 3500   # peak-to-peak swing at/above this = NOISY
    RECHECK_SECS     = 0.2    # minimum time between status re-evaluations
                              # (prevents single-sample flicker)

    def __init__(self, name: str, check_saturation: bool = True):
        self.name              = name
        self._window            = deque(maxlen=self.WINDOW_SIZE)
        self.status             = "CALIBRATING"
        self._status_since      = time.time()
        self._last_check        = 0.0
        # SATURATED assumes large amplitude near the ADC rails is always
        # a hardware fault (railed amplifier, short, very bad contact) —
        # true for EEG, where nothing legitimate should ever swing that
        # large. FALSE for EMG: a genuine, deliberate strong flex is
        # SUPPOSED to produce a large-amplitude burst, and can naturally
        # sit close to the rails — so this same rule flags real gestures
        # as errors on CH2/CH3. Construct EMG channels with
        # check_saturation=False to skip only this one check; NO_SIGNAL
        # and NOISY still apply fully, since a disconnected/loose
        # electrode looks nothing like a real strong flex either way.
        self._check_saturation  = check_saturation

    def update(self, raw_value: float) -> str:
        self._window.append(raw_value)

        if len(self._window) < self.WINDOW_SIZE:
            self.status = "CALIBRATING"
            return self.status

        now = time.time()
        if now - self._last_check < self.RECHECK_SECS:
            return self.status
        self._last_check = now

        arr = self._window
        lo, hi = min(arr), max(arr)
        pp = hi - lo

        if self._check_saturation:
            rail_low  = sum(1 for v in arr if v <= self.SATURATION_LOW)
            rail_high = sum(1 for v in arr if v >= self.SATURATION_HIGH)
            rail_frac = (rail_low + rail_high) / len(arr)
        else:
            rail_frac = 0.0

        if self._check_saturation and rail_frac >= self.SATURATION_FRAC:
            new_status = "SATURATED"
        elif pp <= self.NO_SIGNAL_PP:
            new_status = "NO_SIGNAL"
        elif pp >= self.NOISY_PP:
            new_status = "NOISY"
        else:
            new_status = "OK"

        if new_status != self.status:
            self.status = new_status
            self._status_since = now

        return self.status

    @property
    def is_healthy(self) -> bool:
        """False for SATURATED or NOISY — these produce believable-looking
        false gestures and should veto intent firing. NO_SIGNAL is also
        unhealthy but is self-limiting (near-zero values rarely cross
        any threshold anyway), included here for completeness."""
        return self.status in ("OK", "CALIBRATING")

    @property
    def time_in_status(self) -> float:
        return time.time() - self._status_since

    def reset(self):
        self._window.clear()
        self.status = "CALIBRATING"
        self._status_since = time.time()