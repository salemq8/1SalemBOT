from dataclasses import dataclass


@dataclass(frozen=True)
class ButtonColors:
    background: str
    hover: str
    text: str
    border: str


@dataclass(frozen=True)
class StatusColors:
    background: str
    border: str
    text: str
    title: str
    body: str


@dataclass(frozen=True)
class ThemePalette:
    name: str
    display_name: str
    window_bg: str
    window_bg_alt: str
    sidebar_bg: str
    sidebar_bg_alt: str
    sidebar_border: str
    brand_bg: str
    brand_bg_alt: str
    brand_border: str
    card_bg: str
    card_border: str
    subtle_bg: str
    subtle_border: str
    text_primary: str
    text_secondary: str
    text_muted: str
    text_inverse: str
    accent: str
    accent_hover: str
    accent_border: str
    accent_soft: str
    accent_secondary: str
    success: str
    success_hover: str
    success_border: str
    danger: str
    danger_hover: str
    danger_border: str
    warning: str
    warning_hover: str
    warning_border: str
    warning_text: str
    muted_button: str
    muted_button_hover: str
    muted_button_border: str
    input_bg: str
    input_border: str
    input_focus: str
    input_text: str
    menu_bg: str
    menu_border: str
    menu_hover: str
    nav_text: str
    nav_hover_bg: str
    nav_hover_border: str
    nav_active_bg: str
    nav_active_border: str
    nav_active_text: str
    account_bg: str
    account_bg_hover: str
    account_border: str
    chip_bg: str
    chip_bg_hover: str
    chip_border: str
    chip_border_hover: str
    chip_remove_bg: str
    chip_remove_hover: str
    chart_messages: str
    chart_commands: str
    chart_timeouts: str
    chart_grid: str
    chart_axis: str
    chart_tooltip_bg: str
    chart_tooltip_border: str
    chart_plot_bg: str
    thumbnail_bg: str
    thumbnail_border: str
    avatar_bg: str
    status_neutral: StatusColors
    status_success: StatusColors
    status_info: StatusColors
    status_warning: StatusColors
    status_error: StatusColors

    def button_colors(self, role: str) -> ButtonColors:
        role_map = {
            "primary": ButtonColors(self.accent, self.accent_hover, self.text_inverse, self.accent_border),
            "success": ButtonColors(self.success, self.success_hover, self.text_inverse, self.success_border),
            "danger": ButtonColors(self.danger, self.danger_hover, self.text_inverse, self.danger_border),
            "warning": ButtonColors(self.warning, self.warning_hover, self.warning_text, self.warning_border),
            "muted": ButtonColors(self.muted_button, self.muted_button_hover, self.text_primary, self.muted_button_border),
            "twitch": ButtonColors(self.accent_secondary, self.accent_hover, self.text_inverse, self.accent_border),
            "ghost": ButtonColors(self.elevated_card_background, self.nav_hover_bg, self.text_primary, self.border_color),
            "chip-remove": ButtonColors(self.chip_remove_bg, self.chip_remove_hover, self.text_inverse, self.chip_border_hover),
        }
        return role_map.get(role, role_map["muted"])

    @property
    def app_background(self) -> str:
        return self.window_bg

    @property
    def panel_background(self) -> str:
        return self.window_bg_alt

    @property
    def card_background(self) -> str:
        return self.card_bg

    @property
    def elevated_card_background(self) -> str:
        return self.subtle_bg

    @property
    def border_color(self) -> str:
        return self.card_border

    @property
    def accent_color(self) -> str:
        return self.accent

    def status_colors(self, tone: str) -> StatusColors:
        palette = {
            "neutral": self.status_neutral,
            "success": self.status_success,
            "info": self.status_info,
            "warning": self.status_warning,
            "danger": self.status_error,
            "error": self.status_error,
        }
        return palette.get(tone, self.status_neutral)


