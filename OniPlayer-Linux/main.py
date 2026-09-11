#!/usr/bin/env python3
"""
OniPlayer - Full-featured Video Player for Linux
Based on Windows version with all features, GUI, and auto-hiding controls ported.
"""

import os
import sys
import ctypes
from pathlib import Path

# Force XWayland for VLC embedding on Wayland
os.environ["QT_QPA_PLATFORM"] = "xcb"

# Set up base directory for all resources
if getattr(sys, 'frozen', False):
    base_dir = os.path.join('/usr', 'local', 'lib')
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

# Set up paths for all resources (Linux version)
vlc_engine_path = Path(base_dir) / "vlc_engine"
vlc_lib_path = vlc_engine_path / "lib"
vlc_plugin_path = vlc_engine_path / "plugins"

# Set up VLC environment
os.environ["VLC_PLUGIN_PATH"] = str(vlc_plugin_path)
os.environ["LD_LIBRARY_PATH"] = str(vlc_lib_path) + ":" + os.environ.get("LD_LIBRARY_PATH", "")



# Load libraries in dependency order (libvlccore first, then libvlc)
try:
    RTLD_GLOBAL = 0x100
    libvlccore = ctypes.CDLL(str(vlc_lib_path / "libvlccore.so.9"), mode=RTLD_GLOBAL)
    libvlc = ctypes.CDLL(str(vlc_lib_path / "libvlc.so.5"), mode=RTLD_GLOBAL)
except Exception as e:
    print(f"Warning: Could not load VLC libraries: {e}")

# Import VLC after setting up environment
import vlc

from PyQt6.QtCore import Qt, QTimer, QMimeData, QPoint, QDateTime, QEvent, QRect, QSize, QObject, QWIDGETSIZE_MAX
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QPalette, QColor, QMouseEvent, QKeyEvent, QAction, QActionGroup, QIcon, QFontMetrics, QPainter, QPen, QCursor
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                          QHBoxLayout, QPushButton, QSlider, QFileDialog,
                          QLabel, QStyle, QFrame, QStackedLayout, QMenu, 
                          QMessageBox, QSizePolicy, QScrollArea)

TIMELINE_BUTTON_STYLE = """
    QPushButton {
        background-color: rgba(255, 255, 255, 0.07);
        border: none;
        border-radius: 4px;
        padding: 5px;
    }
    QPushButton:hover {
        background-color: rgba(255, 255, 255, 0.13);
    }
    QPushButton:pressed {
        background-color: rgba(255, 255, 255, 0.20);
    }
"""

def timeline_icon(style, pixmap_type, size=20):
    pixmap = style.standardIcon(pixmap_type).pixmap(size, size)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(200, 200, 200))
    painter.end()
    return QIcon(pixmap)

class ClickableSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            value = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                event.pos().x(), self.width()
            )
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            value = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                event.pos().x(), self.width()
            )
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        event.ignore()

# ─── In-window menu (no native X11 popup → no VLC blink) ─────────────────────

class InWindowMenuAction(QObject):
    """Drop-in replacement for QAction that carries no native window."""
    triggered = pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text      = text
        self._checkable = False
        self._checked   = False
        self._data      = None
        self._enabled   = True

    def text(self):             return self._text
    def setText(self, t):       self._text = t
    def setCheckable(self, v):  self._checkable = v
    def isCheckable(self):      return self._checkable
    def setChecked(self, v):    self._checked = v
    def isChecked(self):        return self._checked
    def setData(self, d):       self._data = d
    def data(self):             return self._data
    def setEnabled(self, v):    self._enabled = v
    def isEnabled(self):        return self._enabled
    def setStyleSheet(self, s): pass   # compat no-op


class InWindowActionGroup(QObject):
    """Drop-in replacement for QActionGroup."""
    triggered = pyqtSignal(object)   # emits the InWindowMenuAction

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions   = []
        self._exclusive = True

    def setExclusive(self, v):  self._exclusive = v
    def actions(self):          return list(self._actions)

    def addAction(self, action):
        if action not in self._actions:
            self._actions.append(action)
            action.triggered.connect(lambda a=action: self._handle(a))

    def removeAction(self, action):
        if action in self._actions:
            self._actions.remove(action)

    def _handle(self, action):
        if self._exclusive:
            for a in self._actions:
                a.setChecked(a is action)
        self.triggered.emit(action)


class _MenuSep(QFrame):
    """Horizontal separator line for InWindowMenu."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(9)
        self.setStyleSheet(
            "QFrame { border: none; border-top: 1px solid rgba(70,70,70,200);"
            " margin: 3px 6px 0 6px; }"
        )


class _MenuRow(QWidget):
    """One clickable / hoverable row inside an InWindowMenu."""
    ROW_H   = 30
    clicked = pyqtSignal()
    hovered = pyqtSignal(object)   # emits self

    def __init__(self, text, checkable=False, checked=False,
                 has_arrow=False, enabled=True, parent=None):
        super().__init__(parent)
        self._text      = text
        self._checkable = checkable
        self._checked   = checked
        self._has_arrow = has_arrow
        self._enabled   = enabled
        self._hovered   = False
        self.setFixedHeight(self.ROW_H)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def set_checked(self, v):
        self._checked = v
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        self.hovered.emit(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        print(f"[DEBUG] _MenuRow mousePressEvent - button: {event.button()}, enabled: {self._enabled}, text: {self._text}")
        if event.button() == Qt.MouseButton.LeftButton and self._enabled:
            event.accept()
            print(f"[DEBUG] _MenuRow clicked: {self._text}")
            self.clicked.emit()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._hovered and self._enabled:
            p.fillRect(self.rect().adjusted(3, 1, -3, -1), QColor(255, 255, 255, 22))

        alpha = 230 if self._enabled else 80
        p.setPen(QColor(255, 255, 255, alpha))

        font = self.font()
        font.setPointSize(10)
        p.setFont(font)

        left  = 26 if self._checkable else 12
        right = self.width() - (20 if self._has_arrow else 8)
        text_r = QRect(left, 0, right - left, self.height())

        if self._checkable and self._checked:
            p.save()
            p.setPen(QColor(51, 153, 255))
            p.drawText(QRect(4, 0, 20, self.height()), Qt.AlignmentFlag.AlignVCenter, "✓")
            p.restore()

        p.drawText(text_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)

        if self._has_arrow:
            p.drawText(QRect(self.width() - 20, 0, 16, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "▸")


class InWindowMenu(QFrame):
    """
    Context menu rendered as a child QFrame of VideoFrame.

    Stays inside the same X11 window as the video surface so no native popup
    window is created — eliminating the video-blink seen with QMenu on
    XWayland + embedded VLC.
    """
    aboutToHide = pyqtSignal()
    triggered   = pyqtSignal(object)   # emits InWindowMenuAction

    _MIN_W = 190

    def __init__(self, video_frame):
        super().__init__(video_frame)
        self._vf          = video_frame   # the VideoFrame parent
        self._items       = []            # ('action', a) | ('sep',) | ('sub', text, sub)
        self._active_sub  = None          # currently visible sub-menu
        self._parent_menu = None          # owning InWindowMenu if we are a submenu
        self._full_h       = 0
        self._calc_w       = self._MIN_W

        self.setWindowFlags(Qt.WindowType.SubWindow)
        self.setObjectName("InWindowMenu")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Don't steal focus from video frame
        self.setStyleSheet("""
            QFrame#InWindowMenu {
                background-color: #1a1a1a;
                border: 1px solid rgba(75, 75, 75, 210);
                border-radius: 4px;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #1a1a1a;
                width: 6px;
                margin: 2px 1px 2px 1px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #444444;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #666666;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        self._outer_vbox = QVBoxLayout(self)
        self._outer_vbox.setContentsMargins(0, 0, 0, 0)
        self._outer_vbox.setSpacing(0)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setContentsMargins(4, 4, 4, 4)
        self._vbox.setSpacing(0)

        self._scroll_area.setWidget(self._container)
        self._outer_vbox.addWidget(self._scroll_area)
        self.hide()

    # ── QMenu-compatible public API ──────────────────────────────────────────

    def setStyleSheet(self, s):       pass          # built-in style takes priority

    def addAction(self, action_or_text):
        if isinstance(action_or_text, str):
            a = InWindowMenuAction(action_or_text)
        else:
            a = action_or_text
        self._items.append(('action', a))
        return a

    def addSeparator(self):
        self._items.append(('sep',))

    def addMenu(self, text):
        sub = InWindowMenu(self._vf)
        sub._parent_menu = self
        self._items.append(('sub', text, sub))
        return sub

    def clear(self):
        self._items.clear()

    def popup(self, global_pos):
        """Show at global_pos (QPoint)."""
        self._show_at(global_pos.x(), global_pos.y())

    # ── Internal ─────────────────────────────────────────────────────────────

    def _show_at(self, gx, gy):
        self._rebuild()
        vfw, vfh = self._vf.width(), self._vf.height()
        max_h = max(100, vfh - 16)
        full_h = self._full_h
        needs_scroll = full_h > max_h
        h = min(full_h, max_h)
        w = self._calc_w + (12 if needs_scroll else 0)

        self._container.setFixedWidth(self._calc_w)

        lpos = self._vf.mapFromGlobal(QPoint(gx, gy))
        min_x, max_x = 4, max(4, vfw - w - 4)
        min_y, max_y = 4, max(4, vfh - h - 4)
        x = max(min_x, min(lpos.x(), max_x))
        y = max(min_y, min(lpos.y(), max_y))

        self.setGeometry(x, y, w, h)
        self.show()

    def _rebuild(self):
        """Recreate row widgets from self._items (stateless → always fresh)."""
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        fm = QFontMetrics(self.font())
        max_item_w = self._MIN_W
        total_h = 8  # top (4px) + bottom (4px) margins

        for entry in self._items:
            if entry[0] == 'sep':
                self._vbox.addWidget(_MenuSep(self._container))
                total_h += 9

            elif entry[0] == 'action':
                action = entry[1]
                row = _MenuRow(
                    action._text, action._checkable, action._checked,
                    enabled=action._enabled, parent=self._container,
                )
                row.clicked.connect(lambda a=action: self._on_action_click(a))
                row.hovered.connect(lambda _r: self._close_active_sub())
                self._vbox.addWidget(row)
                total_h += _MenuRow.ROW_H

                # Compute required width: padding left/right + text width
                left_pad = 26 if action._checkable else 12
                right_pad = 16
                req_w = left_pad + fm.horizontalAdvance(action._text) + right_pad
                if req_w > max_item_w:
                    max_item_w = req_w

            elif entry[0] == 'sub':
                _, text, sub = entry
                row = _MenuRow(text, has_arrow=True, parent=self._container)
                row.hovered.connect(lambda _r, r=row, s=sub: self._open_sub(r, s))
                self._vbox.addWidget(row)
                total_h += _MenuRow.ROW_H

                req_w = 12 + fm.horizontalAdvance(text) + 28
                if req_w > max_item_w:
                    max_item_w = req_w

        self._calc_w = max_item_w
        self._full_h = total_h

    def _on_action_click(self, action):
        print(f"[DEBUG] _on_action_click called for: {action._text}, enabled: {action._enabled}")
        if not action._enabled:
            return
        self._close_root()          # hide everything first
        action.triggered.emit()     # then fire callbacks (safe order)
        self.triggered.emit(action)

    def _open_sub(self, row, sub):
        print(f"[DEBUG] Opening submenu")
        if self._active_sub is sub and sub.isVisible():
            return
        self._close_active_sub()
        sub._rebuild()
        vfw, vfh = self._vf.width(), self._vf.height()
        max_h = max(100, vfh - 16)
        sub_full_h = sub._full_h
        sub_needs_scroll = sub_full_h > max_h
        sub_h = min(sub_full_h, max_h)
        sub_w = sub._calc_w + (12 if sub_needs_scroll else 0)

        sub._container.setFixedWidth(sub._calc_w)
        row_vf = row.mapTo(self._vf, QPoint(0, 0))
        self._active_sub = sub

        sub_x = self.x() + self.width() - 2
        if sub_x + sub_w > vfw - 4:
            sub_x = max(4, self.x() - sub_w + 2)
        sub_y = max(4, min(row_vf.y(), vfh - sub_h - 4))

        sub.setGeometry(sub_x, sub_y, sub_w, sub_h)
        sub.show()

    def _close_active_sub(self):
        if self._active_sub:
            self._active_sub._close_all()
            self._active_sub = None

    def _close_all(self):
        self._close_active_sub()
        self.hide()

    def _close_root(self):
        """Walk up to the root menu, close everything, emit aboutToHide."""
        root = self
        while root._parent_menu:
            root = root._parent_menu
        root._close_all()
        root.aboutToHide.emit()

    def sizeHint(self):
        h = 8   # top + bottom margin (4+4)
        for entry in self._items:
            h += 9 if entry[0] == 'sep' else (_MenuRow.ROW_H + 1)
        w = getattr(self, '_calc_w', self._MIN_W)
        return QSize(w, h)


