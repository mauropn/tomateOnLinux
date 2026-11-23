"""Aplicativo de configuração da mesa TOMATE MTM-1106 (PySide6)."""
from __future__ import annotations

import json
import subprocess
import sys

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QKeyEvent, QPainter,
                           QPainterPath, QPen, QPalette, QTabletEvent)
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QRadioButton, QSlider, QTabWidget, QVBoxLayout, QWidget)

from .. import config as C
from .. import ipc, monitors
from .. import protocol as P
from ..mapping import (TABLET_ASPECT, Mapper, Monitor, PressureCurve, Rect, bounding_box,
                       effective_tablet_area)


def _pal(widget: QWidget):
    p = widget.palette()
    return (p.color(QPalette.Window), p.color(QPalette.WindowText), p.color(QPalette.Highlight),
            p.color(QPalette.Mid), p.color(QPalette.Base))


def _fit(src_w: float, src_h: float, dst: QRectF, margin: float = 16) -> tuple[float, QPointF]:
    """Escala e origem para desenhar um retângulo src dentro de dst mantendo proporção."""
    avail_w, avail_h = dst.width() - 2 * margin, dst.height() - 2 * margin
    s = min(avail_w / src_w, avail_h / src_h) if src_w and src_h else 1
    ox = dst.x() + (dst.width() - src_w * s) / 2
    oy = dst.y() + (dst.height() - src_h * s) / 2
    return s, QPointF(ox, oy)


# ===================================================================== daemon link
class DaemonLink(QObject):
    """Assina o stream do daemon e reconecta automaticamente."""
    pen = Signal(dict)
    button = Signal(str, bool)
    status = Signal(dict)
    linked = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.sock = QLocalSocket(self)
        self.sock.connected.connect(self._on_connected)
        self.sock.disconnected.connect(self._on_lost)
        self.sock.readyRead.connect(self._read)
        self.sock.errorOccurred.connect(self._on_lost)
        self.buf = b""
        self.timer = QTimer(self, interval=2000, timeout=self._ensure)
        self.timer.start()
        QTimer.singleShot(0, self._ensure)  # depois que a janela conectar os sinais

    def _on_lost(self, *_):
        if self.sock.state() != QLocalSocket.ConnectedState:
            self.linked.emit(False)

    def _ensure(self) -> None:
        if self.sock.state() == QLocalSocket.UnconnectedState:
            self.sock.connectToServer(ipc.socket_path())

    def _on_connected(self) -> None:
        self.linked.emit(True)
        self.sock.write(ipc.encode({"cmd": "subscribe"}))

    def _read(self) -> None:
        self.buf += bytes(self.sock.readAll().data())
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            ev = msg.get("ev")
            if ev == "pen":
                self.pen.emit(msg)
            elif ev == "button":
                self.button.emit(msg["id"], msg["down"])
            elif ev == "status":
                self.status.emit(msg)

    def send(self, msg: dict) -> None:
        if self.sock.state() == QLocalSocket.ConnectedState:
            self.sock.write(ipc.encode(msg))