def _make_theme(
    *,
    name: str,
    display_name: str,
    accent: str,
    accent_hover: str,
    accent_border: str,
    accent_soft: str,
    accent_secondary: str,
    window_bg: str,
    window_bg_alt: str,
    sidebar_bg: str,
    sidebar_bg_alt: str,
    brand_bg: str,
    brand_bg_alt: str,
    card_bg: str,
    subtle_bg: str,
    text_primary: str,
    text_secondary: str,
    text_muted: str,
    input_bg: str,
    menu_bg: str,
    nav_active_bg: str,
    chart_messages: str,
    chart_commands: str,
    chart_timeouts: str,
    avatar_bg: str,
    card_border: str | None = None,
    subtle_border: str | None = None,
    sidebar_border: str | None = None,
    brand_border: str | None = None,
    input_border: str | None = None,
    input_focus: str | None = None,
    menu_border: str | None = None,
    menu_hover: str | None = None,
    nav_text: str | None = None,
    nav_hover_bg: str | None = None,
    nav_hover_border: str | None = None,
    nav_active_border: str | None = None,
    nav_active_text: str | None = None,
    account_bg: str | None = None,
    account_bg_hover: str | None = None,
    account_border: str | None = None,
    chip_bg: str | None = None,
    chip_bg_hover: str | None = None,
    chip_border: str | None = None,
    chip_border_hover: str | None = None,
    chip_remove_bg: str | None = None,
    chip_remove_hover: str | None = None,
    success: str | None = None,
    success_hover: str | None = None,
    success_border: str | None = None,
    danger: str | None = None,
    danger_hover: str | None = None,
    danger_border: str | None = None,
    warning: str | None = None,
    warning_hover: str | None = None,
    warning_border: str | None = None,
    warning_text: str | None = None,
    muted_button: str | None = None,
    muted_button_hover: str | None = None,
    muted_button_border: str | None = None,
    chart_grid: str | None = None,
    chart_axis: str | None = None,
    chart_tooltip_bg: str | None = None,
    chart_tooltip_border: str | None = None,
    chart_plot_bg: str | None = None,
    thumbnail_bg: str | None = None,
    thumbnail_border: str | None = None,
):
    card_border = card_border or "#22304a"
    subtle_border = subtle_border or "#2b3b5b"
    sidebar_border = sidebar_border or "#142033"
    brand_border = brand_border or "#23344f"
    input_border = input_border or "#2a3a58"
    input_focus = input_focus or accent_border
    menu_border = menu_border or "#24344f"
    menu_hover = menu_hover or "#172235"
    nav_text = nav_text or text_secondary
    nav_hover_bg = nav_hover_bg or "#142033"
    nav_hover_border = nav_hover_border or "#22314a"
    nav_active_border = nav_active_border or accent_border
    nav_active_text = nav_active_text or "#ffffff"
    account_bg = account_bg or card_bg
    account_bg_hover = account_bg_hover or subtle_bg
    account_border = account_border or card_border
    chip_bg = chip_bg or subtle_bg
    chip_bg_hover = chip_bg_hover or "#2b3a59"
    chip_border = chip_border or "#3a4d73"
    chip_border_hover = chip_border_hover or accent_border
    chip_remove_bg = chip_remove_bg or "#344762"
    chip_remove_hover = chip_remove_hover or "#466180"
    success = success or "#179954"
    success_hover = success_hover or "#1db262"
    success_border = success_border or "#26c26e"
    danger = danger or "#dc3f4f"
    danger_hover = danger_hover or "#ef5564"
    danger_border = danger_border or "#f17482"
    warning = warning or "#f3a324"
    warning_hover = warning_hover or "#ffb53f"
    warning_border = warning_border or "#ffcc73"
    warning_text = warning_text or "#111827"
    muted_button = muted_button or "#314155"
    muted_button_hover = muted_button_hover or "#3e526b"
    muted_button_border = muted_button_border or "#536780"
    chart_grid = chart_grid or "#233249"
    chart_axis = chart_axis or "#7c90ad"
    chart_tooltip_bg = chart_tooltip_bg or "#121b2a"
    chart_tooltip_border = chart_tooltip_border or "#24344f"
    chart_plot_bg = chart_plot_bg or input_bg
    thumbnail_bg = thumbnail_bg or input_bg
    thumbnail_border = thumbnail_border or card_border

    return ThemePalette(
        name=name,
        display_name=display_name,
        window_bg=window_bg,
        window_bg_alt=window_bg_alt,
        sidebar_bg=sidebar_bg,
        sidebar_bg_alt=sidebar_bg_alt,
        sidebar_border=sidebar_border,
        brand_bg=brand_bg,
        brand_bg_alt=brand_bg_alt,
        brand_border=brand_border,
        card_bg=card_bg,
        card_border=card_border,
        subtle_bg=subtle_bg,
        subtle_border=subtle_border,
        text_primary=text_primary,
        text_secondary=text_secondary,
        text_muted=text_muted,
        text_inverse="#ffffff",
        accent=accent,
        accent_hover=accent_hover,
        accent_border=accent_border,
        accent_soft=accent_soft,
        accent_secondary=accent_secondary,
        success=success,
        success_hover=success_hover,
        success_border=success_border,
        danger=danger,
        danger_hover=danger_hover,
        danger_border=danger_border,
        warning=warning,
        warning_hover=warning_hover,
        warning_border=warning_border,
        warning_text=warning_text,
        muted_button=muted_button,
        muted_button_hover=muted_button_hover,
        muted_button_border=muted_button_border,
        input_bg=input_bg,
        input_border=input_border,
        input_focus=input_focus,
        input_text=text_primary,
        menu_bg=menu_bg,
        menu_border=menu_border,
        menu_hover=menu_hover,
        nav_text=nav_text,
        nav_hover_bg=nav_hover_bg,
        nav_hover_border=nav_hover_border,
        nav_active_bg=nav_active_bg,
        nav_active_border=nav_active_border,
        nav_active_text=nav_active_text,
        account_bg=account_bg,
        account_bg_hover=account_bg_hover,
        account_border=account_border,
        chip_bg=chip_bg,
        chip_bg_hover=chip_bg_hover,
        chip_border=chip_border,
        chip_border_hover=chip_border_hover,
        chip_remove_bg=chip_remove_bg,
        chip_remove_hover=chip_remove_hover,
        chart_messages=chart_messages,
        chart_commands=chart_commands,
        chart_timeouts=chart_timeouts,
        chart_grid=chart_grid,
        chart_axis=chart_axis,
        chart_tooltip_bg=chart_tooltip_bg,
        chart_tooltip_border=chart_tooltip_border,
        chart_plot_bg=chart_plot_bg,
        thumbnail_bg=thumbnail_bg,
        thumbnail_border=thumbnail_border,
        avatar_bg=avatar_bg,
        status_neutral=StatusColors(card_bg, subtle_border, text_secondary, text_primary, text_secondary),
        status_success=StatusColors("#10301d", success_border, "#bbf7d0", "#dcfce7", "#bbf7d0"),
        status_info=StatusColors("#13263c", accent_border, "#cde1ff", "#e3eeff", "#cde1ff"),
        status_warning=StatusColors("#36260f", warning_border, "#fdd78b", "#ffe8b5", "#fdd78b"),
        status_error=StatusColors("#3c1620", danger_border, "#fecdd3", "#ffe4e6", "#fecdd3"),
    )


THEMES = {
    "blue": _make_theme(
        name="blue",
        display_name="Blue",
        accent="#3b82f6",
        accent_hover="#5b97ff",
        accent_border="#72a7ff",
        accent_soft="#172554",
        accent_secondary="#7c3aed",
        window_bg="#0b1220",
        window_bg_alt="#101b31",
        sidebar_bg="#08101d",
        sidebar_bg_alt="#0b1629",
        brand_bg="#0e1a2f",
        brand_bg_alt="#14223b",
        card_bg="#111b2f",
        subtle_bg="#162238",
        text_primary="#f8fbff",
        text_secondary="#c7d2e3",
        text_muted="#7e90ad",
        input_bg="#091222",
        menu_bg="#0f1728",
        nav_active_bg="#17386b",
        chart_messages="#6aa2ff",
        chart_commands="#3dd5a0",
        chart_timeouts="#f472b6",
        avatar_bg="#0f766e",
    ),
    "pink": _make_theme(
        name="pink",
        display_name="Pink",
        accent="#ec4899",
        accent_hover="#f06bac",
        accent_border="#f79fc8",
        accent_soft="#4a1633",
        accent_secondary="#f97316",
        window_bg="#160d17",
        window_bg_alt="#261227",
        sidebar_bg="#120811",
        sidebar_bg_alt="#1c0d1d",
        brand_bg="#241127",
        brand_bg_alt="#321535",
        card_bg="#241427",
        subtle_bg="#301b33",
        text_primary="#fff7fb",
        text_secondary="#efd1e3",
        text_muted="#b18da3",
        input_bg="#1a0f1c",
        menu_bg="#241427",
        nav_active_bg="#7a2351",
        chart_messages="#ff85c2",
        chart_commands="#68e0c3",
        chart_timeouts="#ffc857",
        avatar_bg="#be185d",
    ),
    "purple": _make_theme(
        name="purple",
        display_name="Purple",
        accent="#8b5cf6",
        accent_hover="#a47af8",
        accent_border="#c0a5ff",
        accent_soft="#2f1b52",
        accent_secondary="#ec4899",
        window_bg="#0f0c1a",
        window_bg_alt="#19122a",
        sidebar_bg="#0a0814",
        sidebar_bg_alt="#120d21",
        brand_bg="#171129",
        brand_bg_alt="#20163a",
        card_bg="#19132b",
        subtle_bg="#22193a",
        text_primary="#faf8ff",
        text_secondary="#d8d0f2",
        text_muted="#9287bf",
        input_bg="#0f0b1d",
        menu_bg="#171129",
        nav_active_bg="#472e91",
        chart_messages="#b58cff",
        chart_commands="#4de0b1",
        chart_timeouts="#ff7ecf",
        avatar_bg="#6d28d9",
    ),
    "dark": _make_theme(
        name="dark",
        display_name="Dark",
        accent="#22c55e",
        accent_hover="#38d46f",
        accent_border="#74e39e",
        accent_soft="#153222",
        accent_secondary="#4b5563",
        window_bg="#050608",
        window_bg_alt="#0d1014",
        sidebar_bg="#030405",
        sidebar_bg_alt="#090b0e",
        brand_bg="#0d1014",
        brand_bg_alt="#151a21",
        card_bg="#101317",
        subtle_bg="#161b22",
        text_primary="#f8fafc",
        text_secondary="#d2d8e1",
        text_muted="#7f8b99",
        input_bg="#07090c",
        menu_bg="#12161b",
        nav_active_bg="#1d3d2a",
        chart_messages="#64b5ff",
        chart_commands="#4ade80",
        chart_timeouts="#f87171",
        avatar_bg="#14532d",
    ),
    "falcon-neon": _make_theme(
        name="falcon-neon",
        display_name="Falcon Neon",
        accent="#19d7e0",
        accent_hover="#27f0ff",
        accent_border="#27f0ff",
        accent_soft="#0d3f42",
        accent_secondary="#0f6f70",
        window_bg="#07141a",
        window_bg_alt="#091c22",
        sidebar_bg="#061116",
        sidebar_bg_alt="#08191f",
        brand_bg="#0a2329",
        brand_bg_alt="#0d3033",
        card_bg="#0b2d2f",
        subtle_bg="#0a2528",
        text_primary="#f5f7fa",
        text_secondary="#c7d7dd",
        text_muted="#9db3bb",
        input_bg="#081d22",
        menu_bg="#0a2025",
        nav_active_bg="#0d353a",
        chart_messages="#27f0ff",
        chart_commands="#19d7e0",
        chart_timeouts="#39ff14",
        avatar_bg="#0f6f70",
        card_border="#0f6f70",
        subtle_border="#138587",
        sidebar_border="#0d5051",
        brand_border="#19d7e0",
        input_border="#0f6f70",
        input_focus="#27f0ff",
        menu_border="#0f6f70",
        menu_hover="#0e3034",
        nav_text="#c9d9df",
        nav_hover_bg="#0b2a2d",
        nav_hover_border="#19d7e0",
        nav_active_border="#27f0ff",
        nav_active_text="#f5f7fa",
        account_bg="#092327",
        account_bg_hover="#0c2e33",
        account_border="#19d7e0",
        chip_bg="#0c282d",
        chip_bg_hover="#10343a",
        chip_border="#138587",
        chip_border_hover="#27f0ff",
        chip_remove_bg="#0f5457",
        chip_remove_hover="#14777a",
        success="#39ff14",
        success_hover="#62ff42",
        success_border="#8aff71",
        danger="#ff4d6d",
        danger_hover="#ff6783",
        danger_border="#ff8da2",
        warning="#ffd166",
        warning_hover="#ffdc88",
        warning_border="#ffe7aa",
        warning_text="#07141a",
        muted_button="#10363a",
        muted_button_hover="#13454a",
        muted_button_border="#19d7e0",
        chart_grid="#114448",
        chart_axis="#9db3bb",
        chart_tooltip_bg="#081b21",
        chart_tooltip_border="#27f0ff",
        chart_plot_bg="#07171b",
        thumbnail_bg="#07171b",
        thumbnail_border="#19d7e0",
    ),
}

