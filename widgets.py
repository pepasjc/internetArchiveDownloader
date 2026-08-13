"""Widgets e delegates customizados da interface.

Tudo aqui recebe o dicionário de tokens de `themes.build_tokens()` e sabe se
repintar quando o tema muda (`apply_tokens`).
"""

from collections import deque

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import icons
from themes import status_palette
from utils import format_size

# --- Data roles compartilhados pela tabela de downloads -------------------
ROLE_UID = Qt.ItemDataRole.UserRole
ROLE_PROGRESS = Qt.ItemDataRole.UserRole + 1
ROLE_STATUS = Qt.ItemDataRole.UserRole + 2
ROLE_SORT = Qt.ItemDataRole.UserRole + 3


def format_speed(bps):
    if not bps or bps <= 0:
        return "—"
    return f"{format_size(bps)}/s"


def format_eta(remaining_bytes, speed):
    """Tempo restante legível a partir de bytes e velocidade."""
    if not speed or speed <= 0 or remaining_bytes <= 0:
        return "—"
    secs = int(remaining_bytes / speed)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    if secs < 86400:
        return f"{secs // 3600}h {(secs % 3600) // 60:02d}m"
    return f"{secs // 86400}d {(secs % 86400) // 3600}h"


# ==========================================================================
# Blocos estruturais
# ==========================================================================


class Card(QFrame):
    """Superfície elevada com padding padrão."""

    def __init__(self, parent=None, margins=(16, 14, 16, 14), spacing=10):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(spacing)

    def layout(self):
        return self._layout


