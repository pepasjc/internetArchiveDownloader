"""Internet Archive Downloader GUI"""

import sys
import time
import json
import os
import subprocess
import platform
import internetarchive as ia
from urllib.parse import unquote

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QListWidget,
    QLabel,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QListWidgetItem,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QCompleter,
    QMenu,
    QCheckBox,
    QDialog,
    QComboBox,
    QInputDialog,
    QStackedWidget,
    QSplitter,
    QScrollArea,
    QFrame,
    QSystemTrayIcon,
)
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut, QAction

# Importa os módulos locais
import icons
from models import DownloadStatus, DownloadItem
from threads import DownloadManager, set_global_rate_limit
from utils import log, set_logging_enabled, format_size
from translations import Translator
from themes import ACCENTS, DENSITIES, build_stylesheet, build_tokens
from widgets import (
    ROLE_PROGRESS,
    ROLE_SORT,
    ROLE_STATUS,
    ROLE_UID,
    Card,
    FileNameDelegate,
    FilterChip,
    KeyValueGrid,
    NavButton,
    ProgressDelegate,
    SearchField,
    SectionTitle,
    SegmentBar,
    Sidebar,
    SpeedGraph,
    StatTile,
    StatusPillDelegate,
    ToolAction,
    VSep,
    format_eta,
    format_speed,
)

# Índices das páginas do QStackedWidget
PAGE_DOWNLOADS = 0
PAGE_SEARCH = 1
PAGE_ITEM = 2
PAGE_SETTINGS = 3

# Colunas da tabela de downloads
COL_FILE = 0
COL_STATUS = 1
COL_PROGRESS = 2
COL_SIZE = 3
COL_SPEED = 4
COL_ETA = 5
COL_CONN = 6
COL_MESSAGE = 7

# Colunas escondidas conforme a janela encolhe (da menos importante para a mais)
RESPONSIVE_COLUMNS = [
    (1400, COL_MESSAGE),
    (1020, COL_CONN),
    (880, COL_ETA),
    (760, COL_SPEED),
]

ACTIVE_STATES = (DownloadStatus.DOWNLOADING,)
FAILED_STATES = (DownloadStatus.ERROR, DownloadStatus.CANCELLED)


class InternetArchiveGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.item = None
        self.downloads = {}
        self.download_manager = None
        self._id_to_row: dict = {}  # O(1) unique_id → row lookups
        self.settings = QSettings("InternetArchive", "Downloader")

        # Carrega configurações salvas
        self.max_concurrent = self.settings.value("max_concurrent", 2, type=int)
        self.segments_per_file = self.settings.value("segments_per_file", 4, type=int)
        self.default_download_folder = self.settings.value(
            "default_download_folder", ""
        )

        # Aparência (aplicada a quente, sem reiniciar)
        self.theme_mode = self.settings.value("theme_mode", "dark")
        self.accent_name = self.settings.value("accent", "blue")
        self.density = self.settings.value("density", "comfortable")
        self.tokens = build_tokens(self.theme_mode, self.accent_name, self.density)

        # Teto global de velocidade, em KB/s (0 = ilimitado)
        self.speed_limit_kb = self.settings.value("speed_limit_kb", 0, type=int)
        set_global_rate_limit(self.speed_limit_kb * 1024)

        self.minimize_to_tray = self.settings.value(
            "minimize_to_tray", False, type=bool
        )
        self.tray = None
        self._force_quit = False

        # Estado da lista de downloads
        self.active_filter = "all"
        self.list_query = ""
        self.detail_uid = None
        self.segment_snapshots = {}   # uid → [(baixado, tamanho)]
        self._themed_widgets = []     # widgets com apply_tokens()
        self._sidebar_collapsed = False

        # Carrega idioma salvo (padrão: pt-BR)
        self.current_language = self.settings.value("language", "pt-BR")
        self.translator = Translator(self.current_language)
        self.t = self.translator.get  # Shorthand for translations

        # Carrega configuração de logging e aplica globalmente
        enable_logging = self.settings.value("enable_logging", True, type=bool)
        self.set_logging_enabled(enable_logging)

        self.recent_identifiers = self.load_recent_identifiers()
        self.recent_searches = self.load_recent_searches()
        self.all_files = []

        # Carrega último identifier usado
        self.last_identifier = self.settings.value("last_identifier", "")

        # Controle de paginação para busca
        self.search_results_cache = []
        self.current_search_page = 0
        self.results_per_page = 50
        self.current_sort_column = None
        self.current_sort_order = Qt.SortOrder.AscendingOrder
        self.current_search_query = ""  # Termos da busca atual

        self.initUI()
        self.start_download_manager()
        self.load_downloads()

        # Restaura a página selecionada (após initUI)
        last_tab = self.settings.value("last_tab_index", PAGE_DOWNLOADS, type=int)
        if not 0 <= last_tab <= PAGE_SETTINGS:
            last_tab = PAGE_DOWNLOADS
        self.go_to_page(last_tab)

        # Conecta o sinal APÓS restaurar a página (para não sobrescrever na inicialização)
        self.pages.currentChanged.connect(self.on_tab_changed)

        # Atualiza estatísticas agregadas / gráfico uma vez por segundo
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.refresh_stats)
        self.stats_timer.start(1000)

        self.refresh_filter_counts()
        self.refresh_stats()

        # Auto-busca o último identifier se houver (adiado para após a janela aparecer)
        if self.last_identifier:
            log(
                f"[STARTUP] Auto-buscando último identifier (adiado): {self.last_identifier}"
            )
            QTimer.singleShot(0, self.search_files)

    def load_recent_identifiers(self):
        recent = self.settings.value("recent_identifiers", [])
        if isinstance(recent, str):
            try:
                recent = json.loads(recent)
            except:
                recent = []
        return recent if recent else []

    def save_recent_identifiers(self):
        self.settings.setValue(
            "recent_identifiers", json.dumps(self.recent_identifiers)
        )

    def load_recent_searches(self):
        recent = self.settings.value("recent_searches", [])
        if isinstance(recent, str):
            try:
                recent = json.loads(recent)
            except:
                recent = []
        return recent if recent else []

    def save_recent_searches(self):
        self.settings.setValue("recent_searches", json.dumps(self.recent_searches))

    def add_to_recent_searches(self, query):
        if query in self.recent_searches:
            self.recent_searches.remove(query)

        self.recent_searches.insert(0, query)
        self.recent_searches = self.recent_searches[:20]

        self.save_recent_searches()
        self.update_search_completer()

    def load_downloads(self):
        """Carrega downloads salvos de sessões anteriores"""
        # Tenta carregar do novo formato (downloads_json)
        json_str = self.settings.value("downloads_json", "")

        # Fallback para formato antigo se não encontrar o novo
        if not json_str:
            json_str = self.settings.value("downloads", "")

        downloads_data = []
        if json_str:
            try:
                downloads_data = json.loads(json_str)
            except:
                downloads_data = []

        if not downloads_data:
            return

        log(f"\n[LOAD] Carregando {len(downloads_data)} download(s) salvos...")
        log(f"[LOAD] JSON sample: {json_str[:200]}...")

        self.download_table.setUpdatesEnabled(False)
        try:
            for data in downloads_data:
                try:
                    download_item = DownloadItem.from_dict(data)

                    log(f"\n[LOAD] Arquivo: {download_item.filename}")
                    log(f"[LOAD] Total bytes do dict: {download_item.total_bytes}")
                    # Usa o tamanho salvo em cache (evita chamada de rede bloqueante na inicialização)

                    # Atualiza downloaded_bytes com o tamanho atual do arquivo.
                    # Considera tanto o arquivo final quanto segmentos .partN
                    # (downloads multi-segment não finalizados).
                    dest_path = os.path.join(
                        download_item.dest_folder, download_item.filename
                    )
                    main_size = (
                        os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
                    )
                    parts_size = 0
                    for i in range(max(download_item.segments, 1)):
                        seg = f"{dest_path}.part{i}"
                        if os.path.exists(seg):
                            parts_size += os.path.getsize(seg)

                    on_disk = main_size if main_size > 0 else parts_size
                    nothing_on_disk = main_size == 0 and parts_size == 0
                    log(
                        f"[LOAD] Disco: main={main_size} parts={parts_size} → {on_disk} bytes ({format_size(on_disk)})"
                    )

                    # Recuperação: status COMPLETED salvo mas os dados no disco
                    # contradizem isso. Só vale quando existe conteúdo PARCIAL:
                    #  (a) arquivo final presente porém menor que o total, OU
                    #  (b) arquivo final ausente mas existem .partN
                    #      (segmentos baixados mas merge nunca rodou)
                    # Disco totalmente vazio NÃO é sinal de download incompleto:
                    # significa que o usuário apagou o arquivo depois de baixar,
                    # e o download continua concluído.
                    needs_recovery = False
                    if download_item.status == DownloadStatus.COMPLETED:
                        if (
                            main_size > 0
                            and download_item.total_bytes > 0
                            and main_size < download_item.total_bytes
                        ):
                            needs_recovery = True
                            log(
                                f"[LOAD] AVISO: marcado COMPLETED mas só {main_size}/{download_item.total_bytes} no disco."
                            )
                        elif main_size == 0 and parts_size > 0:
                            needs_recovery = True
                            log(
                                f"[LOAD] AVISO: marcado COMPLETED mas merge não rodou (parts={parts_size}, main ausente)."
                            )

                    if needs_recovery:
                        log(f"[LOAD] Restaurando como PAUSED para permitir retomar/mergear.")
                        download_item.status = DownloadStatus.PAUSED
                        download_item.date_completed = None

                    if (
                        download_item.status == DownloadStatus.COMPLETED
                        and nothing_on_disk
                    ):
                        # Arquivo apagado pelo usuário: preserva 100% em vez de
                        # zerar o progresso a partir do que sobrou no disco.
                        download_item.downloaded_bytes = download_item.total_bytes
                        download_item.progress = 100
                        log("[LOAD] Concluído, arquivo ausente do disco (apagado).")
                    else:
                        download_item.downloaded_bytes = on_disk
                        if download_item.total_bytes > 0:
                            download_item.progress = min(
                                100,
                                int((on_disk / download_item.total_bytes) * 100),
                            )
                        else:
                            download_item.progress = 0
                        log(f"[LOAD] Progresso calculado: {download_item.progress}%")

                    log(f"[LOAD] Status: {download_item.status.value}")
                    log(
                        f"[LOAD] Final: total={download_item.total_bytes}, downloaded={download_item.downloaded_bytes}, progress={download_item.progress}%"
                    )

                    self.downloads[download_item.unique_id] = download_item
                    self.add_download_to_table(download_item)

                except Exception as e:
                    log(f"[LOAD] Erro ao carregar download: {e}")
                    import traceback

                    traceback.print_exc()
        finally:
            self.download_table.setUpdatesEnabled(True)

    def save_downloads(self):
        """Salva downloads atuais com todos os metadados"""
        downloads_data = []

        log(f"\n[SAVE] Salvando downloads...")

        for download_item in self.downloads.values():
            # Salva TODOS os downloads (incluindo completados e cancelados)
            # Atualiza downloaded_bytes com o tamanho atual do arquivo se existir
            dest_path = os.path.join(download_item.dest_folder, download_item.filename)
            if os.path.exists(dest_path):
                download_item.downloaded_bytes = os.path.getsize(dest_path)
                if download_item.total_bytes > 0:
                    download_item.progress = int(
                        (download_item.downloaded_bytes / download_item.total_bytes)
                        * 100
                    )

            log(f"[SAVE] {download_item.filename}:")
            log(f"       status={download_item.status.value}")
            log(
                f"       total_bytes={download_item.total_bytes} ({format_size(download_item.total_bytes)})"
            )
            log(
                f"       downloaded_bytes={download_item.downloaded_bytes} ({format_size(download_item.downloaded_bytes)})"
            )
            log(f"       progress={download_item.progress}%")
            log(f"       unique_id={download_item.unique_id}")
            log(f"       date_added={download_item.date_added}")
            log(f"       date_completed={download_item.date_completed}")

            # Converte para dict que já salva como string
            downloads_data.append(download_item.to_dict())

        # Salva como JSON string diretamente, sem usar QSettings nativamente com números grandes
        json_str = json.dumps(downloads_data, ensure_ascii=False)
        log(f"[SAVE] JSON sample: {json_str[:200]}...")

        # Salva como texto puro para evitar conversão automática do QSettings
        self.settings.setValue("downloads_json", json_str)
        log(f"[SAVE] {len(downloads_data)} download(s) salvos\n")

    def add_to_recent(self, identifier):
        if identifier in self.recent_identifiers:
            self.recent_identifiers.remove(identifier)

        self.recent_identifiers.insert(0, identifier)
        self.recent_identifiers = self.recent_identifiers[:50]

        self.save_recent_identifiers()
        self.update_completer()

    # ------------------------------------------------------------------
    # Shell da aplicação
    # ------------------------------------------------------------------

    def initUI(self):
        self.setWindowTitle(self.t("window_title"))
        self.setGeometry(100, 100, 1280, 820)
        self.setMinimumSize(720, 520)
        self.setAcceptDrops(True)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        shell = QHBoxLayout(central_widget)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        # --- Barra lateral -------------------------------------------------
        self.sidebar = Sidebar(self.t("window_title").replace(" Downloader", ""),
                               self.t("app_subtitle"))
        self.sidebar.add_page("download", self.t("nav_downloads"))
        self.sidebar.add_page("search", self.t("nav_search"))
        self.sidebar.add_page("archive", self.t("nav_item"))
        self.sidebar.add_page("settings", self.t("nav_settings"))
        self.sidebar.navigated.connect(self.go_to_page)

        self.theme_toggle = NavButton("moon", self.t("nav_theme"))
        self.theme_toggle.setCheckable(False)
        self.theme_toggle.setToolTip(self.t("nav_theme_tooltip"))
        self.theme_toggle.clicked.connect(self.toggle_theme_mode)
        self.sidebar.add_footer_widget(self.theme_toggle)
        shell.addWidget(self.sidebar)
        self._themed_widgets.append(self.sidebar)

        # --- Área de conteúdo ---------------------------------------------
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 14, 16, 12)
        content_layout.setSpacing(12)
        shell.addWidget(content, 1)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.create_downloads_page())
        self.pages.addWidget(self.create_search_tab())
        self.pages.addWidget(self.create_identifier_tab())
        self.pages.addWidget(self.create_settings_tab())
        content_layout.addWidget(self.pages, 1)

        content_layout.addWidget(self.create_status_strip())

        self.statusBar().showMessage(self.t("status_ready"))
        self.setup_tray()
        self.setup_shortcuts()
        self.apply_theme()

    def create_page_header(self, title, subtitle):
        """Cabeçalho padrão de página: título + subtítulo."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        sub_label = QLabel(subtitle)
        sub_label.setObjectName("PageSubtitle")
        lay.addWidget(title_label)
        lay.addWidget(sub_label)
        return box

    def create_status_strip(self):
        """Rodapé com métricas agregadas e limite global de velocidade."""
        strip = QFrame()
        strip.setObjectName("StatusStrip")
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(18)

        self.stat_active = StatTile(self.t("stat_active"), "0")
        self.stat_queued = StatTile(self.t("stat_queued"), "0")
        self.stat_done = StatTile(self.t("stat_done"), "0")
        self.stat_speed = StatTile(self.t("stat_speed"), "—")
        self.stat_eta = StatTile(self.t("stat_eta"), "—")

        for tile in (self.stat_active, self.stat_queued, self.stat_done):
            lay.addWidget(tile)
        lay.addWidget(VSep())
        lay.addWidget(self.stat_speed)
        lay.addWidget(self.stat_eta)
        lay.addStretch()

        limit_label = QLabel(self.t("speed_limit_label"))
        limit_label.setObjectName("StatLabel")
        self.speed_limit_spin = QSpinBox()
        self.speed_limit_spin.setRange(0, 1024 * 100)
        self.speed_limit_spin.setSingleStep(256)
        self.speed_limit_spin.setValue(self.speed_limit_kb)
        self.speed_limit_spin.setSuffix(" KB/s")
        self.speed_limit_spin.setSpecialValueText(self.t("speed_unlimited"))
        self.speed_limit_spin.setToolTip(self.t("speed_limit_tooltip"))
        self.speed_limit_spin.setMaximumWidth(150)
        self.speed_limit_spin.valueChanged.connect(self.update_speed_limit)

        lay.addWidget(limit_label)
        lay.addWidget(self.speed_limit_spin)
        return strip

    def setup_shortcuts(self):
        """Atalhos de teclado no padrão dos gerenciadores de download."""
        bindings = [
            ("Ctrl+1", lambda: self.go_to_page(PAGE_DOWNLOADS)),
            ("Ctrl+2", lambda: self.go_to_page(PAGE_SEARCH)),
            ("Ctrl+3", lambda: self.go_to_page(PAGE_ITEM)),
            ("Ctrl+4", lambda: self.go_to_page(PAGE_SETTINGS)),
            ("Ctrl+N", self.show_add_url_dialog),
            ("Ctrl+F", self.focus_filter_field),
            ("Ctrl+L", self.toggle_detail_panel),
            ("Space", self.toolbar_pause_resume),
            ("Delete", self.toolbar_remove),
            ("F5", self.toolbar_restart),
        ]
        for key, handler in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(handler)

    def focus_filter_field(self):
        """Ctrl+F: foca o campo de filtro da página atual."""
        index = self.pages.currentIndex()
        if index == PAGE_DOWNLOADS:
            self.list_filter_input.setFocus()
            self.list_filter_input.selectAll()
        elif index == PAGE_SEARCH:
            self.search_query_input.setFocus()
            self.search_query_input.selectAll()
        elif index == PAGE_ITEM:
            self.filter_input.setFocus()
            self.filter_input.selectAll()

    def go_to_page(self, index):
        self.pages.setCurrentIndex(index)
        self.sidebar.set_current(index)

    def on_tab_changed(self, index):
        """Salva a página selecionada quando o usuário navega"""
        self.settings.setValue("last_tab_index", index)
        self.sidebar.set_current(index)
        log(f"[CONFIG] Página alterada para índice: {index}")

    # ------------------------------------------------------------------
    # Tema
    # ------------------------------------------------------------------

    def apply_theme(self):
        """Reconstrói tokens, QSS e repinta todos os widgets customizados."""
        self.tokens = build_tokens(self.theme_mode, self.accent_name, self.density)
        icons.clear_cache()

        app = QApplication.instance()
        stylesheet = build_stylesheet(self.theme_mode, self.accent_name, self.density)
        if app:
            app.setStyleSheet(stylesheet)
        else:
            self.setStyleSheet(stylesheet)

        self.setWindowIcon(icons.app_icon(self.tokens["accent"]))
        self.theme_toggle._icon_name = "sun" if self.theme_mode == "dark" else "moon"

        for widget in self._themed_widgets:
            widget.apply_tokens(self.tokens)

        row_h = self.tokens["row_h_px"]
        for table in (self.download_table, self.search_results_table):
            table.verticalHeader().setDefaultSectionSize(row_h)
        self.download_table.viewport().update()

        if self.tray:
            self.tray.setIcon(icons.app_icon(self.tokens["accent"]))

    def toggle_theme_mode(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        self.settings.setValue("theme_mode", self.theme_mode)
        if hasattr(self, "theme_combo"):
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(0 if self.theme_mode == "dark" else 1)
            self.theme_combo.blockSignals(False)
        self.apply_theme()

    def change_theme_mode(self, index):
        self.theme_mode = "dark" if index == 0 else "light"
        self.settings.setValue("theme_mode", self.theme_mode)
        self.apply_theme()

    def change_accent(self, index):
        self.accent_name = self.accent_combo.itemData(index)
        self.settings.setValue("accent", self.accent_name)
        self.apply_theme()

    def change_density(self, index):
        self.density = self.density_combo.itemData(index)
        self.settings.setValue("density", self.density)
        self.apply_theme()

    # ------------------------------------------------------------------
    # Bandeja do sistema
    # ------------------------------------------------------------------

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray = QSystemTrayIcon(icons.app_icon(self.tokens["accent"]), self)
        menu = QMenu()

        show_action = QAction(self.t("tray_show"), self)
        show_action.triggered.connect(self.show_from_tray)
        pause_action = QAction(self.t("tray_pause_all"), self)
        pause_action.triggered.connect(self.pause_all)
        resume_action = QAction(self.t("tray_resume_all"), self)
        resume_action.triggered.connect(self.resume_all)
        quit_action = QAction(self.t("tray_quit"), self)
        quit_action.triggered.connect(self.quit_application)

        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(pause_action)
        menu.addAction(resume_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.setToolTip(self.t("tray_tooltip_idle"))
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_from_tray()

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_application(self):
        self._force_quit = True
        self.close()

    def pause_all(self):
        for uid, dl in list(self.downloads.items()):
            if dl.status in (DownloadStatus.DOWNLOADING, DownloadStatus.WAITING):
                self.toggle_pause(uid)

    def resume_all(self):
        for uid, dl in list(self.downloads.items()):
            if dl.status in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
                self.toggle_pause(uid)

    # ------------------------------------------------------------------
    # Responsividade
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()

        if hasattr(self, "sidebar"):
            collapsed = width < 1000
            if collapsed != self._sidebar_collapsed:
                self._sidebar_collapsed = collapsed
                self.sidebar.set_collapsed(collapsed)

        if hasattr(self, "download_table"):
            for min_width, column in RESPONSIVE_COLUMNS:
                self.download_table.setColumnHidden(column, width < min_width)

        if hasattr(self, "selection_actions"):
            compact = width < 1150
            for action in self.selection_actions + [
                self.clear_completed_btn,
                self.cancel_all_btn,
            ]:
                action.set_compact(compact)

        if hasattr(self, "stat_eta"):
            self.stat_eta.setVisible(width >= 900)
            self.stat_done.setVisible(width >= 820)

    # ------------------------------------------------------------------
    # Arrastar e soltar URLs
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()
            self.statusBar().showMessage(self.t("drop_hint"), 2000)

    def dropEvent(self, event):
        mime = event.mimeData()
        candidates = []
        if mime.hasUrls():
            candidates.extend(u.toString() for u in mime.urls())
        if mime.hasText():
            candidates.extend(mime.text().split())

        added = 0
        for raw in candidates:
            url = raw.strip()
            if "archive.org/download/" in url:
                if self.add_url_to_queue(url, interactive=False):
                    added += 1

        if added:
            self.go_to_page(PAGE_DOWNLOADS)
            self.statusBar().showMessage(self.t("dropped_added", count=added), 4000)
        else:
            self.statusBar().showMessage(self.t("dropped_none"), 4000)
        event.acceptProposedAction()

    def create_search_tab(self):
        """Cria a página de busca no Internet Archive"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(
            self.create_page_header(self.t("search_title"), self.t("page_search_sub"))
        )

        # Campo de busca dentro de um card
        search_card = QFrame()
        search_card.setObjectName("TopBar")
        card_layout = QVBoxLayout(search_card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)

        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)
        search_label = QLabel(self.t("search_label"))
        self.search_query_input = SearchField(self.t("search_placeholder"))
        self._themed_widgets.append(self.search_query_input)
        self.search_query_input.returnPressed.connect(self.search_archive)

        # Autocomplete para histórico de buscas
        self.search_completer = QCompleter(self.recent_searches)
        self.search_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search_query_input.setCompleter(self.search_completer)

        # Filtro de tipo de mídia
        mediatype_label = QLabel(self.t("search_type_label"))
        self.mediatype_combo = QComboBox()
        self.mediatype_combo.addItems(
            [
                self.t("media_all"),
                self.t("media_audio"),
                self.t("media_video"),
                self.t("media_text"),
                self.t("media_image"),
                self.t("media_software"),
                self.t("media_web"),
                self.t("media_collection"),
                self.t("media_data"),
            ]
        )

        self.search_archive_btn = QPushButton(self.t("search_button"))
        self.search_archive_btn.clicked.connect(self.search_archive)

        self.search_history_btn = QPushButton(self.t("search_history_button"))
        self.search_history_btn.setProperty("class", "secondary")
        self.search_history_btn.clicked.connect(self.show_search_history)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_query_input, 2)
        search_layout.addWidget(mediatype_label)
        search_layout.addWidget(self.mediatype_combo, 1)
        search_layout.addWidget(self.search_archive_btn)
        search_layout.addWidget(self.search_history_btn)
        card_layout.addLayout(search_layout)

        # Dica de sintaxe
        syntax_hint = QLabel(self.t("search_hint"))
        syntax_hint.setProperty("class", "note")
        syntax_hint.setWordWrap(True)
        card_layout.addWidget(syntax_hint)
        layout.addWidget(search_card)

        # Linha de resultados + paginação
        results_row = QHBoxLayout()
        results_row.setSpacing(8)
        self.search_results_label = QLabel("")
        self.search_results_label.setProperty("class", "muted")
        results_row.addWidget(self.search_results_label)
        results_row.addStretch()

        self.prev_page_btn = QPushButton(self.t("search_previous"))
        self.prev_page_btn.setProperty("class", "secondary")
        self.prev_page_btn.clicked.connect(self.previous_page)
        self.prev_page_btn.setEnabled(False)

        self.page_info_label = QLabel("")
        self.page_info_label.setProperty("class", "muted")
        self.page_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.next_page_btn = QPushButton(self.t("search_next"))
        self.next_page_btn.setProperty("class", "secondary")
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)

        results_row.addWidget(self.prev_page_btn)
        results_row.addWidget(self.page_info_label)
        results_row.addWidget(self.next_page_btn)
        layout.addLayout(results_row)

        results_hint = QLabel(self.t("search_results_hint"))
        results_hint.setProperty("class", "note")
        layout.addWidget(results_hint)

        self.search_results_table = QTableWidget()
        self.search_results_table.setColumnCount(6)
        self.search_results_table.setHorizontalHeaderLabels(
            [
                self.t("col_title"),
                self.t("col_identifier"),
                self.t("col_type"),
                self.t("col_downloads"),
                self.t("col_matching_files"),
                self.t("col_description"),
            ]
        )

        # Configuração das colunas
        self.search_results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )  # Título
        self.search_results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive
        )  # Identifier
        self.search_results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )  # Tipo
        self.search_results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )  # Downloads
        self.search_results_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )  # Matching Files
        self.search_results_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )  # Descrição

        # Larguras iniciais
        self.search_results_table.setColumnWidth(0, 250)  # Título
        self.search_results_table.setColumnWidth(1, 200)  # Identifier

        # Altura das linhas
        self.search_results_table.verticalHeader().setDefaultSectionSize(
            self.tokens["row_h_px"]
        )
        self.search_results_table.verticalHeader().setVisible(False)
        self.search_results_table.setShowGrid(False)
        self.search_results_table.setAlternatingRowColors(True)
        self.search_results_table.setWordWrap(False)
        self.search_results_table.horizontalHeader().setHighlightSections(False)

        self.search_results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.search_results_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.search_results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.search_results_table.setSortingEnabled(
            False
        )  # Desabilita ordenação nativa (vamos usar nossa própria)

        # Conecta clique no header para ordenação customizada
        self.search_results_table.horizontalHeader().sectionClicked.connect(
            self.sort_search_results
        )
        self.search_results_table.itemDoubleClicked.connect(
            self.load_item_from_search_table
        )

        # Context menu para resultados de busca
        self.search_results_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.search_results_table.customContextMenuRequested.connect(
            self.show_search_results_context_menu
        )

        layout.addWidget(self.search_results_table)

        return tab

    def search_archive(self):
        """Busca items no Internet Archive"""
        query = self.search_query_input.text().strip()

        if not query:
            QMessageBox.warning(self, self.t("warning"), self.t("warn_search_empty"))
            return

        # Pega o tipo de mídia selecionado
        mediatype_text = self.mediatype_combo.currentText()
        mediatype_map = {
            self.t("media_all"): "",
            self.t("media_audio"): "audio",
            self.t("media_video"): "movies",
            self.t("media_text"): "texts",
            self.t("media_image"): "image",
            self.t("media_software"): "software",
            self.t("media_web"): "web",
            self.t("media_collection"): "collection",
            self.t("media_data"): "data",
        }
        mediatype = mediatype_map.get(mediatype_text, "")

        # Monta a query
        if mediatype:
            full_query = f"{query} AND mediatype:{mediatype}"
        else:
            full_query = query

        self.search_results_label.setText(self.t("searching_for", query=query))
        self.search_results_table.setRowCount(0)
        self.search_archive_btn.setEnabled(False)
        self.prev_page_btn.setEnabled(False)
        self.next_page_btn.setEnabled(False)

        try:
            log(f"[SEARCH] Buscando: {full_query}")

            # Busca até 500 resultados (10 páginas)
            results = ia.search_items(
                full_query,
                fields=["identifier", "title", "description", "downloads", "mediatype"],
                sorts=["downloads desc"],
            )

            self.search_results_cache = []
            count = 0
            for result in results:
                # Limita a 500 resultados total
                if count >= 500:
                    break

                identifier = result.get("identifier", "N/A")
                title = result.get("title", self.t("no_title"))
                description = result.get("description", self.t("no_description"))
                downloads = result.get("downloads", 0)
                mediatype_result = result.get("mediatype", "N/A")

                # Limita tamanho da descrição
                if isinstance(description, list):
                    description = " ".join(description)
                if len(description) > 150:
                    description = description[:150] + "..."

                # Armazena no cache
                self.search_results_cache.append(
                    {
                        "identifier": identifier,
                        "title": title,
                        "description": description,
                        "downloads": downloads,
                        "mediatype": mediatype_result,
                        "matching_files": None,  # Será carregado sob demanda
                        "matching_files_list": None,  # Lista completa de arquivos correspondentes
                    }
                )

                count += 1

            # Armazena os termos de busca para filtragem de arquivos
            if count > 0:
                self.current_search_query = query

            if count == 0:
                self.search_results_label.setText(self.t("no_results"))
                self.page_info_label.setText("")
                QMessageBox.information(
                    self,
                    self.t("no_results_title"),
                    self.t("no_results_found", query=query),
                )
            else:
                # Adiciona ao histórico de buscas
                self.add_to_recent_searches(query)

                # Reset página para a primeira e limpa ordenação
                self.current_search_page = 0
                self.current_sort_column = None
                self.current_sort_order = Qt.SortOrder.AscendingOrder
                self.update_search_page_display()
                log(f"[SEARCH] {count} resultados encontrados")

        except Exception as e:
            log(f"[SEARCH] Erro: {e}")
            QMessageBox.critical(
                self, self.t("error"), self.t("error_search", error=str(e))
            )
            self.search_results_label.setText(self.t("search_error"))
            self.page_info_label.setText("")

        finally:
            self.search_archive_btn.setEnabled(True)

    def sort_search_results(self, column):
        """Ordena os resultados de busca por coluna (considerando TODAS as páginas)"""
        if not self.search_results_cache:
            return

        # Se clicar na mesma coluna, inverte a ordem
        if self.current_sort_column == column:
            self.current_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self.current_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self.current_sort_column = column
            self.current_sort_order = Qt.SortOrder.AscendingOrder

        # Mapeia coluna para chave no dicionário
        column_keys = {
            0: "title",
            1: "identifier",
            2: "mediatype",
            3: "downloads",
            4: "matching_files",
            5: "description",
        }

        sort_key = column_keys.get(column)
        if not sort_key:
            return

        # Ordena o cache completo
        reverse = self.current_sort_order == Qt.SortOrder.DescendingOrder

        if sort_key in ["downloads", "matching_files"]:
            # Para downloads e matching_files, ordena numericamente
            self.search_results_cache.sort(
                key=lambda x: x.get(sort_key, 0) or 0, reverse=reverse
            )
        else:
            # Para texto, ordena alfabeticamente (case insensitive)
            self.search_results_cache.sort(
                key=lambda x: str(x[sort_key]).lower(), reverse=reverse
            )

        log(f"[SORT] Ordenando por {sort_key} ({'DESC' if reverse else 'ASC'})")

        # Volta para a primeira página e atualiza exibição
        self.current_search_page = 0
        self.update_search_page_display()

        # Atualiza indicador visual no header
        self.update_sort_indicator()

    def update_sort_indicator(self):
        """Atualiza os indicadores visuais de ordenação no cabeçalho"""
        header = self.search_results_table.horizontalHeader()

        # Adiciona indicador na coluna atual
        if self.current_sort_column is not None:
            header.setSortIndicator(self.current_sort_column, self.current_sort_order)
            header.setSortIndicatorShown(True)
        else:
            header.setSortIndicatorShown(False)

    def show_matching_files_dialog(self, identifier, title, matching_files):
        """Mostra dialog com arquivos que correspondem à busca"""
        from PyQt6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("matching_files_title"))
        dialog.setGeometry(150, 150, 900, 600)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Cabeçalho com título e identifier
        header_label = QLabel(f"<b>{title}</b><br><i>{identifier}</i>")
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        if not matching_files or len(matching_files) == 0:
            no_files_label = QLabel(self.t("no_matching_files"))
            no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_files_label)
        else:
            # Instrução
            instruction_label = QLabel(
                self.t("matching_files_instruction", count=len(matching_files))
            )
            instruction_label.setProperty("class", "note")
            layout.addWidget(instruction_label)

            # Tabela de arquivos
            files_table = QTableWidget()
            files_table.setColumnCount(4)
            files_table.setHorizontalHeaderLabels(
                [
                    self.t("col_filename"),
                    self.t("col_size"),
                    self.t("col_format"),
                    self.t("col_action"),
                ]
            )

            files_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch
            )
            files_table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.ResizeToContents
            )
            files_table.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.ResizeMode.ResizeToContents
            )
            files_table.horizontalHeader().setSectionResizeMode(
                3, QHeaderView.ResizeMode.ResizeToContents
            )

            files_table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

            for file_info in matching_files:
                row = files_table.rowCount()
                files_table.insertRow(row)

                # Nome do arquivo
                name_item = QTableWidgetItem(file_info["name"])
                files_table.setItem(row, 0, name_item)

                # Tamanho
                size_item = QTableWidgetItem(format_size(file_info["size"]))
                files_table.setItem(row, 1, size_item)

                # Formato
                format_item = QTableWidgetItem(file_info["format"])
                files_table.setItem(row, 2, format_item)

                # Botão de ação (adicionar à fila)
                add_btn = QPushButton(self.t("add_to_queue"))
                add_btn.setProperty("class", "success")
                add_btn.clicked.connect(
                    lambda _checked,
                    id=identifier,
                    fn=file_info["name"],
                    sz=file_info["size"]: self.add_file_to_queue_from_dialog(id, fn, sz)
                )
                files_table.setCellWidget(row, 3, add_btn)

            layout.addWidget(files_table)

        # Botões inferiores
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        view_all_btn = QPushButton(self.t("view_all_files"))
        view_all_btn.clicked.connect(
            lambda: self.view_all_files_from_dialog(identifier, dialog)
        )
        button_layout.addWidget(view_all_btn)

        close_btn = QPushButton(self.t("close"))
        close_btn.setProperty("class", "secondary")
        close_btn.clicked.connect(dialog.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        dialog.exec()

    def _is_duplicate(self, new_item):
        """Returns True if an equivalent download already exists in the queue."""
        for existing in self.downloads.values():
            # URL-based: same URL = same file regardless of display name
            if new_item.url and existing.url:
                if new_item.url == existing.url:
                    return True
            # Identifier-based: same Archive.org item + same filename = same file
            elif not new_item.url and not existing.url:
                if new_item.item_id == existing.item_id and new_item.filename == existing.filename:
                    return True
        return False

    def add_file_to_queue_from_dialog(self, identifier, filename, file_size):
        """Adiciona arquivo à fila de downloads a partir do dialog"""
        if not self.default_download_folder:
            QMessageBox.warning(
                self,
                self.t("info_no_default_folder_title"),
                self.t("warn_no_default_folder"),
            )
            return

        download_item = DownloadItem(
            identifier,
            filename,
            self.default_download_folder,
            segments=self.segments_per_file,
        )
        download_item.total_bytes = file_size

        if self._is_duplicate(download_item):
            QMessageBox.information(
                self,
                self.t("info_already_queued"),
                self.t("warn_already_queued", filename=filename),
            )
            return

        self.downloads[download_item.unique_id] = download_item
        self.add_download_to_table(download_item)
        self.download_manager.add_download(download_item)

        log(
            f"[DIALOG-ADD] Arquivo adicionado: {filename} -> {self.default_download_folder}"
        )
        self.statusBar().showMessage(
            self.t("info_added_to_queue", filename=filename), 3000
        )

    def view_all_files_from_dialog(self, identifier, dialog):
        """Fecha o dialog e abre a aba de identifier com todos os arquivos"""
        dialog.close()

        # Define o identifier no campo da aba "Buscar por Identifier"
        self.id_input.setText(identifier)

        # Muda para a aba de identifier e busca os arquivos
        self.go_to_page(PAGE_ITEM)

        # Busca os arquivos
        self.search_files()

        log(f"[DIALOG] Visualizando todos os arquivos de: {identifier}")

    def update_search_page_display(self):
        """Atualiza a exibição da página atual de resultados"""
        self.search_results_table.setRowCount(0)

        total_results = len(self.search_results_cache)
        total_pages = (
            total_results + self.results_per_page - 1
        ) // self.results_per_page

        start_idx = self.current_search_page * self.results_per_page
        end_idx = min(start_idx + self.results_per_page, total_results)

        # Exibe os resultados da página atual
        for i in range(start_idx, end_idx):
            result = self.search_results_cache[i]
            row = self.search_results_table.rowCount()
            self.search_results_table.insertRow(row)

            # Título
            title_item = QTableWidgetItem(result["title"])
            title_item.setData(
                Qt.ItemDataRole.UserRole, result["identifier"]
            )  # Armazena identifier
            self.search_results_table.setItem(row, 0, title_item)

            # Identifier
            id_item = QTableWidgetItem(result["identifier"])
            self.search_results_table.setItem(row, 1, id_item)

            # Tipo
            type_item = QTableWidgetItem(result["mediatype"])
            self.search_results_table.setItem(row, 2, type_item)

            # Downloads (armazena valor numérico para ordenação correta)
            downloads_item = QTableWidgetItem(f"{result['downloads']:,}")
            downloads_item.setData(Qt.ItemDataRole.UserRole, result["downloads"])
            self.search_results_table.setItem(row, 3, downloads_item)

            # Matching Files (mostrado apenas quando carregado via context menu)
            files_display = "-"
            if result["matching_files"] is not None:
                files_display = (
                    str(result["matching_files"])
                    if result["matching_files"] > 0
                    else "0"
                )

            files_item = QTableWidgetItem(files_display)
            files_item.setData(
                Qt.ItemDataRole.UserRole, result.get("matching_files", 0)
            )
            self.search_results_table.setItem(row, 4, files_item)

            # Descrição
            desc_item = QTableWidgetItem(result["description"])
            self.search_results_table.setItem(row, 5, desc_item)

        # Atualiza label de informação
        self.search_results_label.setText(self.t("results_found", count=total_results))
        self.page_info_label.setText(
            self.t(
                "page_info",
                current=self.current_search_page + 1,
                total=total_pages,
                start=start_idx + 1,
                end=end_idx,
                count=total_results,
            )
        )

        # Habilita/desabilita botões de navegação
        self.prev_page_btn.setEnabled(self.current_search_page > 0)
        self.next_page_btn.setEnabled(self.current_search_page < total_pages - 1)

    def previous_page(self):
        """Vai para a página anterior"""
        if self.current_search_page > 0:
            self.current_search_page -= 1
            self.update_search_page_display()
            log(f"[PAGINATION] Navegando para página {self.current_search_page + 1}")

    def next_page(self):
        """Vai para a próxima página"""
        total_pages = (
            len(self.search_results_cache) + self.results_per_page - 1
        ) // self.results_per_page
        if self.current_search_page < total_pages - 1:
            self.current_search_page += 1
            self.update_search_page_display()
            log(f"[PAGINATION] Navegando para página {self.current_search_page + 1}")

    def load_item_from_search_table(self, item):
        """Carrega os arquivos de um item da busca (duplo clique)"""
        # Pega o identifier da linha clicada
        row = item.row()
        title_item = self.search_results_table.item(row, 0)
        identifier = title_item.data(Qt.ItemDataRole.UserRole)

        if not identifier:
            return

        # Define o identifier no campo da aba "Buscar por Identifier"
        self.id_input.setText(identifier)

        # Muda para a aba de identifier e busca os arquivos
        self.go_to_page(PAGE_ITEM)

        # Busca os arquivos
        self.search_files()

        log(f"[SEARCH] Carregando arquivos do item: {identifier}")

    def show_search_results_context_menu(self, position):
        """Mostra menu de contexto ao clicar com botão direito nos resultados de busca"""
        # Pega o item clicado
        item = self.search_results_table.itemAt(position)
        if not item:
            return

        row = item.row()
        title_item = self.search_results_table.item(row, 0)
        identifier = title_item.data(Qt.ItemDataRole.UserRole)

        if not identifier:
            return

        # Encontra o resultado no cache
        result = None
        for r in self.search_results_cache:
            if r["identifier"] == identifier:
                result = r
                break

        if not result:
            return

        # Cria o menu
        context_menu = QMenu(self)

        # Ação de mostrar arquivos correspondentes
        show_files_action = context_menu.addAction(
            self.t("context_show_matching_files")
        )
        show_files_action.triggered.connect(
            lambda: self.load_matching_files_async(result)
        )

        # Mostra o menu na posição do cursor
        context_menu.exec(self.search_results_table.viewport().mapToGlobal(position))

    def load_matching_files_async(self, result):
        """Carrega arquivos correspondentes em background thread"""
        identifier = result["identifier"]
        title = result["title"]

        # Se já carregou, mostra direto
        if result["matching_files_list"] is not None:
            self.show_matching_files_dialog(
                identifier, title, result["matching_files_list"]
            )
            return

        # Mostra mensagem de carregamento
        QMessageBox.information(self, self.t("info"), self.t("loading_matching_files"))

        # Cria thread para carregar arquivos
        from PyQt6.QtCore import QThread, pyqtSignal

        class MatchingFilesThread(QThread):
            finished = pyqtSignal(int, list)
            error = pyqtSignal(str)

            def __init__(self, identifier, query):
                super().__init__()
                self.identifier = identifier
                self.query = query

            def run(self):
                try:
                    item = ia.get_item(self.identifier)
                    query_terms = self.query.lower().split()

                    matching_files = []
                    for file in item.files:
                        filename = file.get("name", "").lower()

                        # Verifica se algum termo de busca está no nome do arquivo
                        if any(term in filename for term in query_terms):
                            matching_files.append(
                                {
                                    "name": file.get("name", ""),
                                    "size": int(file.get("size", 0)),
                                    "format": file.get("format", "N/A"),
                                }
                            )

                    self.finished.emit(len(matching_files), matching_files)

                except Exception as e:
                    self.error.emit(str(e))

        # Cria e inicia a thread
        thread = MatchingFilesThread(identifier, self.current_search_query)

        def on_finished(count, files):
            result["matching_files"] = count
            result["matching_files_list"] = files

            # Atualiza a tabela
            self.update_search_page_display()

            # Mostra o dialog
            self.show_matching_files_dialog(identifier, title, files)

        def on_error(error_msg):
            QMessageBox.critical(
                self, self.t("error"), self.t("error_loading_files", error=error_msg)
            )

        thread.finished.connect(on_finished)
        thread.error.connect(on_error)
        thread.start()

        # Armazena referência para evitar garbage collection
        self._matching_files_thread = thread

    def create_identifier_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(
            self.create_page_header(
                self.t("page_item_title"), self.t("page_item_sub")
            )
        )

        id_card = QFrame()
        id_card.setObjectName("TopBar")
        id_card_layout = QVBoxLayout(id_card)
        id_card_layout.setContentsMargins(12, 10, 12, 10)
        id_card_layout.setSpacing(8)

        id_layout = QHBoxLayout()
        id_layout.setSpacing(8)
        id_label = QLabel(self.t("identifier_label"))
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText(self.t("identifier_placeholder"))
        self.id_input.returnPressed.connect(self.search_files)

        self.completer = QCompleter(self.recent_identifiers)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.id_input.setCompleter(self.completer)

        self.search_btn = QPushButton(self.t("search_files_button"))
        self.search_btn.clicked.connect(self.search_files)

        self.history_btn = QPushButton(self.t("history_button"))
        self.history_btn.setProperty("class", "secondary")
        self.history_btn.setToolTip(self.t("history_tooltip"))
        self.history_btn.clicked.connect(self.show_history)

        id_layout.addWidget(id_label)
        id_layout.addWidget(self.id_input)
        id_layout.addWidget(self.history_btn)
        id_layout.addWidget(self.search_btn)
        id_card_layout.addLayout(id_layout)

        # Preenche com o último identifier usado
        if self.last_identifier:
            self.id_input.setText(self.last_identifier)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)
        filter_label = QLabel(self.t("filter_label"))
        self.filter_input = SearchField(self.t("filter_placeholder"))
        self._themed_widgets.append(self.filter_input)
        self.filter_input.textChanged.connect(self.filter_files)

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_input)
        id_card_layout.addLayout(filter_layout)
        layout.addWidget(id_card)

        list_row = QHBoxLayout()
        list_label = QLabel(self.t("files_label"))
        list_label.setObjectName("SectionTitle")
        hint_label = QLabel(self.t("double_click_hint"))
        hint_label.setProperty("class", "note")
        list_row.addWidget(list_label)
        list_row.addSpacing(8)
        list_row.addWidget(hint_label)
        list_row.addStretch()
        layout.addLayout(list_row)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.itemDoubleClicked.connect(self.add_file_on_double_click)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(
            self.show_file_list_context_menu
        )
        layout.addWidget(self.file_list)

        download_layout = QHBoxLayout()
        self.download_btn = QPushButton(self.t("add_to_queue_button"))
        self.download_btn.clicked.connect(self.add_to_queue)
        self.download_btn.setEnabled(False)
        download_layout.addStretch()
        download_layout.addWidget(self.download_btn)
        layout.addLayout(download_layout)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        return tab

    # ------------------------------------------------------------------
    # Página de downloads
    # ------------------------------------------------------------------

    def create_downloads_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addWidget(
            self.create_page_header(
                self.t("page_downloads_title"), self.t("page_downloads_sub")
            )
        )
        header_row.addStretch()

        self.add_url_btn = QPushButton(self.t("add_url_button"))
        self.add_url_btn.setToolTip("Ctrl+N")
        self.add_url_btn.clicked.connect(self.show_add_url_dialog)
        header_row.addWidget(self.add_url_btn)
        layout.addLayout(header_row)

        # --- Toolbar de ações ---------------------------------------------
        toolbar = QFrame()
        toolbar.setObjectName("TopBar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(2)

        self.pause_resume_btn = ToolAction(
            "pause", self.t("action_pause"), "Space"
        )
        self.pause_resume_btn.clicked.connect(self.toolbar_pause_resume)

        self.cancel_btn = ToolAction(
            "close", self.t("action_cancel"), danger=True
        )
        self.cancel_btn.clicked.connect(self.toolbar_cancel)

        self.restart_btn = ToolAction("restart", self.t("action_restart"), "F5")
        self.restart_btn.clicked.connect(self.toolbar_restart)

        self.remove_btn = ToolAction("trash", self.t("action_remove"), "Delete")
        self.remove_btn.clicked.connect(self.toolbar_remove)

        self.priority_up_btn = ToolAction(
            "arrow_up", "", self.t("action_move_up")
        )
        self.priority_up_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.priority_up_btn.clicked.connect(self.move_priority_up)

        self.priority_down_btn = ToolAction(
            "arrow_down", "", self.t("action_move_down")
        )
        self.priority_down_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.priority_down_btn.clicked.connect(self.move_priority_down)

        self.open_folder_btn = ToolAction("folder", "", self.t("action_open_folder"))
        self.open_folder_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.open_folder_btn.clicked.connect(self.toolbar_open_folder)

        self.selection_actions = [
            self.pause_resume_btn,
            self.cancel_btn,
            self.restart_btn,
            self.remove_btn,
            self.priority_up_btn,
            self.priority_down_btn,
            self.open_folder_btn,
        ]
        for action in self.selection_actions:
            action.setEnabled(False)
            toolbar_layout.addWidget(action)
            self._themed_widgets.append(action)

        toolbar_layout.addSpacing(6)
        toolbar_layout.addWidget(VSep())
        toolbar_layout.addSpacing(6)

        self.clear_completed_btn = ToolAction("check", self.t("dm_clear_completed"))
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        self.cancel_all_btn = ToolAction(
            "stop", self.t("dm_cancel_all"), danger=True
        )
        self.cancel_all_btn.clicked.connect(self.cancel_all)
        for action in (self.clear_completed_btn, self.cancel_all_btn):
            toolbar_layout.addWidget(action)
            self._themed_widgets.append(action)

        toolbar_layout.addStretch()

        self.detail_toggle_btn = ToolAction(
            "layers", "", self.t("detail_toggle_hide")
        )
        self.detail_toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.detail_toggle_btn.clicked.connect(self.toggle_detail_panel)
        toolbar_layout.addWidget(self.detail_toggle_btn)
        self._themed_widgets.append(self.detail_toggle_btn)

        layout.addWidget(toolbar)

        # --- Chips de filtro + busca na lista ------------------------------
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self.filter_chips = {}
        chip_defs = [
            ("all", "filter_all"),
            ("active", "filter_active"),
            ("waiting", "filter_waiting"),
            ("paused", "filter_paused"),
            ("completed", "filter_completed"),
            ("failed", "filter_failed"),
        ]
        for key, label_key in chip_defs:
            chip = FilterChip(key, self.t(label_key))
            chip.clicked.connect(lambda _=False, k=key: self.set_list_filter(k))
            self.filter_chips[key] = chip
            filter_row.addWidget(chip)
        self.filter_chips["all"].setChecked(True)

        filter_row.addStretch()
        self.list_filter_input = SearchField(self.t("downloads_filter_placeholder"))
        self.list_filter_input.setMaximumWidth(300)
        self.list_filter_input.textChanged.connect(self.on_list_filter_changed)
        self._themed_widgets.append(self.list_filter_input)
        filter_row.addWidget(self.list_filter_input)
        layout.addLayout(filter_row)

        # --- Tabela + painel de detalhes -----------------------------------
        self.downloads_splitter = QSplitter(Qt.Orientation.Vertical)
        self.downloads_splitter.setChildrenCollapsible(False)
        self.downloads_splitter.addWidget(self.create_download_table())
        self.downloads_splitter.addWidget(self.create_detail_panel())
        self.downloads_splitter.setStretchFactor(0, 3)
        self.downloads_splitter.setStretchFactor(1, 1)
        self.downloads_splitter.setSizes([560, 210])
        layout.addWidget(self.downloads_splitter, 1)

        return page

    def create_download_table(self):
        self.download_table = QTableWidget()
        self.download_table.setColumnCount(8)
        self.download_table.setHorizontalHeaderLabels(
            [
                self.t("dm_col_file"),
                self.t("dm_col_status"),
                self.t("dm_col_progress"),
                self.t("dm_col_size"),
                self.t("dm_col_speed"),
                self.t("dm_col_eta"),
                self.t("dm_col_connections"),
                self.t("dm_col_message"),
            ]
        )

        header = self.download_table.horizontalHeader()
        # O nome do arquivo é a coluna que o usuário mais lê: fica com toda a
        # folga da janela; as demais têm largura própria.
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(56)
        # Larguras fixas nas colunas que mudam a cada tick de progresso:
        # ResizeToContents remede a coluna inteira a cada mudança e destrói a
        # performance com muitas linhas.
        for column, width in (
            (COL_STATUS, 104),
            (COL_PROGRESS, 170),
            (COL_SIZE, 158),
            (COL_SPEED, 92),
            (COL_ETA, 80),
            (COL_CONN, 114),
        ):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.download_table.setColumnWidth(column, width)
        header.setSectionResizeMode(COL_MESSAGE, QHeaderView.ResizeMode.Interactive)
        self.download_table.setColumnWidth(COL_MESSAGE, 200)
        header.setHighlightSections(False)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self.sort_download_table)

        self.download_table.verticalHeader().setDefaultSectionSize(
            self.tokens["row_h_px"]
        )
        self.download_table.verticalHeader().setVisible(False)
        self.download_table.setShowGrid(False)
        self.download_table.setAlternatingRowColors(True)
        self.download_table.setWordWrap(False)
        self.download_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.download_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.download_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.download_table.customContextMenuRequested.connect(self.show_context_menu)
        self.download_table.cellDoubleClicked.connect(
            self.on_download_table_double_click
        )
        self.download_table.itemSelectionChanged.connect(self.on_selection_changed)

        # Delegates: pílula de status, barra de progresso e elisão do nome.
        self.name_delegate = FileNameDelegate(self.tokens, self.download_table)
        self.status_delegate = StatusPillDelegate(self.tokens, self.download_table)
        self.progress_delegate = ProgressDelegate(self.tokens, self.download_table)
        self.download_table.setItemDelegateForColumn(COL_FILE, self.name_delegate)
        self.download_table.setItemDelegateForColumn(COL_STATUS, self.status_delegate)
        self.download_table.setItemDelegateForColumn(
            COL_PROGRESS, self.progress_delegate
        )
        self._themed_widgets.extend(
            [self.name_delegate, self.status_delegate, self.progress_delegate]
        )

        self._download_sort_column = None
        self._download_sort_order = Qt.SortOrder.AscendingOrder
        return self.download_table

    def create_detail_panel(self):
        """Painel inferior com informações, mapa de conexões e gráfico."""
        panel = QFrame()
        panel.setObjectName("Card")
        panel.setMinimumHeight(150)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(0)

        self.detail_tabs = QTabWidget()

        info_scroll = QScrollArea()
        info_scroll.setWidgetResizable(True)
        info_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_grid = KeyValueGrid()
        for key, label_key in (
            ("file", "detail_field_file"),
            ("item", "detail_field_item"),
            ("status", "detail_field_status"),
            ("size", "detail_field_size"),
            ("speed", "detail_field_speed"),
            ("eta", "detail_field_eta"),
            ("folder", "detail_field_folder"),
            ("added", "detail_field_added"),
            ("completed", "detail_field_completed"),
            ("id", "detail_field_id"),
        ):
            self.detail_grid.add_row(key, self.t(label_key))
        info_wrapper = QWidget()
        info_lay = QVBoxLayout(info_wrapper)
        info_lay.setContentsMargins(10, 10, 10, 10)
        info_lay.addWidget(self.detail_grid)
        info_lay.addStretch()
        info_scroll.setWidget(info_wrapper)
        self.detail_tabs.addTab(info_scroll, self.t("detail_tab_info"))

        segments_wrapper = QWidget()
        seg_lay = QVBoxLayout(segments_wrapper)
        seg_lay.setContentsMargins(12, 12, 12, 12)
        self.segment_bar = SegmentBar()
        self._themed_widgets.append(self.segment_bar)
        seg_lay.addWidget(self.segment_bar)
        self.detail_tabs.addTab(segments_wrapper, self.t("detail_tab_segments"))

        graph_wrapper = QWidget()
        graph_lay = QVBoxLayout(graph_wrapper)
        graph_lay.setContentsMargins(12, 12, 12, 12)
        self.speed_graph = SpeedGraph()
        self._themed_widgets.append(self.speed_graph)
        graph_lay.addWidget(self.speed_graph)
        self.detail_tabs.addTab(graph_wrapper, self.t("detail_tab_graph"))

        lay.addWidget(self.detail_tabs)
        self.detail_panel = panel
        return panel

    def toggle_detail_panel(self):
        visible = not self.detail_panel.isVisible()
        self.detail_panel.setVisible(visible)
        self.detail_toggle_btn.setToolTip(
            self.t("detail_toggle_hide") if visible else self.t("detail_toggle_show")
        )

    # ------------------------------------------------------------------
    # Filtros, ordenação e detalhes da lista
    # ------------------------------------------------------------------

    def _row_matches_filter(self, download_item):
        if self.list_query and self.list_query not in download_item.filename.lower():
            return False

        status = download_item.status
        if self.active_filter == "all":
            return True
        if self.active_filter == "active":
            return status == DownloadStatus.DOWNLOADING
        if self.active_filter == "waiting":
            return status == DownloadStatus.WAITING
        if self.active_filter == "paused":
            return status == DownloadStatus.PAUSED
        if self.active_filter == "completed":
            return status == DownloadStatus.COMPLETED
        if self.active_filter == "failed":
            return status in FAILED_STATES
        return True

    def apply_list_filter(self):
        """Esconde as linhas que não casam com chip + texto de busca."""
        for row in range(self.download_table.rowCount()):
            item = self.download_table.item(row, COL_FILE)
            uid = item.data(ROLE_UID) if item else None
            download_item = self.downloads.get(uid)
            hidden = not (download_item and self._row_matches_filter(download_item))
            self.download_table.setRowHidden(row, hidden)

    def set_list_filter(self, key):
        self.active_filter = key
        self.apply_list_filter()

    def on_list_filter_changed(self, text):
        self.list_query = text.strip().lower()
        self.apply_list_filter()

    def refresh_filter_counts(self):
        """Atualiza os contadores exibidos em cada chip."""
        if not hasattr(self, "filter_chips"):
            return
        counts = {k: 0 for k in self.filter_chips}
        for dl in self.downloads.values():
            counts["all"] += 1
            if dl.status == DownloadStatus.DOWNLOADING:
                counts["active"] += 1
            elif dl.status == DownloadStatus.WAITING:
                counts["waiting"] += 1
            elif dl.status == DownloadStatus.PAUSED:
                counts["paused"] += 1
            elif dl.status == DownloadStatus.COMPLETED:
                counts["completed"] += 1
            elif dl.status in FAILED_STATES:
                counts["failed"] += 1
        for key, chip in self.filter_chips.items():
            chip.set_count(counts.get(key, 0))

    def sort_download_table(self, column):
        """Ordena manualmente: a ordenação nativa reordenaria a cada tick."""
        if column == COL_PROGRESS:
            return  # progresso é pintado por delegate, sem texto ordenável

        if self._download_sort_column == column:
            self._download_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._download_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._download_sort_column = column
            self._download_sort_order = Qt.SortOrder.AscendingOrder

        self.download_table.sortItems(column, self._download_sort_order)
        self.download_table.horizontalHeader().setSortIndicator(
            column, self._download_sort_order
        )
        self._rebuild_row_map()
        self.apply_list_filter()

    def on_selection_changed(self):
        self.update_toolbar_buttons()
        selected = self.download_table.selectionModel().selectedRows()
        if selected:
            item = self.download_table.item(selected[0].row(), COL_FILE)
            self.detail_uid = item.data(ROLE_UID) if item else None
        else:
            self.detail_uid = None
        self.update_detail_panel()

    def update_detail_panel(self):
        """Repinta o painel de detalhes com o download selecionado."""
        dl = self.downloads.get(self.detail_uid)
        if not dl:
            self.detail_grid.clear_values()
            self.segment_bar.set_segments([])
            return

        remaining = max(0, dl.total_bytes - dl.downloaded_bytes)
        self.detail_grid.set_value("file", dl.filename)
        self.detail_grid.set_value("item", dl.item_id or "—")
        self.detail_grid.set_value("status", dl.status.value)
        self.detail_grid.set_value(
            "size",
            f"{format_size(dl.downloaded_bytes)} / {format_size(dl.total_bytes)}"
            if dl.total_bytes > 0
            else self.t("calculating"),
        )
        self.detail_grid.set_value("speed", format_speed(dl.speed))
        self.detail_grid.set_value(
            "eta",
            format_eta(remaining, dl.speed)
            if dl.status == DownloadStatus.DOWNLOADING
            else "—",
        )
        self.detail_grid.set_value("folder", dl.dest_folder)
        self.detail_grid.set_value(
            "added", dl.date_added.strftime("%Y-%m-%d %H:%M:%S")
        )
        self.detail_grid.set_value(
            "completed",
            dl.date_completed.strftime("%Y-%m-%d %H:%M:%S")
            if dl.date_completed
            else "—",
        )
        self.detail_grid.set_value("id", dl.unique_id)

        segments = self.segment_snapshots.get(self.detail_uid)
        if not segments and dl.total_bytes > 0:
            # Sem telemetria ao vivo (pausado/concluído): mostra o agregado
            segments = [(dl.downloaded_bytes, dl.total_bytes)]
        self.segment_bar.set_segments(segments or [])

    def refresh_stats(self):
        """Recalcula métricas agregadas do rodapé, gráfico e bandeja (1 Hz)."""
        active = queued = done = 0
        total_speed = 0.0
        remaining = 0

        for dl in self.downloads.values():
            if dl.status == DownloadStatus.DOWNLOADING:
                active += 1
                total_speed += dl.speed or 0
                remaining += max(0, dl.total_bytes - dl.downloaded_bytes)
            elif dl.status == DownloadStatus.WAITING:
                queued += 1
            elif dl.status == DownloadStatus.COMPLETED:
                done += 1

        self.stat_active.set_value(str(active))
        self.stat_queued.set_value(str(queued))
        self.stat_done.set_value(str(done))
        self.stat_speed.set_value(format_speed(total_speed))
        self.stat_eta.set_value(format_eta(remaining, total_speed))
        self.speed_graph.add_sample(total_speed)

        if self.detail_uid:
            self.update_detail_panel()

        if self.tray:
            self.tray.setToolTip(
                self.t("tray_tooltip_running", count=active,
                       speed=format_speed(total_speed))
                if active
                else self.t("tray_tooltip_idle")
            )

    def update_speed_limit(self, value):
        self.speed_limit_kb = value
        self.settings.setValue("speed_limit_kb", value)
        set_global_rate_limit(value * 1024)
        if hasattr(self, "speed_limit_setting_spin"):
            self.speed_limit_setting_spin.blockSignals(True)
            self.speed_limit_setting_spin.setValue(value)
            self.speed_limit_setting_spin.blockSignals(False)
        log(f"[CONFIG] Limite global de velocidade: {value} KB/s")

    def toolbar_open_folder(self):
        selected = self.download_table.selectionModel().selectedRows()
        if not selected:
            return
        item = self.download_table.item(selected[0].row(), COL_FILE)
        dl = self.downloads.get(item.data(ROLE_UID)) if item else None
        if dl and os.path.exists(dl.dest_folder):
            self.open_folder(dl.dest_folder)

    def _file_missing(self, download_item):
        """True se o arquivo final de um download concluído não está mais no disco."""
        if not download_item.filename:
            return False
        path = os.path.join(download_item.dest_folder, download_item.filename)
        return not os.path.exists(path)

    def _is_restartable(self, download_item):
        """Cancelado/erro sempre; concluído só se o disco contradiz o status —
        seja por estar incompleto, seja por o usuário ter apagado o arquivo."""
        status = download_item.status
        if status in (DownloadStatus.CANCELLED, DownloadStatus.ERROR):
            return True
        if status == DownloadStatus.COMPLETED:
            if (
                download_item.total_bytes > 0
                and download_item.downloaded_bytes < download_item.total_bytes
            ):
                return True
            return self._file_missing(download_item)
        return False

    def update_toolbar_buttons(self):
        """Atualiza estado dos botões da toolbar baseado em todos os itens selecionados"""
        selected_rows = self.download_table.selectionModel().selectedRows()

        if not selected_rows:
            for action in self.selection_actions:
                action.setEnabled(False)
            return

        # Agrega os status de todos os itens selecionados
        any_pauseable = False   # DOWNLOADING ou WAITING
        any_resumable = False   # PAUSED
        any_cancelable = False
        any_restartable = False

        for index in selected_rows:
            uid = self.download_table.item(index.row(), COL_FILE).data(ROLE_UID)
            if not uid or uid not in self.downloads:
                continue
            dl = self.downloads[uid]
            status = dl.status

            if status in (DownloadStatus.DOWNLOADING, DownloadStatus.WAITING):
                any_pauseable = True
            if status in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
                any_resumable = True
            if status not in (DownloadStatus.CANCELLED, DownloadStatus.COMPLETED):
                any_cancelable = True
            if self._is_restartable(dl):
                any_restartable = True

        # Botão Pause/Resume — habilitado se qualquer item puder ser pausado ou retomado
        can_pause_resume = any_pauseable or any_resumable
        self.pause_resume_btn.setEnabled(can_pause_resume)
        if can_pause_resume:
            if any_pauseable:
                # Seleção mista conta como "pausar": a ação alterna item a item
                self.pause_resume_btn.setText(self.t("action_pause"))
                self.pause_resume_btn._icon_name = "pause"
            else:
                self.pause_resume_btn.setText(self.t("action_resume"))
                self.pause_resume_btn._icon_name = "play"
            self.pause_resume_btn.apply_tokens(self.tokens)

        self.cancel_btn.setEnabled(any_cancelable)
        self.restart_btn.setEnabled(any_restartable)
        self.remove_btn.setEnabled(True)

        # Abrir pasta: apenas com um item selecionado e pasta existente
        if len(selected_rows) == 1:
            uid = self.download_table.item(selected_rows[0].row(), COL_FILE).data(
                ROLE_UID
            )
            dl = self.downloads.get(uid)
            self.open_folder_btn.setEnabled(
                bool(dl) and os.path.exists(dl.dest_folder)
            )
        else:
            self.open_folder_btn.setEnabled(False)

        # Priority buttons: only for a single WAITING item
        if len(selected_rows) == 1:
            row = selected_rows[0].row()
            uid = self.download_table.item(row, COL_FILE).data(ROLE_UID)
            is_waiting = (
                uid and uid in self.downloads
                and self.downloads[uid].status == DownloadStatus.WAITING
            )
            self.priority_up_btn.setEnabled(is_waiting and row > 0)
            self.priority_down_btn.setEnabled(
                is_waiting and row < self.download_table.rowCount() - 1
            )
        else:
            self.priority_up_btn.setEnabled(False)
            self.priority_down_btn.setEnabled(False)

    def toolbar_pause_resume(self):
        """Pausa ou resume todos os downloads selecionados"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        for index in selected_rows:
            uid = self.download_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            if uid:
                self.toggle_pause(uid)

    def toolbar_cancel(self):
        """Cancela todos os downloads selecionados"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        for index in selected_rows:
            uid = self.download_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            if uid:
                self.cancel_download(uid)

    def toolbar_restart(self):
        """Reinicia todos os downloads selecionados"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        for index in selected_rows:
            uid = self.download_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            if uid:
                self.restart_download(uid)

    def toolbar_remove(self):
        """Remove todos os downloads selecionados da lista"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        uids = [
            self.download_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            for index in selected_rows
        ]
        self._remove_by_uids(uids)

    def _stop_download_for_removal(self, download_item):
        """Stop a queued/running download so it can be removed immediately."""
        if self.download_manager:
            self.download_manager.remove_download(download_item)

        thread = download_item.thread
        if thread:
            if thread.isRunning():
                thread.cancel()
            thread.wait()

        download_item.thread = None

    def _remove_download_entry(self, uid):
        """Remove one download entry regardless of its current state."""
        if not uid or uid not in self.downloads:
            return False

        download_item = self.downloads[uid]
        self._stop_download_for_removal(download_item)

        row = self._id_to_row.get(uid)
        del self.downloads[uid]
        self.segment_snapshots.pop(uid, None)

        if row is not None:
            self.download_table.removeRow(row)
            self._rebuild_row_map()

        return True

    def _remove_by_uids(self, uids):
        """Remove uma lista de downloads da tabela em qualquer estado."""
        removed_any = False
        for uid in uids:
            removed_any = self._remove_download_entry(uid) or removed_any

        if removed_any:
            self.save_downloads()
            self.update_toolbar_buttons()
            self.refresh_filter_counts()
            self.apply_list_filter()
            if self.detail_uid not in self.downloads:
                self.detail_uid = None
                self.update_detail_panel()

    # ------------------------------------------------------------------
    # Queue priority helpers
    # ------------------------------------------------------------------

    def _swap_table_rows(self, row1, row2):
        """Swap the contents of two rows in the download table and update _id_to_row."""
        if row1 == row2:
            return

        col_count = self.download_table.columnCount()

        # Sem cellWidget na tabela: o progresso vive nos data roles do item,
        # então trocar os QTableWidgetItem já leva junto barra e status.
        items_r1 = [self.download_table.takeItem(row1, c) for c in range(col_count)]
        items_r2 = [self.download_table.takeItem(row2, c) for c in range(col_count)]

        for c, item in enumerate(items_r2):
            if item:
                self.download_table.setItem(row1, c, item)
        for c, item in enumerate(items_r1):
            if item:
                self.download_table.setItem(row2, c, item)

        # Rebuild the id→row mapping for both affected rows
        for row in (row1, row2):
            name_item = self.download_table.item(row, COL_FILE)
            if name_item:
                uid = name_item.data(ROLE_UID)
                if uid:
                    self._id_to_row[uid] = row

    def move_priority_up(self):
        """Move the selected WAITING download one position higher in the queue."""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if len(selected_rows) != 1:
            return

        row = selected_rows[0].row()
        if row == 0:
            return

        name_item = self.download_table.item(row, 0)
        if not name_item:
            return
        uid = name_item.data(Qt.ItemDataRole.UserRole)
        if not uid or uid not in self.downloads:
            return
        if self.downloads[uid].status != DownloadStatus.WAITING:
            return

        self._swap_table_rows(row, row - 1)
        self.download_manager.move_up(uid)

        # Keep selection on the item that moved
        self.download_table.selectRow(row - 1)
        self.update_toolbar_buttons()

    def move_priority_down(self):
        """Move the selected WAITING download one position lower in the queue."""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if len(selected_rows) != 1:
            return

        row = selected_rows[0].row()
        if row >= self.download_table.rowCount() - 1:
            return

        name_item = self.download_table.item(row, 0)
        if not name_item:
            return
        uid = name_item.data(Qt.ItemDataRole.UserRole)
        if not uid or uid not in self.downloads:
            return
        if self.downloads[uid].status != DownloadStatus.WAITING:
            return

        self._swap_table_rows(row, row + 1)
        self.download_manager.move_down(uid)

        # Keep selection on the item that moved
        self.download_table.selectRow(row + 1)
        self.update_toolbar_buttons()

    def force_download_item(self, uid):
        """Bypass max_concurrent and start this WAITING download immediately."""
        if uid not in self.downloads:
            return
        download_item = self.downloads[uid]
        if download_item.status != DownloadStatus.WAITING:
            return
        self.download_manager.add_force_download(download_item)

    def _settings_row(self, card, label_text, widget, tooltip=None, stretch_widget=False):
        """Linha rótulo → controle dentro de um card de configurações."""
        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel(label_text)
        label.setMinimumWidth(190)
        label.setWordWrap(True)
        if tooltip:
            label.setToolTip(tooltip)
        row.addWidget(label)
        row.addWidget(widget, 1 if stretch_widget else 0)
        if not stretch_widget:
            row.addStretch()
        card.layout().addLayout(row)
        return row

    def create_settings_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(
            self.create_page_header(
                self.t("settings_title"), self.t("page_settings_sub")
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        # --- Aparência ------------------------------------------------------
        appearance = Card()
        appearance.layout().addWidget(SectionTitle(self.t("appearance_section")))

        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.t("appearance_theme_dark"), "dark")
        self.theme_combo.addItem(self.t("appearance_theme_light"), "light")
        self.theme_combo.setCurrentIndex(0 if self.theme_mode == "dark" else 1)
        self.theme_combo.currentIndexChanged.connect(self.change_theme_mode)
        self._settings_row(appearance, self.t("appearance_theme"), self.theme_combo)

        self.accent_combo = QComboBox()
        for name in ACCENTS:
            self.accent_combo.addItem(self.t(f"accent_{name}"), name)
        accent_index = list(ACCENTS).index(
            self.accent_name if self.accent_name in ACCENTS else "blue"
        )
        self.accent_combo.setCurrentIndex(accent_index)
        self.accent_combo.currentIndexChanged.connect(self.change_accent)
        self._settings_row(appearance, self.t("appearance_accent"), self.accent_combo)

        self.density_combo = QComboBox()
        for key in DENSITIES:
            self.density_combo.addItem(self.t(f"appearance_density_{key}"), key)
        self.density_combo.setCurrentIndex(
            list(DENSITIES).index(
                self.density if self.density in DENSITIES else "comfortable"
            )
        )
        self.density_combo.currentIndexChanged.connect(self.change_density)
        self._settings_row(appearance, self.t("appearance_density"), self.density_combo)

        appearance_note = QLabel(self.t("appearance_note"))
        appearance_note.setProperty("class", "note")
        appearance_note.setWordWrap(True)
        appearance.layout().addWidget(appearance_note)
        layout.addWidget(appearance)

        # --- Conta ----------------------------------------------------------
        account = Card()
        account.layout().addWidget(SectionTitle(self.t("account_section")))
        account_desc = QLabel(self.t("account_description"))
        account_desc.setProperty("class", "muted")
        account_desc.setWordWrap(True)
        account.layout().addWidget(account_desc)

        self.account_status_label = QLabel()
        self.update_account_status()
        account.layout().addWidget(self.account_status_label)

        self.ia_email_input = QLineEdit()
        self.ia_email_input.setPlaceholderText(self.t("account_email_placeholder"))
        self._settings_row(
            account, self.t("account_email"), self.ia_email_input, stretch_widget=True
        )

        self.ia_password_input = QLineEdit()
        self.ia_password_input.setPlaceholderText(
            self.t("account_password_placeholder")
        )
        self.ia_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._settings_row(
            account,
            self.t("account_password"),
            self.ia_password_input,
            stretch_widget=True,
        )

        account_buttons = QHBoxLayout()
        account_buttons.setSpacing(10)
        self.ia_login_btn = QPushButton(self.t("account_login"))
        self.ia_login_btn.clicked.connect(self.ia_login)
        self.ia_logout_btn = QPushButton(self.t("account_logout"))
        self.ia_logout_btn.setProperty("class", "secondary")
        self.ia_logout_btn.clicked.connect(self.ia_logout)
        account_buttons.addStretch()
        account_buttons.addWidget(self.ia_logout_btn)
        account_buttons.addWidget(self.ia_login_btn)
        account.layout().addLayout(account_buttons)

        account_note = QLabel(self.t("account_note"))
        account_note.setProperty("class", "note")
        account_note.setWordWrap(True)
        account.layout().addWidget(account_note)
        layout.addWidget(account)

        # --- Pasta padrão ---------------------------------------------------
        folder = Card()
        folder.layout().addWidget(SectionTitle(self.t("folder_section")))
        folder_desc = QLabel(self.t("folder_description"))
        folder_desc.setProperty("class", "muted")
        folder_desc.setWordWrap(True)
        folder.layout().addWidget(folder_desc)

        folder_control = QHBoxLayout()
        folder_control.setSpacing(10)
        self.default_folder_input = QLineEdit()
        self.default_folder_input.setPlaceholderText(self.t("folder_placeholder"))
        self.default_folder_input.setText(self.default_download_folder)
        self.default_folder_input.setReadOnly(True)
        self.choose_folder_btn = QPushButton(self.t("folder_choose"))
        self.choose_folder_btn.clicked.connect(self.choose_default_folder)
        self.clear_folder_btn = QPushButton(self.t("folder_clear"))
        self.clear_folder_btn.setProperty("class", "secondary")
        self.clear_folder_btn.clicked.connect(self.clear_default_folder)
        folder_control.addWidget(self.default_folder_input, 1)
        folder_control.addWidget(self.choose_folder_btn)
        folder_control.addWidget(self.clear_folder_btn)
        folder.layout().addLayout(folder_control)
        layout.addWidget(folder)

        # --- Desempenho -----------------------------------------------------
        perf = Card()
        perf.layout().addWidget(SectionTitle(self.t("perf_section")))

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(self.max_concurrent)
        self.concurrent_spin.valueChanged.connect(self.update_concurrent_limit)
        self._settings_row(
            perf,
            self.t("perf_concurrent"),
            self.concurrent_spin,
            self.t("perf_concurrent_tooltip"),
        )

        self.segments_spin = QSpinBox()
        self.segments_spin.setRange(1, 16)
        self.segments_spin.setValue(self.segments_per_file)
        self.segments_spin.setToolTip(self.t("perf_connections_note_tooltip"))
        self.segments_spin.valueChanged.connect(self.update_segments_per_file)
        self._settings_row(
            perf,
            self.t("perf_connections"),
            self.segments_spin,
            self.t("perf_connections_tooltip"),
        )

        self.speed_limit_setting_spin = QSpinBox()
        self.speed_limit_setting_spin.setRange(0, 1024 * 100)
        self.speed_limit_setting_spin.setSingleStep(256)
        self.speed_limit_setting_spin.setValue(self.speed_limit_kb)
        self.speed_limit_setting_spin.setSuffix(" KB/s")
        self.speed_limit_setting_spin.setSpecialValueText(self.t("speed_unlimited"))
        self.speed_limit_setting_spin.valueChanged.connect(
            self.on_settings_speed_limit_changed
        )
        self._settings_row(
            perf,
            self.t("perf_speed_limit"),
            self.speed_limit_setting_spin,
            self.t("perf_speed_limit_tooltip"),
        )

        perf_note = QLabel(self.t("perf_note"))
        perf_note.setProperty("class", "note")
        perf_note.setWordWrap(True)
        perf.layout().addWidget(perf_note)
        layout.addWidget(perf)

        # --- Comportamento / bandeja ---------------------------------------
        behaviour = Card()
        behaviour.layout().addWidget(SectionTitle(self.t("debug_section")))

        self.tray_checkbox = QCheckBox(self.t("tray_minimize"))
        self.tray_checkbox.setChecked(self.minimize_to_tray)
        self.tray_checkbox.setEnabled(QSystemTrayIcon.isSystemTrayAvailable())
        self.tray_checkbox.stateChanged.connect(self.toggle_minimize_to_tray)
        behaviour.layout().addWidget(self.tray_checkbox)

        self.enable_logging_checkbox = QCheckBox(self.t("debug_logging"))
        self.enable_logging_checkbox.setChecked(
            self.settings.value("enable_logging", True, type=bool)
        )
        self.enable_logging_checkbox.stateChanged.connect(self.toggle_logging)
        behaviour.layout().addWidget(self.enable_logging_checkbox)

        logging_note = QLabel(self.t("debug_note"))
        logging_note.setProperty("class", "note")
        logging_note.setWordWrap(True)
        behaviour.layout().addWidget(logging_note)
        layout.addWidget(behaviour)

        # --- Idioma ---------------------------------------------------------
        language = Card()
        language.layout().addWidget(SectionTitle("🌐 Idioma / Language"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("Português (Brasil)", "pt-BR")
        self.language_combo.addItem("English (US)", "en")
        self.language_combo.setCurrentIndex(
            0 if self.current_language == "pt-BR" else 1
        )
        self.language_combo.currentIndexChanged.connect(self.change_language)
        self._settings_row(
            language,
            "Idioma da interface / Interface language:",
            self.language_combo,
        )
        language_note = QLabel(
            "💡 Nota: O aplicativo será reiniciado para aplicar o novo idioma\n"
            "💡 Note: The application will restart to apply the new language"
        )
        language_note.setProperty("class", "note")
        language_note.setWordWrap(True)
        language.layout().addWidget(language_note)
        layout.addWidget(language)

        layout.addStretch()
        return page

    def on_settings_speed_limit_changed(self, value):
        """Espelha o spin dos ajustes no da barra de status (fonte da verdade)."""
        self.speed_limit_spin.setValue(value)

    def toggle_minimize_to_tray(self, state):
        self.minimize_to_tray = bool(state)
        self.settings.setValue("minimize_to_tray", self.minimize_to_tray)

    def update_account_status(self):
        """Atualiza o status da conta do Internet Archive"""
        try:
            # Tenta usar a própria biblioteca para verificar se está autenticado
            from internetarchive import get_session

            # Cria uma sessão e verifica se tem credenciais
            session = get_session()

            # Verifica se a sessão tem cookies ou access/secret keys configurados
            has_cookies = bool(session.cookies)
            has_s3_keys = bool(session.access_key and session.secret_key)

            log(f"[ACCOUNT] has_cookies={has_cookies}, has_s3_keys={has_s3_keys}")
            log(
                f"[ACCOUNT] access_key={session.access_key}, secret_key={'***' if session.secret_key else None}"
            )

            if has_cookies or has_s3_keys:
                # Tenta identificar o email se possível
                email = getattr(session, "user_email", None) or "configurada"
                self.account_status_label.setText(self.t("account_configured"))
                self.account_status_label.setProperty("class", "success")
                log(f"[ACCOUNT] Conta detectada: {email}")
                return

            # Se não encontrou credenciais, verifica arquivos de configuração manualmente
            config_paths = [
                os.path.expanduser("~/.config/ia.ini"),
                os.path.expanduser("~/.ia"),
                os.path.join(os.environ.get("APPDATA", ""), "ia.ini")
                if os.name == "nt"
                else None,
            ]

            for config_file in config_paths:
                if config_file and os.path.exists(config_file):
                    log(f"[ACCOUNT] Verificando arquivo: {config_file}")
                    with open(config_file, "r") as f:
                        content = f.read()
                        if (
                            "cookies" in content
                            or "access" in content
                            or "secret" in content
                        ):
                            self.account_status_label.setText(
                                self.t("account_configured_file")
                            )
                            self.account_status_label.setProperty("class", "success")
                            log(f"[ACCOUNT] Credenciais encontradas em: {config_file}")
                            return

            self.account_status_label.setText(self.t("account_not_configured"))
            self.account_status_label.setProperty("class", "muted")
            log("[ACCOUNT] Nenhuma credencial encontrada")

        except Exception as e:
            log(f"[ACCOUNT] Erro ao verificar status: {e}")
            import traceback

            traceback.print_exc()
            self.account_status_label.setText(self.t("account_unknown"))
            self.account_status_label.setProperty("class", "muted")

    def ia_login(self):
        """Faz login na conta do Internet Archive"""
        email = self.ia_email_input.text().strip()
        password = self.ia_password_input.text().strip()

        if not email or not password:
            QMessageBox.warning(self, self.t("warning"), self.t("warn_account_fill"))
            return

        try:
            log(f"[ACCOUNT] Tentando fazer login com: {email}")

            # Usa a função configure do internetarchive.config
            from internetarchive.config import configure

            # Configura com email e senha
            config_dict = configure(username=email, password=password)

            if config_dict:
                self.update_account_status()
                self.ia_email_input.clear()
                self.ia_password_input.clear()
                QMessageBox.information(
                    self, self.t("success"), self.t("success_login")
                )
                log(f"[ACCOUNT] Login bem-sucedido para: {email}")
            else:
                QMessageBox.warning(
                    self,
                    self.t("error"),
                    "Falha ao fazer login. Verifique suas credenciais.",
                )

        except Exception as e:
            log(f"[ACCOUNT] Erro ao fazer login: {e}")
            QMessageBox.critical(
                self, self.t("error"), self.t("error_login", error=str(e))
            )

    def ia_logout(self):
        """Remove credenciais do Internet Archive"""
        reply = QMessageBox.question(
            self,
            self.t("confirm"),
            self.t("confirm_logout"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                config_file = os.path.expanduser("~/.config/ia.ini")
                config_file_alt = os.path.expanduser("~/.ia")  # Arquivo alternativo

                removed = False

                if os.path.exists(config_file):
                    os.remove(config_file)
                    log(f"[ACCOUNT] Arquivo de configuração removido: {config_file}")
                    removed = True

                if os.path.exists(config_file_alt):
                    os.remove(config_file_alt)
                    log(
                        f"[ACCOUNT] Arquivo de configuração alternativo removido: {config_file_alt}"
                    )
                    removed = True

                self.update_account_status()
                self.ia_email_input.clear()
                self.ia_password_input.clear()

                if removed:
                    QMessageBox.information(
                        self, self.t("success"), self.t("success_logout")
                    )
                else:
                    QMessageBox.information(
                        self, self.t("info"), self.t("success_logout_none")
                    )

            except Exception as e:
                log(f"[ACCOUNT] Erro ao remover credenciais: {e}")
                QMessageBox.critical(
                    self, self.t("error"), self.t("error_logout", error=str(e))
                )

    def choose_default_folder(self):
        """Abre diálogo para escolher pasta padrão"""
        folder = QFileDialog.getExistingDirectory(
            self, self.t("folder_dialog_title"), self.default_download_folder
        )

        if folder:
            self.default_download_folder = folder
            self.default_folder_input.setText(folder)
            self.settings.setValue("default_download_folder", folder)
            log(f"[CONFIG] Pasta padrão definida: {folder}")

    def clear_default_folder(self):
        """Limpa a pasta padrão"""
        self.default_download_folder = ""
        self.default_folder_input.setText("")
        self.settings.setValue("default_download_folder", "")
        log("[CONFIG] Pasta padrão removida")

    def toggle_logging(self, state):
        """Habilita ou desabilita os logs no console"""
        enabled = state == 2  # Qt.CheckState.Checked

        # Mostra mensagem antes de mudar (para ser visível)
        if enabled:
            print("[CONFIG] Habilitando logs...")
        else:
            print("[CONFIG] Desabilitando logs...")

        self.set_logging_enabled(enabled)
        self.settings.setValue("enable_logging", enabled)

        # Confirma a mudança (só aparece se logs estiverem habilitados)
        log(
            f"[CONFIG] Logs agora estão {'habilitados' if enabled else 'desabilitados'}"
        )

    def set_logging_enabled(self, enabled):
        """Define se os logs devem ser exibidos"""
        set_logging_enabled(enabled)

    def add_file_on_double_click(self, item):
        """Adiciona arquivo à fila ao dar duplo clique (usa pasta padrão)"""
        if not self.default_download_folder:
            QMessageBox.warning(
                self,
                self.t("info_no_default_folder_title"),
                self.t("warn_no_default_folder"),
            )
            return

        filename = item.data(Qt.ItemDataRole.UserRole)
        log(
            f"[QUICK-ADD] Arquivo adicionado via duplo clique: {filename} -> {self.default_download_folder}"
        )
        self._add_single_file_to_queue(filename, self.default_download_folder)

    def show_file_list_context_menu(self, position):
        """Mostra menu de contexto ao clicar com botão direito na lista de arquivos"""
        context_menu = QMenu(self)

        has_items = self.file_list.count() > 0
        has_selection = bool(self.file_list.selectedItems())

        select_all_action = context_menu.addAction(self.t("context_select_all"))
        select_all_action.setEnabled(has_items)

        copy_names_action = context_menu.addAction(self.t("context_copy_filenames"))
        copy_names_action.setEnabled(has_selection)

        context_menu.addSeparator()

        download_now_action = context_menu.addAction(self.t("context_download_now"))
        download_as_action = context_menu.addAction(self.t("context_download_as"))

        download_now_action.setEnabled(has_selection)
        download_as_action.setEnabled(has_selection)

        # Desabilita "Baixar Agora" se não há pasta padrão configurada
        if not self.default_download_folder:
            download_now_action.setEnabled(False)
            download_now_action.setToolTip(self.t("warn_no_default_folder"))

        action = context_menu.exec(self.file_list.viewport().mapToGlobal(position))

        if action == select_all_action:
            self.file_list.selectAll()
        elif action == copy_names_action:
            self._context_copy_filenames()
        elif action == download_now_action:
            self._context_download_now()
        elif action == download_as_action:
            self._context_download_as()

    def _context_download_now(self):
        """Baixa os arquivos selecionados usando a pasta padrão"""
        if not self.default_download_folder:
            QMessageBox.warning(
                self,
                self.t("info_no_default_folder_title"),
                self.t("warn_no_default_folder"),
            )
            return

        selected_items = self.file_list.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            filename = item.data(Qt.ItemDataRole.UserRole)
            self._add_single_file_to_queue(filename, self.default_download_folder)

    def _context_download_as(self):
        """Baixa os arquivos selecionados permitindo escolher a pasta de destino"""
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            return

        dest_folder = QFileDialog.getExistingDirectory(
            self, self.t("folder_dialog_title"), self.default_download_folder
        )

        if not dest_folder:
            return

        for item in selected_items:
            filename = item.data(Qt.ItemDataRole.UserRole)
            self._add_single_file_to_queue(filename, dest_folder)

    def _context_copy_filenames(self):
        """Copia os nomes dos arquivos selecionados para a área de transferência"""
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            return

        names = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]
        text = "\n".join(names)
        QApplication.clipboard().setText(text)
        log(f"[CLIPBOARD] {len(names)} nome(s) de arquivo copiado(s)")

    def _add_single_file_to_queue(self, filename, dest_folder):
        """Adiciona um único arquivo à fila de download"""
        identifier = self.id_input.text().strip()

        file_size = 0
        for f in self.all_files:
            if f["name"] == filename:
                file_size = int(f.get("size", 0))
                break

        download_item = DownloadItem(
            identifier, filename, dest_folder, segments=self.segments_per_file
        )
        download_item.total_bytes = file_size

        if self._is_duplicate(download_item):
            QMessageBox.information(
                self,
                self.t("info_already_queued"),
                self.t("warn_already_queued", filename=filename),
            )
            return

        self.downloads[download_item.unique_id] = download_item
        self.add_download_to_table(download_item)
        self.download_manager.add_download(download_item)

        log(f"[CONTEXT-MENU] Arquivo adicionado: {filename} -> {dest_folder}")
        self.statusBar().showMessage(
            self.t("info_added_to_queue", filename=filename), 3000
        )

    def start_download_manager(self):
        self.download_manager = DownloadManager(self.max_concurrent)
        self.download_manager.download_started.connect(self.on_download_started)
        self.download_manager.start()

    def search_files(self):
        identifier = self.id_input.text().strip()

        if not identifier:
            QMessageBox.warning(
                self, self.t("warning"), self.t("warn_identifier_empty")
            )
            return

        self.status_label.setText(self.t("searching_item", identifier=identifier))
        self.file_list.clear()
        self.search_btn.setEnabled(False)

        try:
            self.item = ia.get_item(identifier)

            if not self.item.exists:
                QMessageBox.warning(
                    self,
                    self.t("error"),
                    self.t("item_not_found", identifier=identifier),
                )
                self.status_label.setText("")
                self.search_btn.setEnabled(True)
                return

            files = list(self.item.files)

            if not files:
                QMessageBox.information(self, self.t("info"), self.t("no_files_found"))
                self.status_label.setText("")
                self.search_btn.setEnabled(True)
                return

            self.all_files = files

            for file in files:
                item_widget = QListWidgetItem(
                    f"{file['name']} ({format_size(file.get('size', 0))})"
                )
                item_widget.setData(Qt.ItemDataRole.UserRole, file["name"])
                self.file_list.addItem(item_widget)

            self.status_label.setText(self.t("files_found", count=len(files)))
            self.download_btn.setEnabled(True)

            self.add_to_recent(identifier)

            # Salva como último identifier usado
            self.last_identifier = identifier
            self.settings.setValue("last_identifier", identifier)
            log(f"[CONFIG] Último identifier salvo: {identifier}")

        except Exception as e:
            QMessageBox.critical(
                self, self.t("error"), self.t("error_load_files", error=str(e))
            )
            self.status_label.setText("")

        finally:
            self.search_btn.setEnabled(True)

    def filter_files(self):
        filter_text = self.filter_input.text().lower()

        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            filename = item.data(Qt.ItemDataRole.UserRole).lower()

            if not filter_text or filter_text in filename:
                item.setHidden(False)
            else:
                item.setHidden(True)

    def add_to_queue(self):
        selected_items = self.file_list.selectedItems()

        if not selected_items:
            QMessageBox.warning(
                self, self.t("warning"), self.t("warn_no_files_selected")
            )
            return

        dest_folder = QFileDialog.getExistingDirectory(
            self, self.t("folder_dialog_title")
        )

        if not dest_folder:
            return

        identifier = self.id_input.text().strip()

        for item in selected_items:
            filename = item.data(Qt.ItemDataRole.UserRole)

            # Busca o tamanho do arquivo na lista
            file_size = 0
            for f in self.all_files:
                if f["name"] == filename:
                    file_size = int(f.get("size", 0))
                    break

            download_item = DownloadItem(
                identifier, filename, dest_folder, segments=self.segments_per_file
            )
            download_item.total_bytes = file_size

            if self._is_duplicate(download_item):
                QMessageBox.warning(
                    self,
                    self.t("warning"),
                    self.t("warn_file_already_queued", filename=filename),
                )
                continue

            self.downloads[download_item.unique_id] = download_item
            self.add_download_to_table(download_item)
            self.download_manager.add_download(download_item)

        QMessageBox.information(
            self,
            self.t("success"),
            self.t("info_files_added", count=len(selected_items)),
        )

    def show_add_url_dialog(self):
        """Mostra dialog para adicionar URL"""
        url, ok = QInputDialog.getText(
            self,
            self.t("add_url_title"),
            self.t("add_url_prompt"),
            QLineEdit.EchoMode.Normal,
            "",
        )

        if ok and url:
            self.add_url_to_queue(url.strip())

    def add_url_to_queue(self, url, interactive=True):
        """Adiciona URL à fila. Com interactive=False (drag & drop) não abre
        diálogos: usa a pasta padrão/última usada e devolve True/False."""
        if not url:
            if interactive:
                QMessageBox.warning(self, self.t("warning"), self.t("warn_url_empty"))
            return False

        last_url_folder = self.settings.value(
            "last_url_download_folder", self.default_download_folder
        )

        if interactive:
            dest_folder = QFileDialog.getExistingDirectory(
                self, self.t("folder_dialog_title"), last_url_folder
            )
        else:
            dest_folder = last_url_folder or self.default_download_folder

        if not dest_folder:
            if not interactive:
                self.statusBar().showMessage(
                    self.t("warn_no_default_folder"), 5000
                )
            return False

        filename = unquote(url.split("/")[-1])

        self.settings.setValue("last_url_download_folder", dest_folder)

        download_item = DownloadItem(
            "", filename, dest_folder, url=url, segments=self.segments_per_file
        )

        if self._is_duplicate(download_item):
            if interactive:
                QMessageBox.warning(
                    self,
                    self.t("warning"),
                    self.t("warn_already_queued", filename=filename),
                )
            return False

        self.downloads[download_item.unique_id] = download_item
        self.add_download_to_table(download_item)
        self.download_manager.add_download(download_item)

        if interactive:
            QMessageBox.information(self, self.t("success"), self.t("info_file_added"))
        return True

    def _rebuild_row_map(self):
        """Rebuilds unique_id→row dict after rows are inserted or removed."""
        self._id_to_row = {}
        for r in range(self.download_table.rowCount()):
            item = self.download_table.item(r, 0)
            if item:
                uid = item.data(Qt.ItemDataRole.UserRole)
                if uid:
                    self._id_to_row[uid] = r

    def _row_tooltip(self, download_item):
        parts = [
            download_item.filename,
            f"{self.t('tooltip_id')}: {download_item.unique_id[:8]}...",
            f"{self.t('tooltip_added')}: {download_item.date_added.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if download_item.date_completed:
            parts.append(
                f"{self.t('tooltip_completed')}: "
                f"{download_item.date_completed.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        return "\n".join(parts)

    def add_download_to_table(self, download_item):
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        self.download_table.setRowHeight(row, self.tokens["row_h_px"])
        self._id_to_row[download_item.unique_id] = row

        filename_item = QTableWidgetItem(download_item.filename)
        filename_item.setToolTip(self._row_tooltip(download_item))
        # unique_id no UserRole: todas as buscas linha→download usam a UUID
        # estável, não o nome exibido (que pode repetir).
        filename_item.setData(ROLE_UID, download_item.unique_id)
        self.download_table.setItem(row, COL_FILE, filename_item)

        # O delegate de status lê o texto; o de progresso lê ROLE_PROGRESS
        # e ROLE_STATUS — nenhum widget por linha.
        status_item = QTableWidgetItem(download_item.status.value)
        self.download_table.setItem(row, COL_STATUS, status_item)

        progress_item = QTableWidgetItem()
        progress_item.setData(ROLE_PROGRESS, download_item.progress)
        progress_item.setData(ROLE_STATUS, download_item.status.value)
        progress_item.setData(ROLE_SORT, download_item.progress)
        self.download_table.setItem(row, COL_PROGRESS, progress_item)

        if download_item.total_bytes > 0:
            size_text = (
                f"{format_size(download_item.downloaded_bytes)} / "
                f"{format_size(download_item.total_bytes)}"
            )
        else:
            size_text = self.t("calculating")
        self.download_table.setItem(row, COL_SIZE, QTableWidgetItem(size_text))

        self.download_table.setItem(row, COL_SPEED, QTableWidgetItem("—"))
        self.download_table.setItem(row, COL_ETA, QTableWidgetItem("—"))

        connections_item = QTableWidgetItem(f"{max(download_item.segments, 1)}x")
        connections_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        connections_item.setToolTip(
            self.t("tooltip_connections", count=download_item.segments)
        )
        self.download_table.setItem(row, COL_CONN, connections_item)

        message_item = QTableWidgetItem(download_item.error_msg)
        message_item.setToolTip(download_item.error_msg)
        self.download_table.setItem(row, COL_MESSAGE, message_item)

        self.refresh_filter_counts()
        self.download_table.setRowHidden(
            row, not self._row_matches_filter(download_item)
        )

    def on_download_started(self, uid):
        if uid in self.downloads:
            download_item = self.downloads[uid]
            if download_item.thread:
                download_item.thread.progress_updated.connect(
                    lambda u, data: self.update_progress(u, data)
                )
                download_item.thread.status_changed.connect(
                    lambda u, status, msg: self.update_status(u, status, msg)
                )

            # The thread emits status_changed(DOWNLOADING) the moment it starts,
            # which is before this slot runs and connects the signal — that first
            # emission is lost.  Force the status update here so the download is
            # immediately pauseable/cancellable.
            self.update_status(uid, DownloadStatus.DOWNLOADING, "")

    def update_progress(self, uid, data):
        progress = data.get("progress", 0)
        downloaded = data.get("downloaded", 0)
        total = data.get("total", 0)
        speed = data.get("speed", 0.0)
        segments = data.get("segments")

        if uid in self.downloads:
            dl = self.downloads[uid]
            dl.progress = progress
            dl.downloaded_bytes = downloaded
            if 0 < total < 100_000_000_000_000:  # sanity: < 100 TB
                dl.total_bytes = total
            dl.speed = speed

        if segments:
            self.segment_snapshots[uid] = list(segments)

        row = self._id_to_row.get(uid)
        if row is not None:
            progress_item = self.download_table.item(row, COL_PROGRESS)
            if progress_item:
                progress_item.setData(ROLE_PROGRESS, progress)
                progress_item.setData(ROLE_SORT, progress)

            size_item = self.download_table.item(row, COL_SIZE)
            if size_item:
                size_item.setText(f"{format_size(downloaded)} / {format_size(total)}")

            speed_item = self.download_table.item(row, COL_SPEED)
            if speed_item:
                speed_item.setText(format_speed(speed))

            eta_item = self.download_table.item(row, COL_ETA)
            if eta_item:
                eta_item.setText(format_eta(max(0, total - downloaded), speed))

    def update_status(self, uid, status, error_msg):
        if uid in self.downloads:
            self.downloads[uid].status = status
            self.downloads[uid].error_msg = error_msg

            # Define date_completed quando o download é concluído
            if (
                status == DownloadStatus.COMPLETED
                and self.downloads[uid].date_completed is None
            ):
                from datetime import datetime

                self.downloads[uid].date_completed = datetime.now()
                log(
                    f"[STATUS] Download concluído: {self.downloads[uid].filename} em {self.downloads[uid].date_completed}"
                )

            # Salva automaticamente quando o status muda
            if status in [
                DownloadStatus.COMPLETED,
                DownloadStatus.ERROR,
                DownloadStatus.PAUSED,
            ]:
                self.save_downloads()

        if status == DownloadStatus.COMPLETED:
            self.segment_snapshots.pop(uid, None)
            if self.tray and uid in self.downloads:
                self.tray.showMessage(
                    self.t("tray_completed"),
                    self.downloads[uid].filename,
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )

        self._paint_status_row(uid, status, error_msg)
        self.refresh_filter_counts()
        if uid == self.detail_uid:
            self.update_detail_panel()

    def _paint_status_row(self, uid, status, error_msg=None):
        """Escreve status/mensagem na linha e reaplica o filtro ativo."""
        row = self._id_to_row.get(uid)
        if row is None:
            return

        download_item = self.downloads.get(uid)
        if download_item:
            filename_item = self.download_table.item(row, COL_FILE)
            if filename_item:
                filename_item.setToolTip(self._row_tooltip(download_item))

        status_item = self.download_table.item(row, COL_STATUS)
        if status_item:
            status_item.setText(status.value)

        progress_item = self.download_table.item(row, COL_PROGRESS)
        if progress_item:
            progress_item.setData(ROLE_STATUS, status.value)
            if status == DownloadStatus.COMPLETED:
                progress_item.setData(ROLE_PROGRESS, 100)
                progress_item.setData(ROLE_SORT, 100)

        if error_msg is not None:
            msg_item = self.download_table.item(row, COL_MESSAGE)
            if msg_item:
                msg_item.setText(error_msg)
                msg_item.setToolTip(error_msg)

        if status != DownloadStatus.DOWNLOADING:
            speed_item = self.download_table.item(row, COL_SPEED)
            if speed_item:
                speed_item.setText("—")
            eta_item = self.download_table.item(row, COL_ETA)
            if eta_item:
                eta_item.setText("—")

        if download_item:
            self.download_table.setRowHidden(
                row, not self._row_matches_filter(download_item)
            )

        # Atualiza botões da toolbar se esta linha estiver selecionada
        self.update_toolbar_buttons()

    def toggle_pause(self, uid):
        if uid not in self.downloads:
            return

        download_item = self.downloads[uid]

        # Se não tem thread rodando (download pausado de sessão anterior ou com erro)
        if not download_item.thread or not download_item.thread.isRunning():
            # Inicia se estava pausado, aguardando ou com erro (retry preservando parciais)
            if download_item.status in [DownloadStatus.PAUSED, DownloadStatus.WAITING, DownloadStatus.ERROR]:
                # Limpa mensagem de erro se estava com erro
                if download_item.status == DownloadStatus.ERROR:
                    download_item.error_msg = ""

                # Adiciona à fila para iniciar
                download_item.thread = None
                self.download_manager.add_download(download_item)
                download_item.status = DownloadStatus.WAITING

                self._paint_status_row(uid, DownloadStatus.WAITING, "")
                self.refresh_filter_counts()
                self.save_downloads()
            return

        # Se tem thread rodando, pausa ou retoma.
        # WAITING is treated the same as DOWNLOADING: the thread may still show
        # WAITING if the initial status_changed(DOWNLOADING) signal fired before
        # its connection was registered in on_download_started.
        if download_item.status in [DownloadStatus.DOWNLOADING, DownloadStatus.WAITING]:
            download_item.thread.pause()
            download_item.status = DownloadStatus.PAUSED
            self._paint_status_row(uid, DownloadStatus.PAUSED)
            self.refresh_filter_counts()
            self.save_downloads()

        elif download_item.status == DownloadStatus.PAUSED:
            download_item.thread.resume()
            download_item.status = DownloadStatus.DOWNLOADING
            self._paint_status_row(uid, DownloadStatus.DOWNLOADING)
            self.refresh_filter_counts()
            self.save_downloads()

    def cancel_download(self, uid):
        if uid not in self.downloads:
            return

        download_item = self.downloads[uid]

        if download_item.thread and download_item.thread.isRunning():
            download_item.thread.cancel()
            download_item.thread.wait()

        self.update_status(
            uid, DownloadStatus.CANCELLED, self.t("status_cancelled_by_user")
        )

    def restart_download(self, uid):
        """Recomeça um download cancelado do zero"""
        if uid not in self.downloads:
            return

        download_item = self.downloads[uid]

        # Remove arquivo principal se existir
        dest_path = os.path.join(download_item.dest_folder, download_item.filename)
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
                log(f"[RESTART] Arquivo principal removido: {dest_path}")
            except Exception as e:
                log(f"[RESTART] Erro ao remover arquivo principal: {e}")

        # Remove segmentos parciais se existirem
        for i in range(download_item.segments):
            segment_file = f"{dest_path}.part{i}"
            if os.path.exists(segment_file):
                try:
                    os.remove(segment_file)
                    log(f"[RESTART] Segmento {i} removido: {segment_file}")
                except Exception as e:
                    log(f"[RESTART] Erro ao remover segmento {i}: {e}")

        # Reset estado do download_item
        download_item.status = DownloadStatus.WAITING
        download_item.progress = 0
        download_item.downloaded_bytes = 0
        download_item.error_msg = ""
        download_item.thread = None
        download_item.date_completed = None  # Reset data de conclusão

        # Atualiza data de adição (considerando como nova tentativa)
        from datetime import datetime

        download_item.date_added = datetime.now()

        log(f"[RESTART] Download reiniciado: {download_item.filename}")

        # Adiciona à fila novamente
        self.download_manager.add_download(download_item)

        # Atualiza GUI
        self.segment_snapshots.pop(uid, None)
        row = self._id_to_row.get(uid)
        if row is not None:
            progress_item = self.download_table.item(row, COL_PROGRESS)
            if progress_item:
                progress_item.setData(ROLE_PROGRESS, 0)
                progress_item.setData(ROLE_SORT, 0)

            size_item = self.download_table.item(row, COL_SIZE)
            if size_item:
                size_item.setText(
                    f"0 B / {format_size(download_item.total_bytes)}"
                    if download_item.total_bytes > 0
                    else self.t("calculating")
                )

        self._paint_status_row(uid, DownloadStatus.WAITING, "")
        self.refresh_filter_counts()
        if uid == self.detail_uid:
            self.update_detail_panel()

    def clear_completed(self):
        uids_to_remove = []

        for row in range(self.download_table.rowCount()):
            uid = self.download_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if uid and uid in self.downloads:
                status = self.downloads[uid].status
                if status in [
                    DownloadStatus.COMPLETED,
                    DownloadStatus.CANCELLED,
                    DownloadStatus.ERROR,
                ]:
                    uids_to_remove.append(uid)

        self._remove_by_uids(uids_to_remove)

    def cancel_all(self):
        for uid in list(self.downloads.keys()):
            self.cancel_download(uid)

    def update_concurrent_limit(self, value):
        self.max_concurrent = value
        if self.download_manager:
            self.download_manager.update_max_concurrent(value)
        self.settings.setValue("max_concurrent", value)
        log(f"[CONFIG] Downloads simultâneos alterado para: {value}")

    def update_segments_per_file(self, value):
        self.segments_per_file = value
        self.settings.setValue("segments_per_file", value)
        log(f"[CONFIG] Conexões por arquivo alterado para: {value}")

    def change_language(self, index):
        """Muda o idioma da interface"""
        new_language = self.language_combo.itemData(index)

        if new_language == self.current_language:
            return  # Não precisa fazer nada se é o mesmo idioma

        # Salva o novo idioma
        self.settings.setValue("language", new_language)
        log(f"[CONFIG] Idioma alterado para: {new_language}")

        # Confirma com o usuário que o app será reiniciado
        reply = QMessageBox.question(
            self,
            "Reiniciar / Restart",
            "O aplicativo precisa ser reiniciado para aplicar o novo idioma.\n"
            "The application needs to restart to apply the new language.\n\n"
            "Deseja reiniciar agora?\n"
            "Do you want to restart now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Salva downloads antes de reiniciar
            self.save_downloads()

            # Reinicia o aplicativo
            import subprocess

            subprocess.Popen([sys.executable] + sys.argv)
            QApplication.quit()
        else:
            # Restaura o combo box para o idioma atual
            current_index = 0 if self.current_language == "pt-BR" else 1
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(current_index)
            self.language_combo.blockSignals(False)

    def show_context_menu(self, position):
        """Mostra menu de contexto ao clicar com botão direito na tabela"""
        item = self.download_table.itemAt(position)
        if not item:
            return

        row = item.row()
        column = item.column()
        uid = self.download_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if not uid or uid not in self.downloads:
            return

        # Se o item clicado está dentro da seleção atual, as ações se aplicam a
        # todos os selecionados; caso contrário, apenas ao item clicado.
        selected_row_indices = {
            idx.row()
            for idx in self.download_table.selectionModel().selectedRows()
        }
        if row in selected_row_indices:
            target_uids = [
                self.download_table.item(r, 0).data(Qt.ItemDataRole.UserRole)
                for r in sorted(selected_row_indices)
                if self.download_table.item(r, 0)
            ]
        else:
            target_uids = [uid]

        # Agrega status de todos os itens alvo
        any_pauseable  = False
        any_resumable  = False
        any_cancelable = False
        any_restartable = False
        any_removable  = False

        for u in target_uids:
            if not u or u not in self.downloads:
                continue
            s = self.downloads[u].status
            if s in (DownloadStatus.DOWNLOADING, DownloadStatus.WAITING):
                any_pauseable = True
            if s in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
                any_resumable = True
            if s not in (DownloadStatus.CANCELLED, DownloadStatus.COMPLETED):
                any_cancelable = True
            if self._is_restartable(self.downloads[u]):
                any_restartable = True
            any_removable = True

        context_menu = QMenu(self)

        # --- Ações de gerenciamento ---
        if any_pauseable or any_resumable:
            if any_pauseable and any_resumable:
                pr_label = "⏸/▶ " + self.t("action_pause") + "/" + self.t("action_resume")
            elif any_pauseable:
                pr_label = "⏸ " + self.t("action_pause")
            else:
                pr_label = "▶ " + self.t("action_resume")
            pause_action = context_menu.addAction(pr_label)
            pause_action.triggered.connect(
                lambda checked=False, us=target_uids: [self.toggle_pause(u) for u in us]
            )

        if any_cancelable:
            cancel_action = context_menu.addAction("✕ " + self.t("action_cancel"))
            cancel_action.triggered.connect(
                lambda checked=False, us=target_uids: [self.cancel_download(u) for u in us]
            )

        if any_restartable:
            restart_action = context_menu.addAction("↻ " + self.t("action_restart"))
            restart_action.triggered.connect(
                lambda checked=False, us=target_uids: [self.restart_download(u) for u in us]
            )

        if any_removable:
            remove_action = context_menu.addAction("🗑 " + self.t("action_remove"))
            remove_action.triggered.connect(
                lambda checked=False, us=target_uids: self._remove_by_uids(us)
            )

        # --- Ações de prioridade (apenas para item único WAITING) ---
        if len(target_uids) == 1:
            single_uid = target_uids[0]
            if single_uid and single_uid in self.downloads:
                if self.downloads[single_uid].status == DownloadStatus.WAITING:
                    context_menu.addSeparator()

                    single_row = self._id_to_row.get(single_uid)

                    move_up_action = context_menu.addAction("⬆ " + self.t("action_move_up"))
                    move_up_action.setEnabled(single_row is not None and single_row > 0)
                    move_up_action.triggered.connect(self.move_priority_up)

                    move_down_action = context_menu.addAction("⬇ " + self.t("action_move_down"))
                    move_down_action.setEnabled(
                        single_row is not None
                        and single_row < self.download_table.rowCount() - 1
                    )
                    move_down_action.triggered.connect(self.move_priority_down)

                    force_action = context_menu.addAction(
                        "⚡ " + self.t("action_force_download")
                    )
                    force_action.triggered.connect(
                        lambda checked=False, u=single_uid: self.force_download_item(u)
                    )

        # --- Ações específicas de coluna ---
        download_item = self.downloads[uid]
        file_path = os.path.join(download_item.dest_folder, download_item.filename)

        has_file_actions = (
            (column == 0 and (os.path.exists(file_path) or os.path.exists(download_item.dest_folder)))
            or (column == COL_MESSAGE and bool(self.download_table.item(row, COL_MESSAGE) and self.download_table.item(row, COL_MESSAGE).text()))
        )

        if not context_menu.isEmpty() and has_file_actions:
            context_menu.addSeparator()

        if column == 0:
            if os.path.exists(file_path):
                open_file_action = context_menu.addAction(self.t("context_open_file"))
                open_file_action.triggered.connect(lambda: self.open_file(file_path))

            if os.path.exists(download_item.dest_folder):
                open_folder_action = context_menu.addAction(self.t("context_open_folder"))
                open_folder_action.triggered.connect(
                    lambda: self.open_folder(download_item.dest_folder)
                )


        elif column == COL_MESSAGE:
            msg_item = self.download_table.item(row, COL_MESSAGE)
            if msg_item and msg_item.text():
                msg_text = msg_item.text()
                copy_action = context_menu.addAction(self.t("context_copy"))
                copy_action.triggered.connect(
                    lambda: self.copy_message_to_clipboard(msg_text)
                )

        if not context_menu.isEmpty():
            context_menu.exec(self.download_table.viewport().mapToGlobal(position))

    def copy_message_to_clipboard(self, text):
        """Copia texto para a área de transferência"""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        log(
            f"[CLIPBOARD] Mensagem copiada: {text[:50]}..."
            if len(text) > 50
            else f"[CLIPBOARD] Mensagem copiada: {text}"
        )

    def open_file(self, file_path):
        """Abre o arquivo com o programa padrão do sistema"""
        try:
            if platform.system() == "Windows":
                os.startfile(file_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", file_path])
            else:  # Linux e outros
                subprocess.run(["xdg-open", file_path])
            log(f"[FILE] Abrindo arquivo: {file_path}")
        except Exception as e:
            log(f"[FILE] Erro ao abrir arquivo: {e}")
            QMessageBox.warning(self, self.t("error"), f"Could not open file: {str(e)}")

    def open_folder(self, folder_path):
        """Abre a pasta no gerenciador de arquivos"""
        try:
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", folder_path])
            else:  # Linux e outros
                subprocess.run(["xdg-open", folder_path])
            log(f"[FOLDER] Abrindo pasta: {folder_path}")
        except Exception as e:
            log(f"[FOLDER] Erro ao abrir pasta: {e}")
            QMessageBox.warning(
                self, self.t("error"), f"Could not open folder: {str(e)}"
            )

    def on_download_table_double_click(self, row, column):
        """Trata duplo clique na tabela de downloads - abre o arquivo"""
        # Só processa se clicar na coluna de arquivo (coluna 0)
        if column == 0:
            filename_item = self.download_table.item(row, 0)
            if filename_item:
                uid = filename_item.data(Qt.ItemDataRole.UserRole)

                if uid and uid in self.downloads:
                    download_item = self.downloads[uid]
                    file_path = os.path.join(
                        download_item.dest_folder, download_item.filename
                    )

                    # Abre o arquivo se ele existir
                    if os.path.exists(file_path):
                        self.open_file(file_path)
                    else:
                        QMessageBox.warning(
                            self, self.t("error"), f"File not found: {file_path}"
                        )

    def show_history(self):
        if not self.recent_identifiers:
            QMessageBox.information(
                self, self.t("history_button"), self.t("history_empty")
            )
            return

        from PyQt6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("history_title"))
        dialog.setGeometry(200, 200, 500, 400)

        layout = QVBoxLayout(dialog)

        label = QLabel(self.t("history_instruction"))
        layout.addWidget(label)

        history_list = QListWidget()
        history_list.addItems(self.recent_identifiers)
        history_list.itemDoubleClicked.connect(
            lambda item: self.load_from_history(item.text(), dialog)
        )
        layout.addWidget(history_list)

        button_layout = QHBoxLayout()

        clear_btn = QPushButton(self.t("history_clear"))
        clear_btn.clicked.connect(lambda: self.clear_history(dialog))

        close_btn = QPushButton(self.t("history_close"))
        close_btn.clicked.connect(dialog.close)

        button_layout.addWidget(clear_btn)
        button_layout.addStretch()
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        dialog.exec()

    def load_from_history(self, identifier, dialog):
        self.id_input.setText(identifier)
        dialog.close()
        self.search_files()

    def clear_history(self, dialog):
        reply = QMessageBox.question(
            self,
            self.t("confirm"),
            self.t("confirm_clear_history"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.recent_identifiers = []
            self.save_recent_identifiers()
            self.update_completer()
            dialog.close()
            QMessageBox.information(
                self, self.t("success"), self.t("success_history_cleared")
            )

    def update_completer(self):
        self.completer.model().setStringList(self.recent_identifiers)

    def update_search_completer(self):
        self.search_completer.model().setStringList(self.recent_searches)

    def show_search_history(self):
        if not self.recent_searches:
            QMessageBox.information(
                self, self.t("search_history_button"), self.t("search_history_empty")
            )
            return

        from PyQt6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("search_history_title"))
        dialog.setGeometry(200, 200, 600, 400)

        layout = QVBoxLayout(dialog)

        label = QLabel(self.t("search_history_instruction"))
        layout.addWidget(label)

        history_list = QListWidget()
        history_list.addItems(self.recent_searches)
        history_list.itemDoubleClicked.connect(
            lambda item: self.load_search_from_history(item.text(), dialog)
        )
        layout.addWidget(history_list)

        button_layout = QHBoxLayout()

        clear_button = QPushButton(self.t("history_clear"))
        clear_button.clicked.connect(lambda: self.clear_search_history(dialog))
        button_layout.addWidget(clear_button)

        close_button = QPushButton(self.t("history_close"))
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)
        dialog.exec()

    def load_search_from_history(self, query, dialog):
        self.search_query_input.setText(query)
        dialog.close()
        self.go_to_page(PAGE_SEARCH)
        self.search_archive()

    def clear_search_history(self, dialog):
        reply = QMessageBox.question(
            self,
            self.t("confirm"),
            self.t("confirm_clear_search_history"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.recent_searches = []
            self.save_recent_searches()
            self.update_search_completer()
            dialog.close()
            QMessageBox.information(
                self, self.t("success"), self.t("success_search_history_cleared")
            )

    def closeEvent(self, event):
        # Fechar apenas esconde a janela quando a bandeja está habilitada
        if self.minimize_to_tray and self.tray and not self._force_quit:
            event.ignore()
            self.hide()
            self.statusBar().showMessage(self.t("tray_tooltip_idle"))
            return

        if self.tray:
            self.tray.hide()

        # Pausa todos os downloads em progresso antes de fechar
        for filename, download_item in list(self.downloads.items()):
            if download_item.thread and download_item.thread.isRunning():
                if download_item.status == DownloadStatus.DOWNLOADING:
                    # Pausa em vez de cancelar para poder retomar depois
                    download_item.thread.pause()
                    download_item.status = DownloadStatus.PAUSED

        # Aguarda um pouco para garantir que pausou
        time.sleep(0.5)

        # Agora pode cancelar as threads
        for filename, download_item in list(self.downloads.items()):
            if download_item.thread and download_item.thread.isRunning():
                download_item.thread.resume()  # Resume para poder cancelar
                download_item.thread.cancel()

        # Aguarda threads terminarem
        max_wait = 2.0
        start_time = time.time()

        while time.time() - start_time < max_wait:
            all_stopped = True
            for download_item in self.downloads.values():
                if download_item.thread and download_item.thread.isRunning():
                    all_stopped = False
                    break

            if all_stopped:
                break

            QApplication.processEvents()
            time.sleep(0.1)

        # Salva downloads antes de fechar
        self.save_downloads()

        if self.download_manager:
            self.download_manager.stop()
            self.download_manager.wait(2000)

        event.accept()
        # quitOnLastWindowClosed está desligado (a janela some para a bandeja),
        # então o encerramento real precisa ser explícito.
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    # Fusion é o único estilo Qt que respeita o QSS de forma consistente nos
    # três sistemas; sem ele o Windows Vista style ignora metade das regras.
    app.setStyle("Fusion")
    app.setApplicationName("Internet Archive Downloader")
    app.setOrganizationName("InternetArchive")
    # Downloads seguem rodando com a janela fechada na bandeja
    app.setQuitOnLastWindowClosed(False)

    gui = InternetArchiveGUI()
    gui.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
