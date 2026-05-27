import os

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)

# ---------------------------------------------------------------------------
# Kybernetic brand palette (sourced from the logo)
# ---------------------------------------------------------------------------
BRAND_DEEP = "#042A37"   # logo background - deep teal
BRAND_GREEN = "#42E695"  # gradient start
BRAND_TEAL = "#3BB2B8"   # gradient end
BRAND_MINT = "#C7F0ED"   # pale accent / tagline

# ---------------------------------------------------------------------------
# Derived UI palette (semantic roles - reuse these everywhere)
# ---------------------------------------------------------------------------
# Surfaces
SIDEBAR = "#03202A"
BG = BRAND_DEEP
CARD = "#0A3A48"
CARD_HOVER_BORDER = "#1F6E7E"  # brighter edge when a card is hovered
INPUT = "#04252F"
BORDER = "#15505F"

# Accents
ACCENT = BRAND_TEAL
ACCENT_HOVER = "#4ECDD3"
GRADIENT_START = BRAND_GREEN
GRADIENT_END = BRAND_TEAL
ON_ACCENT = BRAND_DEEP   # text/icon colour on a bright accent fill

# Text
TEXT = "#E8F6F3"
MUTED = "#84A7AE"
HEADING = "#FFFFFF"

# Semantic / status
PENDING = "#5A7A80"
RUNNING = "#5FD3D9"
SUCCESS = BRAND_GREEN
FAILED = "#FF6B81"

# Translucent fills for status pills (same hue, low alpha)
PENDING_FILL = "rgba(132, 167, 174, 0.16)"
RUNNING_FILL = "rgba(95, 211, 217, 0.18)"
SUCCESS_FILL = "rgba(66, 230, 149, 0.18)"
FAILED_FILL = "rgba(255, 107, 129, 0.18)"

# Buttons / nav (derived shades)
BTN_BG = "#0C3543"
BTN_BORDER = "#16505F"
BTN_HOVER = "#114652"
BTN_PRESSED = "#0A2E3A"
NAV_HOVER = "#0A3340"
NAV_ACTIVE = "#0F4A54"
NAV_ICON = "#9FC2C8"  # neutral tone that reads on both idle and active nav rows

# Toast surfaces
TOAST_BG = "#0C3A48"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

#Sidebar {{
    background-color: {SIDEBAR};
    border-right: 1px solid {BORDER};
}}
#AppTitle {{
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 0.3px;
    color: {HEADING};
    padding: 6px 10px 16px 10px;
}}
QPushButton#NavButton {{
    text-align: left;
    padding: 11px 14px;
    border: none;
    border-radius: 9px;
    color: {MUTED};
    background: transparent;
    font-size: 14px;
}}
QPushButton#NavButton:hover {{
    background: {NAV_HOVER};
    color: {TEXT};
}}
QPushButton#NavButton:pressed {{
    background: {NAV_ACTIVE};
}}
QPushButton#NavButton:checked {{
    background: {NAV_ACTIVE};
    color: {HEADING};
    font-weight: 600;
}}
#SidebarFooter {{
    color: {MUTED};
    font-size: 11px;
    padding: 8px 10px;
}}

#Header {{
    font-size: 23px;
    font-weight: 800;
    letter-spacing: 0.2px;
    color: {HEADING};
}}
#SubHeader {{
    color: {MUTED};
    font-size: 13px;
}}

#Card {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#Card:hover {{
    border: 1px solid {CARD_HOVER_BORDER};
}}
#CardTitle {{
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.2px;
    color: {BRAND_MINT};
}}

QPushButton#PrimaryButton {{
    background-color: {GRADIENT_START};
    color: {ON_ACCENT};
    border: 1px solid {GRADIENT_START};
    border-radius: 9px;
    padding: 9px 16px;
    font-weight: 700;
}}
QPushButton#PrimaryButton:hover {{ background-color: #5CEBA6; border: 1px solid #5CEBA6; }}
QPushButton#PrimaryButton:pressed {{ background-color: #34C97F; border: 1px solid #34C97F; }}
QPushButton#PrimaryButton:disabled {{ background-color: #1C4350; color: #5A7A80; border: 1px solid #1C4350; }}

#Hero {{
    border-radius: 16px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {CARD}, stop:1 {BG});
    border: 1px solid {BORDER};
}}
#HeroTitle {{ font-size: 26px; font-weight: 800; letter-spacing: 0.3px; color: {HEADING}; }}
#HeroSub {{ font-size: 13px; color: {BRAND_MINT}; }}

