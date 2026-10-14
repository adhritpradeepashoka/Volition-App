"""
Volition - 3-DOF Arm Controller
================================
The arm has 3 rotational axes and a gripper:
  Axis 1 (Base)     — rotates around vertical axis (CW/CCW from top view)
  Axis 2 (Shoulder) — rotates around its horizontal axis
  Axis 3 (Elbow)    — rotates around its horizontal axis
  Gripper           — toggles between open and closed

Serial commands sent to Arduino (9600 baud, newline terminated):
  A1:<angle>    Axis 1  (0–180)
  A2:<angle>    Axis 2  (0–180)
  A3:<angle>    Axis 3  (0–180)
  GRIP:OPEN
  GRIP:CLOSE
  GRIP:TOGGLE
  RESET
  STATUS
"""

import serial
import serial.tools.list_ports
import threading
import time


class ArmController:

    # Rotation limits per axis (degrees)
    LIMITS = {
        "a1": (0,   180),
        "a2": (20,  160),
        "a3": (10,  170),
    }

    # Default (rest) positions
    DEFAULTS = {"a1": 90, "a2": 90, "a3": 90}

    # Step size per command (degrees) — scaled by intensity at call time
    BASE_STEP = 10

    # All actions the arm can perform — imported by mapping panel
    ACTIONS = [
        "NONE",
        "AXIS1_CW",  "AXIS1_CCW",
        "AXIS2_CW",  "AXIS2_CCW",
        "AXIS3_CW",  "AXIS3_CCW",
        "GRIP_TOGGLE",
        "GRIP_OPEN", "GRIP_CLOSE",
        "RESET",
    ]

    def __init__(self):
        self.port      = None
        self.serial    = None
        self.connected = False
        self._lock     = threading.Lock()

        # Current positions
        self.a1 = self.DEFAULTS["a1"]
        self.a2 = self.DEFAULTS["a2"]
        self.a3 = self.DEFAULTS["a3"]
        self.grip_open = True

        # Callbacks
        self.on_position_changed = None   # fn(a1, a2, a3, grip_open)
        self.on_status_changed   = None   # fn(msg)

    # ── Connection ────────────────────────────────────────────────────────

    def list_ports(self) -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port: str, baud: int = 9600) -> bool:
        try:
            self.serial    = serial.Serial(port, baud, timeout=1)
            time.sleep(2)
            self.port      = port
            self.connected = True
            self._notify_status(f"Arm connected on {port}")
            self.reset()
            return True
        except Exception as e:
            self.connected = False
            self._notify_status(f"Arm connection failed: {e}")
            return False

    def connect_simulated(self):
        self.connected = True
        self.port      = "SIMULATED"
        self._notify_status("Arm running in SIMULATED mode")
        self.reset()
        return True

    def disconnect(self):
        if self.serial and self.serial.is_open:
            self.send_raw("RESET")
            self.serial.close()
        self.connected = False
        self._notify_status("Arm disconnected")

    # ── Actions ───────────────────────────────────────────────────────────

    def execute_action(self, action: str, intensity: float = 1.0):
        """
        Execute a named arm action.
        Intensity (0–1) scales the rotation step size so a stronger
        signal produces a larger movement.
        """
        if not action or action == "NONE":
            return

        step = max(3, int(self.BASE_STEP * intensity))

        lo1, hi1 = self.LIMITS["a1"]
        lo2, hi2 = self.LIMITS["a2"]
        lo3, hi3 = self.LIMITS["a3"]

        if action == "AXIS1_CW":
            self.a1 = min(hi1, self.a1 + step)
        elif action == "AXIS1_CCW":
            self.a1 = max(lo1, self.a1 - step)
        elif action == "AXIS2_CW":
            self.a2 = min(hi2, self.a2 + step)
        elif action == "AXIS2_CCW":
            self.a2 = max(lo2, self.a2 - step)
        elif action == "AXIS3_CW":
            self.a3 = min(hi3, self.a3 + step)
        elif action == "AXIS3_CCW":
            self.a3 = max(lo3, self.a3 - step)
        elif action == "GRIP_TOGGLE":
            self._toggle_grip()
            return
        elif action == "GRIP_OPEN":
            self.grip_open = True
            self.send_raw("GRIP:OPEN")
            self._notify_position()
            return
        elif action == "GRIP_CLOSE":
            self.grip_open = False
            self.send_raw("GRIP:CLOSE")
            self._notify_position()
            return
        elif action == "RESET":
            self.reset()
            return

        self._send_axes()

    def _toggle_grip(self):
        self.grip_open = not self.grip_open
        self.send_raw("GRIP:TOGGLE")
        self._notify_position()

    def reset(self):
        self.a1 = self.DEFAULTS["a1"]
        self.a2 = self.DEFAULTS["a2"]
        self.a3 = self.DEFAULTS["a3"]
        self.grip_open = True
        self._send_axes()
        self.send_raw("GRIP:OPEN")
        self._notify_position()

    # ── Internal ──────────────────────────────────────────────────────────

    def _send_axes(self):
        self.send_raw(f"A1:{self.a1}")
        self.send_raw(f"A2:{self.a2}")
        self.send_raw(f"A3:{self.a3}")
        self._notify_position()

    def send_raw(self, cmd: str):
        if not self.connected or not self.serial or not self.serial.is_open:
            return
        with self._lock:
            try:
                self.serial.write(f"{cmd}\n".encode("utf-8"))
            except Exception as e:
                self._notify_status(f"Serial write error: {e}")

    def _notify_position(self):
        if self.on_position_changed:
            self.on_position_changed(
                self.a1, self.a2, self.a3, self.grip_open)

    def _notify_status(self, msg: str):
        print(f"[ArmController] {msg}")
        if self.on_status_changed:
            self.on_status_changed(msg)
