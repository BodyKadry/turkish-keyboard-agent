from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QDateTime, QObject, QThread, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from agent_controller import AgentController
from chat_store import ChatStore
from config import BASE_DIR, load_config
from loading_overlay import LoadingOverlay
from logger import clear_log_file, get_logs_dir, setup_logger
from settings_manager import SettingsManager, mask_api_key


STATUS_STYLES = {
    "running": ("Running", "#28c76f"),
    "stopped": ("Stopped", "#ea5455"),
    "correcting": ("Correcting...", "#00cfe8"),
    "error": ("Error", "#ff9f43"),
}


class LogBridge(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: LogBridge) -> None:
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        self.bridge.message.emit(self.format(record))


class StatusBridge(QObject):
    status_changed = Signal(str)


class LoadingBridge(QObject):
    loading_changed = Signal(bool, str)


class ChatInput(QPlainTextEdit):
    send_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("Write text here… example: dunku yemek cok guzeldi")
        self.setMinimumHeight(46)
        self.setMaximumHeight(72)
        self.setObjectName("ChatInput")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        has_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if is_enter and not has_shift:
            event.accept()
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class MessageBubble(QFrame):
    def __init__(
        self,
        role: str,
        text: str,
        timestamp: str | None = None,
        show_copy: bool = False,
    ) -> None:
        super().__init__()
        self.role = role
        self.message_text = text
        self.setObjectName(f"Bubble_{role}")

        role_names = {
            "user": "You",
            "assistant": "AI",
            "system": "System",
            "error": "Error",
        }
        self.role_label = QLabel(role_names.get(role, role.title()))
        self.role_label.setObjectName("BubbleRole")

        self.copy_button: QPushButton | None = None
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self.role_label)
        header.addStretch(1)
        if show_copy:
            self.copy_button = QPushButton("Copy")
            self.copy_button.setObjectName("BubbleCopyButton")
            self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.copy_button.clicked.connect(self._copy_text)
            header.addWidget(self.copy_button)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setObjectName("BubbleText")

        self.time_label = QLabel(timestamp or "")
        self.time_label.setObjectName("BubbleTime")
        self.time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
            if role == "user"
            else Qt.AlignmentFlag.AlignLeft
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 9)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.label)
        if timestamp:
            layout.addWidget(self.time_label)

        self.setMinimumWidth(180)
        self.setMaximumWidth(640)

    def set_text(self, text: str) -> None:
        self.message_text = text
        self.label.setText(text)

    @Slot()
    def _copy_text(self) -> None:
        QApplication.clipboard().setText(self.message_text)
        if self.copy_button is None:
            return
        self.copy_button.setText("Copied")
        QTimer.singleShot(1100, lambda: self.copy_button and self.copy_button.setText("Copy"))