class SectionTitle(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")


class VSep(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VSep")
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFixedWidth(1)


class HSep(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarSep")
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)


class StatTile(QWidget):
    """Par valor/rótulo usado na barra de status inferior."""

    def __init__(self, label, value="—", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.caption = QLabel(label.upper())
        self.caption.setObjectName("StatLabel")
        lay.addWidget(self.value_label)
        lay.addWidget(self.caption)

    def set_value(self, text):
        self.value_label.setText(text)

    def set_label(self, text):
        self.caption.setText(text.upper())


# ==========================================================================
# Botões
# ==========================================================================


class ToolAction(QToolButton):
    """Botão de toolbar com ícone + rótulo, recolorível pelo tema."""

    def __init__(self, icon_name, text, tooltip=None, parent=None,
                 color_token="text", danger=False):
        super().__init__(parent)
        self.setObjectName("ToolAction")
        self._icon_name = icon_name
        self._color_token = "danger" if danger else color_token
        self._label = text
        # Sem rótulo desde a construção = sempre só ícone; com rótulo, o modo
        # compacto pode escondê-lo quando a janela encolhe.
        self._icon_only = not text
        self.setText(text)
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if self._icon_only
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.setIconSize(icons.ICON_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def apply_tokens(self, tokens):
        color = tokens.get(self._color_token, tokens["text"])
        self.setIcon(icons.icon(self._icon_name, color))

    def set_compact(self, compact):
        """Esconde o rótulo em janelas estreitas, mantendo-o como tooltip."""
        if self._icon_only:
            return
        if compact:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            if not self.toolTip():
                self.setToolTip(self._label)
        else:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)


class NavButton(QToolButton):
    """Item da barra lateral. Colapsa para somente ícone em janelas estreitas."""

    def __init__(self, icon_name, text, parent=None):
        super().__init__(parent)
        self.setObjectName("NavButton")
        self._icon_name = icon_name
        self._label = text
        self.setText(text)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setIconSize(QSize(19, 19))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self._tokens = None

    def apply_tokens(self, tokens):
        self._tokens = tokens
        self._refresh_icon()

    def _refresh_icon(self):
        if not self._tokens:
            return
        color = self._tokens["accent"] if self.isChecked() else self._tokens["text_muted"]
        self.setIcon(icons.icon(self._icon_name, color, size=19))

    def set_collapsed(self, collapsed):
        if collapsed:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.setToolTip(self._label)
        else:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.setToolTip("")

    def setChecked(self, checked):  # noqa: N802 (Qt API)
        super().setChecked(checked)
        self._refresh_icon()

    def nextCheckState(self):  # noqa: N802 (Qt API)
        super().nextCheckState()
        self._refresh_icon()


class FilterChip(QToolButton):
    """Chip de filtro com contador, no estilo dos gerenciadores modernos."""

    def __init__(self, key, label, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterChip")
        self.key = key
        self._label = label
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_count(0)

    def set_label(self, label):
        self._label = label
        self.set_count(self._count)

    def set_count(self, count):
        self._count = count
        self.setText(f"{self._label}  {count}" if count else self._label)


class SearchField(QLineEdit):
    """Campo de busca com ícone à esquerda e botão de limpar à direita."""

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self._action = self.addAction(
            icons.icon("search", "#9aa7b4"), QLineEdit.ActionPosition.LeadingPosition
        )

    def apply_tokens(self, tokens):
        self._action.setIcon(icons.icon("search", tokens["text_faint"]))


# ==========================================================================
# Sidebar
# ==========================================================================


class Sidebar(QFrame):
    """Navegação principal: marca, itens e rodapé com ações rápidas."""

    navigated = pyqtSignal(int)

    EXPANDED_WIDTH = 208
    COLLAPSED_WIDTH = 62

    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(self.EXPANDED_WIDTH)
        self._collapsed = False
        self._buttons = []
        self._tokens = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(11, 14, 11, 12)
        lay.setSpacing(4)

        brand = QWidget()
        brand_lay = QHBoxLayout(brand)
        brand_lay.setContentsMargins(3, 0, 0, 0)
        brand_lay.setSpacing(9)
        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(26, 26)
        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(0)
        self.brand_title = QLabel(title)
        self.brand_title.setObjectName("BrandTitle")
        self.brand_sub = QLabel(subtitle)
        self.brand_sub.setObjectName("BrandSub")
        text_box.addWidget(self.brand_title)
        text_box.addWidget(self.brand_sub)
        self.brand_text = QWidget()
        self.brand_text.setLayout(text_box)
        brand_lay.addWidget(self.brand_icon)
        brand_lay.addWidget(self.brand_text)
        brand_lay.addStretch()
        lay.addWidget(brand)

        lay.addSpacing(12)
        self._nav_layout = QVBoxLayout()
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(3)
        lay.addLayout(self._nav_layout)
        lay.addStretch()

        self.separator = HSep()
        lay.addWidget(self.separator)
        lay.addSpacing(6)

        self._footer_layout = QVBoxLayout()
        self._footer_layout.setContentsMargins(0, 0, 0, 0)
        self._footer_layout.setSpacing(3)
        lay.addLayout(self._footer_layout)

    def add_page(self, icon_name, label):
        btn = NavButton(icon_name, label)
        index = len(self._buttons)
        btn.clicked.connect(lambda _=False, i=index: self.navigated.emit(i))
        self._buttons.append(btn)
        self._nav_layout.addWidget(btn)
        return btn

    def add_footer_widget(self, widget):
        self._footer_layout.addWidget(widget)

    def set_current(self, index):
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)

    def set_collapsed(self, collapsed):
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.setFixedWidth(self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH)
        self.brand_text.setVisible(not collapsed)
        for btn in self._buttons:
            btn.set_collapsed(collapsed)
        for i in range(self._footer_layout.count()):
            w = self._footer_layout.itemAt(i).widget()
            if isinstance(w, NavButton):
                w.set_collapsed(collapsed)

    def apply_tokens(self, tokens):
        self._tokens = tokens
        self.brand_icon.setPixmap(
            icons.render_pixmap("app", tokens["accent"], size=26, stroke=1.8)
        )
        for btn in self._buttons:
            btn.apply_tokens(tokens)
        for i in range(self._footer_layout.count()):
            w = self._footer_layout.itemAt(i).widget()
            if hasattr(w, "apply_tokens"):
                w.apply_tokens(tokens)


# ==========================================================================
# Delegates da tabela
# ==========================================================================


class ThemedDelegate(QStyledItemDelegate):
    def __init__(self, tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self.statuses = status_palette(tokens)

    def apply_tokens(self, tokens):
        self.tokens = tokens
        self.statuses = status_palette(tokens)

    def _draw_background(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget
        )

    def _status_colors(self, status_text):
        return self.statuses.get(
            status_text, (self.tokens["neutral"], self.tokens["neutral_soft"])
        )


class StatusPillDelegate(ThemedDelegate):
    """Status como badge arredondado em vez de célula colorida."""

    def paint(self, painter, option, index):
        self._draw_background(painter, option, index)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if not text:
            return

        fg, bg = self._status_colors(text)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        font = QFont(option.font)
        font.setPointSizeF(max(7.5, option.font.pointSizeF() - 0.5))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        pill_w = min(metrics.horizontalAdvance(text) + 20, option.rect.width() - 12)
        pill_h = min(21, option.rect.height() - 8)
        rect = QRectF(
            option.rect.left() + 8,
            option.rect.center().y() - pill_h / 2 + 1,
            max(pill_w, 10),
            pill_h,
        )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, pill_h / 2, pill_h / 2)
        painter.setPen(QPen(QColor(fg)))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class ProgressDelegate(ThemedDelegate):
    """Barra de progresso desenhada (sem QProgressBar por linha)."""

    BAR_HEIGHT = 7

    def paint(self, painter, option, index):
        self._draw_background(painter, option, index)

        progress = index.data(ROLE_PROGRESS)
        progress = 0 if progress is None else max(0, min(100, int(progress)))
        status = index.data(ROLE_STATUS) or ""
        fg, _bg = self._status_colors(status)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pct_text = f"{progress}%"
        font = QFont(option.font)
        font.setPointSizeF(max(7.5, option.font.pointSizeF() - 0.5))
        painter.setFont(font)
        text_w = painter.fontMetrics().horizontalAdvance("100%") + 6

        left = option.rect.left() + 10
        right = option.rect.right() - 8
        bar_right = right - text_w
        bar_w = max(bar_right - left, 4)
        cy = option.rect.center().y() + 1
        track = QRectF(left, cy - self.BAR_HEIGHT / 2, bar_w, self.BAR_HEIGHT)
        radius = self.BAR_HEIGHT / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.tokens["track"]))
        painter.drawRoundedRect(track, radius, radius)

        if progress > 0:
            fill = QRectF(track)
            fill.setWidth(max(track.width() * progress / 100.0, self.BAR_HEIGHT))
            painter.setBrush(QColor(fg))
            painter.drawRoundedRect(fill, radius, radius)

        painter.setPen(QPen(QColor(self.tokens["text_muted"])))
        painter.drawText(
            QRect(int(bar_right), option.rect.top(), int(text_w), option.rect.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
            pct_text,
        )
        painter.restore()


class FileNameDelegate(ThemedDelegate):
    """Nome do arquivo com elisão no meio (preserva a extensão)."""

    def paint(self, painter, option, index):
        self._draw_background(painter, option, index)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.save()
        painter.setPen(QPen(QColor(self.tokens["text"])))
        rect = option.rect.adjusted(10, 0, -8, 0)
        elided = painter.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideMiddle, rect.width()
        )
        painter.drawText(
            rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided
        )
        painter.restore()


# ==========================================================================
# Visualizações
# ==========================================================================


class SpeedGraph(QWidget):
    """Sparkline preenchido da velocidade agregada (últimos N segundos)."""

    def __init__(self, capacity=90, parent=None):
        super().__init__(parent)
        self.samples = deque([0.0] * capacity, maxlen=capacity)
        self.capacity = capacity
        self.tokens = None
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def apply_tokens(self, tokens):
        self.tokens = tokens
        self.update()

    def add_sample(self, value):
        self.samples.append(max(0.0, float(value)))
        self.update()

    def reset(self):
        self.samples = deque([0.0] * self.capacity, maxlen=self.capacity)
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        if not self.tokens:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.tokens["surface_alt"]))
        painter.drawRoundedRect(rect, 8, 8)

        peak = max(self.samples) if self.samples else 0.0
        scale_max = peak * 1.18 if peak > 0 else 1.0

        grid_pen = QPen(QColor(self.tokens["border"]))
        grid_pen.setWidthF(1.0)
        painter.setPen(grid_pen)
        for frac in (0.25, 0.5, 0.75):
            y = rect.bottom() - rect.height() * frac
            painter.drawLine(QPointF(rect.left() + 6, y), QPointF(rect.right() - 6, y))

        n = len(self.samples)
        if n >= 2 and peak > 0:
            inner = rect.adjusted(6, 8, -6, -6)
            step = inner.width() / (n - 1)
            points = [
                QPointF(
                    inner.left() + i * step,
                    inner.bottom() - (v / scale_max) * inner.height(),
                )
                for i, v in enumerate(self.samples)
            ]

            area = QPainterPath()
            area.moveTo(points[0].x(), inner.bottom())
            for p in points:
                area.lineTo(p)
            area.lineTo(points[-1].x(), inner.bottom())
            area.closeSubpath()

            grad = QLinearGradient(0, inner.top(), 0, inner.bottom())
            top = QColor(self.tokens["accent"])
            top.setAlpha(120)
            bottom = QColor(self.tokens["accent"])
            bottom.setAlpha(10)
            grad.setColorAt(0.0, top)
            grad.setColorAt(1.0, bottom)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawPath(area)

            line = QPainterPath()
            line.moveTo(points[0])
            for p in points[1:]:
                line.lineTo(p)
            pen = QPen(QColor(self.tokens["accent"]))
            pen.setWidthF(1.8)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(line)

        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        painter.setFont(font)
        painter.setPen(QPen(QColor(self.tokens["text_faint"])))
        painter.drawText(
            rect.adjusted(9, 5, -9, 0),
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft),
            f"peak {format_speed(peak)}" if peak > 0 else "idle",
        )
        current = self.samples[-1] if self.samples else 0
        painter.setPen(QPen(QColor(self.tokens["text_muted"])))
        painter.drawText(
            rect.adjusted(9, 5, -9, 0),
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight),
            format_speed(current),
        )
        painter.end()


