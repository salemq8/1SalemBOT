import io
import threading
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QMenu, QPushButton, QSlider, QVBoxLayout, QWidget

from core.app_paths import APP_NAME, MUSIC_COMMAND_FILE, SETTINGS_FILE
from core.app_state import default_music_command, load_json, save_json
from .constants import MUSIC_INPUT_PLACEHOLDER, NO_TRACK_TEXT, THUMBNAIL_PLACEHOLDER
from .widgets import Card, ThumbnailWidget


class DashboardMusicMixin:
    def make_music_controls_row(self, paste_callback, play_callback, compact=False):
        row = QHBoxLayout()
        row.setSpacing(8 if not compact else 6)
        row.addWidget(self.make_button("Paste", "primary", paste_callback))
        row.addWidget(self.make_button("Play", "success", play_callback))
        row.addWidget(self.make_button("Skip", "warning", self.skip_current_track))
        row.addWidget(self.make_button("Stop", "danger", self.stop_youtube_audio))
        return row
    def make_music_toggle_button(self):
        button = QPushButton()
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(self.toggle_music_enabled)
        button.setMinimumHeight(30)
        return button
    def register_volume_controls(self, slider, value_label, mute_button, *, row_layout=None, down_button=None, up_button=None):
        self.apply_media_control_direction(slider)
        self.volume_slider_widgets.append(slider)
        self.volume_value_labels.append(value_label)
        self.volume_mute_buttons.append(mute_button)
        if row_layout is not None and down_button is not None and up_button is not None:
            self.volume_control_rows.append(
                {
                    "layout": row_layout,
                    "down_button": down_button,
                    "slider": slider,
                    "up_button": up_button,
                    "mute_button": mute_button,
                    "value_label": value_label,
                }
            )
            self.sync_volume_button_order()
    def apply_media_control_direction(self, widget):
        if widget is None:
            return
        widget.setLayoutDirection(Qt.LeftToRight)
        if hasattr(widget, "setInvertedAppearance"):
            widget.setInvertedAppearance(False)
        if hasattr(widget, "setInvertedControls"):
            widget.setInvertedControls(False)
    def sync_media_control_directions(self):
        for slider in getattr(self, "volume_slider_widgets", []):
            self.apply_media_control_direction(slider)
    def sync_volume_button_order(self):
        is_rtl = self.is_rtl_language()
        for controls in getattr(self, "volume_control_rows", []):
            layout = controls.get("layout")
            if layout is None:
                continue
            down_button = controls.get("down_button")
            slider = controls.get("slider")
            up_button = controls.get("up_button")
            mute_button = controls.get("mute_button")
            value_label = controls.get("value_label")
            widgets = [down_button, slider, up_button, mute_button, value_label]
            if not all(widget is not None for widget in widgets):
                continue

            for widget in widgets:
                layout.removeWidget(widget)

            ordered_widgets = (
                [up_button, slider, down_button, mute_button, value_label]
                if is_rtl
                else [down_button, slider, up_button, mute_button, value_label]
            )
            for widget in ordered_widgets:
                layout.addWidget(widget, 1 if widget is slider else 0)
            self.apply_media_control_direction(slider)
    def persist_audio_settings(self):
        self.settings["audio_volume"] = int(self.audio_volume)
        self.settings["audio_muted"] = bool(self.audio_muted)
        save_json(SETTINGS_FILE, self.settings)
    def sync_volume_controls(self):
        label_text = f"{self.audio_volume}%"
        mute_text = "Unmute" if self.audio_muted else "Mute"

        for slider in self.volume_slider_widgets:
            self.apply_media_control_direction(slider)
            slider.blockSignals(True)
            slider.setValue(self.audio_volume)
            slider.blockSignals(False)

        for label in self.volume_value_labels:
            label.setText(label_text)

        for button in self.volume_mute_buttons:
            self.set_localized_text(button, mute_text)
    def apply_audio_state_from_player(self, state, *, persist=False):
        if not state:
            return
        previous_bound = self.audio_session_attached
        self.audio_volume = max(0, min(100, int(state.get("volume", self.audio_volume))))
        self.audio_muted = bool(state.get("muted", self.audio_muted))
        self.audio_session_attached = bool(state.get("session_bound"))
        self.sync_volume_controls()
        if persist:
            self.persist_audio_settings()
        if self.audio_session_attached and not previous_bound:
            display_name = state.get("display_name") or APP_NAME
            self.append_log(f"[Audio] Windows audio session attached as {display_name}")
    def push_audio_state_to_player(self, *, persist=False):
        player = self.ensure_music_player()
        if player is None:
            return
        player.set_volume(self.audio_volume)
        player.set_muted(self.audio_muted)
        state = player.get_audio_state()
        self.apply_audio_state_from_player(state, persist=persist)
    def set_master_volume(self, value, *, persist=True):
        self.audio_volume = max(0, min(100, int(value)))
        self.sync_volume_controls()
        self.push_audio_state_to_player(persist=persist)
    def adjust_master_volume(self, delta):
        self.set_master_volume(self.audio_volume + int(delta))
    def toggle_audio_mute(self):
        self.audio_muted = not self.audio_muted
        self.sync_volume_controls()
        self.push_audio_state_to_player(persist=True)
    def poll_audio_state(self):
        if not self.music_player_initialized or self.music_player is None:
            return
        try:
            state = self.music_player.get_audio_state()
        except Exception:
            return
        if not state:
            return
        if int(state.get("volume", self.audio_volume)) != self.audio_volume or bool(state.get("muted", self.audio_muted)) != self.audio_muted or bool(state.get("session_bound")) != self.audio_session_attached:
            self.apply_audio_state_from_player(state, persist=True)
    def build_volume_controls_row(self, *, compact=False):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6 if compact else 8)

        down_button = self.make_button("-", "muted", lambda: self.adjust_master_volume(-5))
        down_button.setFixedWidth(42)
        row.addWidget(down_button)

        slider = QSlider(Qt.Horizontal)
        self.apply_media_control_direction(slider)
        slider.setRange(0, 100)
        slider.setValue(self.audio_volume)
        slider.valueChanged.connect(self.set_master_volume)
        row.addWidget(slider, 1)

        up_button = self.make_button("+", "muted", lambda: self.adjust_master_volume(5))
        up_button.setFixedWidth(42)
        row.addWidget(up_button)

        mute_button = self.make_button("Mute", "muted", self.toggle_audio_mute)
        mute_button.setMinimumWidth(88)
        row.addWidget(mute_button)

        value_label = self.make_info_value_label(f"{self.audio_volume}%")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setMinimumWidth(52)
        row.addWidget(value_label)

        self.register_volume_controls(
            slider,
            value_label,
            mute_button,
            row_layout=row,
            down_button=down_button,
            up_button=up_button,
        )
        return row
    def make_now_playing_card(
        self,
        title_text,
        thumbnail_height_range,
        entry_placeholder,
        paste_callback,
        play_callback,
        *,
        queue_min_height=180,
        compact=False,
    ):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8 if compact else 10)

        layout.addWidget(self.make_title(title_text))

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(8)
        toggle_button = self.make_music_toggle_button()
        toggle_row.addWidget(toggle_button, 0, Qt.AlignLeft)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        layout.addWidget(self.make_small_title("Now Playing Preview"))

        thumbnail = ThumbnailWidget(
            THUMBNAIL_PLACEHOLDER,
            min_height=thumbnail_height_range[0],
            max_height=thumbnail_height_range[1],
        )
        layout.addWidget(thumbnail)

        value = self.make_info_value_label(NO_TRACK_TEXT)
        layout.addWidget(value)

        entry = QLineEdit()
        entry.setPlaceholderText(entry_placeholder)
        layout.addWidget(entry)
        layout.addLayout(self.make_music_controls_row(paste_callback, play_callback, compact=compact))

        layout.addWidget(self.make_small_title("Master Volume"))
        layout.addLayout(self.build_volume_controls_row(compact=compact))

        layout.addWidget(self.make_small_title("Queue"))
        queue = QListWidget()
        queue.setMinimumHeight(queue_min_height)
        layout.addWidget(queue)

        queue_actions = QHBoxLayout()
        queue_actions.setContentsMargins(0, 0, 0, 0)
        queue_actions.setSpacing(8)
        remove_button = self.make_button(
            "Remove Selected",
            "muted",
            lambda: self.remove_selected_queue_item(queue),
        )
        queue_actions.addWidget(remove_button, 0, Qt.AlignLeft)
        queue_actions.addStretch()
        layout.addLayout(queue_actions)

        return card, thumbnail, value, entry, queue, toggle_button
    def sync_music_toggle_buttons(self):
        toggle_text = "Music Requests: On" if self.music_enabled else "Music Requests: Off"
        colors = self.theme.status_colors("success" if self.music_enabled else "danger")
        hover = self.theme.success_hover if self.music_enabled else self.theme.danger_hover

        for button in [getattr(self, "dashboard_music_toggle", None), getattr(self, "music_page_toggle", None)]:
            if button is None:
                continue
            button.blockSignals(True)
            button.setChecked(self.music_enabled)
            self.set_localized_text(button, toggle_text)
            button.setStyleSheet(
                f"""
                QPushButton {{
                    background: {colors.background};
                    color: {colors.title};
                    border: 1px solid {colors.border};
                    border-radius: 10px;
                    padding: 6px 12px;
                    font-size: 12px;
                    font-weight: 700;
                }}
                QPushButton:hover {{
                    background: {hover};
                }}
                """
            )
            button.blockSignals(False)
    def persist_music_enabled_setting(self):
        self.settings["music_enabled"] = bool(self.music_enabled)
        save_json(SETTINGS_FILE, self.settings)
    def set_music_enabled(self, enabled: bool, announce=True):
        self.music_enabled = bool(enabled)
        self.persist_music_enabled_setting()
        self.sync_music_toggle_buttons()
        if not self.music_enabled and (self.current_track_active or self.music_queue):
            self.stop_youtube_audio()
        if announce:
            state_text = "enabled" if self.music_enabled else "disabled"
            self.append_log(f"Music requests {state_text}")
    def toggle_music_enabled(self):
        sender = self.sender()
        enabled = bool(sender.isChecked()) if isinstance(sender, QPushButton) else (not self.music_enabled)
        self.set_music_enabled(enabled)
    def set_now_playing_title(self, title: str):
        self.clear_i18n_binding(self.now_playing_value)
        self.clear_i18n_binding(self.music_page_now_playing_value)
        self.now_playing_value.setText(title)
        self.music_page_now_playing_value.setText(title)
    def clear_current_track_ui(self):
        self.current_track_title = ""
        self.set_localized_text(self.now_playing_value, NO_TRACK_TEXT)
        self.set_localized_text(self.music_page_now_playing_value, NO_TRACK_TEXT)
        self.thumbnail_label.clear_thumbnail(THUMBNAIL_PLACEHOLDER)
        self.music_page_thumbnail.clear_thumbnail(THUMBNAIL_PLACEHOLDER)
    def _apply_cover_pixmap(self, pixmap_payload):
        if pixmap_payload is None:
            self.thumbnail_label.clear_thumbnail(THUMBNAIL_PLACEHOLDER)
            self.music_page_thumbnail.clear_thumbnail(THUMBNAIL_PLACEHOLDER)
            return
        if isinstance(pixmap_payload, QPixmap):
            pixmap = pixmap_payload
        else:
            pixmap = QPixmap()
            if not pixmap.loadFromData(pixmap_payload):
                self.thumbnail_label.clear_thumbnail(THUMBNAIL_PLACEHOLDER)
                self.music_page_thumbnail.clear_thumbnail(THUMBNAIL_PLACEHOLDER)
                self.append_log("[Music] Thumbnail payload could not be decoded")
                return
        self.thumbnail_label.set_pixmap(pixmap)
        self.music_page_thumbnail.set_pixmap(pixmap)
    def reset_music_session_state(self):
        self.music_queue = []
        save_json(MUSIC_COMMAND_FILE, default_music_command())
        self.last_music_command_timestamp = ""
        self.current_track_active = False
        self.music_loading = False
        self.current_track_title = ""
        self.current_track_started_at = 0.0

        if self.music_player_initialized and self.music_player is not None:
            try:
                self.music_player.stop()
                self.music_player.clear_current_track()
            except Exception:
                pass

        self.refresh_queue_list_widgets()
        if hasattr(self, "thumbnail_label") and hasattr(self, "music_page_thumbnail"):
            self.clear_current_track_ui()
    def setup_queue_widget(self, widget):
        widget.itemDoubleClicked.connect(lambda item, source=widget: self.remove_queue_item_at(source.row(item)))
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(lambda pos, source=widget: self.show_queue_context_menu(source, pos))
    def show_queue_context_menu(self, widget, position):
        index = widget.currentRow()
        if index < 0 or index >= len(self.music_queue):
            return

        menu = QMenu(self)
        remove_action = menu.addAction("Remove from Queue")
        if menu.exec(widget.mapToGlobal(position)) == remove_action:
            self.remove_queue_item_at(index)
    def remove_queue_item_at(self, index: int):
        if index < 0 or index >= len(self.music_queue):
            return
        removed = self.music_queue.pop(index)
        self.refresh_queue_list_widgets()
        self.append_log(f"Removed from queue: {removed}")
    def remove_selected_queue_item(self, widget):
        self.remove_queue_item_at(widget.currentRow())
    def refresh_queue_list_widgets(self):
        for widget in [self.queue_listbox, self.music_page_queue]:
            widget.clear()
            if not self.music_queue:
                widget.addItem(self.localize("No queued tracks"))
            else:
                for index, item in enumerate(self.music_queue, start=1):
                    widget.addItem(f"{index}. {item}")
    def handle_music_action(self, action: str, query: str = "", source: str = "ui"):
        normalized_action = (action or "").strip().lower()
        normalized_query = (query or "").strip()
        self.append_log(f"[Music] Handling action from {source}: action={normalized_action} query={normalized_query}")

        if normalized_action == "play":
            if not normalized_query:
                self.append_log("Music play requested without a query")
                return
            self.music_entry.setText(normalized_query)
            self.music_page_input.setText(normalized_query)
            self.queue_or_play_music(normalized_query)
            return

        if normalized_action == "skip":
            self.skip_current_track()
            return

        if normalized_action == "stop":
            self.stop_youtube_audio()
            return

        self.append_log(f"Unknown music action ignored: {normalized_action}")
    def start_track_playback(self, query: str):
        player = self.ensure_music_player()
        if player is None:
            self.append_log("Music player is unavailable")
            return

        self.music_loading = True
        self.current_track_active = False
        self.current_track_title = ""
        self.current_track_started_at = 0.0
        self.append_log(f"[Music] Loading request: {query}")

        def worker():
            try:
                self.bridge.log_signal.emit(f"[Music] Resolving track for: {query}")
                track = player.load(query)
                self.bridge.log_signal.emit(f"[Music] Resolved track: {track.title}")
                self.bridge.log_signal.emit("[Music] Starting VLC playback")
                player.play_loaded()

                wait_started_at = time.time()
                last_logged_state = None
                while time.time() - wait_started_at < 10:
                    state = player.get_state()
                    state_text = str(state) if state is not None else "None"
                    if state_text != last_logged_state:
                        self.bridge.log_signal.emit(f"[Music] VLC state: {state_text}")
                        last_logged_state = state_text
                    if player.is_playing():
                        break
                    if state is not None and str(state).lower().endswith("error"):
                        raise RuntimeError("VLC reported an error while starting playback")
                    time.sleep(0.25)

                if not player.is_playing():
                    final_state = player.get_state()
                    raise RuntimeError(f"Playback did not start in time (last state: {final_state})")

                audio_state = player.get_audio_state()
                if audio_state.get("session_bound"):
                    self.bridge.log_signal.emit(
                        f"[Audio] Session ready as {audio_state.get('display_name') or APP_NAME}"
                    )
                self.music_loading = False
                self.current_track_active = True
                self.current_track_title = track.title
                self.current_track_started_at = time.time()

                self.bridge.title_signal.emit(track.title)
                self.bridge.log_signal.emit(f"[Music] Playing: {track.title}")

                image = player.get_thumbnail_image()
                if image:
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    self.bridge.cover_signal.emit(buffer.getvalue())
                    self.bridge.log_signal.emit("[Music] Thumbnail loaded")
                else:
                    self.bridge.log_signal.emit("[Music] Thumbnail missing for current track")
                    self.bridge.clear_cover_signal.emit()
            except Exception as exc:
                last_state = player.get_state() if player is not None else "unavailable"
                self.bridge.log_signal.emit(f"[Music] Failed to play audio: {exc}")
                self.bridge.log_signal.emit(f"[Music] Last VLC state: {last_state}")
                self.music_loading = False
                self.current_track_active = False
                self.current_track_title = ""
                self.current_track_started_at = 0.0
                self.bridge.clear_cover_signal.emit()

        threading.Thread(target=worker, daemon=True).start()
    def queue_or_play_music(self, query: str):
        query = query.strip()
        if not query:
            self.append_log("حط رابط يوتيوب أو اسم مقطع")
            return

        player = self.ensure_music_player()
        if player is None:
            self.append_log("Music player is unavailable")
            return

        if not self.music_enabled:
            self.append_log("Music requests are currently disabled")
            return

        if self.current_track_active or self.music_loading or player.is_playing():
            self.append_log(f"[Music] Busy, queueing request: {query}")
            self.music_queue.append(query)
            self.refresh_queue_list_widgets()
            self.append_log(f"Added to queue: {query}")
            return

        self.append_log(f"[Music] Starting immediate playback for: {query}")
        self.start_track_playback(query)
    def play_youtube_audio(self):
        self.handle_music_action("play", self.music_entry.text(), source="dashboard_ui")
    def play_music_page(self):
        self.handle_music_action("play", self.music_page_input.text(), source="music_page_ui")
    def play_next_in_queue(self):
        if self.music_loading:
            return
        if self.music_queue:
            next_query = self.music_queue.pop(0)
            self.refresh_queue_list_widgets()
            self.start_track_playback(next_query)
        else:
            self.current_track_active = False
            self.current_track_title = ""
            self.clear_current_track_ui()
    def stop_youtube_audio(self):
        player = self.ensure_music_player()
        if player is None:
            self.append_log("Music player is unavailable")
            return

        try:
            player.stop()
            self.music_loading = False
            self.music_queue = []
            self.refresh_queue_list_widgets()
            self.current_track_active = False
            self.current_track_title = ""
            self.clear_current_track_ui()
            self.append_log("Audio stopped and queue cleared")
        except Exception as exc:
            self.append_log(f"Failed to stop audio: {exc}")
    def skip_current_track(self):
        player = self.ensure_music_player()
        if player is None:
            self.append_log("Music player is unavailable")
            return

        try:
            if self.current_track_active or self.music_loading or player.is_playing():
                player.stop()
                self.music_loading = False
                self.current_track_active = False
                self.current_track_title = ""
                self.append_log("Track skipped")
                QTimer.singleShot(500, self.play_next_in_queue)
            else:
                self.append_log("No current track to skip")
        except Exception as exc:
            self.append_log(f"Failed to skip track: {exc}")
    def monitor_music_state(self):
        try:
            if self.music_player_initialized and self.music_player is not None and self.current_track_active and not self.music_loading:
                if time.time() - self.current_track_started_at > 3 and not self.music_player.is_playing():
                    self.append_log(f"Track ended: {self.current_track_title}")
                    self.current_track_active = False
                    self.current_track_title = ""
                    self.play_next_in_queue()
        except Exception as exc:
            self.append_log(f"Music monitor error: {exc}")
    def process_music_command(self):
        try:
            data = load_json(MUSIC_COMMAND_FILE, default_music_command())
            timestamp = data.get("timestamp")
            action = data.get("action")
            query = data.get("query", "")
            source = data.get("source", "external")
            requested_by = data.get("requested_by", "")

            if timestamp and timestamp != self.last_music_command_timestamp:
                self.append_log(
                    f"[Music] Command detected: action={action} timestamp={timestamp} "
                    f"query={query} source={source} requested_by={requested_by}"
                )
                self.last_music_command_timestamp = timestamp
                if action == "play" and not self.music_enabled:
                    self.append_log(f"[Music] Ignored music command while disabled: {query}")
                    return
                self.handle_music_action(action, query, source=f"command_file:{source}")
        except Exception as exc:
            self.append_log(f"Music command read error: {exc}")
    def build_music_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)

        (
            music_card,
            self.music_page_thumbnail,
            self.music_page_now_playing_value,
            self.music_page_input,
            self.music_page_queue,
            self.music_page_toggle,
        ) = self.make_now_playing_card(
            "Music Controls",
            (220, 340),
            MUSIC_INPUT_PLACEHOLDER,
            self.paste_music_to_page,
            self.play_music_page,
        )
        self.setup_queue_widget(self.music_page_queue)
        body_layout.addWidget(music_card)
        body_layout.addStretch()

        layout.addWidget(self.make_scroll_container(body))
        return page
