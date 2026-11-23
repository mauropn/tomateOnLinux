"""Protocolo da TOMATE MTM-1106 (08f2:6811), obtido por engenharia reversa.

Ver docs/protocolo-mtm1106.md para a evidência de cada constante.
"""
from __future__ import annotations

from dataclasses import dataclass

VENDOR_ID = 0x08F2
PRODUCT_ID = 0x6811

# Interface 2: teclado (botões expressos), comandos e, no estado de fábrica, a caneta (report 5).
IFACE_MAIN = 2
# Interface 1: caneta em alta resolução (report 9, após o modo 0) e mouse (roda dos botões).
IFACE_AUX = 1

REPORT_PEN = 0x05        # caneta 12 bits (estado ao ligar a mesa)
REPORT_PEN_HIRES = 0x09  # caneta 15 bits + inclinação (após o comando de modo 0)
REPORT_RAW = 0x06        # fluxo bruto do sensor (após o modo 3): o daemon não usa
REPORT_KEYBOARD = 0x02
REPORT_MOUSE = 0x03
REPORT_CONSUMER = 0x04  # teclas multimídia (ícones impressos na mesa)
REPORT_COMMAND = 0x08  # feature report de 8 bytes

# Escala interna: a do report 9. O report 5 (12 bits / 2047) é convertido para ela.
RAW_X_MAX = 32767
RAW_Y_MAX = 32767
RAW_PRESSURE_MAX = 16383
TILT_MAX = 127
_R5_XY_MAX = 4095
_R5_PRESSURE_MAX = 2047
# Tamanho físico declarado no descritor HID (milésimos de polegada).
PHYSICAL_WIDTH_MIL = 8000
PHYSICAL_HEIGHT_MIL = 5340

FLAG_TIP = 0x01
FLAG_BARREL = 0x02
FLAG_ERASER = 0x04  # botão lateral 2, conforme o descritor
FLAG_IN_RANGE = 0x40

# Modos do comando 0/1/3 (FUN_00495cc8). Observado no Linux (2026-11-18):
#  - estado ao ligar: caneta no report 5 da iface 2;
#  - modo 0: caneta no report 9 da iface 1 (alta resolução + inclinação), que o kernel também entende;
#  - modo 3: só o fluxo bruto report 6 da iface 1 (o driver Windows decodifica). NÃO usar.
MODE_STANDARD = 0
MODE_RAW = 3
MODE_DRIVER = MODE_STANDARD


@dataclass(frozen=True)
class PenSample:
    x: int
    y: int
    pressure: int
    tip: bool
    barrel: bool
    barrel2: bool
    in_range: bool
    tilt_x: int = 0
    tilt_y: int = 0


def _scale(v: int, src_max: int, dst_max: int) -> int:
    return round(min(v, src_max) * dst_max / src_max)


def _s8(b: int) -> int:
    return b - 256 if b > 127 else b


def parse_pen(report: bytes) -> PenSample | None:
    """Decodifica a caneta, sempre na escala interna (RAW_*_MAX).

    Report 5: `05 FF XX XX YY YY PP PP` (little-endian, 12 bits, pressão 0–2047).
    Report 9: `09 FF XX XX YY YY PP PP TX TY` (little-endian, 0–32767, pressão 0–16383, tilt int8).
    """
    if len(report) >= 8 and report[0] == REPORT_PEN:
        x = _scale(int.from_bytes(report[2:4], "little"), _R5_XY_MAX, RAW_X_MAX)
        y = _scale(int.from_bytes(report[4:6], "little"), _R5_XY_MAX, RAW_Y_MAX)
        p = _scale(int.from_bytes(report[6:8], "little"), _R5_PRESSURE_MAX, RAW_PRESSURE_MAX)
        tx = ty = 0
    elif len(report) >= 10 and report[0] == REPORT_PEN_HIRES:
        x = min(int.from_bytes(report[2:4], "little"), RAW_X_MAX)
        y = min(int.from_bytes(report[4:6], "little"), RAW_Y_MAX)
        p = min(int.from_bytes(report[6:8], "little"), RAW_PRESSURE_MAX)
        tx, ty = _s8(report[8]), _s8(report[9])
    else:
        return None
    flags = report[1]
    return PenSample(
        x=x,
        y=y,
        pressure=p,
        tilt_x=tx,
        tilt_y=ty,
        tip=bool(flags & FLAG_TIP),
        barrel=bool(flags & FLAG_BARREL),
        barrel2=bool(flags & FLAG_ERASER),
        in_range=bool(flags & FLAG_IN_RANGE),
    )


# Botões expressos: a mesa os reporta como combinações fixas de teclado (report 2)
# ou como roda de mouse (report 3 da interface 1). Identificamos cada botão físico
# pela combinação que ele produz de fábrica. (modificador HID, keycode HID)
BUTTONS: dict[str, tuple[int, int]] = {
    "B1": (0x00, 0x05),  # b
    "B2": (0x00, 0x08),  # e
    "B3": (0x01, 0x2D),  # Ctrl + -
    "B4": (0x01, 0x2E),  # Ctrl + =
    "B5": (0x00, 0x2F),  # [
    "B6": (0x00, 0x30),  # ]
    "B7": (0x00, 0x2B),  # Tab
    "B8": (0x00, 0x2C),  # Espaço
    "B9": (0x01, 0x00),  # Ctrl
    "B10": (0x04, 0x00),  # Alt
}
WHEEL_BUTTONS = {1: "B11", -1: "B12"}  # roda para cima / para baixo

