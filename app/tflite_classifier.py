"""
Volition - TFLite Classifier
=============================
Loads a trained .tflite model and classifies signal feature vectors.
Falls back to threshold-based classification if no model is present.

The model expects a feature vector of shape (1, NUM_FEATURES):
  [ch2_emg_norm, ch3_emg_norm, eeg_beta_norm,
   eeg_blink_norm, eeg_jaw_norm,
   ch2_mean, ch2_std, ch3_mean, ch3_std]   (9 features)

Output: probability per class in CLASS_NAMES order.
"""

import os
import sys
import json
import numpy as np
from collections import deque
from typing import Optional


def _bundled_data_dir() -> str:
    """
    Where to look for files that were BUNDLED INTO the exe at build time
    (e.g. a pre-trained model shipped alongside the app).

    Running from source: just the script's own folder.
    Running from a frozen PyInstaller onefile exe: PyInstaller unpacks
    bundled data into a temporary folder at sys._MEIPASS every time the
    exe runs — NOT the folder the exe file itself lives in. Bundled
    read-only assets live there while the app is running.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _writable_data_dir() -> str:
    """
    Where to READ/WRITE files that need to persist and be visible to the
    user after the app closes — most importantly, a model freshly
    trained via the TRAIN MODEL button.

    This must NOT be sys._MEIPASS: that folder is temporary, gets wiped
    when the exe exits, and is not writable in some PyInstaller
    configurations anyway. Instead this resolves to the folder the exe
    itself (or the script, when running from source) actually lives in
    — the same folder you'd double-click to launch the app, so a newly
    trained model shows up right next to it and survives a restart.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


MODEL_PATH  = "volition_model.tflite"
NUM_FEATURES = 9

# Fallback only — real class order is loaded per-model from the
# matching *_stats.json file that train_classifier.py writes, since
# PFC and VC models have different (and different-length) class lists.
# This hardcoded list is only used if no stats file is found.
CLASS_NAMES_FALLBACK = [
    "CH2_STRONG",
    "CH2_LIGHT",
    "CH3_STRONG",
    "CH3_LIGHT",
    "BOTH_STRONG",
    "BOTH_LIGHT",
    "EEG_BLINK",
    "EEG_DOUBLE_BLINK",
    "EEG_TRIPLE_BLINK",
    "EEG_JAW_CLENCH",
    "EEG_CHEEK_TWITCH",
    "EEG_FOCUS_HIGH",
    "EEG_ERROR",
    "REST",
]


