import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.ui.themes import THEMES
from core.ui.widgets import ActionButton


def _app():
    return QApplication.instance() or QApplication([])


def _color_distance(left: QColor, right: QColor) -> int:
    return (
        abs(left.red() - right.red())
        + abs(left.green() - right.green())
        + abs(left.blue() - right.blue())
    )


def _render_button(button: ActionButton) -> QImage:
    button.resize(180, 46)
    button.show()
    _app().processEvents()
    image = QImage(button.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    button.render(painter, QPoint(0, 0))
    painter.end()
    return image


def _best_background_sample(image: QImage, expected: QColor) -> QColor:
    sample_points = (
        (image.width() - 22, image.height() // 2),
        (image.width() // 2, 8),
        (image.width() // 2, image.height() - 8),
        (image.width() // 3, image.height() // 2),
    )
    samples = [image.pixelColor(x, y) for x, y in sample_points]
    return min(samples, key=lambda color: _color_distance(color, expected))


class ActionButtonStyleTest(unittest.TestCase):
    def test_action_buttons_render_filled_backgrounds(self):
        _app()
        theme = THEMES["blue"]
        for role in ("primary", "success", "danger", "warning", "muted", "twitch", "ghost"):
            with self.subTest(role=role):
                button = ActionButton("Move Up", role, theme)
                image = _render_button(button)
                expected = QColor(theme.button_colors(role).background)
                sample = _best_background_sample(image, expected)
                app_bg = QColor(theme.app_background)

                self.assertLess(
                    _color_distance(sample, expected),
                    90,
                    f"{role} button did not render its filled background",
                )
                self.assertGreater(
                    _color_distance(sample, app_bg),
                    25,
                    f"{role} button background is too close to the app background",
                )

        button.close()

    def test_disabled_action_button_keeps_muted_fill(self):
        _app()
        theme = THEMES["blue"]
        button = ActionButton("Cancel Download", "danger", theme)
        button.setEnabled(False)
        image = _render_button(button)
        expected = QColor(theme.elevated_card_background)
        sample = _best_background_sample(image, expected)
        app_bg = QColor(theme.app_background)

        self.assertLess(_color_distance(sample, expected), 90)
        self.assertGreater(_color_distance(sample, app_bg), 15)
        button.close()


if __name__ == "__main__":
    unittest.main()
