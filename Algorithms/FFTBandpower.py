# FFT Band Power Calculator for EEG Focus Detection
# Computes power spectral density via FFT, splits into standard EEG bands,
# and applies exponential smoothing. Focus is detected when beta% is elevated.
# Reference: Extracted from NPG Lite EEG Focus firmware (ESP-DSP FFT routines)
#
# Requires: numpy (for FFT)

import numpy as np

# Standard EEG frequency bands (Hz)
DELTA_LOW  = 0.5;  DELTA_HIGH = 4.0
THETA_LOW  = 4.0;  THETA_HIGH = 8.0
ALPHA_LOW  = 8.0;  ALPHA_HIGH = 13.0
BETA_LOW   = 13.0; BETA_HIGH  = 30.0
GAMMA_LOW  = 30.0; GAMMA_HIGH = 45.0

SMOOTHING_FACTOR = 0.63
EPS = 1e-7


class FFTBandpower:
    def __init__(self, fft_size=512, sample_rate=500, smoothing=SMOOTHING_FACTOR):
        self.fft_size = fft_size
        self.sample_rate = sample_rate
        self.smoothing = smoothing
        self.bin_resolution = sample_rate / fft_size

        # Input buffer (circular, fills up to fft_size then triggers FFT)
        self.buffer = np.zeros(fft_size, dtype=np.float64)
        self.write_idx = 0

        # Smoothed band powers
        self.smoothed = {
            'delta': 0.0,
            'theta': 0.0,
            'alpha': 0.0,
            'beta':  0.0,
            'gamma': 0.0,
            'total': 0.0,
        }

        # Latest results (updated after each FFT)
        self.band_percentages = {
            'delta': 0.0,
            'theta': 0.0,
            'alpha': 0.0,
            'beta':  0.0,
            'gamma': 0.0,
        }
        self.peak_frequency = 0.0

    def add_sample(self, sample):
        """
        Add a filtered EEG sample to the buffer.
        Returns True if a new FFT was computed (buffer was full), False otherwise.
        """
        self.buffer[self.write_idx] = sample
        self.write_idx += 1

        if self.write_idx >= self.fft_size:
            self.write_idx = 0
            self._compute()
            return True

        return False

    def _compute(self):
        """Run FFT, compute band powers, smooth, and calculate percentages."""
        # FFT → magnitude² (power spectrum)
        spectrum = np.fft.rfft(self.buffer)
        power = np.real(spectrum * np.conj(spectrum))
        half = len(power)

        # Band power accumulation
        raw = {'delta': 0.0, 'theta': 0.0, 'alpha': 0.0, 'beta': 0.0, 'gamma': 0.0, 'total': 0.0}

        for i in range(1, half):
            freq = i * self.bin_resolution
            p = power[i]
            raw['total'] += p

            if   DELTA_LOW <= freq < DELTA_HIGH: raw['delta'] += p
            elif THETA_LOW <= freq < THETA_HIGH: raw['theta'] += p
            elif ALPHA_LOW <= freq < ALPHA_HIGH: raw['alpha'] += p
            elif BETA_LOW  <= freq < BETA_HIGH:  raw['beta']  += p
            elif GAMMA_LOW <= freq < GAMMA_HIGH: raw['gamma'] += p

        # Exponential smoothing
        a = self.smoothing
        for band in self.smoothed:
            self.smoothed[band] = a * raw[band] + (1 - a) * self.smoothed[band]

        # Percentages of total
        total = self.smoothed['total'] + EPS
        for band in self.band_percentages:
            self.band_percentages[band] = (self.smoothed[band] / total) * 100.0

        # Peak frequency (skip DC bin)
        peak_idx = np.argmax(power[1:]) + 1
        self.peak_frequency = peak_idx * self.bin_resolution

    def get_band_percentages(self):
        """Return dict of band power percentages: delta, theta, alpha, beta, gamma."""
        return self.band_percentages.copy()

    def get_peak_frequency(self):
        """Return the dominant frequency in Hz."""
        return self.peak_frequency

    def is_focused(self, beta_threshold=20.0):
        """Returns True if beta% exceeds threshold (focus detected)."""
        return self.band_percentages['beta'] > beta_threshold

    def reset(self):
        """Reset all state."""
        self.buffer = np.zeros(self.fft_size, dtype=np.float64)
        self.write_idx = 0
        self.smoothed = {k: 0.0 for k in self.smoothed}
        self.band_percentages = {k: 0.0 for k in self.band_percentages}
        self.peak_frequency = 0.0

