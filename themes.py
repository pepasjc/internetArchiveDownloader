"""Design tokens e folhas de estilo para o Internet Archive Downloader.

Toda a aparência sai de um único dicionário de tokens (`build_tokens`), que é
consumido tanto pelo QSS (`build_stylesheet`) quanto pelo código que pinta à mão
(delegates, gráfico de velocidade, ícones). Isso mantém tabela, sidebar e widgets
customizados sempre na mesma paleta.
"""

from string import Template


# ---------------------------------------------------------------------------
# Paletas base
# ---------------------------------------------------------------------------

MODES = ("dark", "light")

PALETTES = {
    "dark": {
        "bg": "#0d1117",
        "sidebar": "#0a0e14",
        "surface": "#151b23",
        "surface_alt": "#1c232d",
        "surface_hover": "#232c38",
        "border": "#252d38",
        "border_strong": "#39434f",
        "text": "#e6edf3",
        "text_muted": "#9aa7b4",
        "text_faint": "#68737f",
        "shadow": "#05070a",
        "success": "#3fb950",
        "success_soft": "#16281c",
        "warning": "#d29922",
        "warning_soft": "#2b2213",
        "danger": "#f85149",
        "danger_soft": "#2d1618",
        "info": "#58a6ff",
        "info_soft": "#0f2438",
        "neutral": "#8b949e",
        "neutral_soft": "#20262d",
        "track": "#232c38",
    },
    "light": {
        "bg": "#f2f4f8",
        "sidebar": "#ffffff",
        "surface": "#ffffff",
        "surface_alt": "#f6f8fb",
        "surface_hover": "#eaeff6",
        "border": "#e0e6ee",
        "border_strong": "#c3cdda",
        "text": "#111827",
        "text_muted": "#55627a",
        "text_faint": "#8a94a6",
        "shadow": "#c8d0dc",
        "success": "#15803d",
        "success_soft": "#e3f7e9",
        "warning": "#b45309",
        "warning_soft": "#fdf1dc",
        "danger": "#c62828",
        "danger_soft": "#fdeaea",
        "info": "#1d68d6",
        "info_soft": "#e6f0fe",
        "neutral": "#64748b",
        "neutral_soft": "#eef1f5",
        "track": "#e4e9f0",
    },
}

# Acentos disponíveis: (normal, hover, pressed, tint dark, tint light)
ACCENTS = {
    "blue":    ("#3b82f6", "#2f74e6", "#2563eb", "#132840", "#e5efff"),
    "violet":  ("#8b5cf6", "#7c4ef0", "#6d3fe0", "#1f1a3a", "#f0eaff"),
    "emerald": ("#10b981", "#0ea472", "#0b8c62", "#0d2a24", "#e2f7f0"),
    "amber":   ("#f59e0b", "#e08f08", "#c47c06", "#2e2411", "#fdf1d9"),
    "rose":    ("#f43f5e", "#e23554", "#c72c48", "#33161f", "#ffe8ec"),
    "cyan":    ("#06b6d4", "#059fba", "#0587a0", "#0a2830", "#e0f6fa"),
}

DENSITIES = {
    "comfortable": {"row_h": 40, "ctl_h": 34, "pad_v": 8, "pad_h": 14, "font": 13},
    "compact":     {"row_h": 30, "ctl_h": 28, "pad_v": 5, "pad_h": 10, "font": 12},
}

DEFAULT_MODE = "dark"
DEFAULT_ACCENT = "blue"
DEFAULT_DENSITY = "comfortable"

FONT_STACK = ("-apple-system, BlinkMacSystemFont, 'Segoe UI Variable Text', "
              "'Segoe UI', Inter, Roboto, Ubuntu, sans-serif")


