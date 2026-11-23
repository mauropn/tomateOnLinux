"""Dispositivos virtuais (uinput): uma mesa de caneta e um teclado/mouse para atalhos."""
from __future__ import annotations

from . import kernel as K
from . import keys
from .mapping import VIRTUAL_MAX
from .protocol import RAW_PRESSURE_MAX, TILT_MAX

PEN_NAME = "TOMATE MTM-1106 Pen (tomate)"
KBD_NAME = "TOMATE MTM-1106 Buttons (tomate)"


class VirtualPen:
    def __init__(self) -> None:
        self.dev = K.UInputDevice(
            PEN_NAME,
            keys=[K.BTN_TOOL_PEN, K.BTN_TOUCH, K.BTN_STYLUS, K.BTN_STYLUS2],
            abs_axes={
                K.ABS_X: (0, VIRTUAL_MAX, 100),
                K.ABS_Y: (0, VIRTUAL_MAX, 100),
                K.ABS_PRESSURE: (0, RAW_PRESSURE_MAX, 0),
                K.ABS_TILT_X: (-TILT_MAX, TILT_MAX, 0),
                K.ABS_TILT_Y: (-TILT_MAX, TILT_MAX, 0),
            },
            props=[K.INPUT_PROP_POINTER],
            product=0x7011,
        )
        self.state = {"in_range": False, "touch": False, "stylus": False, "stylus2": False}

    def update(self, x: int, y: int, pressure: int, in_range: bool, touch: bool,
               stylus: bool, stylus2: bool, tilt_x: int = 0, tilt_y: int = 0) -> None:
        d, st = self.dev, self.state
        if in_range and not st["in_range"]:
            d.emit(K.EV_ABS, K.ABS_X, x)
            d.emit(K.EV_ABS, K.ABS_Y, y)
            d.emit(K.EV_KEY, K.BTN_TOOL_PEN, 1)
        if not in_range:
            touch = stylus = stylus2 = False
            pressure = 0
        d.emit(K.EV_ABS, K.ABS_X, x)
        d.emit(K.EV_ABS, K.ABS_Y, y)
        d.emit(K.EV_ABS, K.ABS_PRESSURE, pressure)
        d.emit(K.EV_ABS, K.ABS_TILT_X, tilt_x)
        d.emit(K.EV_ABS, K.ABS_TILT_Y, tilt_y)
        for name, code, val in (("touch", K.BTN_TOUCH, touch), ("stylus", K.BTN_STYLUS, stylus),
                                ("stylus2", K.BTN_STYLUS2, stylus2)):
            if st[name] != val:
                d.emit(K.EV_KEY, code, int(val))
                st[name] = val
        if not in_range and st["in_range"]:
            d.emit(K.EV_KEY, K.BTN_TOOL_PEN, 0)
        st["in_range"] = in_range
        d.emit(K.EV_MSC, K.MSC_TIMESTAMP, K.monotonic_us())
        d.syn()

    def close(self) -> None:
        self.dev.close()


class VirtualKeyboard:
    def __init__(self) -> None:
        self.dev = K.UInputDevice(
            KBD_NAME,
            keys=keys.all_keyboard_codes() + list(keys.MOUSE_ACTIONS.values()),
            rels=[K.REL_WHEEL, K.REL_HWHEEL],
            product=0x7012,
        )

    def press(self, codes: list[int]) -> None:
        for c in codes:
            self.dev.emit(K.EV_KEY, c, 1)
        self.dev.syn()

    def release(self, codes: list[int]) -> None:
        for c in reversed(codes):
            self.dev.emit(K.EV_KEY, c, 0)
        self.dev.syn()

    def tap(self, codes: list[int]) -> None:
        self.press(codes)
        self.release(codes)

    def wheel(self, steps: int) -> None:
        self.dev.emit(K.EV_REL, K.REL_WHEEL, steps)
        self.dev.syn()

    def close(self) -> None:
        self.dev.close()