# ─────────────────────────────────────────────────────────────────────────────
class VideoFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen, True)  # Keep for VLC compatibility
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoChildEventsForParent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_UpdatesDisabled, True)
        
        # Mouse state tracking
        self.left_button_pressed = False
        self.right_button_pressed = False
        self.show_context = True  # Flag to control context menu display
        self.combination_active = False  # Track if we're in a button combination
        self.combination_start_time = QDateTime.currentMSecsSinceEpoch()  # Track when combination started
        self.right_button_press_time = 0  # Track when right button was pressed
        
        # Button combination detection
        self.button_combination_timer = QTimer(self)
        self.button_combination_timer.setSingleShot(True)
        self.button_combination_timer.setInterval(50)  # 50ms timeout for button combinations
        self.button_combination_timer.timeout.connect(self.handle_button_combination)
        self.pending_button_combination = None
        
        # Hide cursor by default
        self.setCursor(Qt.CursorShape.BlankCursor)
        
        # Create layout for proper layering
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Create in-window context menu (child widget → same X11 window → no blink)
        self.context_menu = InWindowMenu(self)
        self.audio_tracks_menu = None
        self.audio_track_group = InWindowActionGroup(self)
        self.audio_track_group.setExclusive(True)
        self.audio_track_group.triggered.connect(self.on_audio_track_changed)

        self.subtitle_tracks_menu = None
        self.subtitle_track_group = InWindowActionGroup(self)
        self.subtitle_track_group.setExclusive(True)
        self.subtitle_track_group.triggered.connect(self.on_subtitle_track_changed)
        
        self.setup_context_menu()
        self.context_menu.aboutToHide.connect(self._on_context_menu_hide)
        
        # Create logo overlay widget for when no video is playing
        self.logo_overlay = QLabel(self)
        self.logo_overlay.setText("OniPlayer")
        self.logo_font = self.font()
        self.logo_font.setPointSize(28)
        self.logo_font.setBold(True)
        self.logo_overlay.setFont(self.logo_font)
        self.logo_overlay.setStyleSheet("color: rgba(200, 200, 200, 255);")
        self.logo_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_overlay.hide()
        
        # Position logo overlay to center it
        self.logo_overlay.setGeometry(0, 0, 100, 50)
        
        # Show logo initially (no video is playing)
        self.logo_overlay.show()

    def handle_button_combination(self):
        """Handle button combinations after the timeout"""
        # Only trigger combinations if media is currently playing
        if not self.parent.has_media:
            self.pending_button_combination = None
            return
            
        if self.pending_button_combination == "right_hold_left":
            self.parent.play_previous()
            self.combination_active = True
            self.combination_start_time = QDateTime.currentMSecsSinceEpoch()
        elif self.pending_button_combination == "left_hold_right":
            self.parent.play_next()
            self.combination_active = True
            self.combination_start_time = QDateTime.currentMSecsSinceEpoch()
        self.pending_button_combination = None

    def mousePressEvent(self, event):
        # Close menu on left-click outside the menu area
        if self.context_menu.isVisible() and event.button() == Qt.MouseButton.LeftButton:
            gpos = event.globalPosition().toPoint()
            lpos = self.mapFromGlobal(gpos)
            menu_r = self.context_menu.geometry()
            sub = self.context_menu._active_sub
            sub_r = sub.geometry() if (sub and sub.isVisible()) else QRect()
            
            # Only close if click is outside both main menu and submenu
            if not menu_r.contains(lpos) and not sub_r.contains(lpos):
                self.context_menu._close_root()
                event.accept()
                return

        if event.button() == Qt.MouseButton.LeftButton:
            self.left_button_pressed = True
            if self.right_button_pressed:
                # Right button is already pressed, this is a right-hold-left-click
                self.pending_button_combination = "right_hold_left"
                self.button_combination_timer.start()
                self.show_context = False
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_button_pressed = True
            self.right_button_press_time = QDateTime.currentMSecsSinceEpoch()  # Track press time
            if self.left_button_pressed:
                # Left button is already pressed, this is a left-hold-right-click
                self.pending_button_combination = "left_hold_right"
                self.button_combination_timer.start()
                self.show_context = False
            else:
                # Initially block context menu to give time for combinations
                self.show_context = False
                # Start a timer to track if this is a hold
                self.right_click_timer = QTimer(self)
                self.right_click_timer.setSingleShot(True)
                self.right_click_timer.setInterval(200)  # 200ms threshold for hold
                self.right_click_timer.timeout.connect(self.on_right_click_hold)
                self.right_click_timer.start()
        elif event.button() == Qt.MouseButton.MiddleButton:
            # Start a timer for middle button hold
            self.middle_click_timer = QTimer(self)
            self.middle_click_timer.setSingleShot(True)
            self.middle_click_timer.setInterval(1000)  # 1 second for subtitle toggle
            self.middle_click_timer.timeout.connect(self.on_middle_click_hold)
            self.middle_click_timer.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.left_button_pressed = False
            if self.pending_button_combination:
                self.button_combination_timer.stop()
                self.pending_button_combination = None
            # Only reset combination lock when both buttons are released
            if not self.right_button_pressed:
                # Add a small delay before resetting combination lock
                QTimer.singleShot(100, self.reset_combination_lock)
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_button_pressed = False
            if hasattr(self, 'right_click_timer'):
                self.right_click_timer.stop()
            if self.pending_button_combination:
                self.button_combination_timer.stop()
                self.pending_button_combination = None
            # Only reset combination lock when both buttons are released
            if not self.left_button_pressed:
                # Check if the right button was held (timer expired) or quickly clicked
                press_duration = QDateTime.currentMSecsSinceEpoch() - self.right_button_press_time
                if press_duration <= 200 and not self.combination_active:
                    # This was a quick right-click, show context menu
                    self.show_context = True
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                    self.update_audio_tracks()
                    self.update_subtitle_tracks()
                    self.context_menu.popup(self.cursor().pos())
                # If it was held (>200ms), don't show context menu (already blocked by on_right_click_hold)
                # Add a small delay before resetting combination lock
                QTimer.singleShot(100, self.reset_combination_lock)
        elif event.button() == Qt.MouseButton.MiddleButton:
            if hasattr(self, 'middle_click_timer'):
                # If timer is still running, it means this was a quick click
                if self.middle_click_timer.isActive():
                    self.middle_click_timer.stop()
                    self.parent.toggle_fullscreen()  # Toggle fullscreen only on quick click
        super().mouseReleaseEvent(event)

    def reset_combination_lock(self):
        """Reset the combination lock with a delay"""
        self.combination_active = False
        self.show_context = True

    def contextMenuEvent(self, event):
        try:
            # Prevent multiple context menus from opening
            if self.context_menu.isVisible():
                self.context_menu._close_root()
                event.accept()
                return

            current_time = QDateTime.currentMSecsSinceEpoch()
            time_since_right_press = current_time - self.right_button_press_time
            time_since_combination = current_time - self.combination_start_time

            # Windows approach: use timing check to prevent context menu during/after combinations
            # Also block if right button was just pressed (within 200ms) to allow time for combinations
            if (
                self.show_context
                and self.parent.has_media
                and not self.pending_button_combination
                and not self.combination_active
                and time_since_combination > 200
                and time_since_right_press > 200
            ):
                print(f"[DEBUG] Opening context menu at {event.globalPos()}")
                self.setCursor(Qt.CursorShape.ArrowCursor)

                self.update_audio_tracks()
                self.update_subtitle_tracks()

                # InWindowMenu is a child widget — no native popup window is
                # created, so VLC's X11 surface never blinks.
                self.context_menu.popup(event.globalPos())
                event.accept()

            else:
                print(f"[DEBUG] Context menu blocked: show_context={self.show_context}, has_media={self.parent.has_media}, pending={self.pending_button_combination}, combination_active={self.combination_active}, time_since_combination={time_since_combination}, time_since_right_press={time_since_right_press}")
                event.ignore()

        except Exception as e:
            print(f"Context menu error: {e}")
            event.ignore()

    def _on_context_menu_hide(self):
        """Handle context menu closing"""
        # Restore focus to video frame so keyboard shortcuts work
        self.setFocus()
        
        # Get current mouse position relative to window
        cursor_pos = self.mapFromGlobal(self.cursor().pos())
        local_y = cursor_pos.y()
        window_height = self.parent.height()
        
        # Only hide cursor if not in control areas
        if not (local_y <= 30 or window_height - local_y <= 40):
            self.setCursor(Qt.CursorShape.BlankCursor)

    def setup_context_menu(self):
        self.context_menu.setStyleSheet("")   # no-op; InWindowMenu uses its own style
        
        play_action = self.context_menu.addAction("Play/Pause")
        play_action.triggered.connect(lambda: print("[DEBUG] Play/Pause triggered") or self.parent.toggle_play())
        
        fullscreen_action = self.context_menu.addAction("Toggle Fullscreen")
        fullscreen_action.triggered.connect(lambda: print("[DEBUG] Toggle Fullscreen triggered") or self.parent.toggle_fullscreen())
        
        self.context_menu.addSeparator()
        
        self.audio_tracks_menu = self.context_menu.addMenu("Audio Track")
        
        self.subtitle_tracks_menu = self.context_menu.addMenu("Subtitles")
        
        subtitle_sync_menu = self.context_menu.addMenu("Subtitle Sync")
        
        delay_100ms = subtitle_sync_menu.addAction("Delay +100ms")
        delay_100ms.triggered.connect(lambda: print("[DEBUG] Delay +100ms triggered") or self.parent.adjust_subtitle_sync(100))
        delay_500ms = subtitle_sync_menu.addAction("Delay +500ms")
        delay_500ms.triggered.connect(lambda: print("[DEBUG] Delay +500ms triggered") or self.parent.adjust_subtitle_sync(500))
        delay_1000ms = subtitle_sync_menu.addAction("Delay +1s")
        delay_1000ms.triggered.connect(lambda: print("[DEBUG] Delay +1s triggered") or self.parent.adjust_subtitle_sync(1000))
        
        subtitle_sync_menu.addSeparator()
        
        advance_100ms = subtitle_sync_menu.addAction("Advance -100ms")
        advance_100ms.triggered.connect(lambda: print("[DEBUG] Advance -100ms triggered") or self.parent.adjust_subtitle_sync(-100))
        advance_500ms = subtitle_sync_menu.addAction("Advance -500ms")
        advance_500ms.triggered.connect(lambda: print("[DEBUG] Advance -500ms triggered") or self.parent.adjust_subtitle_sync(-500))
        advance_1000ms = subtitle_sync_menu.addAction("Advance -1s")
        advance_1000ms.triggered.connect(lambda: print("[DEBUG] Advance -1s triggered") or self.parent.adjust_subtitle_sync(-1000))
        
        subtitle_sync_menu.addSeparator()
        
        reset_sync = subtitle_sync_menu.addAction("Reset Sync")
        reset_sync.triggered.connect(lambda: print("[DEBUG] Reset Sync triggered") or self.parent.reset_subtitle_sync())
        
        self.context_menu.addSeparator()
        
        open_action = self.context_menu.addAction("Open File...")
        open_action.triggered.connect(lambda: print("[DEBUG] Open File triggered") or self.parent.open_file())
        
        self.context_menu.addSeparator()
        
        prev_action = self.context_menu.addAction("Previous Video")
        prev_action.triggered.connect(lambda: print("[DEBUG] Previous Video triggered") or self.parent.play_previous())
        next_action = self.context_menu.addAction("Next Video")
        next_action.triggered.connect(lambda: print("[DEBUG] Next Video triggered") or self.parent.play_next())
        
        self.context_menu.addSeparator()
        
        seek_menu = self.context_menu.addMenu("Seek")
        back_10 = seek_menu.addAction("Back 10 seconds")
        back_10.triggered.connect(lambda: print("[DEBUG] Back 10s triggered") or self.parent.seek_relative(-10))
        forward_10 = seek_menu.addAction("Forward 10 seconds")
        forward_10.triggered.connect(lambda: print("[DEBUG] Forward 10s triggered") or self.parent.seek_relative(10))
        back_30 = seek_menu.addAction("Back 30 seconds")
        back_30.triggered.connect(lambda: print("[DEBUG] Back 30s triggered") or self.parent.seek_relative(-30))
        forward_30 = seek_menu.addAction("Forward 30 seconds")
        forward_30.triggered.connect(lambda: print("[DEBUG] Forward 30s triggered") or self.parent.seek_relative(30))

    def update_audio_tracks(self):
        if not self.audio_tracks_menu:
            return
        self.audio_tracks_menu.clear()
        
        if not self.parent.has_media:
            no_tracks = self.audio_tracks_menu.addAction("No Audio Tracks")
            no_tracks.setEnabled(False)
            return

        current = self.parent.media_player.audio_get_track()
        count = self.parent.media_player.audio_get_track_count()
        
        if count <= 0:
            no_tracks = self.audio_tracks_menu.addAction("No Audio Tracks")
            no_tracks.setEnabled(False)
            return

        descriptions = self.parent.media_player.audio_get_track_description()
        tracks = []
        
        for i in range(count):
            name = f"Track {i + 1}"
            if descriptions and i < len(descriptions):
                track_id, desc = descriptions[i]
                if track_id == -1:
                    continue
                if desc:
                    try:
                        desc = desc.decode('utf-8') if isinstance(desc, bytes) else str(desc)
                        if desc and desc != str(i):
                            parts = desc.split('-')
                            cleaned_desc = parts[-1].strip() if len(parts) > 1 else desc
                            if not cleaned_desc.lower().startswith('track'):
                                name = f"Track {i + 1} ({cleaned_desc})"
                    except Exception:
                        pass
            tracks.append({"id": i, "name": name})

        # Clear stale group entries (audio menu has no explicit group-clear elsewhere)
        for old in list(self.audio_track_group.actions()):
            self.audio_track_group.removeAction(old)

        for track in tracks:
            action = self.audio_tracks_menu.addAction(track["name"])
            action.setCheckable(True)
            action.setData(track["id"])
            if track["id"] == current:
                action.setChecked(True)
            self.audio_track_group.addAction(action)

    def update_subtitle_tracks(self):
        if not self.subtitle_tracks_menu:
            return

        self.subtitle_tracks_menu.clear()

        # Remove old QAction objects from the exclusive group.
        for action in list(self.subtitle_track_group.actions()):
            self.subtitle_track_group.removeAction(action)
            action.deleteLater()

        if not self.parent.has_media:
            action = self.subtitle_tracks_menu.addAction("No Subtitles")
            action.setEnabled(False)
            return

        try:
            current = self.parent.media_player.video_get_spu()
            descriptions = self.parent.media_player.video_get_spu_description()



            # Disabled option
            disable_action = self.subtitle_tracks_menu.addAction("Disabled")
            disable_action.setCheckable(True)
            disable_action.setData(-1)
            disable_action.setChecked(current == -1)
            self.subtitle_track_group.addAction(disable_action)

            valid_tracks = []

            if descriptions:
                for track_id, name in descriptions:
                    if track_id == -1:
                        continue

                    try:
                        if isinstance(name, bytes):
                            name = name.decode("utf-8", errors="replace")
                        else:
                            name = str(name)
                    except Exception:
                        name = ""

                    valid_tracks.append((track_id, name))

            if not valid_tracks:
                no_tracks = self.subtitle_tracks_menu.addAction(
                    "No Subtitle Tracks"
                )
                no_tracks.setEnabled(False)
                return

            for track_id, name in valid_tracks:
                if name and name != str(track_id):
                    text = f"Track {track_id} ({name})"
                else:
                    text = f"Track {track_id}"

                action = self.subtitle_tracks_menu.addAction(text)
                action.setCheckable(True)
                action.setData(track_id)
                action.setChecked(track_id == current)

                self.subtitle_track_group.addAction(action)

        except Exception as e:
            print(f"Error updating subtitle tracks: {e}")

    def on_audio_track_changed(self, action):
        track_id = action.data()
        success = self.parent.media_player.audio_set_track(track_id)
        if success:
            self.update_audio_tracks()

    def on_subtitle_track_changed(self, action):
        track_id = action.data()
        try:
            self.parent.change_subtitle_track(track_id)
            self.update_subtitle_tracks()
        except Exception as e:
            print(f"Error changing subtitle track: {e}")



    def resizeEvent(self, event):
        super().resizeEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.parent:
            event.accept()
            self.parent.toggle_play()
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        # Check if mouse is over context menu - if so, let the menu handle scrolling
        if self.context_menu.isVisible():
            gpos = event.globalPosition().toPoint()
            lpos = self.mapFromGlobal(gpos)
            menu_r = self.context_menu.geometry()
            sub = self.context_menu._active_sub
            sub_r = sub.geometry() if (sub and sub.isVisible()) else QRect()
            
            # If wheel event is over menu or submenu, ignore it (let menu scroll)
            if menu_r.contains(lpos) or sub_r.contains(lpos):
                event.ignore()
                return
        
        if self.left_button_pressed:
            # Fast forward/rewind when left mouse button is pressed
            delta = event.angleDelta().y()
            if delta > 0:
                self.parent.seek_relative(5)  # Fast forward 5 seconds
            else:
                self.parent.seek_relative(-5)  # Rewind 5 seconds
            event.accept()
        elif self.right_button_pressed:
            # Prevent context menu from showing during right button hold + scroll
            self.show_context = False
            # Change audio track when right mouse button is pressed
            delta = event.angleDelta().y()
            if delta > 0:
                # Scroll up - go to previous audio track
                self.parent.cycle_audio_track_reverse()
            else:
                # Scroll down - go to next audio track
                self.parent.cycle_audio_track()
            event.accept()
        else:
            # Normal volume control when no buttons are pressed
            delta = event.angleDelta().y()
            if delta > 0:
                # Increase volume directly
                current_volume = self.parent.volume_slider.value()
                new_volume = max(0, min(100, current_volume + 5))
                if new_volume != current_volume:
                    self.parent.volume_slider.setValue(new_volume)
                    self.parent.media_player.audio_set_volume(new_volume)
                    self.parent.show_volume_overlay()
            else:
                # Decrease volume directly
                current_volume = self.parent.volume_slider.value()
                new_volume = max(0, min(100, current_volume - 5))
                if new_volume != current_volume:
                    self.parent.volume_slider.setValue(new_volume)
                    self.parent.media_player.audio_set_volume(new_volume)
                    self.parent.show_volume_overlay()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        super().mouseMoveEvent(event)
        if hasattr(self.parent, 'handle_mouse_hover'):
            self.parent.handle_mouse_hover()

    def on_right_click_hold(self):
        """Called when right button is held for more than 200ms"""
        self.show_context = False  # Disable context menu for hold
        self.combination_active = True  # Prevent context menu from showing on release
        self.combination_start_time = QDateTime.currentMSecsSinceEpoch()  # Set start time for timing check

    def on_middle_click_hold(self):
        """Called when middle button is held for 1 second"""
        try:
            self.parent.toggle_subtitles()  # Use new toggle_subtitles method
        except Exception as e:
            print(f"Error in middle click hold: {e}")

    def keyPressEvent(self, event: QKeyEvent):
        # Close in-window menu on Escape
        if self.context_menu.isVisible() and event.key() == Qt.Key.Key_Escape:
            self.context_menu._close_root()
            event.accept()
            return

        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.parent.toggle_play()
            event.accept()
        elif event.key() == Qt.Key.Key_F and not event.isAutoRepeat():
            self.parent.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape and self.parent.isFullScreen():
            self.parent.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.parent.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key.Key_Up:
            current_volume = self.parent.volume_slider.value()
            new_volume = max(0, min(100, current_volume + 5))
            if new_volume != current_volume:
                self.parent.volume_slider.setValue(new_volume)
                self.parent.media_player.audio_set_volume(new_volume)
                self.parent.show_volume_overlay()
            event.accept()
        elif event.key() == Qt.Key.Key_Down:
            current_volume = self.parent.volume_slider.value()
            new_volume = max(0, min(100, current_volume - 5))
            if new_volume != current_volume:
                self.parent.volume_slider.setValue(new_volume)
                self.parent.media_player.audio_set_volume(new_volume)
                self.parent.show_volume_overlay()
            event.accept()
        elif event.key() == Qt.Key.Key_Left:
            self.parent.seek_relative(-10)
            event.accept()
        elif event.key() == Qt.Key.Key_Right:
            self.parent.seek_relative(10)
            event.accept()
        elif event.key() == Qt.Key.Key_M and not event.isAutoRepeat():
            self.parent.toggle_mute()
            event.accept()
        elif event.key() == Qt.Key.Key_PageUp:
            self.parent.play_next()
            event.accept()
        elif event.key() == Qt.Key.Key_PageDown:
            self.parent.play_previous()
            event.accept()
        elif event.key() == Qt.Key.Key_A and not event.isAutoRepeat():
            self.parent.cycle_audio_track()
            event.accept()
        elif event.key() == Qt.Key.Key_S and not event.isAutoRepeat():
            self.parent.toggle_subtitles()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        # No custom painting needed - using overlay widget instead
        super().paintEvent(event)
    
    def resizeEvent(self, event):
        """Handle resize events to keep logo centered"""
        super().resizeEvent(event)
        if hasattr(self, 'logo_overlay'):
            # Make overlay cover entire video frame
            self.logo_overlay.setGeometry(0, 0, self.width(), self.height())

