"""Ícones vetoriais desenhados em runtime.

Sem arquivos externos: cada ícone é uma descrição em uma viewbox 24x24 que é
traçada com QPainter. Isso permite recolorir qualquer ícone conforme o tema
(acento, texto, estados) e renderizar nítido em qualquer DPI.
"""

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

VIEWBOX = 24.0

# Cada ícone: dict com chaves opcionais
#   lines  -> lista de polilinhas [(x, y), ...] traçadas
#   closed -> lista de polígonos traçados e fechados
#   fills  -> lista de polígonos preenchidos
#   circles-> [(cx, cy, r)] traçados
#   dots   -> [(cx, cy, r)] preenchidos
#   arcs   -> [(x, y, w, h, start_deg, span_deg)] traçados
#   rects  -> [(x, y, w, h, radius)] preenchidos
ICONS = {
    "download": {
        "lines": [[(3, 15), (3, 20), (21, 20), (21, 15)], [(12, 3), (12, 15)]],
        "closed": [],
        "fills": [[(6.5, 10.5), (17.5, 10.5), (12, 16.5)]],
    },
    "search": {
        "circles": [(10.5, 10.5, 6.5)],
        "lines": [[(15.5, 15.5), (21, 21)]],
    },
    "archive": {
        "rects": [(3, 4, 18, 4, 1.5)],
        "lines": [[(5, 8), (5, 20), (19, 20), (19, 8)], [(10, 12), (14, 12)]],
    },
    "settings": {
        "lines": [[(3, 6), (21, 6)], [(3, 12), (21, 12)], [(3, 18), (21, 18)]],
        "circles": [(8, 6, 2.4), (16, 12, 2.4), (10, 18, 2.4)],
    },
    "play": {"fills": [[(8, 5), (19, 12), (8, 19)]]},
    "pause": {"rects": [(8, 5, 3, 14, 1.2), (13, 5, 3, 14, 1.2)]},
    "stop": {"rects": [(6, 6, 12, 12, 2)]},
    "close": {"lines": [[(6, 6), (18, 18)], [(18, 6), (6, 18)]]},
    "restart": {
        "arcs": [(4, 4, 16, 16, 70, 250)],
        "fills": [[(17.5, 2.5), (21.5, 7.5), (14.5, 8.0)]],
    },
    "trash": {
        "lines": [
            [(3, 6), (21, 6)],
            [(9, 6), (9, 3.5), (15, 3.5), (15, 6)],
            [(10, 10), (10, 17)],
            [(14, 10), (14, 17)],
        ],
        "closed": [[(5.5, 6), (18.5, 6), (17.5, 20.5), (6.5, 20.5)]],
    },
    "arrow_up": {"lines": [[(12, 20), (12, 5)], [(6, 11), (12, 5), (18, 11)]]},
    "arrow_down": {"lines": [[(12, 4), (12, 19)], [(6, 13), (12, 19), (18, 13)]]},
    "link": {
        "lines": [[(8, 12), (16, 12)]],
        "arcs": [(12.5, 6.5, 11, 11, 90, -180), (0.5, 6.5, 11, 11, 90, 180)],
    },
    "filter": {"closed": [[(3, 5), (21, 5), (14, 12.5), (14, 20), (10, 18), (10, 12.5)]]},
    "clock": {"circles": [(12, 12, 8.5)], "lines": [[(12, 6.5), (12, 12), (16, 14)]]},
    "check": {"lines": [[(4.5, 12.5), (9.5, 17.5), (19.5, 6)]]},
    "alert": {
        "closed": [[(12, 3.5), (21.5, 20), (2.5, 20)]],
        "lines": [[(12, 9.5), (12, 14)]],
        "dots": [(12, 17, 1.1)],
    },
    "info": {"circles": [(12, 12, 8.5)], "lines": [[(12, 11), (12, 16.5)]], "dots": [(12, 7.8, 1.1)]},
    "plus": {"lines": [[(12, 5), (12, 19)], [(5, 12), (19, 12)]]},
    "folder": {
        "closed": [[(3, 19.5), (3, 5), (9, 5), (11.2, 8), (21, 8), (21, 19.5)]],
    },
    "file": {
        "closed": [[(5, 3), (14, 3), (19, 8), (19, 21), (5, 21)]],
        "lines": [[(14, 3), (14, 8), (19, 8)]],
    },
    "activity": {"lines": [[(2.5, 12), (7, 12), (10, 4.5), (14, 19.5), (17, 12), (21.5, 12)]]},
    "zap": {"fills": [[(13, 2), (4, 13.5), (10.5, 13.5), (9.5, 22), (20, 10), (13, 10)]]},
    "sun": {
        "circles": [(12, 12, 4.2)],
        "lines": [
            [(12, 1.5), (12, 4)], [(12, 20), (12, 22.5)],
            [(1.5, 12), (4, 12)], [(20, 12), (22.5, 12)],
            [(4.6, 4.6), (6.4, 6.4)], [(17.6, 17.6), (19.4, 19.4)],
            [(4.6, 19.4), (6.4, 17.6)], [(17.6, 6.4), (19.4, 4.6)],
        ],
    },
    "moon": {"moon": True},
    "copy": {
        "rects": [],
        "closed": [[(9, 3), (20, 3), (20, 15), (9, 15)], [(4, 9), (9, 9), (9, 21), (4, 21)]],
    },
    "external": {
        "lines": [[(19, 13), (19, 20), (4, 20), (4, 5), (11, 5)], [(13, 11), (20, 4)]],
        "closed": [[(14, 4), (20, 4), (20, 10)]],
    },
    "globe": {
        "circles": [(12, 12, 8.5)],
        "lines": [[(3.5, 12), (20.5, 12)]],
        "arcs": [(7.5, 3.5, 9, 17, 90, 180), (7.5, 3.5, 9, 17, 90, -180)],
    },
    "gauge": {
        "arcs": [(3.5, 5, 17, 17, 0, 180)],
        "lines": [[(12, 13.5), (16.5, 9)]],
        "dots": [(12, 13.5, 1.4)],
    },
    "layers": {
        "closed": [[(12, 3), (21, 8), (12, 13), (3, 8)]],
        "lines": [[(3, 12.5), (12, 17.5), (21, 12.5)], [(3, 16.5), (12, 21.5), (21, 16.5)]],
    },
    "menu": {"lines": [[(3, 6), (21, 6)], [(3, 12), (21, 12)], [(3, 18), (21, 18)]]},
    "chevron_left": {"lines": [[(15, 5), (8, 12), (15, 19)]]},
    "chevron_right": {"lines": [[(9, 5), (16, 12), (9, 19)]]},
    "chevron_up": {"lines": [[(5, 15), (12, 8), (19, 15)]]},
    "chevron_down": {"lines": [[(5, 9), (12, 16), (19, 9)]]},
    "history": {
        "arcs": [(3.5, 3.5, 17, 17, 100, 300)],
        "lines": [[(12, 7), (12, 12), (15.5, 14)], [(3.5, 4), (3.5, 9), (8.5, 9)]],
    },
    "user": {"circles": [(12, 8, 4)], "arcs": [(4.5, 12.5, 15, 15, 0, 180)]},
    "app": {
        "fills": [[(12, 2.5), (21.5, 8), (21.5, 16), (12, 21.5), (2.5, 16), (2.5, 8)]],
    },
}

