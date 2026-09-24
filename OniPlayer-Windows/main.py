import sys
import os
from PyQt6.QtCore import Qt, QTimer, QMimeData, QPoint, QDateTime
from PyQt6.QtGui import QPalette, QColor, QMouseEvent, QKeyEvent, QAction, QActionGroup, QIcon, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                          QHBoxLayout, QPushButton, QSlider, QFileDialog,
                          QLabel, QStyle, QFrame, QStackedLayout, QMenu, 
                          QMessageBox, QSizePolicy)

# Set up base directory for all resources
if getattr(sys, 'frozen', False):
    # If we're running as a PyInstaller bundle
    base_dir = os.path.dirname(sys.executable)
else:
    # If we're running as a normal Python script
    base_dir = os.path.dirname(os.path.abspath(__file__))

# Set up paths for all resources
vlc_plugins_path = os.path.join(base_dir, 'plugins')
icon_path = os.path.join(base_dir, 'icon.ico')
libvlc_path = os.path.join(base_dir, 'libvlc.dll')
libvlccore_path = os.path.join(base_dir, 'libvlccore.dll')

# Verify all required files exist
required_files = {
    'icon.ico': icon_path,
    'libvlc.dll': libvlc_path,
    'libvlccore.dll': libvlccore_path,
    'plugins directory': vlc_plugins_path
}

missing_files = []
for name, path in required_files.items():
    if not os.path.exists(path):
        missing_files.append(f"{name} at {path}")

if missing_files:
    error_msg = "Required files are missing:\n" + "\n".join(missing_files)
    print(error_msg)
    if getattr(sys, 'frozen', False):
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, error_msg, "Error", 0x10)
    sys.exit(1)

# Set AppUserModelID so Windows groups the taskbar icon correctly
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("oniplayer.video.player.6.0")
except Exception:
    pass


# Set up VLC environment
os.environ['PATH'] = base_dir + os.pathsep + os.environ.get('PATH', '')
os.environ['VLC_PLUGIN_PATH'] = vlc_plugins_path


# Import VLC after setting up environment
import vlc

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

class VideoFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # Mouse state tracking
        self.left_button_pressed = False
        self.right_button_pressed = False
        self.show_context = True  # Flag to control context menu display
        self.combination_active = False  # New flag to track if we're in a button combination
        self.combination_start_time = 0  # Track when combination started
        
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
        
        # Create context menu and audio submenu
        self.context_menu = QMenu(self)
        self.audio_tracks_menu = None  # Will be created in setup_context_menu
        self.audio_track_group = QActionGroup(self)
        self.audio_track_group.setExclusive(True)
        self.audio_track_group.triggered.connect(self.on_audio_track_changed)
        
        self.subtitle_tracks_menu = None  # Will be created in setup_context_menu
        self.subtitle_track_group = QActionGroup(self)
        self.subtitle_track_group.setExclusive(True)
        self.subtitle_track_group.triggered.connect(self.on_subtitle_track_changed)
        
        self.setup_context_menu()
        
        # Add logo text
        self.logo_text = "OniPlayer"
        self.logo_font = self.font()
        self.logo_font.setPointSize(28)  # Increased size but still minimalistic
        self.logo_font.setBold(True)  # Made bold again

    def handle_button_combination(self):
        """Handle button combinations after the timeout"""
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.left_button_pressed = True
            if self.right_button_pressed:
                # Right button is already pressed, this is a right-hold-left-click
                self.pending_button_combination = "right_hold_left"
                self.button_combination_timer.start()
                self.show_context = False
                self.combination_active = True  # Set immediately to prevent context menu
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_button_pressed = True
            if self.left_button_pressed:
                # Left button is already pressed, this is a left-hold-right-click
                self.pending_button_combination = "left_hold_right"
                self.button_combination_timer.start()
                self.show_context = False
                self.combination_active = True  # Set immediately to prevent context menu
            else:
                # For single right click, allow context menu
                self.show_context = True
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
            current_time = QDateTime.currentMSecsSinceEpoch()
            time_since_combination = current_time - self.combination_start_time
            
            if (self.show_context and 
                self.parent.has_media and 
                not self.pending_button_combination and
                not self.combination_active and
                time_since_combination > 200):
                
                # Show cursor for context menu
                self.setCursor(Qt.CursorShape.ArrowCursor)
                
                # Update tracks before showing menu
                self.update_audio_tracks()
                self.update_subtitle_tracks()
                
                # Show context menu at cursor position
                self.context_menu.popup(event.globalPos())
                
                # Hide cursor when menu closes
                self.context_menu.aboutToHide.connect(self._on_context_menu_hide)
                
                event.accept()
            else:
                event.ignore()
        except Exception as e:
            pass

    def _on_context_menu_hide(self):
        """Handle context menu closing"""
        # Get current mouse position relative to window
        cursor_pos = self.mapFromGlobal(self.cursor().pos())
        local_y = cursor_pos.y()
        window_height = self.parent.height()
        
        # Only hide cursor if not in control areas
        if not (local_y <= 30 or window_height - local_y <= 40):
            self.setCursor(Qt.CursorShape.BlankCursor)

    def setup_context_menu(self):
        # Set style for context menu
        self.context_menu.setStyleSheet("""
            QMenu {
                background-color: rgba(30, 30, 30, 0.95);
                border: 1px solid rgba(60, 60, 60, 0.8);
                padding: 5px;
                border-radius: 3px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 2px;
                color: rgba(255, 255, 255, 0.9);
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(60, 60, 60, 0.8);
                margin: 4px 0px;
            }
        """)
        
        # Playback control
        play_action = self.context_menu.addAction("Play/Pause")
        play_action.triggered.connect(self.parent.toggle_play)
        
        # Fullscreen toggle
        fullscreen_action = self.context_menu.addAction("Toggle Fullscreen")
        fullscreen_action.triggered.connect(self.parent.toggle_fullscreen)
        
        self.context_menu.addSeparator()
        
        # Create and add audio tracks submenu
        self.audio_tracks_menu = self.context_menu.addMenu("Audio Track")
        self.audio_tracks_menu.setStyleSheet("""
            QMenu {
                background-color: rgba(30, 30, 30, 0.95);
                border: 1px solid rgba(60, 60, 60, 0.8);
                padding: 5px;
                border-radius: 3px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 2px;
                color: rgba(255, 255, 255, 0.9);
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(60, 60, 60, 0.8);
                margin: 4px 0px;
            }
        """)
        
        # Create and add subtitle tracks submenu
        self.subtitle_tracks_menu = self.context_menu.addMenu("Subtitles")
        self.subtitle_tracks_menu.setStyleSheet("""
            QMenu {
                background-color: rgba(30, 30, 30, 0.95);
                border: 1px solid rgba(60, 60, 60, 0.8);
                padding: 5px;
                border-radius: 3px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 2px;
                color: rgba(255, 255, 255, 0.9);
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(60, 60, 60, 0.8);
                margin: 4px 0px;
            }
        """)
        
        # Add subtitle sync submenu
        subtitle_sync_menu = self.context_menu.addMenu("Subtitle Sync")
        subtitle_sync_menu.setStyleSheet("""
            QMenu {
                background-color: rgba(30, 30, 30, 0.95);
                border: 1px solid rgba(60, 60, 60, 0.8);
                padding: 5px;
                border-radius: 3px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 2px;
                color: rgba(255, 255, 255, 0.9);
                font-family: "Segoe UI";
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(60, 60, 60, 0.8);
                margin: 4px 0px;
            }
        """)
        
        # Add sync controls
        delay_100ms = subtitle_sync_menu.addAction("Delay +100ms")
        delay_100ms.triggered.connect(lambda: self.parent.adjust_subtitle_sync(100))
        
        delay_500ms = subtitle_sync_menu.addAction("Delay +500ms")
        delay_500ms.triggered.connect(lambda: self.parent.adjust_subtitle_sync(500))
        
        delay_1000ms = subtitle_sync_menu.addAction("Delay +1s")
        delay_1000ms.triggered.connect(lambda: self.parent.adjust_subtitle_sync(1000))
        
        subtitle_sync_menu.addSeparator()
        
        advance_100ms = subtitle_sync_menu.addAction("Advance -100ms")
        advance_100ms.triggered.connect(lambda: self.parent.adjust_subtitle_sync(-100))
        
        advance_500ms = subtitle_sync_menu.addAction("Advance -500ms")
        advance_500ms.triggered.connect(lambda: self.parent.adjust_subtitle_sync(-500))
        
        advance_1000ms = subtitle_sync_menu.addAction("Advance -1s")
        advance_1000ms.triggered.connect(lambda: self.parent.adjust_subtitle_sync(-1000))
        
        subtitle_sync_menu.addSeparator()
        
        reset_sync = subtitle_sync_menu.addAction("Reset Sync")
        reset_sync.triggered.connect(lambda: self.parent.reset_subtitle_sync())
        
        self.context_menu.addSeparator()
        
        # Open file
        open_action = self.context_menu.addAction("Open File...")
        open_action.triggered.connect(self.parent.open_file)
        
        self.context_menu.addSeparator()
        
        # Previous/Next video
        prev_action = self.context_menu.addAction("Previous Video")
        prev_action.triggered.connect(lambda: self.parent.play_previous())
        next_action = self.context_menu.addAction("Next Video")
        next_action.triggered.connect(lambda: self.parent.play_next())
        
        self.context_menu.addSeparator()
        
        # Seek controls
        seek_menu = self.context_menu.addMenu("Seek")
        back_10 = seek_menu.addAction("Back 10 seconds")
        back_10.triggered.connect(lambda: self.parent.seek_relative(-10))
        forward_10 = seek_menu.addAction("Forward 10 seconds")
        forward_10.triggered.connect(lambda: self.parent.seek_relative(10))
        back_30 = seek_menu.addAction("Back 30 seconds")
        back_30.triggered.connect(lambda: self.parent.seek_relative(-30))
        forward_30 = seek_menu.addAction("Forward 30 seconds")
        forward_30.triggered.connect(lambda: self.parent.seek_relative(30))

    def update_audio_tracks(self):
        """Update the audio tracks submenu with available tracks"""
        if not self.audio_tracks_menu:
            return
            
        # Clear existing items
        self.audio_tracks_menu.clear()
        
        if not self.parent.has_media:
            no_tracks = self.audio_tracks_menu.addAction("No Audio Tracks")
            no_tracks.setEnabled(False)
            return

        # Get current track and count
        current = self.parent.media_player.audio_get_track()
        count = self.parent.media_player.audio_get_track_count()
        
        print(f"\nAudio track count: {count}")
        print(f"Current audio track: {current}")
        
        if count <= 0:
            no_tracks = self.audio_tracks_menu.addAction("No Audio Tracks")
            no_tracks.setEnabled(False)
            return

        # Get track descriptions from media player
        descriptions = self.parent.media_player.audio_get_track_description()
        print(f"Track descriptions: {descriptions}")
        
        # Add tracks
        tracks = []
        
        for i in range(count):
            name = f"Track {i + 1}"
            
            # Try to get description from media player
            if descriptions and i < len(descriptions):
                track_id, desc = descriptions[i]
                # Skip track -1 (Disable)
                if track_id == -1:
                    continue
                if desc:
                    try:
                        desc = desc.decode('utf-8') if isinstance(desc, bytes) else str(desc)
                        if desc and desc != str(i):  # Only use description if it's meaningful
                            # Extract just the language or description part
                            parts = desc.split('-')
                            if len(parts) > 1:
                                # Take the last part which usually contains the language
                                cleaned_desc = parts[-1].strip()
                            else:
                                cleaned_desc = desc
                            # Remove any "Track N" patterns
                            if not cleaned_desc.lower().startswith('track'):
                                name = f"Track {i + 1} ({cleaned_desc})"
                    except:
                        pass
            
            tracks.append({"id": i, "name": name})

        # Add tracks to menu
        for track in tracks:
            action = self.audio_tracks_menu.addAction(track["name"])
            action.setCheckable(True)
            action.setData(track["id"])
            if track["id"] == current:
                action.setChecked(True)
            self.audio_track_group.addAction(action)
            print(f"Added audio track: {track['name']}")

    def update_subtitle_tracks(self):
        """Update the subtitle tracks submenu with available tracks"""
        if not self.subtitle_tracks_menu:
            return
            
        # Clear existing items
        self.subtitle_tracks_menu.clear()
        for action in self.subtitle_track_group.actions():
            self.subtitle_track_group.removeAction(action)

        if not self.parent.has_media:
            no_tracks = self.subtitle_tracks_menu.addAction("No Subtitles")
            no_tracks.setEnabled(False)
            return

        # Get current track and count
        current = self.parent.media_player.video_get_spu()
        count = self.parent.media_player.video_get_spu_count()
        
        print(f"\nSubtitle track count: {count}")
        print(f"Current subtitle track: {current}")

        # Add disable subtitles option
        disable_action = QAction("Disabled", self)
        disable_action.setCheckable(True)
        disable_action.setData(-1)
        if current == -1:
            disable_action.setChecked(True)
        self.subtitle_track_group.addAction(disable_action)
        self.subtitle_tracks_menu.addAction(disable_action)

        if count <= 0:
            return

        # Get track descriptions
        descriptions = self.parent.media_player.video_get_spu_description()
        print(f"Subtitle descriptions: {descriptions}")
        
        if descriptions:
            # Add each track from descriptions
            for desc in descriptions:
                track_id, name = desc
                # Skip track -1 (Disable)
                if track_id == -1:
                    continue
                    
                try:
                    name = name.decode('utf-8') if isinstance(name, bytes) else str(name)
                    print(f"Adding subtitle track {track_id}: {name}")
                    
                    # Create track name
                    track_name = f"Track {track_id}"
                    if name and name != str(track_id):
                        track_name = f"Track {track_id} ({name})"
                    
                    action = QAction(track_name, self)
                    action.setCheckable(True)
                    action.setData(track_id)  # Use actual track ID from description
                    if track_id == current:
                        action.setChecked(True)
                    self.subtitle_track_group.addAction(action)
                    self.subtitle_tracks_menu.addAction(action)
                except Exception as e:
                    print(f"Error adding subtitle track {track_id}: {str(e)}")
        else:
            # Fallback to numeric tracks if no descriptions
            for i in range(count):
                # Skip track -1 (Disable)
                if i == -1:
                    continue
                    
                track_name = f"Track {i}"
                action = QAction(track_name, self)
                action.setCheckable(True)
                action.setData(i)
                if i == current:
                    action.setChecked(True)
                self.subtitle_track_group.addAction(action)
                self.subtitle_tracks_menu.addAction(action)
                print(f"Added fallback subtitle track {i}")

    def on_audio_track_changed(self, action):
        """Handle audio track selection"""
        track_id = action.data()
        print(f"\nAttempting to switch to audio track: {track_id}")
        success = self.parent.media_player.audio_set_track(track_id)
        print(f"Track switch {'successful' if success else 'failed'}")
        
        if success:
            # Update menu to show current selection
            self.update_audio_tracks()

    def on_subtitle_track_changed(self, action):
        """Handle subtitle track selection"""
        track_id = action.data()
        print(f"\nAttempting to change subtitle track to: {track_id}")
        
        try:
            # Get current track before change
            old_track = self.parent.media_player.video_get_spu()
            print(f"Current track before change: {old_track}")
            
            # Try to set the new track
            success = self.parent.change_subtitle_track(track_id)
            
            # Get track after change
            new_track = self.parent.media_player.video_get_spu()
            print(f"Track after change attempt: {new_track}")
            
            if success == 0:  # VLC returns 0 on success
                print(f"Successfully changed subtitle track to: {track_id}")
                # Update the menu to reflect the change
                self.update_subtitle_tracks()
            else:
                print(f"Failed to change subtitle track. Return code: {success}")
        except Exception as e:
            print(f"Error changing subtitle track: {str(e)}")

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.parent:
            event.accept()
            self.parent.toggle_play()
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
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

    def keyPressEvent(self, event: QKeyEvent):
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
            # Increase volume directly
            current_volume = self.parent.volume_slider.value()
            new_volume = max(0, min(100, current_volume + 5))
            if new_volume != current_volume:
                self.parent.volume_slider.setValue(new_volume)
                self.parent.media_player.audio_set_volume(new_volume)
                self.parent.show_volume_overlay()
            event.accept()
        elif event.key() == Qt.Key.Key_Down:
            # Decrease volume directly
            current_volume = self.parent.volume_slider.value()
            new_volume = max(0, min(100, current_volume - 5))
            if new_volume != current_volume:
                self.parent.volume_slider.setValue(new_volume)
                self.parent.media_player.audio_set_volume(new_volume)
                self.parent.show_volume_overlay()
            event.accept()
        elif event.key() == Qt.Key.Key_Left:
            self.parent.seek_relative(-10)  # Seek backward 10 seconds
            event.accept()
        elif event.key() == Qt.Key.Key_Right:
            self.parent.seek_relative(10)   # Seek forward 10 seconds
            event.accept()
        elif event.key() == Qt.Key.Key_M and not event.isAutoRepeat():
            self.parent.toggle_mute()
            event.accept()
        elif event.key() == Qt.Key.Key_PageUp:
            self.parent.play_previous()  # Go to previous video
            event.accept()
        elif event.key() == Qt.Key.Key_PageDown:
            self.parent.play_next()  # Go to next video
            event.accept()
        elif event.key() == Qt.Key.Key_A and not event.isAutoRepeat():
            self.parent.cycle_audio_track()  # Cycle to next audio track
            event.accept()
        elif event.key() == Qt.Key.Key_S and not event.isAutoRepeat():
            # Toggle subtitles on/off
            try:
                current = self.parent.media_player.video_get_spu()
                count = self.parent.media_player.video_get_spu_count()
                
                if count > 0:  # Only toggle if there are subtitle tracks available
                    if current == -1:  # If subtitles are off
                        # Get track descriptions to find first valid track
                        descriptions = self.parent.media_player.video_get_spu_description()
                        valid_track = None
                        
                        if descriptions:
                            for track_id, name in descriptions:
                                if track_id != -1:  # Skip the disable track
                                    valid_track = track_id
                                    # Get track name for display
                                    try:
                                        track_name = name.decode('utf-8') if isinstance(name, bytes) else str(name)
                                        if track_name and track_name != str(track_id):
                                            self.parent.show_title_overlay(f"Subtitles: Track {track_id} ({track_name})")
                                        else:
                                            self.parent.show_title_overlay(f"Subtitles: Track {track_id}")
                                    except:
                                        self.parent.show_title_overlay(f"Subtitles: Track {track_id}")
                                    break
                        
                        if valid_track is not None:
                            success = self.parent.media_player.video_set_spu(valid_track)
                            if success == 0:  # VLC returns 0 on success
                                print(f"Subtitles enabled on track {valid_track}")
                            else:
                                print(f"Failed to enable subtitles on track {valid_track}")
                        else:
                            self.parent.show_title_overlay("No valid subtitle tracks")
                            print("No valid subtitle tracks")
                    else:  # If subtitles are on
                        # Disable subtitles
                        success = self.parent.media_player.video_set_spu(-1)
                        if success == 0:  # VLC returns 0 on success
                            self.parent.show_title_overlay("Subtitles: Disabled")
                            print("Subtitles disabled")
                        else:
                            print("Failed to disable subtitles")
                else:
                    self.parent.show_title_overlay("No subtitle tracks available")
                    print("No subtitle tracks available")
            except Exception as e:
                print(f"Error toggling subtitles: {e}")
            event.accept()
        else:
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        super().mouseMoveEvent(event)
        
        if isinstance(self.parent, QMainWindow):
            # Get the cursor position relative to the main window
            cursor_pos = event.pos()
            local_y = cursor_pos.y()
            window_height = self.parent.height()
            
            # Calculate the control areas
            top_area_height = 30  # Height of titlebar
            timeline_area_height = 40  # Height of timeline
            
            # Show/hide cursor based on position
            if local_y <= top_area_height or window_height - local_y <= timeline_area_height:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.BlankCursor)
            
            # Only hide controls in fullscreen mode
            if self.parent.isFullScreen():
                if local_y <= top_area_height:
                    self.parent.top_control_container.show()
                else:
                    self.parent.top_control_container.hide()
                    
                if window_height - local_y <= timeline_area_height:
                    self.parent.timeline_container.show()
                else:
                    self.parent.timeline_container.hide()

    def on_right_click_hold(self):
        """Called when right button is held for more than 200ms"""
        self.show_context = False  # Disable context menu for hold

    def on_middle_click_hold(self):
        """Called when middle button is held for 1 second"""
        try:
            self.parent.toggle_subtitles()  # Use new toggle_subtitles method
        except Exception as e:
            print(f"Error in middle click hold: {e}")

    def keyPressEvent(self, event: QKeyEvent):
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
            # Increase volume directly
            current_volume = self.parent.volume_slider.value()
            new_volume = max(0, min(100, current_volume + 5))
            if new_volume != current_volume:
                self.parent.volume_slider.setValue(new_volume)
                self.parent.media_player.audio_set_volume(new_volume)
                self.parent.show_volume_overlay()
            event.accept()
        elif event.key() == Qt.Key.Key_Down:
            # Decrease volume directly
            current_volume = self.parent.volume_slider.value()
            new_volume = max(0, min(100, current_volume - 5))
            if new_volume != current_volume:
                self.parent.volume_slider.setValue(new_volume)
                self.parent.media_player.audio_set_volume(new_volume)
                self.parent.show_volume_overlay()
            event.accept()
        elif event.key() == Qt.Key.Key_Left:
            self.parent.seek_relative(-10)  # Seek backward 10 seconds
            event.accept()
        elif event.key() == Qt.Key.Key_Right:
            self.parent.seek_relative(10)   # Seek forward 10 seconds
            event.accept()
        elif event.key() == Qt.Key.Key_M and not event.isAutoRepeat():
            self.parent.toggle_mute()
            event.accept()
        elif event.key() == Qt.Key.Key_PageUp:
            self.parent.play_previous()  # Go to previous video
            event.accept()
        elif event.key() == Qt.Key.Key_PageDown:
            self.parent.play_next()  # Go to next video
            event.accept()
        elif event.key() == Qt.Key.Key_A and not event.isAutoRepeat():
            self.parent.cycle_audio_track()  # Cycle to next audio track
            event.accept()
        elif event.key() == Qt.Key.Key_S and not event.isAutoRepeat():
            self.parent.toggle_subtitles()  # Use new toggle_subtitles method
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        
        # Only draw logo if no media is playing
        if not self.parent.has_media:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # Set font for logo
            painter.setFont(self.logo_font)
            
            # Calculate text size
            text_rect = painter.fontMetrics().boundingRect(self.logo_text)
            
            # Calculate center position
            x = (self.width() - text_rect.width()) // 2
            y = (self.height() - text_rect.height()) // 2
            
            # Draw text shadow (more subtle)
            painter.setPen(QPen(QColor(0, 0, 0, 60)))  # More transparent shadow
            painter.drawText(x + 1, y + text_rect.height() + 1, self.logo_text)  # Reduced shadow offset
            
            # Draw main text with darker, more subtle gray
            painter.setPen(QPen(QColor(100, 100, 100)))  # Darker gray for minimalistic look
            painter.drawText(x, y + text_rect.height(), self.logo_text)

