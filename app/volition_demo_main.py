"""
Volition DEMO — Simplified Biosignal Monitor
==============================================
Stripped-down build for presentation/demo video use. Shows only the
essentials a general audience needs to understand the core idea:

  - Live signal bars with floor + threshold overlay (the "adaptive"
    story — this is the most visually compelling part of the pitch)
  - EEG headband mode switch (Prefrontal / Visual Cortex)
  - Data capture + TFLite train/load, so training can be demoed live
  - Signal quality / electrode health at a glance
  - A simple activity log showing intents firing in real time
  - Optional spatial IMU targeting and local Kasa smart-device control

Deliberately removed vs. the full engineering build:
  - 3-axis robotic arm panel and all arm connection/control UI
  - Standard HID keyboard/mouse mapping + ergonomic gyro-controlled keyboard
  - Manual threshold/baseline override sliders (auto-calibration only)

Built on top of NPG-Lite-SNES by Upside Down Labs (GPL-3.0)
Original: https://github.com/upsidedownlabs/NPG-Lite-SNES
"""

import sys
import os
import asyncio
import math
import queue
import threading

# ── Redirect stdout/stderr BEFORE any other import ───────────────────────────
# Prevents a console window from being silently allocated when launched
# via pythonw.exe — see volition_main.py for the full explanation.
if sys.stdout is None or sys.stderr is None:
    _log_dir = os.path.dirname(os.path.abspath(__file__))
    _log_path = os.path.join(_log_dir, "volition_demo_log.txt")
    _log_file = open(_log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = _log_file
    sys.stderr = _log_file
    import datetime
    print(f"\n{'='*60}")
    print(f"Volition (demo build) started — {datetime.datetime.now().isoformat()}")
    print(f"{'='*60}")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QGroupBox, QProgressBar,
    QTextEdit, QInputDialog, QCheckBox, QScrollArea, QButtonGroup,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QGridLayout, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QDateTime
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath

# --- Volition modules ---
from intent_engine import IntentEngine, ALL_POSSIBLE_INTENTS
from hid_controller import HIDController, HID_ACTIONS

# Smart-device support.  Keep the import optional at runtime, but import it
# at module scope so PyInstaller sees it when python-kasa is installed.
try:
    import kasa as _kasa
except ImportError:
    _kasa = None

# --- NPG-Lite-SNES modules (unchanged from original) ---
sys.path.insert(0, os.path.dirname(__file__))
from channel_processor import ChannelProcessor
from ble_manager import BLEManager
from config import MAX_CHANNELS, FILTER_MAP

# ── Colours (identical palette to the full build) ────────────────────────────
C_BG       = "#0a0a0a"
C_PANEL    = "#111111"
C_BORDER   = "#2a2a2a"
C_ACCENT   = "#f5a623"
C_GREEN    = "#00ff66"
C_TEXT     = "#ffffff"
C_MUTED    = "#9a9a9a"
C_DANGER   = "#ff4444"

STYLE = f"""
QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_TEXT}; font-family: 'Consolas', monospace; }}
QGroupBox {{
    border: 1px solid {C_BORDER}; border-radius: 6px;
    margin-top: 12px; padding-top: 8px; font-size: 10px; color: {C_MUTED};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QPushButton {{
    background: {C_PANEL}; border: 1px solid {C_BORDER};
    border-radius: 4px; color: {C_TEXT}; padding: 8px 16px;
    font-size: 12px; font-weight: bold; letter-spacing: 1px;
}}
QPushButton:hover {{ border-color: {C_ACCENT}; color: {C_ACCENT}; }}
QPushButton:checked, QPushButton:pressed {{ background: {C_ACCENT}; color: {C_BG}; border-color: {C_ACCENT}; }}
QPushButton:disabled {{ color: {C_MUTED}; border-color: #1a1a1a; }}
QProgressBar {{
    background: #1a1a1a; border: 1px solid {C_BORDER};
    border-radius: 3px; height: 14px;
}}
QProgressBar::chunk {{ background: {C_ACCENT}; border-radius: 2px; }}
QComboBox {{
    background: {C_PANEL}; border: 1px solid {C_BORDER};
    border-radius: 4px; color: {C_TEXT}; padding: 6px;
    font-size: 11px;
}}
QComboBox QAbstractItemView {{
    background: {C_PANEL}; color: {C_TEXT}; selection-background-color: {C_ACCENT};
}}
QTextEdit {{
    background: #0d0d0d; border: 1px solid {C_BORDER}; border-radius: 4px;
    font-size: 10px; color: {C_TEXT};
}}
QCheckBox {{ font-size: 10px; }}
QScrollBar:vertical {{ background: #111; width: 10px; }}
QScrollBar::handle:vertical {{ background: {C_BORDER}; border-radius: 4px; }}
"""


# ── Signal Bar (identical to full build — this is the visual centrepiece) ────

class SignalBar(QWidget):
    """
    A signal strength bar that shows the RAW value, with floor and
    threshold markers overlaid — the live signal, the learned resting
    floor, and the firing threshold, all on one scale. This is the
    single most demo-worthy element in the whole app: it visually shows
    the adaptive calibration story in real time.
    """

    def __init__(self, colour: str, max_scale: float = 1000.0):
        super().__init__()
        self._value      = 0.0
        self._floor      = None
        self._thresholds = []
        self._max_scale  = max(max_scale, 1.0)
        self._colour     = colour
        self.setFixedHeight(22)
        self.setMinimumWidth(40)

    def set_scale(self, max_scale: float):
        self._max_scale = max(max_scale, 1.0)
        self.update()

    def set_value(self, v: float):
        self._value = max(0.0, v)
        self.update()

    def set_floor(self, floor):
        self._floor = floor
        self.update()

    def set_thresholds(self, thresholds: list):
        self._thresholds = thresholds
        self.update()

    def _x_for(self, raw_value: float) -> int:
        frac = min(1.0, max(0.0, raw_value / self._max_scale))
        return int(self.width() * frac)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        radius = h / 2.0

        track_path = QPainterPath()
        track_path.addRoundedRect(0.5, 0.5, w - 1, h - 1, radius, radius)
        painter.setClipPath(track_path)
        painter.fillRect(0, 0, w, h, QColor("#1a1a1a"))

        fill_w = self._x_for(self._value)
        if fill_w > 0:
            painter.fillRect(0, 0, fill_w, h, QColor(self._colour))

        painter.setClipping(False)

        pen = QPen(QColor(C_BORDER))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRoundedRect(0.5, 0.5, w - 1, h - 1, radius, radius)

        if self._floor is not None:
            fx = self._x_for(self._floor)
            pen = QPen(QColor(255, 255, 255, 110))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(fx, 3, fx, h - 3)

        for th_value, th_colour in self._thresholds:
            tx = self._x_for(th_value)
            pen = QPen(QColor(th_colour))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawLine(tx, 1, tx, h - 1)

        painter.end()


class SignalPanel(QGroupBox):
    """Live signal strength bars — the centrepiece of the demo view."""

    def __init__(self):
        super().__init__("BIOSIGNAL MONITOR")
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 20, 16, 16)

        self._bars = {}
        self._bar_labels = {}
        self._bar_rows   = {}
        signals = [
            ("ch2_emg",  "RIGHT ARM",  C_ACCENT,   1000.0),
            ("ch3_emg",  "LEFT ARM",   "#ff9944",  1000.0),
            ("blink",    "BLINK",      "#4fc3f7",  300.0),
            ("jaw",      "JAW CLENCH", "#ce93d8",  500.0),
            ("focus",    "FOCUS",      "#a5d6a7",  100.0),
        ]
        for key, label, colour, scale in signals:
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel(label)
            lbl.setFixedWidth(110)
            lbl.setStyleSheet(f"color: {C_TEXT}; font-size: 13px; font-weight: bold;")
            bar = SignalBar(colour, max_scale=scale)
            row.addWidget(lbl)
            row.addWidget(bar)
            layout.addLayout(row)
            self._bars[key] = bar
            self._bar_labels[key] = lbl
            self._bar_rows[key] = row

        legend = QLabel("│ white = resting floor    │ bright = fire threshold")
        legend.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        layout.addSpacing(6)
        layout.addWidget(legend)

    def set_jaw_row_mode(self, pfc: bool):
        blink_lbl = self._bar_labels.get("blink")
        jaw_lbl   = self._bar_labels.get("jaw")
        if blink_lbl:
            blink_lbl.setText("CHEEK TWITCH" if pfc else "BLINK")
        if jaw_lbl:
            jaw_lbl.setText("JAW CLENCH")

    def update_signals(self, **kwargs):
        for key, val in kwargs.items():
            if key in self._bars:
                self._bars[key].set_value(max(0.0, val))

    def update_markers(self, key: str, floor=None, thresholds=None):
        if key in self._bars:
            if floor is not None:
                self._bars[key].set_floor(floor)
            if thresholds is not None:
                self._bars[key].set_thresholds(thresholds)


# ── Log Panel ─────────────────────────────────────────────────────────────────