_cache = {}


def _device_pixel_ratio():
    """DPR real da aplicação. Fixar em 2.0 faz o Qt encaixar um pixmap 2x num
    slot 1x e recortar o ícone, então isso precisa vir do QApplication."""
    app = QApplication.instance()
    if app is None:
        return 1.0
    try:
        return float(app.devicePixelRatio()) or 1.0
    except (AttributeError, TypeError):
        return 1.0


def _stroke_pen(color, width):
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _path_from_points(points, close=False):
    path = QPainterPath()
    path.moveTo(*points[0])
    for p in points[1:]:
        path.lineTo(*p)
    if close:
        path.closeSubpath()
    return path


def render_pixmap(name, color, size=18, stroke=1.9, dpr=None):
    """Renderiza um ícone como QPixmap já escalado para o devicePixelRatio."""
    spec = ICONS.get(name)
    dpr = _device_pixel_ratio() if dpr is None else dpr
    px = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    px.setDevicePixelRatio(dpr)
    px.fill(QColor(0, 0, 0, 0))
    if not spec:
        return px

    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scale = size * dpr / VIEWBOX
    painter.scale(scale, scale)

    col = QColor(color)
    pen = _stroke_pen(col, stroke)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    for pts in spec.get("lines", []):
        painter.drawPath(_path_from_points(pts))
    for pts in spec.get("closed", []):
        painter.drawPath(_path_from_points(pts, close=True))
    for cx, cy, r in spec.get("circles", []):
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    for x, y, w, h, start, span in spec.get("arcs", []):
        painter.drawArc(QRectF(x, y, w, h), int(start * 16), int(span * 16))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(col)
    for pts in spec.get("fills", []):
        painter.drawPath(_path_from_points(pts, close=True))
    for cx, cy, r in spec.get("dots", []):
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    for x, y, w, h, radius in spec.get("rects", []):
        painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    if spec.get("moon"):
        outer = QPainterPath()
        outer.addEllipse(QRectF(3, 3, 18, 18))
        inner = QPainterPath()
        inner.addEllipse(QRectF(9, 0.5, 17, 17))
        painter.drawPath(outer.subtracted(inner))

    painter.end()
    return px


def icon(name, color="#e6edf3", size=18, stroke=1.9):
    """QIcon cacheado para (nome, cor, tamanho)."""
    key = (name, str(color), size, stroke, _device_pixel_ratio())
    cached = _cache.get(key)
    if cached is None:
        px = render_pixmap(name, color, size, stroke)
        cached = QIcon(px)
        _cache[key] = cached
    return cached


def app_icon(accent="#3b82f6", size=64):
    """Ícone da janela/bandeja: hexágono do acento com a seta de download."""
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / VIEWBOX, size / VIEWBOX)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawRoundedRect(QRectF(1.5, 1.5, 21, 21), 5.5, 5.5)

    painter.setPen(_stroke_pen("#ffffff", 1.9))
    painter.drawPath(_path_from_points([(6, 16.5), (6, 19), (18, 19), (18, 16.5)]))
    painter.drawPath(_path_from_points([(12, 4.5), (12, 14)]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawPath(_path_from_points([(8, 11), (16, 11), (12, 16)], close=True))
    painter.end()
    return QIcon(px)


def clear_cache():
    """Descarta ícones cacheados (chamado ao trocar de tema)."""
    _cache.clear()


ICON_SIZE = QSize(18, 18)
