# ⬡ VOLITION
### Adaptive Multimodal Biosignal Control System
**Vivo Ignite 4th Edition — SoftTech Innovations / Robotics & AR/VR**

---

## What Is Volition?

Volition reads your body's electrical signals (EMG, EOG, EEG) wirelessly via the NPG Lite and uses them to control a 3-axis robotic arm — with **no manual calibration required**. The system learns your personal signal thresholds automatically.

Built on top of [NPG-Lite-SNES](https://github.com/upsidedownlabs/NPG-Lite-SNES) by Upside Down Labs (GPL-3.0).

---

## Architecture

```
NPG Lite (ESP32-C6)
  3-channel BioAmp (EMG / EOG / EEG)
  ↓  BLE broadcast
  
volition_main.py
  ↓  channel_processor.py  (UDL — unchanged)
     Filters: notch, bandpass, envelope detection
  ↓  intent_engine.py  (NEW — Volition)
     Adaptive threshold learning
     Multi-signal fusion
     Data capture for TFLite training
  ↓  arm_controller.py  (NEW — Volition)
     Serial commands to Arduino
  ↓
volition_arm.ino  (Arduino on the servo arm)
  3x servos: base, shoulder, elbow
  1x gripper servo
```

---

## Hardware Required

| Component | Cost |
|---|---|
| NPG Lite (Upside Down Labs) | Owned |
| Gel electrodes | ~₹200 |
| 3-axis servo arm kit | ~₹800 |
| Arduino UNO (for arm) | ~₹500 |
| MPU6050 via QWIIC (optional) | ~₹150 |
| **Total additional spend** | **~₹1,650** |

---

## Setup

### 1. Clone and install

```bash
# Clone the original NPG-Lite-SNES repo (contains all UDL dependencies)
git clone https://github.com/upsidedownlabs/NPG-Lite-SNES.git
cd NPG-Lite-SNES

# Install dependencies
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
pip install pyserial           # Additional for arm serial
```

### 2. Copy Volition files into the repo

Copy these files into the cloned NPG-Lite-SNES folder:
- `volition_main.py`
- `intent_engine.py`
- `arm/arm_controller.py`
- `arm/volition_arm.ino`

### 3. Upload arm firmware

Open `arm/volition_arm.ino` in Arduino IDE.
Connect arm Arduino via USB and upload.

Wiring:
- Base servo     → Pin 9
- Shoulder servo → Pin 10
- Elbow servo    → Pin 11
- Gripper servo  → Pin 6

### 4. Run Volition

```bash
python volition_main.py
```

---

## Signal Mapping (Default)

| Signal | Gesture | Arm Action |
|---|---|---|
| EMG Ch1 | Strong clench | Grip CLOSE |
| EMG Ch1 | Light clench | Grip OPEN |
| EOG Ch2 | Look left | Rotate base left |
| EOG Ch2 | Look right | Rotate base right |
| EEG Ch3 | Blink | Extend elbow |
| EEG Ch3 | Focus spike | Retract elbow |

---

## Training Your Own TFLite Model (Month 2)

1. Use the **DATA CAPTURE** panel in Volition to record labelled signal samples
2. Gestures are saved to `volition_training_data.csv`
3. Run `train_classifier.py` (coming in Month 2) to train and export `.tflite`
4. Drop the `.tflite` file into the Volition folder — it will auto-load

---

## File Structure

```
NPG-Lite-SNES/              ← Clone UDL repo here
├── channel_processor.py    ← UDL (unchanged)
├── ble_manager.py          ← UDL (unchanged)
├── npg_protocol.py         ← UDL (unchanged)
├── filters/                ← UDL (unchanged)
├── Algorithms/             ← UDL (unchanged)
│
├── volition_main.py        ← Volition entry point (replaces main.py)
├── intent_engine.py        ← Volition adaptive classifier
├── arm/
│   ├── arm_controller.py   ← Volition serial arm control
│   └── volition_arm.ino    ← Arduino firmware for the arm
└── README_VOLITION.md
```

---

## License

Volition modifications: GPL-3.0 (same as NPG-Lite-SNES base)
Original NPG-Lite-SNES: Copyright © 2026 Upside Down Labs