class TFLiteClassifier:
    """
    Wraps a TFLite model for real-time gesture classification.
    If no model file exists, is_loaded returns False and the intent
    engine falls back to adaptive threshold detection automatically.
    """

    WINDOW = 8   # rolling window — 8 samples ≈ 267ms at 30Hz
                 # was 30 (1 second), which caused the 1-2s response delay

    def __init__(self, model_path: str = MODEL_PATH):
        self._interpreter = None
        self._input_idx   = None
        self._output_idx  = None
        self.is_loaded    = False
        self.model_path   = model_path
        self.class_names  = CLASS_NAMES_FALLBACK   # overwritten if stats found
        # Latest inference diagnostics exposed to IntentEngine.
        self.last_class = None
        self.last_probability = 0.0

        # Rolling windows for feature extraction
        self._ch2_window  = deque(maxlen=self.WINDOW)
        self._ch3_window  = deque(maxlen=self.WINDOW)

        # Scale factors (set after first calibration or from saved stats)
        self.ch2_max  = 1000.0
        self.ch3_max  = 1000.0
        self.blink_max = 300.0
        self.jaw_max   = 500.0

        self._try_load(model_path)

    def _resolve_path(self, path: str) -> str:
        """
        Turn a bare relative filename like 'volition_model_pfc.tflite'
        into an absolute path that actually exists, checking the
        writable app folder first (so a freshly retrained model always
        wins over an older bundled one), then falling back to the
        bundled read-only copy shipped inside the exe.

        If path is already absolute, or doesn't exist in either
        location, it's returned unchanged (existing os.path.exists
        checks downstream handle the "not found" case as before).
        """
        if os.path.isabs(path):
            return path

        writable_candidate = os.path.join(_writable_data_dir(), path)
        if os.path.exists(writable_candidate):
            return writable_candidate

        bundled_candidate = os.path.join(_bundled_data_dir(), path)
        if os.path.exists(bundled_candidate):
            return bundled_candidate

        # Neither location has it — return the writable-dir path so the
        # "not found" message shown to the user points somewhere
        # sensible (where they'd expect to look/place a model)
        return writable_candidate

    def _stats_path_for(self, model_path: str) -> str:
        """volition_model_pfc.tflite → volition_model_pfc_stats.json"""
        base, _ = os.path.splitext(model_path)
        return f"{base}_stats.json"

    def _try_load(self, path: str):
        path = self._resolve_path(path)

        if not os.path.exists(path):
            print(f"[TFLite] No model found at '{path}'. "
                  f"Running in threshold mode.")
            return

        # Load the class order this specific model was trained with —
        # critical, since PFC and VC models have different class lists
        # and a mismatched order silently scrambles every prediction.
        stats_path = self._stats_path_for(path)
        if os.path.exists(stats_path):
            try:
                with open(stats_path) as f:
                    stats = json.load(f)
                if "classes" in stats and stats["classes"]:
                    self.class_names = stats["classes"]
                    print(f"[TFLite] Loaded {len(self.class_names)} "
                          f"class labels from '{stats_path}'")
                for k in ("ch2_max", "ch3_max", "blink_max", "jaw_max"):
                    if k in stats and stats[k]:
                        setattr(self, k, float(stats[k]))
            except Exception as e:
                print(f"[TFLite] Could not read '{stats_path}': {e}. "
                      f"Falling back to default class order — "
                      f"predictions may be mislabeled.")
        else:
            print(f"[TFLite] No stats file found at '{stats_path}'. "
                  f"Using fallback class order — retrain with "
                  f"train_classifier.py to generate a matching stats file.")

        try:
            # Try tflite_runtime first (lighter), fall back to full TF
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                from tensorflow.lite.python.interpreter import Interpreter

            self._interpreter = Interpreter(model_path=path)
            self._interpreter.allocate_tensors()
            details = self._interpreter.get_input_details()
            self._input_idx  = details[0]["index"]
            self._output_idx = self._interpreter.get_output_details()[0]["index"]
            self.is_loaded   = True
            print(f"[TFLite] Model loaded from '{path}'")

        except Exception as e:
            print(f"[TFLite] Failed to load model: {e}")
            self.is_loaded = False

    def reload(self, path: str = None):
        """Reload model from disk — call after training a new model."""
        self.is_loaded = False
        self._try_load(path or self.model_path)

    def extract_features(
        self,
        ch2_emg:   float,
        ch3_emg:   float,
        eeg_beta:  float,
        eeg_blink: float,
        eeg_jaw:   float,
    ) -> np.ndarray:
        """
        Build a (1, NUM_FEATURES) feature vector from current signals
        plus rolling statistics.
        """
        self._ch2_window.append(ch2_emg)
        self._ch3_window.append(ch3_emg)

        ch2_arr = np.array(self._ch2_window, dtype=np.float32)
        ch3_arr = np.array(self._ch3_window, dtype=np.float32)

        feats = np.array([[
            ch2_emg   / self.ch2_max,
            ch3_emg   / self.ch3_max,
            eeg_beta  / 100.0,
            eeg_blink / self.blink_max,
            eeg_jaw   / self.jaw_max,
            float(ch2_arr.mean()) / self.ch2_max,
            float(ch2_arr.std())  / self.ch2_max,
            float(ch3_arr.mean()) / self.ch3_max,
            float(ch3_arr.std())  / self.ch3_max,
        ]], dtype=np.float32)

        return feats

    def predict(
        self,
        ch2_emg:   float,
        ch3_emg:   float,
        eeg_beta:  float,
        eeg_blink: float,
        eeg_jaw:   float,
        threshold: float = 0.65,
    ) -> Optional[str]:
        """
        Run inference. Returns the top class name if its probability
        exceeds the threshold, otherwise None (fall through to adaptive
        threshold detection).

        Returns None if model is not loaded.
        """
        if not self.is_loaded or self._interpreter is None:
            return None

        feats = self.extract_features(
            ch2_emg, ch3_emg, eeg_beta, eeg_blink, eeg_jaw)

        try:
            self._interpreter.set_tensor(self._input_idx, feats)
            self._interpreter.invoke()
            probs = self._interpreter.get_tensor(self._output_idx)[0]

            top_idx  = int(np.argmax(probs))
            top_prob = float(probs[top_idx])
            top_cls  = self.class_names[top_idx] if top_idx < len(self.class_names) \
                       else "REST"

            self.last_class = top_cls
            self.last_probability = top_prob

            if top_cls == "REST" or top_prob < threshold:
                return None

            return top_cls

        except Exception as e:
            print(f"[TFLite] Inference error: {e}")
            return None

    def update_scale(self, ch2_max: float, ch3_max: float,
                     blink_max: float, jaw_max: float):
        """Sync scale factors with the intent engine's observed maximums."""
        if ch2_max   > 0: self.ch2_max   = ch2_max
        if ch3_max   > 0: self.ch3_max   = ch3_max
        if blink_max > 0: self.blink_max = blink_max
        if jaw_max   > 0: self.jaw_max   = jaw_max
