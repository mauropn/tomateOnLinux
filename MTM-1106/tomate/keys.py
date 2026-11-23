"""Tabelas de teclas: nomes legíveis ↔ keycodes Linux, e HID usage → keycode Linux."""
from __future__ import annotations

from . import kernel as K

# Keycodes Linux (linux/input-event-codes.h)
_LETTERS = {c: code for c, code in zip(
    "qwertyuiop", range(16, 26))} | {c: code for c, code in zip(
    "asdfghjkl", range(30, 39))} | {c: code for c, code in zip("zxcvbnm", range(44, 51))}

KEYCODES: dict[str, int] = {
    **{c.upper(): v for c, v in _LETTERS.items()},
    **{str(d): 2 + (d - 1) for d in range(1, 10)}, "0": 11,
    "Esc": 1, "Minus": 12, "Equal": 13, "Backspace": 14, "Tab": 15,
    "BracketLeft": 26, "BracketRight": 27, "Enter": 28,
    "Ctrl": 29, "Semicolon": 39, "Apostrophe": 40, "Grave": 41, "Shift": 42,
    "Backslash": 43, "Comma": 51, "Period": 52, "Slash": 53, "ShiftR": 54,
    "Alt": 56, "Space": 57, "CapsLock": 58,
    **{f"F{i}": 58 + i for i in range(1, 11)}, "F11": 87, "F12": 88,
    "CtrlR": 97, "AltGr": 100, "Home": 102, "Up": 103, "PageUp": 104, "Left": 105,
    "Right": 106, "End": 107, "Down": 108, "PageDown": 109, "Insert": 110, "Delete": 111,
    "Super": 125, "Menu": 139,
}

# Ações de mouse que podem ser associadas a botões
MOUSE_ACTIONS = {
    "MouseLeft": K.BTN_LEFT,
    "MouseRight": K.BTN_RIGHT,
    "MouseMiddle": K.BTN_MIDDLE,
}
WHEEL_ACTIONS = {"WheelUp": 1, "WheelDown": -1}

# HID Keyboard usage → keycode Linux (subconjunto suficiente para repassar teclas).
HID_TO_LINUX: dict[int, int] = {
    **{0x04 + i: _LETTERS[c] for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{0x1E + i: 2 + i for i in range(9)}, 0x27: 11,
    0x28: 28, 0x29: 1, 0x2A: 14, 0x2B: 15, 0x2C: 57, 0x2D: 12, 0x2E: 13,
    0x2F: 26, 0x30: 27, 0x31: 43, 0x33: 39, 0x34: 40, 0x35: 41, 0x36: 51,
    0x37: 52, 0x38: 53, 0x39: 58,
    **{0x3A + i: 59 + i for i in range(10)}, 0x44: 87, 0x45: 88,
    0x49: 110, 0x4A: 102, 0x4B: 104, 0x4C: 111, 0x4D: 107, 0x4E: 109,
    0x4F: 106, 0x50: 105, 0x51: 108, 0x52: 103,
}
# HID Consumer usage (report 4 da mesa: ícones impressos) → keycode Linux, como no hid-input.
HID_CONSUMER_TO_LINUX: dict[int, int] = {
    0xB5: 163,   # Próxima faixa → KEY_NEXTSONG
    0xB6: 165,   # Faixa anterior → KEY_PREVIOUSSONG
    0xB7: 166,   # Parar → KEY_STOPCD
    0xCD: 164,   # Play/Pause → KEY_PLAYPAUSE
    0xE2: 113,   # Mudo → KEY_MUTE
    0xE9: 115,   # Volume + → KEY_VOLUMEUP
    0xEA: 114,   # Volume − → KEY_VOLUMEDOWN
    0x183: 226,  # Player de mídia → KEY_MEDIA
    0x18A: 155,  # E-mail → KEY_MAIL
    0x192: 140,  # Calculadora → KEY_CALC
    0x194: 144,  # Arquivos → KEY_FILE
    0x196: 150,  # Navegador → KEY_WWW
    0x221: 217,  # Pesquisar → KEY_SEARCH
    0x223: 172,  # Página inicial → KEY_HOMEPAGE
    0x224: 158,  # Voltar → KEY_BACK
    0x225: 159,  # Avançar → KEY_FORWARD
    0x227: 173,  # Atualizar → KEY_REFRESH
    0x22A: 156,  # Favoritos → KEY_BOOKMARKS
}
# Bits do byte de modificadores HID → keycode Linux
HID_MODIFIERS = [29, 42, 56, 125, 97, 54, 100, 126]


def hid_report_to_keycodes(mod: int, keys: tuple[int, ...]) -> list[int]:
    out = [HID_MODIFIERS[i] for i in range(8) if mod & (1 << i)]
    out += [HID_TO_LINUX[k] for k in keys if k in HID_TO_LINUX]
    return out


def parse_shortcut(text: str) -> list[int]:
    """'Ctrl+Shift+Z' → [29, 42, 44]. Levanta ValueError para nomes desconhecidos."""
    lower = {k.lower(): v for k, v in KEYCODES.items()}
    out = []
    for part in [p.strip() for p in text.split("+") if p.strip()]:
        code = lower.get(part.lower())
        if code is None:
            raise ValueError(f"tecla desconhecida: {part!r}")
        out.append(code)
    if not out:
        raise ValueError("atalho vazio")
    return out


def all_keyboard_codes() -> list[int]:
    return sorted(set(KEYCODES.values()) | set(HID_TO_LINUX.values()) | set(HID_MODIFIERS)
                  | set(HID_CONSUMER_TO_LINUX.values()))