def build_tokens(mode=DEFAULT_MODE, accent=DEFAULT_ACCENT, density=DEFAULT_DENSITY):
    """Monta o dicionário completo de tokens para (mode, accent, density)."""
    mode = mode if mode in PALETTES else DEFAULT_MODE
    accent = accent if accent in ACCENTS else DEFAULT_ACCENT
    density = density if density in DENSITIES else DEFAULT_DENSITY

    tokens = dict(PALETTES[mode])
    a_norm, a_hover, a_press, tint_dark, tint_light = ACCENTS[accent]

    tokens.update(
        {
            "mode": mode,
            "accent": a_norm,
            "accent_hover": a_hover,
            "accent_press": a_press,
            "accent_fg": "#ffffff",
            "accent_soft": tint_dark if mode == "dark" else tint_light,
            "sel_bg": tint_dark if mode == "dark" else tint_light,
            "sel_fg": tokens["text"],
            "font_stack": FONT_STACK,
        }
    )
    tokens.update({k: str(v) for k, v in DENSITIES[density].items()})
    tokens["row_h_px"] = DENSITIES[density]["row_h"]
    tokens["ctl_h_px"] = DENSITIES[density]["ctl_h"]
    return tokens


# Cor por status de download — usado pelos delegates e pelo gráfico.
def status_palette(tokens):
    return {
        "Baixando": (tokens["info"], tokens["info_soft"]),
        "Downloading": (tokens["info"], tokens["info_soft"]),
        "Concluído": (tokens["success"], tokens["success_soft"]),
        "Completed": (tokens["success"], tokens["success_soft"]),
        "Pausado": (tokens["warning"], tokens["warning_soft"]),
        "Paused": (tokens["warning"], tokens["warning_soft"]),
        "Erro": (tokens["danger"], tokens["danger_soft"]),
        "Error": (tokens["danger"], tokens["danger_soft"]),
        "Cancelado": (tokens["neutral"], tokens["neutral_soft"]),
        "Cancelled": (tokens["neutral"], tokens["neutral_soft"]),
        "Aguardando": (tokens["neutral"], tokens["neutral_soft"]),
        "Waiting": (tokens["neutral"], tokens["neutral_soft"]),
    }


# ---------------------------------------------------------------------------
# Folha de estilo
# ---------------------------------------------------------------------------

