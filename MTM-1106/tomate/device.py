"""Descoberta e abertura da mesa física (hidraw + grab dos nós evdev do kernel)."""
from __future__ import annotations

import glob
import logging
import os
import time
from dataclasses import dataclass, field

from . import kernel as K
from . import protocol as P

log = logging.getLogger(__name__)
_ID = f"{P.VENDOR_ID:08X}:{P.PRODUCT_ID:08X}"


@dataclass
class TabletNodes:
    hidraw: dict[int, str] = field(default_factory=dict)   # interface -> /dev/hidrawN
    events: list[str] = field(default_factory=list)         # /dev/input/eventN


def _iface_of(sys_hid_dir: str) -> int:
    # .../3-2.2:1.2/0003:08F2:6811.0008  →  interface 2
    usb_if = os.path.basename(os.path.dirname(os.path.realpath(sys_hid_dir)))
    try:
        return int(usb_if.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return -1


def find_nodes() -> TabletNodes:
    nodes = TabletNodes()
    for p in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(f"{p}/device/uevent").read()
        except OSError:
            continue
        if _ID in uevent:
            nodes.hidraw[_iface_of(f"{p}/device")] = f"/dev/{os.path.basename(p)}"
    for p in sorted(glob.glob("/sys/class/input/event*")):
        try:
            vendor = open(f"{p}/device/id/vendor").read().strip()
            product = open(f"{p}/device/id/product").read().strip()
        except OSError:
            continue
        if int(vendor, 16) == P.VENDOR_ID and int(product, 16) == P.PRODUCT_ID:
            nodes.events.append(f"/dev/input/{os.path.basename(p)}")
    return nodes


def _release_stuck(fd: int, name: str) -> None:
    try:
        codes = K.evdev_release_keys(fd)
    except OSError:
        return
    if codes:
        log.info("liberadas teclas presas em %s: %s", name or "nó do kernel", [hex(c) for c in codes])


class Tablet:
    """Mesa aberta: fds de leitura das hidraw e grab exclusivo dos eventos do kernel."""

    def __init__(self, nodes: TabletNodes) -> None:
        if P.IFACE_MAIN not in nodes.hidraw:
            raise FileNotFoundError("mesa 08f2:6811 não encontrada")
        self.nodes = nodes
        self.main_fd = os.open(nodes.hidraw[P.IFACE_MAIN], os.O_RDWR | os.O_NONBLOCK)
        self.aux_fd = -1
        if P.IFACE_AUX in nodes.hidraw:
            self.aux_fd = os.open(nodes.hidraw[P.IFACE_AUX], os.O_RDONLY | os.O_NONBLOCK)
        self.grabbed: list[int] = []
        for ev in nodes.events:
            try:
                try:
                    fd = os.open(ev, os.O_RDWR | os.O_NONBLOCK)
                except PermissionError:
                    fd = os.open(ev, os.O_RDONLY | os.O_NONBLOCK)
                _release_stuck(fd, ev)
                K.evdev_grab(fd, True)
                self.grabbed.append(fd)
            except OSError as e:
                log.warning("não foi possível fazer grab de %s: %s", ev, e)

    def init_mode(self) -> None:
        K.hid_set_feature(self.main_fd, P.mode_command(P.MODE_DRIVER))
        time.sleep(0.3)  # o driver Windows espera >= 300 ms entre comandos
        K.hid_set_feature(self.main_fd, P.area_command())  # área ativa = mesa inteira

    def fds(self) -> list[int]:
        return [fd for fd in (self.main_fd, self.aux_fd) if fd >= 0] + self.grabbed

    def close(self) -> None:
        for fd in self.grabbed:
            try:
                K.evdev_grab(fd, False)
            except OSError:
                pass
            _release_stuck(fd, "")
            os.close(fd)
        self.grabbed.clear()
        for fd in (self.main_fd, self.aux_fd):
            if fd >= 0:
                os.close(fd)
        self.main_fd = self.aux_fd = -1
