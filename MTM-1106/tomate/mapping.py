"""Lógica pura de mapeamento: área da mesa → monitores, rotação e curva de pressão.

Sem acesso a hardware: totalmente testável.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import protocol as P

VIRTUAL_MAX = 65535  # faixa ABS_X/ABS_Y do dispositivo virtual (cobre o desktop inteiro)
TABLET_ASPECT = P.PHYSICAL_WIDTH_MIL / P.PHYSICAL_HEIGHT_MIL


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def aspect(self) -> float:
        return self.w / self.h if self.h else 1.0

    def contains(self, other: "Rect") -> bool:
        return (other.x >= self.x and other.y >= self.y
                and other.x + other.w <= self.x + self.w + 1e-9
                and other.y + other.h <= self.y + self.h + 1e-9)


@dataclass(frozen=True)
class Monitor:
    key: str          # identificador estável: fabricante|modelo|série
    connector: str    # ex.: HDMI-1
    name: str         # nome amigável
    rect: Rect        # posição/tamanho lógicos no desktop
    builtin: bool = False


def bounding_box(monitors: list[Monitor]) -> Rect:
    if not monitors:
        return Rect(0, 0, 1, 1)
    x0 = min(m.rect.x for m in monitors)
    y0 = min(m.rect.y for m in monitors)
    x1 = max(m.rect.x + m.rect.w for m in monitors)
    y1 = max(m.rect.y + m.rect.h for m in monitors)
    return Rect(x0, y0, x1 - x0, y1 - y0)


@dataclass
class MappingSettings:
    target: str = "all"                  # "all" | "monitor" | "region"
    monitor: str = ""                    # Monitor.key quando target == "monitor"
    region: Rect = field(default_factory=lambda: Rect(0, 0, 1920, 1080))
    tablet_area: Rect = field(default_factory=lambda: Rect(0, 0, 1, 1))  # normalizado 0..1
    keep_aspect: bool = True
    rotation: int = 0                    # 0, 90, 180, 270 (sentido horário)


def resolve_target(s: MappingSettings, monitors: list[Monitor]) -> tuple[Rect, str]:
    """Retângulo de saída no desktop e o alvo efetivamente usado ("all" se houve fallback)."""
    box = bounding_box(monitors)
    if s.target == "monitor":
        for m in monitors:
            if m.key == s.monitor or m.connector == s.monitor:
                return m.rect, "monitor"
        return box, "all"  # monitor escolhido não está conectado
    if s.target == "region" and s.region.w > 0 and s.region.h > 0:
        return s.region, "region"
    return box, "all"


def effective_tablet_area(s: MappingSettings, output: Rect) -> Rect:
    """Área da mesa (normalizada) após o recorte para manter a proporção da saída."""
    a = s.tablet_area
    if not s.keep_aspect or output.h <= 0 or a.w <= 0 or a.h <= 0:
        return a
    rotated = s.rotation in (90, 270)
    out_aspect = output.aspect
    if rotated:
        out_aspect = 1 / out_aspect
    # proporção física da área escolhida na mesa
    area_aspect = (a.w / a.h) * TABLET_ASPECT
    if area_aspect > out_aspect:  # área larga demais: reduz a largura
        new_w = a.w * out_aspect / area_aspect
        return Rect(a.x + (a.w - new_w) / 2, a.y, new_w, a.h)
    new_h = a.h * area_aspect / out_aspect
    return Rect(a.x, a.y + (a.h - new_h) / 2, a.w, new_h)


def _rotate(u: float, v: float, rotation: int) -> tuple[float, float]:
    if rotation == 90:
        return 1 - v, u
    if rotation == 180:
        return 1 - u, 1 - v
    if rotation == 270:
        return v, 1 - u
    return u, v


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


class Mapper:
    """Pré-calcula o mapeamento para converter amostras rapidamente."""

    def __init__(self, s: MappingSettings, monitors: list[Monitor]) -> None:
        self.settings = s
        self.desktop = bounding_box(monitors)
        self.output, self.effective_target = resolve_target(s, monitors)
        self.area = effective_tablet_area(s, self.output)

    def to_desktop(self, raw_x: int, raw_y: int) -> tuple[float, float]:
        nx = raw_x / P.RAW_X_MAX
        ny = raw_y / P.RAW_Y_MAX
        a = self.area
        u = _clamp((nx - a.x) / a.w) if a.w else 0.0
        v = _clamp((ny - a.y) / a.h) if a.h else 0.0
        u, v = _rotate(u, v, self.settings.rotation)
        o = self.output
        return o.x + u * o.w, o.y + v * o.h

    def to_virtual(self, raw_x: int, raw_y: int) -> tuple[int, int]:
        dx, dy = self.to_desktop(raw_x, raw_y)
        d = self.desktop
        vx = round(_clamp((dx - d.x) / d.w) * VIRTUAL_MAX)
        vy = round(_clamp((dy - d.y) / d.h) * VIRTUAL_MAX)
        return vx, vy


# --- pressão ----------------------------------------------------------------------
@dataclass
class PressureCurve:
    """Bézier cúbica de (0,0) a (1,1) com dois pontos de controle, mais limiar e saturação."""
    p1: tuple[float, float] = (0.25, 0.25)
    p2: tuple[float, float] = (0.75, 0.75)
    threshold: float = 0.0   # fração da pressão bruta abaixo da qual a saída é 0
    saturation: float = 1.0  # fração da pressão bruta que já dá saída máxima

    def _bezier(self, t: float) -> tuple[float, float]:
        mt = 1 - t
        a, b, c = 3 * mt * mt * t, 3 * mt * t * t, t * t * t
        return (a * self.p1[0] + b * self.p2[0] + c,
                a * self.p1[1] + b * self.p2[1] + c)

    def apply_unit(self, x: float) -> float:
        """Entrada e saída em 0..1."""
        lo, hi = self.threshold, max(self.saturation, self.threshold + 1e-6)
        if x <= lo:
            return 0.0
        if x >= hi:
            return 1.0
        x = (x - lo) / (hi - lo)
        t0, t1 = 0.0, 1.0  # x(t) é monotônica com p1.x, p2.x em [0,1]
        for _ in range(30):
            tm = (t0 + t1) / 2
            if self._bezier(tm)[0] < x:
                t0 = tm
            else:
                t1 = tm
        return _clamp(self._bezier((t0 + t1) / 2)[1])

    def apply(self, raw: int, raw_max: int = P.RAW_PRESSURE_MAX) -> int:
        return round(self.apply_unit(raw / raw_max) * raw_max)

    def lut(self, raw_max: int = P.RAW_PRESSURE_MAX) -> list[int]:
        return [self.apply(i, raw_max) for i in range(raw_max + 1)]
