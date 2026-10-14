# Volition — Copyright (c) 2026 Adhrit Pradeep. Licensed under GPL-3.0 (see LICENSE).
# Built on NPG-Lite-SNES by Upside Down Labs (GPL-3.0).
"""
Volition - Intent Engine
========================
Channel layout:
  CH1 → EEG  
  CH2 → EMG  Right arm
  CH3 → EMG  Left arm

Two EEG headband modes with different detection profiles:

  PFC (Prefrontal Cortex — Fp1/Fp2 forehead placement)
    Strong cheek twitch artifacts, unreliable blinks
    Intents: CH2/CH3 EMG + CHEEK_TWITCH + JAW_CLENCH + FOCUS

  VC (Visual Cortex — O1/O2 back of head placement)
    Clear blinks, no cheek artifacts, strong alpha
    Intents: CH2/CH3 EMG + BLINK + DOUBLE_BLINK + TRIPLE_BLINK + FOCUS

Each mode has its own TFLite model file.
"""

import time
import csv
import os

def _writable_data_dir() -> str:
    """
    Folder to read/write files that must persist and be visible to the
    user after the app closes (training data CSVs, freshly trained
    models). Matches tflite_classifier._writable_data_dir() — kept as
    a separate small copy here rather than a cross-import, since
    intent_engine.py has no other dependency on tflite_classifier.py
    and this avoids import-order coupling between the two modules.

    Resolves to the exe's own folder when frozen (NOT sys._MEIPASS,
    which is temporary and wiped on exit), or the script's folder when
    running from source.
    """
    import sys
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
from collections import deque
from dataclasses import dataclass
from typing import Optional


# ── Snapshot ──────────────────────────────────────────────────────────────────

@dataclass
class SignalSnapshot:
    timestamp: float
    ch2_emg:   float
    ch3_emg:   float
    eeg_beta:  float
    eeg_blink: float
    eeg_jaw:   float
    intent:    str = "NONE"


# ── Adaptive threshold ────────────────────────────────────────────────────────

class AdaptiveThreshold:
    def __init__(self, initial: float, window: int = 200):
        self.threshold = initial
        self._w        = deque(maxlen=window)
        self._max_seen = 0.0

    def update(self, v: float):
        self._w.append(v)
        if v > 0.01:
            self._max_seen = max(self._max_seen, v)

    def is_triggered(self, v: float) -> bool:
        return v > self.threshold

    def auto_calibrate(self, pct: float = 0.60) -> bool:
        """
        Calibrates threshold from the 90th percentile of observed
        nonzero samples, scaled by pct.

        SAFETY FLOOR: when the floor tracker's baseline sits at a high
        percentile (e.g. 0.95), most corrected samples clamp to exactly
        0 and only a thin band of tiny noise spikes survives as
        nonzero. Calibrating purely against that thin band can produce
        a threshold near zero, which then falsely fires on ordinary
        noise. Guarding against this by never letting the calibrated
        threshold fall below a meaningful fraction of the single
        largest value ever observed (_max_seen) — a real gesture
        should produce a much bigger spike than resting noise ever
        does, so anchoring to a fraction of that peak keeps the
        threshold meaningful even when the percentile-based estimate
        collapses.
        """
        samples = sorted(x for x in self._w if x > 0.01)
        if len(samples) < 10:
            return False
        p90 = samples[int(len(samples) * 0.90)]
        if p90 <= 0:
            return False

        percentile_threshold = p90 * pct
        safety_floor = self._max_seen * 0.35
        self.threshold = max(percentile_threshold, safety_floor)
        return True

    def set_threshold(self, v: float):
        self.threshold = v


# ── Passive floor tracker ─────────────────────────────────────────────────────

class PassiveFloorTracker:
    """
    Continuously learns the resting baseline of a signal purely by
    observing traffic in the background — no "hold still" step required.

    The baseline is set to the CEILING of resting activity (a HIGH
    percentile, e.g. 0.95) rather than the minimum or mean. Every
    signal in Volition uses this same convention consistently: the
    tracked floor represents the maximum voltage typically seen while
    at rest, so only activity that clearly exceeds normal resting
    noise/tone survives the subtraction and can trigger a gesture.

    Why the ceiling, not a low percentile: EMG at rest still carries
    muscle tone, and EEG-derived envelopes (blink/jaw) carry constant
    ambient noise (micro-tremor, environmental EMI). A low percentile
    sits well below where that resting noise ceiling actually is, so
    ordinary noise bursts during rest keep poking above it and get
    misread as real gestures. Anchoring the floor to the observed
    ceiling instead means the classifier only reacts to signal that
    genuinely stands out above everything rest normally produces.

    The floor updates slowly and only recomputes periodically (not every
    tick) so a single sustained gesture can't drag it upward.
    """

    WINDOW_SIZE    = 900    # ~30s at 30Hz — long enough that rest periods
                            # dominate even during active use
    MIN_SAMPLES    = 150    # ~5s — minimum data before floor is trusted
    RECOMPUTE_SECS = 1.0    # how often to recompute (expensive-ish sort)

    def __init__(self, name: str = "", floor_pct: float = 0.10):
        self.name             = name
        self.floor_pct        = floor_pct
        self._window          = deque(maxlen=self.WINDOW_SIZE)
        self.floor            = 0.0
        self.is_established   = False
        self._last_recompute  = 0.0

    def update(self, raw_value: float):
        """Feed the RAW (uncorrected) value — always, every tick,
        regardless of whether a gesture is currently firing."""
        self._window.append(raw_value)

        if len(self._window) < self.MIN_SAMPLES:
            return

        now = time.time()
        if now - self._last_recompute < self.RECOMPUTE_SECS:
            return
        self._last_recompute = now

        samples = sorted(self._window)
        idx = min(len(samples) - 1, max(0, int(len(samples) * self.floor_pct)))
        new_floor = samples[idx]

        was_established = self.is_established
        self.floor = new_floor
        self.is_established = True
        if not was_established:
            print(f"[FloorTracker] {self.name} baseline established: "
                  f"floor={self.floor:.1f} (pct={self.floor_pct})")

    def corrected(self, raw_value: float) -> float:
        """Return the value with the learned resting floor subtracted.
        Clamped at 0 — a signal can't go meaningfully negative once
        the DC/muscle-tone floor is removed."""
        return max(0.0, raw_value - self.floor)

    def reset(self):
        self._window.clear()
        self.floor = 0.0
        self.is_established = False
        self._last_recompute = 0.0




class HoldGate:
    """Signal must stay above threshold for min_samples consecutive 30Hz ticks."""
    def __init__(self, min_samples: int = 8):
        self.min_samples = min_samples
        self._count      = 0
        self._fired      = False

    def update(self, triggered: bool) -> bool:
        if triggered:
            self._count += 1
            if self._count >= self.min_samples and not self._fired:
                self._fired = True
                return True
        else:
            self._count = 0
            self._fired = False
        return False

    def reset(self):
        self._count = 0
        self._fired = False


# ── Blink counter (Visual Cortex mode) ───────────────────────────────────────

