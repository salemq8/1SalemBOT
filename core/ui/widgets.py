from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget

from .constants import THUMBNAIL_PLACEHOLDER
from .localization import DEFAULT_LANGUAGE, is_rtl_language, translate_text
from .themes import DEFAULT_THEME_NAME, THEMES


class Bridge(QObject):
    log_signal = Signal(str)
    cover_signal = Signal(object)
    title_signal = Signal(str)
    clear_cover_signal = Signal()
    account_signal = Signal(object)
    chat_assets_ready_signal = Signal()
    stream_summary_signal = Signal(object)
    viewer_relationships_signal = Signal(object)
    auth_health_signal = Signal(object)
    update_status_signal = Signal(object)
    update_check_result_signal = Signal(object)
    update_progress_signal = Signal(object)
    update_download_result_signal = Signal(object)
    music_playlist_signal = Signal(object)
    music_track_request_signal = Signal(object)


class ThumbnailWidget(QWidget):
    def __init__(self, placeholder=THUMBNAIL_PLACEHOLDER, min_height=180, max_height=340, aspect_ratio=16 / 9):
        super().__init__()
        self.placeholder = placeholder
        self.placeholder_source = placeholder
        self.language = DEFAULT_LANGUAGE
        self._pixmap = None
        self._min_height = min_height
        self._max_height = max_height
        self._aspect_ratio = aspect_ratio
        self.theme = THEMES[DEFAULT_THEME_NAME]

        self.setMinimumHeight(min_height)
        self.setMaximumHeight(max_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if width <= 0:
            return self._min_height
        target_height = int(width / self._aspect_ratio)
        return max(self._min_height, min(self._max_height, target_height))

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        width = max(320, int(self._min_height * self._aspect_ratio))
        return QSize(width, self._min_height)

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def clear_thumbnail(self, text=None):
        self._pixmap = None
        if text is not None:
            self.placeholder = text
            self.placeholder_source = text
        self.update()

    def apply_theme(self, theme):
        self.theme = theme
        self.update()

    def apply_language(self, language):
        self.language = language or DEFAULT_LANGUAGE
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = 12

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)

        painter.fillPath(path, QColor(self.theme.thumbnail_bg))
        painter.setClipPath(path)

        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = rect.x() + (rect.width() - scaled.width()) // 2
            y = rect.y() + (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.setPen(QColor(self.theme.text_secondary))
            painter.drawText(rect, Qt.AlignCenter, translate_text(self.placeholder_source, self.language))

        painter.setClipping(False)
        painter.setPen(QColor(self.theme.thumbnail_border))
        painter.drawRoundedRect(QRectF(rect), radius, radius)
        painter.end()


class SidebarButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setMinimumHeight(44)
        self.theme = THEMES[DEFAULT_THEME_NAME]
        self.language = DEFAULT_LANGUAGE
        self.apply_theme(self.theme)

    def apply_theme(self, theme):
        self.theme = theme
        is_rtl = is_rtl_language(self.language)
        text_align = "right" if is_rtl else "left"
        normal_padding = "11px 16px 11px 14px" if is_rtl else "11px 14px 11px 16px"
        checked_padding = "11px 18px 11px 14px" if is_rtl else "11px 14px 11px 18px"
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {theme.nav_text};
                border: 1px solid transparent;
                text-align: {text_align};
                padding: {normal_padding};
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {theme.nav_hover_bg};
                border-color: {theme.nav_hover_border};
                color: {theme.text_primary};
            }}
            QPushButton:checked {{
                background: {theme.nav_active_bg};
                border-color: {theme.nav_active_border};
                color: {theme.nav_active_text};
                padding: {checked_padding};
            }}
            """
        )

    def apply_language(self, language):
        self.language = language or DEFAULT_LANGUAGE
        self.setLayoutDirection(Qt.RightToLeft if is_rtl_language(self.language) else Qt.LeftToRight)
        self.apply_theme(self.theme)


class ActionButton(QPushButton):
    """Filled dashboard action button that does not rely on app-level QSS selectors."""

    def __init__(self, text="", role="muted", theme=None, parent=None):
        super().__init__(text, parent)
        self.role = role or "muted"
        self.theme = theme or THEMES[DEFAULT_THEME_NAME]
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("buttonRole", self.role)
        self.setProperty("styledActionButton", True)
        self.setFlat(False)
        self.setAutoDefault(False)
        self.setDefault(False)
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.apply_theme(self.theme)

    def set_role(self, role):
        self.role = role or "muted"
        self.setProperty("buttonRole", self.role)
        self.apply_theme(self.theme)

    def apply_theme(self, theme):
        self.theme = theme or THEMES[DEFAULT_THEME_NAME]
        colors = self.theme.button_colors(self.role)
        disabled_bg = self.theme.elevated_card_background
        disabled_border = self.theme.border_color
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {colors.background};
                color: {colors.text};
                border: 1px solid {colors.border};
                border-radius: 12px;
                padding: 10px 16px;
                min-height: 18px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {colors.hover};
                border-color: {self.theme.accent_border};
            }}
            QPushButton:pressed {{
                background-color: {colors.hover};
                padding-top: 11px;
                padding-bottom: 9px;
            }}
            QPushButton:disabled {{
                background-color: {disabled_bg};
                color: {self.theme.text_muted};
                border-color: {disabled_border};
            }}
            """
        )


