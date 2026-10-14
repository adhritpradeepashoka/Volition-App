# Volition

**Adaptive biosignal (EEG/EMG) assistive-control platform for the NPG Lite board.**

Volition learns *your* resting signal level and turns deliberate gestures — a muscle flex, a jaw clench, a cheek twitch, a blink — into computer control. An optional motion sensor (IMU) adds head-movement control of smart devices. It runs on your own computer, offline.

> Prototype for research and demonstration. Not a medical device. No clinical validation has been done.

## What's in this repo

| Folder / file | What it is |
|---|---|
| `INSTALL AND RUN VOLITION.bat` | **Double-click this to install and start Volition** |
| `app/` | The Volition program itself |
| `demonstration-videos/` | Videos of Volition working (start with `01`) |
| `presentations-and-essays/` | Pitch deck, essay and technical document |

---

# How to install Volition — every step

This works on **Windows 10 or 11 only**. You do not need to know how to code. Just follow the steps in order.

**You need:**
- A Windows computer with Bluetooth
- An internet connection (only for the first setup)
- An **NPG Lite** board from Upside Down Labs, charged

## STEP 1 — Install Python (once)

Python is the free program that Volition runs on.

1. Open your web browser and go to **https://www.python.org/downloads/windows/**
2. Scroll down to the list of releases and find **Python 3.13** (any number like 3.13.x is fine).
3. Click **Windows installer (64-bit)**. A file downloads.
4. Double-click the downloaded file to open it.
5. **VERY IMPORTANT:** at the bottom of the first window, tick the box **"Add python.exe to PATH"**.
6. Click **Install Now**.
7. When it says "Setup was successful", click **Close**.

## STEP 2 — Download Volition (once)

1. Go to **https://github.com/adhritpradeepashoka/Volition-App**
2. Click the green **Code** button.
3. Click **Download ZIP**. A file called `Volition-App-main.zip` downloads. (It is large, because it includes the videos.)
4. Open your **Downloads** folder.
5. **Right-click** `Volition-App-main.zip` and click **Extract All...**
6. Click **Extract**. A normal folder called `Volition-App-main` appears.

## STEP 3 — Start Volition

1. Open the new `Volition-App-main` folder.
2. Double-click **`INSTALL AND RUN VOLITION`** (the file ending in `.bat`).
3. If a blue box says **"Windows protected your PC"**: click **More info**, then click **Run anyway**. This is normal for files downloaded from the internet.
4. A black window opens and starts downloading what Volition needs. **Wait.** The first time can take 5–10 minutes. Do not close it.
5. When it finishes, the Volition window opens by itself.

**Next time:** just double-click `INSTALL AND RUN VOLITION` again. It starts in seconds, because the setup is already done.

## STEP 4 — Connect your NPG Lite

1. Make sure Bluetooth is **on** in Windows (click the Bluetooth icon in the bottom-right, or open Settings → Bluetooth).
2. Switch on your NPG Lite. Make sure **no other app or phone is connected to it**.
3. Put the electrodes on as shown in the pictures in the `app/electrode-placement` folder.
4. In Volition, click **CONNECT NPG LITE**.
5. Wait for the scan, then choose the device whose name starts with **NPG**.
6. **Stay still and relaxed.** Volition is learning your resting signal. Wait until the log in the window says **"Calibrated and ready"**.
7. Now try a gesture, such as a clench. The bars on the screen move when Volition sees it.

Volition runs without a trained model, using automatic thresholds that adapt to you. You do not need to train anything to start.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| **"Python is not installed"** in the black window | Do STEP 1 again. Make sure you tick **"Add python.exe to PATH"** before clicking Install Now. Then double-click the `.bat` file again. |
| **"Windows protected your PC"** | Click **More info**, then **Run anyway**. |
| The black window closes immediately | Right-click the `.bat` file, click **Show more options → Open** if you see it, or tell us what happened by opening an Issue on this page. |
| The download fails | Check your internet connection and double-click the `.bat` file again. It continues where it stopped. |
| **No NPG device found** | Switch the NPG Lite off and on, check that it is charged, check that Bluetooth is on, make sure no other app is connected to it, then scan again. |
| **Signal bars are flat, or the log says "loose electrode" / "no signal"** | Re-seat the electrodes and press them firmly on clean skin. |
| Nothing works at all | Close everything, delete the `Volition-App-main` folder, and start again from STEP 2. |

---

## Optional extras

**Train your own model (advanced).** Models are personal to one body, so none is included. Open PowerShell in the `Volition-App-main` folder and run:
```powershell
.venv\Scripts\activate
pip install -r requirements-extras.txt
python app\train_classifier.py
```
Record labelled gestures first using the **data capture** panel inside Volition.

**Make a standalone .exe (advanced).** Double-click `app\Build Volition App.bat` after finishing STEP 3. The finished program appears in `app\dist\`.

**Extra hardware.**
- *IMU / head-movement control:* needs the IMU-enabled NPG Lite firmware. Without it, Volition still works for EEG/EMG.
- *Smart plugs:* Volition can control TP-Link Kasa devices on your home network.
- *Robotic arm:* see `app/README_VOLITION.md`.

## Your data stays yours

Nothing personal is included in this repo. Calibration and training data are saved on your own computer, next to the app, and are never uploaded.

## Credits and license

Built on [NPG-Lite-SNES](https://github.com/upsidedownlabs/NPG-Lite-SNES) and the NPG Lite hardware by [Upside Down Labs](https://upsidedownlabs.tech). Released under **GPL-3.0** (see `LICENSE`), the same license as the original.