DEFAULT_THEME_NAME = "blue"


class ThemeManager:
    def __init__(self, initial_name: str | None = None):
        self.current_name = DEFAULT_THEME_NAME
        self.current_theme = THEMES[DEFAULT_THEME_NAME]
        self.set_theme(initial_name or DEFAULT_THEME_NAME)

    def set_theme(self, name: str):
        if name not in THEMES:
            name = DEFAULT_THEME_NAME
        self.current_name = name
        self.current_theme = THEMES[name]
        return self.current_theme

    def list_choices(self):
        return [(name, theme.display_name) for name, theme in THEMES.items()]


def build_combo_popup_stylesheet(theme: ThemePalette):
    return f"""
    QListView {{
        background-color: {theme.panel_background};
        color: {theme.text_primary};
        border: 1px solid {theme.border_color};
        border-radius: 8px;
        padding: 6px;
        outline: none;
        selection-background-color: {theme.accent_color};
        selection-color: {theme.text_inverse};
    }}
    QListView::item {{
        color: {theme.text_primary};
        min-height: 28px;
        padding: 7px 10px;
        border-radius: 6px;
    }}
    QListView::item:hover {{
        background-color: {theme.accent_color};
        color: {theme.text_inverse};
    }}
    QListView::item:selected {{
        background-color: {theme.accent_color};
        color: {theme.text_inverse};
    }}
    """


def build_app_stylesheet(theme: ThemePalette):
    def button_rule(role: str):
        colors = theme.button_colors(role)
        return f"""
        QPushButton[buttonRole="{role}"] {{
            background-color: {colors.background};
            color: {colors.text};
            border: 1px solid {colors.border};
            border-radius: 12px;
            padding: 10px 16px;
            font-size: 13px;
            font-weight: 700;
            min-height: 18px;
        }}
        QPushButton[buttonRole="{role}"]:hover {{
            background-color: {colors.hover};
            border-color: {colors.border};
        }}
        QPushButton[buttonRole="{role}"]:pressed {{
            background-color: {colors.hover};
            padding-top: 11px;
            padding-bottom: 9px;
        }}
        QPushButton[buttonRole="{role}"]:focus {{
            border-color: {theme.accent_border};
        }}
        QPushButton[buttonRole="{role}"]:disabled {{
            color: {theme.text_muted};
            background-color: {theme.subtle_bg};
            border-color: {theme.card_border};
        }}
        """

    return f"""
    QWidget {{
        color: {theme.text_primary};
    }}
    QMainWindow {{
        background: {theme.app_background};
    }}
    QWidget#appRoot, QStackedWidget#mainStack {{
        background: {theme.app_background};
    }}
    QStackedWidget#mainStack > QWidget {{
        background: transparent;
    }}
    QFrame[cardFrame="true"] {{
        background: {theme.card_background};
        border: 1px solid {theme.border_color};
        border-radius: 18px;
    }}
    QFrame[cardFrame="true"]:hover {{
        border-color: {theme.subtle_border};
    }}
    QFrame[surfaceRole="sidebar"] {{
        background: {theme.panel_background};
        border-right: 1px solid {theme.sidebar_border};
    }}
    QFrame[surfaceRole="brand"] {{
        background: {theme.elevated_card_background};
        border: 1px solid {theme.border_color};
        border-radius: 18px;
    }}
    QFrame[surfaceRole="main"] {{
        background: {theme.app_background};
    }}
    QFrame[surfaceRole="subtle"] {{
        background: {theme.elevated_card_background};
        border: 1px solid {theme.border_color};
        border-radius: 12px;
    }}
    QFrame[surfaceRole="twitchStep"] {{
        background: {theme.elevated_card_background};
        border: 1px solid {theme.border_color};
        border-radius: 14px;
    }}
    QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget, QComboBox {{
        background-color: {theme.input_bg};
        color: {theme.input_text};
        border: 1px solid {theme.border_color};
        border-radius: 10px;
        padding: 8px;
        font-size: 13px;
        selection-background-color: {theme.accent_color};
        selection-color: {theme.text_inverse};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QListWidget:focus, QTableWidget:focus, QComboBox:focus {{
        border: 1px solid {theme.accent_color};
        background-color: {theme.input_bg};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 28px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {theme.panel_background};
        color: {theme.text_primary};
        border: 1px solid {theme.border_color};
        border-radius: 8px;
        padding: 6px;
        outline: none;
        selection-background-color: {theme.accent_color};
        selection-color: {theme.text_inverse};
    }}
    QComboBox QAbstractItemView::item {{
        color: {theme.text_primary};
        min-height: 28px;
        padding: 7px 10px;
        border-radius: 6px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {theme.accent_color};
        color: {theme.text_inverse};
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {theme.accent_color};
        color: {theme.text_inverse};
    }}
    QMenu {{
        background-color: {theme.panel_background};
        color: {theme.text_primary};
        border: 1px solid {theme.border_color};
        border-radius: 12px;
        padding: 8px;
    }}
    QMenu::item {{
        background-color: transparent;
        color: {theme.text_primary};
        padding: 8px 16px;
        border-radius: 8px;
    }}
    QMenu::item:selected {{
        background-color: {theme.accent_color};
        color: {theme.text_inverse};
    }}
    QPushButton {{
        background-color: {theme.muted_button};
        color: {theme.text_primary};
        border: 1px solid {theme.muted_button_border};
        border-radius: 12px;
        padding: 9px 14px;
        font-size: 13px;
        font-weight: 700;
    }}
    QPushButton:hover {{
        background-color: {theme.muted_button_hover};
        border-color: {theme.accent_border};
    }}
    QPushButton:pressed {{
        background-color: {theme.muted_button_hover};
        padding-top: 10px;
        padding-bottom: 8px;
    }}
    QPushButton:disabled {{
        background-color: {theme.elevated_card_background};
        color: {theme.text_muted};
        border-color: {theme.border_color};
    }}
    QCheckBox {{
        spacing: 8px;
        color: {theme.text_secondary};
        font-size: 13px;
        font-weight: 600;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        background-color: {theme.input_bg};
        border: 1px solid {theme.border_color};
    }}
    QCheckBox::indicator:hover {{
        border-color: {theme.accent_border};
    }}
    QCheckBox::indicator:checked {{
        background-color: {theme.accent};
        border-color: {theme.accent_border};
    }}
    QProgressBar {{
        background-color: {theme.input_bg};
        border: 1px solid {theme.border_color};
        border-radius: 8px;
        color: {theme.text_primary};
        min-height: 14px;
        text-align: center;
        font-size: 11px;
        font-weight: 700;
    }}
    QProgressBar::chunk {{
        background-color: {theme.accent};
        border-radius: 7px;
    }}
    QSlider::groove:horizontal {{
        background: {theme.subtle_bg};
        border: 1px solid {theme.subtle_border};
        height: 8px;
        border-radius: 4px;
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {theme.accent}, stop:1 {theme.accent_hover});
        border: 1px solid {theme.accent_border};
        height: 8px;
        border-radius: 4px;
    }}
    QSlider::handle:horizontal {{
        background: {theme.text_inverse};
        border: 2px solid {theme.accent_border};
        width: 16px;
        margin: -6px 0;
        border-radius: 8px;
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QListWidget {{
        background-color: {theme.input_bg};
        border: 1px solid {theme.border_color};
        border-radius: 12px;
        padding: 8px;
        selection-background-color: {theme.nav_active_bg};
        selection-color: {theme.text_primary};
    }}
    QListWidget::item {{
        padding: 8px 10px;
        border-radius: 8px;
        margin: 2px 0;
    }}
    QListWidget::item:hover {{
        background: {theme.elevated_card_background};
    }}
    QListWidget::item:selected {{
        background: {theme.nav_active_bg};
        border: 1px solid {theme.accent_border};
        color: {theme.nav_active_text};
    }}
    QTableView, QTableWidget {{
        alternate-background-color: {theme.elevated_card_background};
        selection-background-color: {theme.accent_color};
        selection-color: {theme.text_inverse};
    }}
    QHeaderView::section {{
        background: {theme.elevated_card_background};
        color: {theme.text_secondary};
        border: none;
        border-bottom: 1px solid {theme.border_color};
        padding: 8px;
        font-size: 12px;
        font-weight: 700;
    }}
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: transparent;
        border: none;
        margin: 2px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {theme.subtle_border};
        border-radius: 4px;
        min-height: 28px;
        min-width: 28px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
        background: {theme.accent_border};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        width: 0;
        height: 0;
        border: none;
        background: transparent;
    }}
    QPushButton, QComboBox, QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QTableWidget, QTableView {{
        transition: all 160ms ease-in-out;
    }}
    QLabel[labelRole="sectionTitle"] {{
        color: {theme.text_primary};
        font-size: 22px;
        font-weight: 700;
    }}
    QLabel[labelRole="cardTitle"] {{
        color: {theme.text_primary};
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel[labelRole="cardSubtitle"] {{
        color: {theme.text_muted};
        font-size: 12px;
    }}
    QLabel[labelRole="smallTitle"] {{
        color: {theme.text_primary};
        font-size: 13px;
        font-weight: 700;
    }}
    QLabel[labelRole="infoValue"] {{
        color: {theme.text_secondary};
        font-size: 14px;
    }}
    QLabel[labelRole="muted"] {{
        color: {theme.text_muted};
        font-size: 12px;
    }}
    QLabel[labelRole="mutedBody"] {{
        color: {theme.text_secondary};
        font-size: 13px;
    }}
    QLabel[labelRole="valueLarge"] {{
        color: {theme.text_primary};
        font-size: 16px;
        font-weight: 700;
    }}
    QLabel[labelRole="statusValue"] {{
        color: {theme.text_primary};
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel[labelRole="heroTitle"] {{
        color: {theme.text_primary};
        font-size: 30px;
        font-weight: 800;
    }}
    QLabel[labelRole="heroSubtitle"] {{
        color: {theme.text_secondary};
        font-size: 14px;
    }}
    QLabel[labelRole="heroMeta"] {{
        color: {theme.text_muted};
        font-size: 12px;
    }}
    QLabel[labelRole="statTitle"] {{
        color: {theme.text_secondary};
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
    }}
    QLabel[labelRole="statValue"] {{
        color: {theme.text_primary};
        font-size: 34px;
        font-weight: 800;
    }}
    QLabel[labelRole="statSubtitle"] {{
        color: {theme.text_muted};
        font-size: 12px;
    }}
    QLabel[labelRole="navLabel"] {{
        color: {theme.text_muted};
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
    }}
    QLabel[labelRole="brandTitle"] {{
        color: {theme.text_primary};
        font-size: 22px;
        font-weight: 800;
    }}
    QLabel[labelRole="brandSubtitle"] {{
        color: {theme.text_muted};
        font-size: 12px;
    }}
    QLabel[labelRole="stepTitle"] {{
        color: {theme.text_primary};
        font-size: 13px;
        font-weight: 700;
    }}
    QLabel[labelRole="stepBody"] {{
        color: {theme.text_secondary};
        font-size: 12px;
    }}
    QLabel[badgeRole="step"] {{
        background: {theme.accent};
        color: {theme.text_inverse};
        border-radius: 14px;
        font-size: 12px;
        font-weight: 700;
    }}
    {button_rule("primary")}
    {button_rule("success")}
    {button_rule("danger")}
    {button_rule("warning")}
    {button_rule("muted")}
    {button_rule("twitch")}
    {button_rule("chip-remove")}
    """