class ThemedCheckBox(QCheckBox):
    """Compact painted checkbox so checked/unchecked states stay visible under app QSS."""

    def __init__(self, text="", theme=None, parent=None):
        super().__init__(text, parent)
        self.theme = theme or THEMES[DEFAULT_THEME_NAME]
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setStyleSheet("QCheckBox { background: transparent; border: none; }")
        self.apply_theme(self.theme)

    def apply_theme(self, theme):
        self.theme = theme or THEMES[DEFAULT_THEME_NAME]
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self):
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(self.text())
        return QSize(max(34, 18 + 9 + text_width), max(24, metrics.height() + 8))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        indicator_size = 18
        spacing = 9
        is_rtl = self.layoutDirection() == Qt.RightToLeft
        indicator_x = self.width() - indicator_size if is_rtl else 0
        indicator_y = (self.height() - indicator_size) / 2
        indicator_rect = QRectF(indicator_x, indicator_y, indicator_size, indicator_size)

        if self.isEnabled():
            bg = QColor(self.theme.accent if self.isChecked() else self.theme.input_bg)
            border = QColor(self.theme.accent_border if (self.isChecked() or self._hovered) else self.theme.border_color)
            text_color = QColor(self.theme.text_primary if self.isChecked() else self.theme.text_secondary)
        else:
            bg = QColor(self.theme.elevated_card_background)
            border = QColor(self.theme.border_color)
            text_color = QColor(self.theme.text_muted)

        painter.setPen(QPen(border, 1.4))
        painter.setBrush(bg)
        painter.drawRoundedRect(indicator_rect, 5, 5)

        if self.isChecked():
            check_pen = QPen(QColor(self.theme.text_inverse), 2.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(check_pen)
            x = indicator_rect.left()
            y = indicator_rect.top()
            painter.drawLine(QPointF(x + 4.5, y + 9.4), QPointF(x + 7.6, y + 12.4))
            painter.drawLine(QPointF(x + 7.6, y + 12.4), QPointF(x + 13.8, y + 5.8))

        if is_rtl:
            text_rect = QRectF(0, 0, max(0, indicator_x - spacing), self.height())
            alignment = Qt.AlignRight | Qt.AlignVCenter
        else:
            text_rect = QRectF(indicator_size + spacing, 0, max(0, self.width() - indicator_size - spacing), self.height())
            alignment = Qt.AlignLeft | Qt.AlignVCenter

        painter.setPen(text_color)
        painter.drawText(text_rect, alignment, self.text())
        painter.end()


class Card(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setProperty("cardFrame", True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.theme = THEMES[DEFAULT_THEME_NAME]
        self.apply_theme(self.theme)

    def apply_theme(self, theme):
        self.theme = theme
        self.setStyleSheet(
            f"""
            QFrame[cardFrame="true"] {{
                background: {theme.card_background};
                border: 1px solid {theme.border_color};
                border-radius: 18px;
            }}
            """
        )
        shadow_color = QColor(theme.app_background)
        shadow_color.setAlpha(115)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(shadow_color)
        self.setGraphicsEffect(shadow)


class ChatLogBrowser(QTextBrowser):
    def __init__(self):
        super().__init__()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.NoFrame)


class StatusDot(QWidget):
    COLOR_MAP = {
        "connected": "#4ade80",
        "healthy": "#4ade80",
        "success": "#4ade80",
        "connecting": "#f59e0b",
        "reconnecting": "#f59e0b",
        "waiting": "#f59e0b",
        "warning": "#f59e0b",
        "failed": "#ef4444",
        "disconnected": "#ef4444",
        "invalid": "#ef4444",
        "danger": "#ef4444",
    }

    def __init__(self, state="disconnected", size=18, dot_size=7, parent=None):
        super().__init__(parent)
        self.state = state
        self.theme = THEMES[DEFAULT_THEME_NAME]
        self.dot_size = dot_size
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)
        self.setToolTip("Disconnected")

    def set_state(self, state, tooltip=""):
        self.state = str(state or "disconnected")
        if tooltip:
            self.setToolTip(tooltip)
        self.update()

    def apply_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        base = self.COLOR_MAP.get(self.state, self.COLOR_MAP["disconnected"])
        badge_rect = QRectF(0, 0, self.width(), self.height())
        badge_bg = QColor(self.theme.elevated_card_background)
        badge_bg.setAlpha(205)
        painter.setBrush(badge_bg)
        painter.drawRoundedRect(badge_rect, 5, 5)

        dot_diameter = min(self.dot_size, self.width(), self.height())
        dot_rect = QRectF(
            (self.width() - dot_diameter) / 2,
            (self.height() - dot_diameter) / 2,
            dot_diameter,
            dot_diameter,
        )

        glow_rect = dot_rect.adjusted(-2, -2, 2, 2)
        glow = QRadialGradient(glow_rect.center(), glow_rect.width() / 2)
        glow_color = QColor(base)
        glow_edge = QColor(base)
        glow_color.setAlpha(58)
        glow_edge.setAlpha(0)
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(1.0, glow_edge)
        painter.setBrush(glow)
        painter.drawEllipse(glow_rect)

        painter.setBrush(QColor(base))
        painter.drawEllipse(dot_rect)
        painter.end()


class AnalyticsChartWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self._labels = []
        self._tooltip_labels = []
        self._hover_index = None
        self.theme = THEMES[DEFAULT_THEME_NAME]
        self._series = {
            "Messages": {"values": [], "color": QColor(self.theme.chart_messages)},
            "Commands": {"values": [], "color": QColor(self.theme.chart_commands)},
            "Timeouts": {"values": [], "color": QColor(self.theme.chart_timeouts)},
        }
        self._point_cache = {}
        self._chart_rect = QRectF()
        self.language = DEFAULT_LANGUAGE

    def set_series_data(self, labels, series, tooltip_labels=None):
        self._labels = list(labels or [])
        self._tooltip_labels = list(tooltip_labels or labels or [])
        for key in self._series:
            self._series[key]["values"] = list(series.get(key, []))
        if self._hover_index is not None and self._hover_index >= len(self._labels):
            self._hover_index = None
        self.update()

    def apply_theme(self, theme):
        self.theme = theme
        self._series["Messages"]["color"] = QColor(theme.chart_messages)
        self._series["Commands"]["color"] = QColor(theme.chart_commands)
        self._series["Timeouts"]["color"] = QColor(theme.chart_timeouts)
        self.update()

    def apply_language(self, language):
        self.language = language or DEFAULT_LANGUAGE
        self.setLayoutDirection(Qt.RightToLeft if is_rtl_language(self.language) else Qt.LeftToRight)
        self.update()

    def _build_points(self, chart_rect: QRectF, values, max_value):
        if not values:
            return []
        count = len(values)
        span = max(count - 1, 1)
        points = []
        for index, value in enumerate(values):
            x = chart_rect.left() + (chart_rect.width() * index / span)
            y = chart_rect.bottom() - ((value / max_value) * chart_rect.height())
            points.append(QPointF(x, y))
        return points

    def _build_line_path(self, points):
        if not points:
            return QPainterPath()

        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        return path

    def _update_hover_index(self, position):
        if self._chart_rect.isNull() or not self._labels:
            next_index = None
        elif not self._chart_rect.adjusted(-20, -10, 20, 28).contains(position):
            next_index = None
        else:
            first_series = self._point_cache.get("Messages") or []
            if not first_series:
                next_index = None
            else:
                distances = [abs(point.x() - position.x()) for point in first_series]
                next_index = min(range(len(distances)), key=distances.__getitem__)

        self.setCursor(Qt.CrossCursor if next_index is not None else Qt.ArrowCursor)
        if next_index != self._hover_index:
            self._hover_index = next_index
            self.update()

    def mouseMoveEvent(self, event):
        self._update_hover_index(event.position())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_index is not None:
            self._hover_index = None
            self.update()
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        outer_rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(outer_rect, Qt.transparent)

        title_rect = QRectF(outer_rect.left(), outer_rect.top(), outer_rect.width(), 28)
        painter.setPen(QColor(self.theme.text_primary))
        title_alignment = (Qt.AlignRight if is_rtl_language(self.language) else Qt.AlignLeft) | Qt.AlignVCenter
        painter.drawText(title_rect, title_alignment, translate_text("7-Day Activity", self.language))

        legend_items = list(self._series.items())
        legend_x = max(int(outer_rect.left() + 120), int(outer_rect.right() - 300))
        legend_y = outer_rect.top() + 4
        for index, (name, meta) in enumerate(legend_items):
            dot_x = legend_x + (index * 96)
            painter.setPen(Qt.NoPen)
            painter.setBrush(meta["color"])
            painter.drawEllipse(QRectF(dot_x, legend_y + 5, 8, 8))
            painter.setPen(QColor(self.theme.text_secondary))
            painter.drawText(QRectF(dot_x + 14, legend_y, 80, 18), Qt.AlignLeft | Qt.AlignVCenter, translate_text(name, self.language))

        chart_rect = QRectF(
            outer_rect.left() + 18,
            outer_rect.top() + 40,
            outer_rect.width() - 36,
            outer_rect.height() - 72,
        )
        self._chart_rect = chart_rect

        painter.setPen(QPen(QColor(self.theme.chart_grid), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(chart_rect, 14, 14)

        all_values = []
        for meta in self._series.values():
            all_values.extend(meta["values"])

        max_value = max(all_values) if all_values else 0
        if max_value <= 0:
            max_value = 1

        grid_lines = 5
        painter.setPen(QPen(QColor(self.theme.chart_grid), 1))
        for index in range(grid_lines + 1):
            y = chart_rect.bottom() - ((chart_rect.height() / grid_lines) * index)
            painter.drawLine(chart_rect.left(), y, chart_rect.right(), y)

            value = int(max_value * index / grid_lines)
            label_rect = QRectF(chart_rect.left() - 44, y - 10, 38, 20)
            painter.setPen(QColor(self.theme.chart_axis))
            painter.drawText(label_rect, Qt.AlignRight | Qt.AlignVCenter, str(value))
            painter.setPen(QPen(QColor(self.theme.chart_grid), 1))

        label_count = len(self._labels)
        if label_count > 1:
            for index in range(label_count):
                x = chart_rect.left() + (chart_rect.width() * index / (label_count - 1))
                painter.drawLine(x, chart_rect.top(), x, chart_rect.bottom())

        self._point_cache = {
            name: self._build_points(chart_rect, meta["values"], max_value)
            for name, meta in self._series.items()
        }

        messages_points = self._point_cache["Messages"]
        messages_path = self._build_line_path(messages_points)
        if not messages_path.isEmpty():
            fill_path = QPainterPath(messages_path)
            fill_path.lineTo(chart_rect.right(), chart_rect.bottom())
            fill_path.lineTo(chart_rect.left(), chart_rect.bottom())
            fill_path.closeSubpath()

            gradient = QLinearGradient(chart_rect.topLeft(), chart_rect.bottomLeft())
            message_color = self._series["Messages"]["color"]
            gradient.setColorAt(0.0, QColor(message_color.red(), message_color.green(), message_color.blue(), 110))
            gradient.setColorAt(1.0, QColor(message_color.red(), message_color.green(), message_color.blue(), 8))
            painter.fillPath(fill_path, gradient)

        for name, meta in self._series.items():
            path = self._build_line_path(self._point_cache[name])
            if path.isEmpty():
                continue

            pen = QPen(meta["color"], 2 if name == "Messages" else 1.6)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        if self._hover_index is not None and self._labels:
            hover_x = self._point_cache.get("Messages", [QPointF(chart_rect.left(), chart_rect.bottom())])[self._hover_index].x()
            painter.setPen(QPen(QColor(self.theme.text_secondary), 1))
            painter.drawLine(QPointF(hover_x, chart_rect.top()), QPointF(hover_x, chart_rect.bottom()))

            for name, meta in self._series.items():
                points = self._point_cache.get(name, [])
                if self._hover_index >= len(points):
                    continue
                point = points[self._hover_index]
                painter.setPen(QPen(meta["color"], 2))
                painter.setBrush(QColor(self.theme.chart_plot_bg))
                painter.drawEllipse(point, 5.5, 5.5)
                painter.setBrush(meta["color"])
                painter.drawEllipse(point, 2.4, 2.4)

            tooltip_width = 190
            tooltip_height = 104
            anchor_point = self._point_cache["Messages"][self._hover_index]
            preferred_x = anchor_point.x() + 20
            if preferred_x + tooltip_width > chart_rect.right() - 8:
                preferred_x = anchor_point.x() - tooltip_width - 20
            tooltip_x = max(chart_rect.left() + 10, preferred_x)
            tooltip_y = min(
                max(chart_rect.top() + 12, anchor_point.y() - 28),
                chart_rect.bottom() - tooltip_height - 12,
            )
            tooltip_rect = QRectF(tooltip_x, tooltip_y, tooltip_width, tooltip_height)

            painter.setPen(QPen(QColor(self.theme.chart_tooltip_border), 1))
            painter.setBrush(QColor(self.theme.chart_tooltip_bg))
            painter.drawRoundedRect(tooltip_rect, 12, 12)

            date_text = self._tooltip_labels[self._hover_index] if self._hover_index < len(self._tooltip_labels) else self._labels[self._hover_index]
            painter.setPen(QColor(self.theme.text_primary))
            painter.drawText(
                QRectF(tooltip_rect.left() + 14, tooltip_rect.top() + 12, tooltip_rect.width() - 28, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                date_text,
            )

            row_y = tooltip_rect.top() + 42
            for name, meta in self._series.items():
                values = meta["values"]
                value = values[self._hover_index] if self._hover_index < len(values) else 0
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(self.theme.chart_plot_bg))
                painter.drawEllipse(QRectF(tooltip_rect.left() + 14, row_y + 2, 12, 12))
                painter.setBrush(meta["color"])
                painter.drawEllipse(QRectF(tooltip_rect.left() + 17, row_y + 5, 6, 6))
                painter.setPen(QColor(self.theme.text_primary))
                painter.drawText(
                    QRectF(tooltip_rect.left() + 34, row_y - 2, tooltip_rect.width() - 48, 18),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    f"{value} {translate_text(name, self.language)}",
                )
                row_y += 24

        painter.setPen(QColor(self.theme.chart_axis))
        label_baseline = QRectF(chart_rect.left(), chart_rect.bottom() + 10, chart_rect.width(), 18)
        if label_count == 1:
            painter.drawText(label_baseline, Qt.AlignLeft | Qt.AlignTop, self._labels[0])
        elif label_count > 1:
            for index, label in enumerate(self._labels):
                x = chart_rect.left() + (chart_rect.width() * index / (label_count - 1))
                text_rect = QRectF(x - 32, chart_rect.bottom() + 10, 64, 18)
                painter.drawText(text_rect, Qt.AlignCenter, label)

        painter.end()


class AccountWidget(QFrame):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self._hovered = False
        self.theme = THEMES[DEFAULT_THEME_NAME]
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(68)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(38, 38)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.avatar_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.title_label = QLabel("Bot account")
        self.title_label.setStyleSheet("font-size:11px;font-weight:600;")
        text_layout.addWidget(self.title_label)

        self.name_label = QLabel("Not connected")
        self.name_label.setStyleSheet("font-size:14px;font-weight:700;")
        text_layout.addWidget(self.name_label)
        layout.addLayout(text_layout, 1)

        self.chevron_label = QLabel("▾")
        self.chevron_label.setStyleSheet("font-size:16px;font-weight:700;")
        self.chevron_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.chevron_label)

        self._apply_style()

    def set_profile(self, name: str, subtitle: str, avatar: QPixmap | None):
        self.name_label.setText(name)
        self.title_label.setText(subtitle)
        if avatar is not None and not avatar.isNull():
            self.avatar_label.setPixmap(avatar)

    def _apply_style(self):
        background = self.theme.elevated_card_background if self._hovered else self.theme.card_background
        self.setStyleSheet(
            f"""
            QFrame {{
                background: {background};
                border: 1px solid {self.theme.border_color};
                border-radius: 14px;
            }}
            """
        )
        self.title_label.setStyleSheet(f"color:{self.theme.text_secondary};font-size:11px;font-weight:600;")
        self.name_label.setStyleSheet(f"color:{self.theme.text_primary};font-size:14px;font-weight:700;")
        self.chevron_label.setStyleSheet(f"color:{self.theme.text_secondary};font-size:16px;font-weight:700;")

    def apply_theme(self, theme):
        self.theme = theme
        self._apply_style()

    def enterEvent(self, event):
        self._hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class SidebarAccountCard(QFrame):
    def __init__(self, role_title=""):
        super().__init__()
        self._hovered = False
        self.theme = THEMES[DEFAULT_THEME_NAME]
        self.language = DEFAULT_LANGUAGE
        self.role_title = role_title

        self.setProperty("sidebarAccountCard", True)
        self.setFixedHeight(58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 30, 7)
        layout.setSpacing(9)

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(32, 32)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.avatar_label, 0, Qt.AlignVCenter)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)

        self.role_label = QLabel(role_title)
        self.role_label.setProperty("i18n_source_text", role_title)
        self.role_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_column.addWidget(self.role_label, 0, Qt.AlignLeft)

        self.username_label = QLabel("Not connected")
        self.username_label.setProperty("i18n_source_text", "Not connected")
        self.username_label.setWordWrap(True)
        text_column.addWidget(self.username_label)
        layout.addLayout(text_column, 1)

        self.status_dot = StatusDot("disconnected", size=18, dot_size=7, parent=self)
        self.status_dot.raise_()
        self.apply_theme(self.theme)
        self.position_status_dot()

    def set_account_state(
        self,
        *,
        role_title=None,
        username=None,
        avatar=None,
        status_state=None,
        status_tooltip=None,
    ):
        if role_title is not None:
            self.role_title = role_title
            self.role_label.setProperty("i18n_source_text", role_title)
            self.role_label.setText(translate_text(role_title, self.language))
        if username is not None:
            username_text = str(username or "")
            if username_text == "Not connected":
                self.username_label.setProperty("i18n_source_text", username_text)
                self.username_label.setText(translate_text(username_text, self.language))
            else:
                self.username_label.setProperty("i18n_source_text", "")
                self.username_label.setText(username_text)

        if avatar is not None and not avatar.isNull():
            self.avatar_label.setPixmap(avatar)
        if status_state is not None:
            self.status_dot.set_state(status_state, status_tooltip or "")
            self.status_dot.raise_()
        self.position_status_dot()

    def position_status_dot(self):
        if not hasattr(self, "status_dot"):
            return
        margin = 8
        self.status_dot.move(self.width() - self.status_dot.width() - margin, margin)
        self.status_dot.show()
        self.status_dot.raise_()

    def _apply_style(self):
        background = self.theme.elevated_card_background if self._hovered else self.theme.card_background
        border = self.theme.border_color
        self.setStyleSheet(
            f"""
            QFrame[sidebarAccountCard="true"] {{
                background: {background};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            """
        )
        self.role_label.setStyleSheet(f"color:{self.theme.text_secondary};font-size:10px;font-weight:700;")
        self.username_label.setStyleSheet(f"color:{self.theme.text_primary};font-size:12px;font-weight:700;")

    def apply_language(self, language):
        self.language = language or DEFAULT_LANGUAGE
        alignment = Qt.AlignRight if is_rtl_language(self.language) else Qt.AlignLeft
        self.role_label.setText(translate_text(self.role_title, self.language))
        username_source = str(self.username_label.property("i18n_source_text") or "")
        if username_source:
            self.username_label.setText(translate_text(username_source, self.language))
        self.role_label.setAlignment(alignment | Qt.AlignVCenter)
        self.username_label.setAlignment(alignment | Qt.AlignVCenter)
        self.setLayoutDirection(Qt.RightToLeft if is_rtl_language(self.language) else Qt.LeftToRight)
        self.position_status_dot()

    def apply_theme(self, theme):
        self.theme = theme
        self.status_dot.apply_theme(theme)
        self._apply_style()
        self.position_status_dot()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_status_dot()

    def showEvent(self, event):
        super().showEvent(event)
        self.position_status_dot()

    def enterEvent(self, event):
        self._hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)