class JawClenchGate:
    """
    Jaw clench is differentiated from cheek twitch purely by duration —
    both read the same eeg_jaw envelope. Without this gate, jaw clench
    used a raw per-tick threshold check with NO duration requirement,
    so it fired on almost every tick the signal was above threshold —
    including during the rise/plateau of an ordinary cheek twitch. That
    made both intents fire off the exact same physical event ("rising
    in tandem"), since cheek twitch fires once after its debounced fall
    while jaw clench was firing repeatedly throughout the same event.

    Fix: require the signal to stay above threshold for MIN_MS
    (genuinely longer than cheek twitch's 50-220ms window) before jaw
    clench can fire at all. Also enforce mutual exclusivity in both
    directions via notify_cheek_twitch()/notify_jaw_clench(): whichever
    detector fires first locks the other out for LOCKOUT_MS, so a
    single event can never register as both.
    """
    MIN_MS      = 250    # jaw must persist beyond the cheek-twitch window
    LOCKOUT_MS  = 500    # confirmed cheek/jaw event blocks the other detector

    def __init__(self):
        self._onset_ms       = 0
        self._in_clench      = False
        self._fired          = False
        self._lockout_until  = 0
        self._peak_value     = 0.0
        self.last_peak_value = 0.0


    def notify_cheek_twitch(self):
        """Call whenever CheekTwitchDetector fires — locks out jaw clench."""
        self._lockout_until = int(time.time() * 1000) + self.LOCKOUT_MS
        self._in_clench = False
        self._fired     = False
        self._peak_value = 0.0

    def process(self, envelope: float, lower: float, upper: float = None) -> bool:
        now_ms = int(time.time() * 1000)
        # Jaw clench uses the lower threshold + duration as its detection gate.
        # The previous upper bound rejected strong, valid clenches before the
        # 300 ms hold could complete. True channel saturation is handled by the
        # signal-health monitor; an optional upper bound is retained for callers
        # that explicitly want one.
        triggered = envelope > lower if upper is None else lower < envelope <= upper

        if self._lockout_until and now_ms < self._lockout_until:
            self._in_clench = False
            self._fired     = False
            return False

        if triggered and not self._in_clench:
            self._in_clench = True
            self._onset_ms  = now_ms
            self._fired     = False
            self._peak_value = envelope

        elif triggered and self._in_clench:
            self._peak_value = max(self._peak_value, envelope)
            if not self._fired and (now_ms - self._onset_ms) >= self.MIN_MS:
                self._fired = True
                self.last_peak_value = self._peak_value
                return True

        elif not triggered:
            self._in_clench = False
            self._fired     = False
            self._peak_value = 0.0

        return False

    def reset(self):
        self._onset_ms      = 0
        self._in_clench     = False
        self._fired         = False
        self._lockout_until = 0
        self._peak_value    = 0.0
        self.last_peak_value = 0.0


class BlinkCounter:
    """
    Counts blinks with duration validation.
    Real blink: 80–450ms above threshold.
    Shorter = artifact. Longer = jaw clench / eye hold.
    emg_active flag suppresses during arm movements.

    threshold_upper rejects anything ABOVE the upper bound too — a
    signal that large is more likely a saturation event or gross
    artifact than a genuine blink, which should have a fairly
    consistent amplitude range once calibrated.
    """
    WINDOW_MS    = 1200
    SETTLE_MS    = 350
    MIN_GAP_MS   = 120
    MIN_BLINK_MS = 80
    MAX_BLINK_MS = 450

    def __init__(self):
        self._times:   list[int] = []
        self._in_blink           = False
        self._onset_ms: int      = 0
        self._counted:  bool     = False
        self._fired:    bool     = False

    def process(self, envelope: float, threshold: float,
                emg_active: bool = False,
                threshold_upper: float = None) -> Optional[str]:
        now_ms = int(time.time() * 1000)
        in_band = envelope > threshold
        if threshold_upper is not None:
            in_band = in_band and envelope <= threshold_upper
        triggered = in_band and not emg_active

        if triggered and not self._in_blink:
            self._in_blink = True
            self._onset_ms = now_ms
            self._counted  = False
        elif triggered and self._in_blink:
            dur = now_ms - self._onset_ms
            if dur > self.MAX_BLINK_MS:
                self._counted = True  # too long — not a blink
            elif dur >= self.MIN_BLINK_MS and not self._counted:
                if not self._times or now_ms - self._times[-1] >= self.MIN_GAP_MS:
                    self._times.append(now_ms)
                    self._counted = True
                    self._fired   = False
        elif not triggered:
            self._in_blink = False

        self._times = [t for t in self._times if now_ms - t <= self.WINDOW_MS]

        if self._times and not self._fired and not triggered:
            if now_ms - self._times[-1] >= self.SETTLE_MS:
                count         = len(self._times)
                self._fired   = True
                self._times.clear()
                if count >= 3: return 'triple'
                if count == 2: return 'double'
                return 'single'
        return None


# ── Cheek twitch detector (PFC mode) ─────────────────────────────────────────

class CheekTwitchDetector:
    """
    Detects deliberate cheek twitches at Fp1/Fp2 placement.

    In PFC position, cheek muscle EMG appears as a large amplitude burst
    on the EEG channel — larger and shorter than a blink (which also
    appears large at Fp1/Fp2 but with slower onset).

    Detection criteria:
      - Envelope > threshold (high — cheek twitches are large)
      - Duration: 50–220ms  (shorter than blinks, sharper than jaw clenches)
      - PEAK must clear threshold by a real margin (see PEAK_MARGIN below)
      - Cooldown: 400ms after firing to prevent double-firing
      - Falling edge is debounced so brief noise dips mid-twitch don't
        prematurely end the window

    PEAK TRACKING — the actual fix for "intensity 0.00" false fires:
    the old version of this detector only tracked timestamps (onset/
    fall), never the actual signal amplitude during the twitch window.
    By the time a debounced fall event resolves and fires, the signal
    has often already decayed back toward the floor — so any intensity
    computed from "whatever eeg_jaw happens to be at this exact tick"
    reads near 0, even for a real detection. Worse, without tracking
    the peak, a signal that only barely grazed the threshold for a
    single noisy sample could still satisfy the duration window and
    fire, since nothing ever checked HOW FAR above threshold it went.

    Now the detector tracks the peak envelope value seen during each
    candidate twitch window, requires that peak to clear the threshold
    by PEAK_MARGIN (not just graze it), and exposes the peak via
    last_peak_value so the caller can compute intensity from the real
    peak instead of a possibly-decayed instantaneous value.
    """
    MIN_MS           = 50
    MAX_MS           = 220
    COOL_MS          = 400
    FALL_DEBOUNCE_MS = 60     # brief dips below threshold don't end the window
    PEAK_MARGIN      = 1.15   # peak must be >=15% above threshold, not just graze it

    def __init__(self):
        self._in_twitch      = False
        self._onset_ms       = 0
        self._last_fire_ms   = 0
        self._fired          = False
        self._fall_onset_ms  = None
        self._peak_value     = 0.0
        self.last_peak_value = 0.0   # exposed for intensity calculation
        self._lockout_until  = 0     # set by notify_jaw_clench()

    def notify_jaw_clench(self):
        """Call whenever JawClenchGate fires — locks out cheek twitch so
        a sustained clench can't also register as a twitch."""
        self._lockout_until = int(time.time() * 1000) + 500
        self._in_twitch     = False
        self._fired         = False
        self._fall_onset_ms = None
        self._peak_value    = 0.0

    def process(self, envelope: float, threshold: float,
                emg_active: bool = False) -> bool:
        """Returns True when a cheek twitch is confirmed."""
        now_ms    = int(time.time() * 1000)
        triggered = envelope > threshold and not emg_active

        if now_ms < self._lockout_until:
            self._in_twitch  = False
            self._fired      = False
            self._peak_value = 0.0
            return False

        if now_ms - self._last_fire_ms < self.COOL_MS:
            if not triggered:
                self._in_twitch  = False
                self._fired      = False
                self._peak_value = 0.0
            return False

        if triggered:
            self._fall_onset_ms = None
            self._peak_value = max(self._peak_value, envelope)

            if not self._in_twitch:
                self._in_twitch  = True
                self._onset_ms   = now_ms
                self._fired      = False
                self._peak_value = envelope

            else:
                dur = now_ms - self._onset_ms
                if dur > self.MAX_MS:
                    # Too long — this is a jaw clench, not a twitch
                    self._fired = True

        elif not triggered and self._in_twitch:
            if self._fall_onset_ms is None:
                self._fall_onset_ms = now_ms

            if now_ms - self._fall_onset_ms >= self.FALL_DEBOUNCE_MS:
                dur  = self._fall_onset_ms - self._onset_ms
                peak = self._peak_value
                self._in_twitch      = False
                self._fall_onset_ms  = None
                self._peak_value     = 0.0

                if (self.MIN_MS <= dur <= self.MAX_MS
                        and not self._fired
                        and peak >= threshold * self.PEAK_MARGIN):
                    self._last_fire_ms   = now_ms
                    self.last_peak_value = peak
                    return True

        return False


