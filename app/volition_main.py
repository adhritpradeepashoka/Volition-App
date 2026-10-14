# Volition — Copyright (c) 2026 Adhrit Pradeep. Licensed under GPL-3.0 (see LICENSE).
# Built on NPG-Lite-SNES by Upside Down Labs (GPL-3.0).
"""
Volition - Adaptive Multimodal Biosignal Control System
========================================================
Built on top of NPG-Lite-SNES by Upside Down Labs (GPL-3.0)
Original: https://github.com/upsidedownlabs/NPG-Lite-SNES

Modifications by [Your Name] for Vivo Ignite 4th Edition:
- Replaced Xbox gamepad output with 3-axis robotic arm control
- Added IntentEngine for adaptive threshold learning
- Added data capture mode for TFLite training
- Added arm visualiser panel in UI
- Removed ViGEmBus dependency

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import sys
import os

# ── Redirect stdout/stderr BEFORE any other import ───────────────────────────
# When launched via pythonw.exe (no console window), sys.stdout and
# sys.stderr are None. The moment any code calls print() or logs a
# warning, some Python/Qt configurations silently allocate a brand-new
# console window just to have somewhere to write to — which is exactly
# what was happening here, since intent_engine.py, tflite_classifier.py,
# and TensorFlow itself all print startup/status messages.
#
# The fix: redirect stdout/stderr to a log file immediately, before any
# other module (including tensorflow) gets imported and has a chance to
# print anything. This must happen here, at the very top, before the
# rest of the imports below.
if sys.stdout is None or sys.stderr is None:
    _log_dir = os.path.dirname(os.path.abspath(__file__))
    _log_path = os.path.join(_log_dir, "volition_log.txt")
    _log_file = open(_log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = _log_file
    sys.stderr = _log_file
    import datetime
    print(f"\n{'='*60}")
    print(f"Volition started (silent/pythonw mode) — {datetime.datetime.now().isoformat()}")
    print(f"{'='*60}")

import asyncio
import threading

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QGroupBox, QProgressBar,
    QTextEdit, QInputDialog, QMessageBox, QFrame, QSplitter,
    QStatusBar, QSlider, QCheckBox, QTableWidget, QTableWidgetItem,
    QDialog, QScrollArea, QHeaderView, QRadioButton, QButtonGroup,
    QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, Slot
from PySide6.QtGui import QFont, QColor, QPalette, QPainter, QPen, QPainterPath

# --- Volition modules ---
from intent_engine import IntentEngine
from arm.arm_controller import ArmController

# --- NPG-Lite-SNES modules (unchanged from original) ---
sys.path.insert(0, os.path.dirname(__file__))
from channel_processor import ChannelProcessor
from ble_manager import BLEManager
from config import MAX_CHANNELS, FILTER_MAP, EMG_SCALE, BLINK_SCALE, EYE_SCALE, JAW_SCALE, ECG_SCALE, clamp100

# ── Colours ───────────────────────────────────────────────────────────────────
C_BG       = "#0a0a0a"
C_PANEL    = "#111111"
C_BORDER   = "#2a2a2a"
C_ACCENT   = "#f5a623"   # Volition amber
C_GREEN    = "#00ff66"
C_TEXT     = "#ffffff"
C_MUTED    = "#9a9a9a"   # raised from #666666 — was too low-contrast to read
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
    border-radius: 4px; color: {C_TEXT}; padding: 6px 14px;
    font-size: 11px; font-weight: bold; letter-spacing: 1px;
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
    border-radius: 4px; padding: 4px 8px; color: {C_TEXT};
}}
QLabel {{ color: {C_TEXT}; }}
QTextEdit {{
    background: {C_PANEL}; border: 1px solid {C_BORDER};
    border-radius: 4px; color: {C_GREEN}; font-size: 10px;
}}
QSlider::groove:horizontal {{ background: {C_BORDER}; height: 4px; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {C_ACCENT}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
"""

# MAX_CHANNELS, FILTER_MAP, EMG_SCALE, BLINK_SCALE, EYE_SCALE, JAW_SCALE,
# ECG_SCALE and clamp100 are now imported directly from UDL's config.py above,
# so Volition always matches the official app's calibration.


# ── Arm Visualiser ────────────────────────────────────────────────────────────