class CorrectionWorker(QObject):
    finished = Signal(str, bool)
    failed = Signal(str)

    def __init__(self, controller: AgentController, text: str) -> None:
        super().__init__()
        self.controller = controller
        self.text = text

    @Slot()
    def run(self) -> None:
        try:
            result = self.controller.correct_text_result(self.text)
            self.finished.emit(result.text, result.failed)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.log = setup_logger()
        self.settings_manager = SettingsManager()
        self.config = load_config()
        self.chat_store = ChatStore(self.config.data_dir, self.log)
        self.status_bridge = StatusBridge()
        self.status_bridge.status_changed.connect(self.set_status)
        self.loading_bridge = LoadingBridge()
        self.loading_bridge.loading_changed.connect(self._on_loading_changed)
        self.controller = AgentController(
            self.config,
            self.log,
            status_callback=self.status_bridge.status_changed.emit,
            loading_callback=self.loading_bridge.loading_changed.emit,
        )
        self.loading_overlay: LoadingOverlay | None = None
        self.correction_thread: QThread | None = None
        self.correction_worker: CorrectionWorker | None = None
        self.loading_bubble_row: QWidget | None = None
        self.loading_bubble: MessageBubble | None = None
        self.loading_dot_count = 0
        self._status_key = "stopped"
        self._exiting = False
        self._tray_message_shown = False

        self.setWindowTitle("Turkish Keyboard Agent")
        self.resize(1180, 820)
        self.setMinimumSize(940, 700)

        self._build_ui()
        self.loading_overlay = LoadingOverlay(self)
        self._build_tray()
        self._attach_log_viewer()
        self._load_settings_fields()
        self._load_chat_history()
        self.set_status("stopped")
        self.log.info("UI started")

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(24, 22, 24, 22)
        root_layout.setSpacing(16)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        app_title = QLabel("Turkish Keyboard Agent")
        app_title.setObjectName("AppTitle")
        subtitle = QLabel("Windows hotkey correction with Ollama")
        subtitle.setObjectName("Subtitle")
        title_block.addWidget(app_title)
        title_block.addWidget(subtitle)

        self.status_label = QLabel("Stopped")
        self.status_label.setObjectName("StatusBadge")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setMinimumWidth(128)

        header.addLayout(title_block)
        header.addStretch(1)
        header.addWidget(self.status_label)
        root_layout.addLayout(header)

        controls_card = self._card("Agent")
        controls_layout = QHBoxLayout()
        controls_card.layout().addLayout(controls_layout)
        controls_layout.setSpacing(12)
        self.start_button = QPushButton("Start Agent")
        self.start_button.clicked.connect(self.start_agent)
        self.stop_button = QPushButton("Stop Agent")
        self.stop_button.clicked.connect(self.stop_agent)
        self.open_data_button = QPushButton("Open Data Folder")
        self.open_data_button.clicked.connect(self.open_data_folder)
        self.open_logs_button = QPushButton("Open Logs")
        self.open_logs_button.clicked.connect(self.open_logs)
        self.clear_logs_button = QPushButton("Clear Logs")
        self.clear_logs_button.clicked.connect(self.clear_logs)

        for button in (
            self.start_button,
            self.stop_button,
            self.open_data_button,
            self.open_logs_button,
            self.clear_logs_button,
        ):
            controls_layout.addWidget(button)
        controls_layout.addStretch(1)
        root_layout.addWidget(controls_card)

        middle = QHBoxLayout()
        middle.setSpacing(16)

        chat_card = self._card("Correction Chat")
        chat_layout = chat_card.layout()
        chat_layout.setSpacing(8)
        chat_subtitle = QLabel(
            "Send Turkish text written without Turkish characters and get a corrected version instantly."
        )
        chat_subtitle.setObjectName("CardSubtitle")
        chat_layout.addWidget(chat_subtitle)

        chat_area = QFrame()
        chat_area.setObjectName("ChatArea")
        chat_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        chat_area_layout = QVBoxLayout(chat_area)
        chat_area_layout.setContentsMargins(0, 0, 0, 0)
        chat_area_layout.setSpacing(10)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setObjectName("ChatScroll")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_scroll.setMinimumHeight(260)
        self.chat_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chat_content = QWidget()
        self.chat_content.setObjectName("ChatContent")
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setContentsMargins(12, 14, 12, 28)
        self.chat_layout.setSpacing(10)
        self.empty_chat_widget = self._empty_chat_state()
        self.chat_layout.addWidget(
            self.empty_chat_widget,
            0,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.chat_layout.addStretch(1)
        self.chat_scroll.setWidget(self.chat_content)

        composer = QFrame()
        composer.setObjectName("ChatComposer")
        composer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        composer.setMinimumHeight(92)
        composer.setMaximumHeight(104)
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(10, 9, 10, 8)
        composer_layout.setSpacing(6)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.chat_input = ChatInput()
        self.chat_input.send_requested.connect(self.send_chat_message)
        self.send_button = QPushButton("➤")
        self.send_button.setObjectName("SendChatButton")
        self.send_button.setMinimumWidth(52)
        self.send_button.clicked.connect(self.send_chat_message)
        self.clear_chat_button = QPushButton("Clear")
        self.clear_chat_button.setObjectName("ClearChatButton")
        self.clear_chat_button.clicked.connect(self.clear_chat)
        input_row.addWidget(self.chat_input, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.clear_chat_button)

        input_hint = QLabel("Press Enter to send • Shift+Enter for new line")
        input_hint.setObjectName("InputHint")

        composer_layout.addLayout(input_row)
        composer_layout.addWidget(input_hint)

        chat_area_layout.addWidget(self.chat_scroll, 1)
        chat_area_layout.addWidget(composer, 0)
        chat_layout.addWidget(chat_area, 1)

        settings_card = self._card("Settings")
        settings_layout = QGridLayout()
        settings_card.layout().addLayout(settings_layout)
        settings_layout.setHorizontalSpacing(12)
        settings_layout.setVerticalSpacing(10)
        self.hotkey_field = QLineEdit()
        self.api_key_field = QLineEdit()
        self.api_key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.base_url_field = QLineEdit()
        self.model_field = QLineEdit()
        self.timeout_field = self._number_field(1, 600, 1)
        self.copy_delay_field = self._number_field(0.01, 5, 0.01)
        self.paste_delay_field = self._number_field(0.01, 5, 0.01)
        self.show_loading_overlay_field = QCheckBox("Show Loading Overlay")
        self.save_settings_button = QPushButton("Save Settings")
        self.save_settings_button.clicked.connect(self.save_settings)

        rows = (
            ("Hotkey", self.hotkey_field),
            ("Ollama API Key", self.api_key_field),
            ("Ollama Base URL", self.base_url_field),
            ("Ollama Model", self.model_field),
            ("Timeout", self.timeout_field),
            ("Copy Delay", self.copy_delay_field),
            ("Paste Delay", self.paste_delay_field),
        )
        for row, (label, widget) in enumerate(rows):
            settings_layout.addWidget(QLabel(label), row, 0)
            settings_layout.addWidget(widget, row, 1)

        settings_layout.addWidget(self.show_loading_overlay_field, len(rows), 1)
        settings_layout.addWidget(
            self.save_settings_button,
            len(rows) + 1,
            1,
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        middle.addWidget(chat_card, 3)
        middle.addWidget(settings_card, 2)
        root_layout.addLayout(middle, 3)

        logs_card = self._card("Live Logs")
        logs_layout = logs_card.layout()
        self.log_viewer = QPlainTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMaximumBlockCount(700)
        logs_layout.addWidget(self.log_viewer)
        root_layout.addWidget(logs_card, 2)

        self.chat_loading_timer = QTimer(self)
        self.chat_loading_timer.setInterval(350)
        self.chat_loading_timer.timeout.connect(self._animate_loading_bubble)

        self.setCentralWidget(root)
        self.setStyleSheet(APP_STYLESHEET)

    def _card(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setFrameShape(QFrame.Shape.NoFrame)
        header = QLabel(title)
        header.setObjectName("CardTitle")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(header)
        return frame

    def _empty_chat_state(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("EmptyChatState")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(22, 19, 22, 19)
        layout.setSpacing(6)

        title = QLabel("Start by typing a Turkish sentence without Turkish characters.")
        title.setObjectName("EmptyChatTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)

        example = QLabel("Example: dun cok guzeldi → dün çok güzeldi")
        example.setObjectName("EmptyChatExample")
        example.setAlignment(Qt.AlignmentFlag.AlignCenter)
        example.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(example)
        return frame

    def _show_empty_chat_state(self) -> None:
        if hasattr(self, "empty_chat_widget"):
            self.empty_chat_widget.show()

    def _hide_empty_chat_state(self) -> None:
        if hasattr(self, "empty_chat_widget"):
            self.empty_chat_widget.hide()

    def _now_time(self) -> str:
        return QDateTime.currentDateTime().toString("HH:mm")

    def _set_chat_busy(self, busy: bool) -> None:
        self.chat_input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.clear_chat_button.setEnabled(not busy)

    def _number_field(self, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setRange(minimum, maximum)
        field.setSingleStep(step)
        field.setDecimals(2)
        return field

    def _build_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(self)
        icon = self._app_icon()
        self.setWindowIcon(icon)
        self.tray_icon.setIcon(icon)

        tray_menu = QMenu()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show_from_tray)
        start_action = QAction("Start Agent", self)
        start_action.triggered.connect(self.start_agent)
        stop_action = QAction("Stop Agent", self)
        stop_action.triggered.connect(self.stop_agent)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.exit_app)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(start_action)
        tray_menu.addAction(stop_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _app_icon(self) -> QIcon:
        icon_path = BASE_DIR / "app.ico"
        if icon_path.exists():
            return QIcon(str(icon_path))
        return QApplication.instance().style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    def _attach_log_viewer(self) -> None:
        self.log_bridge = LogBridge()
        self.log_bridge.message.connect(self._append_log)
        self.qt_log_handler = QtLogHandler(self.log_bridge)
        self.qt_log_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        self.log.addHandler(self.qt_log_handler)

    def _load_settings_fields(self) -> None:
        self.hotkey_field.setText(self.config.hotkey)
        self.api_key_field.setText(self.config.ollama_api_key or "")
        self.api_key_field.setPlaceholderText(mask_api_key(self.config.ollama_api_key))
        self.base_url_field.setText(self.config.ollama_base_url)
        self.model_field.setText(self.config.ollama_model)
        self.timeout_field.setValue(float(self.config.ollama_timeout_seconds))
        self.copy_delay_field.setValue(float(self.config.copy_delay))
        self.paste_delay_field.setValue(float(self.config.paste_delay))
        self.show_loading_overlay_field.setChecked(bool(self.config.show_loading_overlay))

    def _load_chat_history(self) -> None:
        messages = self.chat_store.load_messages()
        if not messages:
            self._show_empty_chat_state()
            return

        self._hide_empty_chat_state()
        for message in messages:
            self._add_chat_bubble(
                message.get("role", "system"),
                message.get("text", ""),
                timestamp=message.get("timestamp") or self._now_time(),
            )

    def _add_chat_bubble(
        self,
        role: str,
        text: str,
        timestamp: str | None = None,
        show_copy: bool | None = None,
    ) -> QWidget:
        self._hide_empty_chat_state()
        row = QWidget()
        row.setObjectName("ChatRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        bubble = MessageBubble(
            role,
            text,
            timestamp=timestamp or self._now_time(),
            show_copy=(role == "assistant" if show_copy is None else show_copy),
        )

        if role == "user":
            row_layout.addStretch(2)
            row_layout.addWidget(bubble, 5)
        elif role in {"system", "error"}:
            row_layout.addStretch(1)
            row_layout.addWidget(bubble, 4)
            row_layout.addStretch(1)
        else:
            row_layout.addWidget(bubble, 5)
            row_layout.addStretch(2)

        self.chat_layout.insertWidget(max(self.chat_layout.count() - 1, 0), row)
        QTimer.singleShot(0, self._scroll_chat_to_bottom)
        return row

    def _scroll_chat_to_bottom(self) -> None:
        scrollbar = self.chat_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _show_loading_bubble(self) -> None:
        self._remove_loading_bubble()
        self.loading_dot_count = 0
        self.loading_bubble_row = self._add_chat_bubble(
            "assistant",
            "AI is typing.",
            show_copy=False,
        )
        self.loading_bubble = self.loading_bubble_row.findChild(MessageBubble)
        self.chat_loading_timer.start()

    def _remove_loading_bubble(self) -> None:
        self.chat_loading_timer.stop()
        if self.loading_bubble_row is not None:
            self.chat_layout.removeWidget(self.loading_bubble_row)
            self.loading_bubble_row.deleteLater()
        self.loading_bubble_row = None
        self.loading_bubble = None

    def _animate_loading_bubble(self) -> None:
        if self.loading_bubble is None:
            return
        self.loading_dot_count = (self.loading_dot_count + 1) % 4
        dots = "." * self.loading_dot_count or "."
        self.loading_bubble.set_text(f"AI is typing{dots}")

    @Slot(str)
    def set_status(self, status: str) -> None:
        self._status_key = status
        label, color = STATUS_STYLES.get(status, STATUS_STYLES["error"])
        self.status_label.setText(label)
        self.status_label.setStyleSheet(
            f"background-color: {color}; color: #08111f; border-radius: 14px; "
            "padding: 6px 14px; font-weight: 700;"
        )
        running = status == "running"
        correcting = status == "correcting"
        self.start_button.setEnabled(not running and not correcting)
        self.stop_button.setEnabled(running or correcting)
        self.send_button.setEnabled(not correcting)

    @Slot(bool, str)
    def _on_loading_changed(self, visible: bool, message: str) -> None:
        if self.loading_overlay is None:
            return
        if visible:
            self.loading_overlay.show_loading(message or "Correcting...")
        else:
            self.loading_overlay.hide_loading()

    @Slot()
    def start_agent(self) -> None:
        try:
            self.controller.start()
        except Exception as exc:
            self.log.exception("Agent start failed: %s", exc)
            self.set_status("error")
            QMessageBox.warning(self, "Agent Error", f"Could not start agent:\n{exc}")

    @Slot()
    def stop_agent(self) -> None:
        try:
            self.controller.stop()
        except Exception as exc:
            self.log.exception("Agent stop failed: %s", exc)
            self.set_status("error")

    @Slot()
    def send_chat_message(self) -> None:
        if self.correction_thread is not None:
            return

        text = self.chat_input.toPlainText().strip()
        if not text:
            return

        self.chat_input.clear()
        self.chat_store.add_message("user", text)
        self._add_chat_bubble("user", text)
        self._show_loading_bubble()
        if self.config.show_loading_overlay and self.loading_overlay is not None:
            self.loading_overlay.show_loading("Correcting...")

        self.set_status("correcting")
        self._set_chat_busy(True)
        self.correction_thread = QThread(self)
        self.correction_worker = CorrectionWorker(self.controller, text)
        self.correction_worker.moveToThread(self.correction_thread)
        self.correction_thread.started.connect(self.correction_worker.run)
        self.correction_worker.finished.connect(self._on_chat_finished)
        self.correction_worker.failed.connect(self._on_chat_failed)
        self.correction_worker.finished.connect(self.correction_thread.quit)
        self.correction_worker.failed.connect(self.correction_thread.quit)
        self.correction_thread.finished.connect(self.correction_worker.deleteLater)
        self.correction_thread.finished.connect(self.correction_thread.deleteLater)
        self.correction_thread.finished.connect(self._on_chat_thread_finished)
        self.correction_thread.start()

    @Slot(str, bool)
    def _on_chat_finished(self, corrected: str, failed: bool) -> None:
        self._remove_loading_bubble()
        if failed:
            message = "Correction failed. Check Ollama API settings."
            self._add_chat_bubble("error", message)
            self.log.error(message)
            self.set_status("error")
            return

        if not corrected.strip():
            message = "Correction failed. Empty response received."
            self._add_chat_bubble("error", message)
            self.log.warning(message)
            self.set_status("error")
            return

        self.chat_store.add_message("assistant", corrected)
        self._add_chat_bubble("assistant", corrected)
        self.log.info("Chat correction completed")

    @Slot(str)
    def _on_chat_failed(self, message: str) -> None:
        self._remove_loading_bubble()
        user_message = "Correction failed. Check Ollama API settings."
        self._add_chat_bubble("error", user_message)
        self.log.error("Chat correction failed: %s", message)
        self.set_status("error")

    @Slot()
    def _on_chat_thread_finished(self) -> None:
        if self.config.show_loading_overlay and self.loading_overlay is not None:
            self.loading_overlay.hide_loading()
        self.correction_thread = None
        self.correction_worker = None
        if self._status_key != "error":
            self.set_status("running" if self.controller.is_running() else "stopped")
        self._set_chat_busy(False)

    @Slot()
    def clear_chat(self) -> None:
        self.chat_store.clear()
        self._remove_loading_bubble()

        for index in reversed(range(self.chat_layout.count())):
            item = self.chat_layout.itemAt(index)
            widget = item.widget()
            if widget is None or widget is self.empty_chat_widget:
                continue
            self.chat_layout.removeWidget(widget)
            widget.deleteLater()

        self.loading_bubble_row = None
        self.loading_bubble = None
        self.chat_loading_timer.stop()
        self._show_empty_chat_state()
        self.log.info("Chat history cleared")

    @Slot()
    def save_settings(self) -> None:
        updates = {
            "HOTKEY": self.hotkey_field.text().strip() or "ctrl+alt+t",
            "OLLAMA_API_KEY": self.api_key_field.text().strip(),
            "OLLAMA_BASE_URL": self.base_url_field.text().strip() or "https://ollama.com/api",
            "OLLAMA_MODEL": self.model_field.text().strip() or "gpt-oss:120b",
            "OLLAMA_TIMEOUT_SECONDS": str(self.timeout_field.value()),
            "COPY_DELAY": str(self.copy_delay_field.value()),
            "PASTE_DELAY": str(self.paste_delay_field.value()),
            "SHOW_LOADING_OVERLAY": (
                "true" if self.show_loading_overlay_field.isChecked() else "false"
            ),
        }

        try:
            self.settings_manager.update_values(updates)
            self.config = load_config()
            self.chat_store = ChatStore(self.config.data_dir, self.log)
            self.controller.reload_config(self.config)
            self._load_settings_fields()
            self.log.info("Settings saved. API key: %s", mask_api_key(self.config.ollama_api_key))
            self.set_status("running" if self.controller.is_running() else "stopped")
        except Exception as exc:
            self.log.exception("Settings save failed: %s", exc)
            self.set_status("error")
            QMessageBox.warning(self, "Settings Error", f"Could not save settings:\n{exc}")

    @Slot()
    def open_data_folder(self) -> None:
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config.data_dir)))

    @Slot()
    def open_logs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_logs_dir())))

    @Slot()
    def clear_logs(self) -> None:
        clear_log_file()
        self.log_viewer.clear()
        self.log.info("Logs cleared")

    @Slot(str)
    def _append_log(self, message: str) -> None:
        self.log_viewer.appendPlainText(message)
        scrollbar = self.log_viewer.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def exit_app(self) -> None:
        self._exiting = True
        self.controller.stop()
        if self.loading_overlay is not None:
            self.loading_overlay.force_hide()
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._exiting:
            self.controller.stop()
            if self.loading_overlay is not None:
                self.loading_overlay.force_hide()
            event.accept()
            return

        event.ignore()
        self.hide()
        if self.tray_icon and self.tray_icon.isVisible() and not self._tray_message_shown:
            self.tray_icon.showMessage(
                "Turkish Keyboard Agent",
                "The app is still running in the system tray.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
            self._tray_message_shown = True

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_from_tray()


def run_app() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Turkish Keyboard Agent")
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    return app.exec()


APP_STYLESHEET = """
QWidget#Root {
    background: #0f1724;
    color: #e7eefc;
    font-family: "Segoe UI";
    font-size: 13px;
}
QLabel#AppTitle {
    font-size: 26px;
    font-weight: 800;
    color: #ffffff;
}
QLabel#Subtitle {
    color: #91a4c7;
    font-size: 13px;
}
QFrame#Card {
    background: #162033;
    border: 1px solid #263650;
    border-radius: 12px;
}
QLabel#CardTitle {
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
}
QLabel#CardSubtitle {
    color: #8fa2c4;
    font-size: 12px;
    margin-top: -6px;
}
QFrame#ChatArea {
    background: transparent;
}
QScrollArea#ChatScroll {
    background: #0b1220;
    border: 1px solid #253650;
    border-radius: 14px;
    margin: 0px;
}
QScrollArea#ChatScroll > QWidget > QWidget {
    background: #0b1220;
}
QWidget#ChatContent {
    background: #0b1220;
}
QWidget#ChatRow {
    background: transparent;
}
QFrame#EmptyChatState {
    background: #111b2d;
    border: 1px dashed #33445f;
    border-radius: 16px;
    min-width: 460px;
}
QLabel#EmptyChatTitle {
    color: #e7eefc;
    font-size: 12px;
    font-weight: 700;
}
QLabel#EmptyChatExample {
    color: #91a4c7;
    font-size: 12px;
}
QFrame#ChatComposer {
    background: #0d1422;
    border: 1px solid #263650;
    border-radius: 14px;
    margin: 0px;
}
QPlainTextEdit#ChatInput {
    background: #101a2c;
    border: 1px solid #2f4261;
    border-radius: 14px;
    color: #eef4ff;
    padding: 8px 12px;
    selection-background-color: #2f80ed;
}
QPlainTextEdit#ChatInput:focus {
    border: 1px solid #3b82f6;
}
QLabel#InputHint {
    color: #7384a3;
    font-size: 11px;
    padding-left: 4px;
}
QFrame#Bubble_user {
    background: #2563eb;
    border: 1px solid #3b82f6;
    border-radius: 18px;
}
QFrame#Bubble_assistant {
    background: #202c40;
    border: 1px solid #31425f;
    border-radius: 18px;
}
QFrame#Bubble_system {
    background: #334155;
    border: 1px solid #475569;
    border-radius: 18px;
}
QFrame#Bubble_error {
    background: #7f1d1d;
    border: 1px solid #ef4444;
    border-radius: 18px;
}
QLabel#BubbleRole {
    color: #c6d4ee;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.3px;
}
QLabel#BubbleText {
    color: #ffffff;
    font-size: 13px;
    line-height: 1.4;
}
QLabel#BubbleTime {
    color: #9fb0cf;
    font-size: 10px;
}
QPushButton#BubbleCopyButton {
    background: transparent;
    color: #a9b8d6;
    border: 1px solid #40536f;
    border-radius: 9px;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 700;
}
QPushButton#BubbleCopyButton:hover {
    background: #2a3952;
    color: #ffffff;
}
QPushButton#SendChatButton {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 18px;
    padding: 10px 14px;
    font-size: 15px;
    font-weight: 900;
}
QPushButton#SendChatButton:hover {
    background: #3478ff;
}
QPushButton#ClearChatButton {
    background: #263650;
    color: #dbe7fb;
    border: 1px solid #354966;
    border-radius: 12px;
    padding: 10px 12px;
    font-weight: 700;
}
QPushButton#ClearChatButton:hover {
    background: #314564;
}
QLabel {
    color: #d7e2f5;
}
QLineEdit, QPlainTextEdit, QDoubleSpinBox {
    background: #0d1422;
    border: 1px solid #2b3b56;
    border-radius: 8px;
    color: #eef4ff;
    padding: 8px;
    selection-background-color: #2f80ed;
}
QPlainTextEdit {
    line-height: 1.35;
}
QCheckBox {
    color: #d7e2f5;
    spacing: 8px;
}
QPushButton {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 700;
}
QPushButton:hover {
    background: #3478ff;
}
QPushButton:pressed {
    background: #1d4ed8;
}
QPushButton:disabled {
    background: #334155;
    color: #7f8da6;
}
QMenu {
    background: #162033;
    color: #e7eefc;
    border: 1px solid #263650;
}
QMenu::item:selected {
    background: #2563eb;
}
"""