class LogPanel(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumHeight(140)

    def log(self, msg: str, colour: str = C_GREEN):
        import time
        ts = time.strftime("%H:%M:%S")
        self.append(f'<span style="color:{C_MUTED}">[{ts}]</span> <span style="color:{colour}">{msg}</span>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())



# ── Spatial IMU + smart-device integration ────────────────────────────────────
#
# BLE transport is handled by ble_connection.py / ble_manager.py. The GUI
# receives decoded IMU packets through BLEManager. This keeps all BLE details
# out of the application layer and leaves the existing EEG/EMG path untouched.
#
# SpatialResolver has two modes:
#   1) Relative targeting (legacy/demo-safe): current head yaw vs. a stored
#      calibration angle.
#   2) Single-target movement-aware targeting: SET INITIAL DIRECTION stores
#      only the selected device's initial bearing; inertial displacement then
#      updates the predicted bearing as the user moves. Natural looks toward
#      the predicted cone can refine the unknown target range automatically.
#
# Important limitation: the MPU6500 has no magnetometer or external position
# reference, so the inertial displacement remains approximate and is guarded
# by an uncertainty threshold. No room-wide target map or repeated captures are
# required for the single selected Kasa device.
#
GYRO_LSB_PER_DPS = 131.0
ACCEL_LSB_PER_G = 16384.0


class SpatialResolver:
    """Single-target, bearing-only spatial tracker for one Kasa device.

    Spatial interaction is intentionally framed around one fixed target:

      1. SET INITIAL DIRECTION while facing the selected Kasa device.
         This stores only the target bearing; no distance is requested.
      2. The headset establishes a local frame at P0 = (0, 0).
      3. The IMU estimates the user's displacement from P0 using gyro-assisted
         attitude compensation plus horizontal accelerometer integration.
      4. The target is assumed to lie on the original bearing ray from P0.
      5. As the user moves, the tracker predicts the target's *current bearing*
         from the translated observation point.
      6. When the user naturally looks toward the predicted bearing, the current
         head bearing can act as a new geometric bearing observation.  The
         intersection of that ray with the original target ray gives a range
         estimate.  This happens automatically; there are no per-position
         capture steps.

    The important output is therefore not absolute room position. It is the
    current target bearing plus a conservative uncertainty cone.

    The headset is expected to remain roughly upright. Accelerometer gravity
    removal / roll-pitch leveling is retained so ordinary head tilt does not
    become horizontal walking motion.

    No camera, magnetometer, external beacons, or firmware changes are used.
    """

    YAW_AXIS = "gz"

    # Keep the existing quick-turn gyro model unchanged.
    GYRO_DEADBAND_DPS = 1.25
    GYRO_BIAS_LEARN_RATE = 0.01

    # Stationary / attitude estimation.
    STATIONARY_GYRO_DPS = 5.0
    STATIONARY_ACCEL_TOL_G = 0.045
    STATIONARY_HOLD_S = 0.25
    REST_BASELINE_LEARN_ALPHA = 0.03

    # Motion / step timing. Magnitude is used only to find gait boundaries;
    # the vector is used for displacement direction.
    STEP_MIN_INTERVAL_S = 0.28
    STEP_MAX_INTERVAL_S = 2.0
    STEP_THRESHOLD_G = 0.010
    STEP_REARM_THRESHOLD_G = 0.000
    STEP_CONFIRM_S = 0.03

    # Adaptive step distance.
    DEFAULT_STEP_LENGTH_M = 0.68
    MIN_STEP_DISTANCE_M = 0.15
    MAX_STEP_DISTANCE_M = 1.50
    STEP_LENGTH_MIN_M = 0.40
    STEP_LENGTH_MAX_M = 1.05
    STEP_LENGTH_LEARN_ALPHA = 0.18

    # Vector / gravity filters.
    GRAVITY_LP_TAU_S = 0.60
    LINEAR_ACCEL_LP_TAU_S = 0.10
    GROUND_SPEED_DECAY = 0.985

    # Single-target bearing geometry.
    INITIAL_TARGET_RANGE_NOMINAL_M = 3.0
    TARGET_RANGE_MIN_M = 0.60
    TARGET_RANGE_MAX_M = 8.00
    TARGET_RANGE_DEFAULT_SIGMA_M = 2.00
    TARGET_RANGE_MIN_SIGMA_M = 0.20
    TARGET_RANGE_LEARN_ALPHA = 0.20
    MIN_GEOMETRY_BASELINE_M = 0.35
    RAY_PARALLEL_SIN_MIN = 0.12
    MIN_INTERSECTION_FORWARD_M = 0.15
    MIN_RANGE_OBSERVATION_M = 0.60
    MAX_RANGE_OBSERVATION_M = 8.00

    # The actual interaction cone is deliberately narrower than the automatic
    # acquisition cone.  The broad cone is used only to recognize that the user
    # is probably re-acquiring the single target; a gesture still requires the
    # smaller fire cone.
    FIRE_TOLERANCE_DEG = 20.0
    ACQUISITION_TOLERANCE_DEG = 32.0
    MIN_HEADING_RATE_FOR_ACQUISITION_DPS = 6.0

    # The cone widens modestly while target range remains uncertain.
    MAX_UNCERTAINTY_CONE_DEG = 28.0

    # Position uncertainty is only a safety gate for the inertial displacement;
    # it is not used as a hard step-count cutoff.
    MAX_POSITION_UNCERTAINTY_M = 1.10

    # Existing hardware assumptions.
    SENSOR_YAW_OFFSET_DEG = 0.0

    def __init__(self):
        self.room_tracking = False
        self.reset()

    @staticmethod
    def _wrap(degrees: float) -> float:
        while degrees > 180.0:
            degrees -= 360.0
        while degrees <= -180.0:
            degrees += 360.0
        return degrees

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        return SpatialResolver._wrap(a - b)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _cross(ax: float, ay: float, bx: float, by: float) -> float:
        return ax * by - ay * bx

    @staticmethod
    def _circular_mean_deg(values):
        if not values:
            return 0.0
        sx = sum(math.cos(math.radians(v)) for v in values)
        sy = sum(math.sin(math.radians(v)) for v in values)
        if abs(sx) < 1e-9 and abs(sy) < 1e-9:
            return values[-1]
        return math.degrees(math.atan2(sy, sx))

    def reset(self):
        # Local frame. x/y are displacement from the current target-direction
        # reference point P0, not an absolute room coordinate.
        self.x_m = 0.0
        self.y_m = 0.0
        self.yaw_deg = 0.0
        self._last_ts_ms = None
        self._gyro_rate_dps = 0.0
        self._gyro_bias_dps = 0.0

        # Gravity / stationary state.
        self._gravity_x_g = 0.0
        self._gravity_y_g = 0.0
        self._gravity_z_g = 1.0
        self._rest_accel_norm_g = None
        self._stationary_since_ms = None
        self._is_stationary = False

        # Motion detector.
        self._accel_norm_lp_g = 1.0
        self._motion_signal_g = 0.0
        self._last_motion_signal_g = 0.0
        self._last_step_ts_ms = None
        self._step_crossing_since_ms = None
        self._step_armed = True

        # Tilt / leveled linear acceleration.
        self._roll_deg = 0.0
        self._pitch_deg = 0.0
        self._lin_ax_g = 0.0
        self._lin_ay_g = 0.0
        self._lin_az_g = 0.0

        # Per-step vector integration.
        self._step_vx_mps = 0.0
        self._step_vy_mps = 0.0
        self._step_dx_m = 0.0
        self._step_dy_m = 0.0
        self._step_time_s = 0.0
        self._step_accel_energy = 0.0

        self.step_count = 0
        self.last_step_interval_s = None
        self.cadence_spm = 0.0
        self.speed_mps = 0.0
        self.step_length_m = self.DEFAULT_STEP_LENGTH_M

        # Conservative inertial displacement uncertainty.
        self.position_uncertainty_m = 0.0
        self.position_confidence = 1.0
        self.packet_count = 0

        # Single target state.
        self.targets = {}                  # alias -> initial world bearing
        self.target_observations = {}      # alias -> natural bearing observations
        self.target_positions = {}         # alias -> estimated target point
        self.target_residuals_m = {}       # alias -> range/bearing residual proxy

        self.target_alias = None
        self.initial_target_heading_deg = None
        self.target_range_m = None
        self.target_range_sigma_m = self.TARGET_RANGE_DEFAULT_SIGMA_M
        self._target_range_nominal_m = self.INITIAL_TARGET_RANGE_NOMINAL_M
        self._last_range_update_ms = None
        self._last_acquisition_heading_deg = None
        self._natural_observation_count = 0
        self._target_locked = False

        self._pose_history = []
        self._pose_history_max_s = 0.6

    @property
    def heading_deg(self) -> float:
        return self._wrap(self.yaw_deg)

    @property
    def position(self):
        return self.x_m, self.y_m

    @property
    def pitch_deg(self) -> float:
        """Estimated pitch from the gravity vector for gyro-keyboard navigation."""
        return float(self._pitch_deg)

    @property
    def is_stationary(self) -> bool:
        return bool(self._is_stationary)

    @property
    def calibration_count(self) -> int:
        return self._natural_observation_count

    @property
    def target_bearing_deg(self):
        bearing, _, _ = self._predicted_target_bearing()
        return bearing

    @property
    def target_cone_half_width_deg(self):
        _, cone, _ = self._predicted_target_bearing()
        return cone

    @property
    def target_range_display_m(self):
        return self.target_range_m if self.target_range_m is not None else self._target_range_nominal_m

    @property
    def target_range_known(self) -> bool:
        return self.target_range_m is not None

    @property
    def target_status(self) -> str:
        if self.initial_target_heading_deg is None:
            return "unset"
        if self.target_range_m is None:
            return "bearing set · range learning"
        return "bearing tracked"

    def set_room_tracking(self, enabled: bool, clear_map: bool = True):
        enabled = bool(enabled)
        if enabled and not self.room_tracking:
            if clear_map:
                self.targets.clear()
                self.target_observations.clear()
                self.target_positions.clear()
                self.target_residuals_m.clear()
                self.target_alias = None
                self.initial_target_heading_deg = None
                self.target_range_m = None
                self.target_range_sigma_m = self.TARGET_RANGE_DEFAULT_SIGMA_M
                self._target_range_nominal_m = self.INITIAL_TARGET_RANGE_NOMINAL_M
                self._natural_observation_count = 0
                self._target_locked = False
            # New spatial session starts at P0 without changing the user's
            # current heading estimate or gyro-bias behaviour.
            self._reset_pdr_session()
        self.room_tracking = enabled

    def _reset_pdr_session(self):
        self.x_m = 0.0
        self.y_m = 0.0
        self._last_step_ts_ms = None
        self._stationary_since_ms = None
        self._is_stationary = False
        self._gravity_x_g = 0.0
        self._gravity_y_g = 0.0
        self._gravity_z_g = 1.0
        self._rest_accel_norm_g = None
        self._accel_norm_lp_g = 1.0
        self._motion_signal_g = 0.0
        self._last_motion_signal_g = 0.0
        self._step_crossing_since_ms = None
        self._step_armed = True
        self._lin_ax_g = 0.0
        self._lin_ay_g = 0.0
        self._lin_az_g = 0.0
        self._step_vx_mps = 0.0
        self._step_vy_mps = 0.0
        self._step_dx_m = 0.0
        self._step_dy_m = 0.0
        self._step_time_s = 0.0
        self._step_accel_energy = 0.0
        self.step_count = 0
        self.last_step_interval_s = None
        self.cadence_spm = 0.0
        self.speed_mps = 0.0
        self.step_length_m = self.DEFAULT_STEP_LENGTH_M
        self.position_uncertainty_m = 0.0
        self.position_confidence = 1.0
        self._pose_history.clear()
        self._last_range_update_ms = None
        self._last_acquisition_heading_deg = None

    def update(self, timestamp_ms: int, ax: int, ay: int, az: int,
               gx: int, gy: int, gz: int):
        ax_g = float(ax) / ACCEL_LSB_PER_G
        ay_g = float(ay) / ACCEL_LSB_PER_G
        az_g = float(az) / ACCEL_LSB_PER_G
        accel_norm_g = math.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g)

        axis_values = {"gx": gx, "gy": gy, "gz": gz}
        raw_dps = float(axis_values.get(self.YAW_AXIS, gz)) / GYRO_LSB_PER_DPS

        if self._last_ts_ms is None:
            self._last_ts_ms = int(timestamp_ms)
            self.packet_count += 1
            self._gravity_x_g = ax_g
            self._gravity_y_g = ay_g
            self._gravity_z_g = az_g
            self._accel_norm_lp_g = accel_norm_g
            return

        dt_ms = (int(timestamp_ms) - int(self._last_ts_ms)) & 0xFFFFFFFF
        self._last_ts_ms = int(timestamp_ms)
        if dt_ms == 0 or dt_ms > 250:
            self.packet_count += 1
            return
        dt_s = dt_ms / 1000.0

        if self._rest_accel_norm_g is None:
            self._rest_accel_norm_g = accel_norm_g
        else:
            calm_for_baseline = abs(raw_dps - self._gyro_bias_dps) < 8.0
            if calm_for_baseline:
                self._rest_accel_norm_g += self.REST_BASELINE_LEARN_ALPHA * (
                    accel_norm_g - self._rest_accel_norm_g
                )

        baseline_norm = self._rest_accel_norm_g if self._rest_accel_norm_g is not None else 1.0
        accel_error_g = abs(accel_norm_g - baseline_norm)

        # Preserve the existing quick-turn gyro bias learner. This is the one
        # heading-estimation behaviour intentionally not rewritten here.
        instant_stationary = (
            abs(raw_dps - self._gyro_bias_dps) <= self.STATIONARY_GYRO_DPS
            and accel_error_g <= self.STATIONARY_ACCEL_TOL_G
        )
        if instant_stationary:
            if self._stationary_since_ms is None:
                self._stationary_since_ms = int(timestamp_ms)
            elif int(timestamp_ms) - self._stationary_since_ms >= int(self.STATIONARY_HOLD_S * 1000):
                self._is_stationary = True
        else:
            self._stationary_since_ms = None
            self._is_stationary = False

        if self._is_stationary:
            self._step_vx_mps *= self.GROUND_SPEED_DECAY
            self._step_vy_mps *= self.GROUND_SPEED_DECAY
            if abs(self._step_vx_mps) < 0.015:
                self._step_vx_mps = 0.0
            if abs(self._step_vy_mps) < 0.015:
                self._step_vy_mps = 0.0

        corrected_dps = raw_dps - self._gyro_bias_dps
        self._gyro_rate_dps = 0.82 * self._gyro_rate_dps + 0.18 * corrected_dps
        rate = self._gyro_rate_dps
        if abs(rate) < self.GYRO_DEADBAND_DPS:
            rate = 0.0
        self.yaw_deg = self._wrap(self.yaw_deg + rate * dt_s)

        # Gravity estimate in sensor frame, and pitch/roll derived from it.
        # MOVED HERE, before the room_tracking early-return below: this is
        # simple, self-contained math (exponential smoothing of the
        # gravity-projected accelerometer axes, no step-detection/PDR
        # state involved) that has nothing to do with room-tracking mode
        # specifically. It was previously placed AFTER the "if not
        # self.room_tracking: return" check, which meant pitch_deg (and
        # roll_deg) never updated past their initial value of 0.0 whenever
        # room_tracking was off — which is the DEFAULT state (self.room_tracking
        # = False in __init__) and has nothing to do with using the Gyro
        # Keyboard. yaw updated fine (it's computed above, unconditionally),
        # so left/right worked while up/down stayed frozen at zero — exactly
        # the reported "doesn't know what is up or down" symptom.
        g_alpha = math.exp(-dt_s / self.GRAVITY_LP_TAU_S)
        self._gravity_x_g = g_alpha * self._gravity_x_g + (1.0 - g_alpha) * ax_g
        self._gravity_y_g = g_alpha * self._gravity_y_g + (1.0 - g_alpha) * ay_g
        self._gravity_z_g = g_alpha * self._gravity_z_g + (1.0 - g_alpha) * az_g

        gxg, gyg, gzg = self._gravity_x_g, self._gravity_y_g, self._gravity_z_g
        self._roll_deg = math.degrees(math.atan2(gyg, gzg))
        self._pitch_deg = math.degrees(
            math.atan2(-gxg, math.sqrt(gyg * gyg + gzg * gzg) + 1e-9)
        )

        # Legacy mode remains a simple relative heading mode and does not
        # accumulate PDR state in the background. Everything below this
        # point (linear acceleration removal, world-frame projection, gait
        # timing/step detection) IS genuinely room-tracking-specific, so
        # it stays gated behind this check.
        if not self.room_tracking:
            self.packet_count += 1
            return


        # Remove gravity, low-pass the residual, then level it into the
        # headset-horizontal frame. This preserves the previous upright/tilt
        # handling rather than treating head tilt as walking direction.
        lax = ax_g - self._gravity_x_g
        lay = ay_g - self._gravity_y_g
        laz = az_g - self._gravity_z_g
        lin_alpha = math.exp(-dt_s / self.LINEAR_ACCEL_LP_TAU_S)
        self._lin_ax_g = lin_alpha * self._lin_ax_g + (1.0 - lin_alpha) * lax
        self._lin_ay_g = lin_alpha * self._lin_ay_g + (1.0 - lin_alpha) * lay
        self._lin_az_g = lin_alpha * self._lin_az_g + (1.0 - lin_alpha) * laz

        world_ax_g, world_ay_g = self._sensor_linear_to_room_xy(
            self._lin_ax_g, self._lin_ay_g, self._lin_az_g
        )

        # Gait timing signal.
        lp_alpha = math.exp(-dt_s / 0.50)
        self._accel_norm_lp_g = lp_alpha * self._accel_norm_lp_g + (1.0 - lp_alpha) * accel_norm_g
        hp_g = accel_norm_g - self._accel_norm_lp_g
        motion_alpha = math.exp(-dt_s / 0.08)
        self._motion_signal_g = motion_alpha * self._motion_signal_g + (1.0 - motion_alpha) * hp_g

        if self._step_armed and self._motion_signal_g > self.STEP_THRESHOLD_G:
            if self._step_crossing_since_ms is None:
                self._step_crossing_since_ms = int(timestamp_ms)
            elif int(timestamp_ms) - self._step_crossing_since_ms >= int(self.STEP_CONFIRM_S * 1000):
                if not self._is_stationary:
                    if self._last_step_ts_ms is None:
                        valid_interval = True
                    else:
                        step_dt_s = (int(timestamp_ms) - self._last_step_ts_ms) / 1000.0
                        valid_interval = self.STEP_MIN_INTERVAL_S <= step_dt_s <= self.STEP_MAX_INTERVAL_S
                    if valid_interval:
                        self._register_step(int(timestamp_ms))
                self._step_armed = False
                self._step_crossing_since_ms = None
        elif not self._step_armed and self._motion_signal_g <= self.STEP_REARM_THRESHOLD_G:
            self._step_armed = True

        if not self._is_stationary:
            ax_mps2 = world_ax_g * 9.80665
            ay_mps2 = world_ay_g * 9.80665
            self._step_vx_mps += ax_mps2 * dt_s
            self._step_vy_mps += ay_mps2 * dt_s
            self._step_vx_mps *= 0.995
            self._step_vy_mps *= 0.995
            self._step_dx_m += self._step_vx_mps * dt_s
            self._step_dy_m += self._step_vy_mps * dt_s
            self._step_time_s += dt_s
            self._step_accel_energy += math.hypot(ax_mps2, ay_mps2) * dt_s

        if self._is_stationary:
            self.speed_mps *= 0.80
            if self.speed_mps < 0.03:
                self.speed_mps = 0.0

        self._last_motion_signal_g = self._motion_signal_g
        self.packet_count += 1

        # Keep short stable history for diagnostics / natural bearing updates.
        if self._is_stationary or (
            abs(self._gyro_rate_dps) <= self.STATIONARY_GYRO_DPS
            and abs(self._motion_signal_g) <= self.STEP_THRESHOLD_G * 1.5
        ):
            self._pose_history.append((int(timestamp_ms), self.x_m, self.y_m, self.heading_deg))
            cutoff = int(timestamp_ms) - int(self._pose_history_max_s * 1000)
            while self._pose_history and self._pose_history[0][0] < cutoff:
                self._pose_history.pop(0)

        self._update_position_confidence()
        self._maybe_refine_target_range(int(timestamp_ms))

    def _update_position_confidence(self):
        self.position_confidence = self._clamp(
            1.0 / (1.0 + self.position_uncertainty_m),
            0.15,
            1.0,
        )

    def _sensor_linear_to_room_xy(self, ax_g: float, ay_g: float, az_g: float):
        # Approximate leveling rotation. The IMU X/Y axes are assumed to be
        # headset-forward/right and Z up. Yaw then rotates the horizontal vector
        # into the local P0 reference frame.
        roll = math.radians(self._roll_deg)
        pitch = math.radians(self._pitch_deg)

        # Undo roll.
        ay1 = ay_g * math.cos(roll) - az_g * math.sin(roll)
        az1 = ay_g * math.sin(roll) + az_g * math.cos(roll)
        # Undo pitch.
        ax2 = ax_g * math.cos(pitch) + az1 * math.sin(pitch)
        # az2 is not required for the horizontal plane.
        az2 = -ax_g * math.sin(pitch) + az1 * math.cos(pitch)
        del az2

        yaw = math.radians(self.heading_deg + self.SENSOR_YAW_OFFSET_DEG)
        room_x = ax2 * math.cos(yaw) - ay1 * math.sin(yaw)
        room_y = ax2 * math.sin(yaw) + ay1 * math.cos(yaw)
        return room_x, room_y

    def _register_step(self, timestamp_ms: int):
        if self._last_step_ts_ms is not None:
            interval_s = (timestamp_ms - self._last_step_ts_ms) / 1000.0
            self.last_step_interval_s = interval_s
            if interval_s > 0:
                self.cadence_spm = 60.0 / interval_s
        self._last_step_ts_ms = timestamp_ms

        dx = self._step_dx_m
        dy = self._step_dy_m
        observed_distance = math.hypot(dx, dy)

        if self.MIN_STEP_DISTANCE_M <= observed_distance <= self.MAX_STEP_DISTANCE_M:
            step_distance = observed_distance
            move_dx = dx
            move_dy = dy
        else:
            # Bounded fallback for a poorly integrated individual gait cycle.
            # The normal path remains vector-derived from acceleration.
            heading = math.radians(self.heading_deg)
            step_distance = self.step_length_m
            move_dx = step_distance * math.cos(heading)
            move_dy = step_distance * math.sin(heading)

        self.x_m += move_dx
        self.y_m += move_dy
        self.step_count += 1

        if self.last_step_interval_s and self.last_step_interval_s > 0:
            self.speed_mps = step_distance / self.last_step_interval_s

        self.step_length_m = self._clamp(
            (1.0 - self.STEP_LENGTH_LEARN_ALPHA) * self.step_length_m
            + self.STEP_LENGTH_LEARN_ALPHA * step_distance,
            self.STEP_LENGTH_MIN_M,
            self.STEP_LENGTH_MAX_M,
        )

        heading_sigma_rad = math.radians(8.0)
        step_sigma = max(0.08, 0.18 * step_distance)
        directional_sigma = abs(step_distance * math.sin(heading_sigma_rad))
        self.position_uncertainty_m = math.sqrt(
            self.position_uncertainty_m ** 2
            + step_sigma ** 2
            + directional_sigma ** 2
        )

        self._step_vx_mps = 0.0
        self._step_vy_mps = 0.0
        self._step_dx_m = 0.0
        self._step_dy_m = 0.0
        self._step_time_s = 0.0
        self._step_accel_energy = 0.0
        self._update_position_confidence()

    def set_initial_direction(self, alias: str):
        """Set the single target's initial bearing and reset P0 to now."""
        alias = str(alias).strip()
        if not alias or alias == "— no device —":
            return False, "No Kasa target selected."

        self.target_alias = alias
        self.targets = {alias: self.heading_deg}
        self.target_observations = {alias: []}
        self.target_positions = {}
        self.target_residuals_m = {}

        self.x_m = 0.0
        self.y_m = 0.0
        self.position_uncertainty_m = 0.0
        self.position_confidence = 1.0

        self.initial_target_heading_deg = self.heading_deg
        self.target_range_m = None
        self.target_range_sigma_m = self.TARGET_RANGE_DEFAULT_SIGMA_M
        self._target_range_nominal_m = self.INITIAL_TARGET_RANGE_NOMINAL_M
        self._last_range_update_ms = None
        self._last_acquisition_heading_deg = None
        self._natural_observation_count = 0
        self._target_locked = True
        self._step_vx_mps = 0.0
        self._step_vy_mps = 0.0
        self._step_dx_m = 0.0
        self._step_dy_m = 0.0

        # Store the initial point as a zero-length natural reference.
        self.target_observations[alias].append((0.0, 0.0, self.heading_deg, None))
        self.target_positions[alias] = self._estimated_target_point()
        return True, f"{alias}: initial direction set at {self.heading_deg:+.1f}°"

    def calibrate_target(self, alias: str):
        # Keep the old app callback name, but it now performs the new
        # one-button setup rather than collecting repeated captures.
        return self.set_initial_direction(alias)

    def clear_target(self, alias: str):
        alias = str(alias)
        self.targets.pop(alias, None)
        self.target_observations.pop(alias, None)
        self.target_positions.pop(alias, None)
        self.target_residuals_m.pop(alias, None)
        if alias == self.target_alias:
            self.target_alias = None
            self.initial_target_heading_deg = None
            self.target_range_m = None
            self._target_locked = False
            self._natural_observation_count = 0

    def _estimated_target_point(self):
        if self.initial_target_heading_deg is None:
            return 0.0, 0.0
        r = self.target_range_display_m
        theta = math.radians(self.initial_target_heading_deg)
        return r * math.cos(theta), r * math.sin(theta)

    def _predicted_target_bearing(self):
        """Return (bearing_deg, uncertainty_half_width_deg, distance_m).

        This is the core of the single-target model: the target remains on the
        original P0 bearing ray while the user translates through the local
        frame.  A range estimate, when available, collapses the cone.  Before
        range has been learned, the cone is based on a conservative family of
        plausible target distances rather than demanding a user-supplied range.
        """
        if self.initial_target_heading_deg is None:
            return None, 180.0, None

        ranges = []
        if self.target_range_m is not None:
            sigma = max(self.TARGET_RANGE_MIN_SIGMA_M, self.target_range_sigma_m)
            low = self._clamp(self.target_range_m - 1.5 * sigma, self.TARGET_RANGE_MIN_M, self.TARGET_RANGE_MAX_M)
            high = self._clamp(self.target_range_m + 1.5 * sigma, self.TARGET_RANGE_MIN_M, self.TARGET_RANGE_MAX_M)
            ranges = [low, self.target_range_m, high]
        else:
            # Log-spaced range hypotheses preserve useful near/far geometry
            # without pretending we know the bulb's distance.
            for i in range(25):
                frac = i / 24.0
                ranges.append(
                    self.TARGET_RANGE_MIN_M
                    * (self.TARGET_RANGE_MAX_M / self.TARGET_RANGE_MIN_M) ** frac
                )

        theta0 = math.radians(self.initial_target_heading_deg)
        ux = math.cos(theta0)
        uy = math.sin(theta0)
        bearings = []
        distances = []
        for r in ranges:
            tx = r * ux
            ty = r * uy
            dx = tx - self.x_m
            dy = ty - self.y_m
            d = math.hypot(dx, dy)
            if d < 1e-6:
                bearings.append(self.heading_deg)
            else:
                bearings.append(math.degrees(math.atan2(dy, dx)))
            distances.append(d)

        central = self._circular_mean_deg(bearings)
        spread = max(abs(self._angle_diff(b, central)) for b in bearings)
        spread = min(spread, self.MAX_UNCERTAINTY_CONE_DEG)
        if self.target_range_m is not None:
            # Range uncertainty is additional to the interaction tolerance;
            # keep the cone from becoming implausibly wide after weak updates.
            spread = min(spread, self.MAX_UNCERTAINTY_CONE_DEG)

        nominal = self.target_range_display_m
        tx = nominal * ux
        ty = nominal * uy
        dx = tx - self.x_m
        dy = ty - self.y_m
        distance = math.hypot(dx, dy)
        if distance < 1e-6:
            nominal_bearing = self.heading_deg
        else:
            nominal_bearing = math.degrees(math.atan2(dy, dx))
        return self._wrap(nominal_bearing), spread, distance

    def _current_head_ray_intersection_range(self):
        """Intersect the current head ray with the original target ray.

        P0 + t*u0 = P + s*v
        where t is the estimated target distance from P0.
        """
        if self.initial_target_heading_deg is None:
            return None

        baseline = math.hypot(self.x_m, self.y_m)
        if baseline < self.MIN_GEOMETRY_BASELINE_M:
            return None

        theta0 = math.radians(self.initial_target_heading_deg)
        ux, uy = math.cos(theta0), math.sin(theta0)
        theta = math.radians(self.heading_deg)
        vx, vy = math.cos(theta), math.sin(theta)

        denom = self._cross(ux, uy, vx, vy)
        if abs(denom) < self.RAY_PARALLEL_SIN_MIN:
            return None

        px, py = self.x_m, self.y_m
        t = self._cross(px, py, vx, vy) / denom
        s = self._cross(px, py, ux, uy) / denom

        if t < self.MIN_RANGE_OBSERVATION_M or t > self.MAX_RANGE_OBSERVATION_M:
            return None
        if s < self.MIN_INTERSECTION_FORWARD_M:
            return None
        return t

    def _maybe_refine_target_range(self, timestamp_ms: int):
        if not self.room_tracking or self.initial_target_heading_deg is None:
            return

        # We only use the current head bearing as a *natural* measurement when
        # it is already near the currently predicted target cone. This prevents
        # arbitrary looks from redefining the bulb location.
        bearing, cone, _ = self._predicted_target_bearing()
        if bearing is None:
            return

        diff = abs(self._angle_diff(self.heading_deg, bearing))
        if diff > self.ACQUISITION_TOLERANCE_DEG + cone:
            return
        if abs(self._gyro_rate_dps) > self.MIN_HEADING_RATE_FOR_ACQUISITION_DPS:
            return

        if self._last_range_update_ms is not None and timestamp_ms - self._last_range_update_ms < 150:
            return

        observed_range = self._current_head_ray_intersection_range()
        if observed_range is None:
            return

        if self.target_range_m is None:
            self.target_range_m = observed_range
            self.target_range_sigma_m = max(
                self.TARGET_RANGE_MIN_SIGMA_M,
                min(self.TARGET_RANGE_DEFAULT_SIGMA_M, observed_range * 0.30),
            )
        else:
            # Robust EWMA. Reject a gross one-off ray intersection rather than
            # letting one odd head movement jump the estimated target distance.
            innovation = observed_range - self.target_range_m
            max_jump = max(0.45, 0.45 * self.target_range_sigma_m)
            innovation = self._clamp(innovation, -max_jump, max_jump)
            self.target_range_m += self.TARGET_RANGE_LEARN_ALPHA * innovation
            self.target_range_m = self._clamp(
                self.target_range_m, self.TARGET_RANGE_MIN_M, self.TARGET_RANGE_MAX_M
            )
            abs_innov = abs(observed_range - self.target_range_m)
            self.target_range_sigma_m = self._clamp(
                (1.0 - 0.12) * self.target_range_sigma_m + 0.12 * abs_innov,
                self.TARGET_RANGE_MIN_SIGMA_M,
                self.TARGET_RANGE_DEFAULT_SIGMA_M,
            )

        self._target_range_nominal_m = self.target_range_m
        self._last_range_update_ms = timestamp_ms
        self._last_acquisition_heading_deg = self.heading_deg
        self._natural_observation_count += 1

        alias = self.target_alias
        if alias:
            self.target_observations.setdefault(alias, []).append(
                (self.x_m, self.y_m, self.heading_deg, self.target_range_m)
            )
            if len(self.target_observations[alias]) > 32:
                del self.target_observations[alias][:-32]
            self.target_positions[alias] = self._estimated_target_point()
            self.target_residuals_m[alias] = self.target_range_sigma_m

    def target_for_current_heading(self):
        """Return (alias, angular_error_deg) only inside the safe target cone."""
        if not self.room_tracking:
            # Preserve the original relative-target behaviour when movement
            # tracking is disabled.
            if not self.targets:
                return None, None
            ranked = sorted(
                (
                    (abs(self._angle_diff(self.heading_deg, angle)), alias)
                    for alias, angle in self.targets.items()
                ),
                key=lambda item: item[0],
            )
            best_diff, best_alias = ranked[0]
            if best_diff > self.FIRE_TOLERANCE_DEG:
                return None, best_diff
            return best_alias, best_diff

        if self.initial_target_heading_deg is None or not self.target_alias:
            return None, None
        if self.position_uncertainty_m > self.MAX_POSITION_UNCERTAINTY_M:
            return None, None

        bearing, cone, _ = self._predicted_target_bearing()
        if bearing is None:
            return None, None

        # The cone is an uncertainty margin around the geometrically predicted
        # bearing. A gesture can execute only in the tighter fire cone around
        # the current estimate, not across the entire uncertainty interval.
        allowed_error = self.FIRE_TOLERANCE_DEG + cone
        diff = abs(self._angle_diff(self.heading_deg, bearing))
        if diff > allowed_error:
            return None, diff
        return self.target_alias, diff

    def target_debug(self):
        bearing, cone, distance = self._predicted_target_bearing()
        return {
            "alias": self.target_alias,
            "initial_heading_deg": self.initial_target_heading_deg,
            "predicted_bearing_deg": bearing,
            "cone_half_width_deg": cone,
            "target_distance_m": distance,
            "range_estimate_m": self.target_range_m,
            "range_sigma_m": self.target_range_sigma_m if self.target_range_m is not None else self.TARGET_RANGE_DEFAULT_SIGMA_M,
            "natural_observations": self._natural_observation_count,
        }

class KasaWorker(QThread):
    """
    Background worker for python-kasa.

    The Volition GUI must never await network operations directly.  Commands
    are queued here; discovery and device actions run in this QThread's own
    asyncio loop.  This keeps the signal-processing/UI path responsive.
    """

    devices_found = Signal(list)
    status = Signal(str)
    state_changed = Signal(str, bool)
    ready = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._commands = queue.Queue()
        self._stop_event = threading.Event()
        self._devices = {}
        self._started_once = False

    def enqueue(self, command: str, argument=None):
        self._commands.put((command, argument))

    def stop_worker(self):
        self._stop_event.set()
        self._commands.put(("__stop__", None))

    def run(self):
        if _kasa is None:
            self.status.emit("python-kasa is not installed. Run: pip install python-kasa")
            self.ready.emit(False)
            return

        try:
            asyncio.run(self._main())
        except Exception as exc:
            self.status.emit(f"Kasa worker failed: {type(exc).__name__}: {exc}")
            self.ready.emit(False)

    async def _main(self):
        self.status.emit("Kasa controller ready.")
        self.ready.emit(True)

        while not self._stop_event.is_set():
            try:
                command, argument = self._commands.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if command == "__stop__":
                break

            try:
                if command == "discover":
                    await self._discover()
                elif command == "toggle":
                    await self._toggle(argument)
                elif command == "on":
                    await self._set_power(argument, True)
                elif command == "off":
                    await self._set_power(argument, False)
                elif command == "refresh":
                    await self._refresh(argument)
            except Exception as exc:
                self.status.emit(
                    f"Kasa operation failed: {type(exc).__name__}: {exc}"
                )

        self.ready.emit(False)

    async def _discover(self):
        self.status.emit("Searching local network for Kasa devices...")
        discovered = await _kasa.Discover.discover()
        self._devices.clear()

        # Keep all discovered devices with a usable alias.  This makes the
        # controller extensible to additional Kasa models later.
        for address, device in discovered.items():
            try:
                await device.update()
            except Exception:
                pass
            alias = str(getattr(device, "alias", "") or "").strip()
            if not alias:
                alias = str(address)
            self._devices[alias] = device

        aliases = list(self._devices.keys())
        self.devices_found.emit(aliases)

        if aliases:
            self.status.emit(f"Found {len(aliases)} Kasa device(s).")
            for alias, device in self._devices.items():
                self.status.emit(
                    f"Kasa: {alias} | model={getattr(device, 'model', 'unknown')}"
                )
        else:
            self.status.emit("No Kasa devices found on the local network.")

    async def _refresh(self, alias):
        device = self._devices.get(alias)
        if device is None:
            self.status.emit(f"Kasa device '{alias}' is not available.")
            return

        await device.update()
        self.state_changed.emit(alias, bool(device.is_on))

    async def _toggle(self, alias):
        device = self._devices.get(alias)
        if device is None:
            self.status.emit(f"Kasa device '{alias}' is not available.")
            return

        await device.update()
        if device.is_on:
            await device.turn_off()
        else:
            await device.turn_on()
        await device.update()

        self.state_changed.emit(alias, bool(device.is_on))
        self.status.emit(
            f"KASA  {alias} → {'ON' if device.is_on else 'OFF'}"
        )

    async def _set_power(self, alias, on: bool):
        device = self._devices.get(alias)
        if device is None:
            self.status.emit(f"Kasa device '{alias}' is not available.")
            return

        if on:
            await device.turn_on()
        else:
            await device.turn_off()
        await device.update()
        self.state_changed.emit(alias, bool(device.is_on))
        self.status.emit(
            f"KASA  {alias} → {'ON' if device.is_on else 'OFF'}"
        )


# ── Training thread ───────────────────────────────────────────────────────────

class _TrainThread(QThread):
    """
    Runs train_classifier's pipeline in-process on a background thread,
    so the UI stays responsive and the packaged .exe doesn't need a
    real Python interpreter available at runtime (see _on_train_clicked
    docstring for why subprocess+sys.executable would break here).

    Captures print() output from train_classifier by temporarily
    redirecting stdout to a queue-like buffer during the call, so
    progress can be streamed into the activity log line by line.
    """
    line_ready   = Signal(str)
    finished_ok  = Signal(str)
    finished_err = Signal(str)

    def __init__(self, mode: str):
        super().__init__()
        self.mode = mode

    def run(self):
        import io
        import contextlib
        import json as _json
        from tflite_classifier import _writable_data_dir, _bundled_data_dir

        buf = io.StringIO()
        try:
            import train_classifier as tc

            if self.mode not in tc.MODE_CONFIG:
                self.finished_err.emit(f"Unknown mode '{self.mode}'")
                return

            cfg = tc.MODE_CONFIG[self.mode]

            # MODE_CONFIG stores bare relative filenames (e.g.
            # 'volition_training_pfc.csv'). Resolve them against the
            # writable app directory — the same folder the exe itself
            # lives in — rather than trusting the process's current
            # working directory, which can be anything when launched by
            # double-clicking a frozen exe from Explorer.
            base_dir   = _writable_data_dir()
            csv_path   = os.path.join(base_dir, cfg["csv"])
            model_path = os.path.join(base_dir, cfg["model"])
            stats_path = os.path.join(base_dir, cfg["stats"])

            if not os.path.exists(csv_path):
                # Not in the writable folder yet — check if a copy was
                # bundled into the exe at build time (see volition_demo.spec).
                # If so, copy it into the writable folder now so it
                # becomes the live file that future captured samples
                # append onto, same as if it had always lived there.
                bundled_csv = os.path.join(_bundled_data_dir(), cfg["csv"])
                if os.path.exists(bundled_csv):
                    import shutil
                    shutil.copy2(bundled_csv, csv_path)
                    self.line_ready.emit(
                        f"Found bundled '{cfg['csv']}' — copied to {base_dir}")

            if not os.path.exists(csv_path):
                self.finished_err.emit(
                    f"'{cfg['csv']}' not found in {base_dir} — "
                    f"collect training data first.")
                return

            with contextlib.redirect_stdout(buf):
                X, y, stats = tc.load_and_prepare(csv_path, cfg["classes"])
                model = tc.train(X, y, len(cfg["classes"]))
                tc.export_tflite(model, model_path)
                with open(stats_path, "w") as f:
                    _json.dump(stats, f, indent=2)

            # Emit captured output line by line, after the fact — Keras
            # prints progress bars with carriage returns during training
            # which don't stream nicely line-by-line in real time from
            # a redirected buffer, so we surface it all at once here.
            for line in buf.getvalue().splitlines():
                if line.strip():
                    self.line_ready.emit(line.strip())

            self.finished_ok.emit(self.mode)

        except Exception as e:
            # Still emit whatever was captured before the failure, so
            # the log shows context leading up to the error
            for line in buf.getvalue().splitlines():
                if line.strip():
                    self.line_ready.emit(line.strip())
            self.finished_err.emit(str(e))


# ── HID Mapping Dialog ───────────────────────────────────────────────────────

class GyroKeyboardPanel(QWidget):
    """
    Ergonomic accessibility keyboard driven by headset orientation.

    The layout is deliberately NOT a QWERTY grid. Space is the exact
    neutral/resting key at the center of a 7x7 movement field. Common letters
    are placed close to that neutral point, while less common letters and
    utility keys are progressively farther away.

    Gyroscope:
        - yaw  -> left / right movement
        - pitch -> up / down movement

    Volition intent:
        - configured biosignal intent acts as the key "click"

    The selector uses discrete angular zones with hysteresis so small,
    involuntary head movements do not cause the highlight to chatter.
    """

    CLICK_INTENT_CANDIDATES = (
        "EEG_CHEEK_TWITCH",
        "EEG_JAW_CLENCH",
        "EEG_BLINK",
        "CH2_STRONG",
        "CH3_STRONG",
    )

    # 7x7 ergonomic movement field.
    # (3,3) is ALWAYS SPACE: the user's natural resting head position.
    # Letters are arranged roughly by English frequency and movement cost.
    KEY_ROWS = [
        ["1", "2", "Y", "U", "P", "3", "4"],
        ["TAB", "CAPS", "I", "R", "N", ",", "."],
        ["K", "M", "BACKSPACE", "A", "ENTER", "W", "J"],
        ["LEFT", "D", "E", "SPACE", "T", "L", "RIGHT"],
        ["X", "F", "UP", "O", "DOWN", "G", "Q"],
        ["'", "/", "S", "C", "H", "5", "6"],
        ["7", "8", "B", "Z", "V", "9", "0"],
    ]

    ACTION_CANDIDATES = {
        **{chr(ord("A") + i): [f"KEY_{chr(ord('A') + i)}"] for i in range(26)},
        **{str(i): [f"KEY_{i}", f"NUM_{i}"] for i in range(10)},
        "SPACE": ["KEY_SPACE", "SPACE"],
        "BACKSPACE": ["KEY_BACKSPACE", "BACKSPACE"],
        "ENTER": ["KEY_ENTER", "ENTER"],
        "TAB": ["KEY_TAB", "TAB"],
        "CAPS": ["KEY_CAPSLOCK", "KEY_CAPS", "CAPSLOCK", "CAPS"],
        "LEFT": ["KEY_LEFT", "LEFT"],
        "RIGHT": ["KEY_RIGHT", "RIGHT"],
        "UP": ["KEY_UP", "UP"],
        "DOWN": ["KEY_DOWN", "DOWN"],
        ",": ["KEY_COMMA", "COMMA"],
        ".": ["KEY_PERIOD", "KEY_DOT", "PERIOD"],
        "/": ["KEY_SLASH", "SLASH"],
        "'": ["KEY_APOSTROPHE", "KEY_QUOTE", "APOSTROPHE"],
    }

    GRID_CENTER = 3
    YAW_DEG_PER_STEP = 7.5
    PITCH_DEG_PER_STEP = 7.5
    HYSTERESIS_DEG = 2.0
    CENTER_DEADZONE_DEG = 3.0
    CLICK_DEBOUNCE_MS = 350

    SPECIAL_KEYS = {
        "SPACE", "BACKSPACE", "ENTER", "TAB", "CAPS",
        "LEFT", "RIGHT", "UP", "DOWN",
        ",", ".", "/", "'",
    }

    def __init__(self, spatial, hid_controller, log_callback=None, parent=None):
        super().__init__(parent)
        self.spatial = spatial
        self.hid = hid_controller
        self.log_callback = log_callback
        self.active = False
        self._anchor_yaw = 0.0
        self._anchor_pitch = 0.0
        self._selected = (self.GRID_CENTER, self.GRID_CENTER)
        self._buttons = {}
        self._key_actions = self._build_actions()
        self._last_intent_ms = 0
        self._last_click_key = None
        self._last_quantized_yaw = 0
        self._last_quantized_pitch = 0

        self.setStyleSheet(f"""
            QWidget {{ background: {C_BG}; color: {C_TEXT}; }}
            QLabel {{ color: {C_TEXT}; }}
            QPushButton {{
                background: {C_PANEL}; color: {C_TEXT};
                border: 1px solid {C_BORDER}; border-radius: 4px;
                font-family: Consolas; font-weight: bold;
            }}
            QPushButton:hover {{ border-color: {C_ACCENT}; color: {C_ACCENT}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        info = QLabel(
            "ERGONOMIC GYRO KEYBOARD  ·  SPACE = neutral  ·  yaw = left/right  ·  "
            "pitch = up/down  ·  Volition signal = click"
        )
        info.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        info.setWordWrap(True)
        root.addWidget(info)

        range_hint = QLabel(
            "Common letters are closer to center.  Move slowly; keys snap to "
            "10° movement zones with a small stability margin."
        )
        range_hint.setStyleSheet(f"color: {C_MUTED}; font-size: 9px;")
        range_hint.setWordWrap(True)
        root.addWidget(range_hint)

        control_row = QHBoxLayout()
        self.lbl_imu = QLabel("IMU: waiting")
        self.lbl_imu.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        control_row.addWidget(self.lbl_imu, 1)
        control_row.addWidget(QLabel("CLICK:"))
        self.cmb_click_intent = QComboBox()
        candidates = [x for x in self.CLICK_INTENT_CANDIDATES if x in ALL_POSSIBLE_INTENTS]
        if not candidates:
            candidates = list(ALL_POSSIBLE_INTENTS)
        self.cmb_click_intent.addItems(candidates)
        if "EEG_CHEEK_TWITCH" in candidates:
            self.cmb_click_intent.setCurrentText("EEG_CHEEK_TWITCH")
        control_row.addWidget(self.cmb_click_intent, 1)
        btn_center = QPushButton("RECENTER → SPACE")
        btn_center.clicked.connect(self.recenter)
        control_row.addWidget(btn_center)
        root.addLayout(control_row)

        self.lbl_selected = QLabel("SELECTED: SPACE")
        self.lbl_selected.setStyleSheet(
            f"color: {C_ACCENT}; font-size: 13px; font-weight: bold;"
        )
        root.addWidget(self.lbl_selected)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(4)
        self.grid.setVerticalSpacing(4)
        self._build_keyboard()
        root.addLayout(self.grid, 1)

        self.lbl_output = QLabel("LAST KEY: —")
        self.lbl_output.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        root.addWidget(self.lbl_output)

        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._poll_orientation)
        self.timer.start()

    def _build_actions(self):
        available = set(HID_ACTIONS)
        out = {}
        for key, candidates in self.ACTION_CANDIDATES.items():
            out[key] = next((a for a in candidates if a in available), None)
        return out

    def _button_style(self, key, selected=False):
        if selected:
            return (
                f"background: {C_ACCENT}; color: {C_BG}; "
                f"border: 2px solid {C_ACCENT}; font-weight: bold;"
            )
        if key == "SPACE":
            return (
                f"background: {C_PANEL}; color: {C_TEXT}; "
                f"border: 2px solid {C_ACCENT}; font-weight: bold;"
            )
        if key in self.SPECIAL_KEYS:
            return (
                f"background: {C_PANEL}; color: {C_TEXT}; "
                f"border: 1px solid {C_MUTED}; font-weight: bold;"
            )
        return f"background: {C_PANEL}; color: {C_TEXT}; border: 1px solid {C_BORDER};"

    def _build_keyboard(self):
        for r, row in enumerate(self.KEY_ROWS):
            for c, key in enumerate(row):
                label = {
                    "SPACE": "SPACE",
                    "BACKSPACE": "⌫",
                    "ENTER": "ENTER",
                    "TAB": "TAB",
                    "CAPS": "CAPS",
                    "LEFT": "←",
                    "RIGHT": "→",
                    "UP": "↑",
                    "DOWN": "↓",
                }.get(key, key)

                btn = QPushButton(label)
                btn.setMinimumHeight(38)
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                btn.setStyleSheet(self._button_style(key, False))
                btn.clicked.connect(
                    lambda _=False, rr=r, cc=c: self._select_cell(rr, cc)
                )
                self.grid.addWidget(btn, r, c)
                self._buttons[(r, c)] = btn

    def _available_cell(self, row, col):
        row = max(0, min(len(self.KEY_ROWS) - 1, int(row)))
        col = max(0, min(len(self.KEY_ROWS[row]) - 1, int(col)))
        return row, col

    def _highlight(self):
        for (r, c), button in self._buttons.items():
            key = self.KEY_ROWS[r][c]
            button.setStyleSheet(self._button_style(key, (r, c) == self._selected))

        btn = self._buttons.get(self._selected)
        if btn is not None:
            btn.setFocus()

        key = self.KEY_ROWS[self._selected[0]][self._selected[1]]
        self.lbl_selected.setText(f"SELECTED: {key}")

    def _select_cell(self, row, col):
        self._selected = self._available_cell(row, col)
        self._last_quantized_yaw = self._selected[1] - self.GRID_CENTER
        self._last_quantized_pitch = self.GRID_CENTER - self._selected[0]
        self._highlight()

    def activate(self):
        self.active = True
        self.recenter()
        self._highlight()
        self.lbl_imu.setText("IMU: active · neutral = SPACE")

    def deactivate(self):
        self.active = False
        self.lbl_imu.setText("IMU: inactive")

    def recenter(self):
        self._anchor_yaw = float(self.spatial.heading_deg)
        self._anchor_pitch = float(self.spatial.pitch_deg)
        self._selected = (self.GRID_CENTER, self.GRID_CENTER)
        self._last_quantized_yaw = 0
        self._last_quantized_pitch = 0
        self._highlight()
        self.lbl_imu.setText(
            f"IMU: centered at SPACE  ·  yaw {self._anchor_yaw:+.1f}°  "
            f"pitch {self._anchor_pitch:+.1f}°"
        )

    @staticmethod
    def _nearest_zone(delta_deg, step_deg):
        """Quantize an angular displacement symmetrically around zero."""
        raw = float(delta_deg) / float(step_deg)
        if raw >= 0.0:
            return int(math.floor(raw + 0.5))
        return int(math.ceil(raw - 0.5))

    def _quantize_axis(self, delta_deg, current_zone, step_deg):
        """Quantize with a center dead-zone and boundary hysteresis."""
        delta_deg = float(delta_deg)
        if abs(delta_deg) <= self.CENTER_DEADZONE_DEG:
            proposed = 0
        else:
            proposed = self._nearest_zone(delta_deg, step_deg)

        if proposed > current_zone:
            boundary = (current_zone + 0.5) * step_deg
            if delta_deg < boundary + self.HYSTERESIS_DEG:
                proposed = current_zone
        elif proposed < current_zone:
            boundary = (current_zone - 0.5) * step_deg
            if delta_deg > boundary - self.HYSTERESIS_DEG:
                proposed = current_zone

        return max(-self.GRID_CENTER, min(self.GRID_CENTER, proposed))

    def _poll_orientation(self):
        if not self.active:
            return
        if getattr(self.spatial, "packet_count", 0) <= 1:
            self.lbl_imu.setText("IMU: waiting for samples...")
            return

        yaw_delta = self.spatial._angle_diff(self.spatial.heading_deg, self._anchor_yaw)
        pitch_delta = float(self.spatial.pitch_deg) - self._anchor_pitch

        yaw_zone = self._quantize_axis(
            yaw_delta,
            self._last_quantized_yaw,
            self.YAW_DEG_PER_STEP,
        )
        pitch_zone = self._quantize_axis(
            pitch_delta,
            self._last_quantized_pitch,
            self.PITCH_DEG_PER_STEP,
        )

        # Positive yaw -> right. Positive pitch -> up.
        # Invert physical headset direction so movement matches the on-screen selector.
        row = self.GRID_CENTER + pitch_zone
        col = self.GRID_CENTER - yaw_zone
        row, col = self._available_cell(row, col)

        self._last_quantized_yaw = col - self.GRID_CENTER
        self._last_quantized_pitch = self.GRID_CENTER - row

        if (row, col) != self._selected:
            self._selected = (row, col)
            self._highlight()

        key = self.KEY_ROWS[row][col]
        self.lbl_imu.setText(
            f"IMU: yaw {yaw_delta:+.1f}°  pitch {pitch_delta:+.1f}°  ·  {key}"
        )

    def click_selected(self, intent: str):
        if not self.active:
            return False
        if intent != self.cmb_click_intent.currentText():
            return False

        now = int(QDateTime.currentMSecsSinceEpoch())
        if now - self._last_intent_ms < self.CLICK_DEBOUNCE_MS:
            return True
        self._last_intent_ms = now

        key = self.KEY_ROWS[self._selected[0]][self._selected[1]]
        action = self._key_actions.get(key)
        if action is None:
            msg = f"GYRO KEYBOARD  {key}  → unavailable HID action"
            self.lbl_output.setText(f"LAST KEY: {key} (unavailable)")
            if self.log_callback:
                self.log_callback(msg, C_DANGER)
            return True

        try:
            self.hid.execute(action)
            self._last_click_key = key
            self.lbl_output.setText(f"LAST KEY: {key}")
            if self.log_callback:
                self.log_callback(
                    f"GYRO KEYBOARD  {key}  ← {intent}  → {action}",
                    C_ACCENT,
                )
        except Exception as exc:
            self.lbl_output.setText(f"LAST KEY: {key} (error)")
            if self.log_callback:
                self.log_callback(
                    f"GYRO KEYBOARD failed for {key}: {exc}", C_DANGER
                )
        return True


class HIDMappingDialog(QDialog):
    """HID configuration with standard mapping and gyro-controlled keyboard tabs."""

    def __init__(self, current_mapping: dict, spatial, hid_controller, log_callback=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Volition — HID Control")
        self.setMinimumSize(700, 720)
        self.setStyleSheet(f"""
            QDialog      {{ background: {C_BG}; color: {C_TEXT}; font-family: Consolas; }}
            QTableWidget {{ background: {C_PANEL}; color: {C_TEXT};
                            gridline-color: {C_BORDER}; border: 1px solid {C_BORDER}; }}
            QHeaderView::section {{ background: {C_PANEL}; color: {C_ACCENT};
                                    font-weight: bold; font-size: 11px;
                                    border: 1px solid {C_BORDER}; padding: 4px; }}
            QComboBox    {{ background: {C_PANEL}; color: {C_TEXT};
                            border: 1px solid {C_BORDER}; padding: 2px 6px; }}
            QPushButton  {{ background: {C_PANEL}; color: {C_TEXT};
                            border: 1px solid {C_BORDER}; padding: 6px 16px;
                            border-radius: 4px; font-weight: bold; }}
            QPushButton:hover {{ border-color: {C_ACCENT}; color: {C_ACCENT}; }}
            QTabWidget::pane {{ border: 1px solid {C_BORDER}; background: {C_BG}; }}
            QTabBar::tab {{ background: {C_PANEL}; color: {C_MUTED}; padding: 8px 18px;
                            border: 1px solid {C_BORDER}; border-bottom: none; }}
            QTabBar::tab:selected {{ color: {C_ACCENT}; border-color: {C_ACCENT}; }}
        """)

        self._mapping = current_mapping
        self._spatial = spatial
        self._hid = hid_controller
        self.keyboard_active = False

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        hdr = QLabel("HID CONTROL")
        hdr.setStyleSheet(f"color: {C_ACCENT}; font-size: 14px; font-weight: bold;")
        layout.addWidget(hdr)

        tabs = QTabWidget()
        self.tabs = tabs
        tabs.addTab(self._build_standard_tab(), "STANDARD HID → SIGNAL")

        self.keyboard = GyroKeyboardPanel(
            self._spatial, self._hid,
            log_callback=lambda msg, colour: self.parent().log.log(msg, colour)
            if self.parent() is not None and hasattr(self.parent(), "log") else None,
            parent=self,
        )
        tabs.addTab(self.keyboard, "GYRO KEYBOARD")
        tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(tabs, 1)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("CLEAR STANDARD MAPPINGS")
        btn_clear.clicked.connect(self._clear_standard)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        btn_close = QPushButton("CLOSE")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._on_tab_changed(0)

    def _build_standard_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        hint = QLabel(
            "Assign a keyboard/mouse HID action to each Volition signal. "
            "Set to NONE to disable that signal."
        )
        hint.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["SIGNAL", "HID ACTION"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(table.styleSheet() +
            f"QTableWidget::item:alternate {{ background: #141414; }}")

        _colours = {"CH2": C_ACCENT, "CH3": "#ff9944", "BOTH": "#ffdd44", "EEG": "#4fc3f7"}
        table.setRowCount(len(ALL_POSSIBLE_INTENTS))
        for row, intent in enumerate(ALL_POSSIBLE_INTENTS):
            prefix = next((k for k in _colours if intent.startswith(k)), "EEG")
            item = QTableWidgetItem(intent.replace("_", " "))
            item.setForeground(QColor(_colours[prefix]))
            table.setItem(row, 0, item)

            cmb = QComboBox()
            cmb.addItems(HID_ACTIONS)
            cmb.setEditable(True)
            cmb.setInsertPolicy(QComboBox.NoInsert)
            completer = cmb.completer()
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            existing = self._mapping.get(intent, "NONE")
            if existing in HID_ACTIONS:
                cmb.setCurrentText(existing)
            cmb.currentTextChanged.connect(
                lambda text, i=intent: self._mapping.__setitem__(i, text)
                if text in HID_ACTIONS else None)
            table.setCellWidget(row, 1, cmb)
            table.setRowHeight(row, 32)

        layout.addWidget(table)
        return page

    def _on_tab_changed(self, index):
        self.keyboard_active = index == 1
        if self.keyboard_active:
            self.keyboard.activate()
        else:
            self.keyboard.deactivate()

    def _clear_standard(self):
        for intent in list(self._mapping):
            self._mapping[intent] = "NONE"

    def closeEvent(self, event):
        self.keyboard.deactivate()
        self.keyboard_active = False
        super().closeEvent(event)


class VolitionDemoApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VOLITION  ·  Adaptive Biosignal Monitor  (Demo)")
        self.setMinimumSize(760, 680)
        self.setStyleSheet(STYLE)

        # Core objects — arm and HID are intentionally NOT created in
        # this build. IntentEngine still fires on_intent internally
        # (so the log can show what would have triggered), it's just
        # nothing is listening to actually move anything.
        self.ble = BLEManager()
        self.processors = [ChannelProcessor() for _ in range(MAX_CHANNELS)]
        self.intent_engine = IntentEngine()
        self.intent_engine.on_intent = self._on_intent

        # HID controller — keyboard/mouse output, wired per-intent via
        # self._hid_mapping (edited through the CONFIGURE HID dialog)
        self.hid = HIDController()
        self.hid.on_status = lambda msg: self.log.log(msg, C_MUTED)
        self._hid_mapping = {intent: "NONE" for intent in ALL_POSSIBLE_INTENTS}
        self._hid_dialog = None

        from signal_health import SignalHealthMonitor
        self._health = {
            0: SignalHealthMonitor("EEG"),
            1: SignalHealthMonitor("CH2", check_saturation=False),
            2: SignalHealthMonitor("CH3", check_saturation=False),
        }
        self._last_logged_health = {0: "CALIBRATING", 1: "CALIBRATING", 2: "CALIBRATING"}

        # Optional IMU stream + spatial resolver. BLEManager owns the actual
        # BLE subscription and forwards decoded packets into this app.
        self._imu_available = False
        self._imu_packet_count = 0
        self.spatial = SpatialResolver()

        # Smart-device worker is started only when the user asks to discover
        # Kasa devices.
        self._kasa_worker = None
        self._kasa_available = False
        self._kasa_devices = []

        self.num_channels = 0
        self.is_connected = False
        self._active_filter_types = ['emg'] * MAX_CHANNELS
        self._active_filter_types[0] = 'eeg'   # CH1 = EEG by Volition convention

        # CRITICAL: the line above only updates this class's own
        # bookkeeping list — it does NOT tell the ChannelProcessor
        # objects themselves what filter chain to run. Each
        # ChannelProcessor defaults to 'emg' internally until told
        # otherwise via set_filter(). Without this call, CH1 silently
        # ran EMG envelope detection instead of EEG filtering forever —
        # which is why the EEG bars never moved and no EEG-based intent
        # ever fired, even though everything else looked wired up.
        for ch, ftype in enumerate(self._active_filter_types):
            self.processors[ch].set_filter(ftype)

        self._build_ui()
        self._connect_signals()
        self._on_mode_changed(0)

        self._timer = QTimer()
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._update_ui)
        self._timer.start()

        self.log.log("Volition ready. Connect NPG Lite to begin.", C_ACCENT)

    # ── UI Construction ───────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(14)
        root.setContentsMargins(16, 16, 16, 16)

        # LEFT: Simplified controls
        left_container = QWidget()
        left_container.setFixedWidth(300)
        left = QVBoxLayout(left_container)
        left.setSpacing(10)
        left.setContentsMargins(0, 0, 0, 0)

        left_scroll = QScrollArea()
        left_scroll.setWidget(left_container)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(318)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}"
            f"QScrollArea > QWidget > QWidget {{ background: transparent; }}")

        title = QLabel("⬡ VOLITION")
        title.setStyleSheet(f"color: {C_ACCENT}; font-size: 24px; font-weight: bold; letter-spacing: 4px;")
        left.addWidget(title)
        sub = QLabel("ADAPTIVE BIOSIGNAL CONTROL")
        sub.setStyleSheet(f"color: {C_MUTED}; font-size: 10px; letter-spacing: 2px;")
        left.addWidget(sub)
        left.addSpacing(6)

        # Connection
        ble_group = QGroupBox("NPG LITE CONNECTION")
        ble_layout = QVBoxLayout(ble_group)
        self.btn_connect = QPushButton("CONNECT NPG LITE")
        self.btn_connect.setCheckable(True)
        self.btn_connect.setFixedHeight(44)
        ble_layout.addWidget(self.btn_connect)
        self.lbl_battery = QLabel("Battery: —")
        self.lbl_battery.setStyleSheet(f"color: {C_MUTED}; font-size: 11px;")
        ble_layout.addWidget(self.lbl_battery)
        left.addWidget(ble_group)

        # Channel configuration — CH1 must be EEG, CH2/CH3 EMG, per
        # Volition's standard wiring convention. Locked (disabled)
        # rather than removed entirely: showing the actual assignment
        # matters for debugging signal issues, even if it's not meant
        # to be changed casually during a demo.
        ch_group = QGroupBox("CHANNEL CONFIGURATION")
        ch_layout = QVBoxLayout(ch_group)
        ch_hint = QLabel("CH1=EEG, CH2/CH3=EMG — standard Volition wiring")
        ch_hint.setStyleSheet(f"color: {C_MUTED}; font-size: 9px;")
        ch_hint.setWordWrap(True)
        ch_layout.addWidget(ch_hint)
        self._ch_combos = []
        default_labels = ["EEG", "EMG", "EMG"]
        for i in range(min(3, MAX_CHANNELS)):
            row = QHBoxLayout()
            lbl = QLabel(f"CH {i+1}")
            lbl.setFixedWidth(40)
            lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
            cmb = QComboBox()
            cmb.addItems(["EMG", "EEG", "EOG", "ECG"])
            cmb.setCurrentText(default_labels[i])
            cmb.currentIndexChanged.connect(
                lambda idx, ch=i: self._on_filter_change(ch, idx))
            row.addWidget(lbl)
            row.addWidget(cmb)
            ch_layout.addLayout(row)
            self._ch_combos.append(cmb)
        left.addWidget(ch_group)

        # Mode selector
        mode_group = QGroupBox("EEG HEADBAND MODE")
        mode_layout = QVBoxLayout(mode_group)
        mode_hint = QLabel("Match this to your electrode position.")
        mode_hint.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        mode_hint.setWordWrap(True)
        mode_layout.addWidget(mode_hint)

        self._mode_btn_group = QButtonGroup(self)
        self._mode_btn_group.setExclusive(True)

        btn_pfc = QPushButton("PREFRONTAL  (Forehead)")
        btn_pfc.setCheckable(True)
        btn_pfc.setChecked(True)
        btn_pfc.setMinimumHeight(40)
        btn_pfc.setStyleSheet(
            f"QPushButton:checked {{ background: {C_ACCENT}; color: {C_BG}; "
            f"border-color: {C_ACCENT}; font-weight: bold; }}")

        btn_vc = QPushButton("VISUAL CORTEX  (Back of head)")
        btn_vc.setCheckable(True)
        btn_vc.setMinimumHeight(40)
        btn_vc.setStyleSheet(
            f"QPushButton:checked {{ background: #4fc3f7; color: {C_BG}; "
            f"border-color: #4fc3f7; font-weight: bold; }}")

        self._mode_btn_group.addButton(btn_pfc, 0)
        self._mode_btn_group.addButton(btn_vc, 1)
        self._mode_btn_group.idClicked.connect(self._on_mode_changed)

        mode_layout.addWidget(btn_pfc)
        mode_layout.addWidget(btn_vc)

        self.lbl_mode_intents = QLabel("Active: CHEEK TWITCH · JAW · FOCUS + EMG")
        self.lbl_mode_intents.setStyleSheet(f"color: {C_ACCENT}; font-size: 10px;")
        self.lbl_mode_intents.setWordWrap(True)
        mode_layout.addWidget(self.lbl_mode_intents)

        self._chk_pfc_blink = QCheckBox("Enable blink detection in PFC mode")
        self._chk_pfc_blink.setStyleSheet(f"color: {C_TEXT}; font-size: 10px;")
        self._chk_pfc_blink.stateChanged.connect(self._on_pfc_blink_toggled)
        mode_layout.addWidget(self._chk_pfc_blink)
        left.addWidget(mode_group)

        # Data capture — kept in full since live training is part of the demo
        cap_group = QGroupBox("DATA CAPTURE  (for TFLite training)")
        cap_layout = QVBoxLayout(cap_group)

        gesture_row = QHBoxLayout()
        gesture_lbl = QLabel("GESTURE")
        gesture_lbl.setFixedWidth(60)
        gesture_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.cmb_capture_gesture = QComboBox()
        self.cmb_capture_gesture.addItems([
            "STRONG_FLEX", "WEAK_FLEX",
            "EEG_CHEEK_TWITCH", "EEG_JAW_CLENCH",
            "EEG_FOCUS_HIGH", "REST"
        ])
        gesture_row.addWidget(gesture_lbl)
        gesture_row.addWidget(self.cmb_capture_gesture)
        cap_layout.addLayout(gesture_row)

        self._arm_row = QHBoxLayout()
        arm_lbl = QLabel("SIDE")
        arm_lbl.setFixedWidth(60)
        arm_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.cmb_capture_arm = QComboBox()
        self.cmb_capture_arm.addItems([
            "CH2  (Right)", "CH3  (Left)", "BOTH  (Both Sides)"])
        self._arm_row.addWidget(arm_lbl)
        self._arm_row.addWidget(self.cmb_capture_arm)
        cap_layout.addLayout(self._arm_row)

        self.cmb_capture_gesture.currentTextChanged.connect(self._on_gesture_type_changed)

        self.lbl_capture_preview = QLabel("Label: CH2_STRONG")
        self.lbl_capture_preview.setStyleSheet(f"color: {C_ACCENT}; font-size: 10px;")
        cap_layout.addWidget(self.lbl_capture_preview)
        self.cmb_capture_gesture.currentTextChanged.connect(self._update_capture_preview)
        self.cmb_capture_arm.currentTextChanged.connect(self._update_capture_preview)

        cap_btn_row = QHBoxLayout()
        self.btn_capture = QPushButton("START CAPTURE")
        self.btn_capture.setCheckable(True)
        self.btn_capture.clicked.connect(self._on_capture_toggle)
        self.lbl_capture_count = QLabel("0 samples")
        self.lbl_capture_count.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        cap_btn_row.addWidget(self.btn_capture)
        cap_btn_row.addWidget(self.lbl_capture_count)
        cap_layout.addLayout(cap_btn_row)
        left.addWidget(cap_group)

        # TFLite — train + load, the other half of the live demo story
        tflite_group = QGroupBox("TFLITE MODEL")
        tflite_layout = QVBoxLayout(tflite_group)
        self.lbl_tflite_status = QLabel("● No model loaded — threshold mode")
        self.lbl_tflite_status.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.lbl_tflite_status.setWordWrap(True)
        tflite_layout.addWidget(self.lbl_tflite_status)

        btn_train_row = QHBoxLayout()
        btn_train = QPushButton("⚙  TRAIN MODEL")
        self.btn_train_ref = btn_train
        btn_train.setToolTip(
            "Runs train_classifier.py for the current mode against\n"
            "collected data. This can take a minute — watch the log.")
        btn_train.clicked.connect(self._on_train_clicked)
        btn_reload_model = QPushButton("⟳  LOAD MODEL")
        btn_reload_model.clicked.connect(self._on_reload_tflite)
        btn_train_row.addWidget(btn_train)
        btn_train_row.addWidget(btn_reload_model)
        tflite_layout.addLayout(btn_train_row)

        hint_tflite = QLabel("Collect data for every gesture, then Train, then Load.")
        hint_tflite.setStyleSheet(f"color: {C_MUTED}; font-size: 9px;")
        hint_tflite.setWordWrap(True)
        tflite_layout.addWidget(hint_tflite)
        left.addWidget(tflite_group)

        cal_btn = QPushButton("↺  RECALIBRATE")
        cal_btn.clicked.connect(self._on_recalibrate)
        left.addWidget(cal_btn)

        hid_btn = QPushButton("⌨  CONFIGURE HID")
        hid_btn.setStyleSheet(
            f"QPushButton {{ border: 2px solid {C_ACCENT}; color: {C_ACCENT}; "
            f"font-size: 11px; font-weight: bold; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {C_ACCENT}; color: {C_BG}; }}")
        hid_btn.clicked.connect(self._open_hid_dialog)
        left.addWidget(hid_btn)
        if not self.hid.enabled:
            hid_btn.setToolTip("pynput not installed — run: pip install pynput")

        # Smart-device / spatial control.  The same Volition intent can now
        # operate a selected Kasa device, but only when the IMU has resolved
        # the user's head direction to that device's calibrated target.
        smart_group = QGroupBox("SMART DEVICE + SPATIAL CONTROL")
        smart_layout = QVBoxLayout(smart_group)
        smart_layout.setSpacing(7)

        self.btn_kasa_connect = QPushButton("CONNECT KASA")
        self.btn_kasa_connect.setFixedHeight(36)
        self.btn_kasa_connect.clicked.connect(self._on_kasa_connect)
        smart_layout.addWidget(self.btn_kasa_connect)

        self.lbl_kasa_status = QLabel("Kasa: not connected")
        self.lbl_kasa_status.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.lbl_kasa_status.setWordWrap(True)
        smart_layout.addWidget(self.lbl_kasa_status)

        kasa_target_row = QHBoxLayout()
        kasa_target_lbl = QLabel("TARGET")
        kasa_target_lbl.setFixedWidth(55)
        kasa_target_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.cmb_kasa_target = QComboBox()
        self.cmb_kasa_target.addItem("— no device —")
        self.cmb_kasa_target.setMinimumWidth(130)
        self.cmb_kasa_target.currentTextChanged.connect(self._on_kasa_target_changed)
        kasa_target_row.addWidget(kasa_target_lbl)
        kasa_target_row.addWidget(self.cmb_kasa_target)
        smart_layout.addLayout(kasa_target_row)

        intent_row = QHBoxLayout()
        intent_lbl = QLabel("GESTURE")
        intent_lbl.setFixedWidth(55)
        intent_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.cmb_spatial_intent = QComboBox()
        spatial_intent_candidates = [
            "EEG_CHEEK_TWITCH",
            "EEG_JAW_CLENCH",
            "EEG_BLINK",
            "CH2_STRONG",
            "CH3_STRONG",
        ]
        available_intents = [
            x for x in spatial_intent_candidates if x in ALL_POSSIBLE_INTENTS
        ]
        if not available_intents:
            available_intents = list(ALL_POSSIBLE_INTENTS)
        self.cmb_spatial_intent.addItems(available_intents)
        if "EEG_CHEEK_TWITCH" in available_intents:
            self.cmb_spatial_intent.setCurrentText("EEG_CHEEK_TWITCH")
        intent_row.addWidget(intent_lbl)
        intent_row.addWidget(self.cmb_spatial_intent)
        smart_layout.addLayout(intent_row)

        self.chk_spatial_mode = QCheckBox("ENABLE SPATIAL TARGETING")
        self.chk_spatial_mode.setStyleSheet(f"color: {C_TEXT}; font-size: 10px;")
        self.chk_spatial_mode.toggled.connect(self._on_spatial_toggled)
        smart_layout.addWidget(self.chk_spatial_mode)

        self.chk_room_tracking = QCheckBox("MOVEMENT-AWARE TARGETING")
        self.chk_room_tracking.setStyleSheet(f"color: {C_TEXT}; font-size: 10px;")
        self.chk_room_tracking.setToolTip(
            "Use inertial movement from the MPU6500 to update one selected Kasa target. "
            "Start with one initial direction; no per-position captures are required."
        )
        self.chk_room_tracking.toggled.connect(self._on_room_tracking_toggled)
        smart_layout.addWidget(self.chk_room_tracking)

        self.btn_calibrate_target = QPushButton("SET INITIAL DIRECTION")
        self.btn_calibrate_target.setEnabled(False)
        self.btn_calibrate_target.setToolTip(
            "Face the selected device and press once to establish P0 and the initial target bearing. "
            "Distance is not requested; movement refines it automatically."
        )
        self.btn_calibrate_target.clicked.connect(self._on_calibrate_spatial_target)
        smart_layout.addWidget(self.btn_calibrate_target)

        self.lbl_spatial_status = QLabel("Spatial: IMU not attached")
        self.lbl_spatial_status.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.lbl_spatial_status.setWordWrap(True)
        smart_layout.addWidget(self.lbl_spatial_status)

        left.addWidget(smart_group)

        left.addStretch()
        root.addWidget(left_scroll)

        # RIGHT: Big, clean signal display + log — this is what the
        # camera should mostly be pointed at
        right = QVBoxLayout()
        right.setSpacing(12)

        self.signal_panel = SignalPanel()
        right.addWidget(self.signal_panel)

        # Signal quality — compact, single row per channel
        qual_group = QGroupBox("SIGNAL QUALITY")
        qual_layout = QVBoxLayout(qual_group)
        self._qual_bars = {}
        self._health_labels = {}
        for sig, label, ch_idx in [("ch2_emg", "RIGHT ARM", 1), ("ch3_emg", "LEFT ARM", 2), ("eeg", "EEG", 0)]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(80)
            lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedHeight(8)
            bar.setTextVisible(False)
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {C_GREEN}; }}")
            health_lbl = QLabel("···")
            health_lbl.setFixedWidth(60)
            health_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 9px; font-weight: bold;")
            row.addWidget(lbl)
            row.addWidget(bar)
            row.addWidget(health_lbl)
            qual_layout.addLayout(row)
            self._qual_bars[sig] = bar
            self._health_labels[ch_idx] = health_lbl
        right.addWidget(qual_group)

        # Calibration + floor status — compact, informative
        status_group = QGroupBox("STATUS")
        status_layout = QVBoxLayout(status_group)
        self.lbl_cal_status = QLabel("● Collecting baseline data...")
        self.lbl_cal_status.setStyleSheet(f"color: {C_MUTED}; font-size: 11px;")
        self.lbl_cal_status.setWordWrap(True)
        status_layout.addWidget(self.lbl_cal_status)
        self.lbl_floor_status = QLabel("○ Learning resting floor...")
        self.lbl_floor_status.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.lbl_floor_status.setWordWrap(True)
        status_layout.addWidget(self.lbl_floor_status)
        right.addWidget(status_group)

        # Activity log
        log_group = QGroupBox("ACTIVITY")
        log_layout = QVBoxLayout(log_group)
        self.log = LogPanel()
        log_layout.addWidget(self.log)
        right.addWidget(log_group)

        root.addLayout(right, 3)

    # ── Signal wiring ─────────────────────────────────────────────────────

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self._on_connect_clicked)
        self.ble.scan_result.connect(self._on_scan_result)
        self.ble.device_connected.connect(self._on_connected)
        self.ble.device_disconnected.connect(self._on_disconnected)
        self.ble.data_received.connect(self._on_data)
        self.ble.battery_updated.connect(self._on_battery)
        self.ble.imu_received.connect(self._on_imu)
        self.ble.imu_available.connect(self._on_imu_available)
        self.ble.error.connect(self._on_error)

        # Kasa worker signals are connected when that worker is created.

    # ── BLE handlers ──────────────────────────────────────────────────────

    def _on_connect_clicked(self):
        if self.btn_connect.isChecked():
            self.btn_connect.setText("SCANNING...")
            self.btn_connect.setEnabled(False)
            self.ble.start_scan()
        else:
            self.ble.disconnect()

    def _on_scan_result(self, devices):
        self.btn_connect.setEnabled(True)
        if not devices:
            self.btn_connect.setChecked(False)
            self.btn_connect.setText("CONNECT NPG LITE")
            self.log.log("No NPG devices found. Is it powered on?", C_DANGER)
            return
        items = [str(d) for d in devices]
        chosen = 0
        if len(devices) > 1:
            item, ok = QInputDialog.getItem(self, "Select NPG Device", "Devices:", items, 0, False)
            if not ok:
                self.btn_connect.setChecked(False)
                self.btn_connect.setText("CONNECT NPG LITE")
                return
            chosen = items.index(item)
        self.btn_connect.setText("CONNECTING...")
        self.ble.connect_to(devices[chosen])

    def _on_connected(self, num_channels):
        self.is_connected = True
        self.num_channels = num_channels
        self.btn_connect.setText("DISCONNECT")
        self.btn_connect.setChecked(True)
        self.btn_connect.setEnabled(True)
        self.log.log(f"NPG Lite connected — {num_channels} channels @ 500Hz", C_GREEN)
        self.intent_engine.force_recalibrate()
        self.intent_engine.reset_floor_trackers()
        for ch in range(self.num_channels):
            self.processors[ch].set_notch('50')   # default 50Hz, no UI in demo build
        for m in self._health.values():
            m.reset()
        self._last_logged_health = {k: "CALIBRATING" for k in self._health}

    def _on_disconnected(self):
        self._imu_available = False
        self._imu_packet_count = 0
        self.spatial.reset()

        self.is_connected = False
        self.num_channels = 0
        self.btn_connect.setChecked(False)
        self.btn_connect.setText("CONNECT NPG LITE")
        self.btn_connect.setEnabled(True)
        self.log.log("NPG Lite disconnected.", C_MUTED)

    # ── IMU handlers ───────────────────────────────────────────────────────

    def _on_imu_available(self, available: bool):
        self._imu_available = bool(available)
        if available:
            self.log.log("IMU stream attached — spatial control available.", C_GREEN)
            if self.chk_spatial_mode.isChecked():
                self.lbl_spatial_status.setText("Spatial: ACTIVE")
                self.lbl_spatial_status.setStyleSheet(
                    f"color: {C_GREEN}; font-size: 10px;"
                )
        else:
            self.log.log("IMU stream unavailable — spatial targeting disabled.", C_MUTED)
            if self.chk_spatial_mode.isChecked():
                self.lbl_spatial_status.setText("Spatial: waiting for IMU stream...")
                self.lbl_spatial_status.setStyleSheet(
                    f"color: {C_MUTED}; font-size: 10px;"
                )

    def _on_imu(self, imu: dict):
        try:
            self.spatial.update(
                int(imu["timestamp_ms"]),
                int(imu["ax"]), int(imu["ay"]), int(imu["az"]),
                int(imu["gx"]), int(imu["gy"]), int(imu["gz"]),
            )
            self._imu_packet_count += 1
        except (KeyError, TypeError, ValueError):
            # A malformed optional IMU packet must never interrupt biosignal
            # processing.
            return

    def _on_error(self, msg):
        self.log.log(f"BLE error: {msg}", C_DANGER)
        if not self.is_connected:
            self.btn_connect.setChecked(False)
            self.btn_connect.setText("CONNECT NPG LITE")
            self.btn_connect.setEnabled(True)

    def _on_battery(self, pct):
        self.lbl_battery.setText(f"Battery: {pct}%")

    def _on_filter_change(self, ch: int, idx: int):
        ftype = FILTER_MAP.get(idx, 'emg')
        self._active_filter_types[ch] = ftype
        self.processors[ch].set_filter(ftype)
        self.log.log(f"CH{ch+1} → {ftype.upper()}", C_MUTED)

    # ── Data processing ───────────────────────────────────────────────────

    def _on_data(self, samples, num_channels):
        if not self.is_connected:
            return
        for sample in samples:
            for ch in range(min(num_channels, MAX_CHANNELS)):
                raw = sample['channels'][ch]
                self.processors[ch].process(raw)
                if ch in self._health:
                    self._health[ch].update(raw)

    def _update_ui(self):
        # IMU packets are drained on the Qt main thread just like the other
        # visual state.  The actual BLE notification callback only enqueues.
        if self.chk_spatial_mode.isChecked() and self._imu_available:
            target_alias, target_diff = self.spatial.target_for_current_heading()
            x_m, y_m = self.spatial.position
            if self.spatial.room_tracking:
                motion = (
                    f"ΔP=({x_m:+.1f},{y_m:+.1f})m  "
                    f"yaw={self.spatial.heading_deg:+.0f}°  "
                    f"steps={self.spatial.step_count}  "
                    f"speed={self.spatial.speed_mps:.1f}m/s  "
                    f"σ={self.spatial.position_uncertainty_m:.2f}m"
                )
                dbg = self.spatial.target_debug()
                if self.spatial.initial_target_heading_deg is None:
                    self.lbl_spatial_status.setText(
                        f"Target: SET INITIAL DIRECTION  ·  {motion}"
                    )
                    self.lbl_spatial_status.setStyleSheet(
                        f"color: {C_MUTED}; font-size: 10px;"
                    )
                elif target_alias is None:
                    self.lbl_spatial_status.setText(
                        f"Target: outside cone  ·  bearing {dbg['predicted_bearing_deg']:+.1f}°  ·  "
                        f"cone ±{dbg['cone_half_width_deg']:.0f}°  ·  {motion}"
                    )
                    self.lbl_spatial_status.setStyleSheet(
                        f"color: {C_MUTED}; font-size: 10px;"
                    )
                else:
                    range_text = (
                        f"R≈{dbg['range_estimate_m']:.1f}m"
                        if dbg['range_estimate_m'] is not None
                        else f"R≈{dbg['target_distance_m']:.1f}m*"
                    )
                    self.lbl_spatial_status.setText(
                        f"TARGET {target_alias}  ·  Δ {target_diff:.1f}°  ·  "
                        f"bearing {dbg['predicted_bearing_deg']:+.1f}°  ·  {range_text}  ·  {motion}"
                    )
                    self.lbl_spatial_status.setStyleSheet(
                        f"color: {C_GREEN}; font-size: 10px;"
                    )
            else:
                if target_alias is None:
                    if self.spatial.targets:
                        self.lbl_spatial_status.setText(
                            f"Spatial: no target in range  ·  heading {self.spatial.heading_deg:+.1f}°"
                        )
                    else:
                        self.lbl_spatial_status.setText(
                            f"Spatial: ACTIVE  ·  no calibrated targets  ·  heading {self.spatial.heading_deg:+.1f}°"
                        )
                    self.lbl_spatial_status.setStyleSheet(
                        f"color: {C_MUTED}; font-size: 10px;"
                    )
                else:
                    self.lbl_spatial_status.setText(
                        f"Spatial: TARGET {target_alias}  ·  Δ {target_diff:.1f}°"
                    )
                    self.lbl_spatial_status.setStyleSheet(
                        f"color: {C_GREEN}; font-size: 10px;"
                    )
        elif self.chk_spatial_mode.isChecked() and not self._imu_available:
            self.lbl_spatial_status.setText("Spatial: waiting for IMU stream...")
            self.lbl_spatial_status.setStyleSheet(
                f"color: {C_MUTED}; font-size: 10px;"
            )

        if not self.is_connected:
            return

        ch2_emg = ch3_emg = 0.0
        eeg_beta = eeg_blink = eeg_jaw = 0.0

        for ch in range(self.num_channels):
            p = self.processors[ch]
            ftype = self._active_filter_types[ch]
            if ftype == 'eeg':
                eeg_beta  = p.val_beta_pct
                eeg_blink = p.val_blink_envelope
                eeg_jaw   = p.val_jaw_envelope
            elif ftype == 'emg':
                val = p.val_emg_envelope
                if ch == 1:
                    ch2_emg = val
                elif ch == 2:
                    ch3_emg = val

        self.intent_engine.update_channel_health(
            ch2_healthy = self._health[1].is_healthy,
            ch3_healthy = self._health[2].is_healthy,
            eeg_healthy = self._health[0].is_healthy,
        )
        self.intent_engine.process_signals(
            ch2_emg=ch2_emg, ch3_emg=ch3_emg,
            eeg_beta=eeg_beta, eeg_blink=eeg_blink, eeg_jaw=eeg_jaw,
        )

        ie = self.intent_engine
        # Cheek twitch detection now reads the BLINK envelope chain
        # (val_blink_envelope), not jaw — restoring two genuinely
        # independent raw signals for cheek twitch vs jaw clench so
        # the two bars move independently instead of in lockstep.
        # This bar is relabelled CHEEK TWITCH in PFC mode but always
        # displays eeg_blink, matching what it actually detects from.
        self.signal_panel.update_signals(
            ch2_emg=ch2_emg, ch3_emg=ch3_emg,
            blink=eeg_blink, jaw=eeg_jaw, focus=eeg_beta,
        )

        f2 = ie._floor_ch2.floor if ie._floor_ch2.is_established else None
        f3 = ie._floor_ch3.floor if ie._floor_ch3.is_established else None
        fb = ie._floor_blink.floor if ie._floor_blink.is_established else None
        fj = ie._floor_jaw.floor if ie._floor_jaw.is_established else None

        self.signal_panel.update_markers("ch2_emg", floor=f2)
        self.signal_panel.update_markers("ch3_emg", floor=f3)
        # Cheek twitch now reads the blink envelope chain — this bar
        # always uses the blink floor regardless of mode, matching the
        # signal it actually displays (see update_signals above).
        self.signal_panel.update_markers("blink", floor=fb)
        self.signal_panel.update_markers("jaw", floor=fj)

        f2v, f3v, fbv, fjv = f2 or 0.0, f3 or 0.0, fb or 0.0, fj or 0.0

        self.signal_panel.update_markers("ch2_emg", thresholds=[
            (f2v + ie.th_ch2_light.threshold, "#ffdd88"),
            (f2v + ie.th_ch2_strong.threshold, "#ffffff"),
        ])
        self.signal_panel.update_markers("ch3_emg", thresholds=[
            (f3v + ie.th_ch3_light.threshold, "#ffdd88"),
            (f3v + ie.th_ch3_strong.threshold, "#ffffff"),
        ])
        if ie.mode == "pfc":
            # CHEEK TWITCH bar — threshold is now calibrated against
            # the blink floor, since detection reads eeg_blink
            self.signal_panel.update_markers("blink", thresholds=[
                (fbv + ie.th_cheek_twitch.threshold, "#ff6644"),
            ])
        else:
            self.signal_panel.update_markers("blink", thresholds=[
                (fbv + ie.th_blink.threshold, "#ffffff"),
                (fbv + ie.th_blink_upper.threshold, "#aaaaaa"),
            ])
        # JAW bar shows only its own jaw-clench thresholds now — cheek
        # twitch no longer shares this signal, so no cross-marker here
        jaw_thresholds = [
            (fjv + ie.th_jaw.threshold, "#ffffff"),
            (fjv + ie.th_jaw_upper.threshold, "#aaaaaa"),
        ]
        self.signal_panel.update_markers("jaw", thresholds=jaw_thresholds)
        self.signal_panel.update_markers("focus", thresholds=[
            (ie.th_eeg_focus.threshold, "#ffffff"),
        ])

        # Health labels
        _health_colours = {
            "OK": C_GREEN, "CALIBRATING": C_MUTED,
            "NO_SIGNAL": C_DANGER, "SATURATED": C_DANGER, "NOISY": "#ffaa00",
        }
        _health_text = {
            "OK": "OK", "CALIBRATING": "···", "NO_SIGNAL": "NO SIG",
            "SATURATED": "SAT", "NOISY": "NOISY",
        }
        for ch_idx, monitor in self._health.items():
            status = monitor.status
            lbl = self._health_labels.get(ch_idx)
            if lbl:
                lbl.setText(_health_text.get(status, status))
                lbl.setStyleSheet(
                    f"color: {_health_colours.get(status, C_MUTED)}; font-size: 9px; font-weight: bold;")
            if status != self._last_logged_health.get(ch_idx) and status != "CALIBRATING":
                self._last_logged_health[ch_idx] = status
                name = monitor.name
                if status == "OK":
                    self.log.log(f"{name} signal recovered — OK", C_GREEN)
                elif status == "NO_SIGNAL":
                    self.log.log(f"⚠ {name}: NO SIGNAL — check electrode contact", C_DANGER)
                elif status == "SATURATED":
                    self.log.log(f"⚠ {name}: SATURATED — check contact", C_DANGER)
                elif status == "NOISY":
                    self.log.log(f"⚠ {name}: NOISY — loose electrode", "#ffaa00")
            elif status == "CALIBRATING":
                self._last_logged_health[ch_idx] = status

        for sig, bar in self._qual_bars.items():
            bar.setValue(int(self.intent_engine.signal_quality.get(sig, 0) * 100))

        floors_ready = f2 is not None and f3 is not None and fb is not None and fj is not None
        if floors_ready:
            self.lbl_floor_status.setText(
                f"● Floor learned  ·  RIGHT={f2:.0f}  LEFT={f3:.0f}  "
                f"BLINK={fb:.0f}  JAW={fj:.0f}")
            self.lbl_floor_status.setStyleSheet(f"color: {C_GREEN}; font-size: 10px;")
        else:
            self.lbl_floor_status.setText("○ Learning resting floor...")
            self.lbl_floor_status.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")

        if ie._auto_calibrated:
            if ie.eeg_in_lockout:
                source = getattr(ie, "_eeg_lockout_source", None)
                if source == "model":
                    self.lbl_cal_status.setText("🤖 MODEL FLAGGED BAD EEG — settling...")
                else:
                    self.lbl_cal_status.setText("⚡ SATURATION LOCKOUT — settling...")
                self.lbl_cal_status.setStyleSheet(f"color: {C_DANGER}; font-size: 11px;")
            else:
                self.lbl_cal_status.setText("● Calibrated and ready")
                self.lbl_cal_status.setStyleSheet(f"color: {C_GREEN}; font-size: 11px;")
        else:
            remain = max(0, ie._calibration_window - ie._samples_since_start)
            self.lbl_cal_status.setText(f"● Calibrating... {remain} samples remaining")
            self.lbl_cal_status.setStyleSheet(f"color: {C_MUTED}; font-size: 11px;")

        if ie._capture_mode:
            self.lbl_capture_count.setText(f"{len(ie._capture_buffer)} samples")

    # ── Intent callback — fires HID actions, logs everything ──────────────

    def _on_intent(self, intent: str, intensity: float):
        # When the gyro-keyboard tab is active, its configured signal acts as
        # the keyboard "click" and is consumed by the keyboard rather than
        # firing the ordinary signal → HID mapping or spatial Kasa action.
        if self._hid_dialog is not None and self._hid_dialog.keyboard_active:
            if self._hid_dialog.keyboard.click_selected(intent):
                return

        # Existing computer/HID output remains unchanged.
        action = self._hid_mapping.get(intent, "NONE")
        if action and action != "NONE":
            self.hid.execute(action)
            self.log.log(
                f"INTENT  {intent}  →  HID:{action}   (intensity {intensity:.2f})",
                C_ACCENT)
        else:
            self.log.log(
                f"INTENT  {intent}   (intensity {intensity:.2f})", C_ACCENT)

        # Optional spatial device output. A gesture reaches the single selected
        # Kasa device only when the predicted bearing cone contains the head
        # direction and the IMU displacement uncertainty remains acceptable.
        if (
            self.chk_spatial_mode.isChecked()
            and intent == self.cmb_spatial_intent.currentText()
            and self._kasa_worker is not None
            and self._kasa_worker.isRunning()
        ):
            target_alias, target_diff = self.spatial.target_for_current_heading()
            if target_alias is not None:
                self._kasa_worker.enqueue("toggle", target_alias)
                self.log.log(
                    f"SPATIAL TARGET  {target_alias}  "
                    f"(Δ {target_diff:.1f}°)  ← {intent}",
                    C_ACCENT,
                )

    # ── Spatial / Kasa handlers ────────────────────────────────────────────
    def _on_kasa_connect(self):
        """Start the Kasa worker and discover devices on the local network."""
        if self._kasa_worker is not None and self._kasa_worker.isRunning():
            self._kasa_worker.enqueue("discover")
            self.lbl_kasa_status.setText("Kasa: searching local network...")
            return

        if _kasa is None:
            self._kasa_available = False
            self.lbl_kasa_status.setText("Kasa: python-kasa not installed")
            self.log.log(
                "Kasa unavailable — run: pip install python-kasa",
                C_DANGER,
            )
            return

        self._kasa_worker = KasaWorker(parent=self)
        self._kasa_worker.ready.connect(self._on_kasa_ready)
        self._kasa_worker.status.connect(self._on_kasa_status)
        self._kasa_worker.devices_found.connect(self._on_kasa_devices_found)
        self._kasa_worker.state_changed.connect(self._on_kasa_state_changed)

        self.btn_kasa_connect.setEnabled(False)
        self.btn_kasa_connect.setText("STARTING KASA...")
        self.lbl_kasa_status.setText("Kasa: starting controller...")
        self._kasa_worker.start()

    def _on_kasa_ready(self, ready: bool):
        if ready:
            self._kasa_available = True
            self.btn_kasa_connect.setEnabled(True)
            self.btn_kasa_connect.setText("REFRESH KASA DEVICES")
            self.lbl_kasa_status.setText("Kasa: controller ready — searching...")
            self._kasa_worker.enqueue("discover")
        else:
            self._kasa_available = False
            self.btn_kasa_connect.setEnabled(True)
            self.btn_kasa_connect.setText("CONNECT KASA")

    def _on_kasa_status(self, msg: str):
        self.lbl_kasa_status.setText(str(msg))
        self.log.log(str(msg), C_MUTED)

    def _on_kasa_devices_found(self, aliases):
        self._kasa_devices = list(aliases or [])

        self.cmb_kasa_target.blockSignals(True)
        self.cmb_kasa_target.clear()
        if self._kasa_devices:
            self.cmb_kasa_target.addItems(self._kasa_devices)
            self.cmb_kasa_target.setCurrentIndex(0)
        else:
            self.cmb_kasa_target.addItem("— no device —")
        self.cmb_kasa_target.blockSignals(False)

        self._on_kasa_target_changed(self.cmb_kasa_target.currentText())

    def _on_kasa_state_changed(self, alias: str, is_on: bool):
        state = "ON" if is_on else "OFF"
        self.lbl_kasa_status.setText(f"Kasa: {alias} → {state}")

    def _on_kasa_target_changed(self, alias: str):
        valid = bool(alias and alias != "— no device —")
        self.btn_calibrate_target.setEnabled(
            valid and self._imu_available and self._kasa_worker is not None
            and self._kasa_worker.isRunning()
        )

        if valid:
            self.lbl_kasa_status.setText(f"Kasa target: {alias}")
        elif self._kasa_available:
            self.lbl_kasa_status.setText("Kasa: no device selected")
        else:
            self.lbl_kasa_status.setText("Kasa: not connected")

    def _on_spatial_toggled(self, checked: bool):
        checked = bool(checked)

        if not checked:
            self.btn_calibrate_target.setEnabled(False)
            self.lbl_spatial_status.setText("Spatial: OFF")
            self.lbl_spatial_status.setStyleSheet(
                f"color: {C_MUTED}; font-size: 10px;"
            )
            return

        self.btn_calibrate_target.setEnabled(
            self._imu_available
            and self.cmb_kasa_target.currentText() != "— no device —"
            and self._kasa_worker is not None
            and self._kasa_worker.isRunning()
        )

        if not self._imu_available:
            self.lbl_spatial_status.setText("Spatial: waiting for IMU stream...")
            self.lbl_spatial_status.setStyleSheet(
                f"color: {C_MUTED}; font-size: 10px;"
            )
        elif self.cmb_kasa_target.currentText() == "— no device —":
            self.lbl_spatial_status.setText("Spatial: active — select a Kasa target")
            self.lbl_spatial_status.setStyleSheet(
                f"color: {C_MUTED}; font-size: 10px;"
            )
        else:
            alias = self.cmb_kasa_target.currentText()
            if self.chk_room_tracking.isChecked():
                self.lbl_spatial_status.setText(
                    f"Target tracking: ACTIVE — {alias} · set initial direction once"
                )
            else:
                self.lbl_spatial_status.setText(
                    f"Spatial: ACTIVE — face {alias} and set initial direction"
                )
            self.lbl_spatial_status.setStyleSheet(
                f"color: {C_GREEN}; font-size: 10px;"
            )

    def _on_room_tracking_toggled(self, checked: bool):
        checked = bool(checked)
        self.spatial.set_room_tracking(checked, clear_map=True)
        if checked:
            self.btn_calibrate_target.setText("SET INITIAL DIRECTION")
            self.log.log(
                "Movement-aware targeting enabled — set the initial target direction once, then move normally.",
                C_ACCENT,
            )
            if hasattr(self, "lbl_spatial_status"):
                self.lbl_spatial_status.setText(
                    "Target: face the selected device and press SET INITIAL DIRECTION. Then move normally."
                )
        else:
            self.btn_calibrate_target.setText("SET INITIAL DIRECTION")
            self.log.log(
                "Movement-aware targeting disabled — using relative direction mode.",
                C_MUTED,
            )

    def _on_calibrate_spatial_target(self):
        alias = self.cmb_kasa_target.currentText()
        if (
            not alias
            or alias == "— no device —"
            or not self._imu_available
        ):
            self.log.log(
                "Cannot calibrate target — select a device and attach the IMU.",
                C_DANGER,
            )
            return

        solved, message = self.spatial.calibrate_target(alias)
        if self.spatial.room_tracking:
            self.btn_calibrate_target.setText("RESET / SET DIRECTION")
            self.lbl_spatial_status.setText(f"Target: {message}")
            self.lbl_spatial_status.setStyleSheet(
                f"color: {C_GREEN if solved else C_MUTED}; font-size: 10px;"
            )
            self.log.log(
                f"TARGET DIRECTION  {alias}  ·  {message}",
                C_ACCENT if solved else C_MUTED,
            )
        else:
            heading = self.spatial.heading_deg
            self.lbl_spatial_status.setText(
                f"Spatial: {message}"
            )
            self.lbl_spatial_status.setStyleSheet(
                f"color: {C_GREEN}; font-size: 10px;"
            )
            self.log.log(
                f"SPATIAL CALIBRATION  {alias}  @ {heading:+.1f}°",
                C_ACCENT,
            )

    def _open_hid_dialog(self):
        if not self.hid.enabled:
            self.log.log(
                "HID unavailable — pynput not installed. Run: pip install pynput",
                C_DANGER)
            return
        self._hid_dialog = HIDMappingDialog(
            self._hid_mapping,
            spatial=self.spatial,
            hid_controller=self.hid,
            log_callback=lambda msg, colour: self.log.log(msg, colour),
            parent=self,
        )
        try:
            self._hid_dialog.exec()
        finally:
            self._hid_dialog = None

    # ── Data capture ──────────────────────────────────────────────────────

    def _on_gesture_type_changed(self, gesture: str):
        emg_gestures = {"STRONG_FLEX", "WEAK_FLEX"}
        is_emg = gesture in emg_gestures
        for i in range(self._arm_row.count()):
            item = self._arm_row.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(is_emg)
        self._update_capture_preview()

    def _update_capture_preview(self):
        self.lbl_capture_preview.setText(f"Label: {self._build_capture_label()}")

    def _build_capture_label(self) -> str:
        gesture = self.cmb_capture_gesture.currentText()
        emg_gestures = {"STRONG_FLEX", "WEAK_FLEX"}
        if gesture in emg_gestures:
            arm_text = self.cmb_capture_arm.currentText()
            suffix = "STRONG" if "STRONG" in gesture else "LIGHT"
            if "BOTH" in arm_text:
                return f"BOTH_{suffix}"
            elif "CH3" in arm_text:
                return f"CH3_{suffix}"
            else:
                return f"CH2_{suffix}"
        return gesture

    def _on_capture_toggle(self):
        if self.btn_capture.isChecked():
            label = self._build_capture_label()
            self.intent_engine.start_capture(label)
            self.btn_capture.setText("STOP CAPTURE")
            self.log.log(f"Capturing '{label}'...", C_ACCENT)
        else:
            count = self.intent_engine.stop_capture()
            rejected = self.intent_engine._capture_rejected_count
            self.btn_capture.setText("START CAPTURE")
            if rejected > 0:
                self.log.log(
                    f"Captured {count} clean samples "
                    f"({rejected} rejected — poor signal health)",
                    "#ffaa00")
            else:
                self.log.log(f"Captured {count} samples", C_GREEN)

    # ── Mode ──────────────────────────────────────────────────────────────

    def _on_pfc_blink_toggled(self, state: int):
        enabled = state == Qt.Checked
        self.intent_engine.pfc_blink_enabled = enabled
        self.intent_engine.force_recalibrate()
        self._refresh_mode_label()
        self.log.log(f"PFC blink detection {'enabled' if enabled else 'disabled'}", C_ACCENT)
        self._on_mode_changed(0)

    def _on_mode_changed(self, btn_id: int):
        mode = "pfc" if btn_id == 0 else "vc"
        self.intent_engine.set_mode(mode)
        self._chk_pfc_blink.setVisible(mode == "pfc")
        self.signal_panel.set_jaw_row_mode(mode == "pfc")

        self.cmb_capture_gesture.blockSignals(True)
        self.cmb_capture_gesture.clear()
        labels = self.intent_engine.capture_labels
        gesture_bases = []
        if "CH2_STRONG" in labels or "CH3_STRONG" in labels:
            gesture_bases.append("STRONG_FLEX")
        if "CH2_LIGHT" in labels or "CH3_LIGHT" in labels:
            gesture_bases.append("WEAK_FLEX")
        eeg_labels = [l for l in labels
                      if l not in ("REST",) and
                      not any(x in l for x in ("CH2", "CH3", "BOTH", "FLEX"))]
        self.cmb_capture_gesture.addItems(gesture_bases + eeg_labels + ["REST"])
        self.cmb_capture_gesture.blockSignals(False)
        self._update_capture_preview()

        self._refresh_mode_label()
        self._on_reload_tflite()

        mode_name = "PREFRONTAL" if mode == "pfc" else "VISUAL CORTEX"
        self.log.log(f"Mode → {mode_name}", C_ACCENT)

    def _refresh_mode_label(self):
        active = self.intent_engine.active_intents
        eeg_only = [i for i in active if i.startswith("EEG")]
        self.lbl_mode_intents.setText(
            f"Active EEG: {' · '.join(i.replace('EEG_', '') for i in eeg_only)}")

    # ── TFLite ────────────────────────────────────────────────────────────

    def _on_recalibrate(self):
        self.intent_engine.force_recalibrate()
        self.log.log("Recalibration started. Hold still for 2 seconds...", C_ACCENT)

    def _on_reload_tflite(self):
        self.intent_engine.reload_tflite()
        if self.intent_engine.tflite_active:
            self.lbl_tflite_status.setText("● TFLite model active")
            self.lbl_tflite_status.setStyleSheet(f"color: {C_GREEN}; font-size: 10px;")
            self.log.log("TFLite model loaded — classifier active.", C_GREEN)
        else:
            self.lbl_tflite_status.setText("● No model found — threshold mode")
            self.lbl_tflite_status.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
            self.log.log("No TFLite model found. Collect data and train.", C_MUTED)

    def _on_train_clicked(self):
        """
        Runs training in-process on a background thread and streams
        progress into the activity log.

        IMPORTANT: this deliberately does NOT use subprocess +
        sys.executable. That works fine when running from source, but
        inside a PyInstaller-frozen .exe, sys.executable points at the
        exe itself (not a Python interpreter) — a subprocess call would
        just try to relaunch the whole GUI app instead of running
        training. Importing train_classifier directly and calling it
        in-process works identically in both cases.
        """
        mode = self.intent_engine.mode
        self.log.log(f"Training {mode.upper()} model — this may take a minute...", C_ACCENT)
        self.btn_train_ref.setEnabled(False)

        self._train_thread = _TrainThread(mode)
        self._train_thread.line_ready.connect(lambda s: self.log.log(s, C_MUTED))
        self._train_thread.finished_ok.connect(self._on_train_finished)
        self._train_thread.finished_err.connect(self._on_train_error)
        self._train_thread.start()

    def _on_train_finished(self, mode: str):
        self.btn_train_ref.setEnabled(True)
        self.log.log(f"Training complete for {mode.upper()}.", C_GREEN)
        self._on_reload_tflite()

    def _on_train_error(self, msg: str):
        self.btn_train_ref.setEnabled(True)
        self.log.log(f"Training failed: {msg}", C_DANGER)



    def closeEvent(self, event):
        # Stop Kasa worker if it was started.
        if self._kasa_worker is not None:
            try:
                self._kasa_worker.stop_worker()
                self._kasa_worker.wait(1500)
            except Exception:
                pass

        # Shut down the existing BLEManager cleanly as well.
        try:
            self.ble.shutdown()
        except Exception:
            pass

        event.accept()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Volition")
    window = VolitionDemoApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    import traceback
    import datetime

    try:
        main()
    except Exception:
        crash_log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "volition_demo_crash_log.txt")
        try:
            with open(crash_log_path, "a") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Crash at {datetime.datetime.now().isoformat()}\n")
                f.write(f"{'='*60}\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise