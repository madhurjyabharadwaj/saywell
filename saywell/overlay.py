"""The always-on floating bar at the bottom of the screen.

Idle: a slim pill; hovering it shows the hotkey hint and clicking opens Saywell.
Listening: live mic level bars. Processing: pulsing dots. Short messages flash in it.

The window never takes focus (WS_EX_NOACTIVATE), so the text field you dictate
into stays focused. Only the drawn pill receives the mouse: fully transparent
pixels of a layered window are click-through.
"""
import math
import queue
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import win32 as w

WIN_W, WIN_H = 300, 64
BOTTOM_MARGIN = 10
BG = QColor(20, 20, 22, 238)
BG_IDLE = QColor(20, 20, 22, 150)
BORDER = QColor(255, 255, 255, 46)
FG = QColor("#f2f2f2")
ACCENT = QColor("#ff5a5f")


class Overlay(QWidget):
    clicked = Signal()

    def __init__(self, level_fn, hint: str):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(WIN_W, WIN_H)
        self.level_fn = level_fn
        self.hint = hint
        self.enabled = True
        self.cmds: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.mode = "idle"
        self.locked = False
        self.hover = False
        self.message = ""
        self.message_until = 0.0
        self.bars = [0.0] * 9
        self.cur_w, self.cur_h = 44.0, 8.0
        self.font = QFont("Segoe UI", 9)
        self._fullscreen = False
        self._fullscreen_checked = 0.0
        self._timer = QTimer(self, interval=16, timeout=self._tick)
        self._topmost = QTimer(self, interval=1500, timeout=self._keep_on_top)

    # -- thread-safe API (called by the engine from worker threads) ------------
    def set_mode(self, mode: str) -> None:          # idle | listening | processing
        self.cmds.put(("mode", mode))

    def set_locked(self, locked: bool) -> None:
        self.cmds.put(("locked", "1" if locked else ""))

    def flash(self, text: str) -> None:
        self.cmds.put(("flash", text))

    # -- UI thread ----------------------------------------------------------------
    def start(self) -> None:
        self._place()
        screen = QGuiApplication.primaryScreen()
        screen.availableGeometryChanged.connect(lambda *_: self._place())
        self.show()
        self._make_noactivate()
        self._timer.start()
        self._topmost.start()

    def set_hint(self, hint: str) -> None:
        self.hint = hint

    def set_enabled(self, on: bool) -> None:
        self.enabled = on

    def _place(self) -> None:
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.x() + (geo.width() - WIN_W) // 2, geo.y() + geo.height() - WIN_H - BOTTOM_MARGIN)

    def _hwnd(self) -> int:
        return int(self.winId())

    def _make_noactivate(self) -> None:
        hwnd = self._hwnd()
        ex = w.user32.GetWindowLongPtrW(hwnd, w.GWL_EXSTYLE)
        w.user32.SetWindowLongPtrW(hwnd, w.GWL_EXSTYLE, ex | w.WS_EX_NOACTIVATE | w.WS_EX_TOOLWINDOW | w.WS_EX_TOPMOST)

    def _keep_on_top(self) -> None:
        # Clicking the taskbar can push us under it; quietly re-assert topmost.
        if self.isVisible():
            w.user32.SetWindowPos(self._hwnd(), w.HWND_TOPMOST, 0, 0, 0, 0,
                                  w.SWP_NOMOVE | w.SWP_NOSIZE | w.SWP_NOACTIVATE)

    def _target(self, flashing: bool) -> tuple[float, float]:
        if flashing and self.mode == "idle":
            return QFontMetrics(self.font).horizontalAdvance(self.message) + 32, 32
        if self.mode == "listening":
            return (148 if self.locked else 132), 36
        if self.mode == "processing":
            return 96, 32
        if self.hover:
            return QFontMetrics(self.font).horizontalAdvance(self.hint) + 32, 30
        return 44, 8

    def _tick(self) -> None:
        while not self.cmds.empty():
            cmd, arg = self.cmds.get_nowait()
            if cmd == "mode":
                self.mode = arg
                if arg != "listening":
                    self.locked = False
            elif cmd == "locked":
                self.locked = bool(arg)
            elif cmd == "flash":
                self.message, self.message_until = arg, time.monotonic() + 2.5
        flashing = time.monotonic() < self.message_until
        busy = self.mode != "idle" or flashing
        now = time.monotonic()
        if now - self._fullscreen_checked > 0.5:
            self._fullscreen, self._fullscreen_checked = w.fullscreen_app_active(), now
        idle_hidden = not self.enabled or self._fullscreen
        want_visible = busy or not idle_hidden
        if want_visible != self.isVisible():
            self.setVisible(want_visible)
            if want_visible:
                self._make_noactivate()
        if not want_visible:
            return
        tw, th = self._target(flashing)
        if not busy and abs(tw - self.cur_w) < 0.5 and abs(th - self.cur_h) < 0.5:
            return  # idle and settled: nothing to animate
        k = 0.35
        self.cur_w += (tw - self.cur_w) * k
        self.cur_h += (th - self.cur_h) * k
        if self.mode == "listening":
            lvl = min(1.0, self.level_fn() * 12)
            self.bars = self.bars[1:] + [lvl]
        self.update()

    def _pill_rect(self) -> QRectF:
        return QRectF((WIN_W - self.cur_w) / 2, WIN_H - self.cur_h - 4, self.cur_w, self.cur_h)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        idle = self.mode == "idle"
        flashing = time.monotonic() < self.message_until
        if idle and not flashing and not self.hover:
            # Near-invisible halo so the slim pill is easy to hover (alpha 0 would be click-through).
            p.fillRect(QRectF((WIN_W - 90) / 2, WIN_H - 26, 90, 26), QColor(0, 0, 0, 1))
        r = self._pill_rect()
        p.setPen(QPen(BORDER, 1))
        p.setBrush(BG_IDLE if idle and not flashing and not self.hover else BG)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setFont(self.font)
        cx, cy = r.center().x(), r.center().y()
        settled = abs(r.width() - self._target(flashing)[0]) < 4
        if idle and flashing:
            if settled:
                p.setPen(FG)
                p.drawText(r, Qt.AlignCenter, self.message)
        elif idle and self.hover:
            if settled:
                p.setPen(FG)
                p.drawText(r, Qt.AlignCenter, self.hint)
        elif self.mode == "listening":
            p.setPen(Qt.NoPen)
            n = len(self.bars)
            x0 = cx - n * 5 + (8 if self.locked else 0)
            p.setBrush(FG)
            for i, b in enumerate(self.bars):
                h = 3 + b * (r.height() - 14)
                p.drawRoundedRect(QRectF(x0 + i * 10, cy - h / 2, 5, h), 2, 2)
            if self.locked:
                p.setBrush(ACCENT)
                p.drawEllipse(QPointF(r.left() + 18, cy), 4, 4)
        elif self.mode == "processing":
            t = time.monotonic()
            p.setPen(Qt.NoPen)
            for i in range(3):
                a = (math.sin(t * 6 - i * 0.8) + 1) / 2
                g = int(90 + 165 * a)
                p.setBrush(QColor(g, g, g))
                p.drawEllipse(QPointF(cx - 16 + i * 16, cy), 4, 4)
        p.end()

    def enterEvent(self, _ev) -> None:
        self.hover = True

    def leaveEvent(self, _ev) -> None:
        self.hover = False
        self.update()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and self.mode == "idle" and self._pill_rect().adjusted(-20, -20, 20, 4).contains(ev.position()):
            self.clicked.emit()
