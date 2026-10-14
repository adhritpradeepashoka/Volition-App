# Jaw Clench Detection Algorithm
# Ported from Arduino C++ (Upside Down Labs, GPL-3.0)
# Original: Krishnanshu Mittal, Deepak Khatri — Upside Down Labs
#
# Pipeline: raw → notch → HP70 → envelope → threshold → clench counting
# Detects single and double jaw clenches with hysteresis and debounce.


class JawClenchDetector:
    """Detects single / double jaw clenches from an HP70 envelope signal."""

    def __init__(self, sample_rate=500):
        self.sample_rate = sample_rate
        self.threshold = 160.0
        self.release_threshold = 70.0
        self.debounce_ms = 270
        self.double_window_ms = 500

        # State
        self.last_jaw_time = 0
        self.last_press_time = 0
        self.jaw_active = False
        self.jaw_released = True

        # Envelope (rolling mean, ~100 ms window)
        self.env_size = max(1, (100 * sample_rate) // 1000)  # 50 @ 500 Hz
        self.env_buf = [0.0] * self.env_size
        self.env_idx = 0
        self.env_sum = 0.0
        self.envelope = 0.0

    # ── helpers ──────────────────────────────────────────────────────────

    def _update_envelope(self, abs_sample):
        self.env_sum -= self.env_buf[self.env_idx]
        self.env_sum += abs_sample
        self.env_buf[self.env_idx] = abs_sample
        self.env_idx = (self.env_idx + 1) % self.env_size
        self.envelope = self.env_sum / self.env_size
        return self.envelope

    # ── main entry ───────────────────────────────────────────────────────

    def process(self, envelope_sample, now_ms):
        """Feed the pre-calculated envelope sample and current time in ms.

        Returns
        -------
        str or None
            ``'single'``, ``'double'``, or ``None``.
        """
        self.envelope = envelope_sample

        high = self.envelope > self.threshold
        low = self.envelope < self.release_threshold
        event = None

        # Release detection (hysteresis)
        if low and self.jaw_active:
            self.jaw_released = True
            self.jaw_active = False

        # Clench detection
        if (high
                and not self.jaw_active
                and self.jaw_released
                and (now_ms - self.last_jaw_time) >= self.debounce_ms):
            self.last_jaw_time = now_ms
            self.jaw_released = False
            self.jaw_active = True

            if (self.last_press_time != 0
                    and (now_ms - self.last_press_time) <= self.double_window_ms):
                event = 'double'
            else:
                event = 'single'

            self.last_press_time = now_ms

        return event