class IncrementalTableModel(QAbstractTableModel):
    def __init__(self, headers, batch_size=200, parent=None):
        super().__init__(parent)
        self._source_headers = list(headers or [])
        self._headers = list(headers or [])
        self._batch_size = max(int(batch_size or 1), 1)
        self._all_rows = []
        self._loaded_count = 0
        self._empty_row = None

    def apply_translator(self, translator):
        if not callable(translator):
            return
        self._headers = [translator(header) for header in self._source_headers]
        if self._headers:
            self.headerDataChanged.emit(Qt.Horizontal, 0, len(self._headers) - 1)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        if self._all_rows:
            return self._loaded_count
        return 1 if self._empty_row else 0

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = self._resolve_row(index.row())
        if row is None:
            return None

        column = index.column()
        cells = row.get("cells", [])

        if role == Qt.DisplayRole:
            if column < len(cells):
                return str(cells[column])
            return ""

        if role == Qt.TextAlignmentRole:
            return row.get("alignments", {}).get(column)

        if role == Qt.ForegroundRole:
            color = row.get("foregrounds", {}).get(column)
            if not color:
                return None
            return QBrush(QColor(color))

        if role == Qt.FontRole:
            font_config = row.get("fonts", {}).get(column)
            if not font_config:
                return None
            font = QFont()
            if isinstance(font_config, dict):
                if "underline" in font_config:
                    font.setUnderline(bool(font_config.get("underline")))
                if "bold" in font_config:
                    font.setBold(bool(font_config.get("bold")))
            return font

        if role == Qt.UserRole:
            return row.get("user_data", {}).get(column)

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        return None

    def canFetchMore(self, parent=QModelIndex()):
        if parent.isValid():
            return False
        return self._loaded_count < len(self._all_rows)

    def fetchMore(self, parent=QModelIndex()):
        if parent.isValid() or not self.canFetchMore(parent):
            return

        remaining = len(self._all_rows) - self._loaded_count
        items_to_fetch = min(self._batch_size, remaining)
        start = self._loaded_count
        end = start + items_to_fetch - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._loaded_count += items_to_fetch
        self.endInsertRows()

    def set_rows(self, rows, empty_row=None):
        self.beginResetModel()
        self._all_rows = list(rows or [])
        self._empty_row = dict(empty_row) if empty_row else None
        self._loaded_count = min(len(self._all_rows), self._batch_size)
        self.endResetModel()

    def ensure_row_loaded(self, row_index):
        if row_index < 0 or row_index >= len(self._all_rows):
            return
        while self._loaded_count <= row_index and self.canFetchMore():
            self.fetchMore()

    def total_count(self):
        return len(self._all_rows)

    def visible_count(self):
        if self._all_rows:
            return self._loaded_count
        return 0

    def _resolve_row(self, row_index):
        if self._all_rows:
            if 0 <= row_index < self._loaded_count:
                return self._all_rows[row_index]
            return None
        if self._empty_row and row_index == 0:
            return self._empty_row
        return None