class StrokedLabel(QLabel):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw text with stroke
        pen = QPen(Qt.GlobalColor.black, 4)  # Increased stroke width further
        painter.setPen(pen)
        
        # Draw text outline (stroke) in 8 directions
        x = 5  # Starting x position
        y = self.height() // 2 + 10  # Vertical center
        
        # Increased offset for maximum visibility
        offsets = [(-3,-3), (0,-3), (3,-3),
                  (-3,0),          (3,0),
                  (-3,3),  (0,3),  (3,3),
                  # Additional diagonal offsets for thicker corners
                  (-2,-2), (2,-2),
                  (-2,2),  (2,2)]
                  
        for dx, dy in offsets:
            painter.drawText(x + dx, y + dy, self.text())
            
        # Draw the main text in cyan
        painter.setPen(QColor("#00FFFF"))
        painter.drawText(x, y, self.text())

class OniPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OniPlayer")
        
        # Set window icon
        icon_path = os.path.join(base_dir, 'icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        


        # Create audio track overlay
        self.audio_track_overlay = StrokedLabel()
        self.audio_track_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.audio_track_overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.audio_track_overlay.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
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

        # Timer for hiding audio track overlay
        self.audio_track_overlay_timer = QTimer(self)
        self.audio_track_overlay_timer.setSingleShot(True)
        self.audio_track_overlay_timer.timeout.connect(self.hide_audio_track_overlay)

        # Remove default window frame
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet("""
            QMainWindow {
                background-color: black;
            }
        """)
        
        # Create top control container first
        self.top_control_container = QWidget()
        self.top_control_container.setObjectName("topControlContainer")
        self.top_control_container.setFixedHeight(30)
        self.top_control_container.setStyleSheet("""
            #topControlContainer {
                background-color: #1A1A1A;
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
                font-family: "Segoe UI";
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
        self.timeline_container.setStyleSheet("""
            #timelineContainer {
                background-color: #1A1A1A;
            }
        """)
        
        # Create central widget and main layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)  # Set margins to 0 initially for fullscreen
        self.main_layout.setSpacing(0)
        
        # Create video container widget
        self.video_container = QWidget()
        self.video_layout = QVBoxLayout(self.video_container)
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_layout.setSpacing(0)
        
        # Create video frame
        self.video_frame = VideoFrame(self)
        self.video_frame.setStyleSheet("background-color: black;")
        self.video_layout.addWidget(self.video_frame)
        
        # Set video container and frame to expand
        self.video_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Create overlays first
        # Create volume indicator overlay
        self.volume_overlay = StrokedLabel()
        self.volume_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.volume_overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.volume_overlay.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)  
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
        self.title_overlay.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)  
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
        
        # Set up floating controls
        self.top_control_container.setParent(self)
        self.timeline_container.setParent(self)
        
        # Make controls stay on top
        self.top_control_container.raise_()
        self.timeline_container.raise_()
        
        # Stack the controls on top of video
        self.main_layout.addWidget(self.video_container)
        
        # Set initial window size
        self.resize(1024, 768)
        
        # Show window first
        self.show()
        
        # Now update control positions after window is shown
        self.update_control_positions()
        
        # Timeline container layout
        timeline_layout = QHBoxLayout(self.timeline_container)
        timeline_layout.setContentsMargins(10, 0, 5, 0)  # Reduced right margin
        timeline_layout.setSpacing(5)  # Reduced spacing
        
        # Play button in timeline
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
        volume_layout.setSpacing(2)  # Reduced spacing
        
        # Volume icon button
        self.volume_button = QPushButton()
        self.volume_button.setFixedSize(28, 28)  # Reduced from 32x32
        self.volume_button.setStyleSheet(TIMELINE_BUTTON_STYLE)
        self.volume_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolume, size=18))
        self.volume_button.clicked.connect(self.toggle_mute)
        volume_layout.addWidget(self.volume_button)
        
        # Volume slider
        self.volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setFixedWidth(80)  # Increased from 40 to 80
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
        self.volume_slider.setValue(60)  # Set default to 60%
        self.volume_slider.valueChanged.connect(self.on_volume_change)
        self.volume_slider.sliderMoved.connect(self.on_volume_change)  # Add this line to update while dragging
        volume_layout.addWidget(self.volume_slider)
        
        # Time labels with more compact styling
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                background: transparent;
                font-size: 11px;
                min-width: 70px;
                padding: 0px;
                margin: 0px;
            }
        """)

        # Create time layout
        time_layout = QHBoxLayout()
        time_layout.addWidget(self.time_label)
        
        # Add widgets to timeline layout
        timeline_layout.addWidget(self.timeline)
        timeline_layout.addLayout(time_layout)
        timeline_layout.addLayout(volume_layout)
        
        # Create control containers with overlay behavior
        
        # Create top control layout and add widgets
        top_control_layout = QHBoxLayout(self.top_control_container)
        top_control_layout.setContentsMargins(0, 0, 0, 0)
        top_control_layout.setSpacing(0)
        
        # Add title label
        self.title_label = QLabel("OniPlayer")
        self.title_label.setStyleSheet("""
            QLabel {
                color: white;
                font-family: "Segoe UI";
                font-size: 12px;
                padding-left: 10px;
            }
        """)
        top_control_layout.addWidget(self.title_label)
        
        # Add spacer to push buttons to the right
        top_control_layout.addStretch()
        
        # Create window control buttons
        self.minimize_button = QPushButton("─")
        self.maximize_button = QPushButton("□")
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("closeButton")
        
        # Add buttons to layout
        top_control_layout.addWidget(self.minimize_button)
        top_control_layout.addWidget(self.maximize_button)
        top_control_layout.addWidget(self.close_button)
        
        # Connect button signals
        self.minimize_button.clicked.connect(self.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximize)
        self.close_button.clicked.connect(self.close)
        
        # Enable drag and drop
        self.setAcceptDrops(True)
        
        # Create VLC instance with plugins path and proper video output settings
        instance_args = ['--no-sub-autodetect-file']  # Disable automatic subtitle loading
        self.instance = vlc.Instance(instance_args)
        self.media_player = self.instance.media_player_new()
        
        # Set default volume to 60 and ensure it's not muted
        self.media_player.audio_set_volume(60)
        self.media_player.audio_set_mute(False)
        
        # Initialize subtitle sync delay
        self.subtitle_delay = 0
        
        # Store last playback position and current index
        self.last_position = 0
        self.current_index = 0
        
        # Set up event manager for end of media
        self.event_manager = self.media_player.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self.on_media_end)
        self.event_manager.event_attach(vlc.EventType.MediaPlayerLengthChanged, self.on_length_changed)
        self.event_manager.event_attach(vlc.EventType.MediaPlayerMediaChanged, self.on_media_changed)
        
        # Set additional media player options
        self.media_player.video_set_mouse_input(False)
        self.media_player.video_set_key_input(False)
        
        # Timer for hiding overlays
        self.volume_overlay_timer = QTimer(self)
        self.volume_overlay_timer.setSingleShot(True)
        self.volume_overlay_timer.timeout.connect(self.hide_volume_overlay)
        
        self.title_overlay_timer = QTimer(self)
        self.title_overlay_timer.setSingleShot(True)
        self.title_overlay_timer.timeout.connect(self.hide_title_overlay)
        
        # Set up update timer
        self.timer = QTimer(self)
        self.timer.setInterval(100)  # Update every 100ms
        self.timer.timeout.connect(self.update_ui)
        
        # Set minimum size
        self.setMinimumSize(800, 600)
        
        # Set initial volume and media state
        self.playlist = []
        self.current_file = None
        self.has_media = False
        self.is_muted = False
        self.last_volume = 60  # Store last volume before mute
        
        # Set focus to video frame for keyboard events
        self.video_frame.setFocus()
        
        # Add this near the start of __init__ after super().__init__()
        # Store last used subtitle track
        self.last_subtitle_track = None

    def change_subtitle_track(self, track_id):
        try:
            if track_id == -1:  # No subtitle
                self.media_player.video_set_spu(-1)
                return True
            
            # Get all subtitle tracks
            spu_count = self.media_player.video_get_spu_count()
            if spu_count > 0:
                # Set the selected track
                success = self.media_player.video_set_spu(track_id)
                if success == 0:  # VLC returns 0 on success
                    # Remember this track if it's not -1
                    if track_id != -1:
                        self.last_subtitle_track = track_id
                print(f"Changed subtitle track to {track_id}, success: {success}")
                return success
            return False
        except Exception as e:
            print(f"Error changing subtitle track: {e}")
            return False

    def toggle_subtitles(self):
        """Toggle subtitles between off and last used track"""
        try:
            current = self.media_player.video_get_spu()
            count = self.media_player.video_get_spu_count()
            
            if count > 0:  # Only toggle if there are subtitle tracks available
                if current == -1:  # If subtitles are off
                    # Try to use last known track first
                    if self.last_subtitle_track is not None:
                        success = self.media_player.video_set_spu(self.last_subtitle_track)
                        if success == 0:  # VLC returns 0 on success
                            # Get track name for display
                            descriptions = self.media_player.video_get_spu_description()
                            track_name = f"Subtitles: Track {self.last_subtitle_track + 1}"
                            if descriptions:
                                for track_id, name in descriptions:
                                    if track_id == self.last_subtitle_track:
                                        try:
                                            name = name.decode('utf-8') if isinstance(name, bytes) else str(name)
                                            if name and name != str(track_id):
                                                track_name = f"Subtitles: Track {track_id + 1} ({name})"
                                        except:
                                            pass
                            self.show_title_overlay(track_name)
                            return
                    
                    # If no last track or failed to set it, find first available track
                    descriptions = self.media_player.video_get_spu_description()
                    valid_track = None
                    
                    if descriptions:
                        for track_id, name in descriptions:
                            if track_id != -1:  # Skip the disable track
                                valid_track = track_id
                                # Remember this track
                                self.last_subtitle_track = track_id
                                # Get track name for display
                                try:
                                    track_name = name.decode('utf-8') if isinstance(name, bytes) else str(name)
                                    if track_name and track_name != str(track_id):
                                        self.show_title_overlay(f"Subtitles: Track {track_id + 1} ({track_name})")
                                    else:
                                        self.show_title_overlay(f"Subtitles: Track {track_id + 1}")
                                except:
                                    self.show_title_overlay(f"Subtitles: Track {track_id + 1}")
                                break
                    
                    if valid_track is not None:
                        success = self.media_player.video_set_spu(valid_track)
                        if success == 0:  # VLC returns 0 on success
                            print(f"Subtitles enabled on track {valid_track}")
                        else:
                            print(f"Failed to enable subtitles on track {valid_track}")
                    else:
                        self.show_title_overlay("No valid subtitle tracks")
                        print("No valid subtitle tracks")
                else:  # If subtitles are on
                    # Remember current track before disabling
                    self.last_subtitle_track = current
                    # Disable subtitles
                    success = self.media_player.video_set_spu(-1)
                    if success == 0:  # VLC returns 0 on success
                        self.show_title_overlay("Subtitles: Disabled")
                        print("Subtitles disabled")
                    else:
                        print("Failed to disable subtitles")
            else:
                self.show_title_overlay("No subtitle tracks available")
                print("No subtitle tracks available")
        except Exception as e:
            print(f"Error toggling subtitles: {e}")

    def update_subtitle_menu(self):
        try:
            self.subtitle_menu.clear()
            
            # Add "No Subtitle" option
            no_sub_action = QAction("No Subtitle", self)
            no_sub_action.triggered.connect(lambda: self.change_subtitle_track(-1))
            self.subtitle_menu.addAction(no_sub_action)
            
            # Add separator
            self.subtitle_menu.addSeparator()
            
            # Get available subtitle tracks
            spu_count = self.media_player.video_get_spu_count()
            if spu_count > 0:
                descriptions = self.media_player.video_get_spu_description()
                for i in range(spu_count):
                    track_name = f"Subtitle Track {i+1}"
                    if descriptions and i < len(descriptions):
                        desc = descriptions[i][1]
                        if isinstance(desc, bytes):
                            track_name = desc.decode('utf-8', errors='replace')
                        else:
                            track_name = str(desc)
                    
                    action = QAction(track_name, self)
                    action.triggered.connect(lambda x, tid=i: self.change_subtitle_track(tid))
                    self.subtitle_menu.addAction(action)
                    print(f"Added subtitle track: {track_name}")
        except Exception as e:
            print(f"Error updating subtitle menu: {e}")

    def on_media_end(self, event):
        # Set has_media to False before playing next
        self.has_media = False
        self.video_frame.update()  # Force update to show logo
        
        # This is called from a different thread, so we need to use a timer
        # to ensure we're in the main thread when playing the next video
        QTimer.singleShot(0, self.play_next)

    def on_length_changed(self, event):
        # Update timeline maximum when media length is available
        length = self.media_player.get_length()
        if length > 0:
            self.timeline.setMaximum(length)

    def on_media_changed(self, event):
        """Handle media changed event and update window size"""
        print("Media changed event received")
        # Add a very short delay to ensure media is initialized
        QTimer.singleShot(100, self.adjust_window_to_video_size)
        QTimer.singleShot(200, self.refresh_cursor)

    def refresh_cursor(self):
        """Force the OS to refresh the cursor over the video frame"""
        try:
            # Map current global mouse position to video_frame coordinates
            local_pos = self.video_frame.mapFromGlobal(self.cursor().pos())
            local_y = local_pos.y()
            window_height = self.height()
            
            top_area_height = 30
            timeline_area_height = 40
            
            # Temporarily set cursor to ArrowCursor to break the busy/stuck cursor state
            self.video_frame.setCursor(Qt.CursorShape.ArrowCursor)
            
            # Then restore the correct cursor (Arrow or Blank) based on position
            if local_y <= top_area_height or window_height - local_y <= timeline_area_height:
                QTimer.singleShot(50, lambda: self.video_frame.setCursor(Qt.CursorShape.ArrowCursor))
            else:
                QTimer.singleShot(50, lambda: self.video_frame.setCursor(Qt.CursorShape.BlankCursor))
        except Exception as e:
            print(f"Error refreshing cursor: {e}")

    def play_next(self):
        try:
            if not self.playlist or len(self.playlist) <= 1:
                # Stop playback and reset media
                self.media_player.stop()
                self.has_media = False
                self.current_file = None
                # Reset UI elements
                self.timeline.setValue(0)
                self.time_label.setText("0:00 / 0:00")
                self.title_label.setText("OniPlayer")
                self.play_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaPlay))
                self.video_frame.update()  # Force update to show logo
                return
                
            # Store current position as percentage and fullscreen state
            was_fullscreen = self.isFullScreen()
            if self.has_media:
                length = self.media_player.get_length()
                if length > 0:
                    self.last_position = self.media_player.get_position()
            
            # Check if we're at the end of the playlist
            next_index = self.current_index + 1
            if next_index >= len(self.playlist):
                # Stop playback and reset media
                self.media_player.stop()
                self.has_media = False
                self.current_file = None
                # Reset UI elements
                self.timeline.setValue(0)
                self.time_label.setText("0:00 / 0:00")
                self.title_label.setText("OniPlayer")
                self.play_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaPlay))
                self.video_frame.update()  # Force update to show logo
                return
            
            # Play next file
            self.current_index = next_index
            next_file = self.playlist[self.current_index]
            
            print(f"Playing next: Current index={self.current_index}")
            self.play_file(next_file)
            
            # Restore fullscreen state if needed
            if was_fullscreen and not self.isFullScreen():
                QTimer.singleShot(100, self.toggle_fullscreen)
            
        except Exception as e:
            print(f"Error playing next file: {e}")

    def play_previous(self):
        try:
            if not self.playlist or len(self.playlist) <= 1:
                return
                
            # Store current position as percentage and fullscreen state
            was_fullscreen = self.isFullScreen()
            if self.has_media:
                length = self.media_player.get_length()
                if length > 0:
                    self.last_position = self.media_player.get_position()
            
            # Calculate previous index
            self.current_index = (self.current_index - 1) % len(self.playlist)
            prev_file = self.playlist[self.current_index]
            
            print(f"Playing previous: Current index={self.current_index}")
            self.play_file(prev_file)
            
            # Restore fullscreen state if needed
            if was_fullscreen and not self.isFullScreen():
                QTimer.singleShot(100, self.toggle_fullscreen)
            
        except Exception as e:
            print(f"Error playing previous file: {e}")

    def update_playlist(self, filepath):
        """Update playlist with all video files in the same directory"""
        # Normalize the input filepath
        filepath = os.path.normpath(filepath)
        self.current_directory = os.path.dirname(filepath)
        video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv'}
        
        # Get all video files in the directory and normalize their paths
        self.playlist = [
            os.path.normpath(os.path.join(self.current_directory, f))
            for f in os.listdir(self.current_directory)
            if os.path.splitext(f)[1].lower() in video_extensions
        ]
        
        # Sort the playlist
        self.playlist.sort()
        
        # Make sure current file is in playlist
        if filepath not in self.playlist:
            self.playlist.append(filepath)
            self.playlist.sort()
        
        # Set current file and its index
        self.current_file = filepath
        self.current_index = self.playlist.index(filepath)

    def adjust_volume(self, delta):
        """Adjust volume by delta and update UI accordingly"""
        current_volume = self.volume_slider.value()
        new_volume = max(0, min(100, current_volume + delta))
        if new_volume != current_volume:
            # Update slider and set volume directly to VLC player
            self.volume_slider.setValue(new_volume)
            self.media_player.audio_set_volume(new_volume)
            self.show_volume_overlay()

    def seek_relative(self, seconds):
        """Seek relative to current position"""
        if not self.has_media:
            return
            
        current_time = self.media_player.get_time()  # Current time in milliseconds
        new_time = current_time + (seconds * 1000)  # Convert seconds to milliseconds
        
        # Ensure we don't seek beyond the media length
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
            self.adjust_volume(5)  # Increase volume by 5%
            event.accept()
        elif event.key() == Qt.Key.Key_Down:
            self.adjust_volume(-5)  # Decrease volume by 5%
            event.accept()
        elif event.key() == Qt.Key.Key_Left:
            self.seek_relative(-10)  # Seek backward 10 seconds
            event.accept()
        elif event.key() == Qt.Key.Key_Right:
            self.seek_relative(10)   # Seek forward 10 seconds
            event.accept()
        elif event.key() == Qt.Key.Key_M and not event.isAutoRepeat():
            self.toggle_mute()
            event.accept()
        elif event.key() == Qt.Key.Key_PageUp:
            self.play_previous()  # Go to previous video
            event.accept()
        elif event.key() == Qt.Key.Key_PageDown:
            self.play_next()  # Go to next video
            event.accept()
        elif event.key() == Qt.Key.Key_A and not event.isAutoRepeat():
            self.cycle_audio_track()  # Cycle to next audio track
            event.accept()
        elif event.key() == Qt.Key.Key_S and not event.isAutoRepeat():
            self.toggle_subtitles()  # Use new toggle_subtitles method
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        # Cleanup VLC objects
        self.media_player.stop()
        self.media_player.release()
        self.instance.release()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # Set focus to video frame when window is shown
        self.video_frame.setFocus()

    def moveEvent(self, event):
        super().moveEvent(event)
        # Update overlay positions when window moves
        self.update_title_overlay_position()
        self.update_volume_overlay_position()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            # Show title overlay with the dragged filename
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
                
            print(f"\nLoading file: {filename}")
            # Update playlist when playing a new file
            self.update_playlist(filename)
            
            media = self.instance.media_new(filename)
            print("Created new media instance")
            
            # Parse media information to get tracks and video size
            media.parse()
            print("Started media parsing")
            
            self.media_player.set_media(media)
            print("Set media to media player")
            
            if sys.platform.startswith('win'):
                try:
                    self.media_player.set_hwnd(int(self.video_frame.winId()))
                    print("Set window handle for Windows")
                except Exception as e:
                    print(f"Error setting window handle: {e}")
                    return
            
            self.has_media = True
            self.current_file = filename
            
            # Try to adjust window size immediately
            self.adjust_window_to_video_size()
            
            # Start playback
            self.toggle_play()
            
            # Force cursor refresh to clear any stuck busy cursor
            QTimer.singleShot(200, self.refresh_cursor)
            
            # Set the position after a short delay to ensure media is loaded
            if self.last_position > 0:
                QTimer.singleShot(100, lambda: self.media_player.set_position(self.last_position))
                self.last_position = 0  # Reset last position
            
            # Update window title and show title overlay
            filename_display = os.path.basename(filename)
            self.setWindowTitle(f"OniPlayer - {filename_display}")
            self.title_label.setText(filename_display)
            self.show_title_overlay(filename_display)
            
            print("Media loading complete")
        except Exception as e:
            print(f"Error loading file {filename}: {e}")

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
            # Save current window state
            self.prev_geometry = self.geometry()
            # Remove margins in fullscreen
            self.main_layout.setContentsMargins(0, 0, 0, 0)
            self.showFullScreen()
            # Hide controls initially in fullscreen
            self.top_control_container.hide()
            self.timeline_container.hide()
            # Ensure controls span full width
            self.update_control_positions()
        else:
            self.showNormal()
            # Restore window geometry
            if hasattr(self, 'prev_geometry'):
                self.setGeometry(self.prev_geometry)
            # Show controls in normal mode
            self.top_control_container.show()
            self.timeline_container.show()
            # Restore margins in windowed mode
            self.main_layout.setContentsMargins(0, 30, 0, 40)
            # Update control positions
            self.update_control_positions()

    def set_position(self, position):
        if self.has_media:
            self.media_player.set_time(position)
            # Update time display immediately when dragging
            if position >= 0:  # Only update if we get a valid time
                total_seconds = position / 1000
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                seconds = int(total_seconds % 60)
                
                if hours > 0:
                    time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    time_str = f"{minutes:02d}:{seconds:02d}"

                # Get duration for complete display
                length = self.media_player.get_length()
                if length > 0:
                    total_seconds = length / 1000
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    seconds = int(total_seconds % 60)

                    if hours > 0:
                        duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                    else:
                        duration_str = f"{minutes:02d}:{seconds:02d}"

                    self.time_label.setText(f"{time_str} / {duration_str}")
                else:
                    self.time_label.setText(f"{time_str} / 0:00")
                
    def update_time_display(self, current_time):
        """Update the time display labels based on the given time in milliseconds"""
        if current_time >= 0:
            total_seconds = current_time / 1000
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            seconds = int(total_seconds % 60)
            
            if hours > 0:
                time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                time_str = f"{minutes:02d}:{seconds:02d}"

            # Update duration label with hours
            length = self.media_player.get_length()
            if length > 0:
                total_seconds = length / 1000
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                seconds = int(total_seconds % 60)

                if hours > 0:
                    duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = f"{minutes:02d}:{seconds:02d}"

                self.time_label.setText(f"{time_str} / {duration_str}")
            else:
                self.time_label.setText(f"{time_str} / 0:00")

    def set_volume(self, volume):
        """Set the volume of the media player"""
        try:
            self.media_player.audio_set_mute(False)  # Always unmute when changing volume
            self.media_player.audio_set_volume(volume)
            
            # Update mute state and icon if volume changes
            if volume > 0 and self.is_muted:
                self.is_muted = False
                self.volume_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolume, size=18))
            elif volume == 0 and not self.is_muted:
                self.is_muted = True
                self.volume_button.setIcon(timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolumeMuted, size=18))
        except Exception as e:
            print(f"Error setting volume: {str(e)}")

    def update_ui(self):
        if not self.has_media:
            return
            
        try:
            if self.media_player and self.media_player.is_playing():
                current_time = self.media_player.get_time()
                if current_time >= 0:  # Only update if we get a valid time
                    self.timeline.setValue(current_time)
                    self.update_time_display(current_time)
        except Exception:
            # Ignore any VLC errors during UI updates
            pass
        
    def open_file(self):
        dialog = QFileDialog()
        filename, _ = dialog.getOpenFileName(self, "Open Video",
                                           "",
                                           "Video Files (*.mp4 *.avi *.mkv *.mov *.wmv)")
        
        if filename:
            self.play_file(filename)

    def load_external_subtitle(self):
        """Load external subtitle file"""
        if not self.has_media:
            QMessageBox.warning(self, "Warning", "Please load a video file first.")
            return
            
        file_dialog = QFileDialog()
        subtitle_file, _ = file_dialog.getOpenFileName(
            self,
            "Select Subtitle File",
            "",
            "Subtitle Files (*.srt *.ass *.ssa *.vtt);;All Files (*.*)"
        )
        
        if subtitle_file:
            try:
                # Add subtitle file as media slave
                success = self.media_player.add_slave(
                    vlc.MediaSlaveType.subtitle,
                    subtitle_file.encode('utf-8'),
                    True
                )
                
                if success == 0:  # VLC returns 0 on success
                    print(f"Successfully loaded subtitle file: {subtitle_file}")
                    # Reset subtitle sync
                    self.subtitle_delay = 0
                    self.media_player.video_set_spu_delay(0)
                    # Update subtitle tracks menu
                    self.video_frame.update_subtitle_tracks()
                    # Try to automatically select the newly added subtitle track
                    count = self.media_player.video_get_spu_count()
                    if count > 0:
                        # Select the last track (usually the newly added one)
                        self.media_player.video_set_spu(count - 1)
                else:
                    QMessageBox.warning(self, "Error", "Failed to load subtitle file.")
            except Exception as e:
                print(f"Error loading subtitle file: {str(e)}")
                QMessageBox.warning(self, "Error", f"Failed to load subtitle file: {str(e)}")

    def adjust_subtitle_sync(self, ms):
        """Adjust subtitle synchronization by specified milliseconds"""
        if not self.has_media:
            return
            
        try:
            self.subtitle_delay += ms
            # VLC expects microseconds (1 millisecond = 1000 microseconds)
            delay_microseconds = self.subtitle_delay * 1000
            
            # Get current subtitle track
            current_track = self.media_player.video_get_spu()
            if current_track >= 0:  # Only adjust if subtitles are enabled
                success = self.media_player.video_set_spu_delay(delay_microseconds)
                if success == 0:  # VLC returns 0 on success
                    print(f"Subtitle delay adjusted to: {self.subtitle_delay}ms ({delay_microseconds} microseconds)")
                    # Show current delay in status bar
                    delay_str = f"+{self.subtitle_delay}ms" if self.subtitle_delay > 0 else f"{self.subtitle_delay}ms"
                    self.statusBar().showMessage(f"Subtitle delay: {delay_str}")
                else:
                    print("Failed to adjust subtitle delay")
            else:
                print("No subtitle track selected")
                self.statusBar().showMessage("Please select a subtitle track first")
        except Exception as e:
            print(f"Error adjusting subtitle sync: {str(e)}")

    def reset_subtitle_sync(self):
        """Reset subtitle synchronization to default"""
        if not self.has_media:
            return
            
        try:
            # Get current subtitle track
            current_track = self.media_player.video_get_spu()
            if current_track >= 0:  # Only reset if subtitles are enabled
                self.subtitle_delay = 0
                success = self.media_player.video_set_spu_delay(0)
                if success == 0:  # VLC returns 0 on success
                    print("Subtitle sync reset to 0ms")
                    self.statusBar().showMessage("Subtitle sync reset")
                else:
                    print("Failed to reset subtitle delay")
            else:
                print("No subtitle track selected")
                self.statusBar().showMessage("Please select a subtitle track first")
        except Exception as e:
            print(f"Error resetting subtitle sync: {str(e)}")

    def cycle_audio_track(self):
        """Cycle to the next audio track"""
        if not self.has_media:
            return
            
        try:
            # Get current track and count
            current = self.media_player.audio_get_track()
            count = self.media_player.audio_get_track_count()
            
            if count <= 1:  # No tracks or only one track
                print("No audio tracks to cycle through")
                return
                
            # Get track descriptions to find valid tracks
            descriptions = self.media_player.audio_get_track_description()
            valid_tracks = []
            
            if descriptions:
                for track_id, _ in descriptions:
                    if track_id != -1:  # Skip the disable track
                        valid_tracks.append(track_id)
            
            if not valid_tracks:
                print("No valid audio tracks found")
                return
                
            # Find current track index in valid tracks
            try:
                current_index = valid_tracks.index(current)
                # Calculate next track index
                next_index = (current_index + 1) % len(valid_tracks)
            except ValueError:
                # If current track not found in valid tracks, start from first valid track
                next_index = 0
            
            # Set the next track
            next_track = valid_tracks[next_index]
            success = self.media_player.audio_set_track(next_track)
            
            # Always show overlay with track info
            if descriptions:
                for track_id, desc in descriptions:
                    if track_id == next_track:
                        if desc:
                            try:
                                desc = desc.decode('utf-8') if isinstance(desc, bytes) else str(desc)
                                track_name = f"Audio: Track {next_track + 1} ({desc})"
                            except:
                                track_name = f"Audio: Track {next_track + 1}"
                        else:
                            track_name = f"Audio: Track {next_track + 1}"
                        break
            else:
                track_name = f"Audio: Track {next_track + 1}"
            
            # Show the track name in the title overlay
            self.show_title_overlay(track_name)
            
            # Update the menu if visible
            if hasattr(self.video_frame, "update_audio_tracks"):
                self.video_frame.update_audio_tracks()
                
        except Exception as e:
            print(f"Error cycling audio track: {e}")

    def cycle_subtitle_track(self):
        """Cycle to the next subtitle track"""
        if not self.has_media:
            return
            
        try:
            # Get current track and count
            current = self.media_player.video_get_spu()
            count = self.media_player.video_get_spu_count()
            
            if count == 0:  # No subtitle tracks
                print("No subtitle tracks to cycle through")
                return
                
            # Calculate next track index (-1 is disabled)
            # If current is -1 (disabled), go to track 0
            # Otherwise cycle to next track or back to -1 if at the end
            if current == -1:
                next_track = 0
            else:
                next_track = current + 1
                if next_track >= count:
                    next_track = -1  # Cycle back to disabled
            
            # Set the next track
            success = self.media_player.video_set_spu(next_track)
            
            # Show overlay with track info
            if success == 0:  # VLC returns 0 on success
                if next_track == -1:
                    track_name = "Subtitles: Disabled"
                else:
                    track_name = f"Subtitles: Track {next_track + 1}"
                self.show_title_overlay(track_name)
            
            # Update the menu if visible
            if hasattr(self.video_frame, "update_subtitle_tracks"):
                self.video_frame.update_subtitle_tracks()
                
        except Exception as e:
            print(f"Error cycling subtitle track: {e}")

    def toggle_mute(self):
        """Toggle mute state of the media player"""
        if not self.has_media:
            return
            
        try:
            # Toggle mute state
            current_mute = self.media_player.audio_get_mute()
            self.media_player.audio_set_mute(not current_mute)
            
            # Small delay to ensure the state is updated
            QTimer.singleShot(5, lambda: self._update_mute_overlay())
            
            # Update volume icon with a small delay to ensure VLC state is updated
            QTimer.singleShot(10, self.update_volume_icon)
            
        except Exception as e:
            print(f"Error toggling mute: {e}")
            
    def _update_mute_overlay(self):
        try:
            # Get the new state after toggle
            is_muted = self.media_player.audio_get_mute()
            current_volume = self.media_player.audio_get_volume()
            
            # Update volume display based on new state
            if is_muted:
                self.volume_overlay.setText("Volume: Muted")
            else:
                self.volume_overlay.setText(f"Volume: {current_volume}%")
                
            # Show the overlay
            self.show_volume_overlay()
            
            print(f"Mute overlay updated. Is muted: {is_muted}, Volume: {current_volume}")
        except Exception as e:
            print(f"Error updating mute overlay: {e}")

    def update_volume_icon(self):
        try:
            is_muted = self.media_player.audio_get_mute()
            current_volume = self.media_player.audio_get_volume()
            
            # Force icon update by temporarily setting it to None
            self.volume_button.setIcon(QIcon())
            
            if is_muted or current_volume == 0:
                icon = timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolumeMuted, size=18)
            else:
                icon = timeline_icon(self.style(), QStyle.StandardPixmap.SP_MediaVolume, size=18)
            
            self.volume_button.setIcon(icon)
            print(f"Updated volume icon - Muted: {is_muted}, Volume: {current_volume}")
        except Exception as e:
            print(f"Error updating volume icon: {e}")

    def on_volume_change(self, value):
        try:
            # Set volume and unmute if needed
            self.media_player.audio_set_mute(False)
            self.media_player.audio_set_volume(value)
            
            # Update volume display
            self.volume_overlay.setText(f"Volume: {value}%")
            self.show_volume_overlay()
            
            # Update volume icon immediately
            QTimer.singleShot(10, self.update_volume_icon)  # Small delay to ensure VLC state is updated
            
            print(f"Volume changed to: {value}")
        except Exception as e:
            print(f"Error changing volume: {e}")

    def timeline_pressed(self):
        self.timer.stop()

    def timeline_released(self):
        self.timer.start()

    def mouseMoveEvent(self, event: QMouseEvent):
        super().mouseMoveEvent(event)
        if self.isFullScreen():
            # Show/hide controls based on mouse position
            show_top = event.pos().y() < 50
            show_bottom = event.pos().y() > self.height() - 50
            
            if show_top:
                self.top_control_container.show()
                self.top_control_container.raise_()
            else:
                self.top_control_container.hide()
                
            if show_bottom:
                self.timeline_container.show()
                self.timeline_container.raise_()
            else:
                self.timeline_container.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.isFullScreen():
            # Allow dragging the window when clicking on the top bar
            if self.top_control_container.geometry().contains(event.pos()):
                self.drag_start_position = event.globalPosition().toPoint()
                self.window_pos_at_drag_start = self.pos()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if hasattr(self, 'drag_start_position') and event.buttons() & Qt.MouseButton.LeftButton:
            # Calculate the distance moved
            delta = event.globalPosition().toPoint() - self.drag_start_position
            # Move the window
            self.move(self.window_pos_at_drag_start + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if hasattr(self, 'drag_start_position'):
                delattr(self, 'drag_start_position')
                delattr(self, 'window_pos_at_drag_start')
        super().mouseReleaseEvent(event)

    def update_volume_overlay_position(self):
        if self.volume_overlay.isVisible():
            # Get the main window position
            window_pos = self.mapToGlobal(QPoint(0, 0))
            # Position volume overlay in the top left corner
            overlay_size = self.volume_overlay.sizeHint()
            x = window_pos.x() + 20  # Margin from left
            y = window_pos.y() + 50  # Below the title bar
            if self.title_overlay.isVisible():
                # If title overlay is visible, position below it
                title_height = self.title_overlay.height()
                y += title_height + 5  # Add some spacing
            self.volume_overlay.move(x, y)

    def update_title_overlay_position(self):
        if self.title_overlay.isVisible():
            # Get the main window position
            window_pos = self.mapToGlobal(QPoint(0, 0))
            # Position title overlay in the top left corner
            overlay_size = self.title_overlay.sizeHint()
            x = window_pos.x() + 20
            y = window_pos.y() + 20
            
            self.title_overlay.move(x, y)
            self.title_overlay.raise_()  # Ensure title stays on top
            # If volume overlay is visible, update its position to stay below title
            if self.volume_overlay.isVisible():
                self.update_volume_overlay_position()
            
    def resizeEvent(self, event):
        super().resizeEvent(event)
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
            
            # Calculate position relative to the main window
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
                # Restart title overlay timer to show it again after volume overlay hides
                self.title_overlay_timer.stop()
                self.title_overlay_timer.start(2000)  # Show title again after 2 seconds
            
            # Reset and start the hide timer
            self.volume_overlay_timer.stop()
            self.volume_overlay_timer.start(1500)  # Hide after 1.5 seconds
            
        except Exception as e:
            print(f"Error showing volume overlay: {e}")

    def show_title_overlay(self, title):
        if not title:
            return
            
        # Cancel any existing hide timer
        if self.title_overlay_timer.isActive():
            self.title_overlay_timer.stop()
        
        self.title_overlay.setText(title)
        
        # Calculate position relative to the video frame
        video_pos = self.video_frame.mapToGlobal(QPoint(0, 0))
        
        # Set fixed position in top-left corner
        title_x = video_pos.x() + 20
        title_y = video_pos.y() + 20
        
        # Set text with eliding for long titles
        self.title_overlay.setText(title)
        self.title_overlay.setWordWrap(False)
        font_metrics = QFontMetrics(self.title_overlay.font())
        elided_text = font_metrics.elidedText(title, Qt.TextElideMode.ElideRight, 800)  # Increased fixed width
        self.title_overlay.setText(elided_text)
        
        # Move to fixed position
        self.title_overlay.move(title_x, title_y)
        
        if self.volume_overlay.isVisible():
            self.title_overlay.hide()
        else:
            # Hide any existing title first
            self.title_overlay.hide()
            self.title_overlay.show()
            # Start new hide timer - 2 seconds for audio track info and subtitle info
            if title.startswith("Audio:") or title.startswith("Subtitles:"):
                self.title_overlay_timer.start(2000)  # 2 seconds for audio/subtitle info
            else:
                self.title_overlay_timer.start(3000)  # 3 seconds for other titles
            
    def hide_volume_overlay(self):
        self.volume_overlay.hide()

    def hide_title_overlay(self):
        self.title_overlay.hide()

    def update_control_positions(self):
        if not self.isVisible():
            return
            
        # Get the actual window width
        window_width = self.width()
        
        # Update top control position to span full width
        self.top_control_container.setGeometry(
            0, 0, window_width, self.top_control_container.height()
        )
        # Update timeline position to span full width
        self.timeline_container.setGeometry(
            0, self.height() - self.timeline_container.height(),
            window_width, self.timeline_container.height()
        )
        
        # Force update
        self.top_control_container.update()
        self.timeline_container.update()

    def adjust_window_to_video_size(self):
        """Handle media changed event and update window size"""
        try:
            # Skip window resizing if in fullscreen mode
            if self.isFullScreen():
                return
                
            # Get video dimensions
            video_width = self.media_player.video_get_width()
            video_height = self.media_player.video_get_height()
            
            if video_width > 0 and video_height > 0:
                # Calculate aspect ratio
                aspect_ratio = video_width / video_height
                
                # Get screen size
                screen = QApplication.primaryScreen()
                screen_size = screen.availableGeometry()
                
                # Calculate maximum size while maintaining aspect ratio
                max_width = min(screen_size.width() * 0.8, video_width)
                max_height = min(screen_size.height() * 0.8, video_height)
                
                if max_width / max_height > aspect_ratio:
                    width = int(max_height * aspect_ratio)
                    height = int(max_height)
                else:
                    width = int(max_width)
                    height = int(max_width / aspect_ratio)
                
                # Center the window on screen
                x = (screen_size.width() - width) // 2
                y = (screen_size.height() - height) // 2
                
                # Set window geometry
                self.setGeometry(x, y, width, height)
                
        except Exception as e:
            print(f"Error adjusting window size: {e}")

    def cycle_audio_track_reverse(self):
        """Cycle to the previous audio track"""
        if not self.has_media:
            return
            
        try:
            # Get current track and count
            current = self.media_player.audio_get_track()
            count = self.media_player.audio_get_track_count()
            
            if count <= 1:  # No tracks or only one track
                print("No audio tracks to cycle through")
                return
                
            # Get track descriptions to find valid tracks
            descriptions = self.media_player.audio_get_track_description()
            valid_tracks = []
            
            if descriptions:
                for track_id, _ in descriptions:
                    if track_id != -1:  # Skip the disable track
                        valid_tracks.append(track_id)
            
            if not valid_tracks:
                print("No valid audio tracks found")
                return
                
            # Find current track index in valid tracks
            try:
                current_index = valid_tracks.index(current)
                # Calculate previous track index
                prev_index = (current_index - 1) % len(valid_tracks)
            except ValueError:
                # If current track not found in valid tracks, start from last valid track
                prev_index = len(valid_tracks) - 1
            
            # Set the previous track
            prev_track = valid_tracks[prev_index]
            success = self.media_player.audio_set_track(prev_track)
            
            # Always show overlay with track info
            if descriptions:
                for track_id, desc in descriptions:
                    if track_id == prev_track:
                        if desc:
                            try:
                                desc = desc.decode('utf-8') if isinstance(desc, bytes) else str(desc)
                                track_name = f"Audio: Track {prev_track + 1} ({desc})"
                            except:
                                track_name = f"Audio: Track {prev_track + 1}"
                        else:
                            track_name = f"Audio: Track {prev_track + 1}"
                        break
            else:
                track_name = f"Audio: Track {prev_track + 1}"
            
            # Show the track name in the title overlay
            self.show_title_overlay(track_name)
            
            # Update the menu if visible
            if hasattr(self.video_frame, "update_audio_tracks"):
                self.video_frame.update_audio_tracks()
                
        except Exception as e:
            print(f"Error cycling audio track in reverse: {e}")

    def show_audio_track_overlay(self, text):
        """Show audio track overlay with the given text"""
        self.audio_track_overlay.setText(text)
        self.audio_track_overlay.adjustSize()
        
        # Calculate position relative to the main window
        window_pos = self.mapToGlobal(QPoint(0, 0))
        
        # Position in top-left corner with margins
        margin = 20
        x = window_pos.x() + margin
        y = window_pos.y() + margin
        
        # Move and show overlay
        self.audio_track_overlay.move(x, y)
        self.audio_track_overlay.show()
        self.audio_track_overlay.raise_()
        
        # Reset and start the hide timer
        self.audio_track_overlay_timer.stop()
        self.audio_track_overlay_timer.start(3000)  # Hide after 3 seconds

    def hide_audio_track_overlay(self):
        """Hide the audio track overlay"""
        self.audio_track_overlay.hide()

def main():
    import sys
    import os

    # Check for programmatic plugins cache regeneration flag
    if len(sys.argv) > 1 and sys.argv[1] == '--reset-plugins-cache':
        try:
            import vlc
            print("Inno Setup Post-Install: Rebuilding VLC plugins cache...")
            vlc.Instance(['--reset-plugins-cache'])
            print("Cache rebuilt successfully!")
            sys.exit(0)
        except Exception as e:
            print(f"Error rebuilding cache: {e}")
            sys.exit(1)

    # Create QApplication instance
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Set Fusion style for better icon handling
    
    # Set application window icon
    icon_path = os.path.join(base_dir, 'icon.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Create and show the player
    player = OniPlayer()
    
    # Go to fullscreen by default after a short delay to ensure window is ready
    QTimer.singleShot(100, player.toggle_fullscreen)
    
    # If file path is provided as argument, play it
    if len(sys.argv) > 1:
        player.play_file(sys.argv[1])
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
