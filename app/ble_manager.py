# Qt wrapper around ble_connection — runs BLE in a background thread,
# emits Qt signals so the UI can react safely from the main thread.
#
# IMPORTANT THREADING NOTE
# =========================
# On Windows, bleak's WinRT backend can invoke notification callbacks
# (on_data / on_battery) from a native WinRT thread-pool thread — NOT
# necessarily the asyncio event loop thread this class manages. That
# thread has never been wrapped by Qt (it's not a QThread, and it's not
# the thread QApplication runs on).
#
# Emitting a Qt signal directly from that unpredictable thread, at 500Hz,
# is what causes:
#   "QBasicTimer::start: QBasicTimer can only be used with threads
#    started with QThread"
# repeated endlessly on every packet.
#
# THE FIX: never call .emit() from inside a bleak callback. Instead,
# push incoming data into a plain thread-safe queue.Queue from whatever
# thread bleak happens to call us on, and drain that queue on a QTimer
# that lives on the MAIN thread (created here, in __init__, which always
# runs on the main thread since BLEManager() is constructed there). Every
# .emit() call this class makes now originates from a thread Qt has
# always known about — the crash cannot happen regardless of which
# native thread WinRT chooses to invoke bleak callbacks on.

import asyncio
import threading
import queue

from PySide6.QtCore import QObject, Signal, QTimer
from ble_connection import NPGConnection


class BLEManager(QObject):
    scan_result         = Signal(list)
    device_connected    = Signal(int)
    device_disconnected = Signal()
    data_received       = Signal(list, int)
    battery_updated     = Signal(int)
    imu_received        = Signal(dict)
    imu_available       = Signal(bool)
    error                = Signal(str)

    # How often the main-thread timer drains the queue. 500Hz data
    # arrives in packets (multiple samples per BLE notification), so
    # draining at ~100Hz comfortably keeps up without adding perceptible
    # latency, while keeping CPU usage low between packets.
    DRAIN_INTERVAL_MS = 10

    def __init__(self):
        super().__init__()

        # Thread-safe queues — safe to push from ANY thread (bleak's
        # WinRT callback thread, the asyncio thread, anywhere), safe to
        # drain from the main thread via the QTimer below.
        self._data_queue  = queue.Queue()
        self._imu_queue   = queue.Queue(maxsize=1000)
        self._misc_queue  = queue.Queue()   # scan results, connect, battery, IMU status, errors

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._conn = None

        # Drain timer — created here, in __init__, which runs on the
        # main thread (BLEManager() is always constructed there). This
        # is the ONLY place Qt signals get emitted from.
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(self.DRAIN_INTERVAL_MS)
        self._drain_timer.timeout.connect(self._drain_queues)
        self._drain_timer.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # ── Main-thread queue draining — the only place .emit() happens ──────

    def _drain_queues(self):
        # Drain data samples — highest frequency, handle first
        while True:
            try:
                samples, num_channels = self._data_queue.get_nowait()
            except queue.Empty:
                break
            self.data_received.emit(samples, num_channels)

        # Drain IMU packets separately. They are much slower than biosignal
        # data but frequent enough to deserve their own bounded queue.
        while True:
            try:
                imu_packet = self._imu_queue.get_nowait()
            except queue.Empty:
                break
            self.imu_received.emit(imu_packet)

        # Drain everything else (scan results, connect/disconnect,
        # battery updates, IMU availability, errors) — all tagged by kind
        # so one queue can carry heterogeneous events without ambiguity
        while True:
            try:
                kind, payload = self._misc_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "scan_result":
                self.scan_result.emit(payload)
            elif kind == "device_connected":
                self.device_connected.emit(payload)
            elif kind == "device_disconnected":
                self.device_disconnected.emit()
            elif kind == "battery_updated":
                self.battery_updated.emit(payload)
            elif kind == "imu_available":
                self.imu_available.emit(bool(payload))
            elif kind == "error":
                self.error.emit(payload)

    # ── Public API — unchanged from before ────────────────────────────────

    def start_scan(self):
        asyncio.run_coroutine_threadsafe(self._scan(), self._loop)

    def connect_to(self, device):
        asyncio.run_coroutine_threadsafe(self._connect(device), self._loop)

    def disconnect(self):
        asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)

    def shutdown(self):
        self._drain_timer.stop()
        try:
            if self._conn:
                asyncio.run_coroutine_threadsafe(
                    self._disconnect(), self._loop
                ).result(timeout=3)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)

    # ── Async BLE operations — run on the asyncio thread ──────────────────
    # These push to queues instead of emitting directly. Note that even
    # though THESE particular methods run on the asyncio thread (which
    # is more predictable than bleak's WinRT callback thread), we still
    # route everything through the same queue+timer path for consistency
    # and so there is exactly one place in the whole class that touches
    # Qt signal emission.

    async def _scan(self):
        try:
            devices = await NPGConnection.scan(timeout=10.0)
            self._misc_queue.put(("scan_result", devices))
        except Exception as e:
            self._misc_queue.put(("error", f"Scan failed: {e}"))

    async def _connect(self, npg_device):
        try:
            self._conn = NPGConnection()
            await self._conn.connect(npg_device)

            # These callbacks may run on bleak's WinRT notification
            # thread — push to the thread-safe queue, never emit here.
            self._conn.on_data(
                lambda s, n: self._data_queue.put((s, n)))
            self._conn.on_battery(
                lambda p: self._misc_queue.put(("battery_updated", p)))
            self._conn.on_imu(self._queue_imu)

            await self._conn.start_streaming()
            self._misc_queue.put(("imu_available", self._conn.imu_available))
            self._misc_queue.put(("device_connected", self._conn.num_channels))
        except Exception as e:
            self._conn = None
            self._misc_queue.put(("error", f"Connection failed: {e}"))

    def _queue_imu(self, packet):
        """Thread-safe IMU queue ingress; never emits Qt signals here."""
        try:
            self._imu_queue.put_nowait(packet)
        except queue.Full:
            # Keep the newest orientation data if the UI is momentarily busy.
            try:
                self._imu_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._imu_queue.put_nowait(packet)
            except queue.Full:
                pass

    async def _disconnect(self):
        try:
            if self._conn:
                await self._conn.disconnect()
                self._conn = None
            self._misc_queue.put(("imu_available", False))
            self._misc_queue.put(("device_disconnected", None))
        except Exception as e:
            self._misc_queue.put(("error", f"Disconnect error: {e}"))
