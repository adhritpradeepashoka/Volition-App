"""
NPG Lite BLE Connection Manager
================================
Handles scanning, connecting, and streaming data from NPG Lite devices.

Usage (standalone):
    python ble_connection.py

Usage (as module):
    from ble_connection import NPGConnection

    connection = NPGConnection()
    devices = await connection.scan()
    await connection.connect(devices[0])
    connection.on_data(my_callback)
    await connection.start_streaming()
"""

import asyncio
import struct
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from npg_protocol import (
    SERVICE_UUID,
    DATA_CHAR_UUID,
    CONTROL_CHAR_UUID,
    BATTERY_CHAR_UUID,
    CMD_START,
    CMD_STOP,
    SAMPLE_RATE,
    detect_channels_from_name,
    parse_packet,
)

# Optional Volition IMU characteristic added by the IMU-enabled NPG Lite firmware.
IMU_CHAR_UUID = "8b5f4e5c-7d3a-4f91-ae2c-7e2f4c7f6a11"


class NPGDevice:
    """Represents a discovered NPG device with parsed metadata."""

    def __init__(self, ble_device: BLEDevice):
        self.ble_device = ble_device
        self.name: str = ble_device.name or "Unknown NPG"
        self.address: str = ble_device.address
        self.expected_channels: int | None = detect_channels_from_name(self.name)

    def __str__(self) -> str:
        ch = f" ({self.expected_channels}CH)" if self.expected_channels else ""
        return f"{self.name}{ch} [{self.address}]"


class NPGConnection:
    """
    Manages BLE connection and data streaming from NPG Lite
    
    Callbacks:
        on_data(callback):    Called with (samples: list[dict], num_channels: int)
        on_battery(callback): Called with (percentage: int)
        on_imu(callback):     Called with a decoded IMU packet dict

    The IMU stream is optional. If the characteristic is unavailable, the
    normal EEG/EMG + battery stream continues exactly as before.
    """

    def __init__(self):
        self.client: BleakClient | None = None
        self.device: NPGDevice | None = None
        self.num_channels: int | None = None
        self.is_streaming: bool = False
        self.sample_count: int = 0
        self._data_callback = None
        self._battery_callback = None
        self._imu_callback = None
        self.imu_available: bool = False
        self.imu_packet_count: int = 0

    # Scanning 

    @staticmethod
    async def scan(timeout: float = 10.0) -> list[NPGDevice]:
        """
        Scan for BLE devices whose name starts with 'NPG'.

        Args:
            timeout: Scan duration in seconds.

        Returns:
            List of discovered NPGDevice objects.
        """
        print(f"Scanning for NPG Lite devices ({timeout}s)...")

        discovered = await BleakScanner.discover(timeout=timeout)
        npg_devices = [
            NPGDevice(d) for d in discovered
            if d.name and d.name.upper().startswith("NPG")
        ]

        if npg_devices:
            print(f"Found {len(npg_devices)} NPG Lite device(s)")
        else:
            print("No NPG Lite devices found")

        return npg_devices

    # Connection 

    async def connect(self, npg_device: NPGDevice) -> None:
        """
        Connect to an NPG device over BLE.

        Args:
            npg_device: The device to connect to.
        """
        self.device = npg_device
        print(f"Connecting to {npg_device.name} ({npg_device.address})...")

        self.client = BleakClient(npg_device.address, timeout=20.0)
        await self.client.connect()

        if not self.client.is_connected:
            raise ConnectionError(f"Failed to connect to {npg_device.name}")

        print(f"Connected to {npg_device.name}")

        # Channel count is determined from device name
        self.num_channels = npg_device.expected_channels
        if self.num_channels is None:
            raise ValueError(
                f"Cannot determine channel count from device name: {npg_device.name}. "
                "Expected name containing '3CH' or '6CH'."
            )
        if self.num_channels == 3:
            print("Explorer or Ninja Playmate detected (3 channels)")
        else:
            print("Beast Playmate detected (6 channels)")

    async def disconnect(self) -> None:
        """Stop streaming (if active) and disconnect from the device."""
        if self.is_streaming:
            await self.stop_streaming()

        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("Disconnected")

        self._reset()

    def _reset(self) -> None:
        """Reset all internal state."""
        self.client = None
        self.device = None
        self.num_channels = None
        self.is_streaming = False
        self.sample_count = 0
        self.imu_available = False
        self.imu_packet_count = 0

    # Callbacks 

    def on_data(self, callback) -> None:
        """
        Register a callback for incoming data samples.

        callback(samples: list[dict], num_channels: int)
            samples: list of {'counter': int, 'channels': list[int]}
        """
        self._data_callback = callback

    def on_battery(self, callback) -> None:
        """
        Register a callback for battery level updates.

        callback(percentage: int)   # 0–100
        """
        self._battery_callback = callback

    def on_imu(self, callback) -> None:
        """
        Register a callback for incoming IMU packets.

        callback(packet: dict) where packet contains:
            timestamp_ms, ax, ay, az, gx, gy, gz
        """
        self._imu_callback = callback

    # Streaming 

    async def start_streaming(self) -> None:
        """
        Subscribe to data/battery notifications and send the START command.
        If channel count wasn't determined from the device name, blocks
        until the first data packet arrives to auto-detect it.
        """
        if not self.client or not self.client.is_connected:
            raise ConnectionError("Not connected to any device")

        # Subscribe to data notifications
        await self.client.start_notify(DATA_CHAR_UUID, self._on_data_notification)

        # Subscribe to battery notifications (might not be supported on all FW versions)
        try:
            await self.client.start_notify(BATTERY_CHAR_UUID, self._on_battery_notification)
        except Exception:
            print("Battery characteristic not available on this device")

        # Optional IMU notifications. This is the only new BLE subscription
        # needed for the IMU-enabled firmware; the existing DATA/BATTERY path
        # is untouched.
        self.imu_available = False
        try:
            await self.client.start_notify(IMU_CHAR_UUID, self._on_imu_notification)
            self.imu_available = True
            print("Volition IMU characteristic attached")
        except Exception as exc:
            print(f"Volition IMU characteristic unavailable: {exc}")

        # Send START command
        await self.client.write_gatt_char(CONTROL_CHAR_UUID, CMD_START)
        self.is_streaming = True
        self.sample_count = 0
        self.imu_packet_count = 0

        print(f"Streaming {self.num_channels} channels @ {SAMPLE_RATE} Hz")

    async def stop_streaming(self) -> None:
        """Send STOP command and unsubscribe from notifications."""
        if not self.client or not self.client.is_connected:
            return

        # Send STOP
        try:
            await self.client.write_gatt_char(CONTROL_CHAR_UUID, CMD_STOP)
        except Exception:
            pass

        # Unsubscribe
        try:
            await self.client.stop_notify(DATA_CHAR_UUID)
        except Exception:
            pass
        try:
            await self.client.stop_notify(BATTERY_CHAR_UUID)
        except Exception:
            pass
        try:
            await self.client.stop_notify(IMU_CHAR_UUID)
        except Exception:
            pass

        self.imu_available = False
        self.is_streaming = False
        print("Streaming stopped")

    # Internal BLE notification handlers 

    def _on_data_notification(self, _sender, data: bytearray) -> None:
        """Handle incoming data notifications from DATA_CHAR_UUID."""
        samples = parse_packet(bytes(data), self.num_channels)
        self.sample_count += len(samples)

        if self._data_callback:
            self._data_callback(samples, self.num_channels)

    def _on_battery_notification(self, _sender, data: bytearray) -> None:
        """Handle incoming battery notifications from BATTERY_CHAR_UUID."""
        if len(data) >= 1 and self._battery_callback:
            self._battery_callback(data[0])

    def _on_imu_notification(self, _sender, data: bytearray) -> None:
        """Decode the Volition IMU characteristic and forward it upstream."""
        if len(data) < 16:
            return

        try:
            timestamp_ms, ax, ay, az, gx, gy, gz = struct.unpack("<I6h", bytes(data[:16]))
        except struct.error:
            return

        self.imu_packet_count += 1
        if self._imu_callback:
            self._imu_callback({
                "timestamp_ms": timestamp_ms,
                "ax": ax,
                "ay": ay,
                "az": az,
                "gx": gx,
                "gy": gy,
                "gz": gz,
            })