# ===================================================================== monitores
class MonitorCanvas(QWidget):
    """Desenha o layout real dos monitores; clique escolhe o alvo, arrasto define região."""
    picked = Signal(str)          # Monitor.key ou "all"
    region_changed = Signal(object)  # Rect

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(260)
        self.monitors: list[Monitor] = []
        self.target = "all"
        self.monitor_key = ""
        self.region = Rect(0, 0, 0, 0)
        self._drag = None

    def set_state(self, mons, target, key, region):
        self.monitors, self.target, self.monitor_key, self.region = mons, target, key, region
        self.update()

    def _xf(self):
        box = bounding_box(self.monitors)
        s, o = _fit(box.w, box.h, QRectF(self.rect()))
        return box, s, o

    def _to_screen(self, r: Rect) -> QRectF:
        box, s, o = self._xf()
        return QRectF(o.x() + (r.x - box.x) * s, o.y() + (r.y - box.y) * s, r.w * s, r.h * s)

    def _to_desktop(self, p: QPointF) -> tuple[float, float]:
        box, s, o = self._xf()
        return box.x + (p.x() - o.x()) / s, box.y + (p.y() - o.y()) / s

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        _bg, fg, hi, mid, base = _pal(self)
        if not self.monitors:
            qp.setPen(fg)
            qp.drawText(self.rect(), Qt.AlignCenter, "Nenhum monitor detectado")
            return
        all_sel = self.target == "all"
        for m in self.monitors:
            r = self._to_screen(m.rect).adjusted(2, 2, -2, -2)
            sel = all_sel or (self.target == "monitor" and self.monitor_key == m.key)
            qp.setPen(QPen(hi if sel else mid, 3 if sel else 1.5))
            qp.setBrush(QColor(hi.red(), hi.green(), hi.blue(), 60) if sel else base)
            qp.drawRoundedRect(r, 8, 8)
            qp.setPen(fg)
            f = QFont(self.font())
            f.setBold(True)
            qp.setFont(f)
            qp.drawText(r.adjusted(8, 8, -8, -8), Qt.AlignTop | Qt.AlignLeft,
                        f"{m.connector}{'  (embutido)' if m.builtin else ''}")
            qp.setFont(self.font())
            qp.drawText(r.adjusted(8, 8, -8, -8), Qt.AlignCenter,
                        f"{m.name}\n{int(m.rect.w)}×{int(m.rect.h)}")
        if self.target == "region" and self.region.w > 0:
            qp.setPen(QPen(hi, 2, Qt.DashLine))
            qp.setBrush(QColor(hi.red(), hi.green(), hi.blue(), 90))
            qp.drawRect(self._to_screen(self.region))

    def mousePressEvent(self, e):
        if self.target == "region":
            self._drag = self._to_desktop(e.position())
            return
        x, y = self._to_desktop(e.position())
        for m in self.monitors:
            r = m.rect
            if r.x <= x <= r.x + r.w and r.y <= y <= r.y + r.h:
                self.picked.emit(m.key)
                return

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        x0, y0 = self._drag
        x1, y1 = self._to_desktop(e.position())
        box = bounding_box(self.monitors)
        x0, x1 = sorted((max(box.x, min(x0, box.x + box.w)), max(box.x, min(x1, box.x + box.w))))
        y0, y1 = sorted((max(box.y, min(y0, box.y + box.h)), max(box.y, min(y1, box.y + box.h))))
        self.region = Rect(round(x0), round(y0), round(x1 - x0), round(y1 - y0))
        self.update()

    def mouseReleaseEvent(self, _):
        if self._drag is not None:
            self._drag = None
            if self.region.w > 10 and self.region.h > 10:
                self.region_changed.emit(self.region)


class IdentifyOverlay(QWidget):
    def __init__(self, screen, text: str) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.text = text
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        QTimer.singleShot(2500, self.close)

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.fillRect(self.rect(), QColor(0, 0, 0, 140))
        f = QFont(self.font())
        f.setPointSize(48)
        f.setBold(True)
        qp.setFont(f)
        qp.setPen(Qt.white)
        qp.drawText(self.rect(), Qt.AlignCenter, self.text)

    def mousePressEvent(self, _):
        self.close()


class MonitorsTab(QWidget):
    changed = Signal()

    def __init__(self, cfg: C.Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.monitors: list[Monitor] = []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Escolha para onde a mesa aponta. Clique num monitor para usá-lo, "
                             "ou arraste para desenhar uma região."))
        row = QHBoxLayout()
        self.rb_all = QRadioButton("Todos os monitores")
        self.rb_mon = QRadioButton("Um monitor")
        self.rb_reg = QRadioButton("Região personalizada")
        self.group = QButtonGroup(self)
        for i, rb in enumerate((self.rb_all, self.rb_mon, self.rb_reg)):
            self.group.addButton(rb, i)
            row.addWidget(rb)
        row.addStretch()
        self.btn_identify = QPushButton("Identificar monitores")
        self.btn_refresh = QPushButton("Atualizar")
        row.addWidget(self.btn_identify)
        row.addWidget(self.btn_refresh)
        lay.addLayout(row)
        self.canvas = MonitorCanvas()
        lay.addWidget(self.canvas, 1)
        form = QHBoxLayout()
        self.combo = QComboBox()
        form.addWidget(QLabel("Monitor:"))
        form.addWidget(self.combo, 1)
        self.keep_aspect = QCheckBox("Manter proporção (sem distorcer o traço)")
        form.addWidget(self.keep_aspect)
        form.addWidget(QLabel("Rotação:"))
        self.rotation = QComboBox()
        for deg, label in ((0, "0° (normal)"), (90, "90°"), (180, "180° (canhoto)"), (270, "270°")):
            self.rotation.addItem(label, deg)
        form.addWidget(self.rotation)
        lay.addLayout(form)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        tip = QLabel("Dica: na aba Botões, associe a ação “Alternar monitor” a um botão da mesa "
                     "para trocar de monitor sem abrir este app.")
        tip.setWordWrap(True)
        tip.setEnabled(False)
        lay.addWidget(tip)

        self.group.idClicked.connect(self._mode_changed)
        self.canvas.picked.connect(self._picked)
        self.canvas.region_changed.connect(self._region)
        self.combo.activated.connect(lambda i: self._picked(self.combo.itemData(i)))
        self.keep_aspect.toggled.connect(self._aspect)
        self.rotation.activated.connect(self._rotation)
        self.btn_identify.clicked.connect(self.identify)
        self.btn_refresh.clicked.connect(self.refresh_monitors)
        self.refresh_monitors()

    def refresh_monitors(self, mons: list[Monitor] | None = None) -> None:
        self.monitors = mons if mons is not None else monitors.list_monitors()
        self.combo.clear()
        for m in self.monitors:
            self.combo.addItem(f"{m.connector} — {m.name} ({int(m.rect.w)}×{int(m.rect.h)})", m.key)
        self.sync()

    def sync(self) -> None:
        m = self.cfg.mapping
        {"all": self.rb_all, "monitor": self.rb_mon, "region": self.rb_reg}[m.target].setChecked(True)
        idx = self.combo.findData(m.monitor)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self.combo.setEnabled(m.target == "monitor")
        self.keep_aspect.setChecked(m.keep_aspect)
        self.rotation.setCurrentIndex(self.rotation.findData(m.rotation))
        self.canvas.set_state(self.monitors, m.target, m.monitor, m.region)
        mp = Mapper(m, self.monitors)
        o = mp.output
        msg = f"Saída: {int(o.w)}×{int(o.h)} em ({int(o.x)}, {int(o.y)})."
        if m.target == "monitor" and mp.effective_target == "all":
            msg += "  ⚠ O monitor escolhido não está conectado: usando todos os monitores."
        a = mp.area
        msg += f"  Área usada da mesa: {a.w * 100:.0f}% × {a.h * 100:.0f}%."
        self.info.setText(msg)

    def _mode_changed(self, i: int) -> None:
        m = self.cfg.mapping
        m.target = ("all", "monitor", "region")[i]
        if m.target == "monitor" and not any(x.key == m.monitor for x in self.monitors) and self.monitors:
            m.monitor = self.monitors[0].key
        if m.target == "region" and m.region.w <= 0:
            m.region = self.monitors[0].rect if self.monitors else Rect(0, 0, 1920, 1080)
        self.sync()
        self.changed.emit()

    def _picked(self, key: str) -> None:
        self.cfg.mapping.target, self.cfg.mapping.monitor = "monitor", key
        self.sync()
        self.changed.emit()

    def _region(self, r: Rect) -> None:
        self.cfg.mapping.region = r
        self.sync()
        self.changed.emit()

    def _aspect(self, on: bool) -> None:
        if self.cfg.mapping.keep_aspect != on:
            self.cfg.mapping.keep_aspect = on
            self.sync()
            self.changed.emit()

    def _rotation(self, i: int) -> None:
        self.cfg.mapping.rotation = self.rotation.itemData(i)
        self.sync()
        self.changed.emit()

    def identify(self) -> None:
        by_conn = {m.connector: m for m in self.monitors}
        self._overlays = []
        for scr in QGuiApplication.screens():
            m = by_conn.get(scr.name())
            text = f"{scr.name()}\n{m.name}" if m else scr.name()
            self._overlays.append(IdentifyOverlay(scr, text))


