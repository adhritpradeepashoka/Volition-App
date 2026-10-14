"""
ThresholdBar — QProgressBar replacement with a draggable threshold marker.

When value >= threshold the fill turns green (detected).
Click and drag anywhere on the bar to reposition the threshold.
"""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPolygonF


class ThresholdBar(QWidget):
    thresholdChanged = Signal(int)   # new threshold (0-100)

    # Palette 
    _BG      = QColor('#1a1a1a')
    _BORDER  = QColor('#2a2a2a')
    _FILL    = QColor('#ffffff')
    _FILL_ON = QColor('#00cc66')     # bright green when detected
    _MARKER  = QColor('#ff6600')     # orange threshold line

    def __init__(self, threshold=50, parent=None):
        super().__init__(parent)
        self._value = 0
        self._threshold = max(0, min(100, threshold))
        self._dragging = False
        self.setMinimumHeight(18)
        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    # Public API (drop-in for QProgressBar) 

    def value(self):
        return self._value

    def setValue(self, v):
        self._value = max(0, min(100, int(v)))
        self.update()

    def threshold(self):
        return self._threshold

    def setThreshold(self, t):
        t = max(0, min(100, int(t)))
        if t != self._threshold:
            self._threshold = t
            self.thresholdChanged.emit(t)
            self.update()

    @property
    def detected(self):
        return self._threshold > 0 and self._value >= self._threshold

    # Painting 

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        r = 6                       # border-radius
        m = 2                       # inner margin

        # 1. Background + border (matches QProgressBar stylesheet)
        p.setPen(QPen(self._BORDER, 1))
        p.setBrush(self._BG)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        # 2. Fill chunk
        fill_w = max(0, int((w - 2 * m) * self._value / 100))
        if fill_w > 0:
            color = self._FILL_ON if self.detected else self._FILL
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(m, m, fill_w, h - 2 * m), r - 1, r - 1)

        # 3. Threshold marker (orange vertical line + small triangle)
        if 0 <= self._threshold <= 100:
            tx = m + (w - 2 * m) * self._threshold / 100.0
            # Visually clamp the marker so the triangle doesn't bleed out of the widget
            tx = max(3.0, min(float(w - 3), tx))
            
            # Vertical line
            p.setPen(QPen(self._MARKER, 2))
            p.drawLine(QPointF(tx, 2), QPointF(tx, h - 2))
            # Small downward triangle at top
            p.setPen(Qt.NoPen)
            p.setBrush(self._MARKER)
            tri = QPolygonF([
                QPointF(tx - 3, 0),
                QPointF(tx + 3, 0),
                QPointF(tx, 5),
            ])
            p.drawConvexPolygon(tri)

        p.end()

    # Mouse interaction (drag threshold) 

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._threshold_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._threshold_from_x(event.position().x())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False

    def _threshold_from_x(self, x):
        m = 2
        usable = self.width() - 2 * m
        if usable <= 0:
            return
        pct = max(0, min(100, int((x - m) / usable * 100)))
        if pct != self._threshold:
            self._threshold = pct
            self.thresholdChanged.emit(pct)
            self.update()