class CheekJawEventResolver:
    """
    Shared PFC event resolver for cheek twitch and jaw clench.

    Both gestures remain adaptive: their live thresholds are supplied on every
    sample. The resolver only changes how a candidate event is evaluated. It
    waits for the event to settle, tracks how much of the event each signal was
    actually active, and then commits to one gesture only when exactly one
    gesture's temporal profile is satisfied.

    Safety invariant:
      - cheek qualifies only -> CHEEK_TWITCH
      - jaw qualifies only   -> JAW_CLENCH
      - both qualify         -> NONE
      - neither qualifies    -> NONE

    This keeps ambiguous cheek/jaw events from becoming commands while still
    allowing the thresholds themselves to adapt continuously.
    """
    END_DEBOUNCE_MS = 80
    CHEEK_MIN_MS = 50
    CHEEK_MAX_MS = 240
    JAW_MIN_MS = 250
    PEAK_MARGIN = 1.15

    def __init__(self):
        self._in_event = False
        self._onset_ms = 0
        self._last_active_ms = 0
        self._last_tick_ms = 0
        self._cheek_active_ms = 0.0
        self._jaw_active_ms = 0.0
        self._event_cheek_peak = 0.0
        self._event_jaw_peak = 0.0
        self.last_cheek_peak = 0.0
        self.last_jaw_peak = 0.0
        self.last_event = "NONE"
        self._blocked_until = 0

    def process(self, cheek_signal: float, cheek_threshold: float,
                jaw_signal: float, jaw_threshold: float) -> Optional[str]:
        now_ms = int(time.time() * 1000)

        # A candidate is driven by either dedicated signal crossing its own
        # adaptive threshold. We do not freeze thresholds here.
        cheek_active = cheek_signal > cheek_threshold
        jaw_active = jaw_signal > jaw_threshold
        any_active = cheek_active or jaw_active

        # Short re-arm window prevents the same physical event from being
        # split into multiple commands by a brief threshold dip.
        if now_ms < self._blocked_until:
            if not any_active:
                self._last_tick_ms = now_ms
            return None

        if self._last_tick_ms:
            dt = max(0, min(now_ms - self._last_tick_ms, 100))
        else:
            dt = 0
        self._last_tick_ms = now_ms

        if any_active:
            if not self._in_event:
                self._in_event = True
                self._onset_ms = now_ms
                self._cheek_active_ms = 0.0
                self._jaw_active_ms = 0.0
                self._event_cheek_peak = cheek_signal if cheek_active else 0.0
                self._event_jaw_peak = jaw_signal if jaw_active else 0.0
            else:
                self._event_cheek_peak = max(self._event_cheek_peak,
                                             cheek_signal if cheek_active else 0.0)
                self._event_jaw_peak = max(self._event_jaw_peak,
                                           jaw_signal if jaw_active else 0.0)

            if cheek_active:
                self._cheek_active_ms += dt
            if jaw_active:
                self._jaw_active_ms += dt
            self._last_active_ms = now_ms
            return None

        if self._in_event:
            # Wait for a real return below both thresholds before deciding.
            if now_ms - self._last_active_ms >= self.END_DEBOUNCE_MS:
                event_duration = max(0, self._last_active_ms - self._onset_ms)
                cheek_peak_ok = (
                    self._event_cheek_peak >= cheek_threshold * self.PEAK_MARGIN
                )
                jaw_peak_ok = self._event_jaw_peak >= jaw_threshold

                cheek_qualifies = (
                    cheek_peak_ok and
                    self.CHEEK_MIN_MS <= self._cheek_active_ms <= self.CHEEK_MAX_MS
                )
                jaw_qualifies = (
                    jaw_peak_ok and self._jaw_active_ms >= self.JAW_MIN_MS
                )

                self.last_cheek_peak = self._event_cheek_peak
                self.last_jaw_peak = self._event_jaw_peak

                # Absolute safety rule: ambiguity never becomes a command.
                if cheek_qualifies and jaw_qualifies:
                    result = "NONE"
                elif cheek_qualifies:
                    result = "EEG_CHEEK_TWITCH"
                elif jaw_qualifies:
                    result = "EEG_JAW_CLENCH"
                else:
                    result = "NONE"

                self.last_event = result
                self._in_event = False
                self._onset_ms = 0
                self._last_active_ms = 0
                self._cheek_active_ms = 0.0
                self._jaw_active_ms = 0.0
                self._event_cheek_peak = 0.0
                self._event_jaw_peak = 0.0
                self._blocked_until = now_ms + 250
                return result if result != "NONE" else None

        return None

    @property
    def in_event(self) -> bool:
        return self._in_event

    def adaptation_allowed(self, cheek_signal: float, cheek_threshold: float,
                           jaw_signal: float, jaw_threshold: float) -> bool:
        """Whether this tick is safe to teach the cheek/jaw thresholds.

        Adaptation remains continuous, but only resting-looking samples are
        allowed into the two gesture threshold learners. During a candidate
        event and a short recovery window, gesture/post-gesture signal is
        excluded so the adaptive thresholds do not learn the gesture as
        baseline. This applies only to PFC cheek/jaw thresholds.
        """
        now_ms = int(time.time() * 1000)
        if self._in_event or now_ms < self._blocked_until:
            return False
        return (cheek_signal <= cheek_threshold and
                jaw_signal <= jaw_threshold)

    def reset(self):
        self._in_event = False
        self._onset_ms = 0
        self._last_active_ms = 0
        self._last_tick_ms = 0
        self._cheek_active_ms = 0.0
        self._jaw_active_ms = 0.0
        self._event_cheek_peak = 0.0
        self._event_jaw_peak = 0.0
        self.last_cheek_peak = 0.0
        self.last_jaw_peak = 0.0
        self.last_event = "NONE"
        self._blocked_until = 0


