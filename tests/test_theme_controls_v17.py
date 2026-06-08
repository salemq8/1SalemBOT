import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLineEdit, QListView, QListWidget, QMenu, QPlainTextEdit

from core.ui.themes import THEMES, build_app_stylesheet, build_combo_popup_stylesheet
from core.ui.music_mixin import DashboardMusicMixin
from core.ui.window import DashboardApp
from core.ui.widgets import ThemedCheckBox


def _app():
    return QApplication.instance() or QApplication([])


def _color_distance(left: QColor, right: QColor) -> int:
    return (
        abs(left.red() - right.red())
        + abs(left.green() - right.green())
        + abs(left.blue() - right.blue())
    )


def _render_widget(widget, width=240, height=42) -> QImage:
    widget.resize(width, height)
    widget.show()
    _app().processEvents()
    image = QImage(widget.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    widget.render(painter, QPoint(0, 0))
    painter.end()
    return image


def _best_sample(image: QImage, expected: QColor) -> QColor:
    sample_points = (
        (image.width() // 2, image.height() // 2),
        (image.width() // 3, image.height() // 2),
        (image.width() - 20, image.height() // 2),
        (image.width() // 2, image.height() - 8),
    )
    samples = [image.pixelColor(x, y) for x, y in sample_points]
    return min(samples, key=lambda color: _color_distance(color, expected))


class ThemeControlsStyleTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.theme = THEMES["blue"]
        self.app.setStyleSheet(build_app_stylesheet(self.theme))

    def test_combobox_popup_uses_theme_palette(self):
        combo = QComboBox()
        combo.addItems(["Blue", "Pink", "Purple"])
        combo.setView(QListView(combo))
        combo.view().setStyleSheet(build_combo_popup_stylesheet(self.theme))

        stylesheet = combo.view().styleSheet()
        self.assertIn(f"background-color: {self.theme.panel_background}", stylesheet)
        self.assertIn(f"background-color: {self.theme.accent_color}", stylesheet)
        self.assertIn(f"border: 1px solid {self.theme.border_color}", stylesheet)
        self.assertIn(f"color: {self.theme.text_primary}", stylesheet)
        self.assertNotIn("#000", stylesheet.lower())
        self.assertNotIn("black", stylesheet.lower())

        image = _render_widget(combo)
        input_sample = _best_sample(image, QColor(self.theme.input_bg))
        self.assertLess(_color_distance(input_sample, QColor(self.theme.input_bg)), 90)
        combo.close()

    def test_qmenu_global_style_uses_theme_palette(self):
        stylesheet = self.app.styleSheet()
        self.assertIn("QMenu {", stylesheet)
        self.assertIn(f"background-color: {self.theme.panel_background}", stylesheet)
        self.assertIn(f"border: 1px solid {self.theme.border_color}", stylesheet)
        self.assertIn(f"background-color: {self.theme.accent_color}", stylesheet)
        self.assertNotIn("background-color: #000", stylesheet.lower())

        menu = QMenu()
        menu.addAction("Move Up")
        image = _render_widget(menu, width=180, height=48)
        sample = _best_sample(image, QColor(self.theme.panel_background))
        self.assertLess(_color_distance(sample, QColor(self.theme.panel_background)), 120)
        menu.close()

    def test_table_selection_uses_visible_accent_highlight(self):
        stylesheet = self.app.styleSheet()
        self.assertIn(f"selection-background-color: {self.theme.accent_color}", stylesheet)
        self.assertIn(f"selection-color: {self.theme.text_inverse}", stylesheet)

    def test_inputs_render_distinct_from_panel_background(self):
        expected_input = QColor(self.theme.input_bg)
        panel = QColor(self.theme.panel_background)

        for widget in (QLineEdit(), QPlainTextEdit()):
            with self.subTest(widget=type(widget).__name__):
                height = 92 if isinstance(widget, QPlainTextEdit) else 42
                image = _render_widget(widget, height=height)
                center = _best_sample(image, expected_input)
                side_border = image.pixelColor(0, image.height() // 2)
                self.assertLess(_color_distance(center, expected_input), 90)
                self.assertGreater(_color_distance(center, panel), 20)
                self.assertGreater(_color_distance(side_border, expected_input), 30)
                widget.close()

    def test_line_edit_focus_highlight_uses_accent(self):
        entry = QLineEdit()
        entry.setFocus()
        self.app.processEvents()
        image = _render_widget(entry)
        accent = QColor(self.theme.accent_color)
        edge = image.pixelColor(0, image.height() // 2)
        self.assertLess(_color_distance(edge, accent), 140)
        entry.close()

    def test_themed_checkbox_has_visible_checked_and_unchecked_states(self):
        checkbox = ThemedCheckBox("Auto Update", self.theme)

        checkbox.setChecked(False)
        unchecked = _render_widget(checkbox, width=180, height=34)
        unchecked_indicator = unchecked.pixelColor(9, unchecked.height() // 2)
        self.assertLess(_color_distance(unchecked_indicator, QColor(self.theme.input_bg)), 100)

        checkbox.setChecked(True)
        checked = _render_widget(checkbox, width=180, height=34)
        checked_indicator = checked.pixelColor(8, checked.height() // 2 - 8)
        self.assertLess(_color_distance(checked_indicator, QColor(self.theme.accent_color)), 140)

        checked_checkmark = checked.pixelColor(4, checked.height() // 2)
        self.assertLess(_color_distance(checked_checkmark, QColor(self.theme.text_inverse)), 180)
        checkbox.close()

    def test_queue_list_renders_as_dark_bordered_box(self):
        queue = QListWidget()
        queue.setProperty("queueList", True)
        queue.addItem("No queued tracks")

        image = _render_widget(queue, width=320, height=90)
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        edge = image.pixelColor(0, image.height() // 2)

        self.assertLess(_color_distance(center, QColor(self.theme.input_bg)), 110)
        self.assertGreater(_color_distance(edge, center), 20)
        queue.close()

    def test_music_queue_uses_explicit_dark_surface_style(self):
        class QueueStyleHarness(DashboardMusicMixin):
            pass

        queue = QListWidget()
        harness = QueueStyleHarness()
        harness.theme = self.theme
        harness.apply_queue_widget_style(queue)
        queue.addItem("1. Resolved Video Title")

        stylesheet = queue.styleSheet()
        self.assertIn(f"background-color: {self.theme.input_bg}", stylesheet)
        self.assertIn(f"border: 1px solid {self.theme.border_color}", stylesheet)
        self.assertIn("border-radius: 12px", stylesheet)
        self.assertIn(f"color: {self.theme.text_primary}", stylesheet)

        image = _render_widget(queue, width=320, height=90)
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        self.assertLess(_color_distance(center, QColor(self.theme.input_bg)), 130)
        queue.close()

    def test_bot_settings_page_keeps_real_form_controls(self):
        patches = (
            ("ensure_alerts_listener", lambda self, force=False: None),
            ("schedule_startup_auto_restart", lambda self: None),
            ("request_auth_health_check", lambda self, force=False: None),
            ("check_for_updates", lambda self, auto=False: None),
        )
        originals = {}
        for name, replacement in patches:
            originals[name] = getattr(DashboardApp, name)
            setattr(DashboardApp, name, replacement)
        try:
            window = DashboardApp()
            window.resize(1200, 800)
            window.switch_page("Bot Settings")
            self.app.processEvents()

            for attr_name in ("theme_selector", "language_selector", "log_retention_selector"):
                combo = getattr(window, attr_name)
                with self.subTest(combo=attr_name):
                    self.assertIsInstance(combo, QComboBox)
                    self.assertIsInstance(combo.view(), QListView)
                    stylesheet = combo.styleSheet()
                    self.assertIn(f"background-color: {window.theme.input_bg}", stylesheet)
                    self.assertIn(f"border: 1px solid {window.theme.border_color}", stylesheet)
                    self.assertIn("border-radius: 10px", stylesheet)
                    self.assertIn("padding:", stylesheet)
                    self.assertIn("QComboBox::drop-down", stylesheet)

            for attr_name in ("settings_bot_login", "settings_channel_login"):
                entry = getattr(window, attr_name)
                with self.subTest(entry=attr_name):
                    self.assertIsInstance(entry, QLineEdit)
                    self.assertTrue(entry.isReadOnly())
                    self.assertEqual(str(entry.property("readOnlyDisplay")), "true")
                    stylesheet = entry.styleSheet()
                    self.assertIn("background-color:", stylesheet)
                    self.assertIn(f"border: 1px solid {window.theme.border_color}", stylesheet)
                    self.assertIn("border-radius: 10px", stylesheet)
                    self.assertIn("padding: 8px 10px", stylesheet)

            self.assertIsInstance(window.trigger_input, QLineEdit)
            self.assertFalse(window.trigger_input.isReadOnly())
            self.assertTrue(window.trigger_input.placeholderText())
            self.assertIn(f"background-color: {window.theme.input_bg}", window.trigger_input.styleSheet())
            self.assertIn(f"border: 1px solid {window.theme.border_color}", window.trigger_input.styleSheet())
            self.assertIn("border-radius: 10px", window.trigger_input.styleSheet())
            self.assertIn("padding: 8px 10px", window.trigger_input.styleSheet())

            self.assertIsInstance(window.trigger_chips_frame, QFrame)
            self.assertEqual(str(window.trigger_chips_frame.property("surfaceRole")), "subtle")
            window.close()
        finally:
            for name, original in originals.items():
                setattr(DashboardApp, name, original)


if __name__ == "__main__":
    unittest.main()
