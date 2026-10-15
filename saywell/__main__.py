"""Start Saywell: `python -m saywell` (or `pythonw -m saywell`, or Saywell.exe)."""
import argparse
import ctypes
import os
import signal
import sys

from .config import APP_NAME, data_dir, load_config, migrate_from_flowlite, settings_path


def _log_to_file() -> None:
    """Without a console (pythonw / packaged app), keep output in saywell.log for troubleshooting."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    os.makedirs(data_dir(), exist_ok=True)
    path = os.path.join(data_dir(), "saywell.log")
    if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
        os.replace(path, path + ".old")
    f = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f


def main() -> None:
    p = argparse.ArgumentParser(prog="saywell", description="Hold-to-talk dictation for Windows")
    p.add_argument("--config", default=None, help="settings file (default: %%APPDATA%%\\Saywell\\settings.json)")
    p.add_argument("--hidden", action="store_true", help="start in the tray without opening the window")
    p.add_argument("--list-mics", action="store_true", help="list input devices and exit")
    p.add_argument("--install-shortcuts", action="store_true", help="add Desktop and Start menu shortcuts and exit")
    args = p.parse_args()
    _log_to_file()

    if args.list_mics:
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                print(f"{i}: {d['name']}")
        return
    if args.install_shortcuts:
        from .shortcuts import create_shortcuts
        for path in create_shortcuts():
            print("created", path)
        return

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication, QMessageBox

    # Own taskbar identity, so Windows shows Saywell's icon rather than Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Saywell.App")
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)

    # Single instance: launching again just brings the running window forward.
    server_name = f"{APP_NAME}-{os.environ.get('USERNAME', 'user')}"
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(300):
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY: let the running copy take focus
        sock.write(b"show")
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)

    from .app import App
    from .config import asset
    from .keystore import get_api_key
    from .overlay import Overlay
    from .ui import Bridge, MainWindow, make_tray

    migrate_from_flowlite()
    cfg = load_config(args.config or settings_path())
    qapp.setWindowIcon(QIcon(asset("saywell.ico")))
    bridge = Bridge()
    holder: dict = {}
    overlay = Overlay(lambda: holder["engine"].recorder.level, "")
    engine = App(cfg, data_dir(), overlay, on_history=bridge.history_changed.emit, on_notice=bridge.notice.emit)
    holder["engine"] = engine
    window = MainWindow(engine, bridge, overlay)
    make_tray(window)
    overlay.clicked.connect(lambda: window.show_page(0))
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.show_page(0)))

    try:
        engine.start()
    except OSError as e:
        QMessageBox.critical(None, APP_NAME, f"Couldn't start the keyboard shortcut listener:\n{e}")
        return
    overlay.start()

    if not get_api_key(cfg["asr"]):
        window.show_page(1)
        window.notify("Add your Groq API key to start dictating.")
    elif not args.hidden:
        window.show_page(0)

    if sys.stdout is not None and sys.stdout.isatty():
        signal.signal(signal.SIGINT, lambda *_: qapp.quit())  # Ctrl+C in a terminal
        QTimer(qapp, interval=250, timeout=lambda: None).start()  # let Python see the signal
    try:
        qapp.exec()
    finally:
        engine.stop()
        server.close()


if __name__ == "__main__":
    main()