# Standalone CLI for testing 

async def _cli_main():
    """Interactive CLI: scan → select device → stream data."""
    connection = NPGConnection()

    # Scan 
    devices = await connection.scan(timeout=10.0)

    if not devices:
        print("\nMake sure your NPG Lite is powered on and not connected to another app.")
        return

    # Display found devices 
    print(f"\n{'═' * 55}")
    print(f"  Found {len(devices)} NPG Lite device(s):")
    print(f"{'═' * 55}")
    for i, dev in enumerate(devices, 1):
        print(f"  [{i}] {dev}")
    print(f"{'═' * 55}")

    # Select device 
    if len(devices) == 1:
        selected = devices[0]
        print(f"\n→ Auto-selecting: {selected}")
    else:
        while True:
            try:
                idx = int(input(f"\nSelect device (1-{len(devices)}): "))
                if 1 <= idx <= len(devices):
                    selected = devices[idx - 1]
                    break
                print(f"  Enter a number between 1 and {len(devices)}")
            except ValueError:
                print("  Enter a valid number")

    # Connect 
    await connection.connect(selected)

    # Register callbacks 
    def on_data(samples, num_channels):
        for sample in samples:
            # Print every 50th sample (counter 0, 50, 100, ...) to avoid flooding
            if sample['counter'] % 50 == 0:
                ch_vals = " | ".join(
                    f"Ch{i+1}:{v:5d}" for i, v in enumerate(sample['channels'])
                )
                print(f"  [#{sample['counter']:3d}] {ch_vals}")

    def on_battery(percentage):
        print(f"Battery: {percentage}%")

    connection.on_data(on_data)
    connection.on_battery(on_battery)

    # Stream 
    await connection.start_streaming()
    print(f"\n  Press Ctrl+C to stop\n{'─' * 55}")

    try:
        while connection.is_streaming:
            await asyncio.sleep(5)
            print(f"  ── {connection.sample_count} samples received ──")
    except KeyboardInterrupt:
        print("\n")
    finally:
        total_samples = connection.sample_count
        await connection.disconnect()
        print(f"\n Total samples: {total_samples}")


if __name__ == "__main__":
    asyncio.run(_cli_main())
