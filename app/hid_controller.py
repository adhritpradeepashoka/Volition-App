# Volition — Copyright (c) 2026 Adhrit Pradeep. Licensed under GPL-3.0 (see LICENSE).
# Built on NPG-Lite-SNES by Upside Down Labs (GPL-3.0).
"""
Volition - HID Controller
==========================
Maps intent strings to keyboard keystrokes, mouse clicks, or
hotkey combos so Volition can control any software on the computer.

Requires: pip install pynput

Usage in Volition: enabled per-intent via the HID Mapping panel.
"""

import threading
from typing import Optional

try:
    from pynput.keyboard import Controller as KeyboardCtrl, Key
    from pynput.mouse import Controller as MouseCtrl, Button
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    print("[HID] pynput not installed. Run: pip install pynput")


# Human-readable action names shown in the HID mapping panel.
# Grouped for readability in the UI dropdown, but it's one flat list.
HID_ACTIONS = [
    "NONE",

    # --- Letters A-Z ---
    "KEY_A", "KEY_B", "KEY_C", "KEY_D", "KEY_E", "KEY_F", "KEY_G",
    "KEY_H", "KEY_I", "KEY_J", "KEY_K", "KEY_L", "KEY_M", "KEY_N",
    "KEY_O", "KEY_P", "KEY_Q", "KEY_R", "KEY_S", "KEY_T", "KEY_U",
    "KEY_V", "KEY_W", "KEY_X", "KEY_Y", "KEY_Z",

    # --- Numbers 0-9 (top row) ---
    "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4",
    "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9",

    # --- Punctuation / symbol keys ---
    "KEY_MINUS", "KEY_EQUALS", "KEY_LBRACKET", "KEY_RBRACKET",
    "KEY_BACKSLASH", "KEY_SEMICOLON", "KEY_QUOTE",
    "KEY_COMMA", "KEY_PERIOD", "KEY_SLASH", "KEY_GRAVE",

    # --- Navigation / editing cluster ---
    "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT",
    "KEY_ENTER", "KEY_SPACE", "KEY_ESCAPE", "KEY_TAB",
    "KEY_BACKSPACE", "KEY_DELETE", "KEY_INSERT",
    "KEY_HOME", "KEY_END", "KEY_PAGE_UP", "KEY_PAGE_DOWN",
    "KEY_CAPS_LOCK",

    # --- Modifier keys (standalone press/release, e.g. for hold-style use) ---
    "KEY_SHIFT", "KEY_CTRL", "KEY_ALT", "KEY_WIN",

    # --- Full function key row ---
    "KEY_F1", "KEY_F2", "KEY_F3", "KEY_F4", "KEY_F5", "KEY_F6",
    "KEY_F7", "KEY_F8", "KEY_F9", "KEY_F10", "KEY_F11", "KEY_F12",

    # --- Media / system keys ---
    "MEDIA_PLAY_PAUSE", "MEDIA_NEXT", "MEDIA_PREV", "MEDIA_STOP",
    "VOLUME_UP", "VOLUME_DOWN", "VOLUME_MUTE",

    # --- Mouse ---
    "MOUSE_LEFT_CLICK", "MOUSE_RIGHT_CLICK", "MOUSE_MIDDLE_CLICK",
    "MOUSE_SCROLL_UP", "MOUSE_SCROLL_DOWN",

    # --- Common hotkey combinations ---
    "HOTKEY_CTRL_A", "HOTKEY_CTRL_C", "HOTKEY_CTRL_V", "HOTKEY_CTRL_X",
    "HOTKEY_CTRL_Z", "HOTKEY_CTRL_Y", "HOTKEY_CTRL_S", "HOTKEY_CTRL_F",
    "HOTKEY_CTRL_N", "HOTKEY_CTRL_W", "HOTKEY_CTRL_T", "HOTKEY_CTRL_TAB",
    "HOTKEY_CTRL_SHIFT_TAB", "HOTKEY_CTRL_SHIFT_T",
    "HOTKEY_ALT_TAB", "HOTKEY_ALT_F4",
    "HOTKEY_WIN_D", "HOTKEY_WIN_E", "HOTKEY_WIN_L",
]


