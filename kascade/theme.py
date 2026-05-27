from PySide6.QtGui import QPalette, QColor

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

# Buttons / nav (derived shades)
BTN_BG = "#0C3543"
BTN_BORDER = "#16505F"
BTN_HOVER = "#114652"
NAV_HOVER = "#0A3340"
NAV_ACTIVE = "#0F4A54"

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
    font-size: 17px;
    font-weight: 700;
    color: {HEADING};
    padding: 6px 10px 14px 10px;
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
    font-weight: 700;
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
#CardTitle {{
    font-size: 14px;
    font-weight: 600;
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
QPushButton#PrimaryButton:disabled {{ background-color: #1C4350; color: #5A7A80; }}

#Hero {{
    border-radius: 16px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {CARD}, stop:1 {BG});
    border: 1px solid {BORDER};
}}
#HeroTitle {{ font-size: 26px; font-weight: 800; color: {HEADING}; }}
#HeroSub {{ font-size: 13px; color: {BRAND_MINT}; }}

#Tile {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#StatLabel {{ color: {MUTED}; font-size: 11px; font-weight: 700; }}
#StatValue {{ color: {HEADING}; font-size: 22px; font-weight: 800; }}

QPushButton#DangerButton {{
    background-color: #3A1822;
    color: #FF8095;
    border: 1px solid #5E2740;
    border-radius: 9px;
    padding: 9px 16px;
    font-weight: 600;
}}
QPushButton#DangerButton:hover {{ background-color: #4A1E2C; }}
QPushButton#DangerButton:disabled {{ background-color: {BTN_BG}; color: #5A7A80; border: 1px solid {BTN_BORDER}; }}

QPushButton {{
    background-color: {BTN_BG};
    color: {TEXT};
    border: 1px solid {BTN_BORDER};
    border-radius: 9px;
    padding: 9px 16px;
}}
QPushButton:hover {{ background-color: {BTN_HOVER}; }}
QPushButton:disabled {{ color: #5A7A80; }}

QPlainTextEdit, QLineEdit, QSpinBox {{
    background-color: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 9px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}

QProgressBar {{
    background-color: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 18px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 7px;
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BTN_BORDER}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


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
    app.setStyleSheet(STYLESHEET)
