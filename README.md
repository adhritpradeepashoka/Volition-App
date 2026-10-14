# Volition

Adaptive biosignal (EEG/EMG) assistive-control platform for the NPG Lite board. Volition learns your own signal baseline and turns deliberate gestures — a flex, a jaw clench, a cheek twitch, a blink — into computer control, with IMU-assisted spatial control for smart devices.

Prototype, not a medical device. No clinical validation has been done.

Built on [NPG-Lite-SNES](https://github.com/upsidedownlabs) by Upside Down Labs (GPL-3.0). See `README_VOLITION.md` for Volition-specific notes.

## Run it

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python volition_demo_main.py
```

On first run there is no model, so Volition runs in adaptive-threshold mode. It calibrates to you at startup.

## Your own data

Nothing personal is included in this repo. Training CSVs, trained models (`volition_model_*.tflite`) and logs are generated next to the app as you use it and are git-ignored. To train your own classifier, record labelled data in the app and run `train_classifier.py`.

## License

GPL-3.0 (see `LICENSE`).