# ===================================================================== área da mesa
class TabletAreaCanvas(QWidget):
    area_changed = Signal(object)  # Rect normalizado

    HANDLE = 10

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(280)
        self.area = Rect(0, 0, 1, 1)
        self.effective = Rect(0, 0, 1, 1)
        self.pen_pos: tuple[float, float, bool] | None = None
        self._drag = None

    def _frame(self) -> QRectF:
        s, o = _fit(TABLET_ASPECT, 1.0, QRectF(self.rect()), 36)
        return QRectF(o.x(), o.y(), TABLET_ASPECT * s, s)

    def _r(self, a: Rect) -> QRectF:
        f = self._frame()
        return QRectF(f.x() + a.x * f.width(), f.y() + a.y * f.height(),
                      a.w * f.width(), a.h * f.height())

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        _bg, fg, hi, mid, base = _pal(self)
        f = self._frame()
        qp.setPen(QPen(mid, 2))
        qp.setBrush(base)
        qp.drawRoundedRect(f.adjusted(-10, -10, 10, 10), 14, 14)
        qp.setPen(QPen(mid, 1, Qt.DotLine))
        qp.drawRect(f)
        ar = self._r(self.area)
        qp.setPen(QPen(hi, 1.5, Qt.DashLine))
        qp.setBrush(Qt.NoBrush)
        qp.drawRect(ar)
        er = self._r(self.effective)
        qp.setPen(QPen(hi, 2.5))
        qp.setBrush(QColor(hi.red(), hi.green(), hi.blue(), 55))
        qp.drawRect(er)
        qp.setBrush(hi)
        for c in (ar.topLeft(), ar.topRight(), ar.bottomLeft(), ar.bottomRight()):
            qp.drawRect(QRectF(c.x() - self.HANDLE / 2, c.y() - self.HANDLE / 2, self.HANDLE, self.HANDLE))
        qp.setPen(fg)
        qp.drawText(QPointF(f.x(), f.y() - 16), "Superfície da mesa")
        if self.pen_pos:
            x, y, tip = self.pen_pos
            p = QPointF(f.x() + x * f.width(), f.y() + y * f.height())
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(220, 60, 60) if tip else QColor(60, 140, 220))
            qp.drawEllipse(p, 6, 6)

    def _norm(self, p: QPointF) -> tuple[float, float]:
        f = self._frame()
        return (min(max((p.x() - f.x()) / f.width(), 0), 1),
                min(max((p.y() - f.y()) / f.height(), 0), 1))

    def mousePressEvent(self, e):
        ar = self._r(self.area)
        p = e.position()
        corners = {"tl": ar.topLeft(), "tr": ar.topRight(), "bl": ar.bottomLeft(), "br": ar.bottomRight()}
        for name, c in corners.items():
            if abs(p.x() - c.x()) <= self.HANDLE and abs(p.y() - c.y()) <= self.HANDLE:
                self._drag = (name, None)
                return
        if ar.contains(p):
            self._drag = ("move", (self._norm(p), self.area))
        else:
            self._drag = ("new", self._norm(p))

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        kind, data = self._drag
        nx, ny = self._norm(e.position())
        a = self.area
        x0, y0, x1, y1 = a.x, a.y, a.x + a.w, a.y + a.h
        if kind == "move":
            (sx, sy), orig = data
            dx = min(max(nx - sx, -orig.x), 1 - orig.x - orig.w)
            dy = min(max(ny - sy, -orig.y), 1 - orig.y - orig.h)
            self.area = Rect(orig.x + dx, orig.y + dy, orig.w, orig.h)
        else:
            if kind == "new":
                x0, y0 = data
                x1, y1 = nx, ny
            if kind in ("tl", "bl"):
                x0 = nx
            if kind in ("tr", "br"):
                x1 = nx
            if kind in ("tl", "tr"):
                y0 = ny
            if kind in ("bl", "br"):
                y1 = ny
            x0, x1 = sorted((x0, x1))
            y0, y1 = sorted((y0, y1))
            self.area = Rect(x0, y0, max(x1 - x0, 0.05), max(y1 - y0, 0.05))
        self.update()

    def mouseReleaseEvent(self, _):
        if self._drag:
            self._drag = None
            self.area_changed.emit(self.area)


class AreaTab(QWidget):
    changed = Signal()

    def __init__(self, cfg: C.Config, mons_tab: MonitorsTab) -> None:
        super().__init__()
        self.cfg, self.mons_tab = cfg, mons_tab
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Arraste os cantos ou o retângulo para escolher a parte da mesa "
                             "que será usada. A área cheia (contorno sólido) é a efetivamente "
                             "usada depois de manter a proporção."))
        self.canvas = TabletAreaCanvas()
        lay.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        self.spins = []
        for label in ("X %", "Y %", "Largura %", "Altura %"):
            sp = QDoubleSpinBox(decimals=1, minimum=0, maximum=100, singleStep=1)
            row.addWidget(QLabel(label))
            row.addWidget(sp)
            self.spins.append(sp)
            sp.editingFinished.connect(self._from_spins)
        full = QPushButton("Mesa inteira")
        full.clicked.connect(lambda: self._set(Rect(0, 0, 1, 1)))
        row.addStretch()
        row.addWidget(full)
        lay.addLayout(row)
        self.canvas.area_changed.connect(self._set)
        self.sync()

    def sync(self) -> None:
        m = self.cfg.mapping
        mp = Mapper(m, self.mons_tab.monitors)
        self.canvas.area = m.tablet_area
        self.canvas.effective = effective_tablet_area(m, mp.output)
        for sp, v in zip(self.spins, (m.tablet_area.x, m.tablet_area.y, m.tablet_area.w, m.tablet_area.h)):
            sp.blockSignals(True)
            sp.setValue(v * 100)
            sp.blockSignals(False)
        self.canvas.update()

    def _from_spins(self) -> None:
        x, y, w, h = (sp.value() / 100 for sp in self.spins)
        w, h = max(min(w, 1 - x), 0.05), max(min(h, 1 - y), 0.05)
        self._set(Rect(x, y, w, h))

    def _set(self, r: Rect) -> None:
        self.cfg.mapping.tablet_area = r
        self.sync()
        self.changed.emit()

    def on_pen(self, msg: dict) -> None:
        self.canvas.pen_pos = ((msg["x"] / P.RAW_X_MAX, msg["y"] / P.RAW_Y_MAX, msg["tip"])
                               if msg["range"] else None)
        self.canvas.update()


