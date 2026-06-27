import json
import os
import sys

import html
import re
import shutil

from PySide6.QtCore import (
    QObject,
    QThread,
    Signal,
    Qt,
    QEvent,
    QTimer,
    QSize,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import QFont, QFontMetrics, QTextCursor, QImage, QPixmap, QIcon, QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from . import backup as content_backup
from .config import Config
from .core import (
    Updater,
    CancelledError,
    UpdateError,
    PHASES,
    connect_sftp,
    find_remote_file,
    subdir_from_match,
)
from .paths import resource_path
from .curseforge import find_latest_server_pack, download_file, get_project_name, CurseForgeError
from .secrets_bws import (
    resolve_secrets,
    config_needs_bws,
    SECRET_ROLES,
    SecretError,
    token_present,
    set_token_for_session,
    persist_token,
)
from .theme import (
    apply_theme,
    nav_icon,
    MUTED,
    PENDING,
    RUNNING,
    SUCCESS,
    FAILED,
    BORDER,
    HEADING,
    BRAND_MINT,
)


class _WheelGuard(QObject):
    """Redirect wheel events on inner widgets to the page scroll area, unless the
    widget is focused. Stops hovering a field from hijacking page scrolling."""

    def __init__(self, scroll):
        super().__init__(scroll)
        self._scroll = scroll

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            sb = self._scroll.verticalScrollBar()
            sb.setValue(sb.value() - event.angleDelta().y())
            return True
        return False


def _configure_scroll(scroll):
    """Make a QScrollArea behave: no horizontal bar, wrapped labels, and
    wheel-over-fields scrolls the page instead of the field."""
    from PySide6.QtWidgets import QSpinBox, QListWidget
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    # Scope the transparent background to the viewport itself. A bare
    # "background: transparent" set inline on the viewport cascades to every
    # descendant (and inline rules outrank the app stylesheet), which wipes out
    # button fills - fatal for borderless PrimaryButtons. An objectName-scoped
    # rule keeps the viewport transparent without leaking onto children.
    scroll.viewport().setObjectName("ScrollViewport")
    scroll.setStyleSheet("#ScrollViewport { background: transparent; }")
    for label in scroll.findChildren(QLabel):
        label.setWordWrap(True)
    guard = _WheelGuard(scroll)
    for widget_type in (QSpinBox, QPlainTextEdit, QListWidget):
        for widget in scroll.findChildren(widget_type):
            widget.installEventFilter(guard)


def _linkify(text):
    escaped = html.escape(text)
    escaped = re.sub(r'(https?://[^\s]+)', r'<a href="\1">\1</a>', escaped)
    return escaped.replace("\n", "<br>")


def show_error_dialog(parent, title, message):
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.RichText)
    box.setText(_linkify(message))
    label = box.findChild(QLabel, "qt_msgbox_label")
    if label:
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    box.exec()


def _human_size(num):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.2f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.2f} PB"