#Tile {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#Tile:hover {{ border: 1px solid {CARD_HOVER_BORDER}; }}
#StatLabel {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 0.6px; }}
#StatValue {{ color: {HEADING}; font-size: 22px; font-weight: 800; }}

/* Status pill (used for the Status tile) */
QLabel#StatusBadge {{
    border-radius: 11px;
    padding: 3px 12px;
    font-size: 13px;
    font-weight: 800;
}}
QLabel#StatusBadge[state="idle"]    {{ color: {MUTED};    background: {PENDING_FILL}; }}
QLabel#StatusBadge[state="running"] {{ color: {RUNNING};  background: {RUNNING_FILL}; }}
QLabel#StatusBadge[state="success"] {{ color: {SUCCESS};  background: {SUCCESS_FILL}; }}
QLabel#StatusBadge[state="failed"]  {{ color: {FAILED};   background: {FAILED_FILL}; }}

/* Required / optional field chips */
QLabel#FieldTag {{
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.5px;
    border-radius: 8px;
    padding: 2px 8px;
}}
QLabel#FieldTag[req="true"]  {{ color: {RUNNING}; background: {RUNNING_FILL}; }}
QLabel#FieldTag[req="false"] {{ color: {MUTED};   background: {PENDING_FILL}; }}

QPushButton#DangerButton {{
    background-color: #3A1822;
    color: #FF8095;
    border: 1px solid #5E2740;
    border-radius: 9px;
    padding: 9px 16px;
    font-weight: 600;
}}
QPushButton#DangerButton:hover {{ background-color: #4A1E2C; }}
QPushButton#DangerButton:pressed {{ background-color: #2E121B; }}
QPushButton#DangerButton:disabled {{ background-color: {BTN_BG}; color: #5A7A80; border: 1px solid {BTN_BORDER}; }}

