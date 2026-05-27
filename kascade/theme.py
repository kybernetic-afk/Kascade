from PySide6.QtGui import QPalette, QColor

# Color palette (dark violet, inspired by a modern dashboard look)
BG = "#0f0b1e"
SIDEBAR = "#0a0814"
CARD = "#1a1533"
INPUT = "#120e24"
BORDER = "#2a2348"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#8f72ff"
TEXT = "#e8e6f0"
MUTED = "#9a93b8"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

#Sidebar {{
    background-color: {SIDEBAR};
    border-right: 1px solid #221c3a;
}}
#AppTitle {{
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
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
    background: #181230;
    color: {TEXT};
}}
QPushButton#NavButton:checked {{
    background: #2a1f55;
    color: #ffffff;
    font-weight: 600;
}}
#SidebarFooter {{
    color: #6b6488;
    font-size: 11px;
    padding: 8px 10px;
}}

#Header {{
    font-size: 23px;
    font-weight: 700;
    color: #ffffff;
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
    color: #cfc8e8;
}}

QPushButton#PrimaryButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #8a5cff, stop:1 #6336ff);
    color: #ffffff;
    border: none;
    border-radius: 9px;
    padding: 10px 20px;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #9a72ff, stop:1 #7a52ff);
}}
QPushButton#PrimaryButton:disabled {{ background-color: #3a3358; color: #847ca8; }}

#Hero {{
    border-radius: 16px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #221a47, stop:1 #16122b);
    border: 1px solid #2f2658;
}}
#HeroTitle {{ font-size: 26px; font-weight: 800; color: #ffffff; }}
#HeroSub {{ font-size: 13px; color: #b9b2d6; }}

#Tile {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#StatLabel {{ color: {MUTED}; font-size: 11px; font-weight: 700; }}
#StatValue {{ color: #ffffff; font-size: 22px; font-weight: 800; }}

QPushButton#DangerButton {{
    background-color: #2a1622;
    color: #ff8095;
    border: 1px solid #5e2740;
    border-radius: 9px;
    padding: 10px 18px;
    font-weight: 600;
}}
QPushButton#DangerButton:hover {{ background-color: #3a1d2e; }}
QPushButton#DangerButton:disabled {{ background-color: #221c3a; color: #6b6488; border: 1px solid #322a52; }}

QPushButton {{
    background-color: #221c3a;
    color: {TEXT};
    border: 1px solid #322a52;
    border-radius: 9px;
    padding: 9px 16px;
}}
QPushButton:hover {{ background-color: #2a2348; }}
QPushButton:disabled {{ color: #6b6488; }}

QPlainTextEdit, QLineEdit, QSpinBox {{
    background-color: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 9px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}

QLabel#StatusBadge {{
    border-radius: 13px;
    padding: 6px 16px;
    font-weight: 600;
}}
QLabel#StatusBadge[state="idle"] {{ background: #221c3a; color: {MUTED}; }}
QLabel#StatusBadge[state="running"] {{ background: #2a2455; color: #b9a6ff; }}
QLabel#StatusBadge[state="success"] {{ background: #103a2b; color: #3ddc97; }}
QLabel#StatusBadge[state="failed"] {{ background: #3a1622; color: #ff7a90; }}

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
QScrollBar::handle:vertical {{ background: #322a52; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #43396e; }}
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
    pal.setColor(QPalette.Button, QColor("#221c3a"))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(CARD))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor("#6b6488"))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