# ── Intent engine ─────────────────────────────────────────────────────────────

# Intents active in each mode
PFC_INTENTS_BASE = [
    "CH2_STRONG", "CH2_LIGHT",
    "CH3_STRONG", "CH3_LIGHT",
    "BOTH_STRONG", "BOTH_LIGHT",
    "EEG_CHEEK_TWITCH",
    "EEG_JAW_CLENCH",
    "EEG_FOCUS_HIGH",
]

PFC_INTENTS_WITH_BLINK = PFC_INTENTS_BASE + [
    "EEG_BLINK",
    "EEG_DOUBLE_BLINK",
    "EEG_TRIPLE_BLINK",
]

VC_INTENTS = [
    "CH2_STRONG", "CH2_LIGHT",
    "CH3_STRONG", "CH3_LIGHT",
    "BOTH_STRONG", "BOTH_LIGHT",
    "EEG_BLINK",
    "EEG_DOUBLE_BLINK",
    "EEG_TRIPLE_BLINK",
    "EEG_FOCUS_HIGH",
]

ALL_POSSIBLE_INTENTS = sorted(set(PFC_INTENTS_WITH_BLINK + VC_INTENTS))

PFC_CAPTURE_LABELS_BASE = [
    "CH2_STRONG", "CH2_LIGHT",
    "CH3_STRONG", "CH3_LIGHT",
    "BOTH_STRONG", "BOTH_LIGHT",
    "EEG_CHEEK_TWITCH",
    "EEG_JAW_CLENCH",
    "EEG_FOCUS_HIGH",
    "EEG_ERROR",
    "REST",
]

PFC_CAPTURE_LABELS_WITH_BLINK = [
    "CH2_STRONG", "CH2_LIGHT",
    "CH3_STRONG", "CH3_LIGHT",
    "BOTH_STRONG", "BOTH_LIGHT",
    "EEG_CHEEK_TWITCH",
    "EEG_BLINK",
    "EEG_DOUBLE_BLINK",
    "EEG_TRIPLE_BLINK",
    "EEG_JAW_CLENCH",
    "EEG_FOCUS_HIGH",
    "EEG_ERROR",
    "REST",
]

VC_CAPTURE_LABELS = [
    "CH2_STRONG", "CH2_LIGHT",
    "CH3_STRONG", "CH3_LIGHT",
    "BOTH_STRONG", "BOTH_LIGHT",
    "EEG_BLINK",
    "EEG_DOUBLE_BLINK",
    "EEG_TRIPLE_BLINK",
    "EEG_FOCUS_HIGH",
    "EEG_ERROR",
    "REST",
]

MODEL_PATHS = {
    "pfc": "volition_model_pfc.tflite",
    "vc":  "volition_model_vc.tflite",
}


