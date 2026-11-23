"""Configuração persistente em TOML (~/.config/tomate/config.toml)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .mapping import MappingSettings, PressureCurve, Rect
from .protocol import BUTTON_FACTORY_LABEL

# Ações possíveis para um botão:
#   "default"          repassa o atalho de fábrica
#   "disabled"         ignora
#   "key:Ctrl+Z"       atalho de teclado
#   "mouse:MouseRight" clique (MouseLeft, MouseRight, MouseMiddle)
#   "wheel:WheelUp"    rolagem (WheelUp, WheelDown)
#   "cycle_monitor"    alterna o alvo: cada monitor → todos
#   "stylus" / "stylus2" botão de caneta (só para botões da caneta)
BUTTON_IDS = list(BUTTON_FACTORY_LABEL)
PEN_BUTTON_IDS = ["PEN1", "PEN2"]


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "tomate"


def config_path() -> Path:
    return config_dir() / "config.toml"


@dataclass
class Config:
    mapping: MappingSettings = field(default_factory=MappingSettings)
    pressure: PressureCurve = field(default_factory=PressureCurve)
    buttons: dict[str, str] = field(default_factory=lambda: {b: "default" for b in BUTTON_IDS})
    pen_buttons: dict[str, str] = field(default_factory=lambda: {"PEN1": "stylus", "PEN2": "stylus2"})

    # ---- serialização ----
    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        c = cls()
        m = d.get("mapping", {})
        r = m.get("region", {})
        a = m.get("tablet_area", {})
        c.mapping = MappingSettings(
            target=m.get("target", "all") if m.get("target") in ("all", "monitor", "region") else "all",
            monitor=str(m.get("monitor", "")),
            region=Rect(float(r.get("x", 0)), float(r.get("y", 0)),
                        float(r.get("w", 1920)), float(r.get("h", 1080))),
            tablet_area=_norm_rect(a),
            keep_aspect=bool(m.get("keep_aspect", True)),
            rotation=int(m.get("rotation", 0)) if int(m.get("rotation", 0)) in (0, 90, 180, 270) else 0,
        )
        p = d.get("pressure", {})
        c.pressure = PressureCurve(
            p1=_pt(p.get("p1"), (0.25, 0.25)),
            p2=_pt(p.get("p2"), (0.75, 0.75)),
            threshold=_unit(p.get("threshold", 0.0)),
            saturation=_unit(p.get("saturation", 1.0)) or 1.0,
        )
        for b, act in d.get("buttons", {}).items():
            if b in c.buttons:
                c.buttons[b] = str(act)
        for b, act in d.get("pen_buttons", {}).items():
            if b in c.pen_buttons:
                c.pen_buttons[b] = str(act)
        return c

    def to_toml(self) -> str:
        m, p = self.mapping, self.pressure
        lines = [
            "# Configuração da mesa TOMATE MTM-1106 — gerada pelo tomate-gui",
            "[mapping]",
            f'target = "{m.target}"',
            f"monitor = {_q(m.monitor)}",
            f"keep_aspect = {str(m.keep_aspect).lower()}",
            f"rotation = {m.rotation}",
            f"region = {{ x = {m.region.x:g}, y = {m.region.y:g}, w = {m.region.w:g}, h = {m.region.h:g} }}",
            f"tablet_area = {{ x = {m.tablet_area.x:.4f}, y = {m.tablet_area.y:.4f}, "
            f"w = {m.tablet_area.w:.4f}, h = {m.tablet_area.h:.4f} }}",
            "",
            "[pressure]",
            f"p1 = [{p.p1[0]:.4f}, {p.p1[1]:.4f}]",
            f"p2 = [{p.p2[0]:.4f}, {p.p2[1]:.4f}]",
            f"threshold = {p.threshold:.4f}",
            f"saturation = {p.saturation:.4f}",
            "",
            "[buttons]",
            *[f"{b} = {_q(a)}" for b, a in self.buttons.items()],
            "",
            "[pen_buttons]",
            *[f"{b} = {_q(a)}" for b, a in self.pen_buttons.items()],
            "",
        ]
        return "\n".join(lines)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unit(v) -> float:
    try:
        return min(max(float(v), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def _pt(v, default):
    try:
        return (_unit(v[0]), _unit(v[1]))
    except (TypeError, IndexError):
        return default


def _norm_rect(a: dict) -> Rect:
    x, y = _unit(a.get("x", 0)), _unit(a.get("y", 0))
    w = _unit(a.get("w", 1)) or 1.0
    h = _unit(a.get("h", 1)) or 1.0
    return Rect(x, y, min(w, 1 - x) or 1 - x, min(h, 1 - y) or 1 - y)


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        with open(path, "rb") as f:
            return Config.from_dict(tomllib.load(f))
    except FileNotFoundError:
        return Config()
    except (tomllib.TOMLDecodeError, ValueError, TypeError):
        return Config()


def save(cfg: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(cfg.to_toml(), encoding="utf-8")
    os.replace(tmp, path)
    return path
