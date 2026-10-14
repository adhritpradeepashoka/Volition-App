# Blink Detection Algorithm
# Ported from Arduino C++ (Upside Down Labs, GPL-3.0)
# Original: Krishnanshu Mittal, Deepak Khatri — Upside Down Labs
#
# Pipeline: raw → notch → LP45 → HP5 → envelope → threshold → blink counting
# Detects single, double, and triple blinks with debounce and timing windows.


class BlinkDetector:
    """Detects single / double / triple blinks from an EEG envelope signal."""

    def __init__(self, sample_rate=500):
        self.sample_rate = sample_rate
        self.threshold = 50.0

        # Timing (ms)
        self.debounce_ms = 250
        self.double_blink_ms = 600
        self.triple_blink_ms = 800

        # State
        self.last_blink_time = 0
        self.first_blink_time = 0
        self.second_blink_time = 0
        self.blink_count = 0
        self.blink_active = False

        # Envelope (rolling mean of |sample|)
        window_ms = 100
        self.env_size = max(1, (window_ms * sample_rate) // 1000)
        self.env_buf = [0.0] * self.env_size
        self.env_idx = 0
        self.env_sum = 0.0
        self.envelope = 0.0

    # ── helpers ──────────────────────────────────────────────────────────

    def _update_envelope(self, sample):
        a = abs(sample)
        self.env_sum -= self.env_buf[self.env_idx]
        self.env_sum += a
        self.env_buf[self.env_idx] = a
        self.env_idx = (self.env_idx + 1) % self.env_size
        self.envelope = self.env_sum / self.env_size
        return self.envelope

    # ── main entry ───────────────────────────────────────────────────────

    def process(self, envelope_sample, now_ms):
        """Feed the pre-calculated envelope sample and current time in ms.

        Returns
        -------
        str or None
            ``'single'``, ``'double'``, ``'triple'``, or ``None``.
        """
        self.envelope = envelope_sample
        high = self.envelope > self.threshold
        event = None

        # Rising-edge detection with debounce
        if (not self.blink_active
                and high
                and (now_ms - self.last_blink_time) >= self.debounce_ms):
            self.last_blink_time = now_ms

            if self.blink_count == 0:
                self.first_blink_time = now_ms
                self.blink_count = 1
            elif (self.blink_count == 1
                  and (now_ms - self.first_blink_time) <= self.double_blink_ms):
                self.second_blink_time = now_ms
                self.blink_count = 2
            elif (self.blink_count == 2
                  and (now_ms - self.second_blink_time) <= self.triple_blink_ms):
                event = 'triple'
                self.blink_count = 0
            else:
                self.first_blink_time = now_ms
                self.blink_count = 1

            self.blink_active = True

        if not high:
            self.blink_active = False

        # Timeout → emit pending events
        if (self.blink_count == 2
                and (now_ms - self.second_blink_time) > self.triple_blink_ms):
            event = 'double'
            self.blink_count = 0

        if (self.blink_count == 1
                and (now_ms - self.first_blink_time) > self.double_blink_ms):
            event = 'single'
            self.blink_count = 0

        return event
