# Eye Movement Detection Algorithm
# Ported from Arduino C++ (Upside Down Labs, GPL-3.0)
# Original: Krishnanshu Mittal, Deepak Khatri — Upside Down Labs
#
# Pipeline: raw → notch → BP1to10 → baseline tracker → deviation → threshold
# Detects left and right eye movements from EOG deviation signal.


class EyeMovementDetector:
    """Detects left / right eye movements from a deviation signal."""

    def __init__(self):
        self.threshold = 150.0
        self.debounce_ms = 800
        self.last_movement_time = 0

    def process(self, deviation, now_ms):
        """Feed the deviation (signal − baseline) and current time in ms.

        Returns
        -------
        str or None
            ``'left'``, ``'right'``, or ``None``.
        """
        if (now_ms - self.last_movement_time) < self.debounce_ms:
            return None

        if deviation > self.threshold:
            self.last_movement_time = now_ms
            return 'left'
        elif deviation < -self.threshold:
            self.last_movement_time = now_ms
            return 'right'

        return None