# ===================================================================== pressão
class CurveEditor(QWidget):
    curve_changed = Signal()

    def __init__(self, curve: PressureCurve) -> None:
        super().__init__()
        self.curve = curve
        self.setMinimumSize(300, 300)
        self.live: tuple[float, float] | None = None
        self._drag = None

    def _box(self) -> QRectF:
        side = min(self.width(), self.height()) - 40
        return QRectF((self.width() - side) / 2, 20, side, side)

    def _pt(self, x, y) -> QPointF:
        b = self._box()
        return QPointF(b.x() + x * b.width(), b.bottom() - y * b.height())

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        _bg, fg, hi, mid, base = _pal(self)
        b = self._box()
        qp.fillRect(b, base)
        qp.setPen(QPen(mid, 1, Qt.DotLine))
        for i in range(1, 4):
            qp.drawLine(self._pt(i / 4, 0), self._pt(i / 4, 1))
            qp.drawLine(self._pt(0, i / 4), self._pt(1, i / 4))
        qp.setPen(QPen(mid, 1))
        qp.drawRect(b)
        qp.drawLine(self._pt(0, 0), self._pt(1, 1))
        path = QPainterPath(self._pt(0, 0))
        for i in range(1, 201):
            x = i / 200
            path.lineTo(self._pt(x, self.curve.apply_unit(x)))
        qp.setPen(QPen(hi, 3))
        qp.drawPath(path)
        qp.setPen(QPen(mid, 1, Qt.DashLine))
        qp.drawLine(self._pt(0, 0), self._pt(*self.curve.p1))
        qp.drawLine(self._pt(1, 1), self._pt(*self.curve.p2))
        qp.setPen(QPen(fg, 1.5))
        qp.setBrush(hi)
        for p in (self.curve.p1, self.curve.p2):
            qp.drawEllipse(self._pt(*p), 7, 7)
        qp.setPen(fg)
        qp.drawText(QRectF(b.x(), b.bottom() + 2, b.width(), 18), Qt.AlignCenter, "pressão da caneta →")
        if self.live:
            qp.setBrush(QColor(220, 60, 60))
            qp.setPen(Qt.NoPen)
            qp.drawEllipse(self._pt(*self.live), 6, 6)

    def mousePressEvent(self, e):
        p = e.position()
        for name in ("p1", "p2"):
            c = self._pt(*getattr(self.curve, name))
            if (c - p).manhattanLength() < 18:
                self._drag = name
                return

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        b = self._box()
        x = min(max((e.position().x() - b.x()) / b.width(), 0), 1)
        y = min(max((b.bottom() - e.position().y()) / b.height(), 0), 1)
        setattr(self.curve, self._drag, (round(x, 3), round(y, 3)))
        self.update()

    def mouseReleaseEvent(self, _):
        if self._drag:
            self._drag = None
            self.curve_changed.emit()