BUTTON_FACTORY_LABEL = {
    "B1": "b", "B2": "e", "B3": "Ctrl+-", "B4": "Ctrl+=", "B5": "[", "B6": "]",
    "B7": "Tab", "B8": "Espaço", "B9": "Ctrl", "B10": "Alt",
    "B11": "Roda ↑", "B12": "Roda ↓",
}
_BY_COMBO = {v: k for k, v in BUTTONS.items()}


def parse_keyboard(report: bytes) -> tuple[int, tuple[int, ...]] | None:
    """Report 2: `02 MOD 00 K1 K2 K3 K4 K5`. Devolve (modificador, teclas)."""
    if len(report) < 8 or report[0] != REPORT_KEYBOARD:
        return None
    return report[1], tuple(k for k in report[3:8] if k)


def keyboard_to_buttons(mod: int, keys: tuple[int, ...]) -> set[str]:
    """Converte um report de teclado no conjunto de botões físicos pressionados.

    Combinações desconhecidas (ex.: Ctrl+Z de fábrica) devolvem conjunto vazio e
    são repassadas como teclado pelo daemon.
    """
    if not keys:
        b = _BY_COMBO.get((mod, 0))
        return {b} if b else set()
    out = set()
    for k in keys:
        b = _BY_COMBO.get((mod, k))
        if b is None:
            return set()
        out.add(b)
    return out


def parse_consumer(report: bytes) -> int | None:
    """Report 4 (iface 2): `04 LO HI`. Devolve o usage Consumer (0 = soltou)."""
    if len(report) < 3 or report[0] != REPORT_CONSUMER:
        return None
    return int.from_bytes(report[1:3], "little")


def parse_wheel(report: bytes) -> int:
    """Report 3 (iface 1): `03 BTN DX DY WHEEL`. Devolve +1, -1 ou 0."""
    if len(report) < 5 or report[0] != REPORT_MOUSE:
        return 0
    w = report[4] - 256 if report[4] > 127 else report[4]
    return (w > 0) - (w < 0)


def _pack12(a: int, b: int) -> tuple[int, int, int]:
    """Empacota dois valores de 12 bits como o driver: lo(a), lo(b), hi(a)|hi(b)<<4."""
    return a & 0xFF, b & 0xFF, ((a >> 8) & 0x0F) | (((b >> 8) & 0x0F) << 4)


# Retângulo enviado junto com o comando de modo. O driver Windows manda ScreenMap do
# TSetting.ini (FUN_004c05c8, caso 5 → FUN_00495568): v24 = topo, v26 = esquerda,
# v28 = largura, v2a = altura, padrão 0, 0, 4095, 4095. Com largura/altura 0 a firmware
# põe a origem no centro da mesa com escala 2× (metade esquerda/superior presa em 0).
FULL_AREA = (0, 0, 4095, 4095)


def mode_command(mode: int = MODE_DRIVER, rect: tuple[int, int, int, int] = FULL_AREA) -> bytes:
    """Comando de modo (FUN_00495cc8 + FUN_004954f8).

    rect = (v24, v26, v28, v2a) = (topo, esquerda, largura, altura), em 12 bits; padrão: mesa inteira.
    Layout: 08 MODE lo(v26) lo(v28) hi(v26)|hi(v28)<<4 lo(v24) lo(v2a) hi(v24)|hi(v2a)<<4
    """
    v24, v26, v28, v2a = rect
    a0, a1, a2 = _pack12(v26, v28)
    b0, b1, b2 = _pack12(v24, v2a)
    return bytes([REPORT_COMMAND, mode & 0xFF, a0, a1, a2, b0, b1, b2])


CMD_AREA = 7


def area_command(left: int = 0, top: int = 0, right: int = 4095, bottom: int = 4095) -> bytes:
    """Área ativa em hardware (FUN_00494c6c, TabletMap* do TSetting.ini), em 12 bits.

    Layout: 08 07 hi(l)|hi(t)<<4 lo(l) lo(t) hi(w)|hi(h)<<4 lo(w) lo(h), com w = r-l, h = b-t.
    A mesa guarda a última área recebida (ex.: do driver Windows). Uma área que começa no
    meio do X faz a metade esquerda sair como 0 e a direita esticar a faixa inteira.
    """
    w, h = right - left, bottom - top
    return bytes([REPORT_COMMAND, CMD_AREA,
                  ((left >> 8) & 0x0F) | (((top >> 8) & 0x0F) << 4), left & 0xFF, top & 0xFF,
                  ((w >> 8) & 0x0F) | (((h >> 8) & 0x0F) << 4), w & 0xFF, h & 0xFF])
