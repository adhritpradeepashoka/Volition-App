# Volition

**Adaptive biosignal (EEG/EMG) assistive-control platform for the NPG Lite board.**

Volition learns *your* resting signal level and turns deliberate gestures — a muscle flex, a jaw clench, a cheek twitch, a blink — into computer control. An optional IMU adds head-orientation control of smart devices. It runs offline on your own computer.

> Prototype for research and demonstration. Not a medical device; no clinical validation has been done.

## What's in this repo

| Folder | Contents |
|---|---|
| `app/` | The Volition application (Python / PySide6) |
| `presentations-and-essays/` | Pitch presentation and supporting technical document |
| `demonstration-videos/` | Recorded demos |

## Install (Windows 10/11)

You need:
- A PC with **Bluetooth Low Energy** and **Windows 10 or 11**
- **64-bit Python 3.11–3.13** from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH* in the installer)
- An **NPG Lite** from Upside Down Labs, powered on and not connected to another app

Open **PowerShell** and run:

```powershell
git clone https://github.com/adhritpradeepashoka/Volition-App.git
cd Volition-App
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app\volition_demo_main.py
```

No git? On the repo page click **Code → Download ZIP**, unzip it, open PowerShell in the unzipped folder, and run the commands from `python -m venv .venv` down.

If PowerShell refuses to activate the venv, run this once and try again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## First run

1. Switch the NPG Lite on and click scan in the app. Pick the device whose name starts with `NPG`.
2. Place electrodes as shown in `app/electrode-placement/`.
3. Hold still while Volition calibrates to your resting signal, then try your gestures.

There is no pre-trained model in this repo because models are specific to one person's body. Until you train your own, Volition runs in **adaptive-threshold mode**, which needs no model. Your calibration and training data are saved next to the app, are never uploaded, and are git-ignored.

## Train your own model (optional)

```powershell
pip install -r requirements-extras.txt
```
Record labelled gestures with the app's data-capture panel, then run `python app\train_classifier.py`. The resulting `volition_model_*.tflite` file is picked up on the next launch.

## Build a standalone .exe (optional)

Double-click `app\Build Volition App.bat` (it expects the `.venv` created above, at the repo root). The finished app appears in `app\dist\`.

## Optional hardware

- **IMU (spatial control):** needs the IMU-enabled NPG Lite firmware. Without it the app still works for EEG/EMG; IMU features stay off.
- **Smart plugs:** `python-kasa` is used for Kasa smart devices on your local network.
- **Robotic arm:** see `app/README_VOLITION.md` and `app/arm/`.

## Credits and license

Built on [NPG-Lite-SNES](https://github.com/upsidedownlabs/NPG-Lite-SNES) and the NPG Lite hardware by [Upside Down Labs](https://upsidedownlabs.tech). Released under **GPL-3.0** (see `LICENSE`), the same license as the original.
