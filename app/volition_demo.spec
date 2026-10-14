# volition_demo.spec
# ====================
# Builds "Volition App.exe" — a standalone, single-file, windowed
# executable for the simplified demo build (volition_demo_main.py).
#
# MUST BE RUN ON WINDOWS. PyInstaller produces platform-specific
# binaries — this cannot be built from Linux/Mac and used on Windows.
#
# Usage (from inside the activated .venv, in this folder):
#     pyinstaller volition_demo.spec --clean
#
# Output appears in: dist/Volition App.exe
#
# First build will take several minutes (TensorFlow Lite is the
# largest dependency by far). Subsequent builds are faster.

import os
from pathlib import Path

block_cipher = None

# ── Detect which TFLite backend is installed ─────────────────────────────
# tflite_classifier.py tries tflite_runtime first, falls back to the
# full tensorflow.lite. We just need to make sure hiddenimports covers
# the actual interpreter module — the pyinstaller-hooks-contrib package
# already ships a proper hook-tensorflow.py that handles collecting
# TensorFlow's own data files and binaries automatically (confirmed:
# it runs during Analysis, well before EXE build). Manually calling
# collect_all('tensorflow') on top of that double-collects and produces
# malformed TOC entries that crash PyInstaller's final packaging step —
# so we deliberately do NOT do that here.
tf_hidden_imports = []

try:
    import tflite_runtime
    tf_hidden_imports.append('tflite_runtime.interpreter')
    print(">>> Detected tflite_runtime — using lightweight TFLite backend")
except ImportError:
    try:
        import tensorflow
        tf_hidden_imports += [
            'tensorflow.lite.python.interpreter',
            'tensorflow.lite',
        ]
        print(">>> Detected full tensorflow — using tensorflow.lite backend "
              "(this will make the exe noticeably larger, ~300-600MB). "
              "Relying on pyinstaller-hooks-contrib's built-in tensorflow "
              "hook for data/binary collection.")
    except ImportError:
        print(">>> WARNING: Neither tflite_runtime nor tensorflow found. "
              "TFLite features will not work in the built exe.")

# ── Data files to bundle ──────────────────────────────────────────────────
# Anything the app reads from disk at runtime (not imported as Python
# code) needs to be listed here explicitly, or it won't exist inside
# the bundled exe.
datas = [
    ('Algorithms', 'Algorithms'),
    ('filters', 'filters'),
    ('icons', 'icons'),
]

# Bundle a pre-trained model + its stats file if present, so the demo
# exe works immediately without requiring a fresh training pass.
for model_file in Path('.').glob('volition_model_*.tflite'):
    datas.append((str(model_file), '.'))
for stats_file in Path('.').glob('volition_model_*_stats.json'):
    datas.append((str(stats_file), '.'))
# Bundle any training data already captured during development too, so
# the packaged exe can retrain immediately without needing a fresh
# capture pass. See _TrainThread in volition_demo_main.py for the
# matching writable-dir-first / bundled-fallback resolution logic.
for csv_file in Path('.').glob('volition_training_*.csv'):
    datas.append((str(csv_file), '.'))

# train_classifier.py is now imported directly as a Python module by
# volition_demo_main.py (see _TrainThread) rather than invoked as a
# subprocess script, so PyInstaller's normal import analysis picks it
# up automatically — no explicit datas entry needed.

# ── Hidden imports ──────────────────────────────────────────────────────
# Modules PyInstaller's static analysis can miss: bleak's WinRT backend
# loads platform modules dynamically, and PySide6 sometimes needs its
# submodules spelled out explicitly.
hiddenimports = [
    'bleak.backends.winrt',
    'bleak.backends.winrt.client',
    'bleak.backends.winrt.scanner',
    'winrt.windows.devices.bluetooth',
    'winrt.windows.devices.bluetooth.advertisement',
    'winrt.windows.devices.bluetooth.genericattributeprofile',
    'winrt.windows.devices.enumeration',
    'winrt.windows.devices.radios',
    'winrt.windows.foundation',
    'winrt.windows.foundation.collections',
    'winrt.windows.storage.streams',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    # pynput's Windows backend — used by hid_controller.py for
    # keyboard/mouse output. PyInstaller's static analysis can miss
    # this since pynput selects its backend dynamically at import time
    # based on the OS, which looks like a conditional/optional import
    # rather than a hard dependency.
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
] + tf_hidden_imports

