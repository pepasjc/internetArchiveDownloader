"""Temas e estilos visuais para o Internet Archive Downloader"""

def get_modern_theme():
    """Retorna o tema moderno com cores azuis"""
    return """
        /* Estilo geral */
        QWidget {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            font-size: 13px;
            color: #2c3e50;
        }

        QMainWindow {
            background-color: #f5f7fa;
        }

        /* Tabs */
        QTabWidget::pane {
            border: none;
            background-color: white;
            border-radius: 8px;
            margin-top: 10px;
        }

        QTabBar::tab {
            background-color: #e8ecf1;
            color: #5a6c7d;
            border: none;
            padding: 12px 20px;
            margin-right: 4px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            font-weight: 500;
        }

        QTabBar::tab:selected {
            background-color: white;
            color: #2563eb;
            font-weight: 600;
        }

        QTabBar::tab:hover {
            background-color: #dde3ea;
        }

        /* Labels */
        QLabel {
            color: #2c3e50;
        }

        QLabel[class="section-header"] {
            font-size: 18px;
            font-weight: bold;
            color: #2563eb;
            padding: 5px 0;
        }

        QLabel[class="subsection-header"] {
            font-size: 14px;
            font-weight: bold;
            color: #64748b;
        }

        QLabel[class="note"] {
            color: #64748b;
            font-size: 11px;
            font-style: italic;
        }

        QLabel[class="success"] {
            color: #10b981;
            font-weight: bold;
        }

        QLabel[class="muted"] {
            color: #94a3b8;
        }

        /* Inputs */
        QLineEdit, QComboBox {
            padding: 8px 12px;
            border: 2px solid #e2e8f0;
            border-radius: 6px;
            background-color: white;
            color: #2c3e50;
            selection-background-color: #3b82f6;
        }

        QLineEdit:focus, QComboBox:focus {
            border: 2px solid #3b82f6;
            outline: none;
        }

        QComboBox::drop-down {
            border: none;
            width: 30px;
        }

        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #64748b;
            margin-right: 8px;
        }

        /* Buttons */
        QPushButton {
            background-color: #3b82f6;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            font-weight: 500;
            min-width: 80px;
            font-size: 13px;
        }

        QPushButton:hover {
            background-color: #2563eb;
        }

        QPushButton:pressed {
            background-color: #1d4ed8;
        }

        QPushButton:disabled {
            background-color: #cbd5e1;
            color: #94a3b8;
        }

        /* Icon buttons (small square buttons with symbols) */
        QPushButton[minimumWidth="32"] {
            font-size: 16px;
            padding: 0px;
            min-width: 32px;
        }

        /* Secondary Buttons (History, etc) */
        QPushButton[class="secondary"] {
            background-color: #64748b;
        }

        QPushButton[class="secondary"]:hover {
            background-color: #475569;
        }

        /* Success Buttons */
        QPushButton[class="success"] {
            background-color: #10b981;
        }

        QPushButton[class="success"]:hover {
            background-color: #059669;
        }

        /* Danger Buttons */
        QPushButton[class="danger"] {
            background-color: #ef4444;
        }

        QPushButton[class="danger"]:hover {
            background-color: #dc2626;
        }

        /* Tables */
        QTableWidget {
            background-color: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            gridline-color: #f1f5f9;
            selection-background-color: #dbeafe;
            selection-color: #1e40af;
        }

        QTableWidget::item {
            padding: 8px;
            border-bottom: 1px solid #f1f5f9;
        }

        QTableWidget::item:selected {
            background-color: #dbeafe;
            color: #1e40af;
        }

        QHeaderView::section {
            background-color: #f8fafc;
            color: #64748b;
            padding: 12px 8px;
            border: none;
            border-bottom: 2px solid #e2e8f0;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.5px;
        }

        QHeaderView::section:hover {
            background-color: #f1f5f9;
        }

        /* Lists */
        QListWidget {
            background-color: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 4px;
        }

        QListWidget::item {
            padding: 8px 12px;
            border-radius: 4px;
            margin: 2px 0;
        }

        QListWidget::item:hover {
            background-color: #f1f5f9;
        }

        QListWidget::item:selected {
            background-color: #dbeafe;
            color: #1e40af;
        }

        /* Progress Bar */
        QProgressBar {
            border: none;
            border-radius: 4px;
            background-color: #e2e8f0;
            text-align: center;
            height: 20px;
        }

        QProgressBar::chunk {
            background-color: #3b82f6;
            border-radius: 4px;
        }

        /* SpinBox */
        QSpinBox {
            padding: 8px 12px;
            border: 2px solid #e2e8f0;
            border-radius: 6px;
            background-color: white;
            min-width: 80px;
        }

        QSpinBox:focus {
            border: 2px solid #3b82f6;
        }

        QSpinBox::up-button, QSpinBox::down-button {
            border: none;
            width: 20px;
            background-color: transparent;
        }

        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background-color: #f1f5f9;
        }

        QSpinBox::up-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-bottom: 5px solid #64748b;
        }

        QSpinBox::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid #64748b;
        }

        /* CheckBox */
        QCheckBox {
            spacing: 8px;
        }

        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 2px solid #cbd5e1;
            background-color: white;
        }

        QCheckBox::indicator:checked {
            background-color: #3b82f6;
            border-color: #3b82f6;
            image: none;
        }

        QCheckBox::indicator:hover {
            border-color: #3b82f6;
        }

        /* Scrollbars */
        QScrollBar:vertical {
            border: none;
            background-color: #f8fafc;
            width: 12px;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical {
            background-color: #cbd5e1;
            border-radius: 6px;
            min-height: 30px;
        }

        QScrollBar::handle:vertical:hover {
            background-color: #94a3b8;
        }

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }

        QScrollBar:horizontal {
            border: none;
            background-color: #f8fafc;
            height: 12px;
            border-radius: 6px;
        }

        QScrollBar::handle:horizontal {
            background-color: #cbd5e1;
            border-radius: 6px;
            min-width: 30px;
        }

        QScrollBar::handle:horizontal:hover {
            background-color: #94a3b8;
        }

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }

        /* Status Bar */
        QStatusBar {
            background-color: #f8fafc;
            color: #64748b;
            border-top: 1px solid #e2e8f0;
            padding: 4px 8px;
        }

        /* Menus */
        QMenu {
            background-color: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 4px;
        }

        QMenu::item {
            padding: 8px 24px 8px 12px;
            border-radius: 4px;
            margin: 2px 4px;
        }

        QMenu::item:selected {
            background-color: #dbeafe;
            color: #1e40af;
        }

        /* Dialog */
        QDialog {
            background-color: #f5f7fa;
        }

        /* Message Box */
        QMessageBox {
            background-color: white;
        }
    """