QPushButton {{
    background-color: {BTN_BG};
    color: {TEXT};
    border: 1px solid {BTN_BORDER};
    border-radius: 9px;
    padding: 9px 16px;
}}
QPushButton:hover {{ background-color: {BTN_HOVER}; border: 1px solid {ACCENT}; }}
QPushButton:pressed {{ background-color: {BTN_PRESSED}; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton:disabled {{ color: #5A7A80; border: 1px solid {BTN_BORDER}; }}

QPlainTextEdit, QLineEdit, QSpinBox {{
    background-color: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 9px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QPlainTextEdit:hover, QLineEdit:hover, QSpinBox:hover {{ border: 1px solid #1C6373; }}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}

/* Checkboxes */
QCheckBox {{ spacing: 9px; color: {TEXT}; }}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {BORDER};
    background: {INPUT};
}}
QCheckBox::indicator:hover {{ border: 1px solid {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {GRADIENT_START};
    border: 1px solid {GRADIENT_START};
}}
QCheckBox::indicator:checked:hover {{ background: #5CEBA6; border: 1px solid #5CEBA6; }}

/* Spin boxes */
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    background: {BTN_BG};
    border-left: 1px solid {BORDER};
}}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 8px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 8px; border-top: 1px solid {BORDER}; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {BTN_HOVER}; }}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{ background: {BTN_PRESSED}; }}

QProgressBar {{
    background-color: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 18px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {GRADIENT_START}, stop:1 {GRADIENT_END});
}}

/* List widgets */
QListWidget {{
    background-color: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 6px;
    color: {TEXT};
}}
QListWidget::item:hover {{ background: {NAV_HOVER}; }}
QListWidget::item:selected {{ background: {NAV_ACTIVE}; color: {HEADING}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BTN_BORDER}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Toasts */
QFrame#Toast {{
    background-color: {TOAST_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#Toast[kind="success"] {{ border-left: 4px solid {SUCCESS}; }}
QFrame#Toast[kind="error"]   {{ border-left: 4px solid {FAILED}; }}
QFrame#Toast[kind="info"]    {{ border-left: 4px solid {RUNNING}; }}
QLabel#ToastText {{ color: {TEXT}; font-size: 13px; font-weight: 600; }}
"""


# ---------------------------------------------------------------------------
# Runtime-rendered icons
#
# We draw the few glyph images the stylesheet needs (checkbox tick, spin-box
# chevrons) and the sidebar nav icons with QPainter, then write the PNGs to a
# cache folder and reference them from QSS by path. This keeps the build to a
# single bundled asset (icon.ico) - nothing here needs to ship in the exe - and
# degrades gracefully: if anything fails, the stylesheet fragment is simply not
# applied (filled check-box, native spin arrows, text-only nav).
# ---------------------------------------------------------------------------
_nav_icons = {}


def _icon_cache_dir() -> str:
    from .paths import config_dir
    path = os.path.join(config_dir(), "_ui")
    os.makedirs(path, exist_ok=True)
    return path


def _new_pixmap(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    return pix


def _stroke_painter(pix: QPixmap, color: str, width: float) -> QPainter:
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    return p


def _save(pix: QPixmap, path: str) -> bool:
    return pix.save(path, "PNG")


def _draw_check(path: str) -> bool:
    pix = _new_pixmap(28)
    p = _stroke_painter(pix, ON_ACCENT, 3.4)
    p.drawPolyline(QPolygonF([QPointF(6, 14), QPointF(12, 20), QPointF(22, 8)]))
    p.end()
    return _save(pix, path)


def _draw_chevron(path: str, up: bool) -> bool:
    pix = _new_pixmap(20)
    p = _stroke_painter(pix, TEXT, 2.2)
    if up:
        p.drawPolyline(QPolygonF([QPointF(5, 13), QPointF(10, 7), QPointF(15, 13)]))
    else:
        p.drawPolyline(QPolygonF([QPointF(5, 7), QPointF(10, 13), QPointF(15, 7)]))
    p.end()
    return _save(pix, path)


def _draw_nav(name: str) -> QIcon:
    """Draw a simple monochrome line glyph for a sidebar entry."""
    pix = _new_pixmap(36)
    if name == "Run":
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(NAV_ICON))
        p.drawPolygon(QPolygonF([QPointF(11, 8), QPointF(11, 28), QPointF(28, 18)]))
        p.end()
    elif name == "Content":
        p = _stroke_painter(pix, NAV_ICON, 2.4)
        p.drawRoundedRect(8, 9, 20, 18, 3, 3)
        p.drawLine(8, 15, 28, 15)
        p.end()
    elif name == "Secrets":
        # Horizontal Yale-style key: ring bow (with hole) on the left, a straight
        # blade to the right, and two downward teeth at the tip. The horizontal
        # blade + teeth are what keep it from reading as a magnifying glass.
        p = _stroke_painter(pix, NAV_ICON, 2.4)
        p.drawEllipse(QPointF(11.5, 18.0), 6.0, 6.0)   # bow
        p.setBrush(QColor(NAV_ICON))
        p.drawEllipse(QPointF(11.5, 18.0), 1.7, 1.7)   # hole in the bow
        p.setBrush(Qt.NoBrush)
        p.drawLine(17, 18, 30, 18)                     # blade
        p.drawLine(26, 18, 26, 23)                     # tooth 1
        p.drawLine(30, 18, 30, 22)                     # tooth 2
        p.end()
    elif name == "Settings":
        p = _stroke_painter(pix, NAV_ICON, 2.4)
        # three "sliders": rails with knobs
        for y, kx in ((11, 23), (18, 13), (25, 26)):
            p.drawLine(9, y, 27, y)
            p.setBrush(QColor(NAV_ICON))
            p.drawEllipse(QPointF(float(kx), float(y)), 3.2, 3.2)
        p.end()
    return QIcon(pix)


def _build_icon_assets() -> str:
    """Render glyph PNGs + nav icons. Returns a QSS fragment (may be empty)."""
    try:
        cache = _icon_cache_dir()
        check = os.path.join(cache, "check.png")
        chev_up = os.path.join(cache, "chevron-up.png")
        chev_dn = os.path.join(cache, "chevron-down.png")
        ok = _draw_check(check) and _draw_chevron(chev_up, up=True) and _draw_chevron(chev_dn, up=False)

        for nm in ("Run", "Content", "Secrets", "Settings"):
            _nav_icons[nm] = _draw_nav(nm)

        if not ok:
            return ""
        u = lambda pth: '"' + pth.replace("\\", "/") + '"'
        return f"""
QCheckBox::indicator:checked {{ image: url({u(check)}); }}
QSpinBox::up-arrow   {{ image: url({u(chev_up)}); width: 11px; height: 11px; }}
QSpinBox::down-arrow {{ image: url({u(chev_dn)}); width: 11px; height: 11px; }}
"""
    except Exception:
        return ""


def nav_icon(name: str) -> QIcon:
    """Sidebar icon for a nav entry; empty QIcon if rendering was unavailable."""
    return _nav_icons.get(name, QIcon())


def apply_theme(app):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(INPUT))
    pal.setColor(QPalette.AlternateBase, QColor(CARD))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(BTN_BG))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(ON_ACCENT))
    pal.setColor(QPalette.ToolTipBase, QColor(CARD))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET + _build_icon_assets())
