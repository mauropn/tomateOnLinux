"""Acesso direto ao kernel Linux (hidraw, evdev, uinput) via ioctl, sem dependências."""
from __future__ import annotations

import fcntl
import os
import struct
import time

# --- ioctl encoding ------------------------------------------------------------
_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2


def _IOC(direction: int, typ: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(typ) << 8) | nr


def HIDIOCSFEATURE(n: int) -> int:
    return _IOC(_IOC_WRITE | _IOC_READ, "H", 0x06, n)


def HIDIOCGFEATURE(n: int) -> int:
    return _IOC(_IOC_WRITE | _IOC_READ, "H", 0x07, n)


EVIOCGRAB = _IOC(_IOC_WRITE, "E", 0x90, 4)
KEY_CNT = 0x300


def EVIOCGKEY(n: int) -> int:
    return _IOC(_IOC_READ, "E", 0x18, n)


_UINPUT_SETUP_SIZE = 92  # struct input_id (8) + name[80] + ff_effects_max (4)
_UINPUT_ABS_SETUP_SIZE = 28  # __u16 code + pad + struct input_absinfo (6 * s32)
UI_DEV_CREATE = _IOC(_IOC_NONE, "U", 1, 0)
UI_DEV_DESTROY = _IOC(_IOC_NONE, "U", 2, 0)
UI_DEV_SETUP = _IOC(_IOC_WRITE, "U", 3, _UINPUT_SETUP_SIZE)
UI_ABS_SETUP = _IOC(_IOC_WRITE, "U", 4, _UINPUT_ABS_SETUP_SIZE)
UI_SET_EVBIT = _IOC(_IOC_WRITE, "U", 100, 4)
UI_SET_KEYBIT = _IOC(_IOC_WRITE, "U", 101, 4)
UI_SET_RELBIT = _IOC(_IOC_WRITE, "U", 102, 4)
UI_SET_ABSBIT = _IOC(_IOC_WRITE, "U", 103, 4)
UI_SET_PROPBIT = _IOC(_IOC_WRITE, "U", 110, 4)

# --- códigos de evento (linux/input-event-codes.h) ------------------------------
EV_SYN, EV_KEY, EV_REL, EV_ABS, EV_MSC = 0x00, 0x01, 0x02, 0x03, 0x04
SYN_REPORT = 0
MSC_TIMESTAMP = 0x05
ABS_X, ABS_Y, ABS_PRESSURE = 0x00, 0x01, 0x18
ABS_TILT_X, ABS_TILT_Y = 0x1A, 0x1B
REL_HWHEEL, REL_WHEEL = 0x06, 0x08
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
BTN_TOOL_PEN, BTN_TOUCH, BTN_STYLUS, BTN_STYLUS2 = 0x140, 0x14A, 0x14B, 0x14C
INPUT_PROP_POINTER = 0x00
BUS_VIRTUAL = 0x06

_EVENT = struct.Struct("llHHi")  # struct input_event (64 bits)


# --- hidraw ----------------------------------------------------------------------
def hid_set_feature(fd: int, data: bytes) -> None:
    fcntl.ioctl(fd, HIDIOCSFEATURE(len(data)), bytearray(data))


def evdev_grab(fd: int, grab: bool = True) -> None:
    fcntl.ioctl(fd, EVIOCGRAB, 1 if grab else 0)


def evdev_pressed_keys(fd: int) -> list[int]:
    """Teclas/botões que o kernel considera apertados neste dispositivo (EVIOCGKEY)."""
    buf = bytearray(KEY_CNT // 8)
    fcntl.ioctl(fd, EVIOCGKEY(len(buf)), buf)
    return [i * 8 + b for i, byte in enumerate(buf) if byte for b in range(8) if byte >> b & 1]


def evdev_release_keys(fd: int) -> list[int]:
    """Injeta a liberação de tudo o que estiver apertado (fd aberto com escrita).

    Usado antes de capturar (grab) e depois de soltar os nós do kernel: se a caneta estava
    em proximidade nesse momento, o compositor nunca veria a saída e deixaria um cursor
    parado na tela.
    """
    codes = evdev_pressed_keys(fd)
    if codes:
        ev = b"".join(_EVENT.pack(0, 0, EV_KEY, c, 0) for c in codes)
        os.write(fd, ev + _EVENT.pack(0, 0, EV_SYN, SYN_REPORT, 0))
    return codes


# --- uinput ----------------------------------------------------------------------
class UInputDevice:
    """Dispositivo virtual /dev/uinput mínimo."""

    def __init__(
        self,
        name: str,
        keys: list[int] = (),
        rels: list[int] = (),
        abs_axes: dict[int, tuple[int, int, int]] | None = None,  # code -> (min, max, resolução)
        props: list[int] = (),
        vendor: int = 0x1209,
        product: int = 0x7011,
    ) -> None:
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            if keys:
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
                for k in keys:
                    fcntl.ioctl(self.fd, UI_SET_KEYBIT, k)
            if rels:
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
                for r in rels:
                    fcntl.ioctl(self.fd, UI_SET_RELBIT, r)
            if abs_axes:
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_MSC)
                for code, (lo, hi, res) in abs_axes.items():
                    fcntl.ioctl(self.fd, UI_SET_ABSBIT, code)
                    setup = struct.pack("HHiiiiii", code, 0, 0, lo, hi, 0, 0, res)
                    fcntl.ioctl(self.fd, UI_ABS_SETUP, setup)
            for p in props:
                fcntl.ioctl(self.fd, UI_SET_PROPBIT, p)
            setup = struct.pack("HHHH80sI", BUS_VIRTUAL, vendor, product, 1,
                                name.encode()[:79], 0)
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except Exception:
            os.close(self.fd)
            raise
        self._pending: list[bytes] = []

    def emit(self, etype: int, code: int, value: int) -> None:
        self._pending.append(_EVENT.pack(0, 0, etype, code, int(value)))

    def syn(self) -> None:
        self.emit(EV_SYN, SYN_REPORT, 0)
        os.write(self.fd, b"".join(self._pending))
        self._pending.clear()

    def close(self) -> None:
        if self.fd >= 0:
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            finally:
                os.close(self.fd)
                self.fd = -1


def monotonic_us() -> int:
    return int(time.monotonic() * 1_000_000) & 0x7FFFFFFF
