"""Saywell's main window (History + Settings) and tray icon."""
import copy
import datetime as dt
import json
import os
import threading
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMenu, QPlainTextEdit, QPushButton, QScrollArea,
                               QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import keystore, shortcuts
from .app import App, pretty_keys
from .config import APP_NAME, VERSION, asset, data_dir, save_config, settings_path

HOTKEY_PRESETS = [["ctrl", "win"], ["ctrl", "alt"], ["ralt"], ["rctrl"]]
PASTE_LAST_PRESETS = [["alt", "shift", "z"], ["ctrl", "alt", "v"], []]

_APP_NAMES = {"windowsterminal": "Terminal", "code": "VS Code", "winword": "Word", "outlook": "Outlook",
              "msedge": "Edge", "chrome": "Chrome", "firefox": "Firefox", "excel": "Excel", "powerpnt": "PowerPoint",
              "olk": "Outlook", "ms-teams": "Teams", "explorer": "File Explorer", "notepad": "Notepad"}

LIGHT = dict(bg="#f7f7f8", side="#eeeef1", surface="#ffffff", border="#e3e3e8", text="#18181b", muted="#6b6b76",
             accent="#e8435f", accent_hover="#d23752", accent_text="#ffffff", soft="#fbe7eb", warn="#9a5b00",
             warn_bg="#fff6e5", input="#ffffff", sel="#f3d3da", chevron="chevron_light.svg")
DARK = dict(bg="#161619", side="#1c1c20", surface="#222227", border="#303037", text="#ececf0", muted="#9b9ba6",
            accent="#f0566f", accent_hover="#ff6b82", accent_text="#ffffff", soft="#3a2329", warn="#f2b456",
            warn_bg="#33291a", input="#1b1b1f", sel="#5a2e37", chevron="chevron_dark.svg")


def stylesheet(t: dict) -> str:
    check = asset("check.svg").replace("\\", "/")
    chevron = asset(t["chevron"]).replace("\\", "/")
    return f"""
    QWidget {{ color: {t['text']}; font-family: 'Segoe UI'; font-size: 10pt; }}
    QMainWindow, #page, #scrollBody {{ background: {t['bg']}; }}
    QScrollArea {{ border: none; background: {t['bg']}; }}
    #sidebar {{ background: {t['side']}; border-right: 1px solid {t['border']}; }}
    #brand {{ font-size: 15pt; font-weight: 600; }}
    #nav {{ text-align: left; padding: 8px 12px; border: none; border-radius: 8px; background: transparent; color: {t['muted']}; }}
    #nav:hover {{ background: {t['border']}; color: {t['text']}; }}
    #nav:checked {{ background: {t['surface']}; color: {t['text']}; font-weight: 600; }}
    #hintCard {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    #hintTitle {{ font-weight: 600; }}
    #muted, #hint {{ color: {t['muted']}; }}
    #hint {{ font-size: 9pt; }}
    #title {{ font-size: 20pt; font-weight: 600; }}
    #day {{ color: {t['muted']}; font-weight: 600; font-size: 9pt; padding-top: 10px; }}
    #card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    #failedCard {{ background: {t['warn_bg']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    #appTag {{ color: {t['muted']}; background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 1px 6px; font-size: 8.5pt; }}
    #body {{ font-size: 10.5pt; }}
    #warn {{ color: {t['warn']}; }}
    #empty {{ color: {t['muted']}; font-size: 11pt; padding: 40px; }}
    #section {{ font-size: 11.5pt; font-weight: 600; padding-top: 14px; }}
    QLineEdit, QPlainTextEdit, QComboBox {{ background: {t['input']}; border: 1px solid {t['border']}; border-radius: 8px;
        padding: 6px 8px; selection-background-color: {t['sel']}; selection-color: {t['text']}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']}; selection-background-color: {t['soft']}; selection-color: {t['text']}; }}
    QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 6px 12px; }}
    QPushButton:hover {{ border-color: {t['muted']}; }}
    QPushButton:disabled {{ color: {t['muted']}; }}
    #primary {{ background: {t['accent']}; border: 1px solid {t['accent']}; color: {t['accent_text']}; font-weight: 600; }}
    #primary:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
    #small {{ padding: 3px 10px; font-size: 9pt; }}
    #link {{ border: none; background: transparent; color: {t['muted']}; text-align: left; padding: 4px 12px; }}
    #link:hover {{ color: {t['text']}; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {t['muted']}; background: {t['input']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; image: url("{check}"); }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    """