class SegmentBar(QWidget):
    """Mapa das conexões paralelas: uma faixa por segmento do arquivo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []  # [(downloaded, size)]
        self.tokens = None
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def apply_tokens(self, tokens):
        self.tokens = tokens
        self.update()

    def set_segments(self, segments):
        self.segments = segments or []
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        if not self.tokens:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        if not self.segments:
            painter.setPen(QPen(QColor(self.tokens["text_faint"])))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "—")
            painter.end()
            return

        n = len(self.segments)
        gap = 3.0
        bar_h = min(13.0, max(5.0, (rect.height() - gap * (n - 1)) / n))
        total_h = bar_h * n + gap * (n - 1)
        y = rect.top() + max(0.0, (rect.height() - total_h) / 2)

        painter.setPen(Qt.PenStyle.NoPen)
        for downloaded, size in self.segments:
            track = QRectF(rect.left(), y, rect.width(), bar_h)
            radius = bar_h / 2
            painter.setBrush(QColor(self.tokens["track"]))
            painter.drawRoundedRect(track, radius, radius)

            pct = (downloaded / size) if size else 0.0
            pct = max(0.0, min(1.0, pct))
            if pct > 0:
                fill = QRectF(track)
                fill.setWidth(max(track.width() * pct, bar_h))
                done = pct >= 0.999
                painter.setBrush(
                    QColor(self.tokens["success"] if done else self.tokens["accent"])
                )
                painter.drawRoundedRect(fill, radius, radius)
            y += bar_h + gap
        painter.end()


class KeyValueGrid(QWidget):
    """Grade rótulo/valor do painel de detalhes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(5)

    def add_row(self, key, label):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        caption = QLabel(label)
        caption.setObjectName("StatLabel")
        caption.setMinimumWidth(96)
        value = QLabel("—")
        value.setProperty("class", "muted")
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(value, 1)
        self._layout.addWidget(row)
        self._rows[key] = (caption, value)

    def set_label(self, key, label):
        if key in self._rows:
            self._rows[key][0].setText(label)

    def set_value(self, key, text):
        if key in self._rows:
            self._rows[key][1].setText(text if text else "—")

    def clear_values(self):
        for _caption, value in self._rows.values():
            value.setText("—")