_QSS = Template(
    """
* { outline: 0; }

QWidget {
    font-family: $font_stack;
    font-size: ${font}px;
    color: $text;
}

QMainWindow, QDialog { background-color: $bg; }

QToolTip {
    background-color: $surface_alt;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 6px;
    padding: 6px 9px;
}

/* ---------------- Shell / sidebar ---------------- */

QFrame#Sidebar {
    background-color: $sidebar;
    border: none;
    border-right: 1px solid $border;
}

QLabel#BrandTitle {
    font-size: ${font}px;
    font-weight: 700;
    color: $text;
    letter-spacing: 0.2px;
}

QLabel#BrandSub {
    font-size: 10px;
    color: $text_faint;
    letter-spacing: 0.6px;
}

QToolButton#NavButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: ${pad_v}px 10px;
    color: $text_muted;
    font-size: ${font}px;
    font-weight: 500;
    text-align: left;
}

QToolButton#NavButton:hover {
    background-color: $surface_hover;
    color: $text;
}

QToolButton#NavButton:checked {
    background-color: $accent_soft;
    color: $accent;
    font-weight: 600;
}

QFrame#SidebarSep {
    background-color: $border;
    max-height: 1px;
    border: none;
}

/* ---------------- Cards / superfícies ---------------- */

QFrame#Card, QFrame[card="true"] {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 10px;
}

QFrame#TopBar {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 10px;
}

QFrame#StatusStrip {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 10px;
}

QFrame#VSep {
    background-color: $border;
    max-width: 1px;
    border: none;
}

QLabel#PageTitle {
    font-size: 19px;
    font-weight: 700;
    color: $text;
}

QLabel#PageSubtitle, QLabel[class="note"] {
    color: $text_faint;
    font-size: 11px;
}

QLabel#SectionTitle, QLabel[class="subsection-header"] {
    font-size: 13px;
    font-weight: 700;
    color: $text;
    letter-spacing: 0.2px;
}

QLabel[class="section-header"] {
    font-size: 19px;
    font-weight: 700;
    color: $text;
}

QLabel[class="muted"] { color: $text_muted; }
QLabel[class="success"] { color: $success; font-weight: 600; }
QLabel[class="danger"]  { color: $danger; font-weight: 600; }

QLabel#StatValue {
    font-size: 14px;
    font-weight: 700;
    color: $text;
}

QLabel#StatLabel {
    font-size: 10px;
    color: $text_faint;
    letter-spacing: 0.5px;
}

/* ---------------- Entradas ---------------- */

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {
    background-color: $surface_alt;
    border: 1px solid $border;
    border-radius: 8px;
    color: $text;
    selection-background-color: $accent;
    selection-color: $accent_fg;
    min-height: ${ctl_h}px;
}

QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {
    padding: 0px ${pad_h}px;
}

QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: $border_strong; }

QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {
    border-color: $accent;
    background-color: $surface;
}

QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    color: $text_faint;
    background-color: $surface;
}

QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid $text_muted;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background-color: $surface;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: $accent_soft;
    selection-color: $text;
    outline: 0;
}

/* SpinBox: nunca usar padding aqui — corta os botões de incremento. */
QSpinBox { min-width: 76px; padding-right: 2px; }
QSpinBox::up-button, QSpinBox::down-button {
    border: none;
    background: transparent;
    width: 18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background-color: $surface_hover; }
QSpinBox::up-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid $text_muted;
}
QSpinBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid $text_muted;
}

/* ---------------- Botões ---------------- */

QPushButton {
    background-color: $accent;
    color: $accent_fg;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0px ${pad_h}px;
    min-height: ${ctl_h}px;
    font-weight: 600;
    font-size: ${font}px;
}
QPushButton:hover   { background-color: $accent_hover; }
QPushButton:pressed { background-color: $accent_press; }
QPushButton:disabled {
    background-color: $surface_alt;
    color: $text_faint;
    border-color: $border;
}

QPushButton[class="secondary"], QPushButton[class="ghost"] {
    background-color: $surface_alt;
    color: $text;
    border: 1px solid $border;
}
QPushButton[class="secondary"]:hover, QPushButton[class="ghost"]:hover {
    background-color: $surface_hover;
    border-color: $border_strong;
}
QPushButton[class="secondary"]:disabled, QPushButton[class="ghost"]:disabled {
    color: $text_faint;
    background-color: $surface;
}

QPushButton[class="success"] { background-color: $success; color: #ffffff; }
QPushButton[class="danger"]  { background-color: $danger;  color: #ffffff; }
QPushButton[class="success"]:hover { background-color: $success; }
QPushButton[class="danger"]:hover  { background-color: $danger; }

/* Botões de ação da toolbar (ícone + rótulo) */
QToolButton#ToolAction {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 5px 10px;
    color: $text;
    font-size: ${font}px;
    font-weight: 500;
}
QToolButton#ToolAction:hover {
    background-color: $surface_hover;
    border-color: $border;
}
QToolButton#ToolAction:pressed { background-color: $surface_alt; }
QToolButton#ToolAction:disabled { color: $text_faint; }

/* Chips de filtro */
QToolButton#FilterChip {
    background-color: transparent;
    border: 1px solid $border;
    border-radius: 13px;
    padding: 3px 12px;
    color: $text_muted;
    font-size: 12px;
    font-weight: 500;
}
QToolButton#FilterChip:hover { background-color: $surface_hover; color: $text; }
QToolButton#FilterChip:checked {
    background-color: $accent_soft;
    border-color: $accent;
    color: $accent;
    font-weight: 600;
}

/* ---------------- Tabelas ---------------- */

QTableWidget, QTableView, QTreeView {
    background-color: $surface;
    alternate-background-color: $surface_alt;
    border: 1px solid $border;
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: $sel_bg;
    selection-color: $text;
}

QTableWidget::item, QTableView::item {
    padding: 0px 10px;
    border: none;
    border-bottom: 1px solid $border;
}
QTableWidget::item:hover { background-color: $surface_hover; }
QTableWidget::item:selected, QTableView::item:selected {
    background-color: $sel_bg;
    color: $text;
}

QHeaderView { background-color: transparent; }
QHeaderView::section {
    background-color: $surface_alt;
    color: $text_faint;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid $border;
    border-right: 1px solid $border;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}
QHeaderView::section:last { border-right: none; }
QHeaderView::section:hover { color: $text; background-color: $surface_hover; }
QTableCornerButton::section { background-color: $surface_alt; border: none; }

/* ---------------- Listas ---------------- */

QListWidget {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 5px;
}
QListWidget::item {
    padding: 6px 10px;
    border-radius: 6px;
    color: $text;
}
QListWidget::item:hover { background-color: $surface_hover; }
QListWidget::item:selected { background-color: $sel_bg; color: $text; }

/* ---------------- Barras de progresso ---------------- */

QProgressBar {
    border: none;
    border-radius: 5px;
    background-color: $track;
    text-align: center;
    color: $text;
    min-height: 10px;
    max-height: 10px;
}
QProgressBar::chunk { background-color: $accent; border-radius: 5px; }

/* ---------------- Abas (painel de detalhes) ---------------- */

QTabWidget::pane {
    border: none;
    border-top: 1px solid $border;
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    color: $text_muted;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 7px 14px;
    font-weight: 500;
    font-size: 12px;
}
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected {
    color: $accent;
    border-bottom: 2px solid $accent;
    font-weight: 600;
}

/* ---------------- CheckBox ---------------- */

QCheckBox { spacing: 8px; color: $text; background: transparent; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid $border_strong;
    background-color: $surface_alt;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent;
}

/* ---------------- Scrollbars ---------------- */

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

QScrollBar:vertical {
    border: none; background: transparent; width: 10px; margin: 2px;
}
QScrollBar::handle:vertical {
    background-color: $border_strong; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background-color: $text_faint; }
QScrollBar:horizontal {
    border: none; background: transparent; height: 10px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background-color: $border_strong; border-radius: 5px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background-color: $text_faint; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------------- Splitter ---------------- */

QSplitter::handle { background-color: transparent; }
QSplitter::handle:vertical { height: 8px; }
QSplitter::handle:horizontal { width: 8px; }
QSplitter::handle:hover { background-color: $accent_soft; }

/* ---------------- Menus ---------------- */

QMenu {
    background-color: $surface;
    border: 1px solid $border_strong;
    border-radius: 10px;
    padding: 5px;
}
QMenu::item {
    padding: 7px 26px 7px 12px;
    border-radius: 6px;
    color: $text;
}
QMenu::item:selected { background-color: $accent_soft; color: $text; }
QMenu::item:disabled { color: $text_faint; }
QMenu::separator { height: 1px; background: $border; margin: 5px 8px; }

/* ---------------- StatusBar / MessageBox ---------------- */

QStatusBar {
    background-color: $bg;
    color: $text_muted;
    border-top: 1px solid $border;
}
QStatusBar::item { border: none; }

QMessageBox { background-color: $surface; }
QMessageBox QLabel { color: $text; }
"""
)


def build_stylesheet(mode=DEFAULT_MODE, accent=DEFAULT_ACCENT, density=DEFAULT_DENSITY):
    """QSS completo para a combinação de tokens informada."""
    return _QSS.substitute(build_tokens(mode, accent, density))


def get_current_theme():
    """Compatibilidade: tema padrão da aplicação."""
    return build_stylesheet()