def get_dark_theme():
    """Retorna o tema escuro moderno"""
    return """
        /* Estilo geral */
        QWidget {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            font-size: 13px;
            color: #e2e8f0;
            background-color: transparent;
        }

        QMainWindow {
            background-color: #0f172a;
        }

        /* Tabs */
        QTabWidget::pane {
            border: none;
            background-color: #1e293b;
            border-radius: 8px;
            margin-top: 10px;
        }

        QTabBar::tab {
            background-color: #334155;
            color: #94a3b8;
            border: none;
            padding: 12px 20px;
            margin-right: 4px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            font-weight: 500;
        }

        QTabBar::tab:selected {
            background-color: #1e293b;
            color: #60a5fa;
            font-weight: 600;
        }

        QTabBar::tab:hover {
            background-color: #475569;
        }

        /* Labels */
        QLabel {
            color: #e2e8f0;
            background-color: transparent;
        }

        QLabel[class="section-header"] {
            font-size: 18px;
            font-weight: bold;
            color: #60a5fa;
            padding: 5px 0;
        }

        QLabel[class="subsection-header"] {
            font-size: 14px;
            font-weight: bold;
            color: #94a3b8;
        }

        QLabel[class="note"] {
            color: #64748b;
            font-size: 11px;
            font-style: italic;
        }

        QLabel[class="success"] {
            color: #10b981;
            font-weight: bold;
        }

        QLabel[class="muted"] {
            color: #64748b;
        }

        /* Inputs */
        QLineEdit, QComboBox {
            padding: 8px 12px;
            border: 2px solid #334155;
            border-radius: 6px;
            background-color: #1e293b;
            color: #e2e8f0;
            selection-background-color: #3b82f6;
        }

        QLineEdit:focus, QComboBox:focus {
            border: 2px solid #3b82f6;
            outline: none;
        }

        QComboBox::drop-down {
            border: none;
            width: 30px;
            background-color: transparent;
        }

        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #94a3b8;
            margin-right: 8px;
        }

        QComboBox QAbstractItemView {
            background-color: #1e293b;
            color: #e2e8f0;
            selection-background-color: #3b82f6;
            border: 1px solid #334155;
            border-radius: 6px;
        }

        /* Buttons */
        QPushButton {
            background-color: #3b82f6;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            font-weight: 500;
            min-width: 80px;
            font-size: 13px;
        }

        QPushButton:hover {
            background-color: #2563eb;
        }

        QPushButton:pressed {
            background-color: #1d4ed8;
        }

        QPushButton:disabled {
            background-color: #334155;
            color: #64748b;
        }

        /* Icon buttons (small square buttons with symbols) */
        QPushButton[minimumWidth="32"] {
            font-size: 16px;
            padding: 0px;
            min-width: 32px;
        }

        /* Secondary Buttons */
        QPushButton[class="secondary"] {
            background-color: #475569;
        }

        QPushButton[class="secondary"]:hover {
            background-color: #64748b;
        }

        /* Success Buttons */
        QPushButton[class="success"] {
            background-color: #10b981;
        }

        QPushButton[class="success"]:hover {
            background-color: #059669;
        }

        /* Danger Buttons */
        QPushButton[class="danger"] {
            background-color: #ef4444;
        }

        QPushButton[class="danger"]:hover {
            background-color: #dc2626;
        }

        /* Tables */
        QTableWidget {
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            gridline-color: #334155;
            selection-background-color: #1e40af;
            selection-color: #dbeafe;
        }

        QTableWidget::item {
            padding: 8px;
            border-bottom: 1px solid #334155;
            color: #e2e8f0;
        }

        QTableWidget::item:selected {
            background-color: #1e40af;
            color: #dbeafe;
        }

        QHeaderView::section {
            background-color: #0f172a;
            color: #94a3b8;
            padding: 12px 8px;
            border: none;
            border-bottom: 2px solid #334155;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.5px;
        }

        QHeaderView::section:hover {
            background-color: #1e293b;
        }

        /* Lists */
        QListWidget {
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 4px;
        }

        QListWidget::item {
            padding: 8px 12px;
            border-radius: 4px;
            margin: 2px 0;
            color: #e2e8f0;
        }

        QListWidget::item:hover {
            background-color: #334155;
        }

        QListWidget::item:selected {
            background-color: #1e40af;
            color: #dbeafe;
        }

        /* Progress Bar */
        QProgressBar {
            border: none;
            border-radius: 4px;
            background-color: #334155;
            text-align: center;
            height: 20px;
            color: #e2e8f0;
        }

        QProgressBar::chunk {
            background-color: #3b82f6;
            border-radius: 4px;
        }

        /* SpinBox */
        QSpinBox {
            padding: 8px 12px;
            border: 2px solid #334155;
            border-radius: 6px;
            background-color: #1e293b;
            color: #e2e8f0;
            min-width: 80px;
        }

        QSpinBox:focus {
            border: 2px solid #3b82f6;
        }

        QSpinBox::up-button, QSpinBox::down-button {
            border: none;
            width: 20px;
            background-color: transparent;
        }

        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background-color: #334155;
        }

        QSpinBox::up-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-bottom: 5px solid #94a3b8;
        }

        QSpinBox::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid #94a3b8;
        }

        /* CheckBox */
        QCheckBox {
            spacing: 8px;
            color: #e2e8f0;
            background-color: transparent;
        }

        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 2px solid #475569;
            background-color: #1e293b;
        }

        QCheckBox::indicator:checked {
            background-color: #3b82f6;
            border-color: #3b82f6;
            image: none;
        }

        QCheckBox::indicator:hover {
            border-color: #3b82f6;
        }

        /* Scrollbars */
        QScrollBar:vertical {
            border: none;
            background-color: #1e293b;
            width: 12px;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical {
            background-color: #475569;
            border-radius: 6px;
            min-height: 30px;
        }

        QScrollBar::handle:vertical:hover {
            background-color: #64748b;
        }

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }

        QScrollBar:horizontal {
            border: none;
            background-color: #1e293b;
            height: 12px;
            border-radius: 6px;
        }

        QScrollBar::handle:horizontal {
            background-color: #475569;
            border-radius: 6px;
            min-width: 30px;
        }

        QScrollBar::handle:horizontal:hover {
            background-color: #64748b;
        }

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }

        /* Status Bar */
        QStatusBar {
            background-color: #0f172a;
            color: #94a3b8;
            border-top: 1px solid #334155;
            padding: 4px 8px;
        }

        /* Menus */
        QMenu {
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 4px;
        }

        QMenu::item {
            padding: 8px 24px 8px 12px;
            border-radius: 4px;
            margin: 2px 4px;
            color: #e2e8f0;
        }

        QMenu::item:selected {
            background-color: #1e40af;
            color: #dbeafe;
        }

        /* Dialog */
        QDialog {
            background-color: #0f172a;
        }

        /* Message Box */
        QMessageBox {
            background-color: #1e293b;
        }

        QMessageBox QLabel {
            color: #e2e8f0;
        }

        QMessageBox QPushButton {
            min-width: 80px;
        }
    """


# Função para obter tema atual (pode ser expandida para suportar múltiplos temas)
def get_current_theme():
    """Retorna o tema atual da aplicação"""
    return get_dark_theme()  # Dark theme como padrão
