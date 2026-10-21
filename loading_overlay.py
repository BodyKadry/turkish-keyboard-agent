from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class SpinnerWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(28, 28)

    def set_angle(self, angle: int) -> None:
        self._angle = angle % 360
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(5, 5, -5, -5)
        base_pen = QPen(QColor(255, 255, 255, 45), 3)
        painter.setPen(base_pen)
        painter.drawEllipse(rect)

        accent_pen = QPen(QColor("#00cfe8"), 3)
        accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(accent_pen)
        painter.drawArc(rect, int(-self._angle * 16), int(-115 * 16))


class LoadingOverlay(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._requests = 0
        self._angle = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setObjectName("LoadingOverlay")

        self.spinner = SpinnerWidget(self)
        self.label = QLabel("Correcting...")
        self.label.setObjectName("OverlayText")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)
        layout.addWidget(self.spinner)
        layout.addWidget(self.label)

        self.timer = QTimer(self)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self._tick)

        self.setStyleSheet(
            """
            QFrame#LoadingOverlay {
                background: rgba(13, 20, 34, 230);
                border: 1px solid rgba(95, 125, 170, 170);
                border-radius: 18px;
            }
            QLabel#OverlayText {
                color: #eef4ff;
                font-family: "Segoe UI";
                font-size: 13px;
                font-weight: 700;
            }
            """
        )

    def show_loading(self, message: str = "Correcting...") -> None:
        self._requests += 1
        self.label.setText(message or "Correcting...")
        self.adjustSize()
        self._move_near_cursor()
        if not self.isVisible():
            self.show()
            self.raise_()
            self.timer.start()

    def hide_loading(self) -> None:
        if self._requests > 0:
            self._requests -= 1

        if self._requests > 0:
            return

        self._requests = 0
        self.timer.stop()
        self.hide()

    def force_hide(self) -> None:
        self._requests = 0
        self.timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.spinner.set_angle(self._angle)

    def _move_near_cursor(self) -> None:
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        x = cursor_pos.x() + 28
        y = cursor_pos.y() + 28

        if not available.contains(QPoint(x, y)):
            x = available.right() - self.width() - 28
            y = available.bottom() - self.height() - 28

        x = max(available.left() + 10, min(x, available.right() - self.width() - 10))
        y = max(available.top() + 10, min(y, available.bottom() - self.height() - 10))
        self.move(x, y)