def app_label(exe: str | None) -> str:
    name = (exe or "").rsplit(".", 1)[0]
    return _APP_NAMES.get(name.lower(), name[:1].upper() + name[1:]) if name else ""


def day_label(d: dt.date) -> str:
    today = dt.date.today()
    if d == today:
        return "Today"
    if d == today - dt.timedelta(days=1):
        return "Yesterday"
    return d.strftime("%A, %B %d").replace(" 0", " ") + ("" if d.year == today.year else f", {d.year}")


def time_label(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%I:%M %p").lstrip("0")


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


class Bridge(QObject):
    """Carries engine callbacks (worker threads) onto the UI thread."""
    history_changed = Signal()
    notice = Signal(str)
    retry_done = Signal(int, str, str)       # row id, text, error
    key_checked = Signal(bool, str)


# -- History -----------------------------------------------------------------------

class HistoryCard(QFrame):
    def __init__(self, row: dict, on_retry):
        super().__init__()
        failed = row["status"] == "failed"
        self.setObjectName("failedCard" if failed else "card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(label(time_label(row["ts"]), "muted"))
        if app_label(row.get("app")):
            top.addWidget(label(app_label(row["app"]), "appTag"))
        top.addStretch(1)
        self.text = (row.get("final_text") or "").strip()
        if failed:
            self.btn = QPushButton("Retry")
            self.btn.setObjectName("small")
            self.btn.clicked.connect(lambda: (self.btn.setEnabled(False), self.btn.setText("Retrying…"), on_retry(row["id"])))
        else:
            self.btn = QPushButton("Copy")
            self.btn.setObjectName("small")
            self.btn.clicked.connect(self.copy)
        self.btn.setCursor(Qt.PointingHandCursor)
        top.addWidget(self.btn)
        lay.addLayout(top)
        if failed:
            secs = round((row.get("audio_ms") or 0) / 1000)
            err = (row.get("error") or "").split("\n")[0][:140]
            body = label(f"Couldn't transcribe this {secs}s recording. It's saved, so you can retry.\n{err}", "warn", wrap=True)
        elif not self.text:
            body = label("(no speech)", "muted")
        else:
            body = label(self.text, "body", wrap=True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.setCursor(Qt.IBeamCursor)
        lay.addWidget(body)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text)
        self.btn.setText("Copied ✓")
        QTimer.singleShot(1400, lambda: self.btn.setText("Copy"))


class HistoryPage(QWidget):
    def __init__(self, engine: App, on_retry):
        super().__init__()
        self.setObjectName("page")
        self.engine = engine
        self.on_retry = on_retry
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 0)
        outer.setSpacing(6)
        outer.addWidget(label("History", "title"))
        self.stats = label("", "muted")
        outer.addWidget(self.stats)
        self.search = QLineEdit(placeholderText="Search your dictations…", clearButtonEnabled=True)
        self.search.setMaximumWidth(420)
        outer.addSpacing(6)
        outer.addWidget(self.search)
        self.scroll = QScrollArea(widgetResizable=True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)
        self._debounce = QTimer(self, singleShot=True, interval=180, timeout=self.reload)
        self.search.textChanged.connect(lambda _: self._debounce.start())

    def reload(self) -> None:
        count, words = self.engine.history.stats()
        self.stats.setText(f"{count:,} dictation{'s' * (count != 1)} · {words:,} words. "
                           "Copy a whole entry, or select any part of the text.")
        body = QWidget()
        body.setObjectName("scrollBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 8, 12, 24)
        lay.setSpacing(8)
        q = self.search.text().strip()
        rows = self.engine.history.recent(q)
        last_day = None
        for row in rows:
            if row["status"] == "empty" and not q:
                continue
            day = dt.date.fromtimestamp(row["ts"])
            if day != last_day:
                lay.addWidget(label(day_label(day).upper(), "day"))
                last_day = day
            lay.addWidget(HistoryCard(row, self.on_retry))
        if last_day is None:
            msg = (f"Nothing matches “{q}”." if q else
                   f"No dictations yet.\nHold {pretty_keys(self.engine.cfg['hotkey'])} in any app, speak, and let go.")
            e = label(msg, "empty", wrap=True)
            e.setAlignment(Qt.AlignCenter)
            lay.addWidget(e)
        lay.addStretch(1)
        pos = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(body)
        self.scroll.verticalScrollBar().setValue(pos)


# -- Settings -----------------------------------------------------------------------

class SettingsPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.setObjectName("page")
        self.window_ = window
        self.engine = window.engine
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 16)
        outer.addWidget(label("Settings", "title"))
        scroll = QScrollArea(widgetResizable=True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("scrollBody")
        self.form = QVBoxLayout(body)
        self.form.setContentsMargins(0, 0, 16, 16)
        self.form.setSpacing(6)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # API key
        self._section("Speech-to-text API key")
        self.key = QLineEdit(echoMode=QLineEdit.Password)
        self.key.setMaximumWidth(460)
        self.show_key = QPushButton("Show")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(lambda on: (self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                                  self.show_key.setText("Hide" if on else "Show")))
        self.test_btn = QPushButton("Test key")
        self.test_btn.clicked.connect(self._test_key)
        row = QHBoxLayout()
        row.addWidget(self.key, 1)
        row.addWidget(self.show_key)
        row.addWidget(self.test_btn)
        row.addStretch(0)
        self.form.addLayout(row)
        self.key_status = label("", "hint", wrap=True)
        self.key_status.hide()
        self.form.addWidget(self.key_status)
        get_key = label('Saywell uses Groq for speech-to-text and cleanup. Get a free key at '
                        '<a href="https://console.groq.com/keys">console.groq.com/keys</a>.', "hint", wrap=True)
        get_key.setOpenExternalLinks(True)
        self.form.addWidget(get_key)
        window.bridge.key_checked.connect(self._key_checked)

        # Dictation
        self._section("Dictation")
        self.hotkey = self._combo("Dictation shortcut", "Hold to talk. Tap Space while holding for hands-free; Esc cancels.",
                                  [(pretty_keys(k), k) for k in HOTKEY_PRESETS], self.engine.cfg["hotkey"])
        self.paste_last = self._combo("Paste last transcript", "Pastes your most recent dictation again, wherever your cursor is.",
                                      [(pretty_keys(k), k) for k in PASTE_LAST_PRESETS], self.engine.cfg.get("paste_last_hotkey") or [])
        self.mic = self._combo("Microphone", "", self._mics(), self.engine.cfg["microphone"])
        self.sounds = self._check("Play start and stop sounds", self.engine.cfg["sounds"])
        self.bar = self._check("Show the floating bar at the bottom of the screen", self.engine.cfg.get("show_bar", True))

        # Writing
        self._section("Writing")
        self.cleanup = self._check("Clean up with AI (remove filler words, fix punctuation, apply corrections)",
                                   self.engine.cfg["cleanup"]["enabled"])
        self.name = self._line("Your name", "Helps spell your name correctly.", self.engine.cfg["user_name"])
        self.style = self._line("Writing style", "Optional, e.g. “casual, British spelling”.", self.engine.cfg["cleanup"].get("style", ""))
        self.form.addWidget(label("Dictionary", ""))
        self.form.addWidget(label("Names, jargon and product words to spell exactly. One per line.", "hint"))
        self.dictionary = QPlainTextEdit("\n".join(self.engine.cfg["dictionary"]))
        self.dictionary.setFixedHeight(110)
        self.dictionary.setMaximumWidth(460)
        self.form.addWidget(self.dictionary)

        # App
        self._section("App")
        app_row = QHBoxLayout()
        b = QPushButton("Add to Desktop and Start menu")
        b.clicked.connect(self._shortcuts)
        app_row.addWidget(b)
        b = QPushButton("Open data folder")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data_dir())))
        app_row.addWidget(b)
        app_row.addStretch(1)
        self.form.addLayout(app_row)
        self.app_status = label(f"{APP_NAME} {VERSION} · settings are stored in {settings_path()}", "hint", wrap=True)
        self.app_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.form.addWidget(self.app_status)
        self.form.addStretch(1)

        # Save bar
        bar = QHBoxLayout()
        self.saved = label("", "muted")
        save = QPushButton("Save changes")
        save.setObjectName("primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self.save)
        bar.addStretch(1)
        bar.addWidget(self.saved)
        bar.addWidget(save)
        outer.addLayout(bar)
        self.refresh_key_hint()

    # builders
    def _section(self, text: str) -> None:
        self.form.addWidget(label(text, "section"))

    def _combo(self, title: str, hint: str, items: list[tuple[str, object]], current) -> QComboBox:
        self.form.addWidget(label(title))
        cb = QComboBox()
        cb.setMaximumWidth(460)
        for text, value in items:
            cb.addItem(text, value)
        idx = next((i for i, (_, v) in enumerate(items) if v == current), -1)
        if idx < 0:
            cb.addItem(f"{pretty_keys(current) if isinstance(current, list) else current} (custom)", current)
            idx = cb.count() - 1
        cb.setCurrentIndex(idx)
        self.form.addWidget(cb)
        if hint:
            self.form.addWidget(label(hint, "hint", wrap=True))
        return cb

    def _check(self, text: str, on: bool) -> QCheckBox:
        c = QCheckBox(text)
        c.setChecked(bool(on))
        self.form.addWidget(c)
        return c

    def _line(self, title: str, hint: str, value: str) -> QLineEdit:
        self.form.addWidget(label(title))
        e = QLineEdit(value)
        e.setMaximumWidth(460)
        self.form.addWidget(e)
        self.form.addWidget(label(hint, "hint"))
        return e

    @staticmethod
    def _mics() -> list[tuple[str, object]]:
        items: list[tuple[str, object]] = [("System default", None)]
        try:
            import sounddevice as sd
            api = sd.query_devices(kind="input")["hostapi"]
            seen = set()
            for d in sd.query_devices():
                if d["max_input_channels"] > 0 and d["hostapi"] == api and d["name"] not in seen:
                    seen.add(d["name"])
                    items.append((d["name"], d["name"]))
        except Exception as e:
            print(f"[settings] could not list microphones: {e}")
        return items

    # behaviour
    def refresh_key_hint(self) -> None:
        asr = self.engine.cfg["asr"]
        stored = keystore.unprotect(asr.get("api_key", ""))
        if stored:
            self.key.setPlaceholderText(f"Saved key ending in …{stored[-4:]} (paste a new one to replace it)")
        elif os.environ.get(asr.get("api_key_env", "")):
            self.key.setPlaceholderText(f"Using {asr['api_key_env']} from your environment (paste a key to save one here)")
        else:
            self.key.setPlaceholderText("Paste your Groq API key (gsk_…)")

    def _test_key(self) -> None:
        asr = dict(self.engine.cfg["asr"])
        if self.key.text().strip():
            asr["api_key"] = self.key.text().strip()
        key = keystore.get_api_key(asr)
        if not key:
            self.key_status.setText("Paste a key first.")
            self.key_status.show()
            return
        self.test_btn.setEnabled(False)
        self.key_status.setText("Checking…")
        self.key_status.show()

        def check():
            req = urllib.request.Request(asr["base_url"].rstrip("/") + "/models",
                                         headers={"Authorization": f"Bearer {key}", "User-Agent": "Saywell/0.2"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    json.load(r)
                self.window_.bridge.key_checked.emit(True, "Key works ✓")
            except urllib.error.HTTPError as e:
                self.window_.bridge.key_checked.emit(False, "That key was rejected (HTTP %d)." % e.code)
            except Exception as e:
                self.window_.bridge.key_checked.emit(False, f"Couldn't reach the server: {e}")
        threading.Thread(target=check, daemon=True).start()

    def _key_checked(self, ok: bool, msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.key_status.setText(msg)

    def _shortcuts(self) -> None:
        try:
            made = shortcuts.create_shortcuts()
            self.app_status.setText("Shortcuts created:\n" + "\n".join(made))
        except Exception as e:
            self.app_status.setText(f"Couldn't create shortcuts: {e}")

    def save(self) -> None:
        cfg = copy.deepcopy(self.engine.cfg)
        new_key = self.key.text().strip()
        if new_key:
            enc = keystore.protect(new_key)
            cfg["asr"]["api_key"] = enc
            c = cfg["cleanup"]
            if c.get("provider") == "openai_compatible" and c.get("base_url") == cfg["asr"]["base_url"]:
                c["api_key"] = enc
        cfg["hotkey"] = self.hotkey.currentData()
        cfg["paste_last_hotkey"] = self.paste_last.currentData()
        cfg["microphone"] = self.mic.currentData()
        cfg["sounds"] = self.sounds.isChecked()
        cfg["show_bar"] = self.bar.isChecked()
        cfg["cleanup"]["enabled"] = self.cleanup.isChecked()
        cfg["user_name"] = self.name.text().strip()
        cfg["cleanup"]["style"] = self.style.text().strip()
        cfg["dictionary"] = [w.strip() for w in self.dictionary.toPlainText().splitlines() if w.strip()]
        save_config(cfg, settings_path())
        self.window_.apply_config(cfg)
        self.key.clear()
        self.refresh_key_hint()
        self.saved.setText("Saved ✓")
        QTimer.singleShot(2500, lambda: self.saved.setText(""))


# -- Window -------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, engine: App, bridge: Bridge, overlay):
        super().__init__()
        self.engine = engine
        self.bridge = bridge
        self.overlay = overlay
        self.tray: QSystemTrayIcon | None = None
        self._told_about_tray = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(asset("saywell.ico")))
        self.resize(940, 660)
        self.setMinimumSize(720, 480)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(210)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 18, 14, 14)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(asset("saywell.ico")).pixmap(28, 28))
        brand.addWidget(logo)
        brand.addWidget(label(APP_NAME, "brand"))
        brand.addStretch(1)
        sv.addLayout(brand)
        sv.addSpacing(16)
        self.nav = QButtonGroup(self)
        self.pages = QStackedWidget()
        self.history_page = HistoryPage(engine, self.retry)
        self.settings_page = SettingsPage(self)
        for i, (name, page) in enumerate([("History", self.history_page), ("Settings", self.settings_page)]):
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, i)
            sv.addWidget(b)
            self.pages.addWidget(page)
        self.nav.idClicked.connect(self.pages.setCurrentIndex)
        self.nav.button(0).setChecked(True)
        sv.addStretch(1)
        card = QFrame()
        card.setObjectName("hintCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 10)
        self.hint_title = label("", "hintTitle", wrap=True)
        self.hint_body = label("", "hint", wrap=True)
        cv.addWidget(self.hint_title)
        cv.addWidget(self.hint_body)
        sv.addWidget(card)
        sv.addSpacing(6)
        quit_btn = QPushButton(f"Quit {APP_NAME}")
        quit_btn.setObjectName("link")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.clicked.connect(QApplication.quit)
        sv.addWidget(quit_btn)
        h.addWidget(side)
        h.addWidget(self.pages, 1)
        self.setCentralWidget(root)

        self._update_hints()
        self.apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_theme())
        bridge.history_changed.connect(self._history_changed)
        bridge.retry_done.connect(self._retry_done)
        bridge.notice.connect(self.notify)
        self.history_page.reload()

    def apply_theme(self) -> None:
        dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        t = DARK if dark else LIGHT
        qapp = QApplication.instance()
        pal = qapp.palette()
        pal.setColor(QPalette.Link, QColor(t["accent"]))
        qapp.setPalette(pal)
        qapp.setStyleSheet(stylesheet(t))

    def _update_hints(self) -> None:
        cfg = self.engine.cfg
        self.hint_title.setText(f"Hold {pretty_keys(cfg['hotkey'])} to dictate")
        extra = "" if not cfg.get("paste_last_hotkey") else f"\n{pretty_keys(cfg['paste_last_hotkey'])} pastes the last one."
        self.hint_body.setText("Tap Space while holding for hands-free. Esc cancels." + extra)
        self.overlay.set_hint(f"Hold {pretty_keys(cfg['hotkey'])} to dictate")
        self.overlay.set_enabled(cfg.get("show_bar", True))
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME}: hold {pretty_keys(cfg['hotkey'])} to dictate")

    def copy_last(self) -> None:
        text = self.engine.history.last_text()
        if text:
            QGuiApplication.clipboard().setText(text.strip())
        self.overlay.flash("Copied last transcript" if text else "Nothing to copy yet")

    def apply_config(self, cfg: dict) -> None:
        self.engine.reconfigure(cfg)
        self._update_hints()

    # pages
    def show_page(self, index: int) -> None:
        self.nav.button(index).setChecked(True)
        self.pages.setCurrentIndex(index)
        if index == 0:
            self.history_page.reload()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _history_changed(self) -> None:
        if self.isVisible():
            self.history_page.reload()

    def showEvent(self, ev) -> None:
        self.history_page.reload()
        super().showEvent(ev)

    def closeEvent(self, ev) -> None:
        # Closing the window keeps Saywell running so the hotkey still works.
        ev.ignore()
        self.hide()
        if not self._told_about_tray:
            self._told_about_tray = True
            self.notify(f"{APP_NAME} is still running. Hold {pretty_keys(self.engine.cfg['hotkey'])} to dictate; "
                        "quit from the tray icon.")

    def notify(self, msg: str) -> None:
        if self.tray:
            self.tray.showMessage(APP_NAME, msg, QIcon(asset("saywell.ico")), 5000)
        print(f"[notice] {msg}")

    # retry
    def retry(self, row_id: int) -> None:
        def run():
            try:
                text = self.engine.retry(row_id)
                self.bridge.retry_done.emit(row_id, text, "")
            except Exception as e:
                self.bridge.retry_done.emit(row_id, "", str(e))
        threading.Thread(target=run, daemon=True).start()

    def _retry_done(self, row_id: int, text: str, err: str) -> None:
        self.history_page.reload()
        if err:
            self.notify(f"Still couldn't transcribe it: {err[:160]}")
        elif text:
            QGuiApplication.clipboard().setText(text.strip())
            self.notify("Transcribed and copied to your clipboard.")


def make_tray(window: MainWindow) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(QIcon(asset("saywell.ico")), window)
    menu = QMenu()
    for text, fn in [(f"Open {APP_NAME}", lambda: window.show_page(0)),
                     ("Copy last transcript", window.copy_last),
                     ("Settings", lambda: window.show_page(1))]:
        a = QAction(text, menu)
        a.triggered.connect(fn)
        menu.addAction(a)
    menu.addSeparator()
    q = QAction(f"Quit {APP_NAME}", menu)
    q.triggered.connect(QApplication.quit)
    menu.addAction(q)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: window.show_page(0) if reason == QSystemTrayIcon.Trigger else None)
    window.tray = tray
    window._update_hints()
    window._tray_menu = menu  # keep a reference
    tray.show()
    return tray