class IntentEngine:

    COOLDOWN = {
        "CH2_STRONG":        0.3,   # tighter — TFLite handles its own smoothing
        "CH2_LIGHT":         0.3,
        "CH3_STRONG":        0.3,
        "CH3_LIGHT":         0.3,
        "BOTH_STRONG":       0.4,
        "BOTH_LIGHT":        0.4,
        "EEG_CHEEK_TWITCH":  0.4,
        "EEG_BLINK":         0.5,
        "EEG_DOUBLE_BLINK":  0.8,
        "EEG_TRIPLE_BLINK":  0.8,
        "EEG_JAW_CLENCH":    0.7,
        "EEG_FOCUS_HIGH":    1.0,
    }

    # Separate tighter cooldowns used when TFLite is active
    # since the model already handles temporal smoothing
    COOLDOWN_TFLITE = {
        "CH2_STRONG":        0.15,
        "CH2_LIGHT":         0.15,
        "CH3_STRONG":        0.15,
        "CH3_LIGHT":         0.15,
        "BOTH_STRONG":       0.20,
        "BOTH_LIGHT":        0.20,
        "EEG_CHEEK_TWITCH":  0.25,
        "EEG_BLINK":         0.35,
        "EEG_DOUBLE_BLINK":  0.60,
        "EEG_TRIPLE_BLINK":  0.60,
        "EEG_JAW_CLENCH":    0.50,
        "EEG_FOCUS_HIGH":    0.80,
    }

    BOTH_WINDOW = 0.15

    def __init__(self, mode: str = "pfc"):
        # EMG thresholds
        self.th_ch2_strong = AdaptiveThreshold(600.0)
        self.th_ch2_light  = AdaptiveThreshold(300.0)
        self.th_ch3_strong = AdaptiveThreshold(600.0)
        self.th_ch3_light  = AdaptiveThreshold(300.0)

        # Hold gates (EMG)
        self._gate_ch2_strong = HoldGate(min_samples=8)
        self._gate_ch2_light  = HoldGate(min_samples=5)
        self._gate_ch3_strong = HoldGate(min_samples=8)
        self._gate_ch3_light  = HoldGate(min_samples=5)
        self.hold_strong_samples = 8
        self.hold_light_samples  = 5

        # EEG thresholds
        self.th_blink        = AdaptiveThreshold(150.0)   # lower bound
        self.th_blink_upper  = AdaptiveThreshold(280.0)   # upper bound —
                                                            # above this, treat
                                                            # as artifact, not a blink
        self.th_jaw          = AdaptiveThreshold(200.0)   # lower bound
        self.th_jaw_upper    = AdaptiveThreshold(450.0)   # upper bound
        self.th_cheek_twitch = AdaptiveThreshold(250.0)   # PFC only
        self.th_eeg_focus    = AdaptiveThreshold(40.0)

        # Saturation lockout
        # After a strong cheek twitch, the BioAmp capacitors take ~5s
        # to discharge. During this decay the signal is elevated and
        # fires false jaw/focus/twitch events. We detect saturation
        # (signal > SAT_RATIO × jaw threshold) and lock out ALL EEG
        # detection for LOCKOUT_SECS until signal returns to baseline.
        self._LOCKOUT_SECS   = 4.5
        # The EEG channel health monitor already detects true saturation.
        # Keep this envelope guard only for extreme excursions so a strong
        # real jaw clench is not mistaken for saturation.
        self._SAT_RATIO      = 8.0    # jaw_threshold × this = extreme excursion
        self._lockout_until  = 0.0
        self._saturation_latched = False
        self._saturation_recovery_ratio = 0.50
        self.eeg_in_lockout  = False  # exposed for UI status
        self._eeg_lockout_source = None  # "saturation" | "model" — for UI messaging

        # Trained "this doesn't look like real EEG" detector — a second,
        # learned layer on top of the hardware saturation check above.
        # Captured/trained as an ordinary gesture class ("EEG_ERROR")
        # alongside real gestures; when the model predicts it, EEG
        # intents get suppressed the same way a hardware saturation
        # event does, just via a shorter lockout since it's a softer
        # signal than a confirmed hardware fault.
        self.EEG_MODEL_ERROR_LOCKOUT_SECS = 2.0

        self._blink_counter   = BlinkCounter()
        # PFC cheek/jaw now share one adaptive event resolver. The legacy
        # per-detector objects remain in the file for compatibility but are
        # no longer used for live PFC classification.
        self._cheek_jaw_resolver = CheekJawEventResolver()
        self._ch2_last: float = 0.0
        self._ch3_last: float = 0.0

        self._last_fire: dict[str, float] = {}

        # Mode — 'pfc' or 'vc'
        self._mode = mode
        self.pfc_blink_enabled = False   # toggle via UI checkbox

        # TFLite
        self._tflite = None
        # TFLite returns a classification for the current frame/window.
        # Keep a latch so one sustained prediction becomes one discrete
        # intent event rather than re-firing every cooldown interval.
        self._tflite_latched_intent = None
        self._last_tflite_confidence = 0.0
        # EEG_ERROR is intentionally harder to trigger than ordinary intents:
        # require sustained, high-confidence agreement rather than one frame.
        self._eeg_error_streak = 0
        self._eeg_error_last_time = 0.0
        self._eeg_error_lock_conf = 0.80
        self._eeg_error_required_frames = 3
        self._load_tflite()

        # Data capture
        self._capture_mode   = False
        self._capture_label  = "UNKNOWN"
        self._capture_buffer: list[SignalSnapshot] = []
        self._capture_rejected_count = 0   # samples dropped for bad signal health
        self._capture_path   = "volition_training_data.csv"

        # Callbacks
        self.on_intent   = None
        self.on_snapshot = None
        self.on_mode_changed = None   # fn(mode, active_intents)

        # Calibration
        self._samples_since_start = 0
        self._auto_calibrated     = False
        self._calibration_window  = 500

        # Passive baseline floor — continuously learned in the background,
        # no manual "hold still" step needed. Subtracted from raw values
        # before anything else (thresholds, detectors, TFLite) sees them.
        # All four signals now track the CEILING of resting activity
        # (high percentile), not a mix of low/high — per direct
        # request: baseline should always sit at the maximum resting
        # voltage for every signal, consistently. This also gives more
        # headroom against incidental noise/movement across the board,
        # not just for the EEG-derived signals as before.
        self._floor_ch2   = PassiveFloorTracker("CH2",   floor_pct=0.95)
        self._floor_ch3   = PassiveFloorTracker("CH3",   floor_pct=0.95)
        self._floor_blink = PassiveFloorTracker("BLINK", floor_pct=0.95)
        self._floor_jaw   = PassiveFloorTracker("JAW",   floor_pct=0.95)

        # Channel health — set via update_channel_health() each tick from
        # the main app's SignalHealthMonitor instances. A channel flagged
        # unhealthy (SATURATED/NOISY/NO_SIGNAL) has its intents vetoed
        # before firing, since those fault conditions can trip adaptive
        # thresholds and look identical to real gestures.
        self._ch2_healthy = True
        self._ch3_healthy = True
        self._eeg_healthy = True
        self._eeg_detection_allowed = False   # true only once calibrated + healthy

        self.signal_quality = {"ch2_emg": 0.0, "ch3_emg": 0.0, "eeg": 0.0}

    def update_channel_health(self, ch2_healthy: bool = True,
                               ch3_healthy: bool = True,
                               eeg_healthy: bool = True):
        """Called every tick from the main app with SignalHealthMonitor
        results. Unhealthy channels have their intents vetoed."""
        self._ch2_healthy = ch2_healthy
        self._ch3_healthy = ch3_healthy
        self._eeg_healthy = eeg_healthy

    def _intent_channel_ok(self, intent: str) -> bool:
        """Veto an intent if the channel(s) it comes from are unhealthy."""
        if intent.startswith("CH2_"):
            return self._ch2_healthy
        if intent.startswith("CH3_"):
            return self._ch3_healthy
        if intent.startswith("BOTH_"):
            return self._ch2_healthy and self._ch3_healthy
        if intent.startswith("EEG_"):
            return self._eeg_healthy
        return True

    def _capture_label_channel_ok(self, label: str) -> bool:
        """
        Same idea as _intent_channel_ok, but for DATA CAPTURE labels
        rather than live intents — this is what actually improves
        dataset quality: a sample captured while an electrode is
        loose, saturated, or disconnected gets silently dropped before
        it ever reaches the training CSV, instead of quietly teaching
        the model that noise looks like a real gesture.

        REST is treated specially — it requires ALL channels healthy,
        not just the ones nominally "used" by the label. REST defines
        what "nothing is happening" looks like for every signal at
        once, so contaminating it with a bad channel corrupts the
        baseline the whole classifier is measured against.
        """
        if label == "REST":
            return self._ch2_healthy and self._ch3_healthy and self._eeg_healthy
        return self._intent_channel_ok(label)

    # ── Mode ──────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def active_intents(self) -> list[str]:
        if self._mode == "vc":
            return VC_INTENTS
        return PFC_INTENTS_WITH_BLINK if self.pfc_blink_enabled \
               else PFC_INTENTS_BASE

    @property
    def capture_labels(self) -> list[str]:
        if self._mode == "vc":
            return VC_CAPTURE_LABELS
        return PFC_CAPTURE_LABELS_WITH_BLINK if self.pfc_blink_enabled \
               else PFC_CAPTURE_LABELS_BASE

    def set_mode(self, mode: str):
        """Switch between 'pfc' and 'vc'. Reloads TFLite model for that mode."""
        if mode not in ("pfc", "vc"):
            return
        self._mode = mode
        # A new model/mode is a new prediction stream; re-arm the event latch.
        self._tflite_latched_intent = None
        self._last_tflite_confidence = 0.0
        self.force_recalibrate()
        self._load_tflite()
        print(f"[IntentEngine] Mode → {mode.upper()}  "
              f"Active intents: {self.active_intents}")
        if self.on_mode_changed:
            self.on_mode_changed(mode, self.active_intents)

    # ── TFLite ────────────────────────────────────────────────────────

    def _load_tflite(self):
        path = MODEL_PATHS.get(self._mode, "")
        try:
            from tflite_classifier import TFLiteClassifier
            self._tflite = TFLiteClassifier(model_path=path)
            if self._tflite.is_loaded:
                print(f"[IntentEngine] TFLite ({self._mode.upper()}) active.")
            else:
                print(f"[IntentEngine] No TFLite model for {self._mode.upper()} "
                      f"— using thresholds.")
        except Exception as e:
            print(f"[IntentEngine] TFLite unavailable: {e}")
            self._tflite = None

    def reload_tflite(self):
        # A reloaded model starts a fresh prediction stream.
        self._tflite_latched_intent = None
        self._last_tflite_confidence = 0.0
        # EEG_ERROR is intentionally harder to trigger than ordinary intents:
        # require sustained, high-confidence agreement rather than one frame.
        self._eeg_error_streak = 0
        self._eeg_error_last_time = 0.0
        self._eeg_error_lock_conf = 0.80
        self._eeg_error_required_frames = 3
        self._load_tflite()

    @property
    def tflite_active(self) -> bool:
        return self._tflite is not None and self._tflite.is_loaded

    # ── Main entry ────────────────────────────────────────────────────

    def process_signals(
        self,
        ch2_emg:   float = 0.0,
        ch3_emg:   float = 0.0,
        eeg_beta:  float = 0.0,
        eeg_blink: float = 0.0,
        eeg_jaw:   float = 0.0,
    ) -> Optional[str]:

        now = time.time()

        # ── Passive floor correction ──────────────────────────────────
        # Feed raw values into the floor trackers (they need the true
        # raw signal to keep learning), then replace the working values
        # with the floor-corrected versions for everything downstream.
        self._floor_ch2.update(ch2_emg)
        self._floor_ch3.update(ch3_emg)
        self._floor_blink.update(eeg_blink)
        self._floor_jaw.update(eeg_jaw)

        ch2_emg   = self._floor_ch2.corrected(ch2_emg)
        ch3_emg   = self._floor_ch3.corrected(ch3_emg)
        eeg_blink = self._floor_blink.corrected(eeg_blink)
        eeg_jaw   = self._floor_jaw.corrected(eeg_jaw)

        # Update EMG thresholds
        self.th_ch2_strong.update(ch2_emg)
        self.th_ch2_light.update(ch2_emg)
        self.th_ch3_strong.update(ch3_emg)
        self.th_ch3_light.update(ch3_emg)

        # Update EEG thresholds. PFC cheek/jaw remain adaptive, but their
        # threshold learners only absorb resting-looking samples. This keeps
        # real gesture bursts and their immediate recovery from becoming the
        # new baseline while still allowing the thresholds to drift with
        # changing noise/intensity over time. Other EEG adaptation is unchanged.
        self.th_blink.update(eeg_blink)
        if self._mode == "pfc":
            if self._cheek_jaw_resolver.adaptation_allowed(
                    eeg_blink, self.th_cheek_twitch.threshold,
                    eeg_jaw, self.th_jaw.threshold):
                self.th_jaw.update(eeg_jaw)
                self.th_cheek_twitch.update(eeg_blink)
        else:
            self.th_jaw.update(eeg_jaw)
            self.th_cheek_twitch.update(eeg_blink)
        self.th_eeg_focus.update(eeg_beta)

        # Track per-arm activation — only when arm is dominant
        ch2_norm_q = ch2_emg / max(self.th_ch2_light.threshold, 1)
        ch3_norm_q = ch3_emg / max(self.th_ch3_light.threshold, 1)
        total_q    = ch2_norm_q + ch3_norm_q
        if total_q > 0:
            if ch2_norm_q / total_q > 0.50:
                self._ch2_last = now
            if ch3_norm_q / total_q > 0.50:
                self._ch3_last = now

        # ── Saturation lockout ────────────────────────────────────────
        # Detect an extreme jaw/cheek excursion and start the EEG lockout.
        # IMPORTANT: do not restart the timer on every tick while the same
        # excursion is still high. The safeguard latches until the signal
        # first falls back below a recovery level, which prevents one long
        # artifact from repeatedly re-triggering the safeguard.
        sat_threshold = self.th_jaw.threshold * self._SAT_RATIO
        sat_recovery = sat_threshold * self._saturation_recovery_ratio

        if self._saturation_latched:
            if eeg_jaw <= sat_recovery:
                self._saturation_latched = False
        elif eeg_jaw > sat_threshold:
            self._saturation_latched = True
            self._lockout_until = now + self._LOCKOUT_SECS
            self._eeg_lockout_source = "saturation"

        self.eeg_in_lockout = self._saturation_latched or (now < self._lockout_until)

        # Signal quality
        self.signal_quality["ch2_emg"] = max(
            self.signal_quality["ch2_emg"] * 0.99, ch2_emg / 1000.0)
        self.signal_quality["ch3_emg"] = max(
            self.signal_quality["ch3_emg"] * 0.99, ch3_emg / 1000.0)
        self.signal_quality["eeg"] = max(
            self.signal_quality["eeg"] * 0.99, eeg_beta / 100.0)

        # Auto-calibrate
        self._samples_since_start += 1
        if not self._auto_calibrated and \
                self._samples_since_start >= self._calibration_window:
            self._calibrate()
            # Start post-calibration EMG detection from a clean state so a
            # gate that accumulated pre-calibration samples cannot fire
            # immediately using the newly calibrated thresholds.
            for g in (self._gate_ch2_strong, self._gate_ch2_light,
                      self._gate_ch3_strong, self._gate_ch3_light):
                g.reset()

        # Mode-specific EEG event detection — skip during lockout, and
        # CRITICALLY also skip until auto-calibration has genuinely
        # completed. Firing gesture detectors against the hardcoded
        # __init__ defaults (th_cheek_twitch=250, etc.) before real
        # calibration data has been gathered is unreliable — a noisy
        # or unstable connection produces bursts that can easily
        # satisfy the duration+peak-margin gate purely from electrical
        # noise, since that gate checks shape, not signal trustworthiness.
        # Also gate on eeg_healthy: a flapping/unstable channel (loose
        # electrode, bad contact) needs to be excluded at the point of
        # detection, not just logged as a warning after the fact.
        emg_active = (
            self.th_ch2_light.is_triggered(ch2_emg) or
            self.th_ch3_light.is_triggered(ch3_emg)
        )

        blink_event = None
        cheek_fired = False
        jaw_fired = False

        eeg_detection_allowed = (
            not self.eeg_in_lockout
            and self._auto_calibrated
            and self._eeg_healthy
        )
        self._eeg_detection_allowed = eeg_detection_allowed   # read by _classify_threshold's jaw-clench check

        if eeg_detection_allowed:
            if self._mode == "vc":
                blink_event = self._blink_counter.process(
                    eeg_blink, self.th_blink.threshold, emg_active,
                    threshold_upper=self.th_blink_upper.threshold)
            elif self._mode == "pfc":
                # Cheek/jaw use one shared event resolver so adaptation can
                # continue while the two gestures are evaluated as a single
                # physical event. Ambiguous events become NONE.
                cheek_jaw_event = self._cheek_jaw_resolver.process(
                    eeg_blink, self.th_cheek_twitch.threshold,
                    eeg_jaw, self.th_jaw.threshold)
                cheek_fired = cheek_jaw_event == "EEG_CHEEK_TWITCH"
                jaw_fired = cheek_jaw_event == "EEG_JAW_CLENCH"
                # Optional blink detection in PFC — uses blink envelope
                # with a lower threshold since blinks are smaller at Fp1/Fp2
                if self.pfc_blink_enabled:
                    blink_event = self._blink_counter.process(
                        eeg_blink,
                        self.th_blink.threshold * 0.7,  # 30% lower for PFC
                        emg_active,
                        threshold_upper=self.th_blink_upper.threshold)

        snap = SignalSnapshot(
            timestamp=now,
            ch2_emg=ch2_emg, ch3_emg=ch3_emg,
            eeg_beta=eeg_beta, eeg_blink=eeg_blink, eeg_jaw=eeg_jaw,
        )

        # Classify
        # Do not allow any EMG-derived intent to escape during startup
        # calibration. Signal data still feeds the adaptive thresholds, but
        # no command can be emitted until calibration is complete.
        if self._auto_calibrated:
            tflite_intent = self._classify_tflite(
                ch2_emg, ch3_emg, eeg_beta, eeg_blink, eeg_jaw, blink_event)
        else:
            tflite_intent = None

        # TFLite produces a *state* (the class it currently predicts), but
        # the UI/HID layer needs a *discrete event*.  Latch the current class
        # until the model returns to REST/None (or another class), so a single
        # sustained gesture cannot fire repeatedly every cooldown interval.
        tflite_event = tflite_intent
        # ── Event resolver ──────────────────────────────────────────────
        # TFLite is treated as a supporting classifier, not an authority.
        # The deterministic event detectors have priority because they operate
        # on the live, user-calibrated signal. In particular, a confirmed jaw
        # clench must not be hidden by an EEG_ERROR or CHEEK_TWITCH prediction.
        #
        # EEG_ERROR is now advisory only: repeated model errors may be useful
        # for diagnostics, but they do NOT hard-lock the user's valid gesture
        # path. True channel-health/saturation protection remains active above.
        tflite_event = None
        if tflite_intent == "EEG_ERROR":
            self._eeg_error_streak = 0
            self._eeg_error_last_time = now
            # Fall through to the deterministic event detectors.
        elif tflite_intent is None:
            self._tflite_latched_intent = None
        elif tflite_intent == self._tflite_latched_intent:
            tflite_event = None
        else:
            self._tflite_latched_intent = tflite_intent
            tflite_event = tflite_intent

        # PFC cheek/jaw events are now committed only by the shared
        # deterministic resolver. Do not let the TFLite state prediction
        # bypass that event-level decision and reclassify a dynamic signal as
        # cheek/jaw on its own. Other PFC TFLite intents remain unchanged.
        if self._mode == "pfc" and cheek_fired:
            intent = "EEG_CHEEK_TWITCH"
        elif self._mode == "pfc" and jaw_fired:
            intent = "EEG_JAW_CLENCH"
        elif self._mode == "pfc" and tflite_event in (
                "EEG_CHEEK_TWITCH", "EEG_JAW_CLENCH"):
            intent = self._classify_threshold(
                snap, blink_event, cheek_fired, jaw_fired)
        elif tflite_event is not None:
            intent = tflite_event
        else:
            intent = self._classify_threshold(
                snap, blink_event, cheek_fired, jaw_fired)

        snap.intent = intent

        if self._capture_mode:
            if self._capture_label_channel_ok(self._capture_label):
                snap.intent = self._capture_label
                self._capture_buffer.append(snap)
            else:
                self._capture_rejected_count += 1

        if self.on_snapshot:
            self.on_snapshot(snap)

        if intent and intent != "NONE" and intent in self.active_intents \
                and self._intent_channel_ok(intent):
            if self._check_cooldown(intent):
                intensity = self._compute_intensity(intent, snap)
                if self.on_intent:
                    self.on_intent(intent, intensity)
                return intent

        return None

    # ── Classification ────────────────────────────────────────────────

    def _classify_tflite(self, ch2, ch3, beta, blink, jaw,
                         blink_event) -> Optional[str]:
        if not self.tflite_active:
            return None
        self._tflite.update_scale(
            self.th_ch2_strong._max_seen,
            self.th_ch3_strong._max_seen,
            self.th_blink._max_seen,
            self.th_jaw._max_seen,
        )
        cls = self._tflite.predict(ch2, ch3, beta, blink, jaw)
        # Preserve the model's confidence for diagnostics/intensity fallback.
        self._last_tflite_confidence = float(
            getattr(self._tflite, "last_probability", 0.0) or 0.0
        )
        if cls == "EEG_ERROR":
            # Sentinel — not a real gesture, never in active_intents.
            # Caller handles this specially (triggers lockout, no
            # threshold fallback).
            return "EEG_ERROR"
        if cls is None or cls not in self.active_intents:
            return None
        return cls

    def _classify_threshold(self, snap: SignalSnapshot,
                             blink_event: Optional[str],
                             cheek_fired: bool,
                             jaw_fired: bool = False) -> str:
        now = time.time()

        ch2_strong = self.th_ch2_strong.is_triggered(snap.ch2_emg)
        ch3_strong = self.th_ch3_strong.is_triggered(snap.ch3_emg)
        ch2_light  = self.th_ch2_light.is_triggered(snap.ch2_emg)
        ch3_light  = self.th_ch3_light.is_triggered(snap.ch3_emg)

        fired_ch2_strong = self._gate_ch2_strong.update(ch2_strong)
        fired_ch3_strong = self._gate_ch3_strong.update(ch3_strong)
        fired_ch2_light  = self._gate_ch2_light.update(ch2_light and not ch2_strong)
        fired_ch3_light  = self._gate_ch3_light.update(ch3_light and not ch3_strong)

        any_emg_fired = (fired_ch2_strong or fired_ch3_strong or
                         fired_ch2_light  or fired_ch3_light)

        if any_emg_fired:
            # ── Dominant channel check ────────────────────────────────
            # Normalise each channel against its own strong threshold so
            # a channel with a naturally lower threshold isn't penalised.
            # If one channel is more than 2× stronger than the other,
            # treat the weaker reading as cross-talk and ignore it.
            th2 = max(self.th_ch2_strong.threshold, 1)
            th3 = max(self.th_ch3_strong.threshold, 1)
            n2  = snap.ch2_emg / th2   # normalised CH2 (1.0 = at strong threshold)
            n3  = snap.ch3_emg / th3   # normalised CH3

            ch2_dominant = n2 > n3 * 2.0   # CH2 is 2× stronger → CH2 only
            ch3_dominant = n3 > n2 * 2.0   # CH3 is 2× stronger → CH3 only
            genuinely_both = not ch2_dominant and not ch3_dominant

            if ch2_dominant:
                if fired_ch2_strong: return "CH2_STRONG"
                if fired_ch2_light:  return "CH2_LIGHT"
                # Gate fired on CH3 but CH2 is dominant — suppress CH3
                return "NONE"

            if ch3_dominant:
                if fired_ch3_strong: return "CH3_STRONG"
                if fired_ch3_light:  return "CH3_LIGHT"
                return "NONE"

            # Genuinely both — both channels independently above threshold
            if genuinely_both:
                if fired_ch2_strong or fired_ch3_strong: return "BOTH_STRONG"
                if fired_ch2_light  or fired_ch3_light:  return "BOTH_LIGHT"

        # Explicit event results from the live detectors take priority over
        # raw threshold comparisons. Ambiguous simultaneous cheek+jaw events
        # are intentionally suppressed; never convert uncertainty into a
        # potentially unsafe command.
        if getattr(self, "_mode", "pfc") == "pfc":
            if cheek_fired and jaw_fired:
                return "NONE"
            if jaw_fired:
                return "EEG_JAW_CLENCH"
            if cheek_fired:
                return "EEG_CHEEK_TWITCH"

        # EEG — mode specific. Gated on eeg_detection_allowed computed
        # earlier — no EEG intent can classify at all until calibration
        # is genuinely complete and the channel is currently healthy,
        # regardless of what raw values look like in the meantime.
        if getattr(self, "_eeg_detection_allowed", False):
            if self._mode == "pfc":
                if cheek_fired:
                    return "EEG_CHEEK_TWITCH"
                if jaw_fired:
                    return "EEG_JAW_CLENCH"
                if self.pfc_blink_enabled:
                    if blink_event == 'triple': return "EEG_TRIPLE_BLINK"
                    if blink_event == 'double': return "EEG_DOUBLE_BLINK"
                    if blink_event == 'single': return "EEG_BLINK"
            elif self._mode == "vc":
                if blink_event == 'triple': return "EEG_TRIPLE_BLINK"
                if blink_event == 'double': return "EEG_DOUBLE_BLINK"
                if blink_event == 'single': return "EEG_BLINK"

            if self.th_eeg_focus.is_triggered(snap.eeg_beta):
                return "EEG_FOCUS_HIGH"

        return "NONE"

    def _compute_intensity(self, intent: str, snap: SignalSnapshot) -> float:
        if "CH2" in intent:
            return min(1.0, snap.ch2_emg / max(self.th_ch2_strong._max_seen, 1))
        if "CH3" in intent:
            return min(1.0, snap.ch3_emg / max(self.th_ch3_strong._max_seen, 1))
        if "BOTH" in intent:
            v = (snap.ch2_emg + snap.ch3_emg) / 2
            return min(1.0, v / max(self.th_ch2_strong._max_seen, 1))
        if "BLINK" in intent:
            return min(1.0, snap.eeg_blink / max(self.th_blink._max_seen, 1))
        if intent == "EEG_JAW_CLENCH":
            # Use the peak observed during the confirmed hold. Historical
            # max_seen can be dominated by an unrelated artifact and make a
            # perfectly strong clench appear artificially tiny.
            peak = self._cheek_jaw_resolver.last_jaw_peak
            if peak <= 0:
                peak = snap.eeg_jaw
            th = max(self.th_jaw.threshold, 1.0)
            # Gentle threshold-relative mapping: reaching the calibrated
            # threshold is already a meaningful gesture, while ~2× threshold
            # reaches full intensity. This avoids an old artifact max_seen
            # making ordinary clenches appear near zero.
            return min(1.0, max(0.0, (peak / th - 0.75) / 1.25))
        if intent == "EEG_CHEEK_TWITCH":
            # Prefer the threshold detector's tracked peak when it actually
            # fired. TFLite can also produce this intent independently, so in
            # that case use the current corrected signal as a meaningful
            # fallback instead of a stale zero-valued detector peak.
            peak = self._cheek_jaw_resolver.last_cheek_peak
            if peak > 0:
                return min(1.0, peak / max(self.th_cheek_twitch._max_seen, 1))

            # TFLite can generate the event without the threshold detector
            # firing. If the instantaneous signal has already decayed, use
            # the model confidence rather than reporting a misleading 0.00.
            if self.tflite_active and self._last_tflite_confidence > 0:
                return min(1.0, self._last_tflite_confidence)

            return min(1.0, snap.eeg_blink / max(
                self.th_cheek_twitch._max_seen, 1))
        if intent == "EEG_FOCUS_HIGH":
            return min(1.0, snap.eeg_beta / 100.0)
        return 0.7

    # ── Cooldown ──────────────────────────────────────────────────────

    def _check_cooldown(self, intent: str) -> bool:
        now  = time.time()
        # Use tighter cooldowns when TFLite is active — the model
        # already handles temporal smoothing so we don't need long
        # cooldowns to prevent rapid re-firing
        table = self.COOLDOWN_TFLITE if self.tflite_active else self.COOLDOWN
        cd   = table.get(intent, 0.4)
        last = self._last_fire.get(intent, 0)
        if now - last >= cd:
            self._last_fire[intent] = now
            return True
        return False

    # ── Calibration ───────────────────────────────────────────────────

    def _calibrate(self):
        self.th_ch2_strong.auto_calibrate(0.60)
        self.th_ch2_light.threshold  = self.th_ch2_strong.threshold * 0.50
        self.th_ch3_strong.auto_calibrate(0.60)
        self.th_ch3_light.threshold  = self.th_ch3_strong.threshold * 0.50
        self.th_blink.auto_calibrate(0.75)     # stricter for blink (lower bound)
        self.th_blink_upper.auto_calibrate(0.97)  # near-max legit signal —
                                                    # above this is presumed artifact
        self.th_jaw.auto_calibrate(0.60)
        self.th_jaw_upper.auto_calibrate(0.97)
        self.th_cheek_twitch.auto_calibrate(0.70)  # between blink and jaw
        self.th_eeg_focus.auto_calibrate(0.60)
        self._auto_calibrated = True
        print(f"[IntentEngine] Calibrated ({self._mode.upper()}):")
        print(f"  CH2  strong={self.th_ch2_strong.threshold:.0f}  "
              f"light={self.th_ch2_light.threshold:.0f}")
        print(f"  CH3  strong={self.th_ch3_strong.threshold:.0f}  "
              f"light={self.th_ch3_light.threshold:.0f}")
        if self._mode == "pfc":
            print(f"  Cheek={self.th_cheek_twitch.threshold:.0f}  "
                  f"Jaw={self.th_jaw.threshold:.0f}-{self.th_jaw_upper.threshold:.0f}")
        else:
            print(f"  Blink={self.th_blink.threshold:.0f}-{self.th_blink_upper.threshold:.0f}")
        print(f"  Focus={self.th_eeg_focus.threshold:.0f}")

    def force_recalibrate(self):
        self._auto_calibrated     = False
        self._samples_since_start = 0
        self._blink_counter       = BlinkCounter()
        self._cheek_jaw_resolver = CheekJawEventResolver()
        self._saturation_latched  = False
        self._lockout_until       = 0.0
        for g in (self._gate_ch2_strong, self._gate_ch2_light,
                  self._gate_ch3_strong, self._gate_ch3_light):
            g.reset()
        print(f"[IntentEngine] Recalibration started ({self._mode.upper()})...")

    def reset_floor_trackers(self):
        """Only call this on a genuinely new device connection — the
        passive floor is about electrode/skin contact, not detection
        mode, so mode switches and routine recalibration should NOT
        discard 30s of good passive learning."""
        for f in (self._floor_ch2, self._floor_ch3,
                  self._floor_blink, self._floor_jaw):
            f.reset()
        print("[IntentEngine] Floor trackers reset (new connection).")

    def set_hold_durations(self, strong: int, light: int):
        self.hold_strong_samples = strong
        self.hold_light_samples  = light
        for g in (self._gate_ch2_strong, self._gate_ch3_strong):
            g.min_samples = strong; g.reset()
        for g in (self._gate_ch2_light, self._gate_ch3_light):
            g.min_samples = light; g.reset()

    # ── Data capture ─────────────────────────────────────────────────

    def start_capture(self, label: str):
        self._capture_mode   = True
        self._capture_label  = label
        self._capture_buffer = []
        self._capture_rejected_count = 0

    def stop_capture(self) -> int:
        self._capture_mode = False
        count = len(self._capture_buffer)
        if count > 0:
            self._write_csv()
        if self._capture_rejected_count > 0:
            print(f"[IntentEngine] Rejected {self._capture_rejected_count} "
                  f"sample(s) during capture due to poor signal health "
                  f"(loose/noisy/saturated electrode) — kept {count} clean "
                  f"sample(s).")
        return count

    def _write_csv(self):
        # Use mode-specific CSV file, resolved against the app's
        # writable directory rather than a bare relative path (which
        # would depend on the process's current working directory —
        # unreliable when launched by double-clicking a frozen exe)
        path = os.path.join(
            _writable_data_dir(), f"volition_training_{self._mode}.csv")
        new  = not os.path.exists(path)
        with open(path, 'a', newline='') as f:
            w = csv.writer(f)
            if new:
                w.writerow(['timestamp','ch2_emg','ch3_emg',
                            'eeg_beta','eeg_blink','eeg_jaw','label'])
            for s in self._capture_buffer:
                w.writerow([s.timestamp, s.ch2_emg, s.ch3_emg,
                            s.eeg_beta, s.eeg_blink, s.eeg_jaw, s.intent])
        print(f"[IntentEngine] {len(self._capture_buffer)} samples → {path}")
