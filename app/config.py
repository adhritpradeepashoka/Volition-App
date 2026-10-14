# Constants and helpers used across the app

MAX_CHANNELS = 6
FILTER_MAP = {0: 'emg', 1: 'eeg', 2: 'eog', 3: 'ecg'}

# Progress bar scaling (raw value to 0-100 range)
EMG_SCALE = 1000.0
BLINK_SCALE = 300.0
EYE_SCALE = 300.0
JAW_SCALE = 500.0
ECG_SCALE = 500.0


def clamp100(val, scale):
    return max(0, min(100, int(val / scale * 100)))

# Default UI Thresholds
DEFAULT_THRESHOLDS = {
    'pbFocus':    50,
    'pbBlink':    17,
    'pbLeftEye':  50,
    'pbRightEye': 50,
    'pbJaw':      32,
    'pbECG':      50,
    'pbEMG1':     40,
    'pbEMG2':     40,
    'pbEMG3':     40,
    'pbEMG4':     40,
    'pbEMG5':     40,
    'pbEMG6':     40,
}