def _add_shadow(widget, blur=24, dy=6, alpha=70):
    """Soft drop shadow for card elevation."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


class Card(QFrame):
    def __init__(self, title=None):
        super().__init__()
        self.setObjectName("Card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(18, 16, 18, 18)
        self.box.setSpacing(12)
        _add_shadow(self)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self.box.addWidget(label)

    def add(self, widget, stretch=0):
        self.box.addWidget(widget, stretch)

    def add_layout(self, layout):
        self.box.addLayout(layout)


class StatTile(QFrame):
    def __init__(self, label, badge=False):
        super().__init__()
        self.setObjectName("Tile")
        self._badge = badge
        _add_shadow(self, blur=18, dy=4, alpha=55)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(6)
        self.label = QLabel(label.upper())
        self.label.setObjectName("StatLabel")
        self.value = QLabel("-")
        if badge:
            # A status pill: object name + dynamic 'state' drive the QSS colour.
            self.value.setObjectName("StatusBadge")
            self.value.setProperty("state", "idle")
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(self.value, 0, Qt.AlignLeft)
            row.addStretch(1)
            box.addWidget(self.label)
            box.addLayout(row)
        else:
            self.value.setObjectName("StatValue")
            box.addWidget(self.label)
            box.addWidget(self.value)
        box.addStretch(1)

    def set_value(self, text, color=None):
        self.value.setText(text)
        if not self._badge:
            self.value.setStyleSheet(f"color: {color};" if color else "")

    def set_state(self, text, state):
        """For badge tiles: set text and re-polish the pill for `state`."""
        self.value.setText(text)
        self.value.setProperty("state", state)
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)


class PlaceholderListWidget(QListWidget):
    """A list that paints centered placeholder text when it holds no items."""

    def __init__(self, placeholder):
        super().__init__()
        self._placeholder = placeholder

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(MUTED))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter | Qt.TextWordWrap,
                             self._placeholder)
            painter.end()


class Toast(QFrame):
    """Transient bottom-right notification that fades in, lingers, and fades out."""

    GLYPHS = {"success": "✓", "error": "✕", "info": "•"}
    COLORS = {"success": SUCCESS, "error": FAILED, "info": RUNNING}

    def __init__(self, parent, text, kind="success", duration=2600):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("kind", kind)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 11, 16, 11)
        row.setSpacing(10)
        glyph = QLabel(self.GLYPHS.get(kind, "•"))
        glyph.setStyleSheet(
            f"color: {self.COLORS.get(kind, RUNNING)}; font-size: 15px; font-weight: 800;"
        )
        label = QLabel(text)
        label.setObjectName("ToastText")
        row.addWidget(glyph)
        row.addWidget(label)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self.adjustSize()
        self._reposition()

        self._fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_in.setDuration(160)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_out.setDuration(260)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self.deleteLater)

        self.show()
        self.raise_()
        self._fade_in.start()
        QTimer.singleShot(duration, self._fade_out.start)

    def _reposition(self):
        parent = self.parentWidget()
        if not parent:
            return
        margin = 22
        x = parent.width() - self.width() - margin
        y = parent.height() - self.height() - margin
        self.move(max(margin, x), max(margin, y))

    @staticmethod
    def show_message(host, text, kind="success"):
        """`host` is any widget; the toast is parented to its top-level window."""
        window = host.window() if host else None
        if window is not None:
            Toast(window, text, kind)


def _page_header(title, subtitle):
    wrap = QVBoxLayout()
    wrap.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("Header")
    s = QLabel(subtitle)
    s.setObjectName("SubHeader")
    s.setWordWrap(True)
    wrap.addWidget(t)
    wrap.addWidget(s)
    return wrap


class Worker(QObject):
    log_line = Signal(str)
    phase = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.log_line.emit("Resolving secrets...")
            secrets = resolve_secrets(
                self.config.secrets, self.config.bws_project_id, log=self.log_line.emit
            )
            self.log_line.emit("Secrets ready.")
            updater = Updater(
                self.config,
                secrets,
                log=self.log_line.emit,
                is_cancelled=lambda: self._cancel,
                phase=self.phase.emit,
            )
            updater.run()
            if updater.unplaced_config:
                names = ", ".join(updater.unplaced_config)
                self.finished.emit(
                    True,
                    f"Update completed, but {len(updater.unplaced_config)} config "
                    f"file(s) had no known destination and were placed in config/ root, "
                    f"so they may not take effect: {names}. Set a path for them on the "
                    f"Content page.",
                )
            else:
                self.finished.emit(True, "Update completed!")
        except CancelledError as e:
            self.finished.emit(False, str(e))
        except UpdateError as e:
            msg = str(e)
            if e.help_url:
                msg += f"\n\nHelp: {e.help_url}"
            self.log_line.emit(f"ERROR: {msg}")
            self.finished.emit(False, msg)
        except SecretError as e:
            self.log_line.emit(f"ERROR: {e}")
            self.finished.emit(False, str(e))
        except Exception as e:
            self.log_line.emit(f"ERROR: {e}")
            self.finished.emit(False, str(e))


class ProjectNameWorker(QObject):
    done = Signal(int, str)
    failed = Signal(int)

    def __init__(self, project_id):
        super().__init__()
        self.project_id = project_id

    def run(self):
        try:
            name = get_project_name(self.project_id)
            self.done.emit(self.project_id, name)
        except Exception:
            self.failed.emit(self.project_id)


class DiscoverWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, object)  # (success, info dict or error string)

    def __init__(self, project_id, name_match):
        super().__init__()
        self.project_id = project_id
        self.name_match = name_match

    def run(self):
        try:
            info = find_latest_server_pack(
                self.project_id, self.name_match, log=self.log_line.emit
            )
            self.finished.emit(True, info)
        except CurseForgeError as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, str(e))


class DownloadWorker(QObject):
    log_line = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, url, dest_path):
        super().__init__()
        self.url = url
        self.dest_path = dest_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            download_file(
                self.url,
                self.dest_path,
                log=self.log_line.emit,
                progress_cb=self.progress.emit,
                is_cancelled=lambda: self._cancel,
            )
            self.finished.emit(True, f"Downloaded {self.dest_path}")
        except CurseForgeError as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, str(e))


class RemoteSearchWorker(QObject):
    """Connects via SFTP and finds where a config file currently lives on the
    server. Emits finished(success, matches_or_error)."""

    finished = Signal(bool, object)  # (success, list[str] of remote paths OR error str)

    def __init__(self, config, filename):
        super().__init__()
        self.config = config
        self.filename = filename

    def run(self):
        try:
            secrets = resolve_secrets(self.config.secrets, self.config.bws_project_id)
            client, sftp = connect_sftp(secrets)
            try:
                search_base = f"{self.config.remote_base}config"
                matches = find_remote_file(sftp, search_base, self.filename)
            finally:
                sftp.close()
                client.close()
            self.finished.emit(True, matches)
        except (UpdateError, SecretError) as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, str(e))


def ensure_bws_token(parent) -> bool:
    """Ensure a Bitwarden access token is available, prompting for one if not.

    Returns True if a token is present (or was supplied), False if the user
    cancelled. Shared by the Run and Content pages.
    """
    if token_present():
        return True
    dialog = TokenDialog(parent)
    if dialog.exec() != QDialog.Accepted:
        return False
    token = dialog.token()
    if not token:
        QMessageBox.warning(parent, "No token", "No token was entered.")
        return False
    set_token_for_session(token)
    if dialog.should_remember():
        persist_token(token)
    return True


class BusyDialog(QDialog):
    """A small modal 'please wait' dialog with an indeterminate bar. Stays open
    until finish() is called by the operation that owns it."""

    def __init__(self, parent, message):
        super().__init__(parent)
        self.setWindowTitle("Please wait")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._can_close = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        layout.addWidget(bar)

    def finish(self):
        self._can_close = True
        self.accept()

    def closeEvent(self, event):
        if self._can_close:
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        # Don't let Escape dismiss the dialog before the lookup finishes.
        if event.key() == Qt.Key_Escape and not self._can_close:
            event.ignore()
        else:
            super().keyPressEvent(event)


class TokenDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bitwarden access token")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        info = QLabel(
            "No BWS_ACCESS_TOKEN was found. Paste your Bitwarden Secrets Manager "
            "machine-account access token to continue."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("0.xxxxxxxx...")
        layout.addWidget(self.token_edit)

        self.remember = QCheckBox("Remember on this PC (saves to your user environment)")
        self.remember.setChecked(True)
        layout.addWidget(self.remember)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setText("Use token")
        ok.setObjectName("PrimaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def token(self) -> str:
        return self.token_edit.text().strip()

    def should_remember(self) -> bool:
        return self.remember.isChecked()


class PhaseRow(QWidget):
    COLORS = {"pending": PENDING, "active": RUNNING, "done": SUCCESS, "failed": FAILED}
    GLYPHS = {"pending": "○", "active": "●", "done": "✓", "failed": "✕"}

    def __init__(self, text):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedWidth(18)
        icon_font = QFont()
        icon_font.setPointSize(12)
        self.icon.setFont(icon_font)
        self.label = QLabel(text)
        row.addWidget(self.icon)
        row.addWidget(self.label)
        row.addStretch(1)
        self.set_state("pending")

    def set_state(self, state):
        self.icon.setText(self.GLYPHS[state])
        self.icon.setStyleSheet(f"color: {self.COLORS[state]};")
        if state == "active":
            self.label.setStyleSheet(f"color: {HEADING}; font-weight: 600;")
        elif state == "done":
            self.label.setStyleSheet(f"color: {BRAND_MINT};")
        elif state == "failed":
            self.label.setStyleSheet(f"color: {FAILED}; font-weight: 600;")
        else:
            self.label.setStyleSheet(f"color: {MUTED};")


class ActivityDialog(QDialog):
    def __init__(self, parent, phases, title="Updating server"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self.setModal(True)
        self._finished = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        heading = QLabel(title)
        heading.setObjectName("Header")
        layout.addWidget(heading)

        card = Card()
        self.rows = {}
        for key, text in phases:
            row = PhaseRow(text)
            self.rows[key] = row
            card.add(row)
        layout.addWidget(card)

        self.detail = QLabel("Preparing...")
        self.detail.setObjectName("SubHeader")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate while running
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMaximumHeight(180)
        self.log.setVisible(False)
        layout.addWidget(self.log)

        buttons = QHBoxLayout()
        self.toggle_btn = QPushButton("Show details")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.toggled.connect(self._toggle_log)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("DangerButton")
        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("PrimaryButton")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.toggle_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    def _toggle_log(self, checked):
        self.log.setVisible(checked)
        self.toggle_btn.setText("Hide details" if checked else "Show details")
        self.adjustSize()

    def set_phase(self, key):
        order = list(self.rows.keys())
        if key in order:
            idx = order.index(key)
            for i, k in enumerate(order):
                if i < idx:
                    self.rows[k].set_state("done")
                elif i == idx:
                    self.rows[k].set_state("active")

    def append_log(self, line):
        self.log.appendPlainText(line)
        self.log.moveCursor(QTextCursor.End)
        text = line.strip()
        if text and not text.startswith("="):
            self.detail.setText(text)

    def set_finished(self, success, message):
        self._finished = True
        if success:
            for row in self.rows.values():
                row.set_state("done")
        else:
            for row in self.rows.values():
                if row.icon.text() == PhaseRow.GLYPHS["active"]:
                    row.set_state("failed")
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if success else 0)
        self.detail.setText(("Done. " if success else "Failed. ") + message)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

    def closeEvent(self, event):
        if self._finished:
            event.accept()
        else:
            event.ignore()


class RunPage(QWidget):
    def __init__(self, config, get_config):
        super().__init__()
        self.config = config
        self.get_config = get_config
        self.thread = None
        self.worker = None
        self.dl_thread = None
        self.dl_worker = None
        self._busy = False
        self._has_pack = False
        self._project_names = {}
        self._name_thread = None
        self._name_worker = None
        self._name_fetch_id = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        # Hero banner
        hero = QFrame()
        hero.setObjectName("Hero")
        hero_box = QHBoxLayout(hero)
        hero_box.setContentsMargins(24, 20, 24, 20)
        hero_box.setSpacing(16)
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)
        title = QLabel("Update your server")
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        sub = QLabel("Fetch the newest pack and deploy it to your server in one click.")
        sub.setObjectName("HeroSub")
        sub.setWordWrap(True)
        left.addWidget(title)
        left.addWidget(sub)
        hero_box.addWidget(left_w, 1)
        self.download_btn = QPushButton("Download Latest")
        self.download_btn.clicked.connect(self.download_latest)
        self.run_btn = QPushButton("Run Update")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("DangerButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        hero_box.addWidget(self.download_btn)
        hero_box.addWidget(self.run_btn)
        hero_box.addWidget(self.cancel_btn)
        layout.addWidget(hero)

        # Stat tiles
        grid = QGridLayout()
        grid.setSpacing(14)
        self.tile_modpack = StatTile("Modpack")
        self.tile_status = StatTile("Status", badge=True)
        self.tile_pack = StatTile("Local pack")
        self.tile_secrets = StatTile("Secrets source")
        self.tile_mods = StatTile("Extra mods")
        self.tile_config = StatTile("Config overrides")
        tiles = [self.tile_modpack, self.tile_status, self.tile_pack,
                 self.tile_secrets, self.tile_mods, self.tile_config]
        for i, tile in enumerate(tiles):
            grid.addWidget(tile, i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        layout.addLayout(grid)

        self.no_pack_hint = QLabel(
            "No pack downloaded yet - click Download Latest to fetch the newest version."
        )
        self.no_pack_hint.setObjectName("SubHeader")
        self.no_pack_hint.setWordWrap(True)
        self.no_pack_hint.setVisible(False)
        layout.addWidget(self.no_pack_hint)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        layout.addStretch(1)

        self._set_status("Idle", "idle")
        self._refresh_tiles()

    def showEvent(self, event):
        self._refresh_tiles()
        super().showEvent(event)

    def _refresh_tiles(self):
        cfg = self.config
        # Modpack name (fetched in the background, cached per project id)
        self._ensure_project_name()

        # Local pack
        try:
            packs = [f for f in os.listdir(cfg.base_dir)
                     if f.startswith("ServerFiles-") and f.endswith(".zip")]
        except OSError:
            packs = []
        if packs:
            newest = max(packs, key=lambda f: os.path.getmtime(os.path.join(cfg.base_dir, f)))
            version = newest[len("ServerFiles-"):-len(".zip")]
            self.tile_pack.set_value(version)
            self._has_pack = True
        else:
            self.tile_pack.set_value("None", MUTED)
            self._has_pack = False

        # Secrets source
        modes = {(s or {}).get("mode", "bws") for s in (cfg.secrets or {}).values()}
        if modes == {"bws"}:
            self.tile_secrets.set_value("Bitwarden")
        elif modes == {"plaintext"}:
            self.tile_secrets.set_value("Plaintext")
        else:
            self.tile_secrets.set_value("Mixed")

        # Content counts
        def count(sub):
            try:
                d = os.path.join(cfg.post_update_dir, sub)
                return sum(1 for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
            except OSError:
                return 0
        self.tile_mods.set_value(str(count("mods")))
        self.tile_config.set_value(str(count("config")))

        self._update_run_enabled()

    def _ensure_project_name(self):
        pid = self.config.curseforge_project_id
        if pid in self._project_names:
            self.tile_modpack.set_value(self._project_names[pid])
            return
        if self._name_fetch_id == pid:
            return
        self._name_fetch_id = pid
        self.tile_modpack.set_value("Loading...", MUTED)
        self._name_thread = QThread()
        self._name_worker = ProjectNameWorker(pid)
        self._name_worker.moveToThread(self._name_thread)
        self._name_thread.started.connect(self._name_worker.run)
        self._name_worker.done.connect(self._on_name)
        self._name_worker.failed.connect(self._on_name_failed)
        self._name_worker.done.connect(self._name_thread.quit)
        self._name_worker.failed.connect(self._name_thread.quit)
        self._name_thread.finished.connect(self._name_thread.deleteLater)
        self._name_thread.start()

    def _on_name(self, pid, name):
        self._project_names[pid] = name
        self._name_fetch_id = None
        if pid == self.config.curseforge_project_id:
            self.tile_modpack.set_value(name)

    def _on_name_failed(self, pid):
        self._name_fetch_id = None
        if pid == self.config.curseforge_project_id and pid not in self._project_names:
            self.tile_modpack.set_value(f"#{pid}", MUTED)

    def _update_run_enabled(self):
        self.cancel_btn.setEnabled(self._busy)
        self.download_btn.setEnabled(not self._busy)
        self.run_btn.setEnabled(not self._busy and self._has_pack)
        self.run_btn.setToolTip(
            "" if self._has_pack else "Download the latest pack first."
        )
        self.no_pack_hint.setVisible(not self._busy and not self._has_pack)

    def _set_status(self, text, state):
        self.tile_status.set_state(text, state)

    def append(self, line):
        # Page no longer shows a log panel; live activity lives in the modal dialog.
        # Kept as a hook so download/discovery status messages have a sink.
        pass

    def _ensure_token(self) -> bool:
        return ensure_bws_token(self)

    def _set_busy(self, busy):
        self._busy = busy
        self._update_run_enabled()

    def start(self):
        config = self.get_config()
        if config_needs_bws(config.secrets) and not self._ensure_token():
            self._set_status("No token", "failed")
            return
        self._set_busy(True)
        self._set_status("Running...", "running")

        self.activity = ActivityDialog(self, PHASES, title="Updating server")

        self.thread = QThread()
        self.worker = Worker(config)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log_line.connect(self.activity.append_log)
        self.worker.phase.connect(self.activity.set_phase)
        self.worker.finished.connect(self.activity.set_finished)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.activity.cancel_btn.clicked.connect(self.cancel)
        self.activity.show()
        self.thread.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel()
            self._set_status("Cancelling...", "running")
            self.cancel_btn.setEnabled(False)
        elif self.dl_worker:
            self.dl_worker.cancel()
            self._set_status("Cancelling...", "running")
            self.cancel_btn.setEnabled(False)

    def on_finished(self, success, message):
        self._set_status("Completed" if success else "Failed",
                         "success" if success else "failed")
        self._set_busy(False)
        self.worker = None
        self._refresh_tiles()
        if not success and "cancel" not in message.lower():
            show_error_dialog(self, "Update failed", message)

    # ------------------------------------------------------------------
    # CurseForge download flow
    # ------------------------------------------------------------------
    def download_latest(self):
        config = self.get_config()
        self._set_busy(True)
        self._set_status("Searching...", "running")

        self.thread = QThread()
        self.discover_worker = DiscoverWorker(
            config.curseforge_project_id, config.server_pack_match
        )
        self.discover_worker.moveToThread(self.thread)
        self.thread.started.connect(self.discover_worker.run)
        self.discover_worker.finished.connect(self.on_discovered)
        self.discover_worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_discovered(self, success, result):
        self.discover_worker = None
        if not success:
            self._set_status("Search failed", "failed")
            show_error_dialog(self, "Search failed", str(result))
            self._set_busy(False)
            return

        info = result
        dest_dir = self.get_config().base_dir
        size = _human_size(info["file_length"])
        date = info["date"].split("T")[0] if info.get("date") else "unknown date"
        details = (
            f"Found: {info['file_name']}\n"
            f"Version: {info['parent_version']}\n"
            f"Released: {date}\n"
            f"Size: {size}\n\n"
            f"Download to:\n{dest_dir}"
        )
        box = QMessageBox(self)
        box.setWindowTitle("Confirm download")
        box.setText("Latest server pack found on CurseForge.")
        box.setInformativeText(details)
        dl = box.addButton("Download", QMessageBox.AcceptRole)
        box.addButton("Abort", QMessageBox.RejectRole)
        dl.setObjectName("PrimaryButton")
        box.exec()
        if box.clickedButton() is not dl:
            self._set_status("Aborted", "idle")
            self._set_busy(False)
            return

        self._start_download(info, dest_dir)

    def _start_download(self, info, dest_dir):
        dest_path = os.path.join(dest_dir, info["file_name"])
        self._set_status("Downloading...", "running")
        self.progress.setValue(0)
        self.progress.setVisible(True)

        self.dl_thread = QThread()
        self.dl_worker = DownloadWorker(info["download_url"], dest_path)
        self.dl_worker.moveToThread(self.dl_thread)
        self.dl_thread.started.connect(self.dl_worker.run)
        self.dl_worker.log_line.connect(self.append)
        self.dl_worker.progress.connect(self._on_download_progress)
        self.dl_worker.finished.connect(self.on_download_finished)
        self.dl_worker.finished.connect(self.dl_thread.quit)
        self.dl_thread.finished.connect(self.dl_thread.deleteLater)
        self.dl_thread.start()

    def _on_download_progress(self, pct):
        self.progress.setValue(pct)

    def on_download_finished(self, success, message):
        self.progress.setVisible(False)
        self._set_status("Downloaded" if success else "Failed",
                         "success" if success else "failed")
        self._set_busy(False)
        self.dl_worker = None
        self._refresh_tiles()

        if success:
            reply = QMessageBox.question(
                self,
                "Run update now?",
                "Download complete. Push the new server pack to the server now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.start()
        elif "cancel" not in message.lower():
            show_error_dialog(self, "Download failed", message)


class SettingsPage(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)
        outer.addLayout(_page_header("Settings", "Configure paths, server targets, and update behavior."))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(16)

        # Locations & connection
        conn = Card("Locations & connection")
        form = QFormLayout()
        form.setSpacing(10)
        self.base_dir = QLineEdit(config.base_dir)
        form.addRow("Downloads folder:", self._browse_row(self.base_dir))
        self.post_update_dir = QLineEdit(config.post_update_dir)
        form.addRow("Post-update folder:", self._browse_row(self.post_update_dir))
        self.remote_base = QLineEdit(config.remote_base)
        form.addRow("Remote base path:", self.remote_base)
        conn.add_layout(form)
        layout.addWidget(conn)

        # CurseForge download
        cf = Card("CurseForge download")
        cform = QFormLayout()
        cform.setSpacing(10)
        self.curseforge_project_id = QLineEdit(str(config.curseforge_project_id))
        cform.addRow("Project ID:", self.curseforge_project_id)
        self.server_pack_match = QLineEdit(config.server_pack_match)
        self.server_pack_match.setPlaceholderText("text the server pack filename contains")
        cform.addRow("Server pack name contains:", self.server_pack_match)
        cf.add_layout(cform)
        layout.addWidget(cf)

        # Timing & retries
        timing = Card("Timing & retries")
        tform = QFormLayout()
        tform.setSpacing(10)
        self.stop_delay = QSpinBox()
        self.stop_delay.setRange(0, 600)
        self.stop_delay.setValue(config.stop_delay)
        self.stop_delay.setSuffix(" s")
        tform.addRow("Stop delay:", self.stop_delay)
        self.upload_retries = QSpinBox()
        self.upload_retries.setRange(1, 20)
        self.upload_retries.setValue(config.upload_retries)
        tform.addRow("Upload retries:", self.upload_retries)
        timing.add_layout(tform)
        layout.addWidget(timing)

        # Targets
        targets_card = Card("Target folders / files (one per line)")
        self.targets = QPlainTextEdit("\n".join(config.targets))
        self.targets.setFont(QFont("Consolas", 9))
        targets_card.add(self.targets)
        layout.addWidget(targets_card)

        # Post-update
        post_card = Card("Post-update handling")
        post_card.add(QLabel("Post-update folders (one per line):"))
        self.post_update_folders = QPlainTextEdit("\n".join(config.post_update_folders))
        self.post_update_folders.setFont(QFont("Consolas", 9))
        self.post_update_folders.setMaximumHeight(80)
        post_card.add(self.post_update_folders)
        post_card.add(QLabel("Known file paths (JSON):"))
        self.known_file_paths = QPlainTextEdit(json.dumps(config.known_file_paths, indent=2))
        self.known_file_paths.setFont(QFont("Consolas", 9))
        post_card.add(self.known_file_paths)
        layout.addWidget(post_card)

        # Folders
        folders = Card("App folders")
        folders.add(QLabel(
            "The app creates these folders for your custom content. "
            "Drop extra mods, configs, and a custom server-icon.png into the post-update folders."
        ))
        folder_btns = QHBoxLayout()
        open_content = QPushButton("Open content folder")
        open_content.clicked.connect(lambda: self._open_folder(self.config.post_update_dir))
        open_downloads = QPushButton("Open downloads folder")
        open_downloads.clicked.connect(lambda: self._open_folder(self.config.base_dir))
        folder_btns.addWidget(open_content)
        folder_btns.addWidget(open_downloads)
        folder_btns.addStretch(1)
        folders.add_layout(folder_btns)
        layout.addWidget(folders)

        layout.addStretch(1)
        scroll.setWidget(container)
        _configure_scroll(scroll)
        outer.addWidget(scroll, 1)

        save_row = QHBoxLayout()
        self.saved_label = QLabel("")
        self.saved_label.setObjectName("SubHeader")
        save_row.addWidget(self.saved_label, 1)
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self.save)
        save_row.addWidget(self.save_btn)
        outer.addLayout(save_row)

    def _browse_row(self, line_edit):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line_edit, 1)
        btn = QPushButton("Browse...")

        def browse():
            path = QFileDialog.getExistingDirectory(self, "Select folder", line_edit.text())
            if path:
                line_edit.setText(path)

        btn.clicked.connect(browse)
        row.addWidget(btn)
        return row

    def apply_to_config(self) -> bool:
        try:
            known = json.loads(self.known_file_paths.toPlainText() or "{}")
            if not isinstance(known, dict):
                raise ValueError("Known file paths must be a JSON object.")
        except (json.JSONDecodeError, ValueError) as e:
            QMessageBox.warning(self, "Invalid JSON", f"Known file paths: {e}")
            return False

        self.config.base_dir = self.base_dir.text().strip()
        self.config.post_update_dir = self.post_update_dir.text().strip()
        self.config.remote_base = self.remote_base.text().strip() or "/"
        try:
            self.config.curseforge_project_id = int(self.curseforge_project_id.text().strip() or 0)
        except ValueError:
            QMessageBox.warning(self, "Invalid value", "CurseForge Project ID must be a number.")
            return False
        self.config.server_pack_match = self.server_pack_match.text().strip() or "ServerFiles"
        self.config.stop_delay = self.stop_delay.value()
        self.config.upload_retries = self.upload_retries.value()
        self.config.targets = [
            ln.strip() for ln in self.targets.toPlainText().splitlines() if ln.strip()
        ]
        self.config.post_update_folders = [
            ln.strip()
            for ln in self.post_update_folders.toPlainText().splitlines()
            if ln.strip()
        ]
        self.config.known_file_paths = known
        return True

    def save(self):
        if not self.apply_to_config():
            return
        self.config.save()
        self.saved_label.setText("Settings saved.")
        Toast.show_message(self, "Settings saved", "success")

    def _open_folder(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except (OSError, AttributeError):
            QMessageBox.warning(self, "Open folder", f"Could not open:\n{path}")


def convert_to_server_icon(src_path, dest_path):
    """Resize/convert any image to a 64x64 PNG saved at dest_path."""
    img = QImage(src_path)
    if img.isNull():
        return False, "That file isn't a readable image."
    scaled = img.scaled(64, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - 64) // 2)
    y = max(0, (scaled.height() - 64) // 2)
    cropped = scaled.copy(x, y, 64, 64)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if not cropped.save(dest_path, "PNG"):
        return False, "Failed to save the converted icon."
    return True, "Server icon set (64x64 PNG)."


class FileEditorDialog(QDialog):
    def __init__(self, parent, path):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(os.path.basename(path))
        self.setMinimumSize(640, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.edit = QPlainTextEdit()
        self.edit.setFont(QFont("Consolas", 10))
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                self.edit.setPlainText(f.read())
        except OSError as e:
            self.edit.setPlainText(f"# Could not read file: {e}")
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("PrimaryButton")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(self.edit.toPlainText())
            self.accept()
        except OSError as e:
            QMessageBox.warning(self, "Save failed", str(e))


class ContentPage(QWidget):
    def __init__(self, config, get_config=None):
        super().__init__()
        self.config = config
        # Returns the live merged config (Settings + Secrets applied); used only
        # by 'Find on server', which needs the current remote_base and secrets.
        self.get_config = get_config or (lambda: config)
        self._search_thread = None
        self._search_worker = None
        self._search_busy = None
        self._search_result = None
        self._search_base = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        outer.addLayout(_page_header(
            "Content", "Make it yours - layer custom mods, configs, and a server icon onto every update."
        ))
        explain = QLabel(
            "After the base server pack is uploaded, your custom content is applied on top:\n"
            "  -  Mods: extra or replacement .jar files added to the server's mods folder.\n"
            "  -  Config overrides: config files matched by name and replaced. Pin an exact "
            "destination with 'Find on server' or 'Set path' so a file can't be missed.\n"
            "  -  Server icon: a 64x64 server-icon.png placed in the server root."
        )
        explain.setObjectName("SubHeader")
        explain.setWordWrap(True)
        outer.addWidget(explain)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(16)

        # Mods
        mods_card = Card("Extra / override mods")
        self.mods_list = PlaceholderListWidget(
            "No extra mods yet.\nClick “Add jars…” to layer mods onto every update."
        )
        self.mods_list.setMaximumHeight(150)
        mods_card.add(self.mods_list)
        mods_card.add_layout(self._row([
            ("Add jars...", self.add_mods, False),
            ("Remove", self.remove_mods, False),
            ("Open folder", lambda: self._open(self._mods_dir()), False),
        ]))
        layout.addWidget(mods_card)

        # Config
        config_card = Card("Config overrides")
        self.config_list = PlaceholderListWidget(
            "No config overrides yet.\nAdd files or create a new one to override pack configs."
        )
        self.config_list.setMaximumHeight(150)
        self.config_list.itemDoubleClicked.connect(lambda _i: self.edit_config())
        config_card.add(self.config_list)
        config_card.add_layout(self._row([
            ("Add files...", self.add_configs, False),
            ("New file...", self.new_config, False),
            ("Edit", self.edit_config, False),
            ("Remove", self.remove_configs, False),
            ("Open folder", lambda: self._open(self._config_dir()), False),
        ]))
        # Destination row: pin where the selected config file is written on the
        # server, so it can't be missed by name-matching.
        dest_row = QHBoxLayout()
        dest_label = QLabel("Selected file's destination:")
        dest_label.setObjectName("SubHeader")
        dest_row.addWidget(dest_label)
        find_btn = QPushButton("Find on server...")
        find_btn.clicked.connect(self.find_on_server)
        set_btn = QPushButton("Set path...")
        set_btn.clicked.connect(self.set_config_path)
        dest_row.addWidget(find_btn)
        dest_row.addWidget(set_btn)
        dest_row.addStretch(1)
        config_card.add_layout(dest_row)
        layout.addWidget(config_card)

        # Server icon
        icon_card = Card("Server icon")
        icon_card.add(QLabel(
            "Minecraft requires a 64x64 PNG named server-icon.png. Pick any image "
            "(PNG, JPG, BMP, etc.) and it is resized and renamed automatically."
        ))
        icon_row = QHBoxLayout()
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(64, 64)
        self.icon_preview.setStyleSheet(f"border: 1px solid {BORDER}; border-radius: 6px;")
        self.icon_preview.setAlignment(Qt.AlignCenter)
        self.icon_status = QLabel()
        self.icon_status.setObjectName("SubHeader")
        icon_row.addWidget(self.icon_preview)
        icon_row.addWidget(self.icon_status, 1)
        icon_card.add_layout(icon_row)
        icon_btns = QHBoxLayout()
        self.set_icon_btn = QPushButton("Set custom icon...")
        self.set_icon_btn.setObjectName("PrimaryButton")
        self.set_icon_btn.clicked.connect(self.set_icon)
        self.remove_icon_btn = QPushButton("Remove icon")
        self.remove_icon_btn.clicked.connect(self.remove_icon)
        icon_btns.addWidget(self.set_icon_btn)
        icon_btns.addWidget(self.remove_icon_btn)
        icon_btns.addStretch(1)
        icon_card.add_layout(icon_btns)
        layout.addWidget(icon_card)

        # Backup & restore
        backup_card = Card("Backup & restore")
        backup_card.add(QLabel(
            "Save all your custom mods, configs, and server-files into a single zip file - "
            "useful before reinstalling Kascade on another PC. Restore merges the zip on "
            "top of your current content, overwriting any files with the same name."
        ))
        backup_card.add_layout(self._row([
            ("Create backup...", self.create_backup, True),
            ("Restore from backup...", self.restore_backup, False),
        ]))
        layout.addWidget(backup_card)

        layout.addStretch(1)
        scroll.setWidget(container)
        _configure_scroll(scroll)
        outer.addWidget(scroll, 1)

        self._refresh()

    # ----- helpers -----
    def _row(self, buttons):
        row = QHBoxLayout()
        for text, handler, primary in buttons:
            btn = QPushButton(text)
            if primary:
                btn.setObjectName("PrimaryButton")
            btn.clicked.connect(handler)
            row.addWidget(btn)
        row.addStretch(1)
        return row

    def _mods_dir(self):
        return os.path.join(self.config.post_update_dir, "mods")

    def _config_dir(self):
        return os.path.join(self.config.post_update_dir, "config")

    def _server_files_dir(self):
        return os.path.join(self.config.post_update_dir, "server-files")

    def _icon_path(self):
        return os.path.join(self._server_files_dir(), "server-icon.png")

    def _open(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except (OSError, AttributeError):
            QMessageBox.warning(self, "Open folder", f"Could not open:\n{path}")

    def _list_files(self, directory):
        try:
            return sorted(f for f in os.listdir(directory)
                          if os.path.isfile(os.path.join(directory, f)))
        except OSError:
            return []

    def showEvent(self, event):
        self._refresh()
        super().showEvent(event)

    def _config_destination(self, name):
        """Human label for where a config file will be written on the server."""
        subdir = self.config.get_config_path(name)
        if subdir is None:
            return "Auto (match on server)"
        subdir = subdir.strip("/")
        return f"config/{subdir}/{name}" if subdir else f"config/{name}"

    def _refresh(self):
        self.mods_list.clear()
        self.mods_list.addItems(self._list_files(self._mods_dir()))
        self.config_list.clear()
        for name in self._list_files(self._config_dir()):
            item = QListWidgetItem(f"{name}    →    {self._config_destination(name)}")
            item.setData(Qt.UserRole, name)
            self.config_list.addItem(item)
        icon = self._icon_path()
        if os.path.isfile(icon):
            pix = QPixmap(icon)
            if not pix.isNull():
                self.icon_preview.setPixmap(pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.icon_status.setText("Custom server-icon.png is set.")
        else:
            self.icon_preview.clear()
            self.icon_status.setText("No custom icon set.")

    def _copy_into(self, directory, files):
        os.makedirs(directory, exist_ok=True)
        for src in files:
            try:
                shutil.copy2(src, os.path.join(directory, os.path.basename(src)))
            except OSError as e:
                QMessageBox.warning(self, "Copy failed", f"{os.path.basename(src)}: {e}")
        self._refresh()

    # ----- actions -----
    def add_mods(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add mod jars", "", "Jar files (*.jar)")
        if files:
            self._copy_into(self._mods_dir(), files)

    def remove_mods(self):
        self._remove_selected(self.mods_list, self._mods_dir())

    def add_configs(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add config files", "", "All files (*.*)")
        if files:
            self._copy_into(self._config_dir(), files)

    def new_config(self):
        name, ok = QInputDialog.getText(self, "New config file", "File name (e.g. mymod.toml):")
        name = name.strip()
        if not ok or not name:
            return
        os.makedirs(self._config_dir(), exist_ok=True)
        path = os.path.join(self._config_dir(), name)
        if not os.path.exists(path):
            try:
                open(path, "w", encoding="utf-8").close()
            except OSError as e:
                QMessageBox.warning(self, "Create failed", str(e))
                return
        self._refresh()
        FileEditorDialog(self, path).exec()
        self._refresh()

    def _item_name(self, item):
        """The bare filename for a list item (config rows carry it in UserRole;
        mod rows use the display text directly)."""
        return item.data(Qt.UserRole) or item.text()

    def _selected_config_name(self):
        item = self.config_list.currentItem()
        return self._item_name(item) if item else None

    def edit_config(self):
        name = self._selected_config_name()
        if not name:
            QMessageBox.information(self, "Edit", "Select a config file first.")
            return
        FileEditorDialog(self, os.path.join(self._config_dir(), name)).exec()

    def remove_configs(self):
        self._remove_selected(self.config_list, self._config_dir())

    def _remove_selected(self, list_widget, directory):
        items = list_widget.selectedItems()
        if not items:
            QMessageBox.information(self, "Remove", "Select one or more files first.")
            return
        names = [self._item_name(i) for i in items]
        if QMessageBox.question(self, "Remove files", f"Remove {', '.join(names)}?") != QMessageBox.Yes:
            return
        for name in names:
            try:
                os.remove(os.path.join(directory, name))
            except OSError as e:
                QMessageBox.warning(self, "Remove failed", f"{name}: {e}")
            # Drop any pinned destination for a removed config file.
            if directory == self._config_dir():
                self.config.set_config_path(name, "")
        if directory == self._config_dir():
            self.config.save()
        self._refresh()

    # ----- config destination paths -----
    def _parse_dest_to_subdir(self, text, name):
        """Normalize whatever the user typed into a sub-path relative to config/.

        Accepts a bare sub-folder ('dcint'), a 'config/...'-prefixed path, or a
        full path that ends with the filename, and returns just the sub-folder.
        """
        t = (text or "").strip().strip("/")
        if t.lower() == "config":
            return ""
        if t.lower().startswith("config/"):
            t = t[len("config/"):]
        if t == name:
            return ""
        if t.endswith("/" + name):
            t = t[: -(len(name) + 1)]
        return t.strip("/")

    def _pin_destination(self, name, subdir, toast):
        self.config.set_config_path(name, subdir)
        self.config.save()
        self._refresh()
        Toast.show_message(self, toast, "success")

    def set_config_path(self):
        name = self._selected_config_name()
        if not name:
            QMessageBox.information(self, "Set path", "Select a config file first.")
            return
        current = self.config.get_config_path(name) or ""
        text, ok = QInputDialog.getText(
            self,
            "Set destination path",
            f"Sub-folder under config/ where '{name}' should be written.\n"
            "Leave blank to revert to automatic name-matching.\n"
            "Examples:  dcintegration   or   ftbquests/chapters",
            text=current,
        )
        if not ok:
            return
        self._pin_destination(name, self._parse_dest_to_subdir(text, name),
                              "Destination updated")

    def find_on_server(self):
        name = self._selected_config_name()
        if not name:
            QMessageBox.information(self, "Find on server", "Select a config file first.")
            return
        config = self.get_config()
        if config_needs_bws(config.secrets) and not ensure_bws_token(self):
            return

        self._search_result = None
        self._search_base = f"{config.remote_base}config"
        self._search_busy = BusyDialog(self, f"Searching the server for '{name}'...")
        self._search_thread = QThread()
        self._search_worker = RemoteSearchWorker(config, name)
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.finished.connect(self._on_search_done)
        self._search_worker.finished.connect(self._search_thread.quit)
        self._search_thread.finished.connect(self._search_thread.deleteLater)
        self._search_thread.start()
        self._search_busy.exec()  # modal; closed by _on_search_done via finish()
        self._handle_search_result(name)

    def _on_search_done(self, success, result):
        self._search_result = (success, result)
        self._search_worker = None
        if self._search_busy is not None:
            self._search_busy.finish()

    def _handle_search_result(self, name):
        result = self._search_result
        self._search_result = None
        self._search_busy = None
        if result is None:
            return  # dialog closed without a result
        success, payload = result
        if not success:
            show_error_dialog(self, "Find on server", str(payload))
            return

        matches = payload or []
        if not matches:
            text, ok = QInputDialog.getText(
                self,
                "Not found on server",
                f"'{name}' wasn't found anywhere under config/ on the server.\n"
                "The modpack may not ship it (it can be created on first launch).\n\n"
                "Enter the sub-folder under config/ where it should go "
                "(blank = config root):",
            )
            if ok:
                self._pin_destination(name, self._parse_dest_to_subdir(text, name),
                                      "Destination set")
            return

        # Offer the discovered location(s); the box is editable so the user can
        # also type a sub-folder by hand.
        subdirs = []
        for match in matches:
            sd = subdir_from_match(self._search_base, match)
            if sd not in subdirs:
                subdirs.append(sd)
        labels = []
        label_map = {}
        for sd in subdirs:
            label = f"config/{sd}/{name}" if sd else f"config/{name}"
            labels.append(label)
            label_map[label] = sd
        choice, ok = QInputDialog.getItem(
            self,
            "Found on server",
            f"'{name}' was found at the location(s) below. Pick where future "
            "updates should write it (or type a sub-folder):",
            labels,
            0,
            True,
        )
        if not ok:
            return
        subdir = label_map.get(choice)
        if subdir is None:
            subdir = self._parse_dest_to_subdir(choice, name)
        self._pin_destination(name, subdir, "Destination pinned")

    def set_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)",
        )
        if not path:
            return
        ok, message = convert_to_server_icon(path, self._icon_path())
        self._refresh()
        if ok:
            Toast.show_message(self, "Server icon set", "success")
        else:
            QMessageBox.warning(self, "Server icon", message)

    def remove_icon(self):
        icon = self._icon_path()
        if os.path.isfile(icon):
            try:
                os.remove(icon)
                Toast.show_message(self, "Server icon removed", "info")
            except OSError as e:
                QMessageBox.warning(self, "Remove failed", str(e))
        self._refresh()

    def create_backup(self):
        from datetime import datetime
        default_name = f"kascade-content-{datetime.now().strftime('%Y-%m-%d_%H%M')}.zip"
        target, _ = QFileDialog.getSaveFileName(
            self, "Save backup as", default_name, "Zip files (*.zip)"
        )
        if not target:
            return
        try:
            result = content_backup.create_backup(
                self.config.post_update_dir, target, self.config.content_subfolders()
            )
        except content_backup.BackupError as e:
            QMessageBox.warning(self, "Backup failed", str(e))
            return
        except OSError as e:
            QMessageBox.warning(self, "Backup failed", f"Could not write backup:\n{e}")
            return
        if result.file_count == 0:
            Toast.show_message(self, "Backup created (no custom content found)", "info")
        else:
            Toast.show_message(
                self, f"Backup created ({result.file_count} files)", "success"
            )

    def restore_backup(self):
        source, _ = QFileDialog.getOpenFileName(
            self, "Choose a backup zip", "", "Zip files (*.zip);;All files (*.*)"
        )
        if not source:
            return
        manifest = content_backup.read_manifest(source)
        if manifest is None:
            confirm = QMessageBox.question(
                self,
                "Not a Kascade backup",
                "This zip doesn't carry a Kascade manifest. It may still restore "
                "correctly, but only do this if you trust where it came from.\n\n"
                "Existing files with the same names will be overwritten. Continue?",
            )
        else:
            file_count = manifest.get("file_count", "?")
            folders = ", ".join(manifest.get("folders") or []) or "none"
            confirm = QMessageBox.question(
                self,
                "Restore backup",
                f"Restore {file_count} files into folders: {folders}?\n\n"
                "Existing files with the same names will be overwritten. "
                "Other files are left alone.",
            )
        if confirm != QMessageBox.Yes:
            return
        try:
            result = content_backup.restore_backup(source, self.config.post_update_dir)
        except content_backup.BackupError as e:
            QMessageBox.warning(self, "Restore failed", str(e))
            return
        except OSError as e:
            QMessageBox.warning(self, "Restore failed", f"Could not extract backup:\n{e}")
            return
        self._refresh()
        Toast.show_message(
            self, f"Restored {result.file_count} files from backup", "success"
        )


class SecretsPage(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.rows = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)
        outer.addLayout(_page_header(
            "Secrets",
            "Enter each value directly, or tick 'From Bitwarden' and enter the name of the "
            "matching secret in Bitwarden Secrets Manager to pull it from there.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(16)

        top = QHBoxLayout()
        self.show_values = QCheckBox("Show values")
        self.show_values.toggled.connect(self._apply_echo)
        top.addWidget(self.show_values)
        top.addStretch(1)
        layout.addLayout(top)

        values_card = Card("Values")
        form = QFormLayout()
        form.setSpacing(12)
        # Fixed name-column width so the Required/Optional chips line up in a
        # column even though the secret names differ in length.
        _name_font = QFont("Segoe UI")
        _name_font.setPixelSize(13)
        _fm = QFontMetrics(_name_font)
        name_col_w = max(_fm.horizontalAdvance(lbl) for _, lbl, _, _ in SECRET_ROLES) + 10
        for key, label, required, sensitive in SECRET_ROLES:
            src = (config.secrets or {}).get(key, {})
            checkbox = QCheckBox("From Bitwarden")
            value_edit = QLineEdit(src.get("value", ""))
            value_edit.setPlaceholderText("required" if required else "optional")
            # Show the default secret name as an example placeholder rather than
            # real text - everyone names their secrets differently. Only a name
            # that genuinely differs from the default is shown as text; left
            # blank (or matching the default), it falls back to `key` on save.
            saved_bws = src.get("bws_key", "")
            bws_edit = QLineEdit("" if (not saved_bws or saved_bws == key) else saved_bws)
            bws_edit.setPlaceholderText(f"e.g. {key}")

            stack = QStackedWidget()
            stack.addWidget(value_edit)  # index 0: plaintext
            stack.addWidget(bws_edit)    # index 1: bitwarden
            from_bws = src.get("mode", "bws") == "bws"
            checkbox.setChecked(from_bws)
            stack.setCurrentIndex(1 if from_bws else 0)
            checkbox.toggled.connect(lambda checked, s=stack: s.setCurrentIndex(1 if checked else 0))

            field = QWidget()
            fb = QHBoxLayout(field)
            fb.setContentsMargins(0, 0, 0, 0)
            fb.setSpacing(12)
            stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            fb.addWidget(stack, 1)
            fb.addWidget(checkbox, 0)

            name_w = QWidget()
            nb = QHBoxLayout(name_w)
            nb.setContentsMargins(0, 0, 0, 0)
            nb.setSpacing(8)
            name_lbl = QLabel(label)
            name_lbl.setFixedWidth(name_col_w)
            chip = QLabel("Required" if required else "Optional")
            chip.setObjectName("FieldTag")
            chip.setProperty("req", "true" if required else "false")
            nb.addWidget(name_lbl)
            nb.addWidget(chip)
            nb.addStretch(1)
            form.addRow(name_w, field)

            self.rows[key] = {
                "checkbox": checkbox,
                "value_edit": value_edit,
                "bws_edit": bws_edit,
                "sensitive": sensitive,
            }
        values_card.add_layout(form)
        layout.addWidget(values_card)

        bws_card = Card("Bitwarden Secrets Manager")
        bws_card.add(QLabel(
            "'From Bitwarden' uses Bitwarden Secrets Manager (the bws CLI) - not the "
            "password vault. It needs a machine-account access token, which the app "
            "will prompt for on first use."
        ))
        bform = QFormLayout()
        self.bws_project_id = QLineEdit(config.bws_project_id)
        self.bws_project_id.setPlaceholderText("optional - limit lookup to one project")
        bform.addRow("Project ID:", self.bws_project_id)
        bws_card.add_layout(bform)
        bws_card.add(QLabel(
            "Plaintext values are stored in this app's config file on your PC."
        ))
        layout.addWidget(bws_card)

        layout.addStretch(1)
        scroll.setWidget(container)
        _configure_scroll(scroll)
        outer.addWidget(scroll, 1)

        self._apply_echo(False)

        save_row = QHBoxLayout()
        self.saved_label = QLabel("")
        self.saved_label.setObjectName("SubHeader")
        save_row.addWidget(self.saved_label, 1)
        self.save_btn = QPushButton("Save Secrets")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self.save)
        save_row.addWidget(self.save_btn)
        outer.addLayout(save_row)

    def _apply_echo(self, show):
        mode = QLineEdit.Normal if show else QLineEdit.Password
        for row in self.rows.values():
            if row["sensitive"]:
                row["value_edit"].setEchoMode(mode)

    def apply_to_config(self) -> bool:
        secrets = {}
        for key, row in self.rows.items():
            if row["checkbox"].isChecked():
                secrets[key] = {
                    "mode": "bws",
                    "value": "",
                    "bws_key": row["bws_edit"].text().strip() or key,
                }
            else:
                secrets[key] = {
                    "mode": "plaintext",
                    "value": row["value_edit"].text(),
                    "bws_key": row["bws_edit"].text().strip() or key,
                }
        self.config.secrets = secrets
        self.config.bws_project_id = self.bws_project_id.text().strip()
        return True

    def save(self):
        self.apply_to_config()
        self.config.save()
        self.saved_label.setText("Secrets saved.")
        Toast.show_message(self, "Secrets saved", "success")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kascade")
        self.resize(1000, 700)
        self.setMinimumSize(880, 580)
        self.config = Config.load()
        self.config.ensure_dirs()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 20, 14, 14)
        side.setSpacing(6)
        title = QLabel("Kascade")
        title.setObjectName("AppTitle")
        side.addWidget(title)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, name in enumerate(["Run", "Content", "Secrets", "Settings"]):
            btn = QPushButton(f"  {name}")
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            icon = nav_icon(name)
            if not icon.isNull():
                btn.setIcon(icon)
                btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _checked, i=index: self.stack.setCurrentIndex(i))
            self.nav_group.addButton(btn, index)
            side.addWidget(btn)
        side.addStretch(1)
        footer = QLabel(f"v{__version__}")
        footer.setObjectName("SidebarFooter")
        side.addWidget(footer)
        root.addWidget(sidebar)

        # Content
        self.stack = QStackedWidget()
        self.settings_page = SettingsPage(self.config)
        self.secrets_page = SecretsPage(self.config)
        self.content_page = ContentPage(self.config, self._current_config)
        self.run_page = RunPage(self.config, self._current_config)
        self.stack.addWidget(self.run_page)       # index 0
        self.stack.addWidget(self.content_page)   # index 1
        self.stack.addWidget(self.secrets_page)   # index 2
        self.stack.addWidget(self.settings_page)  # index 3
        root.addWidget(self.stack, 1)

        self.nav_group.button(0).setChecked(True)
        self.stack.setCurrentIndex(0)

    def _current_config(self):
        self.settings_page.apply_to_config()
        self.secrets_page.apply_to_config()
        return self.config


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    icon_path = resource_path(os.path.join("assets", "icon.ico"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
