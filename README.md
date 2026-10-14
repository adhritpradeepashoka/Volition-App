# Volition

**Adaptive biosignal (EEG/EMG) assistive-control platform for the NPG Lite board.**

Volition learns *your* resting signal level and turns deliberate gestures — a muscle flex, a jaw clench, a cheek twitch, a blink — into computer control. Built in: a head-controlled **gyro keyboard** and head-pointing control of smart devices, both driven by an optional motion sensor (IMU). It runs on your own computer, offline.

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
2. Scroll down to the list of releases and find **Python 3.13** (any number like 3.13.x is fine). **Do not pick 3.14 or anything newer, and do not pick 3.10 or older.** Volition has only been built and tested on 3.13.
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

> **Careful — Windows often makes a folder inside a folder.** If you open `Volition-App-main` and see only *another* `Volition-App-main` folder, open that one too. Keep going until you see the files `README.md` and `INSTALL AND RUN VOLITION`, and the folders `app`, `demonstration-videos` and `presentations-and-essays`. **That is the right folder.**

## STEP 3 — Start Volition

1. Open the right folder from STEP 2 (the one that contains `app`, `README.md` and the installer file).
2. Double-click **`INSTALL AND RUN VOLITION`** (the file ending in `.bat`). **Leave this file where it is, next to the `app` folder. Do not drag it out of the folder or move it elsewhere.** It needs the `app` folder beside it.
3. If a blue box says **"Windows protected your PC"**: click **More info**, then click **Run anyway**. This is normal for files downloaded from the internet.
4. A black window opens and starts downloading what Volition needs. You will see lots of scrolling text and progress bars. **That is normal. Wait.** The first time can take 5–10 minutes. Do not close it.
5. When it finishes, the Volition window opens by itself.

**Next time:** just double-click `INSTALL AND RUN VOLITION` again. It starts in seconds, because the setup is already done.

**Want an icon on your desktop?** Right-click `INSTALL AND RUN VOLITION`. On Windows 11 click **Show more options** first. Then click **Send to → Desktop (create shortcut)**. Use the shortcut to start Volition. Leave the original file where it is, because the shortcut points to it.

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

## Ignore the other files

You will see other `.bat` files and many other files inside the `app` folder. **Ignore them.** Only `INSTALL AND RUN VOLITION` is needed to use Volition.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| **"Your Python is the wrong version"** in the black window | Install Python 3.13 (64-bit) as in STEP 1. You can keep your other Python. Then double-click the `.bat` file again. |
| **"Python is not installed"** in the black window | Do STEP 1 again. Make sure you tick **"Add python.exe to PATH"** before clicking Install Now. Then double-click the `.bat` file again. |
| **"Windows protected your PC"** | Click **More info**, then **Run anyway**. |
| The black window closes immediately | Open Start, type **cmd**, and press Enter. Then drag the `.bat` file into that window and press Enter. The window now stays open so you can read the error. If it still doesn't make sense, open an **Issue** on this GitHub page and paste what it says. |
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
- *Gyro keyboard and head-pointing control:* these are already inside the app (the **GYRO KEYBOARD** tab, and the smart-device controls). They are steered by head movement, so they need a motion sensor wired to the NPG Lite (the code is written for an MPU6500) and NPG Lite firmware that streams its readings (the firmware is in the [`firmware/`](firmware/) folder, with wiring and flashing steps). Without that hardware the app still works for EEG/EMG; the head-movement features simply have no motion data.
- *Smart plugs:* Volition can control TP-Link Kasa devices on your home network.
- *Robotic arm:* see `app/README_VOLITION.md`.

## Your data stays yours

Nothing personal is included in this repo. Calibration and training data are saved on your own computer, next to the app, and are never uploaded.

## Credits and license

Built (Partially) on [NPG-Lite-SNES](https://github.com/upsidedownlabs/NPG-Lite-SNES) and the NPG Lite hardware by [Upside Down Labs](https://upsidedownlabs.tech). Released under **GPL-3.0** (see `LICENSE`), the same license as the original.

## Author and credits

Volition was created by **Adhrit Pradeep**. Copyright (c) 2026 Adhrit Pradeep.

It is built on top of the open-source NPG-Lite-SNES / NPG-LITE-BLE work by [Upside Down Labs](https://upsidedownlabs.tech) (GPL-3.0). Because of that, Volition is also released under the GNU GPL v3 (see `LICENSE`): you may use, change and share it, as long as you keep it open under the same license and keep these credits.
