import io
import threading
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QMenu, QPushButton, QSlider, QVBoxLayout, QWidget

from core.app_paths import APP_NAME, MUSIC_COMMAND_FILE, SETTINGS_FILE
from core.app_state import default_music_command, load_json, save_json
from core.music_content_filter import is_track_blocked_by_policy, music_policy_block_message
from core.music_metadata import is_youtube_url, resolve_track_metadata
from core.music_playlist import (
    PLAYLIST_IMPORT_LIMIT as DEFAULT_PLAYLIST_IMPORT_LIMIT,
    fetch_youtube_playlist_items,
    is_youtube_playlist_url,
)
from .constants import MUSIC_INPUT_PLACEHOLDER, NO_TRACK_TEXT, THUMBNAIL_PLACEHOLDER
from .widgets import Card, ThemedCheckBox, ThumbnailWidget


class DashboardMusicMixin:
    SKIP_NEXT_TRACK_MAX_DELAY_MS = 5000
    SKIP_NEXT_TRACK_PREFERRED_DELAY_MS = 100
    PLAYLIST_IMPORT_LIMIT = DEFAULT_PLAYLIST_IMPORT_LIMIT
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

        queue_header = QHBoxLayout()
        queue_header.setContentsMargins(0, 0, 0, 0)
        queue_header.addWidget(self.make_small_title("Queue"))
        queue_header.addStretch()
        queue_count = QLabel()
        self.set_label_role(queue_count, "mutedBody")
        queue_header.addWidget(queue_count)
        self.queue_count_labels.append(queue_count)
        layout.addLayout(queue_header)

        queue = QListWidget()
        queue.setMinimumHeight(queue_min_height)
        layout.addWidget(queue)

        duplicate_checkbox = ThemedCheckBox(self.localize("Prevent duplicate tracks"), self.theme)
        self._set_i18n_source(duplicate_checkbox, "Prevent duplicate tracks")
        duplicate_checkbox.toggled.connect(self.set_prevent_duplicate_tracks)
        self.register_prevent_duplicate_checkbox(duplicate_checkbox)
        layout.addWidget(duplicate_checkbox)

        queue_actions = QHBoxLayout()
        queue_actions.setContentsMargins(0, 0, 0, 0)
        queue_actions.setSpacing(8)
        queue_actions.addWidget(self.make_button("Move Up", "muted", lambda: self.move_selected_queue_item(queue, -1)))
        queue_actions.addWidget(self.make_button("Move Down", "muted", lambda: self.move_selected_queue_item(queue, 1)))
        remove_button = self.make_button(
            "Remove Selected",
            "muted",
            lambda: self.remove_selected_queue_item(queue),
        )
        queue_actions.addWidget(remove_button, 0, Qt.AlignLeft)
        queue_actions.addWidget(self.make_button("Clear Queue", "danger", self.clear_music_queue), 0, Qt.AlignLeft)
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
                    background-color: {colors.background};
                    color: {colors.title};
                    border: 1px solid {colors.border};
                    border-radius: 10px;
                    padding: 6px 12px;
                    font-size: 12px;
                    font-weight: 700;
                }}
                QPushButton:hover {{
                    background-color: {hover};
                }}
                """
            )
            button.blockSignals(False)
    def persist_music_enabled_setting(self):
        self.settings["music_enabled"] = bool(self.music_enabled)
        save_json(SETTINGS_FILE, self.settings)
    def persist_prevent_duplicate_setting(self):
        self.settings["prevent_duplicate_tracks"] = bool(self.prevent_duplicate_tracks)
        save_json(SETTINGS_FILE, self.settings)
    def register_prevent_duplicate_checkbox(self, checkbox):
        self.prevent_duplicate_checkboxes.append(checkbox)
        checkbox.blockSignals(True)
        checkbox.setChecked(bool(self.prevent_duplicate_tracks))
        checkbox.blockSignals(False)
    def sync_prevent_duplicate_checkboxes(self):
        for checkbox in getattr(self, "prevent_duplicate_checkboxes", []):
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(self.prevent_duplicate_tracks))
            checkbox.blockSignals(False)
    def set_prevent_duplicate_tracks(self, enabled):
        self.prevent_duplicate_tracks = bool(enabled)
        self.persist_prevent_duplicate_setting()
        self.sync_prevent_duplicate_checkboxes()
        state_text = "enabled" if self.prevent_duplicate_tracks else "disabled"
        self.append_log(f"[Music] Prevent duplicate tracks {state_text}")
    def normalize_track_query(self, query):
        return str(query or "").strip().lower()
    def queue_title_store(self):
        if not hasattr(self, "music_queue_titles") or not isinstance(self.music_queue_titles, dict):
            self.music_queue_titles = {}
        return self.music_queue_titles
    def clean_track_display_title(self, title, query):
        candidate = str(title or "").strip()
        query_text = str(query or "").strip()
        if candidate and candidate != query_text:
            return candidate
        if is_youtube_url(query_text):
            return "YouTube Track"
        return candidate or query_text or "Track"
    def set_music_queue_title(self, query, title=None):
        query_text = str(query or "").strip()
        if not query_text:
            return ""
        display_title = self.clean_track_display_title(title, query_text)
        self.queue_title_store()[query_text] = display_title
        return display_title
    def display_track_name(self, query):
        query_text = str(query or "").strip()
        title = self.queue_title_store().get(query_text, "")
        return self.clean_track_display_title(title, query_text)
    def is_duplicate_track_query(self, query, *, seen=None):
        if not getattr(self, "prevent_duplicate_tracks", True):
            return False
        normalized = self.normalize_track_query(query)
        if not normalized:
            return False
        if seen is not None and normalized in seen:
            return True
        current_query = self.normalize_track_query(getattr(self, "current_track_query", ""))
        if current_query and normalized == current_query and (self.current_track_active or self.music_loading):
            return True
        return any(self.normalize_track_query(item) == normalized for item in self.music_queue)
    def queue_track_query(self, query, display_name=None):
        if self.is_duplicate_track_query(query):
            self.append_log(f"[Music] Duplicate track ignored: {self.clean_track_display_title(display_name, query)}")
            return False
        display_title = self.set_music_queue_title(query, display_name)
        self.music_queue.append(query)
        self.refresh_queue_list_widgets()
        self.append_log(f"[Music] Track added to queue: {display_title}")
        return True
    def filter_duplicate_queue_entries(self, entries):
        normalized_entries = []
        for entry in entries or []:
            if isinstance(entry, dict):
                query = str(entry.get("query") or "").strip()
                title = str(entry.get("title") or "").strip()
                channel = str(entry.get("channel") or "").strip()
            else:
                query = str(entry or "").strip()
                title = ""
                channel = ""
            if query:
                normalized_entries.append({"query": query, "title": title, "channel": channel})

        if not getattr(self, "prevent_duplicate_tracks", True):
            return normalized_entries

        seen = {self.normalize_track_query(item) for item in self.music_queue if self.normalize_track_query(item)}
        current_query = self.normalize_track_query(getattr(self, "current_track_query", ""))
        if current_query and (self.current_track_active or self.music_loading):
            seen.add(current_query)

        filtered = []
        skipped = 0
        for entry in normalized_entries:
            normalized = self.normalize_track_query(entry.get("query", ""))
            if not normalized:
                continue
            if normalized in seen:
                skipped += 1
                continue
            seen.add(normalized)
            filtered.append(entry)
        if skipped:
            self.append_log(f"[Music] Ignored {skipped} duplicate queued tracks.")
        return filtered
    def filter_duplicate_queue_queries(self, queries):
        return [entry["query"] for entry in self.filter_duplicate_queue_entries(queries)]
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
    def reset_current_track_state(self, *, clear_player=False, clear_ui=False):
        self.music_loading = False
        self.current_track_active = False
        self.current_track_title = ""
        self.current_track_query = ""
        self.current_track_started_at = 0.0

        if clear_player and self.music_player_initialized and self.music_player is not None:
            try:
                self.music_player.clear_current_track()
            except Exception:
                pass

        if clear_ui and hasattr(self, "thumbnail_label") and hasattr(self, "music_page_thumbnail"):
            self.clear_current_track_ui()
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
        self.queue_title_store().clear()
        save_json(MUSIC_COMMAND_FILE, default_music_command())
        self.last_music_command_timestamp = ""
        self.reset_current_track_state()

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
        widget.setProperty("queueList", True)
        self.apply_queue_widget_style(widget)
        widget.itemDoubleClicked.connect(lambda item, source=widget: self.remove_queue_item_at(source.row(item)))
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(lambda pos, source=widget: self.show_queue_context_menu(source, pos))
    def queue_widget_stylesheet(self):
        return f"""
            QListWidget {{
                background-color: {self.theme.input_bg};
                color: {self.theme.text_primary};
                border: 1px solid {self.theme.border_color};
                border-radius: 12px;
                padding: 10px;
                font-size: 13px;
                outline: none;
                selection-background-color: {self.theme.accent_color};
                selection-color: {self.theme.text_inverse};
            }}
            QListWidget:focus {{
                border: 1px solid {self.theme.accent_border};
                background-color: {self.theme.input_bg};
            }}
            QListWidget::item {{
                background: transparent;
                color: {self.theme.text_primary};
                padding: 8px 10px;
                border-radius: 8px;
                margin: 2px 0;
            }}
            QListWidget::item:hover {{
                background-color: {self.theme.elevated_card_background};
                color: {self.theme.text_primary};
            }}
            QListWidget::item:selected {{
                background-color: {self.theme.accent_color};
                color: {self.theme.text_inverse};
                border: 1px solid {self.theme.accent_border};
            }}
            QListWidget::item:disabled {{
                color: {self.theme.text_secondary};
            }}
        """
    def apply_queue_widget_style(self, widget):
        if widget is None:
            return
        widget.setProperty("queueList", True)
        widget.setStyleSheet(self.queue_widget_stylesheet())
    def show_queue_context_menu(self, widget, position):
        index = widget.currentRow()
        if index < 0 or index >= len(self.music_queue):
            return

        menu = QMenu(self)
        move_up_action = menu.addAction("Move Up")
        move_down_action = menu.addAction("Move Down")
        remove_action = menu.addAction("Remove from Queue")
        selected_action = menu.exec(widget.mapToGlobal(position))
        if selected_action == move_up_action:
            self.move_queue_item(index, -1)
        elif selected_action == move_down_action:
            self.move_queue_item(index, 1)
        elif selected_action == remove_action:
            self.remove_queue_item_at(index)
    def set_queue_selection(self, index):
        if index < 0 or index >= len(self.music_queue):
            return
        for widget in [getattr(self, "queue_listbox", None), getattr(self, "music_page_queue", None)]:
            if widget is not None:
                widget.setCurrentRow(index)
    def move_queue_item(self, index, delta):
        target = index + int(delta)
        if index < 0 or index >= len(self.music_queue) or target < 0 or target >= len(self.music_queue):
            return
        self.music_queue[index], self.music_queue[target] = self.music_queue[target], self.music_queue[index]
        self.refresh_queue_list_widgets(selected_index=target)
        self.append_log(f"[Music] Queue item moved {'up' if delta < 0 else 'down'}")
    def move_selected_queue_item(self, widget, delta):
        self.move_queue_item(widget.currentRow(), delta)
    def clear_music_queue(self):
        if not self.music_queue:
            self.refresh_queue_list_widgets()
            self.append_log("[Music] Queue already empty")
            return
        removed_count = len(self.music_queue)
        self.music_queue = []
        self.queue_title_store().clear()
        self.refresh_queue_list_widgets()
        self.append_log(f"[Music] Queue cleared ({removed_count} tracks removed)")
    def remove_queue_item_at(self, index: int):
        if index < 0 or index >= len(self.music_queue):
            return
        removed = self.music_queue.pop(index)
        self.refresh_queue_list_widgets()
        self.append_log(f"Removed from queue: {self.display_track_name(removed)}")
    def remove_selected_queue_item(self, widget):
        self.remove_queue_item_at(widget.currentRow())
    def refresh_queue_count_labels(self):
        count = len(self.music_queue)
        label_text = f"Queue: {count} track" if count == 1 else f"Queue: {count} tracks"
        for label in getattr(self, "queue_count_labels", []):
            self.set_dynamic_text(label, label_text)
    def refresh_queue_list_widgets(self, selected_index=None):
        for widget in [getattr(self, "queue_listbox", None), getattr(self, "music_page_queue", None)]:
            if widget is None:
                continue
            widget.clear()
            if not self.music_queue:
                widget.addItem(self.localize("No queued tracks"))
            else:
                for index, item in enumerate(self.music_queue, start=1):
                    widget.addItem(f"{index}. {self.display_track_name(item)}")
                if selected_index is not None:
                    widget.setCurrentRow(max(0, min(int(selected_index), len(self.music_queue) - 1)))
        self.refresh_queue_count_labels()
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
        self.current_track_query = query
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
                self.current_track_query = query
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
                self.current_track_query = ""
                self.current_track_started_at = 0.0
                self.bridge.clear_cover_signal.emit()

        threading.Thread(target=worker, daemon=True).start()
    def inspect_track_request(self, query: str):
        return resolve_track_metadata(query)
    def start_track_request_inspection(self, query: str):
        self.append_log(f"[Music] Checking track metadata: {query}")

        def worker():
            try:
                metadata = self.inspect_track_request(query)
                blocked = is_track_blocked_by_policy(
                    title=metadata.title,
                    channel=metadata.channel,
                )
                self.bridge.music_track_request_signal.emit(
                    {
                        "ok": True,
                        "query": metadata.query or query,
                        "title": metadata.title,
                        "channel": metadata.channel,
                        "blocked": blocked,
                    }
                )
            except Exception as exc:
                self.bridge.music_track_request_signal.emit(
                    {
                        "ok": False,
                        "query": query,
                        "error": str(exc),
                    }
                )

        threading.Thread(target=worker, daemon=True).start()
    def apply_track_request_result(self, payload):
        if not payload or not payload.get("ok"):
            error = str((payload or {}).get("error") or "Unknown track metadata error").strip()
            self.append_log(f"[Music] Track could not be checked: {error}")
            return

        title = str(payload.get("title") or "").strip()
        channel = str(payload.get("channel") or "").strip()
        query = str(payload.get("query") or "").strip()

        if payload.get("blocked") or is_track_blocked_by_policy(title=title, channel=channel):
            self.append_log(music_policy_block_message())
            self.append_log("[Music] Track unavailable due to music policy.")
            return

        if not query:
            self.append_log("[Music] Track could not be checked: no playable URL found")
            return

        if not self.music_enabled:
            self.append_log("Music requests are currently disabled")
            return

        player = self.ensure_music_player()
        if player is None:
            self.append_log("Music player is unavailable")
            return

        if self.current_track_active or self.music_loading or player.is_playing():
            self.append_log(f"[Music] Busy, queueing request: {title or query}")
            self.queue_track_query(query, title or query)
            return

        if self.is_duplicate_track_query(query):
            self.append_log(f"[Music] Duplicate track ignored: {title or query}")
            return
        display_title = self.set_music_queue_title(query, title or query)
        self.append_log(f"[Music] Track added for immediate playback: {display_title}")
        self.append_log(f"[Music] Starting immediate playback for: {display_title}")
        self.start_track_playback(query)
    def fetch_playlist_items(self, query: str):
        return fetch_youtube_playlist_items(query, max_tracks=self.PLAYLIST_IMPORT_LIMIT)
    def start_playlist_import(self, query: str):
        if getattr(self, "playlist_import_loading", False):
            self.append_log("[Music] Playlist import already in progress")
            return

        self.playlist_import_loading = True
        self.append_log(f"[Music] Loading playlist items (max {self.PLAYLIST_IMPORT_LIMIT}): {query}")

        def worker():
            try:
                playlist = self.fetch_playlist_items(query)
                self.bridge.music_playlist_signal.emit(
                    {
                        "ok": True,
                        "title": playlist.title,
                        "tracks": [
                            {"title": track.title, "query": track.query, "channel": track.channel}
                            for track in playlist.tracks
                        ],
                        "truncated": bool(playlist.truncated),
                        "blocked_count": int(playlist.blocked_count),
                    }
                )
            except Exception as exc:
                self.bridge.music_playlist_signal.emit(
                    {
                        "ok": False,
                        "error": str(exc),
                        "query": query,
                    }
                )

        threading.Thread(target=worker, daemon=True).start()
    def apply_playlist_import_result(self, payload):
        self.playlist_import_loading = False
        if not payload or not payload.get("ok"):
            error = str((payload or {}).get("error") or "Unknown playlist error").strip()
            self.append_log(f"[Music] Playlist could not be loaded: {error}")
            return

        if not self.music_enabled:
            self.append_log("[Music] Playlist ignored because music requests are disabled")
            return

        player = self.ensure_music_player()
        if player is None:
            self.append_log("Music player is unavailable")
            return

        tracks = payload.get("tracks") or []
        blocked_count = int(payload.get("blocked_count") or 0)
        entries = []
        for track in tracks:
            if not isinstance(track, dict):
                continue
            title = str(track.get("title") or "").strip()
            channel = str(track.get("channel") or "").strip()
            query = str(track.get("query") or "").strip()
            if not query:
                continue
            if is_track_blocked_by_policy(title=title, channel=channel, playlist_title=payload.get("title", "")):
                blocked_count += 1
                continue
            entries.append({"query": query, "title": title, "channel": channel})

        if blocked_count:
            self.append_log(music_policy_block_message())
            self.append_log(f"[Music] Skipped {blocked_count} playlist tracks due to music policy.")

        if not entries:
            self.append_log("[Music] Playlist could not be loaded: Track unavailable due to music policy.")
            return

        entries = self.filter_duplicate_queue_entries(entries)
        if not entries:
            self.refresh_queue_list_widgets()
            self.append_log("[Music] Playlist contained no new tracks to add.")
            return

        for entry in entries:
            self.set_music_queue_title(entry["query"], entry.get("title"))
        queries = [entry["query"] for entry in entries]

        is_busy = self.current_track_active or self.music_loading or player.is_playing()
        if is_busy:
            self.music_queue.extend(queries)
        else:
            first_query = queries[0]
            remaining_queries = queries[1:]
            if remaining_queries:
                self.music_queue = remaining_queries + self.music_queue

        self.refresh_queue_list_widgets()
        self.append_log(f"[Music] Added {len(queries)} tracks from playlist.")
        if payload.get("truncated"):
            self.append_log(f"[Music] Playlist import limited to first {self.PLAYLIST_IMPORT_LIMIT} tracks")

        if not is_busy:
            self.append_log(f"[Music] Starting first playlist track: {self.display_track_name(first_query)}")
            self.start_track_playback(first_query)
    def queue_or_play_music(self, query: str):
        query = query.strip()
        if not query:
            self.append_log("حط رابط يوتيوب أو اسم مقطع")
            return

        if not self.music_enabled:
            self.append_log("Music requests are currently disabled")
            return

        if is_youtube_playlist_url(query):
            self.start_playlist_import(query)
            return

        self.start_track_request_inspection(query)
    def play_youtube_audio(self):
        self.handle_music_action("play", self.music_entry.text(), source="dashboard_ui")
    def play_music_page(self):
        self.handle_music_action("play", self.music_page_input.text(), source="music_page_ui")
    def play_next_in_queue(self):
        if self.music_loading:
            self.append_log("[Music] Queue advance delayed while current track is loading")
            return
        if self.music_queue:
            next_query = self.music_queue.pop(0)
            self.refresh_queue_list_widgets()
            self.append_log(f"[Music] Playing next queued track: {self.display_track_name(next_query)}")
            self.start_track_playback(next_query)
        else:
            self.reset_current_track_state(clear_player=True, clear_ui=True)
            self.refresh_queue_list_widgets()
            self.append_log("[Music] Queue empty - No track loaded")
    def schedule_play_next_in_queue(self):
        QTimer.singleShot(0, self.play_next_in_queue)
    def schedule_skip_queue_advance(self, stop_completed):
        advanced = {"done": False}
        started_at = time.monotonic()

        def advance_once(reason):
            if advanced["done"]:
                return
            advanced["done"] = True
            if not stop_completed["done"]:
                self.append_log("[Music] Skip handoff reached 5s cap; starting next queued track")
            else:
                self.append_log(f"[Music] Skip handoff ready: {reason}")
            self.play_next_in_queue()

        def poll_stop():
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            if stop_completed["done"]:
                advance_once("current playback stopped")
                return
            if elapsed_ms >= self.SKIP_NEXT_TRACK_MAX_DELAY_MS:
                advance_once("timeout cap")
                return
            QTimer.singleShot(self.SKIP_NEXT_TRACK_PREFERRED_DELAY_MS, poll_stop)

        QTimer.singleShot(0, poll_stop)
    def stop_youtube_audio(self):
        player = self.ensure_music_player()
        if player is None:
            self.append_log("Music player is unavailable")
            return

        try:
            player.stop()
            self.music_loading = False
            self.music_queue = []
            self.queue_title_store().clear()
            self.refresh_queue_list_widgets()
            self.reset_current_track_state(clear_player=True, clear_ui=True)
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
                stop_completed = {"done": False}

                def stop_worker():
                    try:
                        player.stop()
                    except Exception as exc:
                        self.bridge.log_signal.emit(f"[Music] VLC stop during skip failed: {exc}")
                    finally:
                        stop_completed["done"] = True

                threading.Thread(target=stop_worker, daemon=True).start()
                self.reset_current_track_state(clear_player=True, clear_ui=True)
                self.append_log("[Music] Track skipped")
                if self.music_queue:
                    self.schedule_skip_queue_advance(stop_completed)
                else:
                    self.play_next_in_queue()
            else:
                self.reset_current_track_state(clear_player=True, clear_ui=True)
                self.refresh_queue_list_widgets()
                self.append_log("[Music] No current track to skip - No track loaded")
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
