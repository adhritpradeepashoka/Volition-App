"""
Volition - TFLite Training Script
===================================
Run this AFTER collecting training data for each mode.

Usage:
    python train_classifier.py pfc
    python train_classifier.py vc

Reads:  volition_training_pfc.csv  OR  volition_training_vc.csv
Writes: volition_model_pfc.tflite  OR  volition_model_vc.tflite

Requirements:
    pip install tensorflow pandas scikit-learn
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split

PFC_CLASSES = [
    "CH2_STRONG", "CH2_LIGHT",
    "CH3_STRONG", "CH3_LIGHT",
    "BOTH_STRONG", "BOTH_LIGHT",
    "EEG_CHEEK_TWITCH",
    "EEG_JAW_CLENCH",
    "EEG_FOCUS_HIGH",
    "EEG_ERROR",
    "REST",
]

VC_CLASSES = [
    "CH2_STRONG", "CH2_LIGHT",
    "CH3_STRONG", "CH3_LIGHT",
    "BOTH_STRONG", "BOTH_LIGHT",
    "EEG_BLINK",
    "EEG_DOUBLE_BLINK",
    "EEG_TRIPLE_BLINK",
    "EEG_FOCUS_HIGH",
    "EEG_ERROR",
    "REST",
]

MODE_CONFIG = {
    "pfc": {
        "csv":     "volition_training_pfc.csv",
        "model":   "volition_model_pfc.tflite",
        "stats":   "volition_model_pfc_stats.json",
        "classes": PFC_CLASSES,
    },
    "vc": {
        "csv":     "volition_training_vc.csv",
        "model":   "volition_model_vc.tflite",
        "stats":   "volition_model_vc_stats.json",
        "classes": VC_CLASSES,
    },
}


def load_and_prepare(csv_path: str, class_names: list):
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} samples from '{csv_path}'")
    print(f"Label distribution:\n{df['label'].value_counts()}\n")

    ch2_max   = float(df["ch2_emg"].max())   or 1000.0
    ch3_max   = float(df["ch3_emg"].max())   or 1000.0
    blink_max = float(df["eeg_blink"].max()) or 300.0
    jaw_max   = float(df["eeg_jaw"].max())   or 500.0

    # Rolling window must match TFLiteClassifier.WINDOW = 8
    X = np.column_stack([
        df["ch2_emg"]   / ch2_max,
        df["ch3_emg"]   / ch3_max,
        df["eeg_beta"]  / 100.0,
        df["eeg_blink"] / blink_max,
        df["eeg_jaw"]   / jaw_max,
        df["ch2_emg"]   / ch2_max,
        (df["ch2_emg"]  / ch2_max).rolling(8, min_periods=1).std().fillna(0),
        df["ch3_emg"]   / ch3_max,
        (df["ch3_emg"]  / ch3_max).rolling(8, min_periods=1).std().fillna(0),
    ]).astype(np.float32)

    le = LabelEncoder()
    le.classes_ = np.array(class_names)
    y = le.transform(df["label"])

    stats = {
        "ch2_max": ch2_max, "ch3_max": ch3_max,
        "blink_max": blink_max, "jaw_max": jaw_max,
        "classes": class_names,
    }
    return X, y, stats


def train(X, y, num_classes: int):
    import tensorflow as tf

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y)

    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(X.shape[1],)),
        tf.keras.layers.Dense(64, activation="relu"),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(32, activation="relu"),
        tf.keras.layers.Dense(num_classes, activation="softmax"),
    ])

    model.compile(
        optimizer="adam",
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    print("Training...")
    model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=40,
        batch_size=32,
        verbose=1,
    )

    val_loss, val_acc = model.evaluate(X_val, y_val, verbose=0)
    print(f"\nValidation accuracy: {val_acc:.1%}")
    return model


def export_tflite(model, output_path: str):
    import tensorflow as tf
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    tflite_model = converter.convert()
    with open(output_path, "wb") as f:
        f.write(tflite_model)
    size_kb = os.path.getsize(output_path) / 1024
    print(f"Saved TFLite model to '{output_path}' ({size_kb:.1f} KB)")


def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "pfc"
    if mode not in MODE_CONFIG:
        print(f"Usage: python train_classifier.py [pfc|vc]")
        return

    cfg = MODE_CONFIG[mode]
    print(f"\n═══ Training Volition model — {mode.upper()} mode ═══\n")

    if not os.path.exists(cfg["csv"]):
        print(f"ERROR: '{cfg['csv']}' not found.")
        print(f"Collect {mode.upper()} training data first using the Volition app.")
        return

    X, y, stats = load_and_prepare(cfg["csv"], cfg["classes"])
    model = train(X, y, len(cfg["classes"]))
    export_tflite(model, cfg["model"])

    with open(cfg["stats"], "w") as f:
        json.dump(stats, f, indent=2)
    print(f"Saved scale stats to '{cfg['stats']}'")
    print(f"\nDone. Switch to {mode.upper()} mode in Volition and click RELOAD MODEL.")


if __name__ == "__main__":
    main()
