"""Descoberta de monitores: GNOME/Mutter via D-Bus (Wayland ou X11), xrandr como reserva."""
from __future__ import annotations

import re
import subprocess

from .mapping import Monitor, Rect

_MUTTER = dict(object_path="/org/gnome/Mutter/DisplayConfig",
               bus_name="org.gnome.Mutter.DisplayConfig",
               interface="org.gnome.Mutter.DisplayConfig")


def parse_mutter_state(body) -> list[Monitor]:
    """Converte o retorno de GetCurrentState em monitores com retângulos lógicos."""
    _serial, physical, logical, props = body
    layout_logical = props.get("layout-mode", ("u", 1))[1] == 1  # 1 = lógico, 2 = físico
    info = {}
    for spec, modes, mprops in physical:
        cur = next((m for m in modes if m[6].get("is-current", ("b", False))[1]), None)
        info[spec[0]] = (spec, cur, {k: v[1] for k, v in mprops.items()})
    out = []
    for x, y, scale, transform, _primary, specs, _lprops in logical:
        for spec in specs:
            connector = spec[0]
            pspec, mode, mprops = info.get(connector, (spec, None, {}))
            if mode is None:
                continue
            w, h = mode[1], mode[2]
            if transform in (1, 3, 5, 7):  # 90/270 graus
                w, h = h, w
            if layout_logical and scale:
                w, h = w / scale, h / scale
            vendor, product, serial = pspec[1], pspec[2], pspec[3]
            out.append(Monitor(
                key=f"{vendor}|{product}|{serial}",
                connector=connector,
                name=str(mprops.get("display-name", f"{vendor} {product}")),
                rect=Rect(float(x), float(y), float(w), float(h)),
                builtin=bool(mprops.get("is-builtin", False)),
            ))
    return sorted(out, key=lambda m: (m.rect.x, m.rect.y))


def _mutter_monitors() -> list[Monitor]:
    from jeepney import DBusAddress, new_method_call
    from jeepney.io.blocking import open_dbus_connection

    addr = DBusAddress(_MUTTER["object_path"], bus_name=_MUTTER["bus_name"],
                       interface=_MUTTER["interface"])
    with open_dbus_connection("SESSION") as conn:
        reply = conn.send_and_get_reply(new_method_call(addr, "GetCurrentState"), timeout=3)
    return parse_mutter_state(reply.body)


_XRANDR_RE = re.compile(r"^\s*\d+:\s+[+*]*(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)\s+(\S+)")


def parse_xrandr(text: str) -> list[Monitor]:
    out = []
    for line in text.splitlines():
        m = _XRANDR_RE.match(line)
        if m:
            _name, w, h, x, y, conn = m.groups()
            out.append(Monitor(key=conn, connector=conn, name=conn,
                               rect=Rect(float(x), float(y), float(w), float(h)),
                               builtin=conn.startswith(("eDP", "LVDS"))))
    return sorted(out, key=lambda m: (m.rect.x, m.rect.y))


def _xrandr_monitors() -> list[Monitor]:
    text = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True,
                          timeout=3, check=True).stdout
    return parse_xrandr(text)


def list_monitors() -> list[Monitor]:
    for fn in (_mutter_monitors, _xrandr_monitors):
        try:
            mons = fn()
            if mons:
                return mons
        except Exception:
            continue
    return []


def watch_changes(callback) -> None:
    """Bloqueia escutando o sinal MonitorsChanged do Mutter; chama callback() a cada mudança.

    Retorna se o D-Bus não estiver disponível (o chamador faz polling nesse caso).
    """
    from jeepney import MatchRule
    from jeepney.io.blocking import open_dbus_connection, Proxy
    from jeepney.bus_messages import message_bus

    rule = MatchRule(type="signal", interface=_MUTTER["interface"],
                     member="MonitorsChanged", path=_MUTTER["object_path"])
    with open_dbus_connection("SESSION") as conn:
        Proxy(message_bus, conn).AddMatch(rule)
        with conn.filter(rule) as queue:
            while True:
                conn.recv_until_filtered(queue)
                callback()