class PressureTab(QWidget):
    changed = Signal()
    PRESETS = {
        "Muito suave": ((0.0, 0.7), (0.3, 1.0)),
        "Suave": ((0.1, 0.4), (0.6, 0.95)),
        "Linear": ((0.25, 0.25), (0.75, 0.75)),
        "Firme": ((0.4, 0.1), (0.95, 0.6)),
        "Muito firme": ((0.7, 0.0), (1.0, 0.3)),
    }

    def __init__(self, cfg: C.Config) -> None:
        super().__init__()
        self.cfg = cfg
        lay = QHBoxLayout(self)
        self.editor = CurveEditor(cfg.pressure)
        lay.addWidget(self.editor, 2)
        side = QVBoxLayout()
        lay.addLayout(side, 1)
        side.addWidget(QLabel("Arraste os dois pontos para mudar a curva."))
        grid = QGridLayout()
        for i, name in enumerate(self.PRESETS):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, n=name: self._preset(n))
            grid.addWidget(b, i // 2, i % 2)
        side.addLayout(grid)
        form = QFormLayout()
        self.threshold = QSlider(Qt.Horizontal, minimum=0, maximum=30)
        self.saturation = QSlider(Qt.Horizontal, minimum=50, maximum=100)
        form.addRow("Pressão mínima (limiar):", self.threshold)
        form.addRow("Pressão máxima (saturação):", self.saturation)
        side.addLayout(form)
        self.bar_raw = QProgressBar(maximum=P.RAW_PRESSURE_MAX, format="caneta: %v")
        self.bar_out = QProgressBar(maximum=P.RAW_PRESSURE_MAX, format="saída: %v")
        side.addWidget(QLabel("Teste ao vivo (pressione a caneta na mesa):"))
        side.addWidget(self.bar_raw)
        side.addWidget(self.bar_out)
        self.peak = QLabel("Pico: 0")
        side.addWidget(self.peak)
        side.addStretch()
        self._peak = 0
        self.editor.curve_changed.connect(self.changed)
        self.threshold.sliderReleased.connect(self._sliders)
        self.saturation.sliderReleased.connect(self._sliders)
        self.threshold.valueChanged.connect(self._sliders_live)
        self.saturation.valueChanged.connect(self._sliders_live)
        self.sync()

    def sync(self) -> None:
        self.editor.curve = self.cfg.pressure
        for s, v in ((self.threshold, self.cfg.pressure.threshold), (self.saturation, self.cfg.pressure.saturation)):
            s.blockSignals(True)
            s.setValue(round(v * 100))
            s.blockSignals(False)
        self.editor.update()

    def _preset(self, name: str) -> None:
        self.cfg.pressure.p1, self.cfg.pressure.p2 = self.PRESETS[name]
        self.editor.update()
        self.changed.emit()

    def _sliders_live(self) -> None:
        self.cfg.pressure.threshold = self.threshold.value() / 100
        self.cfg.pressure.saturation = self.saturation.value() / 100
        self.editor.update()

    def _sliders(self) -> None:
        self._sliders_live()
        self.changed.emit()

    def on_pen(self, msg: dict) -> None:
        raw = msg["p"] if msg["tip"] else 0
        self.bar_raw.setValue(raw)
        self.bar_out.setValue(msg["po"])
        if raw > self._peak:
            self._peak = raw
            self.peak.setText(f"Pico: {raw} de {P.RAW_PRESSURE_MAX}")
        self.editor.live = (raw / P.RAW_PRESSURE_MAX, msg["po"] / P.RAW_PRESSURE_MAX) if raw else None
        self.editor.update()


# ===================================================================== botões
_QT_KEY_NAMES = {
    **{getattr(Qt, f"Key_{c}"): c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
    **{getattr(Qt, f"Key_F{i}"): f"F{i}" for i in range(1, 13)},
    Qt.Key_Escape: "Esc", Qt.Key_Tab: "Tab", Qt.Key_Backspace: "Backspace", Qt.Key_Return: "Enter",
    Qt.Key_Enter: "Enter", Qt.Key_Space: "Space", Qt.Key_Minus: "Minus", Qt.Key_Equal: "Equal",
    Qt.Key_Plus: "Equal", Qt.Key_BracketLeft: "BracketLeft", Qt.Key_BracketRight: "BracketRight",
    Qt.Key_Semicolon: "Semicolon", Qt.Key_Apostrophe: "Apostrophe", Qt.Key_Comma: "Comma",
    Qt.Key_Period: "Period", Qt.Key_Slash: "Slash", Qt.Key_Backslash: "Backslash",
    Qt.Key_Home: "Home", Qt.Key_End: "End", Qt.Key_PageUp: "PageUp", Qt.Key_PageDown: "PageDown",
    Qt.Key_Left: "Left", Qt.Key_Right: "Right", Qt.Key_Up: "Up", Qt.Key_Down: "Down",
    Qt.Key_Insert: "Insert", Qt.Key_Delete: "Delete",
}


class ShortcutEdit(QLineEdit):
    """Campo que captura a próxima combinação de teclas pressionada."""
    captured = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("clique e pressione o atalho")
        self.setReadOnly(True)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        mods = e.modifiers()
        parts = [n for flag, n in ((Qt.ControlModifier, "Ctrl"), (Qt.ShiftModifier, "Shift"),
                                   (Qt.AltModifier, "Alt"), (Qt.MetaModifier, "Super")) if mods & flag]
        name = _QT_KEY_NAMES.get(e.key())
        if name is None:
            return  # só modificador por enquanto
        text = "+".join(parts + [name])
        self.setText(text)
        self.captured.emit(text)


ACTIONS = [("default", "Padrão de fábrica"), ("key", "Atalho de teclado"),
           ("mouse:MouseLeft", "Clique esquerdo"), ("mouse:MouseRight", "Clique direito"),
           ("mouse:MouseMiddle", "Clique do meio"), ("wheel:WheelUp", "Rolar para cima"),
           ("wheel:WheelDown", "Rolar para baixo"), ("cycle_monitor", "Alternar monitor"),
           ("disabled", "Desativado")]
PEN_ACTIONS = [("stylus", "Botão 1 da caneta (padrão do sistema)"),
               ("stylus2", "Botão 2 da caneta (padrão do sistema)")] + ACTIONS[1:]


class ButtonRow(QWidget):
    changed = Signal(str, str)

    def __init__(self, bid: str, label: str, action: str, actions) -> None:
        super().__init__()
        self.bid = bid
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.name = QLabel(label)
        self.name.setMinimumWidth(170)
        self.name.setAutoFillBackground(True)
        lay.addWidget(self.name)
        self.combo = QComboBox()
        for data, text in actions:
            self.combo.addItem(text, data)
        lay.addWidget(self.combo, 1)
        self.shortcut = ShortcutEdit()
        lay.addWidget(self.shortcut, 1)
        kind = "key" if action.startswith("key:") else action
        idx = self.combo.findData(kind)
        self.combo.setCurrentIndex(max(idx, 0))
        self.shortcut.setText(action[4:] if action.startswith("key:") else "")
        self.shortcut.setVisible(kind == "key")
        self.combo.activated.connect(self._combo)
        self.shortcut.captured.connect(lambda t: self.changed.emit(self.bid, "key:" + t))

    def _combo(self, _i) -> None:
        data = self.combo.currentData()
        self.shortcut.setVisible(data == "key")
        if data == "key":
            self.shortcut.setFocus()
            if self.shortcut.text():
                self.changed.emit(self.bid, "key:" + self.shortcut.text())
        else:
            self.changed.emit(self.bid, data)

    def flash(self, down: bool) -> None:
        pal = self.name.palette()
        pal.setColor(QPalette.Window, self.palette().color(QPalette.Highlight) if down
                     else self.palette().color(QPalette.Window))
        self.name.setPalette(pal)


class ButtonsTab(QWidget):
    changed = Signal()

    def __init__(self, cfg: C.Config) -> None:
        super().__init__()
        self.cfg = cfg
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Aperte um botão da mesa para ver qual é (ele fica destacado)."))
        self.rows: dict[str, ButtonRow] = {}
        box = QGroupBox("Botões da mesa")
        bl = QVBoxLayout(box)
        for i, bid in enumerate(C.BUTTON_IDS):
            r = ButtonRow(bid, f"Botão {i + 1}  ({P.BUTTON_FACTORY_LABEL[bid]})",
                          cfg.buttons.get(bid, "default"), ACTIONS)
            r.changed.connect(self._set)
            bl.addWidget(r)
            self.rows[bid] = r
        lay.addWidget(box)
        pbox = QGroupBox("Botões da caneta")
        pl = QVBoxLayout(pbox)
        for i, bid in enumerate(C.PEN_BUTTON_IDS):
            r = ButtonRow(bid, f"Botão lateral {i + 1}", cfg.pen_buttons.get(bid, "stylus"), PEN_ACTIONS)
            r.changed.connect(self._set)
            pl.addWidget(r)
            self.rows[bid] = r
        lay.addWidget(pbox)
        lay.addStretch()

    def _set(self, bid: str, action: str) -> None:
        target = self.cfg.pen_buttons if bid.startswith("PEN") else self.cfg.buttons
        target[bid] = action
        self.changed.emit()

    def on_button(self, bid: str, down: bool) -> None:
        if bid in self.rows:
            self.rows[bid].flash(down)
            if bid in P.WHEEL_BUTTONS.values() and down:
                QTimer.singleShot(250, lambda: self.rows[bid].flash(False))

    def on_pen(self, msg: dict) -> None:
        self.rows["PEN1"].flash(bool(msg.get("b1")))
        self.rows["PEN2"].flash(bool(msg.get("b2")))


# ===================================================================== teste
class DrawCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(300)
        self.strokes: list[list[tuple[QPointF, float]]] = []
        self.setAttribute(Qt.WA_TabletTracking)

    def tabletEvent(self, e: QTabletEvent) -> None:
        pt, pr = e.position(), e.pressure()
        if e.type() == QTabletEvent.TabletPress:
            self.strokes.append([(pt, pr)])
        elif e.type() == QTabletEvent.TabletMove and e.buttons() & Qt.LeftButton and self.strokes:
            self.strokes[-1].append((pt, pr))
        e.accept()
        self.update()

    def mousePressEvent(self, e):
        self.strokes.append([(e.position(), 0.5)])

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self.strokes:
            self.strokes[-1].append((e.position(), 0.5))
            self.update()

    def clear(self) -> None:
        self.strokes.clear()
        self.update()

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        _bg, fg, _hi, mid, base = _pal(self)
        qp.fillRect(self.rect(), base)
        qp.setPen(QPen(mid, 1))
        qp.drawRect(self.rect().adjusted(0, 0, -1, -1))
        for st in self.strokes:
            for (a, pa), (b, pb) in zip(st, st[1:]):
                qp.setPen(QPen(fg, 0.5 + 12 * (pa + pb) / 2, Qt.SolidLine, Qt.RoundCap))
                qp.drawLine(a, b)


class TestTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Desenhe com a caneta: a espessura do traço segue a pressão."))
        row.addStretch()
        self.readout = QLabel("—")
        row.addWidget(self.readout)
        clear = QPushButton("Limpar")
        row.addWidget(clear)
        lay.addLayout(row)
        self.canvas = DrawCanvas()
        lay.addWidget(self.canvas, 1)
        clear.clicked.connect(self.canvas.clear)

    def on_pen(self, msg: dict) -> None:
        if msg["range"]:
            self.readout.setText(f"X {msg['x']}  Y {msg['y']}  pressão {msg['p'] if msg['tip'] else 0}"
                                 f" → {msg['po']}  {'[botão 1]' if msg.get('b1') else ''}"
                                 f"{'[botão 2]' if msg.get('b2') else ''}")
        else:
            self.readout.setText("caneta fora de alcance")


# ===================================================================== janela
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TOMATE MTM-1106 — Configuração da mesa")
        self.resize(980, 680)
        self.cfg = C.load()
        tabs = QTabWidget()
        self.mons = MonitorsTab(self.cfg)
        self.area = AreaTab(self.cfg, self.mons)
        self.pressure = PressureTab(self.cfg)
        self.buttons = ButtonsTab(self.cfg)
        self.test = TestTab()
        tabs.addTab(self.mons, "Monitores")
        tabs.addTab(self.area, "Área da mesa")
        tabs.addTab(self.pressure, "Pressão")
        tabs.addTab(self.buttons, "Botões")
        tabs.addTab(self.test, "Teste")
        self.setCentralWidget(tabs)
        self.daemon_label = QLabel()
        self.tablet_label = QLabel()
        self.statusBar().addWidget(self.daemon_label)
        self.statusBar().addWidget(self.tablet_label)
        self.btn_start = QPushButton("Iniciar serviço")
        self.btn_start.clicked.connect(self.start_daemon)
        self.statusBar().addPermanentWidget(self.btn_start)

        self.save_timer = QTimer(self, singleShot=True, interval=250, timeout=self.apply)
        for t in (self.mons, self.area, self.pressure, self.buttons):
            t.changed.connect(self.save_timer.start)
        self.mons.changed.connect(self.area.sync)

        self.link = DaemonLink()
        self.link.linked.connect(self._daemon_state)
        self.link.status.connect(self._status)
        self.link.pen.connect(self._pen)
        self.link.button.connect(self.buttons.on_button)
        self._daemon_state(False)

    def apply(self) -> None:
        C.save(self.cfg)
        self.link.send({"cmd": "reload"})

    def _pen(self, msg: dict) -> None:
        current = self.centralWidget().currentWidget()
        if current is self.area:
            self.area.on_pen(msg)
        elif current is self.pressure:
            self.pressure.on_pen(msg)
        elif current is self.buttons:
            self.buttons.on_pen(msg)
        elif current is self.test:
            self.test.on_pen(msg)

    def _daemon_state(self, ok: bool) -> None:
        self.daemon_label.setText("Serviço: ● rodando" if ok else "Serviço: ○ parado")
        self.btn_start.setVisible(not ok)
        if not ok:
            self.tablet_label.setText("")

    def _status(self, st: dict) -> None:
        self.tablet_label.setText("Mesa: conectada" if st.get("connected") else "Mesa: desconectada")
        mons = [Monitor(m["key"], m["connector"], m["name"], Rect(*m["rect"]), m["builtin"])
                for m in st.get("monitors", [])]
        # o daemon pode ter alternado o monitor pelo botão da mesa
        fresh = C.load()
        self.cfg.mapping.target, self.cfg.mapping.monitor = fresh.mapping.target, fresh.mapping.monitor
        if mons != self.mons.monitors:
            self.mons.refresh_monitors(mons)
        else:
            self.mons.sync()
        self.area.sync()

    def start_daemon(self) -> None:
        r = subprocess.run(["systemctl", "--user", "start", "tomate-daemon.service"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.Popen([sys.executable, "-m", "tomate.daemon"], start_new_session=True)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("tomate")
    app.setDesktopFileName("tomate")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
