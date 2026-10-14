# ECG R-Peak Detector with BPM Calculation
# Pan-Tompkins inspired algorithm: derivative → squaring → MWI → adaptive thresholds
# Detects heartbeats (R-peaks) and computes rolling BPM.
# Reference: Extracted from NPG Lite ECG firmware (EcgDetector class)

class ECGDetector:
    def __init__(self, sample_rate=500):
        self.fs = sample_rate

        # Scale sample counts from the original 125 Hz base
        self._ecg_hist_len   = self._scale(240)
        self._mwi_win        = self._scale(20)
        self._refract        = self._scale(25)
        self._learn_samples  = sample_rate * 5
        self._r_search_back  = self._scale(22)
        self._r_search_fwd   = self._scale(3)
        self._tw_min         = self._scale(25)
        self._tw_max         = self._scale(45)
        self._recover_gap    = sample_rate // 2
        self._no_qrs_abs     = sample_rate
        self._tw_slope_ratio = 0.5

        # History ring buffers
        self.ecg_hist   = [0.0] * self._ecg_hist_len
        self.slope_hist = [0.0] * self._ecg_hist_len
        self.ecg_time   = [0]   * self._ecg_hist_len
        self.ecg_w = 0

        # 5-point derivative buffer
        self.d_buf = [0.0] * 5
        self.d_w = 0

        # Moving window integrator
        self.mwi_buf = [0.0] * self._mwi_win
        self.mwi_w = 0
        self.mwi_sum = 0.0

        # MWI peak tracking (3-sample window for peak detection)
        self.m0 = 0.0; self.m1 = 0.0; self.m2 = 0.0
        self.t0 = 0;   self.t1 = 0;   self.t2 = 0

        # Adaptive thresholds (Pan-Tompkins)
        self.SPKI = 0.0
        self.NPKI = 0.0
        self.TH1 = 0.0
        self.TH2 = 0.0

        # QRS tracking
        self.last_qrs = 0
        self.last_qrs_slope = 0.0

        # RR interval averaging (8-sample ring)
        self.rr_buf = [0] * 8
        self.rr_w = 0
        self.rr_n = 0
        self.rr_avg = float(sample_rate)

        # Searchback peak
        self.sb_peak_val = 0.0
        self.sb_peak_time = 0

        # Learning phase
        self.learn_count = 0
        self.learn_max = 0.0
        self.learn_sum = 0.0

        # MWI baseline (noise floor tracking)
        self.mw_base_init = False
        self.mw_base = 0.0
        self.last_recover = 0

        # BPM calculation (8-sample RR history)
        self.last_r_time = 0
        self.rr_hist = [0] * 8
        self.rr_hw = 0
        self.rr_hn = 0
        self.bpm = 0.0

        # Beat event flag
        self.beat_event = False
        self.last_beat_n = 0

        # Sample counter
        self.n_now = 0

    def _scale(self, original):
        """Scale a sample count from base 125Hz to current sample rate."""
        return ((original * self.fs) + 62) // 125

    # Public API 

    def process(self, adc_value):
        """
        Process a single raw ADC sample (12-bit, 0–4095).
        Call this at the configured sample rate.
        Returns True if a heartbeat (R-peak) was detected on this sample.
        """
        self.n_now += 1
        n = self.n_now

        # Center around zero (12-bit ADC midpoint = 2048)
        x = float(adc_value) - 2048.0

        # 5-point derivative
        d = self._derivative5(x)
        slope = abs(d)

        # Squaring + MWI
        s2 = d * d
        mw = self._mwi(s2)

        # Store in history
        self.ecg_hist[self.ecg_w] = x
        self.slope_hist[self.ecg_w] = slope
        self.ecg_time[self.ecg_w] = n
        self.ecg_w = (self.ecg_w + 1) % self._ecg_hist_len

        # Shift 3-sample peak window
        self.m0, self.t0 = self.m1, self.t1
        self.m1, self.t1 = self.m2, self.t2
        self.m2, self.t2 = mw, n

        # MWI baseline tracking (after learning phase)
        if n >= self._learn_samples:
            if not self.mw_base_init:
                self.mw_base = mw
                self.mw_base_init = True
            if mw < self.TH1:
                self.mw_base = 0.99 * self.mw_base + 0.01 * mw
            self._watchdog_recover(n)

        # Detect MWI peak (m1 is a local maximum)
        self.beat_event = False
        if n >= 2 and self.m1 > self.m0 and self.m1 >= self.m2:
            self._handle_mwi_peak(n, self.m1, self.t1)

        # Searchback
        self._searchback(n)

        return self.beat_event

    def pop_beat_event(self):
        """Check and clear the beat event flag."""
        if not self.beat_event:
            return False
        self.beat_event = False
        return True

    def get_bpm(self):
        """Return the current estimated BPM (0 if not enough data)."""
        return self.bpm

    def reset(self):
        """Reset all state to initial values."""
        self.__init__(self.fs)

    # Internals 

    def _derivative5(self, x):
        """5-point derivative (Pan-Tompkins)."""
        self.d_buf[self.d_w] = x
        self.d_w = (self.d_w + 1) % 5
        i = self.d_w
        xn2 = self.d_buf[(i + 3) % 5]
        xn1 = self.d_buf[(i + 4) % 5]
        xp1 = self.d_buf[(i + 1) % 5]
        xp2 = self.d_buf[(i + 2) % 5]
        return (-xn2 - 2.0 * xn1 + 2.0 * xp1 + xp2) / 8.0

    def _mwi(self, x):
        """Moving window integrator."""
        self.mwi_sum -= self.mwi_buf[self.mwi_w]
        self.mwi_buf[self.mwi_w] = x
        self.mwi_sum += x
        self.mwi_w = (self.mwi_w + 1) % self._mwi_win
        return self.mwi_sum / self._mwi_win

    def _update_thresholds(self):
        self.TH1 = self.NPKI + 0.25 * (self.SPKI - self.NPKI)
        self.TH2 = 0.40 * self.TH1

    def _rr_update(self, rr):
        self.rr_buf[self.rr_w] = rr
        self.rr_w = (self.rr_w + 1) & 7
        if self.rr_n < 8:
            self.rr_n += 1
        s = sum(self.rr_buf[:self.rr_n])
        self.rr_avg = s / self.rr_n if self.rr_n > 0 else float(self.fs)

    def _bpm_update(self, r_time):
        if self.last_r_time == 0:
            self.last_r_time = r_time
            return
        rr_samp = r_time - self.last_r_time
        self.last_r_time = r_time

        if rr_samp < 10 or rr_samp > self.fs * 3:
            return

        self.rr_hist[self.rr_hw] = rr_samp
        self.rr_hw = (self.rr_hw + 1) & 7
        if self.rr_hn < 8:
            self.rr_hn += 1

        rr_mean = sum(self.rr_hist[:self.rr_hn]) / self.rr_hn
        self.bpm = (60.0 * self.fs) / rr_mean

    def _slope_around(self, time_center, half_win):
        best = 0.0
        for k in range(self._ecg_hist_len):
            idx = (self.ecg_w + self._ecg_hist_len - 1 - k) % self._ecg_hist_len
            dt = self.ecg_time[idx] - time_center
            if dt > half_win:
                continue
            if dt < -half_win:
                break
            v = self.slope_hist[idx]
            if v > best:
                best = v
        return best

    def _accept_qrs(self, peak_time):
        if self.last_qrs != 0:
            dt = peak_time - self.last_qrs
            if dt < self._refract:
                return False
            # T-wave rejection
            if self._tw_min <= dt <= self._tw_max:
                slope_now = self._slope_around(peak_time, 2)
                if self.last_qrs_slope > 0.0 and slope_now < self._tw_slope_ratio * self.last_qrs_slope:
                    return False
            # Too early relative to RR average
            if self.rr_n >= 2:
                if float(dt) < 0.30 * self.rr_avg:
                    return False
        return True

    def _find_r_peak(self, qrs_time):
        best_abs = -1.0
        best_slope = -1.0
        best_time = 0

        for k in range(self._ecg_hist_len):
            idx = (self.ecg_w + self._ecg_hist_len - 1 - k) % self._ecg_hist_len
            dt = self.ecg_time[idx] - qrs_time
            if dt > self._r_search_fwd:
                continue
            if dt < -self._r_search_back:
                break

            v = self.ecg_hist[idx]
            av = abs(v)
            s = self.slope_hist[idx]

            if av > best_abs or (av == best_abs and s > best_slope):
                best_abs = av
                best_slope = s
                best_time = self.ecg_time[idx]

        return best_time if best_time != 0 else None

    def _handle_mwi_peak(self, n_now, peak_val, peak_time):
        # Learning phase
        if n_now < self._learn_samples:
            self.learn_count += 1
            self.learn_sum += peak_val
            if peak_val > self.learn_max:
                self.learn_max = peak_val
            if n_now == self._learn_samples - 1:
                self.SPKI = self.learn_max
                self.NPKI = (self.learn_sum / self.learn_count) if self.learn_count > 0 else 0.1 * self.learn_max
                self._update_thresholds()
            return

        is_qrs = peak_val >= self.TH1 and self._accept_qrs(peak_time)

        if not is_qrs:
            self.NPKI = 0.125 * peak_val + 0.875 * self.NPKI
            self._update_thresholds()
            if peak_val > self.TH2 and peak_val > self.sb_peak_val:
                self.sb_peak_val = peak_val
                self.sb_peak_time = peak_time
            return

        # QRS confirmed
        rr = self.rr_avg if self.last_qrs == 0 else (peak_time - self.last_qrs)
        self.last_qrs = peak_time
        self._rr_update(int(rr))

        self.last_qrs_slope = self._slope_around(peak_time, 2)

        self.SPKI = 0.125 * peak_val + 0.875 * self.SPKI
        self._update_thresholds()

        self.sb_peak_val = 0.0
        self.sb_peak_time = 0

        r_time = self._find_r_peak(peak_time)
        if r_time is None:
            r_time = peak_time

        self.beat_event = True
        self.last_beat_n = r_time
        self._bpm_update(r_time)

    def _searchback(self, n_now):
        if n_now < self._learn_samples:
            return
        if self.last_qrs == 0:
            return

        since = float(n_now - self.last_qrs)
        if since <= 1.66 * self.rr_avg:
            return

        if self.sb_peak_time != 0 and self.sb_peak_val >= self.TH2 and self._accept_qrs(self.sb_peak_time):
            rr = self.sb_peak_time - self.last_qrs
            self.last_qrs = self.sb_peak_time
            self._rr_update(rr)

            self.last_qrs_slope = self._slope_around(self.sb_peak_time, 2)
            self.SPKI = 0.125 * self.sb_peak_val + 0.875 * self.SPKI
            self._update_thresholds()

            r_time = self._find_r_peak(self.sb_peak_time)
            if r_time is None:
                r_time = self.sb_peak_time

            self.beat_event = True
            self.last_beat_n = r_time
            self._bpm_update(r_time)

            self.sb_peak_val = 0.0
            self.sb_peak_time = 0
        else:
            self.sb_peak_val = 0.0
            self.sb_peak_time = 0
            self.NPKI *= 0.95
            self._update_thresholds()

    def _watchdog_recover(self, n_now):
        if n_now < self._learn_samples:
            return
        if self.last_qrs == 0:
            return

        blind_limit = int(1.5 * self.rr_avg)
        if blind_limit < self._no_qrs_abs:
            blind_limit = self._no_qrs_abs

        since = n_now - self.last_qrs
        if since <= blind_limit:
            return
        if (n_now - self.last_recover) < self._recover_gap:
            return

        self.last_recover = n_now
        self.SPKI *= 0.50
        self.NPKI = 0.90 * self.NPKI + 0.10 * self.mw_base

        if self.NPKI < 1e-6:
            self.NPKI = 1e-6
        if self.SPKI < self.NPKI:
            self.SPKI = self.NPKI

        self._update_thresholds()
        self.sb_peak_val = 0.0
        self.sb_peak_time = 0