class StrokedLabel(QLabel):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        pen = QPen(Qt.GlobalColor.black, 4)
        painter.setPen(pen)
        
        x = 5
        y = self.height() // 2 + 10
        
        offsets = [(-3,-3), (0,-3), (3,-3),
                  (-3,0),          (3,0),
                  (-3,3),  (0,3),  (3,3),
                  (-2,-2), (2,-2),
                  (-2,2),  (2,2)]
                  
        for dx, dy in offsets:
            painter.drawText(x + dx, y + dy, self.text())
            
        painter.setPen(QColor("#00FFFF"))
        painter.drawText(x, y, self.text())

class OniPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OniPlayer")
        
        # Remove default window frame
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet("""
            QMainWindow {
                background-color: black;
            }
        """)
        
        # Create top control container first
        self.top_control_container = QWidget()
        self.top_control_container.setFixedHeight(30)
        self.top_control_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.top_control_container.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 0px;
                padding: 0px;
                min-width: 30px;
                max-width: 30px;
                min-height: 30px;
                max-height: 30px;
                color: white;
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(128, 128, 128, 0.5);
            }
            QPushButton:pressed {
                background-color: rgba(96, 96, 96, 0.7);
            }
            #closeButton:hover {
                background-color: #E81123;
            }
        """)

        # Create timeline container
        self.timeline_container = QWidget()
        self.timeline_container.setObjectName("timelineContainer")
        self.timeline_container.setFixedHeight(40)
        self.timeline_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.timeline_container.setStyleSheet("""
            #timelineContainer {
                background-color: #1A1A1A;
            }
        """)
        
        # Create central widget and main layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 30, 0, 40)
        self.main_layout.setSpacing(0)
        
        # Create overlay widgets as top-level Tool windows (same approach as Windows version).
        # Using FramelessWindowHint | Tool so they float over the player without stealing focus.
        # WindowStaysOnTopHint ensures they appear above the VLC-embedded native window on Linux.
        self.audio_track_overlay = StrokedLabel()
        self.audio_track_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.audio_track_overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.audio_track_overlay.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.audio_track_overlay.setStyleSheet("""
            StrokedLabel {
                color: #00FFFF;
                font-size: 24px;
                font-weight: bold;
                padding: 10px;
                background: rgba(0, 0, 0, 0.5);
            }
        """)
        self.audio_track_overlay.hide()

        self.audio_track_overlay_timer = QTimer(self)
        self.audio_track_overlay_timer.setSingleShot(True)
        self.audio_track_overlay_timer.timeout.connect(self.hide_audio_track_overlay)
        
        # Create volume indicator overlay
        self.volume_overlay = StrokedLabel()
        self.volume_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.volume_overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.volume_overlay.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.volume_overlay.setStyleSheet("""
            StrokedLabel {
                color: #00FFFF;
                font-size: 24px;
                font-weight: bold;
                padding: 10px;
                background: rgba(0, 0, 0, 0.5);
            }
        """)
        self.volume_overlay.setText("Volume: 100%")
        self.volume_overlay.hide()
        
        # Create title overlay
        self.title_overlay = StrokedLabel()
        self.title_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.title_overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.title_overlay.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.title_overlay.setStyleSheet("""
            StrokedLabel {
                color: #00FFFF;
                font-size: 24px;
                font-weight: bold;
                padding: 15px 30px;
                background: transparent;
                min-width: 400px;
                max-width: 800px;
            }
        """)
        self.title_overlay.setWordWrap(True)
        self.title_overlay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_overlay.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.title_overlay.hide()

        # Create video container widget
        self.video_container = QWidget()
        self.video_layout = QVBoxLayout(self.video_container)
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_layout.setSpacing(0)
        
        # Create video frame
        self.video_frame = VideoFrame(self)
        self.video_frame.setStyleSheet("background-color: black;")
        self.video_layout.addWidget(self.video_frame)
        
        self.video_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Set up floating controls
        self.top_control_container.setParent(self)
        self.timeline_container.setParent(self)
        
        self.main_layout.addWidget(self.video_container)
        
        self.resize(1024, 768)
        self.show()
        self.update_control_positions()
        
        # Force cursor update to ensure it's set to blank cursor
        # This fixes the issue where the cursor stays in its previous state (e.g., text icon)
        # from other applications when the player opens
        QTimer.singleShot(50, self.force_cursor_update)
        QTimer.singleShot(200, self.force_cursor_update)
        QTimer.singleShot(500, self.force_cursor_update)
        
        # Timeline container layout
        timeline_layout = QHBoxLayout(self.timeline_container)
        timeline_layout.setContentsMargins(10, 0, 5, 0)
        timeline_layout.setSpacing(5)
        
        # Play button
        self.play_button = QPushButton()
        self.play_button.setFixedSize(32, 32)
        self.play_button.setStyleSheet(TIMELINE_BUTTON_STYLE)
        self.play_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaPlay))
        self.play_button.clicked.connect(self.toggle_play)
        timeline_layout.addWidget(self.play_button)

        # Previous button
        self.prev_button = QPushButton()
        self.prev_button.setFixedSize(32, 32)
        self.prev_button.setStyleSheet(TIMELINE_BUTTON_STYLE)
        self.prev_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.prev_button.clicked.connect(self.play_previous)
        timeline_layout.addWidget(self.prev_button)

        # Next button
        self.next_button = QPushButton()
        self.next_button.setFixedSize(32, 32)
        self.next_button.setStyleSheet(TIMELINE_BUTTON_STYLE)
        self.next_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaSkipForward))
        self.next_button.clicked.connect(self.play_next)
        timeline_layout.addWidget(self.next_button)
        
        # Timeline slider
        self.timeline = ClickableSlider(Qt.Orientation.Horizontal)
        self.timeline.setStyleSheet("""
            QSlider::groove:horizontal {
                border: none;
                height: 3px;
                background: rgba(255, 255, 255, 0.2);
                margin: 0px;
            }

            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: none;
                width: 8px;
                height: 8px;
                margin: -3px 0;
                border-radius: 4px;
            }

            QSlider::sub-page:horizontal {
                background: #3399FF;
                border: none;
                height: 3px;
                margin: 0px;
            }

            QSlider::handle:horizontal:hover {
                background: #FFFFFF;
                border: none;
                width: 10px;
                height: 10px;
                margin: -4px 0;
                border-radius: 5px;
            }
            
            QSlider::groove:horizontal:hover {
                height: 4px;
            }
            
            QSlider::sub-page:horizontal:hover {
                height: 4px;
            }
        """)
        self.timeline.setMaximum(1000)
        self.timeline.sliderMoved.connect(self.set_position)
        self.timeline.sliderPressed.connect(self.timeline_pressed)
        self.timeline.sliderReleased.connect(self.timeline_released)
        
        # Volume controls
        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(2)
        
        self.volume_button = QPushButton()
        self.volume_button.setFixedSize(28, 28)
        self.volume_button.setStyleSheet(TIMELINE_BUTTON_STYLE)
        self.volume_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolume, size=18))
        self.volume_button.clicked.connect(self.toggle_mute)
        volume_layout.addWidget(self.volume_button)
        
        self.volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: none;
                height: 4px;
                background: rgba(255, 255, 255, 0.2);
                margin: 0px;
            }

            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: none;
                width: 10px;
                height: 10px;
                margin: -3px 0;
                border-radius: 5px;
            }

            QSlider::sub-page:horizontal {
                background: #3399FF;
                border: none;
                height: 4px;
                margin: 0px;
            }

            QSlider::handle:horizontal:hover {
                background: #FFFFFF;
                border: none;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            
            QSlider::groove:horizontal:hover {
                height: 5px;
            }
            
            QSlider::sub-page:horizontal:hover {
                height: 5px;
            }
        """)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(60)
        self.volume_slider.valueChanged.connect(self.on_volume_change)
        self.volume_slider.sliderMoved.connect(self.on_volume_change)
        volume_layout.addWidget(self.volume_slider)
        
        self.time_label = QLabel("0:00")
        self.time_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                background: transparent;
                font-size: 11px;
                min-width: 35px;
                padding: 0;
            }
        """)
        
        self.duration_label = QLabel("/ 0:00")
        self.duration_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                background: transparent;
                font-size: 11px;
                min-width: 35px;
                padding: 0;
            }
        """)
        
        time_layout = QHBoxLayout()
        time_layout.setSpacing(2)
        time_layout.addWidget(self.time_label)
        time_layout.addWidget(self.duration_label)
        
        timeline_layout.addWidget(self.timeline)
        timeline_layout.addLayout(time_layout)
        timeline_layout.addLayout(volume_layout)
        
        top_control_layout = QHBoxLayout(self.top_control_container)
        top_control_layout.setContentsMargins(0, 0, 0, 0)
        top_control_layout.setSpacing(0)
        
        self.title_label = QLabel("OniPlayer")
        self.title_label.setStyleSheet("""
            QLabel {
                color: white;
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
                padding-left: 10px;
            }
        """)
        top_control_layout.addWidget(self.title_label)
        top_control_layout.addStretch()
        
        self.minimize_button = QPushButton("─")
        self.maximize_button = QPushButton("□")
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("closeButton")
        
        top_control_layout.addWidget(self.minimize_button)
        top_control_layout.addWidget(self.maximize_button)
        top_control_layout.addWidget(self.close_button)
        
        self.minimize_button.clicked.connect(self.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximize)
        self.close_button.clicked.connect(self.close)
        
        self.setAcceptDrops(True)
        
        # Initialize VLC engine instance for Linux.
        # Configuration for subtitle support:
        # --no-xvideo: Disable XV overlay to ensure subtitles render properly
        # --vout=x11: Use X11 video output for better subtitle support
        # --no-video-title-show: Disable video title overlay
        # --sub-source=freetype: Enable freetype font rendering for subtitles
        instance_args = [
            "--no-xvideo",
            "--vout=x11",
            "--no-video-title-show",
            "--sub-source=freetype",
        ]
        self.instance = vlc.Instance(instance_args)
        
        if self.instance is None:
            print("Error: Failed to create VLC instance")
            raise RuntimeError("Failed to create VLC instance")
            
        self.media_player = self.instance.media_player_new()
        
        self.media_player.audio_set_volume(60)
        self.media_player.audio_set_mute(False)
        
        self.subtitle_delay = 0
        self.last_position = 0
        self.current_index = 0
        
        self.event_manager = self.media_player.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self.on_media_end)
        self.event_manager.event_attach(vlc.EventType.MediaPlayerLengthChanged, self.on_length_changed)
        self.event_manager.event_attach(vlc.EventType.MediaPlayerMediaChanged, self.on_media_changed)
        # MediaPlayerPlaying fires when VLC actually starts decoding frames.
        # Subtitle track descriptions are not available until ~500ms after this.
        self.event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, self.on_media_playing)
        
        self.media_player.video_set_mouse_input(False)
        self.media_player.video_set_key_input(False)
        
        self.volume_overlay_timer = QTimer(self)
        self.volume_overlay_timer.setSingleShot(True)
        self.volume_overlay_timer.timeout.connect(self.hide_volume_overlay)
        
        self.title_overlay_timer = QTimer(self)
        self.title_overlay_timer.setSingleShot(True)
        self.title_overlay_timer.timeout.connect(self.hide_title_overlay)
        
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_ui)
        
        self.setMinimumSize(800, 600)
        
        self.playlist = []
        self.current_file = None
        self.has_media = False
        self.is_muted = False
        self.last_volume = 60
        self.last_subtitle_track = None
        self.disabled_subtitle_track_backup = None
        
        self.video_frame.setFocus()

        # Install global event filter for mouse hover tracking
        QApplication.instance().installEventFilter(self)

        # Hover tracking timer for seamless auto-hide
        self.hover_timer = QTimer(self)
        self.hover_timer.setInterval(50)
        self.hover_timer.timeout.connect(self.handle_mouse_hover)
        self.hover_timer.start()

        # Fullscreen transition flag to prevent ghost effects
        self._fullscreen_transition = False

        # Start in fullscreen mode by default
        QTimer.singleShot(100, self.toggle_fullscreen)
        # Ensure controls are properly sized after fullscreen transition
        QTimer.singleShot(200, self._ensure_fullscreen_control_sizes)



    def check_subtitle_tracks(self):
        """
        Check subtitle tracks without blocking the Qt event loop.

        VLC may not expose SPU/subtitle tracks immediately after play().
        Poll briefly using QTimer instead of time.sleep().
        """
        if not self.has_media:
            return

        try:
            spu_count = self.media_player.video_get_spu_count()
            descriptions = self.media_player.video_get_spu_description()
            print(f"[DEBUG] spu_count={spu_count} descriptions={descriptions}")
            if descriptions:
                available_ids = [track_id for track_id, _ in descriptions]
                valid_tracks = [
                    (track_id, name)
                    for track_id, name in descriptions
                    if track_id != -1
                ]
                if self.last_subtitle_track is not None:
                    if self.last_subtitle_track == -1:
                        self.media_player.video_set_spu(-1)
                        print(f"[DEBUG] Restored disabled subtitles (-1)")
                    elif self.last_subtitle_track in available_ids:
                        self.media_player.video_set_spu(self.last_subtitle_track)
                        print(f"[DEBUG] Restored subtitle track {self.last_subtitle_track}")
                    elif valid_tracks:
                        first_id = valid_tracks[0][0]
                        self.media_player.video_set_spu(first_id)
                        self.last_subtitle_track = first_id
                        self.disabled_subtitle_track_backup = first_id
                else:
                    if valid_tracks:
                        first_id = valid_tracks[0][0]
                        self.media_player.video_set_spu(first_id)
                        self.last_subtitle_track = first_id
                        self.disabled_subtitle_track_backup = first_id
                        print(f"[DEBUG] Auto-enabled first subtitle track {first_id}")
                        if self.subtitle_delay:
                            self.media_player.video_set_spu_delay(
                                self.subtitle_delay * 1000
                            )

                self.video_frame.update_subtitle_tracks()
                self.video_frame.update_audio_tracks()
                return

            # Subtitle tracks may not have been created yet.
            elapsed = getattr(self, "_subtitle_check_elapsed", 0)

            if elapsed < 3000:
                self._subtitle_check_elapsed = elapsed + 100
                QTimer.singleShot(100, self.check_subtitle_tracks)
            else:
                self.video_frame.update_subtitle_tracks()
                self.video_frame.update_audio_tracks()

        except Exception as e:
            print(f"Error checking subtitle tracks: {e}")

    def change_subtitle_track(self, track_id):
        try:
            if track_id == -1:
                self.media_player.video_set_spu(-1)
                self.last_subtitle_track = -1
                print(f"[DEBUG] Disabled subtitles")
                self.video_frame.update_subtitle_tracks()
                return True
            
            spu_count = self.media_player.video_get_spu_count()
            print(f"[DEBUG] Available subtitle tracks: {spu_count}")
            if spu_count > 0:
                self.media_player.video_set_spu(track_id)
                self.last_subtitle_track = track_id
                self.disabled_subtitle_track_backup = track_id
                current = self.media_player.video_get_spu()
                print(f"[DEBUG] set_spu({track_id}), current now = {current}")
                
                self.video_frame.update()
                self.video_frame.update_subtitle_tracks()
                return True
            else:
                print(f"[DEBUG] No subtitle tracks available")
                return False
        except Exception as e:
            print(f"Error changing subtitle track: {e}")
            return False

    def toggle_subtitles(self):
        if not self.has_media:
            return

        try:
            current = self.media_player.video_get_spu()
            descriptions = self.media_player.video_get_spu_description()

            valid_tracks = []

            if descriptions:
                for track_id, name in descriptions:
                    if track_id == -1:
                        continue

                    if isinstance(name, bytes):
                        name = name.decode("utf-8", errors="replace")
                    else:
                        name = str(name)

                    valid_tracks.append((track_id, name))

            if not valid_tracks:
                self.show_title_overlay("No subtitle tracks available")
                return

            # Currently disabled -> enable last selected or first available.
            if current == -1:
                track_id = getattr(self, 'disabled_subtitle_track_backup', None)
                if track_id is None:
                    track_id = self.last_subtitle_track

                valid_ids = [tid for tid, _ in valid_tracks]

                if track_id not in valid_ids or track_id == -1:
                    track_id = valid_tracks[0][0]

                self.change_subtitle_track(track_id)

                track_name = next(
                    (
                        name
                        for tid, name in valid_tracks
                        if tid == track_id
                    ),
                    "",
                )

                if track_name and track_name != str(track_id):
                    text = f"Subtitles: {track_name}"
                else:
                    text = f"Subtitles: Track {track_id}"

                self.show_title_overlay(text)
                return

            # Currently enabled -> disable.
            if current != -1:
                self.disabled_subtitle_track_backup = current

            self.change_subtitle_track(-1)
            self.show_title_overlay("Subtitles: Disabled")

        except Exception as e:
            print(f"Error toggling subtitles: {e}")

    def on_media_end(self, event):
        self.has_media = False
        self.video_frame.logo_overlay.show()
        QTimer.singleShot(0, self.play_next)

    def reset_to_default_ui(self):
        """Reset the player to default UI state when no video is playing"""
        self.media_player.stop()
        self.has_media = False
        self.current_file = None
        self.timeline.setValue(0)
        self.time_label.setText("0:00")
        self.duration_label.setText("/ 0:00")
        self.title_label.setText("OniPlayer")
        self.setWindowTitle("OniPlayer")
        self.play_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaPlay))
        self.timer.stop()
        
        # Show logo overlay when no video is playing
        self.video_frame.logo_overlay.show()
        
        # Preserve current window mode (fullscreen or floating window)
        # Only show controls if in floating window mode
        if not self.isFullScreen():
            self.top_control_container.show()
            self.timeline_container.show()
            self.main_layout.setContentsMargins(0, 30, 0, 40)
        
        # Show cursor when resetting to default UI
        if hasattr(self, 'video_frame'):
            self.video_frame.setCursor(Qt.CursorShape.ArrowCursor)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        
        # Repaint video frame to show default logo
        self.video_frame.update()

    def on_length_changed(self, event):
        length = self.media_player.get_length()
        if length > 0:
            self.timeline.setMaximum(length)

    def on_media_changed(self, event):
        QTimer.singleShot(100, self.adjust_window_to_video_size)
        QTimer.singleShot(200, self.refresh_cursor)

    def force_cursor_update(self):
        """Force cursor to blank cursor to fix cursor state from other applications"""
        try:
            # Force the cursor to blank cursor immediately
            self.video_frame.setCursor(Qt.CursorShape.BlankCursor)
            # Temporarily set to arrow cursor to force a cursor change
            self.video_frame.setCursor(Qt.CursorShape.ArrowCursor)
            # Then back to blank cursor
            QTimer.singleShot(10, lambda: self.video_frame.setCursor(Qt.CursorShape.BlankCursor))
            # Then apply the correct cursor based on position
            QTimer.singleShot(20, self.refresh_cursor)
        except Exception as e:
            print(f"Error forcing cursor update: {e}")

    def refresh_cursor(self):
        try:
            local_pos = self.video_frame.mapFromGlobal(self.cursor().pos())
            local_y = local_pos.y()
            window_height = self.height()
            
            top_area_height = 30
            timeline_area_height = 40
            
            self.video_frame.setCursor(Qt.CursorShape.ArrowCursor)
            
            if local_y <= top_area_height or window_height - local_y <= timeline_area_height:
                QTimer.singleShot(50, lambda: self.video_frame.setCursor(Qt.CursorShape.ArrowCursor))
            else:
                QTimer.singleShot(50, lambda: self.video_frame.setCursor(Qt.CursorShape.BlankCursor))
        except Exception as e:
            print(f"Error refreshing cursor: {e}")

    def play_next(self):
        try:
            # Check if there are more videos to play
            if not self.playlist or len(self.playlist) <= 1:
                self.reset_to_default_ui()
                return
                
            was_fullscreen = self.isFullScreen()
            if self.has_media:
                length = self.media_player.get_length()
                if length > 0:
                    self.last_position = self.media_player.get_position()
            
            next_index = self.current_index + 1
            if next_index >= len(self.playlist):
                self.reset_to_default_ui()
                return
            
            self.current_index = next_index
            next_file = self.playlist[self.current_index]
            self.play_file(next_file)
            
            if was_fullscreen and not self.isFullScreen():
                QTimer.singleShot(100, self.toggle_fullscreen)
            
        except Exception as e:
            print(f"Error playing next file: {e}")

    def play_previous(self):
        try:
            if not self.playlist or len(self.playlist) <= 1:
                return
                
            was_fullscreen = self.isFullScreen()
            if self.has_media:
                length = self.media_player.get_length()
                if length > 0:
                    self.last_position = self.media_player.get_position()
            
            self.current_index = (self.current_index - 1) % len(self.playlist)
            prev_file = self.playlist[self.current_index]
            self.play_file(prev_file)
            
            if was_fullscreen and not self.isFullScreen():
                QTimer.singleShot(100, self.toggle_fullscreen)
            
        except Exception as e:
            print(f"Error playing previous file: {e}")

    def update_playlist(self, filepath):
        filepath = os.path.normpath(filepath)
        self.current_directory = os.path.dirname(filepath)
        video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv'}
        
        self.playlist = [
            os.path.normpath(os.path.join(self.current_directory, f))
            for f in os.listdir(self.current_directory)
            if os.path.splitext(f)[1].lower() in video_extensions
        ]
        self.playlist.sort()
        
        if filepath not in self.playlist:
            self.playlist.append(filepath)
            self.playlist.sort()
        
        self.current_file = filepath
        self.current_index = self.playlist.index(filepath)

    def adjust_volume(self, delta):
        current_volume = self.volume_slider.value()
        new_volume = max(0, min(100, current_volume + delta))
        if new_volume != current_volume:
            self.volume_slider.setValue(new_volume)
            self.media_player.audio_set_volume(new_volume)
            self.show_volume_overlay()

    def seek_relative(self, seconds):
        if not self.has_media:
            return
        current_time = self.media_player.get_time()
        new_time = current_time + (seconds * 1000)
        length = self.media_player.get_length()
        new_time = max(0, min(length, new_time))
        self.media_player.set_time(int(new_time))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.toggle_play()
            event.accept()
        elif event.key() == Qt.Key.Key_F and not event.isAutoRepeat():
            self.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key.Key_Up:
            self.adjust_volume(5)
            event.accept()
        elif event.key() == Qt.Key.Key_Down:
            self.adjust_volume(-5)
            event.accept()
        elif event.key() == Qt.Key.Key_Left:
            self.seek_relative(-10)
            event.accept()
        elif event.key() == Qt.Key.Key_Right:
            self.seek_relative(10)
            event.accept()
        elif event.key() == Qt.Key.Key_M and not event.isAutoRepeat():
            self.toggle_mute()
            event.accept()
        elif event.key() == Qt.Key.Key_PageUp:
            self.play_next()
            event.accept()
        elif event.key() == Qt.Key.Key_PageDown:
            self.play_previous()
            event.accept()
        elif event.key() == Qt.Key.Key_A and not event.isAutoRepeat():
            self.cycle_audio_track()
            event.accept()
        elif event.key() == Qt.Key.Key_S and not event.isAutoRepeat():
            self.toggle_subtitles()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.media_player.stop()
        self.media_player.release()
        self.instance.release()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.video_frame.setFocus()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.update_title_overlay_position()
        self.update_volume_overlay_position()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            filename = os.path.basename(event.mimeData().urls()[0].toLocalFile())
            self.show_title_overlay(f"{filename}")
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile():
                self.play_file(url.toLocalFile())
                event.acceptProposedAction()

    def play_file(self, filename):
        try:
            if not os.path.exists(filename):
                print(f"File not found: {filename}")
                return
                
            self.update_playlist(filename)
            self.subtitle_delay = 0
            self.last_subtitle_track = None
            self.disabled_subtitle_track_backup = None

            # Set the X11 window FIRST - before set_media and play()
            # This matches the working example pattern and ensures the
            # subtitle/video output is bound to the correct native window.
            try:
                self.media_player.set_xwindow(int(self.video_frame.winId()))
            except Exception as e:
                print(f"Error setting X window handle: {e}")
                return

            media = self.instance.media_new(filename)
            
            # Parse media to get video dimensions before playing
            # This ensures video size is available for window sizing on first launch
            media.parse()
            
            self.media_player.set_media(media)
            self.media_player.play()  # on_media_playing fires ~500ms later → subtitle tracks loaded

            self.has_media = True
            self.current_file = filename
            
            # Hide logo overlay when video is playing
            self.video_frame.logo_overlay.hide()

            self.adjust_window_to_video_size()

            QTimer.singleShot(200, self.refresh_cursor)

            if self.last_position > 0:
                QTimer.singleShot(100, lambda: self.media_player.set_position(self.last_position))
                self.last_position = 0
            
            filename_display = os.path.basename(filename)
            self.setWindowTitle(f"OniPlayer - {filename_display}")
            self.title_label.setText(filename_display)
            self.show_title_overlay(filename_display)

            # Sync play button icon (play() was called directly above)
            self.play_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaPause))
            self.timer.start()
            
        except Exception as e:
            print(f"Error loading file {filename}: {e}")

    def on_media_playing(self, event):
        """Fires when VLC actually begins decoding frames.
        Subtitle track descriptions may not be available immediately."""
        self._subtitle_check_elapsed = 0
        QTimer.singleShot(200, self.check_subtitle_tracks)


    def toggle_play(self):
        if not self.has_media:
            return
            
        if self.media_player.is_playing():
            self.media_player.pause()
            self.play_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaPlay))
            self.timer.stop()
        else:
            self.media_player.play()
            self.play_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaPause))
            self.timer.start()
            
    def toggle_maximize(self):
        self.toggle_fullscreen()

    def toggle_fullscreen(self):
        if not self.isFullScreen():
            self.prev_geometry = self.geometry()
            self.main_layout.setContentsMargins(0, 0, 0, 0)
            
            self.showFullScreen()
            
            # Resize control containers to match fullscreen width
            window_width = self.width()
            self.top_control_container.setFixedWidth(window_width)
            self.timeline_container.setFixedWidth(window_width)
            
            # Force immediate hide with aggressive repaint to prevent ghost effect
            self.top_control_container.hide()
            self.timeline_container.hide()
            
            # Force complete repaint sequence
            self.top_control_container.repaint()
            self.timeline_container.repaint()
            self.video_frame.repaint()
            self.repaint()
            
            self.update_control_positions()
            
            # Add flag to prevent immediate showing by hover handler with shorter delay
            self._fullscreen_transition = True
            QTimer.singleShot(300, self._clear_fullscreen_transition)
            
            # Force one more refresh after transition
            QTimer.singleShot(100, self._force_refresh_controls)
        else:
            self.showNormal()
            if hasattr(self, 'prev_geometry'):
                self.setGeometry(self.prev_geometry)
            
            # Reset control containers to dynamic width for windowed mode
            self.top_control_container.setFixedWidth(QWIDGETSIZE_MAX)
            self.timeline_container.setFixedWidth(QWIDGETSIZE_MAX)
            
            self.top_control_container.show()
            self.timeline_container.show()
            self.main_layout.setContentsMargins(0, 30, 0, 40)
            
            # Force immediate geometry update
            self.update_control_positions()
            
            # Force complete repaint sequence
            self.top_control_container.repaint()
            self.timeline_container.repaint()
            self.video_frame.repaint()
            self.repaint()
            
            # Add flag to prevent immediate hiding by hover handler with shorter delay
            self._fullscreen_transition = True
            QTimer.singleShot(300, self._clear_fullscreen_transition)
            
            # Force one more refresh after transition
            QTimer.singleShot(100, self._force_refresh_controls)

    def _clear_fullscreen_transition(self):
        """Clear the fullscreen transition flag after a short delay"""
        self._fullscreen_transition = False

    def _force_refresh_controls(self):
        """Force refresh of control containers to eliminate ghost effects"""
        if self.isFullScreen():
            # Ensure controls are hidden in fullscreen
            self.top_control_container.hide()
            self.timeline_container.hide()
        else:
            # Ensure controls are shown in windowed mode
            self.top_control_container.show()
            self.timeline_container.show()
        
        # Force repaint
        self.top_control_container.repaint()
        self.timeline_container.repaint()
        self.video_frame.repaint()
        self.update()
        
        # Update logo overlay visibility based on media state
        if self.has_media:
            self.video_frame.logo_overlay.hide()
        else:
            self.video_frame.logo_overlay.show()

    def _ensure_fullscreen_control_sizes(self):
        """Ensure control containers are properly sized in fullscreen mode"""
        if self.isFullScreen():
            window_width = self.width()
            self.top_control_container.setFixedWidth(window_width)
            self.timeline_container.setFixedWidth(window_width)
            self.update_control_positions()

    def set_position(self, position):
        if self.has_media:
            self.media_player.set_time(position)
            if position >= 0:
                total_seconds = position / 1000
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                seconds = int(total_seconds % 60)
                
                if hours > 0:
                    time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    time_str = f"{minutes:02d}:{seconds:02d}"
                self.time_label.setText(time_str)
                
    def update_time_display(self, current_time):
        if current_time >= 0:
            total_seconds = current_time / 1000
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            seconds = int(total_seconds % 60)
            
            if hours > 0:
                time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                time_str = f"{minutes:02d}:{seconds:02d}"
            self.time_label.setText(time_str)
            
            length = self.media_player.get_length()
            if length > 0:
                total_seconds = length / 1000
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                seconds = int(total_seconds % 60)
                
                if hours > 0:
                    duration_str = f"/ {hours}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = f"/ {minutes:02d}:{seconds:02d}"
                self.duration_label.setText(duration_str)

    def set_volume(self, volume):
        try:
            self.media_player.audio_set_mute(False)
            self.media_player.audio_set_volume(volume)
            
            if volume > 0 and self.is_muted:
                self.is_muted = False
                self.volume_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolume, size=18))
            elif volume == 0 and not self.is_muted:
                self.is_muted = True
                self.volume_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolumeMuted, size=18))
        except Exception as e:
            print(f"Error setting volume: {e}")

    def update_ui(self):
        if not self.has_media:
            return
            
        try:
            if self.media_player and self.media_player.is_playing():
                current_time = self.media_player.get_time()
                if current_time >= 0:
                    self.timeline.setValue(current_time)
                    self.update_time_display(current_time)
        except Exception:
            pass
        
    def open_file(self):
        dialog = QFileDialog()
        filename, _ = dialog.getOpenFileName(self, "Open Video",
                                           "",
                                           "Video Files (*.mp4 *.avi *.mkv *.mov *.wmv)")
        
        if filename:
            self.play_file(filename)

    def adjust_subtitle_sync(self, ms):
        if not self.has_media:
            return
            
        try:
            self.subtitle_delay += ms
            delay_microseconds = self.subtitle_delay * 1000
            
            current_track = self.media_player.video_get_spu()
            if current_track >= 0:
                success = self.media_player.video_set_spu_delay(delay_microseconds)
                if success == 0:
                    delay_str = f"+{self.subtitle_delay}ms" if self.subtitle_delay > 0 else f"{self.subtitle_delay}ms"
                    self.show_title_overlay(f"Subtitle Delay: {delay_str}")
        except Exception as e:
            print(f"Error adjusting subtitle sync: {e}")

    def reset_subtitle_sync(self):
        if not self.has_media:
            return
            
        try:
            current_track = self.media_player.video_get_spu()
            if current_track >= 0:
                self.subtitle_delay = 0
                success = self.media_player.video_set_spu_delay(0)
                if success == 0:
                    self.show_title_overlay("Subtitle Sync Reset")
        except Exception as e:
            print(f"Error resetting subtitle sync: {e}")

    def cycle_audio_track(self):
        if not self.has_media:
            return
            
        try:
            current = self.media_player.audio_get_track()
            count = self.media_player.audio_get_track_count()
            
            if count <= 1:
                return
                
            descriptions = self.media_player.audio_get_track_description()
            valid_tracks = []
            
            if descriptions:
                for track_id, _ in descriptions:
                    if track_id != -1:
                        valid_tracks.append(track_id)
            
            if not valid_tracks:
                return
                
            try:
                current_index = valid_tracks.index(current)
                next_index = (current_index + 1) % len(valid_tracks)
            except ValueError:
                next_index = 0
            
            next_track = valid_tracks[next_index]
            self.media_player.audio_set_track(next_track)
            
            track_name = f"Audio: Track {next_track + 1}"
            if descriptions:
                for track_id, desc in descriptions:
                    if track_id == next_track:
                        if desc:
                            try:
                                desc = desc.decode('utf-8') if isinstance(desc, bytes) else str(desc)
                                track_name = f"Audio: Track {next_track + 1} ({desc})"
                            except Exception:
                                pass
                        break
            
            self.show_title_overlay(track_name)
            if hasattr(self.video_frame, "update_audio_tracks"):
                self.video_frame.update_audio_tracks()
                
        except Exception as e:
            print(f"Error cycling audio track: {e}")

    def cycle_audio_track_reverse(self):
        if not self.has_media:
            return
            
        try:
            current = self.media_player.audio_get_track()
            count = self.media_player.audio_get_track_count()
            
            if count <= 1:
                return
                
            descriptions = self.media_player.audio_get_track_description()
            valid_tracks = []
            
            if descriptions:
                for track_id, _ in descriptions:
                    if track_id != -1:
                        valid_tracks.append(track_id)
            
            if not valid_tracks:
                return
                
            try:
                current_index = valid_tracks.index(current)
                prev_index = (current_index - 1) % len(valid_tracks)
            except ValueError:
                prev_index = len(valid_tracks) - 1
            
            prev_track = valid_tracks[prev_index]
            self.media_player.audio_set_track(prev_track)
            
            track_name = f"Audio: Track {prev_track + 1}"
            if descriptions:
                for track_id, desc in descriptions:
                    if track_id == prev_track:
                        if desc:
                            try:
                                desc = desc.decode('utf-8') if isinstance(desc, bytes) else str(desc)
                                track_name = f"Audio: Track {prev_track + 1} ({desc})"
                            except Exception:
                                pass
                        break
            
            self.show_title_overlay(track_name)
            if hasattr(self.video_frame, "update_audio_tracks"):
                self.video_frame.update_audio_tracks()
                
        except Exception as e:
            print(f"Error cycling audio track reverse: {e}")

    def toggle_mute(self):
        if not self.has_media:
            return
            
        try:
            current_mute = self.media_player.audio_get_mute()
            self.media_player.audio_set_mute(not current_mute)
            
            QTimer.singleShot(5, lambda: self._update_mute_overlay())
            QTimer.singleShot(10, self.update_volume_icon)
            
        except Exception as e:
            print(f"Error toggling mute: {e}")
            
    def _update_mute_overlay(self):
        try:
            is_muted = self.media_player.audio_get_mute()
            current_volume = self.media_player.audio_get_volume()
            
            if is_muted:
                self.volume_overlay.setText("Volume: Muted")
            else:
                self.volume_overlay.setText(f"Volume: {current_volume}%")
                
            self.show_volume_overlay()
        except Exception as e:
            print(f"Error updating mute overlay: {e}")

    def update_volume_icon(self):
        try:
            is_muted = self.media_player.audio_get_mute()
            current_volume = self.media_player.audio_get_volume()
            
            self.volume_button.setIcon(QIcon())
            
            if is_muted or current_volume == 0:
                icon = timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolumeMuted, size=18)
            else:
                icon = timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolume, size=18)
            
            self.volume_button.setIcon(icon)
        except Exception as e:
            print(f"Error updating volume icon: {e}")

    def on_volume_change(self, value):
        try:
            self.media_player.audio_set_mute(False)
            self.media_player.audio_set_volume(value)
            
            self.volume_overlay.setText(f"Volume: {value}%")
            self.show_volume_overlay()
            
            QTimer.singleShot(10, self.update_volume_icon)
        except Exception as e:
            print(f"Error changing volume: {e}")

    def timeline_pressed(self):
        self.timer.stop()

    def timeline_released(self):
        self.timer.start()

    def eventFilter(self, watched, event):
        # Removed menu closing logic - let VideoFrame handle it in mousePressEvent
        
        if event.type() in (
            QEvent.Type.MouseMove,
            QEvent.Type.HoverMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Enter,
            QEvent.Type.Leave,
        ):
            self.handle_mouse_hover()
        return super().eventFilter(watched, event)

    def handle_mouse_hover(self):
        if not self.isVisible() or self.isMinimized():
            return

        # Skip hover handling during fullscreen transition to prevent ghost effects
        if hasattr(self, '_fullscreen_transition') and self._fullscreen_transition:
            return

        # In Floating Window (windowed) mode:
        if not self.isFullScreen():
            # ALWAYS show titlebar and timeline in windowed mode
            if not self.top_control_container.isVisible():
                self.top_control_container.show()

            if not self.timeline_container.isVisible():
                self.timeline_container.show()

            # Check if cursor is over control areas
            global_pos = QCursor.pos()
            local_pos = self.mapFromGlobal(global_pos)
            x = local_pos.x()
            y = local_pos.y()
            win_w = self.width()
            win_h = self.height()

            top_threshold = 30
            bottom_threshold = 40

            in_top_area = (y <= top_threshold)
            in_bottom_area = (win_h - y <= bottom_threshold)

            # If context menu is open, show cursor
            if hasattr(self, 'video_frame') and hasattr(self.video_frame, 'context_menu') and self.video_frame.context_menu.isVisible():
                if hasattr(self, 'video_frame'):
                    self.video_frame.setCursor(Qt.CursorShape.ArrowCursor)
                self.setCursor(Qt.CursorShape.ArrowCursor)
                return

            # Show cursor only when hovering over control areas
            if in_top_area or in_bottom_area:
                if hasattr(self, 'video_frame'):
                    self.video_frame.setCursor(Qt.CursorShape.ArrowCursor)
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                if hasattr(self, 'video_frame'):
                    self.video_frame.setCursor(Qt.CursorShape.BlankCursor)
                self.setCursor(Qt.CursorShape.BlankCursor)
            return

        # If window is currently being dragged by titlebar
        if hasattr(self, 'drag_start_position'):
            self.top_control_container.show()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        # If context menu is open
        if hasattr(self, 'video_frame') and hasattr(self.video_frame, 'context_menu') and self.video_frame.context_menu.isVisible():
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        # In Fullscreen mode: Auto-hide titlebar & timeline on hover
        global_pos = QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)
        x = local_pos.x()
        y = local_pos.y()
        win_w = self.width()
        win_h = self.height()

        # If mouse is outside window bounds
        if x < 0 or x > win_w or y < 0 or y > win_h:
            self.top_control_container.hide()
            self.timeline_container.hide()
            if hasattr(self, 'video_frame'):
                self.video_frame.setCursor(Qt.CursorShape.ArrowCursor)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        top_threshold = 45
        bottom_threshold = 55

        in_top_area = (y <= top_threshold)
        in_bottom_area = (win_h - y <= bottom_threshold)

        # Keep controls visible if slider is being dragged
        if hasattr(self, 'timeline') and hasattr(self, 'volume_slider') and (self.timeline.isSliderDown() or self.volume_slider.isSliderDown()):
            in_bottom_area = True

        # Auto-hide logic for fullscreen mode
        if in_top_area:
            if not self.top_control_container.isVisible():
                self.top_control_container.show()
        else:
            if self.top_control_container.isVisible():
                self.top_control_container.hide()

        if in_bottom_area:
            if not self.timeline_container.isVisible():
                self.timeline_container.show()
        else:
            if self.timeline_container.isVisible():
                self.timeline_container.hide()

        # Set cursor shape based on hover area
        if in_top_area or in_bottom_area:
            if hasattr(self, 'video_frame'):
                self.video_frame.setCursor(Qt.CursorShape.ArrowCursor)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            if hasattr(self, 'video_frame'):
                self.video_frame.setCursor(Qt.CursorShape.BlankCursor)
            self.setCursor(Qt.CursorShape.BlankCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        super().mouseMoveEvent(event)
        
        if hasattr(self, 'drag_start_position') and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.drag_start_position
            self.move(self.window_pos_at_drag_start + delta)
            event.accept()
            return
            
        self.handle_mouse_hover()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.isFullScreen():
            if self.top_control_container.geometry().contains(event.pos()) or event.pos().y() <= 30:
                self.drag_start_position = event.globalPosition().toPoint()
                self.window_pos_at_drag_start = self.pos()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if hasattr(self, 'drag_start_position'):
                delattr(self, 'drag_start_position')
                delattr(self, 'window_pos_at_drag_start')
        super().mouseReleaseEvent(event)

    def update_volume_overlay_position(self):
        if self.volume_overlay.isVisible():
            # Overlays are top-level windows; position using global screen coordinates
            window_pos = self.mapToGlobal(QPoint(0, 0))
            x = window_pos.x() + 20
            y = window_pos.y() + 50
            if self.title_overlay.isVisible():
                title_height = self.title_overlay.height()
                y += title_height + 5
            self.volume_overlay.move(x, y)

    def update_title_overlay_position(self):
        if self.title_overlay.isVisible():
            window_pos = self.mapToGlobal(QPoint(0, 0))
            x = window_pos.x() + 20
            y = window_pos.y() + 20
            self.title_overlay.move(x, y)
            self.title_overlay.raise_()
            if self.volume_overlay.isVisible():
                self.update_volume_overlay_position()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        # Ensure control containers resize properly in fullscreen mode
        if self.isFullScreen():
            window_width = self.width()
            self.top_control_container.setFixedWidth(window_width)
            self.timeline_container.setFixedWidth(window_width)
        
        self.update_control_positions()
        self.update_volume_overlay_position()
        self.update_title_overlay_position()

    def show_volume_overlay(self):
        try:
            # Get current volume and update text
            volume = self.media_player.audio_get_volume()
            is_muted = self.media_player.audio_get_mute()
            if is_muted:
                self.volume_overlay.setText("Volume: Muted")
            else:
                self.volume_overlay.setText(f"Volume: {volume}%")
            
            # Calculate position relative to the main window (global screen coords)
            window_pos = self.mapToGlobal(QPoint(0, 0))
            
            # Adjust size of overlay
            self.volume_overlay.adjustSize()
            overlay_width = self.volume_overlay.width()
            overlay_height = self.volume_overlay.height()
            
            # Position in top-left corner with margins
            margin = 20
            volume_x = window_pos.x() + margin
            volume_y = window_pos.y() + margin
            
            # Ensure overlay is within window bounds
            volume_x = max(window_pos.x(), min(volume_x, window_pos.x() + self.width() - overlay_width))
            volume_y = max(window_pos.y(), min(volume_y, window_pos.y() + self.height() - overlay_height))
            
            # Move and show overlay
            self.volume_overlay.move(volume_x, volume_y)
            self.volume_overlay.show()
            self.volume_overlay.raise_()
            
            # If title overlay is visible, hide it
            if self.title_overlay.isVisible():
                self.title_overlay.hide()
                self.title_overlay_timer.stop()
                self.title_overlay_timer.start(2000)
            
            # Reset and start the hide timer
            self.volume_overlay_timer.stop()
            self.volume_overlay_timer.start(1500)
            
        except Exception as e:
            print(f"Error showing volume overlay: {e}")

    def show_title_overlay(self, title):
        if not title:
            return
            
        # Cancel any existing hide timer
        if self.title_overlay_timer.isActive():
            self.title_overlay_timer.stop()
        
        self.title_overlay.setText(title)
        
        # Calculate position relative to the video frame (global screen coords)
        video_pos = self.video_frame.mapToGlobal(QPoint(0, 0))
        title_x = video_pos.x() + 20
        title_y = video_pos.y() + 20
        
        # Set text with eliding for long titles
        self.title_overlay.setText(title)
        self.title_overlay.setWordWrap(False)
        font_metrics = QFontMetrics(self.title_overlay.font())
        elided_text = font_metrics.elidedText(title, Qt.TextElideMode.ElideRight, 800)
        self.title_overlay.setText(elided_text)
        
        # Move to fixed position
        self.title_overlay.move(title_x, title_y)
        
        if self.volume_overlay.isVisible():
            self.title_overlay.hide()
        else:
            # Hide any existing title first
            self.title_overlay.hide()
            self.title_overlay.show()
            # Start new hide timer
            if title.startswith("Audio:") or title.startswith("Subtitles:"):
                self.title_overlay_timer.start(2000)
            else:
                self.title_overlay_timer.start(3000)

    def hide_volume_overlay(self):
        self.volume_overlay.hide()

    def hide_title_overlay(self):
        self.title_overlay.hide()

    def update_control_positions(self):
        if not self.isVisible():
            return
            
        window_width = self.width()
        
        # In fullscreen mode, explicitly set container widths to match window width
        if self.isFullScreen():
            self.top_control_container.setFixedWidth(window_width)
            self.timeline_container.setFixedWidth(window_width)
        
        self.top_control_container.setGeometry(
            0, 0, window_width, self.top_control_container.height()
        )
        self.timeline_container.setGeometry(
            0, self.height() - self.timeline_container.height(),
            window_width, self.timeline_container.height()
        )
        
        self.top_control_container.update()
        self.timeline_container.update()

    def adjust_window_to_video_size(self):
        try:
            if self.isFullScreen():
                return
                
            video_width = self.media_player.video_get_width()
            video_height = self.media_player.video_get_height()
            
            if video_width > 0 and video_height > 0:
                aspect_ratio = video_width / video_height
                screen = QApplication.primaryScreen()
                screen_size = screen.availableGeometry()
                
                max_width = min(screen_size.width() * 0.8, video_width)
                max_height = min(screen_size.height() * 0.8, video_height)
                
                if max_width / max_height > aspect_ratio:
                    width = int(max_height * aspect_ratio)
                    height = int(max_height)
                else:
                    width = int(max_width)
                    height = int(max_width / aspect_ratio)
                
                x = (screen_size.width() - width) // 2
                y = (screen_size.height() - height) // 2
                
                self.setGeometry(x, y, width, height)
                
        except Exception as e:
            print(f"Error adjusting window size: {e}")

    def show_audio_track_overlay(self, text):
        """Show audio track overlay with the given text"""
        self.audio_track_overlay.setText(text)
        self.audio_track_overlay.adjustSize()
        
        # Calculate position relative to the main window (global screen coords)
        window_pos = self.mapToGlobal(QPoint(0, 0))
        margin = 20
        x = window_pos.x() + margin
        y = window_pos.y() + margin
        
        # Move and show overlay
        self.audio_track_overlay.move(x, y)
        self.audio_track_overlay.show()
        self.audio_track_overlay.raise_()
        
        # Reset and start the hide timer
        self.audio_track_overlay_timer.stop()
        self.audio_track_overlay_timer.start(3000)

    def hide_audio_track_overlay(self):
        self.audio_track_overlay.hide()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    player = OniPlayer()
    
    if len(sys.argv) > 1:
        player.play_file(sys.argv[1])
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