class ArmVisualiser(QWidget):
    """Simple visual display of arm joint positions."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(200)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        title = QLabel("3-AXIS ARM  (ROTATION)")
        title.setStyleSheet(f"color: {C_ACCENT}; font-size: 11px; font-weight: bold; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._bars = {}
        for name, label in [("a1", "AXIS 1"), ("a2", "AXIS 2"), ("a3", "AXIS 3")]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(70)
            lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
            bar = QProgressBar()
            bar.setRange(0, 180)
            bar.setValue(90)
            bar.setTextVisible(True)
            bar.setFormat("%v°")
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {C_ACCENT}; }}")
            row.addWidget(lbl)
            row.addWidget(bar)
            layout.addLayout(row)
            self._bars[name] = bar

        # Grip status
        grip_row = QHBoxLayout()
        grip_lbl = QLabel("GRIP")
        grip_lbl.setFixedWidth(70)
        grip_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self._grip_indicator = QLabel("● OPEN")
        self._grip_indicator.setStyleSheet(f"color: {C_GREEN}; font-size: 11px; font-weight: bold;")
        grip_row.addWidget(grip_lbl)
        grip_row.addWidget(self._grip_indicator)
        layout.addLayout(grip_row)

        # Last intent
        intent_row = QHBoxLayout()
        intent_lbl = QLabel("INTENT")
        intent_lbl.setFixedWidth(70)
        intent_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self._intent_label = QLabel("—")
        self._intent_label.setStyleSheet(f"color: {C_ACCENT}; font-size: 11px; font-weight: bold;")
        intent_row.addWidget(intent_lbl)
        intent_row.addWidget(self._intent_label)
        layout.addLayout(intent_row)

        layout.addStretch()

    def update_position(self, a1: int, a2: int, a3: int, grip_open: bool):
        self._bars["a1"].setValue(a1)
        self._bars["a2"].setValue(a2)
        self._bars["a3"].setValue(a3)
        if grip_open:
            self._grip_indicator.setText("● OPEN")
            self._grip_indicator.setStyleSheet(f"color: {C_GREEN}; font-size: 11px; font-weight: bold;")
        else:
            self._grip_indicator.setText("● CLOSED")
            self._grip_indicator.setStyleSheet(f"color: {C_DANGER}; font-size: 11px; font-weight: bold;")

    def update_intent(self, intent: str):
        self._intent_label.setText(intent.replace("_", " "))


# ── Signal Bar with overlay markers ────────────────────────────────────────────

class SignalBar(QWidget):
    """
    A signal strength bar that shows the RAW value (not floor-corrected)
    so the floor and threshold markers land somewhere meaningful — on a
    floor-corrected scale the floor line would trivially always sit at
    zero, which tells you nothing. Showing raw value + floor line +
    threshold line together lets you watch the live signal, see exactly
    where the learned resting floor sits, and see exactly where it needs
    to cross to fire — all on one scale.

    Markers:
      floor      — thin grey line  — the passively learned resting floor
      thresholds — list of (value, colour) — one or more trigger lines
                   (e.g. light + strong for EMG, single for blink/jaw/focus)
    """

    def __init__(self, colour: str, max_scale: float = 1000.0):
        super().__init__()
        self._value      = 0.0
        self._floor      = None
        self._thresholds = []   # list of (value, colour)
        self._max_scale  = max(max_scale, 1.0)
        self._colour     = colour
        self.setFixedHeight(14)
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
        """thresholds: list of (value, colour) tuples, or empty list."""
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

        # Rounded track background, clipped so the fill can't spill
        # past the rounded corners
        track_path = QPainterPath()
        track_path.addRoundedRect(0.5, 0.5, w - 1, h - 1, radius, radius)
        painter.setClipPath(track_path)
        painter.fillRect(0, 0, w, h, QColor("#1a1a1a"))

        # Value fill
        fill_w = self._x_for(self._value)
        if fill_w > 0:
            painter.fillRect(0, 0, fill_w, h, QColor(self._colour))

        painter.setClipping(False)

        # Border outline
        pen = QPen(QColor(C_BORDER))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRoundedRect(0.5, 0.5, w - 1, h - 1, radius, radius)

        # Floor marker — soft grey, slightly inset from top/bottom so it
        # reads as an overlay notch rather than a line slicing the bar
        if self._floor is not None:
            fx = self._x_for(self._floor)
            pen = QPen(QColor(255, 255, 255, 110))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(fx, 2, fx, h - 2)

        # Threshold marker(s) — solid, slightly brighter, full height
        for th_value, th_colour in self._thresholds:
            tx = self._x_for(th_value)
            pen = QPen(QColor(th_colour))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(tx, 1, tx, h - 1)

        painter.end()


class SignalPanel(QGroupBox):
    """Live signal strength bars per channel, with floor + threshold overlays."""

    def __init__(self):
        super().__init__("BIOSIGNAL MONITOR")
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self._bars = {}
        self._bar_labels = {}
        self._bar_rows   = {}
        signals = [
            ("ch2_emg",  "CH2 RIGHT",  C_ACCENT,   1000.0),
            ("ch3_emg",  "CH3 LEFT",   "#ff9944",  1000.0),
            ("blink",    "BLINK",      "#4fc3f7",  300.0),
            ("jaw",      "JAW CLENCH", "#ce93d8",  500.0),
            ("focus",    "FOCUS",      "#a5d6a7",  100.0),
        ]
        for key, label, colour, scale in signals:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(75)
            lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
            bar = SignalBar(colour, max_scale=scale)
            row.addWidget(lbl)
            row.addWidget(bar)
            layout.addLayout(row)
            self._bars[key] = bar
            self._bar_labels[key] = lbl
            self._bar_rows[key] = row

        legend = QLabel("│ grey = resting floor    │ bright = fire threshold")
        legend.setStyleSheet(f"color: {C_MUTED}; font-size: 8px;")
        layout.addWidget(legend)

    def set_jaw_row_mode(self, pfc: bool):
        """
        Both BLINK and JAW CLENCH bars are always visible, always
        showing their own dedicated signal — no hiding or repurposing.
        In PFC, the CHEEK TWITCH bar (previously the "blink" slot when
        relabelled) has been retired in favour of showing cheek twitch
        markers directly on the JAW CLENCH bar, since both come from the
        same eeg_jaw envelope anyway.
        """
        blink_lbl = self._bar_labels.get("blink")
        jaw_lbl   = self._bar_labels.get("jaw")
        jaw_row   = self._bar_rows.get("jaw")

        if blink_lbl:
            blink_lbl.setText("BLINK")
        if jaw_lbl:
            jaw_lbl.setText("JAW CLENCH")

        # Always visible in both modes now
        if jaw_row:
            for i in range(jaw_row.count()):
                w = jaw_row.itemAt(i).widget()
                if w:
                    w.setVisible(True)

    def update_signals(self, **kwargs):
        """Set raw values (NOT floor-corrected — see SignalBar docstring)."""
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
        self.setMaximumHeight(120)

    def log(self, msg: str, colour: str = C_GREEN):
        import time
        ts = time.strftime("%H:%M:%S")
        self.append(f'<span style="color:{C_MUTED}">[{ts}]</span> <span style="color:{colour}">{msg}</span>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ── Mapping dialog ────────────────────────────────────────────────────────────

class MappingDialog(QDialog):
    """
    Full-screen scrollable control mapping table.
    Each row: coloured signal label | arm action dropdown | HID key dropdown
    Opens from the main window's CONFIGURE MAPPING button.
    Changes take effect immediately — no save needed.
    """

    def __init__(self, intent_engine, arm_actions, hid_actions,
                 mapping_combos, hid_mapping_combos, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Volition — Control Mapping")
        self.setMinimumSize(820, 600)
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
        """)

        self._mapping_combos     = mapping_combos
        self._hid_mapping_combos = hid_mapping_combos
        self._arm_actions        = arm_actions
        self._hid_actions        = hid_actions
        self._intent_engine      = intent_engine

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QLabel("CONTROL MAPPING  —  changes apply instantly")
        hdr.setStyleSheet(f"color: {C_ACCENT}; font-size: 13px; "
                          f"font-weight: bold; letter-spacing: 2px;")
        layout.addWidget(hdr)

        hint = QLabel(
            "Amber = right arm  |  Orange = left arm  |  "
            "Yellow = both arms  |  Blue = EEG\n"
            "Set ARM ACTION to NONE to disable. Set HID KEY to NONE for no keyboard output.")
        hint.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        layout.addWidget(hint)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["SIGNAL", "ARM ACTION", "HID KEY"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            f"QTableWidget::item:alternate {{ background: #141414; }}")

        _colours = {
            "CH2":  C_ACCENT,
            "CH3":  "#ff9944",
            "BOTH": "#ffdd44",
            "EEG":  "#4fc3f7",
        }

        all_intents = intent_engine.active_intents
        self._table.setRowCount(len(all_intents))
        self._row_combos = {}   # intent → (arm_cmb, hid_cmb) in table

        for row, intent in enumerate(all_intents):
            prefix = next((k for k in _colours if intent.startswith(k)), "EEG")
            colour = _colours[prefix]

            # Signal label cell
            lbl_item = QTableWidgetItem(intent.replace("_", " "))
            lbl_item.setForeground(QColor(colour))
            font = QFont("Consolas", 10)
            font.setBold(True)
            lbl_item.setFont(font)
            self._table.setItem(row, 0, lbl_item)

            # Arm action dropdown — reuse existing combo values
            arm_cmb = QComboBox()
            arm_cmb.addItems(arm_actions)
            # Sync with existing mapping
            existing_arm = mapping_combos.get(intent)
            if existing_arm:
                arm_cmb.setCurrentText(existing_arm.currentText())
            arm_cmb.currentTextChanged.connect(
                lambda txt, i=intent: self._on_arm_changed(i, txt))
            self._table.setCellWidget(row, 1, arm_cmb)

            # HID dropdown — reuse existing combo values
            hid_cmb = QComboBox()
            hid_cmb.addItems(hid_actions)
            existing_hid = hid_mapping_combos.get(intent)
            if existing_hid:
                hid_cmb.setCurrentText(existing_hid.currentText())
            hid_cmb.currentTextChanged.connect(
                lambda txt, i=intent: self._on_hid_changed(i, txt))
            self._table.setCellWidget(row, 2, hid_cmb)

            self._row_combos[intent] = (arm_cmb, hid_cmb)

        self._table.setRowHeight(0, 36)
        for r in range(len(all_intents)):
            self._table.setRowHeight(r, 36)

        layout.addWidget(self._table)

        # Buttons
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("RESET TO DEFAULTS")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_close = QPushButton("CLOSE")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _on_arm_changed(self, intent: str, action: str):
        """Push change back to main window's mapping combos."""
        cmb = self._mapping_combos.get(intent)
        if cmb:
            cmb.setCurrentText(action)

    def _on_hid_changed(self, intent: str, action: str):
        cmb = self._hid_mapping_combos.get(intent)
        if cmb:
            cmb.setCurrentText(action)

    def refresh_intents(self, new_intents: list[str]):
        """Called when mode switches — rebuilds the table rows."""
        # Update row visibility based on which intents are now active
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item:
                intent = item.text().replace(" ", "_")
                visible = intent in new_intents
                self._table.setRowHidden(row, not visible)

    def _reset_defaults(self):
        from arm.arm_controller import ArmController as _AC
        defaults = {
            "CH2_STRONG":       "GRIP_TOGGLE",
            "CH2_LIGHT":        "AXIS1_CW",
            "CH3_STRONG":       "GRIP_TOGGLE",
            "CH3_LIGHT":        "AXIS1_CCW",
            "BOTH_STRONG":      "RESET",
            "BOTH_LIGHT":       "AXIS2_CW",
            "EEG_BLINK":        "AXIS3_CW",
            "EEG_DOUBLE_BLINK": "AXIS3_CCW",
            "EEG_TRIPLE_BLINK": "AXIS2_CCW",
            "EEG_JAW_CLENCH":   "GRIP_TOGGLE",
            "EEG_CHEEK_TWITCH": "GRIP_TOGGLE",
            "EEG_FOCUS_HIGH":   "AXIS2_CW",
        }
        for intent, (arm_cmb, hid_cmb) in self._row_combos.items():
            d = defaults.get(intent, "NONE")
            arm_cmb.setCurrentText(d)
            hid_cmb.setCurrentText("NONE")


