# NPG Lite firmware (EEG/EMG + head-movement sensor)

`NPG-LITE-BLE-IMU-final/NPG-LITE-BLE-IMU-final.ino` is the sketch running on the NPG Lite used with Volition.
It is based on the public NPG-LITE-BLE firmware architecture from [Upside Down Labs](https://upsidedownlabs.tech) (GPL-3.0; see also [github.com/upsidedownlabs](https://github.com/upsidedownlabs)) and adds a motion-sensor stream.

**This is the one firmware to use for everything.** It streams EEG/EMG exactly like the standard NPG Lite firmware
(same Bluetooth name pattern, same data format), and also streams head movement if a motion sensor is plugged in.
If no sensor is attached it just carries on with EEG/EMG normally (the serial monitor prints "No compatible MPU detected").
So there is no need to choose between two firmwares: flash this one and use the app.

> The sensor is detected only at start-up, so plug it in **before** powering the NPG Lite on (or press reset after plugging it in).

## Hardware
- NPG Lite (ESP32-C6)
- An MPU6050 or MPU6500 motion sensor on the QWIIC / I2C port: **SDA = GPIO 22, SCL = GPIO 23**, address 0x68 or 0x69
  (the sketch accepts WHO_AM_I 0x68 = MPU6050 or 0x70 = MPU6500)

## What it sends over Bluetooth (BLE)
| Item | UUID |
|---|---|
| Service | `4fafc201-1fb5-459e-8fcc-c5c9c331914b` |
| EEG/EMG data | `beb5483e-36e1-4688-b7f5-ea07361b26a8` (500 Hz) |
| Control (START / STOP / WHORU / STATUS) | `0000ff01-0000-1000-8000-00805f9b34fb` |
| Battery | `f633d0ec-46b4-43c1-a39f-1ca06d0602e1` |
| Motion (IMU) | `8b5f4e5c-7d3a-4f91-ae2c-7e2f4c7f6a11` (100 Hz) |

Motion packet, 16 bytes, little-endian: `timestamp_ms (uint32)`, then `ax, ay, az, gx, gy, gz` (int16 each).
Ranges: accelerometer ±2 g, gyro ±250 °/s.

## How to flash it (Arduino IDE)
1. Install the Arduino IDE, then in Boards Manager install **esp32 by Espressif** (the board was built with core 3.3.10).
2. Library Manager: install **Adafruit NeoPixel**.
3. Open the `.ino` file, choose the ESP32-C6 board that matches your NPG Lite, plug it in over USB, and click Upload.
4. Always keep a backup of your board first: `esptool --chip esp32c6 read_flash 0 ALL backup.bin`
   (restore with `esptool --chip esp32c6 write_flash 0x0 backup.bin`).

Note: this sketch has not been recompiled in the cloud workspace; it matches the firmware that was dumped from a working board.
