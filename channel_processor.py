# Per-channel signal processing pipeline.
# Each channel gets a notch filter + one of: EMG, EEG, EOG, or ECG filter chain.

from filters.BS50 import BS50
from filters.BS60 import BS60
from filters.HP70 import HP70
from filters.HP5 import HP5
from filters.LP45 import LP45
from filters.BPECG import BPECG
from filters.BP1To10 import BP1To10
from Algorithms.EnvelopeDetector import EnvelopeDetector
from Algorithms.BaselineTracker import BaselineTracker
from Algorithms.FFTBandpower import FFTBandpower


class ChannelProcessor:
    def __init__(self):
        self.notch = None
        self.filter_type = 'emg'
        self._init_emg()

    # Pipeline initialisers

    def _init_emg(self):
        self.hp70 = HP70()
        self.emg_env = EnvelopeDetector(64)
        self.val_emg_envelope = 0.0

    def _init_eeg(self):
        self.lp45 = LP45()
        self.hp5 = HP5()
        self.fft = FFTBandpower(fft_size=512, sample_rate=500)
        self.blink_env = EnvelopeDetector(50)
        self.jaw_hp70 = HP70()
        self.jaw_env = EnvelopeDetector(50)
        self.val_beta_pct = 0.0
        self.val_blink_envelope = 0.0
        self.val_jaw_envelope = 0.0

    def _init_eog(self):
        self.bp1to10 = BP1To10()
        self.baseline = BaselineTracker(256)
        self.jaw_hp70 = HP70()
        self.jaw_env = EnvelopeDetector(50)
        self.val_eye_deviation = 0.0
        self.val_jaw_envelope = 0.0

    def _init_ecg(self):
        self.ecg_filter = BPECG()
        self.val_ecg = 0.0

    # Configuration

    def set_notch(self, setting):
        if setting == '50':   
            self.notch = BS50()
        elif setting == '60': 
            self.notch = BS60()
        else:                 
            self.notch = None

    def set_filter(self, ftype):
        self.filter_type = ftype
        if ftype == 'emg':   
            self._init_emg()
        elif ftype == 'eeg': 
            self._init_eeg()
        elif ftype == 'eog': 
            self._init_eog()
        elif ftype == 'ecg': 
            self._init_ecg()

    # Per-sample processing

    def process(self, raw):
        v = float(raw)
        if self.notch:
            v = self.notch.process(v)

        if self.filter_type == 'emg':
            f = self.hp70.process(v)
            self.val_emg_envelope = self.emg_env.get_envelope(abs(f))

        elif self.filter_type == 'eeg':
            lp = self.lp45.process(v)
            if self.fft.add_sample(lp):
                self.val_beta_pct = self.fft.get_band_percentages()['beta']
            hp = self.hp5.process(lp)
            self.val_blink_envelope = self.blink_env.get_envelope(abs(hp))
            j = self.jaw_hp70.process(v)
            self.val_jaw_envelope = self.jaw_env.get_envelope(abs(j))

        elif self.filter_type == 'eog':
            bp = self.bp1to10.process(v)
            self.baseline.update(bp)
            self.val_eye_deviation = bp - self.baseline.get_baseline()
            j = self.jaw_hp70.process(v)
            self.val_jaw_envelope = self.jaw_env.get_envelope(abs(j))

        elif self.filter_type == 'ecg':
            f = self.ecg_filter.process(v)
            self.val_ecg = abs(f)