# ── Main window ───────────────────────────────────────────────────────────────

class VolitionApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VOLITION  ·  Adaptive Biosignal Control System")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(STYLE)

        # Core objects
        self.ble = BLEManager()
        self.processors = [ChannelProcessor() for _ in range(MAX_CHANNELS)]
        self.intent_engine = IntentEngine()
        self.arm = ArmController()

        # Signal health monitors — watch raw ADC per channel to catch
        # disconnected electrodes, saturation, and noise before the
        # classifier mistakes them for real gestures
        from signal_health import SignalHealthMonitor
        self._health = {
            0: SignalHealthMonitor("EEG"),
            1: SignalHealthMonitor("CH2"),
            2: SignalHealthMonitor("CH3"),
        }
        self._last_logged_health = {0: "CALIBRATING", 1: "CALIBRATING", 2: "CALIBRATING"}
        self.intent_engine.on_intent = self._on_intent

        # HID controller
        from hid_controller import HIDController
        self.hid = HIDController()
        self.hid.on_status = lambda msg: self.log.log(msg, C_MUTED)

        self.num_channels = 0
        self.is_connected = False
        self._active_filter_types = ['emg'] * MAX_CHANNELS

        # Wire callbacks
        self.arm.on_position_changed = self._on_arm_position
        self.arm.on_status_changed   = self._on_arm_status
        self.intent_engine.on_intent = self._on_intent

        self._build_ui()
        self._connect_signals()

        # Sync mode-dependent UI (labels, visibility, capture list) to
        # match the default PFC mode — idClicked never fires on its own
        # just because a button starts checked, so without this call the
        # JAW bar/sliders would show generic labels until the user
        # clicked a mode button once.
        self._on_mode_changed(0)

        # 30Hz update timer
        self._timer = QTimer()
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._update_ui)
        self._timer.start()

        # Connect arm in simulated mode immediately
        self.arm.connect_simulated()
        self.log.log("Volition ready. Connect NPG Lite to begin.", C_ACCENT)
        self.log.log("Arm running in SIMULATED mode. Connect serial port for hardware.", C_MUTED)

    # ── UI Construction ───────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # LEFT: Scrollable controls panel
        left_container = QWidget()
        left_container.setFixedWidth(300)
        left = QVBoxLayout(left_container)
        left.setSpacing(8)
        left.setContentsMargins(0, 0, 0, 0)

        left_scroll = QScrollArea()
        left_scroll.setWidget(left_container)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(318)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}"
            f"QScrollArea > QWidget > QWidget {{ background: transparent; }}")

        # Title
        title = QLabel("⬡ VOLITION")
        title.setStyleSheet(f"color: {C_ACCENT}; font-size: 22px; font-weight: bold; letter-spacing: 4px;")
        left.addWidget(title)
        sub = QLabel("ADAPTIVE MULTIMODAL BIOSIGNAL CONTROL")
        sub.setStyleSheet(f"color: {C_MUTED}; font-size: 9px; letter-spacing: 3px;")
        left.addWidget(sub)

        # BLE Connection
        ble_group = QGroupBox("NPG LITE CONNECTION")
        ble_layout = QVBoxLayout(ble_group)
        self.btn_connect = QPushButton("CONNECT NPG LITE")
        self.btn_connect.setCheckable(True)
        self.btn_connect.setFixedHeight(40)
        ble_layout.addWidget(self.btn_connect)
        self.lbl_battery = QLabel("Battery: —")
        self.lbl_battery.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        ble_layout.addWidget(self.lbl_battery)
        left.addWidget(ble_group)

        # Channel config
        ch_group = QGroupBox("CHANNEL CONFIGURATION")
        ch_layout = QVBoxLayout(ch_group)
        self._ch_combos = []
        for i in range(MAX_CHANNELS):
            row = QHBoxLayout()
            lbl = QLabel(f"CH {i+1}")
            lbl.setFixedWidth(35)
            lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
            cmb = QComboBox()
            cmb.addItems(["EMG", "EEG", "EOG", "ECG"])
            cmb.setEnabled(False)
            cmb.currentIndexChanged.connect(lambda idx, ch=i: self._on_filter_change(ch, idx))
            row.addWidget(lbl)
            row.addWidget(cmb)
            ch_layout.addLayout(row)
            self._ch_combos.append(cmb)
        left.addWidget(ch_group)

        # Arm connection
        arm_group = QGroupBox("ARM CONNECTION")
        arm_layout = QVBoxLayout(arm_group)
        arm_port_row = QHBoxLayout()
        self.cmb_arm_port = QComboBox()
        self.cmb_arm_port.addItem("SIMULATED")
        self.cmb_arm_port.addItems(self.arm.list_ports())
        btn_arm_connect = QPushButton("CONNECT ARM")
        btn_arm_connect.clicked.connect(self._on_arm_connect)
        arm_port_row.addWidget(self.cmb_arm_port)
        arm_port_row.addWidget(btn_arm_connect)
        arm_layout.addLayout(arm_port_row)
        btn_arm_reset = QPushButton("RESET ARM")
        btn_arm_reset.clicked.connect(self.arm.reset)
        arm_layout.addWidget(btn_arm_reset)
        left.addWidget(arm_group)

        # Notch filter (power line interference)
        notch_group = QGroupBox("NOTCH FILTER")
        notch_layout = QHBoxLayout(notch_group)
        notch_lbl = QLabel("Power line:")
        notch_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self._notch_combo = QComboBox()
        self._notch_combo.addItems(["50 Hz  (India/EU)", "60 Hz  (US)", "Off"])
        self._notch_combo.setCurrentIndex(0)   # default 50Hz
        self._notch_combo.currentIndexChanged.connect(self._apply_notch)
        notch_layout.addWidget(notch_lbl)
        notch_layout.addWidget(self._notch_combo)
        left.addWidget(notch_group)
        cap_group = QGroupBox("DATA CAPTURE  (for TFLite training)")
        cap_layout = QVBoxLayout(cap_group)

        # Gesture type selector
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

        # Arm selector — only shown for EMG gestures
        self._arm_row = QHBoxLayout()
        arm_lbl = QLabel("ARM")
        arm_lbl.setFixedWidth(60)
        arm_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.cmb_capture_arm = QComboBox()
        self.cmb_capture_arm.addItems([
            "CH2  (Right)", "CH3  (Left)", "BOTH  (Both Arms)"])
        self._arm_row.addWidget(arm_lbl)
        self._arm_row.addWidget(self.cmb_capture_arm)
        cap_layout.addLayout(self._arm_row)

        # Hide arm selector for EEG/REST gestures
        self.cmb_capture_gesture.currentTextChanged.connect(
            self._on_gesture_type_changed)

        # Label preview
        self.lbl_capture_preview = QLabel("Label: CH2_STRONG_FLEX")
        self.lbl_capture_preview.setStyleSheet(
            f"color: {C_ACCENT}; font-size: 9px;")
        cap_layout.addWidget(self.lbl_capture_preview)
        self.cmb_capture_gesture.currentTextChanged.connect(
            self._update_capture_preview)
        self.cmb_capture_arm.currentTextChanged.connect(
            self._update_capture_preview)

        cap_btn_row = QHBoxLayout()
        self.btn_capture = QPushButton("START CAPTURE")
        self.btn_capture.setCheckable(True)
        self.btn_capture.clicked.connect(self._on_capture_toggle)
        self.lbl_capture_count = QLabel("0 samples")
        self.lbl_capture_count.setStyleSheet(
            f"color: {C_MUTED}; font-size: 10px;")
        cap_btn_row.addWidget(self.btn_capture)
        cap_btn_row.addWidget(self.lbl_capture_count)
        cap_layout.addLayout(cap_btn_row)
        left.addWidget(cap_group)

        # Mode selector
        mode_group = QGroupBox("EEG HEADBAND MODE")
        mode_layout = QVBoxLayout(mode_group)
        mode_hint = QLabel("Match this to your electrode position.")
        mode_hint.setStyleSheet(f"color: {C_MUTED}; font-size: 9px;")
        mode_hint.setWordWrap(True)
        mode_layout.addWidget(mode_hint)

        self._mode_btn_group = QButtonGroup(self)
        self._mode_btn_group.setExclusive(True)
        mode_btn_row = QHBoxLayout()

        btn_pfc = QPushButton("PREFRONTAL  (Forehead)")
        btn_pfc.setCheckable(True)
        btn_pfc.setChecked(True)
        btn_pfc.setMinimumHeight(36)
        btn_pfc.setStyleSheet(
            f"QPushButton:checked {{ background: {C_ACCENT}; color: {C_BG}; "
            f"border-color: {C_ACCENT}; font-weight: bold; }}")

        btn_vc = QPushButton("VISUAL CORTEX  (Back of head)")
        btn_vc.setCheckable(True)
        btn_vc.setMinimumHeight(36)
        btn_vc.setStyleSheet(
            f"QPushButton:checked {{ background: #4fc3f7; color: {C_BG}; "
            f"border-color: #4fc3f7; font-weight: bold; }}")

        self._mode_btn_group.addButton(btn_pfc, 0)
        self._mode_btn_group.addButton(btn_vc, 1)
        self._mode_btn_group.idClicked.connect(self._on_mode_changed)

        mode_layout.addWidget(btn_pfc)
        mode_layout.addWidget(btn_vc)

        self.lbl_mode_intents = QLabel(
            "Active: CHEEK TWITCH · JAW · FOCUS + EMG")
        self.lbl_mode_intents.setStyleSheet(
            f"color: {C_ACCENT}; font-size: 9px;")
        self.lbl_mode_intents.setWordWrap(True)
        mode_layout.addWidget(self.lbl_mode_intents)

        # PFC blink option — only visible in PFC mode
        self._chk_pfc_blink = QCheckBox("Enable blink detection in PFC mode")
        self._chk_pfc_blink.setStyleSheet(
            f"color: {C_TEXT}; font-size: 10px;")
        self._chk_pfc_blink.setToolTip(
            "Blinks appear smaller at Fp1/Fp2 than in VC mode.\n"
            "Uses a 30% lower threshold to compensate.\n"
            "May increase false positives — adjust BLINK slider if needed.")
        self._chk_pfc_blink.stateChanged.connect(self._on_pfc_blink_toggled)
        mode_layout.addWidget(self._chk_pfc_blink)
        left.addWidget(mode_group)

        # TFLite status
        tflite_group = QGroupBox("TFLITE MODEL")
        tflite_layout = QVBoxLayout(tflite_group)
        self.lbl_tflite_status = QLabel("● No model loaded — threshold mode")
        self.lbl_tflite_status.setStyleSheet(
            f"color: {C_MUTED}; font-size: 10px;")
        self.lbl_tflite_status.setWordWrap(True)
        tflite_layout.addWidget(self.lbl_tflite_status)
        btn_reload_model = QPushButton("⟳  RELOAD MODEL")
        btn_reload_model.clicked.connect(self._on_reload_tflite)
        tflite_layout.addWidget(btn_reload_model)
        hint_tflite = QLabel("Run train_classifier.py after collecting data.")
        hint_tflite.setStyleSheet(f"color: {C_MUTED}; font-size: 9px;")
        hint_tflite.setWordWrap(True)
        tflite_layout.addWidget(hint_tflite)
        left.addWidget(tflite_group)

        cal_btn = QPushButton("↺  RECALIBRATE THRESHOLDS")
        cal_btn.clicked.connect(self._on_recalibrate)
        left.addWidget(cal_btn)

        map_btn = QPushButton("⚙  CONFIGURE MAPPING")
        map_btn.setFixedHeight(40)
        map_btn.setStyleSheet(
            f"QPushButton {{ border: 2px solid {C_ACCENT}; color: {C_ACCENT}; "
            f"font-size: 11px; font-weight: bold; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {C_ACCENT}; color: {C_BG}; }}")
        map_btn.clicked.connect(self._open_mapping_dialog)
        left.addWidget(map_btn)

        left.addStretch()

        root.addWidget(left_scroll)

        # CENTRE: Signal monitor + log
        centre = QVBoxLayout()
        self.signal_panel = SignalPanel()
        centre.addWidget(self.signal_panel)
        self.log = LogPanel()
        centre.addWidget(self.log)
        root.addLayout(centre, 3)

        # RIGHT: Arm visualiser
        right = QVBoxLayout()
        self.arm_vis = ArmVisualiser()
        right.addWidget(self.arm_vis)

        # Signal quality indicators
        qual_group = QGroupBox("SIGNAL QUALITY")
        qual_layout = QVBoxLayout(qual_group)
        self._qual_bars = {}
        self._health_labels = {}
        for sig, label, ch_idx in [("ch2_emg", "CH2", 1), ("ch3_emg", "CH3", 2), ("eeg", "EEG", 0)]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(35)
            lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedHeight(8)
            bar.setTextVisible(False)
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {C_GREEN}; }}")
            health_lbl = QLabel("···")
            health_lbl.setFixedWidth(56)
            health_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 9px; font-weight: bold;")
            row.addWidget(lbl)
            row.addWidget(bar)
            row.addWidget(health_lbl)
            qual_layout.addLayout(row)
            self._qual_bars[sig] = bar
            self._health_labels[ch_idx] = health_lbl
        health_hint = QLabel(
            "OK=good · NO SIG=check electrode · SAT=bad contact/short · NOISY=loose/movement")
        health_hint.setStyleSheet(f"color: {C_MUTED}; font-size: 8px;")
        health_hint.setWordWrap(True)
        qual_layout.addWidget(health_hint)
        right.addWidget(qual_group)

        # Calibration status
        self.lbl_cal_status = QLabel("● Collecting baseline data...")
        self.lbl_cal_status.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
        self.lbl_cal_status.setWordWrap(True)
        right.addWidget(self.lbl_cal_status)

        # Passive floor tracker status
        self.lbl_floor_status = QLabel("○ Learning resting floor...")
        self.lbl_floor_status.setStyleSheet(f"color: {C_MUTED}; font-size: 9px;")
        self.lbl_floor_status.setWordWrap(True)
        right.addWidget(self.lbl_floor_status)

        # Manual threshold tuning for EEG signals
        thresh_group = QGroupBox("EEG THRESHOLD TUNING")
        thresh_layout = QVBoxLayout(thresh_group)
        thresh_hint = QLabel("Drag left if intent isn't firing. Drag right to reduce false triggers.\nHOLD = samples signal must stay above threshold before firing (30Hz = 1s).\nUPPER bounds reject signals so large they're likely artifacts, not real gestures.")
        thresh_hint.setStyleSheet(f"color: {C_MUTED}; font-size: 9px;")
        thresh_hint.setWordWrap(True)
        thresh_layout.addWidget(thresh_hint)

        self._thresh_sliders = {}
        self._thresh_labels  = {}   # key → QLabel, for mode-aware renaming
        self._thresh_rows    = {}   # key → QHBoxLayout, for mode-aware show/hide

        for key, label, default, lo, hi in [
            ("blink",       "BLINK LOWER",              150, 1,  500),
            ("blink_upper", "BLINK UPPER",               280, 1,  500),
            ("jaw",         "JAW/CHEEK LOWER",           200, 1,  500),
            ("jaw_upper",   "JAW/CHEEK UPPER",           450, 1,  500),
            ("eeg_focus",   "FOCUS",                      40, 1,  100),
            ("hold_light",  "LIGHT HOLD  (smp)",           5, 2,   20),
            ("hold_strong", "STRONG HOLD (smp)",           8, 3,   30),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 10px;")
            slider = QSlider(Qt.Horizontal)
            slider.setRange(lo, hi)
            slider.setValue(default)
            unit = "" if "smp" not in label else " smp"
            val_lbl = QLabel(f"{default}{unit}")
            val_lbl.setFixedWidth(50)
            val_lbl.setStyleSheet(f"color: {C_ACCENT}; font-size: 10px;")
            slider.valueChanged.connect(
                lambda v, k=key, vl=val_lbl, u=unit:
                    self._on_thresh_changed(k, v, vl, u))
            row.addWidget(lbl)
            row.addWidget(slider)
            row.addWidget(val_lbl)
            thresh_layout.addLayout(row)
            self._thresh_sliders[key] = slider
            self._thresh_labels[key]  = lbl
            self._thresh_rows[key]    = row

        right.addWidget(thresh_group)

        right.addStretch()
        root.addLayout(right, 2)

        # Hidden mapping combos — values stored here, displayed in MappingDialog
        from arm.arm_controller import ArmController as _AC
        from hid_controller import HID_ACTIONS

        _arm_defaults = {
            "CH2_STRONG":        "GRIP_TOGGLE",
            "CH2_LIGHT":         "AXIS1_CW",
            "CH3_STRONG":        "GRIP_TOGGLE",
            "CH3_LIGHT":         "AXIS1_CCW",
            "BOTH_STRONG":       "RESET",
            "BOTH_LIGHT":        "AXIS2_CW",
            "EEG_BLINK":         "AXIS3_CW",
            "EEG_DOUBLE_BLINK":  "AXIS3_CCW",
            "EEG_TRIPLE_BLINK":  "AXIS2_CCW",
            "EEG_JAW_CLENCH":    "GRIP_TOGGLE",
            "EEG_CHEEK_TWITCH":  "GRIP_TOGGLE",
            "EEG_FOCUS_HIGH":    "AXIS2_CW",
        }

        self._mapping_combos     = {}
        self._hid_mapping_combos = {}
        self._arm_actions_list   = _AC.ACTIONS
        self._hid_actions_list   = HID_ACTIONS

        from intent_engine import ALL_POSSIBLE_INTENTS
        for intent in ALL_POSSIBLE_INTENTS:
            arm_cmb = QComboBox()
            arm_cmb.addItems(_AC.ACTIONS)
            d = _arm_defaults.get(intent, "NONE")
            if d in _AC.ACTIONS:
                arm_cmb.setCurrentIndex(_AC.ACTIONS.index(d))
            hid_cmb = QComboBox()
            hid_cmb.addItems(HID_ACTIONS)
            # Keep hidden — values accessed in _on_intent
            self._mapping_combos[intent]     = arm_cmb
            self._hid_mapping_combos[intent] = hid_cmb

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("VOLITION ready.")

    # ── Signal wiring ─────────────────────────────────────────────────────

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self._on_connect_clicked)
        self.ble.scan_result.connect(self._on_scan_result)
        self.ble.device_connected.connect(self._on_connected)
        self.ble.device_disconnected.connect(self._on_disconnected)
        self.ble.data_received.connect(self._on_data)
        self.ble.battery_updated.connect(self._on_battery)
        self.ble.error.connect(self._on_error)

    # ── BLE handlers ──────────────────────────────────────────────────────

    def _on_connect_clicked(self):
        if self.btn_connect.isChecked():
            self.btn_connect.setText("SCANNING...")
            self.btn_connect.setEnabled(False)
            self.status.showMessage("Scanning for NPG Lite...")
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
        for i in range(MAX_CHANNELS):
            self._ch_combos[i].setEnabled(i < num_channels)
        self.log.log(f"NPG Lite connected — {num_channels} channels @ 500Hz", C_GREEN)
        self.status.showMessage(f"Connected · {num_channels}CH · 500Hz")
        self.intent_engine.force_recalibrate()
        self.intent_engine.reset_floor_trackers()
        self._apply_notch()
        for m in self._health.values():
            m.reset()
        self._last_logged_health = {k: "CALIBRATING" for k in self._health}   # apply notch immediately on connect

    def _on_disconnected(self):
        self.is_connected = False
        self.num_channels = 0
        self.btn_connect.setChecked(False)
        self.btn_connect.setText("CONNECT NPG LITE")
        self.btn_connect.setEnabled(True)
        for cmb in self._ch_combos:
            cmb.setEnabled(False)
        self.log.log("NPG Lite disconnected.", C_MUTED)
        self.status.showMessage("Disconnected.")

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
        """30Hz UI update — collect processor outputs, feed intent engine."""
        if not self.is_connected:
            return

        ch2_emg = ch3_emg = 0.0
        eeg_beta = eeg_blink = eeg_jaw = 0.0

        for ch in range(self.num_channels):
            p = self.processors[ch]
            ftype = self._active_filter_types[ch]

            if ftype == 'eeg':
                # CH1 = EEG
                eeg_beta  = p.val_beta_pct
                eeg_blink = p.val_blink_envelope
                eeg_jaw   = p.val_jaw_envelope

            elif ftype == 'emg':
                val = p.val_emg_envelope
                if ch == 1:
                    # CH2 = Right arm
                    ch2_emg = val
                elif ch == 2:
                    # CH3 = Left arm
                    ch3_emg = val

        # Feed intent engine with per-channel values
        self.intent_engine.update_channel_health(
            ch2_healthy = self._health[1].is_healthy,
            ch3_healthy = self._health[2].is_healthy,
            eeg_healthy = self._health[0].is_healthy,
        )
        self.intent_engine.process_signals(
            ch2_emg=ch2_emg,
            ch3_emg=ch3_emg,
            eeg_beta=eeg_beta,
            eeg_blink=eeg_blink,
            eeg_jaw=eeg_jaw,
        )

        # Display: RAW values on the bars (not corrected — see SignalBar
        # docstring for why), with floor + threshold overlay markers so
        # you can watch the live signal relative to both lines directly.
        ie = self.intent_engine
        self.signal_panel.update_signals(
            ch2_emg = ch2_emg,
            ch3_emg = ch3_emg,
            blink   = eeg_blink,
            jaw     = eeg_jaw,
            focus   = eeg_beta,
        )

        # Floor markers (raw space) — None until established, hides the line
        self.signal_panel.update_markers(
            "ch2_emg", floor=ie._floor_ch2.floor if ie._floor_ch2.is_established else None)
        self.signal_panel.update_markers(
            "ch3_emg", floor=ie._floor_ch3.floor if ie._floor_ch3.is_established else None)
        self.signal_panel.update_markers(
            "blink", floor=ie._floor_blink.floor if ie._floor_blink.is_established else None)
        self.signal_panel.update_markers(
            "jaw", floor=ie._floor_jaw.floor if ie._floor_jaw.is_established else None)

        # Threshold markers — thresholds are calibrated on the FLOOR-
        # CORRECTED signal, so convert back to raw space by adding the
        # floor back: raw_threshold = floor + corrected_threshold
        f2 = ie._floor_ch2.floor if ie._floor_ch2.is_established else 0.0
        f3 = ie._floor_ch3.floor if ie._floor_ch3.is_established else 0.0
        fb = ie._floor_blink.floor if ie._floor_blink.is_established else 0.0
        fj = ie._floor_jaw.floor if ie._floor_jaw.is_established else 0.0

        self.signal_panel.update_markers("ch2_emg", thresholds=[
            (f2 + ie.th_ch2_light.threshold, "#ffdd88"),
            (f2 + ie.th_ch2_strong.threshold, "#ffffff"),
        ])
        self.signal_panel.update_markers("ch3_emg", thresholds=[
            (f3 + ie.th_ch3_light.threshold, "#ffdd88"),
            (f3 + ie.th_ch3_strong.threshold, "#ffffff"),
        ])

        # BLINK bar — always dedicated to the blink envelope
        self.signal_panel.update_markers("blink",
            floor=ie._floor_blink.floor if ie._floor_blink.is_established else None,
            thresholds=[
                (fb + ie.th_blink.threshold,       "#ffffff"),
                (fb + ie.th_blink_upper.threshold, "#aaaaaa"),
            ])

        # JAW CLENCH bar — always dedicated to the jaw envelope. In PFC
        # mode it also shows the cheek twitch threshold (orange) since
        # both detectors read the same underlying signal.
        jaw_thresholds = [
            (fj + ie.th_jaw.threshold,       "#ffffff"),
            (fj + ie.th_jaw_upper.threshold, "#aaaaaa"),
        ]
        if ie.mode == "pfc":
            jaw_thresholds.append((fj + ie.th_cheek_twitch.threshold, "#ff6644"))
        self.signal_panel.update_markers("jaw",
            floor=ie._floor_jaw.floor if ie._floor_jaw.is_established else None,
            thresholds=jaw_thresholds)

        self.signal_panel.update_markers("focus", thresholds=[
            (ie.th_eeg_focus.threshold, "#ffffff"),
        ])

        # Update health status labels + log transitions
        _health_colours = {
            "OK":          C_GREEN,
            "CALIBRATING": C_MUTED,
            "NO_SIGNAL":   C_DANGER,
            "SATURATED":   C_DANGER,
            "NOISY":       "#ffaa00",
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
                    f"color: {_health_colours.get(status, C_MUTED)}; "
                    f"font-size: 9px; font-weight: bold;")
            # Log only when status actually changes, not every tick
            if status != self._last_logged_health.get(ch_idx) and status != "CALIBRATING":
                self._last_logged_health[ch_idx] = status
                name = monitor.name
                if status == "OK":
                    self.log.log(f"{name} signal recovered — OK", C_GREEN)
                elif status == "NO_SIGNAL":
                    self.log.log(
                        f"⚠ {name}: NO SIGNAL — check electrode contact "
                        f"and snap connector", C_DANGER)
                elif status == "SATURATED":
                    self.log.log(
                        f"⚠ {name}: SATURATED — amplifier railing, check "
                        f"for short or very poor contact", C_DANGER)
                elif status == "NOISY":
                    self.log.log(
                        f"⚠ {name}: NOISY — loose electrode or movement "
                        f"artifact, check mounting", "#ffaa00")
            elif status == "CALIBRATING":
                self._last_logged_health[ch_idx] = status

        # Signal quality display
        for sig, bar in self._qual_bars.items():
            bar.setValue(int(
                self.intent_engine.signal_quality.get(sig, 0) * 100))

        # Passive floor status
        ie = self.intent_engine
        floors_ready = (ie._floor_ch2.is_established and
                       ie._floor_ch3.is_established and
                       ie._floor_blink.is_established and
                       ie._floor_jaw.is_established)
        if floors_ready:
            self.lbl_floor_status.setText(
                f"● Floor: CH2={ie._floor_ch2.floor:.0f}  "
                f"CH3={ie._floor_ch3.floor:.0f}  "
                f"BLINK={ie._floor_blink.floor:.0f}  "
                f"JAW={ie._floor_jaw.floor:.0f}")
            self.lbl_floor_status.setStyleSheet(
                f"color: {C_GREEN}; font-size: 9px;")
        else:
            self.lbl_floor_status.setText("○ Learning resting floor...")
            self.lbl_floor_status.setStyleSheet(
                f"color: {C_MUTED}; font-size: 9px;")

        # Calibration status
        if self.intent_engine._auto_calibrated:
            bt  = self.intent_engine.th_blink.threshold
            btu = self.intent_engine.th_blink_upper.threshold
            jt  = self.intent_engine.th_jaw.threshold
            jtu = self.intent_engine.th_jaw_upper.threshold
            self._thresh_sliders["blink"].setValue(int(bt))
            self._thresh_sliders["blink_upper"].setValue(int(btu))
            self._thresh_sliders["jaw"].setValue(int(jt))
            self._thresh_sliders["jaw_upper"].setValue(int(jtu))
            if self.intent_engine.eeg_in_lockout:
                source = getattr(self.intent_engine, "_eeg_lockout_source", None)
                if source == "model":
                    self.lbl_cal_status.setText(
                        "🤖 MODEL FLAGGED BAD EEG — suppressing until clean signal returns")
                else:
                    self.lbl_cal_status.setText(
                        "⚡ SATURATION LOCKOUT — settling...")
                self.lbl_cal_status.setStyleSheet(
                    f"color: {C_DANGER}; font-size: 10px;")
            else:
                self.lbl_cal_status.setText(
                    f"● Calibrated  blink={bt:.0f}-{btu:.0f}  jaw={jt:.0f}-{jtu:.0f}")
                self.lbl_cal_status.setStyleSheet(
                    f"color: {C_GREEN}; font-size: 10px;")
        else:
            remain = max(0,
                self.intent_engine._calibration_window
                - self.intent_engine._samples_since_start)
            self.lbl_cal_status.setText(
                f"● Calibrating... {remain} samples remaining")
            self.lbl_cal_status.setStyleSheet(
                f"color: {C_MUTED}; font-size: 10px;")

        # Capture count
        if self.intent_engine._capture_mode:
            self.lbl_capture_count.setText(
                f"{len(self.intent_engine._capture_buffer)} samples")

    # ── Arm callbacks ─────────────────────────────────────────────────────

    def _on_arm_position(self, a1, a2, a3, grip_open):
        self.arm_vis.update_position(a1, a2, a3, grip_open)

    def _on_arm_status(self, msg):
        self.log.log(f"ARM: {msg}", C_MUTED)
        self.status.showMessage(msg, 3000)

    def _on_intent(self, intent: str, intensity: float):
        # Look up arm action
        arm_cmb = self._mapping_combos.get(intent)
        hid_cmb = self._hid_mapping_combos.get(intent)

        if arm_cmb is None:
            self.log.log(
                f"WARNING: no mapping row for '{intent}'", C_DANGER)
            return

        arm_action = arm_cmb.currentText()
        hid_action = hid_cmb.currentText() if hid_cmb else "NONE"

        # Fire arm action
        if arm_action and arm_action != "NONE":
            self.arm.execute_action(arm_action, intensity)

        # Fire HID action
        if hid_action and hid_action != "NONE":
            self.hid.execute(hid_action)

        # Update UI
        parts = []
        if arm_action != "NONE": parts.append(f"ARM:{arm_action}")
        if hid_action != "NONE": parts.append(f"HID:{hid_action}")
        label = "  ".join(parts) if parts else "(unassigned)"

        self.arm_vis.update_intent(f"{intent} → {label}")
        self.log.log(
            f"INTENT  {intent}  →  {label}  (intensity {intensity:.2f})",
            C_ACCENT if parts else C_MUTED)

    def _on_arm_connect(self):
        port = self.cmb_arm_port.currentText()
        if port == "SIMULATED":
            self.arm.connect_simulated()
        else:
            self.arm.connect(port)

    def _on_gesture_type_changed(self, gesture: str):
        """Show/hide arm selector depending on whether gesture needs an arm."""
        emg_gestures = {"STRONG_FLEX", "WEAK_FLEX"}
        is_emg = gesture in emg_gestures
        for i in range(self._arm_row.count()):
            item = self._arm_row.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(is_emg)
        self._update_capture_preview()

    def _update_capture_preview(self):
        """Show the full label that will be written to CSV."""
        self.lbl_capture_preview.setText(
            f"Label: {self._build_capture_label()}")

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
        # EEG and REST categories — return as-is
        return gesture

    def _on_capture_toggle(self):
        if self.btn_capture.isChecked():
            label = self._build_capture_label()
            self.intent_engine.start_capture(label)
            self.btn_capture.setText("STOP CAPTURE")
            self.log.log(f"Capturing '{label}'...", C_ACCENT)
        else:
            count = self.intent_engine.stop_capture()
            self.btn_capture.setText("START CAPTURE")
            self.log.log(
                f"Captured {count} samples → volition_training_data.csv",
                C_GREEN)

    def _on_pfc_blink_toggled(self, state: int):
        enabled = state == Qt.Checked
        self.intent_engine.pfc_blink_enabled = enabled
        self.intent_engine.force_recalibrate()
        active = self.intent_engine.active_intents
        eeg_only = [i for i in active if i.startswith("EEG")]
        self.lbl_mode_intents.setText(
            f"Active EEG: {' · '.join(i.replace('EEG_','') for i in eeg_only)}")
        self.log.log(
            f"PFC blink detection {'enabled' if enabled else 'disabled'}",
            C_ACCENT)
        # Update capture gesture list
        self._on_mode_changed(0)   # refresh with current PFC mode

    def _on_mode_changed(self, btn_id: int):
        mode = "pfc" if btn_id == 0 else "vc"
        self.intent_engine.set_mode(mode)

        # Show PFC blink checkbox only in PFC mode
        self._chk_pfc_blink.setVisible(mode == "pfc")

        # Relabel/hide the JAW bar in the BIOSIGNAL MONITOR panel too
        self.signal_panel.set_jaw_row_mode(mode == "pfc")

        # Mode-aware relabel/show-hide for the jaw/cheek threshold rows.
        # PFC's headline EEG detector is cheek twitch, not jaw clench, so
        # relabel to match; VC doesn't use this signal at all, so hide it
        # rather than showing a misleading duplicate of the blink rows.
        jaw_visible = (mode == "pfc")
        for key, pfc_label in [("jaw", "CHEEK TWITCH LOWER"),
                                ("jaw_upper", "CHEEK TWITCH UPPER")]:
            row = self._thresh_rows.get(key)
            lbl = self._thresh_labels.get(key)
            if row:
                for i in range(row.count()):
                    w = row.itemAt(i).widget()
                    if w:
                        w.setVisible(jaw_visible)
            if lbl:
                lbl.setText(pfc_label if jaw_visible else "JAW/CHEEK LOWER"
                            if key == "jaw" else "JAW/CHEEK UPPER")

        # Update capture gesture list
        self.cmb_capture_gesture.blockSignals(True)
        self.cmb_capture_gesture.clear()
        labels = self.intent_engine.capture_labels
        emg_labels    = [l for l in labels if "STRONG" in l or "WEAK" in l
                         or l in ("BOTH_STRONG", "BOTH_LIGHT")]
        gesture_bases = []
        if "CH2_STRONG" in labels or "CH3_STRONG" in labels:
            gesture_bases.append("STRONG_FLEX")
        if "CH2_LIGHT" in labels or "CH3_LIGHT" in labels:
            gesture_bases.append("WEAK_FLEX")
        eeg_labels = [l for l in labels
                      if l not in ("REST",) and
                      not any(x in l for x in ("CH2","CH3","BOTH","FLEX"))]
        self.cmb_capture_gesture.addItems(gesture_bases + eeg_labels + ["REST"])
        self.cmb_capture_gesture.blockSignals(False)
        self._update_capture_preview()

        # Update mode intent label
        active = self.intent_engine.active_intents
        eeg_only = [i for i in active if i.startswith("EEG")]
        self.lbl_mode_intents.setText(
            f"Active EEG: {' · '.join(i.replace('EEG_','') for i in eeg_only)}")

        # Update TFLite status
        self._on_reload_tflite()

        mode_name = "PREFRONTAL" if mode == "pfc" else "VISUAL CORTEX"
        self.log.log(f"Mode → {mode_name}", C_ACCENT)

    def _open_mapping_dialog(self):
        dlg = MappingDialog(
            intent_engine        = self.intent_engine,
            arm_actions          = self._arm_actions_list,
            hid_actions          = self._hid_actions_list,
            mapping_combos       = self._mapping_combos,
            hid_mapping_combos   = self._hid_mapping_combos,
            parent               = self,
        )
        dlg.exec()

    def _apply_notch(self):
        """Apply notch filter setting to all active channel processors."""
        idx = self._notch_combo.currentIndex()
        setting = {0: '50', 1: '60', 2: 'off'}[idx]
        for ch in range(self.num_channels):
            self.processors[ch].set_notch(setting)
        if self.is_connected:
            self.log.log(
                f"Notch filter: {self._notch_combo.currentText()}", C_MUTED)

    def _on_recalibrate(self):
        self.intent_engine.force_recalibrate()
        self.log.log("Recalibration started. Hold still for 2 seconds...", C_ACCENT)

    def _on_reload_tflite(self):
        self.intent_engine.reload_tflite()
        if self.intent_engine.tflite_active:
            self.lbl_tflite_status.setText("● TFLite model active")
            self.lbl_tflite_status.setStyleSheet(
                f"color: {C_GREEN}; font-size: 10px;")
            self.log.log("TFLite model loaded — classifier active.", C_GREEN)
        else:
            self.lbl_tflite_status.setText(
                "● No model found — threshold mode")
            self.lbl_tflite_status.setStyleSheet(
                f"color: {C_MUTED}; font-size: 10px;")
            self.log.log(
                "No TFLite model found. Run train_classifier.py first.",
                C_MUTED)

    def _on_thresh_changed(self, key: str, value: int, val_lbl, unit: str = ""):
        val_lbl.setText(f"{value}{unit}")
        ie = self.intent_engine
        if key == "blink":
            ie.th_blink.set_threshold(value)
        elif key == "blink_upper":
            ie.th_blink_upper.set_threshold(value)
        elif key == "jaw":
            ie.th_jaw.set_threshold(value)
        elif key == "jaw_upper":
            ie.th_jaw_upper.set_threshold(value)
        elif key == "eeg_focus":
            ie.th_eeg_focus.set_threshold(value)
        elif key == "hold_strong":
            ie.set_hold_durations(value, ie.hold_light_samples)
        elif key == "hold_light":
            ie.set_hold_durations(ie.hold_strong_samples, value)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Volition")
    window = VolitionApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # When launched via pythonw.exe (no console window), an unhandled
    # exception would otherwise vanish silently with zero indication of
    # what went wrong. Catch anything that escapes main() and write it
    # to a crash log next to this script, so "silent launch" never means
    # "silently fails with no way to debug."
    import traceback
    import datetime

    try:
        main()
    except Exception:
        crash_log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "volition_crash_log.txt")
        try:
            with open(crash_log_path, "a") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Crash at {datetime.datetime.now().isoformat()}\n")
                f.write(f"{'='*60}\n")
                f.write(traceback.format_exc())
        except Exception:
            pass   # even the crash logger failing shouldn't raise further
        raise  # re-raise so `python` (non-w) launches still show it too
