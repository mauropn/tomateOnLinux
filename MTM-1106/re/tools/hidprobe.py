#!/usr/bin/env python3
"""Sonda HID somente leitura para a TOMATE MTM-1106 (08f2:6811).

Uso:
  hidprobe.py info                 lista hidraw da mesa
  hidprobe.py getfeature N ID LEN  HIDIOCGFEATURE no hidrawN
  hidprobe.py listen SECS          mostra reports de todas as hidraw da mesa
"""
import fcntl
import glob
import os
import select
import sys
import time

VID, PID = 0x08F2, 0x6811


def _IOC(d, t, nr, size):
    return (d << 30) | (size << 16) | (ord(t) << 8) | nr


def HIDIOCGFEATURE(n):
    return _IOC(3, "H", 0x07, n)


def tablet_hidraws():
    out = []
    for p in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        ue = open(f"{p}/device/uevent").read()
        if f"{VID:08X}:{PID:08X}" in ue:
            iface = os.path.basename(os.path.realpath(f"{p}/device/..")).split(".")[-1]
            out.append((f"/dev/{os.path.basename(p)}", iface))
    return out


def getfeature(dev, rid, length):
    buf = bytearray(length + 1)
    buf[0] = rid
    fd = os.open(dev, os.O_RDWR)
    try:
        n = fcntl.ioctl(fd, HIDIOCGFEATURE(len(buf)), buf, True)
    finally:
        os.close(fd)
    return bytes(buf[: n if isinstance(n, int) and n > 0 else len(buf)])


def listen(secs):
    fds = {}
    for dev, iface in tablet_hidraws():
        fds[os.open(dev, os.O_RDONLY | os.O_NONBLOCK)] = (dev, iface)
    end = time.time() + secs
    last = {}
    while time.time() < end:
        r, _, _ = select.select(list(fds), [], [], 0.2)
        for fd in r:
            data = os.read(fd, 128)
            dev, iface = fds[fd]
            if last.get(fd) != data:
                print(f"{time.time():.3f} {dev} iface{iface}: {data.hex(' ')}", flush=True)
                last[fd] = data


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    if cmd == "info":
        for dev, iface in tablet_hidraws():
            print(dev, "interface", iface)
    elif cmd == "getfeature":
        dev, rid, ln = f"/dev/hidraw{sys.argv[2]}", int(sys.argv[3], 0), int(sys.argv[4], 0)
        try:
            print(getfeature(dev, rid, ln).hex(" "))
        except OSError as e:
            print("erro:", e)
    elif cmd == "setfeature":
        # setfeature N HEXBYTES  (primeiro byte = report ID)
        dev, data = f"/dev/hidraw{sys.argv[2]}", bytes.fromhex(sys.argv[3])
        fd = os.open(dev, os.O_RDWR)
        try:
            fcntl.ioctl(fd, _IOC(3, "H", 0x06, len(data)), bytearray(data))
            print("ok:", data.hex(" "))
        except OSError as e:
            print("erro:", e)
        finally:
            os.close(fd)
    elif cmd == "listen":
        listen(float(sys.argv[2]))


if __name__ == "__main__":
    main()
