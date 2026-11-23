"""Daemon: lê a mesa, aplica a configuração e reemite eventos por dispositivos uinput."""
from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import selectors
import signal
import socket
import threading
import time

from . import config as C
from . import ipc, keys, monitors
from . import protocol as P
from .device import Tablet, find_nodes
from .mapping import Mapper
from .virtual import VirtualKeyboard, VirtualPen

log = logging.getLogger("tomate")
STREAM_INTERVAL = 1 / 60


class Daemon:
    def __init__(self) -> None:
        self.cfg = C.load()
        self.monitors = monitors.list_monitors()
        self.mapper = Mapper(self.cfg.mapping, self.monitors)
        self.lut = self.cfg.pressure.lut()
        self.pen = VirtualPen()
        self.kbd = VirtualKeyboard()
        self.tablet: Tablet | None = None
        self.sel = selectors.DefaultSelector()
        self.clients: dict[socket.socket, dict] = {}
        self.pressed_buttons: set[str] = set()
        self.held_actions: dict[str, list[int]] = {}
        self.passthrough_held: list[int] = []
        self.consumer_held: int | None = None
        self.last_stream = 0.0
        self.running = True
        # pipe para acordar o loop quando o layout de monitores muda (thread D-Bus)
        self.wake_r, self.wake_w = os.pipe()
        os.set_blocking(self.wake_r, False)
        self.sel.register(self.wake_r, selectors.EVENT_READ, ("wake", None))
        self._start_server()
        threading.Thread(target=self._watch_monitors, daemon=True).start()

    # ------------------------------------------------------------------ setup
    def _start_server(self) -> None:
        path = ipc.socket_path()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        os.chmod(path, 0o600)
        self.server.listen(8)
        self.server.setblocking(False)
        self.sel.register(self.server, selectors.EVENT_READ, ("accept", None))

    def _watch_monitors(self) -> None:
        try:
            monitors.watch_changes(lambda: os.write(self.wake_w, b"m"))
        except Exception as e:  # sem Mutter: faz polling
            log.info("sem sinal MonitorsChanged (%s); usando polling", e)
            last = self.monitors
            while self.running:
                time.sleep(3)
                cur = monitors.list_monitors()
                if cur != last:
                    last = cur
                    os.write(self.wake_w, b"m")

    def rebuild(self) -> None:
        self.mapper = Mapper(self.cfg.mapping, self.monitors)
        self.lut = self.cfg.pressure.lut()
        if self.cfg.mapping.target != self.mapper.effective_target:
            log.warning("alvo %s indisponível; usando todos os monitores", self.cfg.mapping.target)
        self.broadcast({"ev": "status", **self.status()})

    def status(self) -> dict:
        return {
            "connected": self.tablet is not None,
            "monitors": [{"key": m.key, "connector": m.connector, "name": m.name,
                          "rect": [m.rect.x, m.rect.y, m.rect.w, m.rect.h],
                          "builtin": m.builtin} for m in self.monitors],
            "target": self.cfg.mapping.target,
            "effective_target": self.mapper.effective_target,
            "output": [self.mapper.output.x, self.mapper.output.y,
                       self.mapper.output.w, self.mapper.output.h],
            "area": [self.mapper.area.x, self.mapper.area.y, self.mapper.area.w, self.mapper.area.h],
        }

    # ------------------------------------------------------------------ tablet
    def try_connect(self) -> None:
        nodes = find_nodes()
        if P.IFACE_MAIN not in nodes.hidraw:
            return
        try:
            t = Tablet(nodes)
            t.init_mode()
        except OSError as e:
            log.warning("falha ao abrir a mesa: %s", e)
            return
        self.tablet = t
        self.sel.register(t.main_fd, selectors.EVENT_READ, ("main", None))
        if t.aux_fd >= 0:
            self.sel.register(t.aux_fd, selectors.EVENT_READ, ("aux", None))
        for fd in t.grabbed:
            self.sel.register(fd, selectors.EVENT_READ, ("drain", None))
        log.info("mesa conectada: %s", nodes)
        self.broadcast({"ev": "status", **self.status()})

    def disconnect(self) -> None:
        if not self.tablet:
            return
        for fd in self.tablet.fds():
            try:
                self.sel.unregister(fd)
            except (KeyError, ValueError):
                pass
        self.tablet.close()
        self.tablet = None
        self.pen.update(0, 0, 0, False, False, False, False)
        self._release_all()
        log.info("mesa desconectada")
        self.broadcast({"ev": "status", **self.status()})

    def on_main(self, data: bytes) -> None:
        if data[:1] == bytes([P.REPORT_PEN]):
            s = P.parse_pen(data)
            if s:
                self.on_pen(s)
        elif data[:1] == bytes([P.REPORT_KEYBOARD]):
            kb = P.parse_keyboard(data)
            if kb:
                self.on_keyboard(*kb)
        elif data[:1] == bytes([P.REPORT_CONSUMER]):
            usage = P.parse_consumer(data)
            if usage is not None:
                self.on_consumer(usage)

    def on_consumer(self, usage: int) -> None:
        """Repassa as teclas multimídia; o report só diz qual está apertada (0 = nenhuma)."""
        code = keys.HID_CONSUMER_TO_LINUX.get(usage)
        if self.consumer_held is not None and self.consumer_held != code:
            self.kbd.release([self.consumer_held])
            self.consumer_held = None
        if code is not None and self.consumer_held is None:
            self.kbd.press([code])
            self.consumer_held = code
        elif usage and code is None:
            log.debug("tecla multimídia sem tradução: 0x%x", usage)

    def on_aux(self, data: bytes) -> None:
        if data[:1] == bytes([P.REPORT_PEN_HIRES]):
            s = P.parse_pen(data)
            if s:
                self.on_pen(s)
            return
        w = P.parse_wheel(data)
        if w:
            b = P.WHEEL_BUTTONS[w]
            self.on_button(b, True)
            self.on_button(b, False)

    def on_pen(self, s: P.PenSample) -> None:
        vx, vy = self.mapper.to_virtual(s.x, s.y)
        out_p = self.lut[s.pressure] if s.tip else 0
        touch = s.tip and out_p > 0
        stylus = stylus2 = False
        for pid, flag in (("PEN1", s.barrel), ("PEN2", s.barrel2)):
            act = self.cfg.pen_buttons.get(pid, "")
            if act == "stylus":
                stylus = stylus or flag
            elif act == "stylus2":
                stylus2 = stylus2 or flag
            elif (pid in self.pressed_buttons) != flag:
                self.on_button(pid, flag, pen=True)
        self.pen.update(vx, vy, out_p, s.in_range, touch, stylus, stylus2, s.tilt_x, s.tilt_y)
        now = time.monotonic()
        if self.clients and (now - self.last_stream >= STREAM_INTERVAL or not s.in_range):
            self.last_stream = now
            self.broadcast({"ev": "pen", "x": s.x, "y": s.y, "p": s.pressure, "po": out_p,
                            "tip": s.tip, "range": s.in_range, "b1": s.barrel, "b2": s.barrel2},
                           stream_only=True)

    # ------------------------------------------------------------------ buttons
    def on_keyboard(self, mod: int, keycodes: tuple[int, ...]) -> None:
        now = P.keyboard_to_buttons(mod, keycodes)
        if now or not keycodes and mod == 0:
            for b in sorted(self.pressed_buttons - now):
                if not b.startswith("PEN"):
                    self.on_button(b, False)
            for b in sorted(now - self.pressed_buttons):
                self.on_button(b, True)
            self._passthrough([])
        else:  # combinação desconhecida: repassa como teclado
            self._passthrough(keys.hid_report_to_keycodes(mod, keycodes))

    def _passthrough(self, codes: list[int]) -> None:
        released = [c for c in self.passthrough_held if c not in codes]
        pressed = [c for c in codes if c not in self.passthrough_held]
        if released:
            self.kbd.release(released)
        if pressed:
            self.kbd.press(pressed)
        self.passthrough_held = list(codes)

    def on_button(self, b: str, down: bool, pen: bool = False) -> None:
        if down:
            self.pressed_buttons.add(b)
        else:
            self.pressed_buttons.discard(b)
        self.broadcast({"ev": "button", "id": b, "down": down}, stream_only=True)
        act = (self.cfg.pen_buttons if pen else self.cfg.buttons).get(b, "default")
        if act == "disabled":
            return
        if act == "default":
            if b in P.WHEEL_BUTTONS.values():
                act = "wheel:" + ("WheelUp" if b == P.WHEEL_BUTTONS[1] else "WheelDown")
            elif b in P.BUTTONS:
                codes = keys.hid_report_to_keycodes(P.BUTTONS[b][0],
                                                    (P.BUTTONS[b][1],) if P.BUTTONS[b][1] else ())
                self._hold(b, codes, down)
                return
            else:
                return
        if act == "cycle_monitor":
            if down:
                self.cycle_monitor()
        elif act.startswith("wheel:"):
            if down:
                self.kbd.wheel(keys.WHEEL_ACTIONS.get(act[6:], 0))
        elif act.startswith("mouse:"):
            code = keys.MOUSE_ACTIONS.get(act[6:])
            if code:
                self._hold(b, [code], down)
        elif act.startswith("key:"):
            try:
                self._hold(b, keys.parse_shortcut(act[4:]), down)
            except ValueError as e:
                log.warning("atalho inválido em %s: %s", b, e)

    def _hold(self, b: str, codes: list[int], down: bool) -> None:
        if down:
            if b in self.held_actions:
                return
            self.held_actions[b] = codes
            self.kbd.press(codes)
        else:
            codes = self.held_actions.pop(b, None)
            if codes:
                self.kbd.release(codes)

    def _release_all(self) -> None:
        for b in list(self.held_actions):
            self._hold(b, [], False)
        self._passthrough([])
        self.on_consumer(0)
        self.pressed_buttons.clear()

    def cycle_monitor(self) -> None:
        order = [m.key for m in self.monitors] + ["all"]
        m = self.cfg.mapping
        cur = m.monitor if m.target == "monitor" and m.monitor in order else "all"
        nxt = order[(order.index(cur) + 1) % len(order)]
        if nxt == "all":
            m.target = "all"
        else:
            m.target, m.monitor = "monitor", nxt
        C.save(self.cfg)
        self.rebuild()
        log.info("alvo alternado para %s", nxt)

    # ------------------------------------------------------------------ IPC
    def broadcast(self, msg: dict, stream_only: bool = False) -> None:
        data = ipc.encode(msg)
        for conn, st in list(self.clients.items()):
            if stream_only and not st.get("subscribed"):
                continue
            if st.get("subscribed"):
                try:
                    conn.send(data)
                except (BlockingIOError, InterruptedError):
                    pass  # cliente lento: descarta a amostra
                except OSError:
                    self._drop(conn)

    def _drop(self, conn: socket.socket) -> None:
        try:
            self.sel.unregister(conn)
        except (KeyError, ValueError):
            pass
        self.clients.pop(conn, None)
        conn.close()

    def on_client(self, conn: socket.socket) -> None:
        st = self.clients[conn]
        try:
            chunk = conn.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            chunk = b""
        if not chunk:
            self._drop(conn)
            return
        st["buf"] += chunk
        while b"\n" in st["buf"]:
            line, st["buf"] = st["buf"].split(b"\n", 1)
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            reply = self.handle(msg, st)
            if reply is not None:
                try:
                    conn.setblocking(True)
                    conn.sendall(ipc.encode(reply))
                    conn.setblocking(False)
                except OSError:
                    self._drop(conn)
                    return

    def handle(self, msg: dict, st: dict) -> dict | None:
        cmd = msg.get("cmd")
        if cmd == "reload":
            self.cfg = C.load()
            self.rebuild()
            return {"ok": True}
        if cmd == "status":
            return {"ok": True, **self.status()}
        if cmd == "subscribe":
            st["subscribed"] = True
            return {"ev": "status", **self.status()}
        if cmd == "cycle_monitor":
            self.cycle_monitor()
            return {"ok": True}
        return {"ok": False, "error": f"comando desconhecido: {cmd}"}

    # ------------------------------------------------------------------ loop
    def run(self) -> None:
        next_try = 0.0
        while self.running:
            if self.tablet is None and time.monotonic() >= next_try:
                self.try_connect()
                next_try = time.monotonic() + 2
            for key, _ in self.sel.select(timeout=1.0):
                kind, _ = key.data
                if kind == "accept":
                    try:
                        conn, _ = self.server.accept()
                    except OSError:
                        continue
                    conn.setblocking(False)
                    self.clients[conn] = {"buf": b"", "subscribed": False}
                    self.sel.register(conn, selectors.EVENT_READ, ("client", None))
                elif kind == "client":
                    if key.fileobj in self.clients:
                        self.on_client(key.fileobj)
                elif kind == "wake":
                    try:
                        os.read(self.wake_r, 64)
                    except BlockingIOError:
                        pass
                    self.monitors = monitors.list_monitors()
                    log.info("layout de monitores mudou: %s", [m.connector for m in self.monitors])
                    self.rebuild()
                elif kind in ("main", "aux", "drain"):
                    self._read_tablet(key.fd, kind)

    def _read_tablet(self, fd: int, kind: str) -> None:
        while self.tablet is not None:
            try:
                data = os.read(fd, 64)
            except BlockingIOError:
                return
            except OSError as e:
                if e.errno in (errno.ENODEV, errno.EIO, errno.EBADF):
                    self.disconnect()
                    return
                raise
            if not data:
                self.disconnect()
                return
            if kind == "main":
                self.on_main(data)
            elif kind == "aux":
                self.on_aux(data)
            # "drain": eventos do kernel já capturados (grab); descartados

    def shutdown(self, *_):
        self.running = False

    def close(self) -> None:
        self.disconnect()
        self.pen.close()
        self.kbd.close()
        self.server.close()
        try:
            os.unlink(ipc.socket_path())
        except OSError:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Daemon da mesa TOMATE MTM-1106")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if ipc.request({"cmd": "status"}, timeout=0.5) is not None:
        raise SystemExit("o tomate-daemon já está rodando")
    d = Daemon()
    signal.signal(signal.SIGTERM, d.shutdown)
    signal.signal(signal.SIGINT, d.shutdown)
    signal.signal(signal.SIGHUP, lambda *_: os.write(d.wake_w, b"m"))
    log.info("monitores: %s", [(m.connector, m.rect) for m in d.monitors])
    try:
        d.run()
    finally:
        d.close()


if __name__ == "__main__":
    main()
