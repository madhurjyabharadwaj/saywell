"""Render saywell/assets/saywell.ico and saywell.png (run once after changing the design).

    python tools/make_icon.py
"""
import os
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saywell", "assets")
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
QUOTE_X = [0.37, 0.63]  # centres of the two quotation marks


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    pad = s * 0.04
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, QColor("#ff7a45"))
    g.setColorAt(1, QColor("#e5336d"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(QRectF(pad, pad, s - 2 * pad, s - 2 * pad), s * 0.24, s * 0.24)
    p.setBrush(QColor("#ffffff"))
    r = s * 0.105
    cy = s * 0.44
    for fx in QUOTE_X:
        cx = s * fx
        p.drawEllipse(QPointF(cx, cy), r, r)
        tail = QPainterPath()
        tail.moveTo(cx + r, cy)
        tail.cubicTo(cx + r, cy + 1.6 * r, cx - 0.1 * r, cy + 2.5 * r, cx - 0.9 * r, cy + 2.7 * r)
        tail.cubicTo(cx - 0.2 * r, cy + 2.0 * r, cx + 0.1 * r, cy + 1.4 * r, cx - 0.05 * r, cy + 0.95 * r)
        tail.closeSubpath()
        p.drawPath(tail)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def main() -> None:
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    pngs = [png_bytes(render(s)) for s in SIZES]
    # ICO container with PNG-compressed entries (supported since Windows Vista).
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries, blobs = b"", b""
    for size, data in zip(SIZES, pngs):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    with open(os.path.join(OUT, "saywell.ico"), "wb") as f:
        f.write(header + entries + blobs)
    render(256).save(os.path.join(OUT, "saywell.png"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