class TriggerChipWidget(QFrame):
    removed = Signal(str)

    def __init__(self, trigger_text):
        super().__init__()
        self.trigger_text = trigger_text
        self._hovered = False
        self.theme = THEMES[DEFAULT_THEME_NAME]
        self.setProperty("triggerChip", "true")
        self.setCursor(Qt.PointingHandCursor)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 9, 4)
        layout.setSpacing(5)

        self.label = QLabel(trigger_text)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background: transparent; border: none; font-size:12px; font-weight:500;")
        layout.addWidget(self.label)

        self.button = QPushButton("×")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setFixedSize(14, 14)
        self.button.setFlat(True)
        self.button.setFocusPolicy(Qt.NoFocus)
        self.button.setVisible(False)
        self.button.setProperty("triggerChipRemove", "true")
        self.button.clicked.connect(lambda: self.removed.emit(self.trigger_text))
        layout.addWidget(self.button)

        self._apply_style()

    def _apply_style(self):
        background = self.theme.chip_bg_hover if self._hovered else self.theme.chip_bg
        border = self.theme.chip_border_hover if self._hovered else self.theme.chip_border
        self.setStyleSheet(
            f"""
            QFrame[triggerChip="true"] {{
                background: {background};
                border: 1px solid {border};
                border-radius: 13px;
            }}
            """
        )
        self.label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                border: none;
                color: {self.theme.text_primary};
                font-size: 12px;
                font-weight: 500;
            }}
            """
        )
        self.button.setStyleSheet(
            f"""
            QPushButton[triggerChipRemove="true"] {{
                background: transparent;
                border: none;
                color: {self.theme.text_muted};
                padding: 0;
                margin: 0;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton[triggerChipRemove="true"]:hover {{
                background: transparent;
                border: none;
                color: {self.theme.text_primary};
            }}
            QPushButton[triggerChipRemove="true"]:pressed {{
                background: transparent;
                border: none;
                color: {self.theme.accent};
            }}
            """
        )

    def apply_theme(self, theme):
        self.theme = theme
        self._apply_style()

    def enterEvent(self, event):
        self._hovered = True
        self.button.setVisible(True)
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.button.setVisible(False)
        self._apply_style()
        super().leaveEvent(event)