class HIDController:
    """
    Executes HID actions on the host computer.
    Each action fires in a daemon thread so it doesn't block
    the 30Hz signal processing loop.
    """

    def __init__(self):
        self.enabled = HAS_PYNPUT
        self._kb  = KeyboardCtrl() if HAS_PYNPUT else None
        self._ms  = MouseCtrl()    if HAS_PYNPUT else None
        self._cooldown: dict[str, float] = {}

        # Mapping of action name → callable
        self._dispatch: dict[str, callable] = {}
        if HAS_PYNPUT:
            self._build_dispatch()

        # Callback for status messages
        self.on_status = None   # fn(msg)

    def _build_dispatch(self):
        kb, ms = self._kb, self._ms
        K = Key

        def key_tap(k):
            return lambda: kb.tap(k)

        def hotkey(*keys):
            def _do():
                for k in keys:
                    kb.press(k)
                for k in reversed(keys):
                    kb.release(k)
            return _do

        d = {}

        # --- Letters A-Z — plain character taps ---
        for letter in "abcdefghijklmnopqrstuvwxyz":
            d[f"KEY_{letter.upper()}"] = key_tap(letter)

        # --- Numbers 0-9 ---
        for digit in "0123456789":
            d[f"KEY_{digit}"] = key_tap(digit)

        # --- Punctuation / symbol keys ---
        d["KEY_MINUS"]      = key_tap('-')
        d["KEY_EQUALS"]     = key_tap('=')
        d["KEY_LBRACKET"]   = key_tap('[')
        d["KEY_RBRACKET"]   = key_tap(']')
        d["KEY_BACKSLASH"]  = key_tap('\\')
        d["KEY_SEMICOLON"]  = key_tap(';')
        d["KEY_QUOTE"]      = key_tap("'")
        d["KEY_COMMA"]      = key_tap(',')
        d["KEY_PERIOD"]     = key_tap('.')
        d["KEY_SLASH"]      = key_tap('/')
        d["KEY_GRAVE"]      = key_tap('`')

        # --- Navigation / editing cluster ---
        d["KEY_UP"]         = key_tap(K.up)
        d["KEY_DOWN"]       = key_tap(K.down)
        d["KEY_LEFT"]       = key_tap(K.left)
        d["KEY_RIGHT"]      = key_tap(K.right)
        d["KEY_ENTER"]      = key_tap(K.enter)
        d["KEY_SPACE"]      = key_tap(K.space)
        d["KEY_ESCAPE"]     = key_tap(K.esc)
        d["KEY_TAB"]        = key_tap(K.tab)
        d["KEY_BACKSPACE"]  = key_tap(K.backspace)
        d["KEY_DELETE"]     = key_tap(K.delete)
        d["KEY_INSERT"]     = key_tap(K.insert)
        d["KEY_HOME"]       = key_tap(K.home)
        d["KEY_END"]        = key_tap(K.end)
        d["KEY_PAGE_UP"]    = key_tap(K.page_up)
        d["KEY_PAGE_DOWN"]  = key_tap(K.page_down)
        d["KEY_CAPS_LOCK"]  = key_tap(K.caps_lock)

        # --- Modifier keys — standalone tap (press+release), useful
        # for things like "hold shift while doing X" workflows where
        # the person pairs this with another mapped key in sequence ---
        d["KEY_SHIFT"] = key_tap(K.shift)
        d["KEY_CTRL"]  = key_tap(K.ctrl)
        d["KEY_ALT"]   = key_tap(K.alt)
        d["KEY_WIN"]   = key_tap(K.cmd)

        # --- Full function key row ---
        for n in range(1, 13):
            d[f"KEY_F{n}"] = key_tap(getattr(K, f"f{n}"))

        # --- Media / system keys ---
        d["MEDIA_PLAY_PAUSE"] = key_tap(K.media_play_pause)
        d["MEDIA_NEXT"]       = key_tap(K.media_next)
        d["MEDIA_PREV"]       = key_tap(K.media_previous)
        d["MEDIA_STOP"]       = key_tap(getattr(K, 'media_stop', K.media_play_pause))
        d["VOLUME_UP"]        = key_tap(K.media_volume_up)
        d["VOLUME_DOWN"]      = key_tap(K.media_volume_down)
        d["VOLUME_MUTE"]      = key_tap(K.media_volume_mute)

        # --- Mouse ---
        d["MOUSE_LEFT_CLICK"]   = lambda: ms.click(Button.left)
        d["MOUSE_RIGHT_CLICK"]  = lambda: ms.click(Button.right)
        d["MOUSE_MIDDLE_CLICK"] = lambda: ms.click(Button.middle)
        d["MOUSE_SCROLL_UP"]    = lambda: ms.scroll(0, 3)
        d["MOUSE_SCROLL_DOWN"]  = lambda: ms.scroll(0, -3)

        # --- Common hotkey combinations ---
        d["HOTKEY_CTRL_A"] = hotkey(K.ctrl, 'a')
        d["HOTKEY_CTRL_C"] = hotkey(K.ctrl, 'c')
        d["HOTKEY_CTRL_V"] = hotkey(K.ctrl, 'v')
        d["HOTKEY_CTRL_X"] = hotkey(K.ctrl, 'x')
        d["HOTKEY_CTRL_Z"] = hotkey(K.ctrl, 'z')
        d["HOTKEY_CTRL_Y"] = hotkey(K.ctrl, 'y')
        d["HOTKEY_CTRL_S"] = hotkey(K.ctrl, 's')
        d["HOTKEY_CTRL_F"] = hotkey(K.ctrl, 'f')
        d["HOTKEY_CTRL_N"] = hotkey(K.ctrl, 'n')
        d["HOTKEY_CTRL_W"] = hotkey(K.ctrl, 'w')
        d["HOTKEY_CTRL_T"] = hotkey(K.ctrl, 't')
        d["HOTKEY_CTRL_TAB"]        = hotkey(K.ctrl, K.tab)
        d["HOTKEY_CTRL_SHIFT_TAB"]  = hotkey(K.ctrl, K.shift, K.tab)
        d["HOTKEY_CTRL_SHIFT_T"]    = hotkey(K.ctrl, K.shift, 't')
        d["HOTKEY_ALT_TAB"] = hotkey(K.alt, K.tab)
        d["HOTKEY_ALT_F4"]  = hotkey(K.alt, K.f4)
        d["HOTKEY_WIN_D"]   = hotkey(K.cmd, 'd')
        d["HOTKEY_WIN_E"]   = hotkey(K.cmd, 'e')
        d["HOTKEY_WIN_L"]   = hotkey(K.cmd, 'l')

        self._dispatch = d

    def execute(self, action: str):
        """Fire a HID action in a daemon thread."""
        if not self.enabled or action == "NONE" or not action:
            return

        fn = self._dispatch.get(action)
        if fn is None:
            return

        def _run():
            try:
                fn()
                if self.on_status:
                    self.on_status(f"HID: {action}")
            except Exception as e:
                if self.on_status:
                    self.on_status(f"HID error ({action}): {e}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