a = Analysis(
    ['volition_demo_main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Explicitly exclude the full-app-only dependency this demo
        # build never imports
        'vgamepad',
        # Genuinely unused by both the live app and train_classifier.py
        # (which IS imported in-process now — pandas and scikit-learn
        # are deliberately NOT excluded, since training needs them for
        # real). Kept conservative here: only excluding packages with
        # no code path that could plausibly need them, since getting
        # this wrong breaks the exe in ways that are hard to debug
        # without being able to test-build locally.
        'lxml',
        'matplotlib',
        'torch',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── Defensive TOC sanitization ────────────────────────────────────────────
# The exact same "ValueError: not enough values to unpack (expected 3,
# got 2)" crash persisted even after removing the manual
# collect_all('tensorflow') merge — which means one of the AUTOMATIC
# hooks that runs during Analysis() above (most likely hook-tensorflow
# or a Keras-related hook shipped by pyinstaller-hooks-contrib) is
# itself producing a malformed 2-element entry somewhere in a.datas,
# a.binaries, or a.zipfiles. This is a known class of bug in some
# pyinstaller-hooks-contrib + tensorflow/keras version combinations.
#
# Rather than trying to guess which specific hook is at fault without
# being able to test-build locally, this pass scans every TOC list PyInstaller
# is about to consume and repairs or drops anything that isn't a proper
# (dest_name, src_name, typecode) 3-tuple, so the build can proceed
# regardless of which hook introduced the bad entry.
def _sanitize_toc(toc, toc_name):
    if toc is None:
        return toc
    fixed = []
    dropped = 0
    for entry in toc:
        if isinstance(entry, (tuple, list)):
            if len(entry) == 3:
                fixed.append(tuple(entry))
            elif len(entry) == 2:
                # Missing typecode — 'DATA' is the safe default for
                # anything that isn't specifically a binary/extension
                dest_name, src_name = entry
                fixed.append((dest_name, src_name, 'DATA'))
            else:
                dropped += 1
                continue
        else:
            dropped += 1
            continue
    if dropped:
        print(f">>> Sanitized {toc_name}: dropped {dropped} malformed entr"
              f"{'y' if dropped == 1 else 'ies'} that would have crashed the build")
    return fixed

a.datas     = _sanitize_toc(a.datas, "a.datas")
a.binaries  = _sanitize_toc(a.binaries, "a.binaries")
a.zipfiles  = _sanitize_toc(a.zipfiles, "a.zipfiles")

# NOTE: deliberately NOT manually merging collect_all('tensorflow')
# results here. pyinstaller-hooks-contrib's own hook-tensorflow.py
# already ran during Analysis() above and collected everything needed —
# doing it again here was the exact cause of the
# "ValueError: not enough values to unpack (expected 3, got 2)" crash
# during EXE build (malformed/duplicated TOC entries from double
# collection). If TFLite features don't work in the built exe, that
# points to the automatic hook being incomplete for your TF version —
# tell me the exact tensorflow version (`pip show tensorflow`) and
# we'll add back a properly-guarded, deduplicated merge if needed.

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Volition App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX compression + TensorFlow DLLs are known to
                         # conflict on Windows — leave off for reliability
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # windowed — no console box, ever
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='volition_icon.ico' if os.path.exists('volition_icon.ico')
         else ('icons/app_icon.ico' if os.path.exists('icons/app_icon.ico') else None),
)
