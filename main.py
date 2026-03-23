"""Internet Archive Downloader GUI"""

import sys
import time
import json
import os
import subprocess
import platform
import internetarchive as ia

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLineEdit, QPushButton, QListWidget,
    QLabel, QFileDialog, QProgressBar, QMessageBox,
    QTabWidget, QListWidgetItem, QSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCompleter, QMenu, QCheckBox, QDialog, QComboBox, QInputDialog
)
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import QColor

# Importa os módulos locais
from models import DownloadStatus, DownloadItem
from threads import DownloadManager
from utils import log, set_logging_enabled, format_size
from translations import Translator
from themes import get_current_theme

class InternetArchiveGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.item = None
        self.downloads = {}
        self.download_manager = None
        self.settings = QSettings('InternetArchive', 'Downloader')

        # Carrega configurações salvas
        self.max_concurrent = self.settings.value('max_concurrent', 2, type=int)
        self.segments_per_file = self.settings.value('segments_per_file', 4, type=int)
        self.default_download_folder = self.settings.value('default_download_folder', '')

        # Carrega idioma salvo (padrão: pt-BR)
        self.current_language = self.settings.value('language', 'pt-BR')
        self.translator = Translator(self.current_language)
        self.t = self.translator.get  # Shorthand for translations

        # Carrega configuração de logging e aplica globalmente
        enable_logging = self.settings.value('enable_logging', True, type=bool)
        self.set_logging_enabled(enable_logging)

        self.recent_identifiers = self.load_recent_identifiers()
        self.recent_searches = self.load_recent_searches()
        self.all_files = []

        # Carrega último identifier usado
        self.last_identifier = self.settings.value('last_identifier', '')

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

        # Restaura a aba selecionada (após initUI)
        last_tab = self.settings.value('last_tab_index', 0, type=int)
        self.tabs_widget.setCurrentIndex(last_tab)

        # Conecta o sinal APÓS restaurar a aba (para não sobrescrever durante a inicialização)
        self.tabs_widget.currentChanged.connect(self.on_tab_changed)

        # Auto-busca o último identifier se houver (adiado para após a janela aparecer)
        if self.last_identifier:
            log(f"[STARTUP] Auto-buscando último identifier (adiado): {self.last_identifier}")
            QTimer.singleShot(0, self.search_files)
        
    def load_recent_identifiers(self):
        recent = self.settings.value('recent_identifiers', [])
        if isinstance(recent, str):
            try:
                recent = json.loads(recent)
            except:
                recent = []
        return recent if recent else []
    
    def save_recent_identifiers(self):
        self.settings.setValue('recent_identifiers', json.dumps(self.recent_identifiers))

    def load_recent_searches(self):
        recent = self.settings.value('recent_searches', [])
        if isinstance(recent, str):
            try:
                recent = json.loads(recent)
            except:
                recent = []
        return recent if recent else []

    def save_recent_searches(self):
        self.settings.setValue('recent_searches', json.dumps(self.recent_searches))

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
        json_str = self.settings.value('downloads_json', '')
        
        # Fallback para formato antigo se não encontrar o novo
        if not json_str:
            json_str = self.settings.value('downloads', '')
        
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
        
        for data in downloads_data:
            try:
                download_item = DownloadItem.from_dict(data)
                
                log(f"\n[LOAD] Arquivo: {download_item.filename}")
                log(f"[LOAD] Total bytes do dict: {download_item.total_bytes}")
                # Usa o tamanho salvo em cache (evita chamada de rede bloqueante na inicialização)
                
                # Atualiza downloaded_bytes com o tamanho atual do arquivo
                dest_path = os.path.join(download_item.dest_folder, download_item.filename)
                if os.path.exists(dest_path):
                    download_item.downloaded_bytes = os.path.getsize(dest_path)
                    log(f"[LOAD] Arquivo encontrado no disco: {download_item.downloaded_bytes} bytes ({format_size(download_item.downloaded_bytes)})")
                    if download_item.total_bytes > 0:
                        download_item.progress = int((download_item.downloaded_bytes / download_item.total_bytes) * 100)
                        log(f"[LOAD] Progresso calculado: {download_item.progress}%")
                else:
                    log(f"[LOAD] Arquivo não encontrado no disco: {dest_path}")
                    download_item.downloaded_bytes = 0
                    download_item.progress = 0
                
                log(f"[LOAD] Status: {download_item.status.value}")
                log(f"[LOAD] Final: total={download_item.total_bytes}, downloaded={download_item.downloaded_bytes}, progress={download_item.progress}%")
                
                self.downloads[download_item.filename] = download_item
                self.add_download_to_table(download_item)
                
            except Exception as e:
                log(f"[LOAD] Erro ao carregar download: {e}")
                import traceback
                traceback.print_exc()
    
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
                    download_item.progress = int((download_item.downloaded_bytes / download_item.total_bytes) * 100)

            log(f"[SAVE] {download_item.filename}:")
            log(f"       status={download_item.status.value}")
            log(f"       total_bytes={download_item.total_bytes} ({format_size(download_item.total_bytes)})")
            log(f"       downloaded_bytes={download_item.downloaded_bytes} ({format_size(download_item.downloaded_bytes)})")
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
        self.settings.setValue('downloads_json', json_str)
        log(f"[SAVE] {len(downloads_data)} download(s) salvos\n")
    
    def add_to_recent(self, identifier):
        if identifier in self.recent_identifiers:
            self.recent_identifiers.remove(identifier)
        
        self.recent_identifiers.insert(0, identifier)
        self.recent_identifiers = self.recent_identifiers[:20]
        
        self.save_recent_identifiers()
        self.update_completer()
        
    def initUI(self):
        self.setWindowTitle(self.t('window_title'))
        self.setGeometry(100, 100, 1100, 750)

        # Aplica stylesheet moderno
        self.setStyleSheet(get_current_theme())

        # Adiciona barra de status
        self.statusBar().showMessage(self.t('status_ready'))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tabs_widget = QTabWidget()
        layout.addWidget(self.tabs_widget)

        tab1 = self.create_search_tab()
        self.tabs_widget.addTab(tab1, self.t('tab_search'))

        tab2 = self.create_identifier_tab()
        self.tabs_widget.addTab(tab2, self.t('tab_identifier'))

        tab3 = self.create_download_manager_tab()
        self.tabs_widget.addTab(tab3, self.t('tab_downloads'))

        tab4 = self.create_settings_tab()
        self.tabs_widget.addTab(tab4, self.t('tab_settings'))

    def on_tab_changed(self, index):
        """Salva a aba selecionada quando o usuário muda de aba"""
        self.settings.setValue('last_tab_index', index)
        log(f"[CONFIG] Aba alterada para índice: {index}")

    def create_search_tab(self):
        """Cria a aba de busca no Internet Archive"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Título
        title = QLabel(self.t('search_title'))
        title.setProperty('class', 'section-header')
        layout.addWidget(title)

        # Campo de busca
        search_layout = QHBoxLayout()
        search_layout.setSpacing(12)
        search_label = QLabel(self.t('search_label'))
        self.search_query_input = QLineEdit()
        self.search_query_input.setPlaceholderText(self.t('search_placeholder'))
        self.search_query_input.returnPressed.connect(self.search_archive)

        # Autocomplete para histórico de buscas
        self.search_completer = QCompleter(self.recent_searches)
        self.search_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search_query_input.setCompleter(self.search_completer)

        # Filtro de tipo de mídia
        mediatype_label = QLabel(self.t('search_type_label'))
        self.mediatype_combo = QComboBox()
        self.mediatype_combo.addItems([
            self.t('media_all'),
            self.t('media_audio'),
            self.t('media_video'),
            self.t('media_text'),
            self.t('media_image'),
            self.t('media_software'),
            self.t('media_web'),
            self.t('media_collection'),
            self.t('media_data')
        ])

        self.search_archive_btn = QPushButton(self.t('search_button'))
        self.search_archive_btn.clicked.connect(self.search_archive)

        self.search_history_btn = QPushButton(self.t('search_history_button'))
        self.search_history_btn.setProperty("class", "secondary")
        self.search_history_btn.setStyle(self.search_history_btn.style())
        self.search_history_btn.clicked.connect(self.show_search_history)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_query_input, 2)
        search_layout.addWidget(mediatype_label)
        search_layout.addWidget(self.mediatype_combo, 1)
        search_layout.addWidget(self.search_archive_btn)
        search_layout.addWidget(self.search_history_btn)
        layout.addLayout(search_layout)

        # Dica de sintaxe
        syntax_hint = QLabel(self.t('search_hint'))
        syntax_hint.setProperty('class', 'note')
        syntax_hint.setWordWrap(True)
        layout.addWidget(syntax_hint)

        # Label dos resultados
        self.search_results_label = QLabel('')
        layout.addWidget(self.search_results_label)

        # Controles de paginação
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(12)
        self.prev_page_btn = QPushButton(self.t('search_previous'))
        self.prev_page_btn.setProperty('class', 'secondary')
        self.prev_page_btn.clicked.connect(self.previous_page)
        self.prev_page_btn.setEnabled(False)

        self.page_info_label = QLabel('')
        self.page_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.next_page_btn = QPushButton(self.t('search_next'))
        self.next_page_btn.setProperty('class', 'secondary')
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)

        pagination_layout.addWidget(self.prev_page_btn)
        pagination_layout.addWidget(self.page_info_label)
        pagination_layout.addWidget(self.next_page_btn)
        layout.addLayout(pagination_layout)

        # Tabela de resultados
        results_hint = QLabel(self.t('search_results_hint'))
        results_hint.setProperty('class', 'note')
        layout.addWidget(results_hint)

        self.search_results_table = QTableWidget()
        self.search_results_table.setColumnCount(6)
        self.search_results_table.setHorizontalHeaderLabels([
            self.t('col_title'), self.t('col_identifier'), self.t('col_type'),
            self.t('col_downloads'), self.t('col_matching_files'), self.t('col_description')
        ])

        # Configuração das colunas
        self.search_results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Título
        self.search_results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # Identifier
        self.search_results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Tipo
        self.search_results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Downloads
        self.search_results_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Matching Files
        self.search_results_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # Descrição

        # Larguras iniciais
        self.search_results_table.setColumnWidth(0, 250)  # Título
        self.search_results_table.setColumnWidth(1, 200)  # Identifier

        # Altura das linhas
        self.search_results_table.verticalHeader().setDefaultSectionSize(40)

        self.search_results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.search_results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.search_results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.search_results_table.setSortingEnabled(False)  # Desabilita ordenação nativa (vamos usar nossa própria)

        # Conecta clique no header para ordenação customizada
        self.search_results_table.horizontalHeader().sectionClicked.connect(self.sort_search_results)
        self.search_results_table.itemDoubleClicked.connect(self.load_item_from_search_table)

        # Context menu para resultados de busca
        self.search_results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search_results_table.customContextMenuRequested.connect(self.show_search_results_context_menu)

        layout.addWidget(self.search_results_table)

        return tab

    def search_archive(self):
        """Busca items no Internet Archive"""
        query = self.search_query_input.text().strip()

        if not query:
            QMessageBox.warning(self, self.t('warning'), self.t('warn_search_empty'))
            return

        # Pega o tipo de mídia selecionado
        mediatype_text = self.mediatype_combo.currentText()
        mediatype_map = {
            self.t('media_all'): '',
            self.t('media_audio'): 'audio',
            self.t('media_video'): 'movies',
            self.t('media_text'): 'texts',
            self.t('media_image'): 'image',
            self.t('media_software'): 'software',
            self.t('media_web'): 'web',
            self.t('media_collection'): 'collection',
            self.t('media_data'): 'data'
        }
        mediatype = mediatype_map.get(mediatype_text, '')

        # Monta a query
        if mediatype:
            full_query = f'{query} AND mediatype:{mediatype}'
        else:
            full_query = query

        self.search_results_label.setText(self.t('searching_for', query=query))
        self.search_results_table.setRowCount(0)
        self.search_archive_btn.setEnabled(False)
        self.prev_page_btn.setEnabled(False)
        self.next_page_btn.setEnabled(False)

        try:
            log(f"[SEARCH] Buscando: {full_query}")

            # Busca até 500 resultados (10 páginas)
            results = ia.search_items(
                full_query,
                fields=['identifier', 'title', 'description', 'downloads', 'mediatype'],
                sorts=['downloads desc']
            )

            self.search_results_cache = []
            count = 0
            for result in results:
                # Limita a 500 resultados total
                if count >= 500:
                    break

                identifier = result.get('identifier', 'N/A')
                title = result.get('title', self.t('no_title'))
                description = result.get('description', self.t('no_description'))
                downloads = result.get('downloads', 0)
                mediatype_result = result.get('mediatype', 'N/A')

                # Limita tamanho da descrição
                if isinstance(description, list):
                    description = ' '.join(description)
                if len(description) > 150:
                    description = description[:150] + '...'

                # Armazena no cache
                self.search_results_cache.append({
                    'identifier': identifier,
                    'title': title,
                    'description': description,
                    'downloads': downloads,
                    'mediatype': mediatype_result,
                    'matching_files': None,  # Será carregado sob demanda
                    'matching_files_list': None  # Lista completa de arquivos correspondentes
                })

                count += 1

            # Armazena os termos de busca para filtragem de arquivos
            if count > 0:
                self.current_search_query = query

            if count == 0:
                self.search_results_label.setText(self.t('no_results'))
                self.page_info_label.setText('')
                QMessageBox.information(self, self.t('no_results_title'),
                                      self.t('no_results_found', query=query))
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
            QMessageBox.critical(self, self.t('error'), self.t('error_search', error=str(e)))
            self.search_results_label.setText(self.t('search_error'))
            self.page_info_label.setText('')

        finally:
            self.search_archive_btn.setEnabled(True)

    def sort_search_results(self, column):
        """Ordena os resultados de busca por coluna (considerando TODAS as páginas)"""
        if not self.search_results_cache:
            return

        # Se clicar na mesma coluna, inverte a ordem
        if self.current_sort_column == column:
            self.current_sort_order = Qt.SortOrder.DescendingOrder if self.current_sort_order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        else:
            self.current_sort_column = column
            self.current_sort_order = Qt.SortOrder.AscendingOrder

        # Mapeia coluna para chave no dicionário
        column_keys = {
            0: 'title',
            1: 'identifier',
            2: 'mediatype',
            3: 'downloads',
            4: 'matching_files',
            5: 'description'
        }

        sort_key = column_keys.get(column)
        if not sort_key:
            return

        # Ordena o cache completo
        reverse = (self.current_sort_order == Qt.SortOrder.DescendingOrder)

        if sort_key in ['downloads', 'matching_files']:
            # Para downloads e matching_files, ordena numericamente
            self.search_results_cache.sort(key=lambda x: x.get(sort_key, 0) or 0, reverse=reverse)
        else:
            # Para texto, ordena alfabeticamente (case insensitive)
            self.search_results_cache.sort(key=lambda x: str(x[sort_key]).lower(), reverse=reverse)

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
        dialog.setWindowTitle(self.t('matching_files_title'))
        dialog.setGeometry(150, 150, 900, 600)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Cabeçalho com título e identifier
        header_label = QLabel(f"<b>{title}</b><br><i>{identifier}</i>")
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        if not matching_files or len(matching_files) == 0:
            no_files_label = QLabel(self.t('no_matching_files'))
            no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_files_label)
        else:
            # Instrução
            instruction_label = QLabel(self.t('matching_files_instruction', count=len(matching_files)))
            instruction_label.setProperty('class', 'note')
            layout.addWidget(instruction_label)

            # Tabela de arquivos
            files_table = QTableWidget()
            files_table.setColumnCount(4)
            files_table.setHorizontalHeaderLabels([
                self.t('col_filename'), self.t('col_size'),
                self.t('col_format'), self.t('col_action')
            ])

            files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            files_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

            files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

            for file_info in matching_files:
                row = files_table.rowCount()
                files_table.insertRow(row)

                # Nome do arquivo
                name_item = QTableWidgetItem(file_info['name'])
                files_table.setItem(row, 0, name_item)

                # Tamanho
                size_item = QTableWidgetItem(format_size(file_info['size']))
                files_table.setItem(row, 1, size_item)

                # Formato
                format_item = QTableWidgetItem(file_info['format'])
                files_table.setItem(row, 2, format_item)

                # Botão de ação (adicionar à fila)
                add_btn = QPushButton(self.t('add_to_queue'))
                add_btn.setProperty('class', 'success')
                add_btn.clicked.connect(
                    lambda _checked, id=identifier, fn=file_info['name'], sz=file_info['size']:
                    self.add_file_to_queue_from_dialog(id, fn, sz)
                )
                files_table.setCellWidget(row, 3, add_btn)

            layout.addWidget(files_table)

        # Botões inferiores
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        view_all_btn = QPushButton(self.t('view_all_files'))
        view_all_btn.clicked.connect(lambda: self.view_all_files_from_dialog(identifier, dialog))
        button_layout.addWidget(view_all_btn)

        close_btn = QPushButton(self.t('close'))
        close_btn.setProperty('class', 'secondary')
        close_btn.clicked.connect(dialog.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        dialog.exec()

    def add_file_to_queue_from_dialog(self, identifier, filename, file_size):
        """Adiciona arquivo à fila de downloads a partir do dialog"""
        if not self.default_download_folder:
            QMessageBox.warning(self, self.t('info_no_default_folder_title'),
                              self.t('warn_no_default_folder'))
            return

        if filename in self.downloads:
            QMessageBox.information(self, self.t('info_already_queued'),
                                  self.t('warn_already_queued', filename=filename))
            return

        download_item = DownloadItem(identifier, filename, self.default_download_folder, segments=self.segments_per_file)
        download_item.total_bytes = file_size
        self.downloads[filename] = download_item
        self.add_download_to_table(download_item)
        self.download_manager.add_download(download_item)

        log(f"[DIALOG-ADD] Arquivo adicionado: {filename} -> {self.default_download_folder}")
        self.statusBar().showMessage(self.t('info_added_to_queue', filename=filename), 3000)

    def view_all_files_from_dialog(self, identifier, dialog):
        """Fecha o dialog e abre a aba de identifier com todos os arquivos"""
        dialog.close()

        # Define o identifier no campo da aba "Buscar por Identifier"
        self.id_input.setText(identifier)

        # Muda para a aba de identifier e busca os arquivos
        self.tabs_widget.setCurrentIndex(1)  # Aba "Buscar por Identifier"

        # Busca os arquivos
        self.search_files()

        log(f"[DIALOG] Visualizando todos os arquivos de: {identifier}")

    def update_search_page_display(self):
        """Atualiza a exibição da página atual de resultados"""
        self.search_results_table.setRowCount(0)

        total_results = len(self.search_results_cache)
        total_pages = (total_results + self.results_per_page - 1) // self.results_per_page

        start_idx = self.current_search_page * self.results_per_page
        end_idx = min(start_idx + self.results_per_page, total_results)

        # Exibe os resultados da página atual
        for i in range(start_idx, end_idx):
            result = self.search_results_cache[i]
            row = self.search_results_table.rowCount()
            self.search_results_table.insertRow(row)

            # Título
            title_item = QTableWidgetItem(result['title'])
            title_item.setData(Qt.ItemDataRole.UserRole, result['identifier'])  # Armazena identifier
            self.search_results_table.setItem(row, 0, title_item)

            # Identifier
            id_item = QTableWidgetItem(result['identifier'])
            self.search_results_table.setItem(row, 1, id_item)

            # Tipo
            type_item = QTableWidgetItem(result['mediatype'])
            self.search_results_table.setItem(row, 2, type_item)

            # Downloads (armazena valor numérico para ordenação correta)
            downloads_item = QTableWidgetItem(f"{result['downloads']:,}")
            downloads_item.setData(Qt.ItemDataRole.UserRole, result['downloads'])
            self.search_results_table.setItem(row, 3, downloads_item)

            # Matching Files (mostrado apenas quando carregado via context menu)
            files_display = '-'
            if result['matching_files'] is not None:
                files_display = str(result['matching_files']) if result['matching_files'] > 0 else '0'

            files_item = QTableWidgetItem(files_display)
            files_item.setData(Qt.ItemDataRole.UserRole, result.get('matching_files', 0))
            self.search_results_table.setItem(row, 4, files_item)

            # Descrição
            desc_item = QTableWidgetItem(result['description'])
            self.search_results_table.setItem(row, 5, desc_item)

        # Atualiza label de informação
        self.search_results_label.setText(self.t('results_found', count=total_results))
        self.page_info_label.setText(self.t('page_info',
                                            current=self.current_search_page + 1,
                                            total=total_pages,
                                            start=start_idx + 1,
                                            end=end_idx,
                                            count=total_results))

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
        total_pages = (len(self.search_results_cache) + self.results_per_page - 1) // self.results_per_page
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
        self.tabs_widget.setCurrentIndex(1)  # Aba "Buscar por Identifier"

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
            if r['identifier'] == identifier:
                result = r
                break

        if not result:
            return

        # Cria o menu
        context_menu = QMenu(self)

        # Ação de mostrar arquivos correspondentes
        show_files_action = context_menu.addAction(self.t('context_show_matching_files'))
        show_files_action.triggered.connect(lambda: self.load_matching_files_async(result))

        # Mostra o menu na posição do cursor
        context_menu.exec(self.search_results_table.viewport().mapToGlobal(position))

    def load_matching_files_async(self, result):
        """Carrega arquivos correspondentes em background thread"""
        identifier = result['identifier']
        title = result['title']

        # Se já carregou, mostra direto
        if result['matching_files_list'] is not None:
            self.show_matching_files_dialog(identifier, title, result['matching_files_list'])
            return

        # Mostra mensagem de carregamento
        QMessageBox.information(self, self.t('info'), self.t('loading_matching_files'))

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
                        filename = file.get('name', '').lower()

                        # Verifica se algum termo de busca está no nome do arquivo
                        if any(term in filename for term in query_terms):
                            matching_files.append({
                                'name': file.get('name', ''),
                                'size': int(file.get('size', 0)),
                                'format': file.get('format', 'N/A')
                            })

                    self.finished.emit(len(matching_files), matching_files)

                except Exception as e:
                    self.error.emit(str(e))

        # Cria e inicia a thread
        thread = MatchingFilesThread(identifier, self.current_search_query)

        def on_finished(count, files):
            result['matching_files'] = count
            result['matching_files_list'] = files

            # Atualiza a tabela
            self.update_search_page_display()

            # Mostra o dialog
            self.show_matching_files_dialog(identifier, title, files)

        def on_error(error_msg):
            QMessageBox.critical(self, self.t('error'),
                               self.t('error_loading_files', error=error_msg))

        thread.finished.connect(on_finished)
        thread.error.connect(on_error)
        thread.start()

        # Armazena referência para evitar garbage collection
        self._matching_files_thread = thread

    def create_identifier_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        id_layout = QHBoxLayout()
        id_layout.setSpacing(12)
        id_label = QLabel(self.t('identifier_label'))
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText(self.t('identifier_placeholder'))
        self.id_input.returnPressed.connect(self.search_files)

        self.completer = QCompleter(self.recent_identifiers)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.id_input.setCompleter(self.completer)

        self.search_btn = QPushButton(self.t('search_files_button'))
        self.search_btn.clicked.connect(self.search_files)

        self.history_btn = QPushButton(self.t('history_button'))
        self.history_btn.setProperty('class', 'secondary')
        self.history_btn.setToolTip(self.t('history_tooltip'))
        self.history_btn.clicked.connect(self.show_history)

        id_layout.addWidget(id_label)
        id_layout.addWidget(self.id_input)
        id_layout.addWidget(self.history_btn)
        id_layout.addWidget(self.search_btn)
        layout.addLayout(id_layout)

        # Preenche com o último identifier usado
        if self.last_identifier:
            self.id_input.setText(self.last_identifier)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        filter_label = QLabel(self.t('filter_label'))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(self.t('filter_placeholder'))
        self.filter_input.textChanged.connect(self.filter_files)
        self.clear_filter_btn = QPushButton('✕')
        self.clear_filter_btn.setProperty('class', 'secondary')
        self.clear_filter_btn.setMaximumWidth(35)
        self.clear_filter_btn.setToolTip(self.t('clear_filter_tooltip'))
        self.clear_filter_btn.clicked.connect(lambda: self.filter_input.clear())

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_input)
        filter_layout.addWidget(self.clear_filter_btn)
        layout.addLayout(filter_layout)

        list_label = QLabel(self.t('files_label'))
        layout.addWidget(list_label)

        hint_label = QLabel(self.t('double_click_hint'))
        hint_label.setProperty('class', 'note')
        layout.addWidget(hint_label)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.file_list.itemDoubleClicked.connect(self.add_file_on_double_click)
        layout.addWidget(self.file_list)

        download_layout = QHBoxLayout()
        self.download_btn = QPushButton(self.t('add_to_queue_button'))
        self.download_btn.clicked.connect(self.add_to_queue)
        self.download_btn.setEnabled(False)
        download_layout.addStretch()
        download_layout.addWidget(self.download_btn)
        layout.addLayout(download_layout)

        self.status_label = QLabel('')
        layout.addWidget(self.status_label)

        return tab

    def create_download_manager_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Toolbar with action buttons
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)

        self.pause_resume_btn = QPushButton("⏸ " + self.t('action_pause'))
        self.pause_resume_btn.setProperty('class', 'secondary')
        self.pause_resume_btn.clicked.connect(self.toolbar_pause_resume)
        self.pause_resume_btn.setEnabled(False)

        self.cancel_btn = QPushButton("✕ " + self.t('action_cancel'))
        self.cancel_btn.setProperty('class', 'danger')
        self.cancel_btn.clicked.connect(self.toolbar_cancel)
        self.cancel_btn.setEnabled(False)

        self.restart_btn = QPushButton("↻ " + self.t('action_restart'))
        self.restart_btn.setProperty('class', 'success')
        self.restart_btn.clicked.connect(self.toolbar_restart)
        self.restart_btn.setEnabled(False)

        self.remove_btn = QPushButton("🗑 " + self.t('action_remove'))
        self.remove_btn.setProperty('class', 'secondary')
        self.remove_btn.clicked.connect(self.toolbar_remove)
        self.remove_btn.setEnabled(False)

        toolbar_layout.addWidget(self.pause_resume_btn)
        toolbar_layout.addWidget(self.cancel_btn)
        toolbar_layout.addWidget(self.restart_btn)
        toolbar_layout.addWidget(self.remove_btn)
        toolbar_layout.addStretch()

        self.add_url_btn = QPushButton("🔗 " + self.t('add_url_button'))
        self.add_url_btn.clicked.connect(self.show_add_url_dialog)

        self.clear_completed_btn = QPushButton(self.t('dm_clear_completed'))
        self.clear_completed_btn.setProperty('class', 'secondary')
        self.clear_completed_btn.clicked.connect(self.clear_completed)

        self.cancel_all_btn = QPushButton(self.t('dm_cancel_all'))
        self.cancel_all_btn.setProperty("class", "danger")
        self.cancel_all_btn.clicked.connect(self.cancel_all)

        toolbar_layout.addWidget(self.add_url_btn)
        toolbar_layout.addWidget(self.clear_completed_btn)
        toolbar_layout.addWidget(self.cancel_all_btn)

        layout.addLayout(toolbar_layout)

        # Download table
        self.download_table = QTableWidget()
        self.download_table.setColumnCount(7)
        self.download_table.setHorizontalHeaderLabels([
            self.t('dm_col_file'), self.t('dm_col_status'), self.t('dm_col_progress'),
            self.t('dm_col_size'), self.t('dm_col_speed'), self.t('dm_col_connections'),
            self.t('dm_col_message')
        ])
        # Aumenta altura das linhas para melhor visibilidade
        self.download_table.verticalHeader().setDefaultSectionSize(35)
        # Esconde o header vertical (números de linha) que aparecia como caixas pretas
        self.download_table.verticalHeader().setVisible(False)

        self.download_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.download_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.download_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.download_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.download_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.download_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Conexões
        self.download_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)  # Mensagem
        self.download_table.setColumnWidth(2, 200)
        self.download_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.download_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.download_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.download_table.customContextMenuRequested.connect(self.show_context_menu)
        self.download_table.cellDoubleClicked.connect(self.on_download_table_double_click)
        self.download_table.itemSelectionChanged.connect(self.update_toolbar_buttons)

        layout.addWidget(self.download_table)

        return tab

    def update_toolbar_buttons(self):
        """Atualiza estado dos botões da toolbar baseado na seleção"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0

        if not has_selection:
            self.pause_resume_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.restart_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            return

        # Pega o primeiro item selecionado para determinar estado dos botões
        row = selected_rows[0].row()
        filename = self.download_table.item(row, 0).text()

        if filename in self.downloads:
            download_item = self.downloads[filename]
            status = download_item.status

            # Botão Pause/Resume
            if status in [DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED, DownloadStatus.WAITING]:
                self.pause_resume_btn.setEnabled(True)
                if status == DownloadStatus.PAUSED:
                    self.pause_resume_btn.setText("▶ " + self.t('action_resume'))
                else:
                    self.pause_resume_btn.setText("⏸ " + self.t('action_pause'))
            else:
                self.pause_resume_btn.setEnabled(False)

            # Botão Cancel
            self.cancel_btn.setEnabled(status not in [DownloadStatus.CANCELLED, DownloadStatus.COMPLETED])

            # Botão Restart
            self.restart_btn.setEnabled(status == DownloadStatus.CANCELLED)

            # Botão Remove - sempre habilitado quando há seleção
            self.remove_btn.setEnabled(True)

    def toolbar_pause_resume(self):
        """Pausa ou resume o download selecionado"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        filename = self.download_table.item(row, 0).text()
        self.toggle_pause(filename)

    def toolbar_cancel(self):
        """Cancela o download selecionado"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        filename = self.download_table.item(row, 0).text()
        self.cancel_download(filename)

    def toolbar_restart(self):
        """Reinicia o download selecionado"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        filename = self.download_table.item(row, 0).text()
        self.restart_download(filename)

    def toolbar_remove(self):
        """Remove o download selecionado da lista"""
        selected_rows = self.download_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        filename = self.download_table.item(row, 0).text()

        if filename in self.downloads:
            download_item = self.downloads[filename]

            # Só permite remover se estiver concluído, cancelado ou com erro
            if download_item.status in [DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.ERROR]:
                del self.downloads[filename]
                self.download_table.removeRow(row)
                self.save_downloads()
            else:
                QMessageBox.warning(self, self.t('warning'),
                                  self.t('warn_remove_active'))

    def create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Título
        title = QLabel(self.t('settings_title'))
        title.setProperty('class', 'section-header')
        layout.addWidget(title)

        layout.addSpacing(10)

        # Seção: Conta do Internet Archive
        account_group_label = QLabel(self.t('account_section'))
        account_group_label.setProperty('class', 'subsection-header')
        layout.addWidget(account_group_label)

        account_desc = QLabel(self.t('account_description'))
        layout.addWidget(account_desc)

        # Status da conta
        self.account_status_label = QLabel()
        self.update_account_status()
        layout.addWidget(self.account_status_label)

        # Email
        email_layout = QHBoxLayout()
        email_layout.setSpacing(12)
        email_label = QLabel(self.t('account_email'))
        email_label.setMinimumWidth(80)
        self.ia_email_input = QLineEdit()
        self.ia_email_input.setPlaceholderText(self.t('account_email_placeholder'))
        email_layout.addWidget(email_label)
        email_layout.addWidget(self.ia_email_input)
        layout.addLayout(email_layout)

        # Senha
        password_layout = QHBoxLayout()
        password_layout.setSpacing(12)
        password_label = QLabel(self.t('account_password'))
        password_label.setMinimumWidth(80)
        self.ia_password_input = QLineEdit()
        self.ia_password_input.setPlaceholderText(self.t('account_password_placeholder'))
        self.ia_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.ia_password_input)
        layout.addLayout(password_layout)

        # Botões de ação
        account_buttons_layout = QHBoxLayout()
        account_buttons_layout.setSpacing(12)
        self.ia_login_btn = QPushButton(self.t('account_login'))
        self.ia_login_btn.clicked.connect(self.ia_login)

        self.ia_logout_btn = QPushButton(self.t('account_logout'))
        self.ia_logout_btn.setProperty('class', 'secondary')
        self.ia_logout_btn.clicked.connect(self.ia_logout)

        account_buttons_layout.addWidget(self.ia_login_btn)
        account_buttons_layout.addWidget(self.ia_logout_btn)
        account_buttons_layout.addStretch()
        layout.addLayout(account_buttons_layout)

        account_note = QLabel(self.t('account_note'))
        account_note.setProperty('class', 'note')
        account_note.setWordWrap(True)
        layout.addWidget(account_note)

        layout.addSpacing(20)

        # Seção: Pasta Padrão
        folder_group_label = QLabel(self.t('folder_section'))
        folder_group_label.setProperty('class', 'subsection-header')
        layout.addWidget(folder_group_label)

        folder_layout = QHBoxLayout()
        folder_desc = QLabel(self.t('folder_description'))
        folder_layout.addWidget(folder_desc)
        layout.addLayout(folder_layout)

        folder_control_layout = QHBoxLayout()
        folder_control_layout.setSpacing(12)
        self.default_folder_input = QLineEdit()
        self.default_folder_input.setPlaceholderText(self.t('folder_placeholder'))
        self.default_folder_input.setText(self.default_download_folder)
        self.default_folder_input.setReadOnly(True)

        self.choose_folder_btn = QPushButton(self.t('folder_choose'))
        self.choose_folder_btn.clicked.connect(self.choose_default_folder)

        self.clear_folder_btn = QPushButton(self.t('folder_clear'))
        self.clear_folder_btn.setProperty('class', 'secondary')
        self.clear_folder_btn.clicked.connect(self.clear_default_folder)

        folder_control_layout.addWidget(self.default_folder_input)
        folder_control_layout.addWidget(self.choose_folder_btn)
        folder_control_layout.addWidget(self.clear_folder_btn)
        layout.addLayout(folder_control_layout)

        layout.addSpacing(20)

        # Seção: Performance
        perf_group_label = QLabel(self.t('perf_section'))
        perf_group_label.setProperty('class', 'subsection-header')
        layout.addWidget(perf_group_label)

        concurrent_layout = QHBoxLayout()
        concurrent_layout.setSpacing(12)
        concurrent_label = QLabel(self.t('perf_concurrent'))
        concurrent_label.setToolTip(self.t('perf_concurrent_tooltip'))
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setMinimum(1)
        self.concurrent_spin.setMaximum(10)
        self.concurrent_spin.setValue(self.max_concurrent)
        self.concurrent_spin.valueChanged.connect(self.update_concurrent_limit)
        concurrent_layout.addWidget(concurrent_label)
        concurrent_layout.addWidget(self.concurrent_spin)
        concurrent_layout.addStretch()
        layout.addLayout(concurrent_layout)

        segments_layout = QHBoxLayout()
        segments_layout.setSpacing(12)
        segments_label = QLabel(self.t('perf_connections'))
        segments_label.setToolTip(self.t('perf_connections_tooltip'))
        self.segments_spin = QSpinBox()
        self.segments_spin.setMinimum(1)
        self.segments_spin.setMaximum(16)
        self.segments_spin.setValue(self.segments_per_file)
        self.segments_spin.setToolTip(self.t('perf_connections_note_tooltip'))
        self.segments_spin.valueChanged.connect(self.update_segments_per_file)
        segments_layout.addWidget(segments_label)
        segments_layout.addWidget(self.segments_spin)
        segments_layout.addStretch()
        layout.addLayout(segments_layout)

        layout.addSpacing(10)

        perf_note = QLabel(self.t('perf_note'))
        perf_note.setProperty('class', 'note')
        perf_note.setWordWrap(True)
        layout.addWidget(perf_note)

        layout.addSpacing(20)

        # Seção: Debug e Logs
        debug_group_label = QLabel(self.t('debug_section'))
        debug_group_label.setProperty('class', 'subsection-header')
        layout.addWidget(debug_group_label)

        self.enable_logging_checkbox = QCheckBox(self.t('debug_logging'))
        self.enable_logging_checkbox.setChecked(self.settings.value('enable_logging', True, type=bool))
        self.enable_logging_checkbox.stateChanged.connect(self.toggle_logging)
        layout.addWidget(self.enable_logging_checkbox)

        logging_note = QLabel(self.t('debug_note'))
        logging_note.setProperty('class', 'note')
        logging_note.setWordWrap(True)
        layout.addWidget(logging_note)

        layout.addSpacing(20)

        # Seção: Idioma / Language
        language_group_label = QLabel('🌐 Idioma / Language')
        language_group_label.setProperty('class', 'subsection-header')
        layout.addWidget(language_group_label)

        language_layout = QHBoxLayout()
        language_layout.setSpacing(12)
        language_label = QLabel('Idioma da interface / Interface language:')
        self.language_combo = QComboBox()
        self.language_combo.addItem('Português (Brasil)', 'pt-BR')
        self.language_combo.addItem('English (US)', 'en')

        # Set current language
        current_index = 0 if self.current_language == 'pt-BR' else 1
        self.language_combo.setCurrentIndex(current_index)

        self.language_combo.currentIndexChanged.connect(self.change_language)

        language_layout.addWidget(language_label)
        language_layout.addWidget(self.language_combo)
        language_layout.addStretch()
        layout.addLayout(language_layout)

        language_note = QLabel('💡 Nota: O aplicativo será reiniciado para aplicar o novo idioma\n💡 Note: The application will restart to apply the new language')
        language_note.setProperty('class', 'note')
        language_note.setWordWrap(True)
        layout.addWidget(language_note)

        layout.addStretch()

        return tab

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
            log(f"[ACCOUNT] access_key={session.access_key}, secret_key={'***' if session.secret_key else None}")

            if has_cookies or has_s3_keys:
                # Tenta identificar o email se possível
                email = getattr(session, 'user_email', None) or 'configurada'
                self.account_status_label.setText(self.t('account_configured'))
                self.account_status_label.setProperty('class', 'success')
                log(f"[ACCOUNT] Conta detectada: {email}")
                return

            # Se não encontrou credenciais, verifica arquivos de configuração manualmente
            config_paths = [
                os.path.expanduser('~/.config/ia.ini'),
                os.path.expanduser('~/.ia'),
                os.path.join(os.environ.get('APPDATA', ''), 'ia.ini') if os.name == 'nt' else None,
            ]

            for config_file in config_paths:
                if config_file and os.path.exists(config_file):
                    log(f"[ACCOUNT] Verificando arquivo: {config_file}")
                    with open(config_file, 'r') as f:
                        content = f.read()
                        if 'cookies' in content or 'access' in content or 'secret' in content:
                            self.account_status_label.setText(self.t('account_configured_file'))
                            self.account_status_label.setProperty('class', 'success')
                            log(f"[ACCOUNT] Credenciais encontradas em: {config_file}")
                            return

            self.account_status_label.setText(self.t('account_not_configured'))
            self.account_status_label.setProperty('class', 'muted')
            log("[ACCOUNT] Nenhuma credencial encontrada")

        except Exception as e:
            log(f"[ACCOUNT] Erro ao verificar status: {e}")
            import traceback
            traceback.print_exc()
            self.account_status_label.setText(self.t('account_unknown'))
            self.account_status_label.setProperty('class', 'muted')

    def ia_login(self):
        """Faz login na conta do Internet Archive"""
        email = self.ia_email_input.text().strip()
        password = self.ia_password_input.text().strip()

        if not email or not password:
            QMessageBox.warning(self, self.t('warning'), self.t('warn_account_fill'))
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
                QMessageBox.information(self, self.t('success'),
                                      self.t('success_login'))
                log(f"[ACCOUNT] Login bem-sucedido para: {email}")
            else:
                QMessageBox.warning(self, self.t('error'), 'Falha ao fazer login. Verifique suas credenciais.')

        except Exception as e:
            log(f"[ACCOUNT] Erro ao fazer login: {e}")
            QMessageBox.critical(self, self.t('error'),
                               self.t('error_login', error=str(e)))

    def ia_logout(self):
        """Remove credenciais do Internet Archive"""
        reply = QMessageBox.question(self, self.t('confirm'),
                                     self.t('confirm_logout'),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            try:
                config_file = os.path.expanduser('~/.config/ia.ini')
                config_file_alt = os.path.expanduser('~/.ia')  # Arquivo alternativo

                removed = False

                if os.path.exists(config_file):
                    os.remove(config_file)
                    log(f"[ACCOUNT] Arquivo de configuração removido: {config_file}")
                    removed = True

                if os.path.exists(config_file_alt):
                    os.remove(config_file_alt)
                    log(f"[ACCOUNT] Arquivo de configuração alternativo removido: {config_file_alt}")
                    removed = True

                self.update_account_status()
                self.ia_email_input.clear()
                self.ia_password_input.clear()

                if removed:
                    QMessageBox.information(self, self.t('success'), self.t('success_logout'))
                else:
                    QMessageBox.information(self, self.t('info'), self.t('success_logout_none'))

            except Exception as e:
                log(f"[ACCOUNT] Erro ao remover credenciais: {e}")
                QMessageBox.critical(self, self.t('error'), self.t('error_logout', error=str(e)))

    def choose_default_folder(self):
        """Abre diálogo para escolher pasta padrão"""
        folder = QFileDialog.getExistingDirectory(self, self.t('folder_dialog_title'), self.default_download_folder)

        if folder:
            self.default_download_folder = folder
            self.default_folder_input.setText(folder)
            self.settings.setValue('default_download_folder', folder)
            log(f"[CONFIG] Pasta padrão definida: {folder}")

    def clear_default_folder(self):
        """Limpa a pasta padrão"""
        self.default_download_folder = ''
        self.default_folder_input.setText('')
        self.settings.setValue('default_download_folder', '')
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
        self.settings.setValue('enable_logging', enabled)

        # Confirma a mudança (só aparece se logs estiverem habilitados)
        log(f"[CONFIG] Logs agora estão {'habilitados' if enabled else 'desabilitados'}")

    def set_logging_enabled(self, enabled):
        """Define se os logs devem ser exibidos"""
        set_logging_enabled(enabled)

    def add_file_on_double_click(self, item):
        """Adiciona arquivo à fila ao dar duplo clique (usa pasta padrão)"""
        if not self.default_download_folder:
            QMessageBox.warning(self, self.t('info_no_default_folder_title'),
                              self.t('warn_no_default_folder'))
            return

        filename = item.data(Qt.ItemDataRole.UserRole)

        if filename in self.downloads:
            QMessageBox.information(self, self.t('info_already_queued'),
                                  self.t('warn_already_queued', filename=filename))
            return

        identifier = self.id_input.text().strip()

        # Busca o tamanho do arquivo na lista
        file_size = 0
        for f in self.all_files:
            if f['name'] == filename:
                file_size = int(f.get('size', 0))
                break

        download_item = DownloadItem(identifier, filename, self.default_download_folder, segments=self.segments_per_file)
        download_item.total_bytes = file_size
        self.downloads[filename] = download_item
        self.add_download_to_table(download_item)
        self.download_manager.add_download(download_item)

        log(f"[QUICK-ADD] Arquivo adicionado via duplo clique: {filename} -> {self.default_download_folder}")

        # Feedback visual rápido
        self.statusBar().showMessage(self.t('info_added_to_queue', filename=filename), 3000)

    def start_download_manager(self):
        self.download_manager = DownloadManager(self.max_concurrent)
        self.download_manager.download_started.connect(self.on_download_started)
        self.download_manager.start()
    
    def search_files(self):
        identifier = self.id_input.text().strip()

        if not identifier:
            QMessageBox.warning(self, self.t('warning'), self.t('warn_identifier_empty'))
            return

        self.status_label.setText(self.t('searching_item', identifier=identifier))
        self.file_list.clear()
        self.search_btn.setEnabled(False)

        try:
            self.item = ia.get_item(identifier)

            if not self.item.exists:
                QMessageBox.warning(self, self.t('error'), self.t('item_not_found', identifier=identifier))
                self.status_label.setText('')
                self.search_btn.setEnabled(True)
                return

            files = list(self.item.files)

            if not files:
                QMessageBox.information(self, self.t('info'), self.t('no_files_found'))
                self.status_label.setText('')
                self.search_btn.setEnabled(True)
                return

            self.all_files = files

            for file in files:
                item_widget = QListWidgetItem(f"{file['name']} ({format_size(file.get('size', 0))})")
                item_widget.setData(Qt.ItemDataRole.UserRole, file['name'])
                self.file_list.addItem(item_widget)

            self.status_label.setText(self.t('files_found', count=len(files)))
            self.download_btn.setEnabled(True)

            self.add_to_recent(identifier)

            # Salva como último identifier usado
            self.last_identifier = identifier
            self.settings.setValue('last_identifier', identifier)
            log(f"[CONFIG] Último identifier salvo: {identifier}")

        except Exception as e:
            QMessageBox.critical(self, self.t('error'), self.t('error_load_files', error=str(e)))
            self.status_label.setText('')

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
            QMessageBox.warning(self, self.t('warning'), self.t('warn_no_files_selected'))
            return

        dest_folder = QFileDialog.getExistingDirectory(self, self.t('folder_dialog_title'))

        if not dest_folder:
            return

        identifier = self.id_input.text().strip()

        for item in selected_items:
            filename = item.data(Qt.ItemDataRole.UserRole)

            if filename in self.downloads:
                QMessageBox.warning(self, self.t('warning'),
                                  self.t('warn_file_already_queued', filename=filename))
                continue

            # Busca o tamanho do arquivo na lista
            file_size = 0
            for f in self.all_files:
                if f['name'] == filename:
                    file_size = int(f.get('size', 0))
                    break

            download_item = DownloadItem(identifier, filename, dest_folder, segments=self.segments_per_file)
            download_item.total_bytes = file_size  # Define o tamanho total
            self.downloads[filename] = download_item
            self.add_download_to_table(download_item)
            self.download_manager.add_download(download_item)

        QMessageBox.information(self, self.t('success'),
                              self.t('info_files_added', count=len(selected_items)))
    
    def show_add_url_dialog(self):
        """Mostra dialog para adicionar URL"""
        url, ok = QInputDialog.getText(
            self,
            self.t('add_url_title'),
            self.t('add_url_prompt'),
            QLineEdit.EchoMode.Normal,
            ""
        )

        if ok and url:
            self.add_url_to_queue(url.strip())

    def add_url_to_queue(self, url):
        """Adiciona URL à fila de downloads"""
        if not url:
            QMessageBox.warning(self, self.t('warning'), self.t('warn_url_empty'))
            return

        dest_folder = QFileDialog.getExistingDirectory(self, self.t('folder_dialog_title'))

        if not dest_folder:
            return

        filename = url.split('/')[-1]

        if filename in self.downloads:
            QMessageBox.warning(self, self.t('warning'),
                              self.t('warn_already_queued', filename=filename))
            return

        download_item = DownloadItem("", filename, dest_folder, url=url, segments=self.segments_per_file)
        self.downloads[filename] = download_item
        self.add_download_to_table(download_item)
        self.download_manager.add_download(download_item)

        QMessageBox.information(self, self.t('success'), self.t('info_file_added'))
    
    def add_download_to_table(self, download_item):
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)

        # Coluna de arquivo com tooltip mostrando datas
        filename_item = QTableWidgetItem(download_item.filename)

        # Cria tooltip com informações de data
        tooltip_parts = [
            f"{self.t('tooltip_id')}: {download_item.unique_id[:8]}...",
            f"{self.t('tooltip_added')}: {download_item.date_added.strftime('%Y-%m-%d %H:%M:%S')}"
        ]
        if download_item.date_completed:
            tooltip_parts.append(f"{self.t('tooltip_completed')}: {download_item.date_completed.strftime('%Y-%m-%d %H:%M:%S')}")

        filename_item.setToolTip('\n'.join(tooltip_parts))
        self.download_table.setItem(row, 0, filename_item)
        
        status_item = QTableWidgetItem(download_item.status.value)
        self.download_table.setItem(row, 1, status_item)

        # Aplica cores baseado no status com melhor contraste
        if download_item.status == DownloadStatus.COMPLETED:
            status_item.setBackground(QColor(200, 255, 200))  # Verde claro
            status_item.setForeground(QColor(0, 100, 0))  # Verde escuro
        elif download_item.status == DownloadStatus.ERROR:
            status_item.setBackground(QColor(255, 200, 200))  # Vermelho claro
            status_item.setForeground(QColor(139, 0, 0))  # Vermelho escuro
        elif download_item.status == DownloadStatus.CANCELLED:
            status_item.setBackground(QColor(220, 220, 220))  # Cinza claro
            status_item.setForeground(QColor(60, 60, 60))  # Cinza escuro
        elif download_item.status == DownloadStatus.DOWNLOADING:
            status_item.setBackground(QColor(173, 216, 230))  # Azul claro
            status_item.setForeground(QColor(0, 51, 102))  # Azul escuro
        elif download_item.status == DownloadStatus.PAUSED:
            status_item.setBackground(QColor(255, 255, 180))  # Amarelo claro
            status_item.setForeground(QColor(139, 139, 0))  # Amarelo escuro
        elif download_item.status == DownloadStatus.WAITING:
            status_item.setBackground(QColor(240, 240, 255))  # Azul muito claro
            status_item.setForeground(QColor(0, 0, 139))  # Azul escuro
        
        progress_bar = QProgressBar()
        progress_bar.setValue(download_item.progress)
        self.download_table.setCellWidget(row, 2, progress_bar)
        
        # Mostra tamanhos com os valores do download_item
        log(f"[TABLE] Adicionando à tabela: downloaded={download_item.downloaded_bytes}, total={download_item.total_bytes}")
        
        if download_item.total_bytes > 0:
            size_text = f"{format_size(download_item.downloaded_bytes)} / {format_size(download_item.total_bytes)}"
        else:
            size_text = self.t('calculating')
        
        log(f"[TABLE] Texto do tamanho: {size_text}")
        
        size_item = QTableWidgetItem(size_text)
        self.download_table.setItem(row, 3, size_item)
        
        speed_item = QTableWidgetItem("0 B/s")
        self.download_table.setItem(row, 4, speed_item)

        # Coluna de conexões
        connections_text = f"{download_item.segments}x" if download_item.segments > 1 else "1x"
        connections_item = QTableWidgetItem(connections_text)
        connections_item.setToolTip(self.t('tooltip_connections', count=download_item.segments))
        self.download_table.setItem(row, 5, connections_item)

        # Coluna de mensagem
        self.download_table.setItem(row, 6, QTableWidgetItem(download_item.error_msg))
    
    def on_download_started(self, filename):
        if filename in self.downloads:
            download_item = self.downloads[filename]
            if download_item.thread:
                download_item.thread.progress_updated.connect(
                    lambda fn, data: self.update_progress(fn, data))
                download_item.thread.status_changed.connect(
                    lambda fn, status, msg: self.update_status(fn, status, msg))
    
    def update_progress(self, filename, data):
        log(f"[UPDATE_PROGRESS] RECEBIDO: filename={filename}")
        log(f"[UPDATE_PROGRESS] RECEBIDO: data={data} (type={type(data)})")
        
        # Extrai dados do dicionário
        progress = data.get('progress', 0)
        downloaded = data.get('downloaded', 0)
        total = data.get('total', 0)
        speed = data.get('speed', 0.0)
        
        log(f"[UPDATE_PROGRESS] EXTRAÍDO: progress={progress}%, downloaded={downloaded}, total={total}, speed={speed}")
        
        if filename in self.downloads:
            self.downloads[filename].progress = progress
            self.downloads[filename].downloaded_bytes = downloaded
            # IMPORTANTE: Só atualiza total_bytes se for maior que 0 e válido
            if total > 0 and total < 100000000000000:  # Menor que 100TB (valor razoável)
                self.downloads[filename].total_bytes = total
            self.downloads[filename].speed = speed
            
            # Salva periodicamente (a cada 5% de progresso)
            if progress % 5 == 0:
                self.save_downloads()
        
        for row in range(self.download_table.rowCount()):
            if self.download_table.item(row, 0).text() == filename:
                progress_bar = self.download_table.cellWidget(row, 2)
                if progress_bar:
                    progress_bar.setValue(progress)
                
                size_text = f"{format_size(downloaded)} / {format_size(total)}"
                log(f"[UPDATE_PROGRESS] size_text={size_text}")
                
                size_item = self.download_table.item(row, 3)
                if size_item:
                    size_item.setText(size_text)
                    log(f"[UPDATE_PROGRESS] Tamanho atualizado na GUI: {size_text}")
                
                speed_text = f"{format_size(speed)}/s" if speed > 0 else "0 B/s"
                speed_item = self.download_table.item(row, 4)
                if speed_item:
                    speed_item.setText(speed_text)
                
                break
    
    def update_status(self, filename, status, error_msg):
        if filename in self.downloads:
            self.downloads[filename].status = status
            self.downloads[filename].error_msg = error_msg

            # Define date_completed quando o download é concluído
            if status == DownloadStatus.COMPLETED and self.downloads[filename].date_completed is None:
                from datetime import datetime
                self.downloads[filename].date_completed = datetime.now()
                log(f"[STATUS] Download concluído: {filename} em {self.downloads[filename].date_completed}")

            # Salva automaticamente quando o status muda
            if status in [DownloadStatus.COMPLETED, DownloadStatus.ERROR, DownloadStatus.PAUSED]:
                self.save_downloads()
        
        for row in range(self.download_table.rowCount()):
            if self.download_table.item(row, 0).text() == filename:
                # Atualiza tooltip do filename se foi concluído
                if status == DownloadStatus.COMPLETED:
                    filename_item = self.download_table.item(row, 0)
                    download_item = self.downloads[filename]
                    tooltip_parts = [
                        f"{self.t('tooltip_id')}: {download_item.unique_id[:8]}...",
                        f"{self.t('tooltip_added')}: {download_item.date_added.strftime('%Y-%m-%d %H:%M:%S')}"
                    ]
                    if download_item.date_completed:
                        tooltip_parts.append(f"{self.t('tooltip_completed')}: {download_item.date_completed.strftime('%Y-%m-%d %H:%M:%S')}")
                    filename_item.setToolTip('\n'.join(tooltip_parts))

                status_item = self.download_table.item(row, 1)
                status_item.setText(status.value)

                # Aplica cores com melhor contraste
                if status == DownloadStatus.COMPLETED:
                    status_item.setBackground(QColor(200, 255, 200))  # Verde claro
                    status_item.setForeground(QColor(0, 100, 0))  # Verde escuro
                elif status == DownloadStatus.ERROR:
                    status_item.setBackground(QColor(255, 200, 200))  # Vermelho claro
                    status_item.setForeground(QColor(139, 0, 0))  # Vermelho escuro
                elif status == DownloadStatus.CANCELLED:
                    status_item.setBackground(QColor(220, 220, 220))  # Cinza claro
                    status_item.setForeground(QColor(60, 60, 60))  # Cinza escuro
                elif status == DownloadStatus.DOWNLOADING:
                    status_item.setBackground(QColor(173, 216, 230))  # Azul claro
                    status_item.setForeground(QColor(0, 51, 102))  # Azul escuro
                elif status == DownloadStatus.PAUSED:
                    status_item.setBackground(QColor(255, 255, 180))  # Amarelo claro
                    status_item.setForeground(QColor(139, 139, 0))  # Amarelo escuro
                elif status == DownloadStatus.WAITING:
                    status_item.setBackground(QColor(240, 240, 255))  # Azul muito claro
                    status_item.setForeground(QColor(0, 0, 139))  # Azul escuro

                # Atualiza mensagem de erro
                msg_item = self.download_table.item(row, 6)
                msg_item.setText(error_msg)

                # Atualiza botões da toolbar se esta linha estiver selecionada
                self.update_toolbar_buttons()
                break
    
    def toggle_pause(self, filename):
        if filename not in self.downloads:
            return
        
        download_item = self.downloads[filename]
        
        # Se não tem thread rodando (download pausado de sessão anterior)
        if not download_item.thread or not download_item.thread.isRunning():
            # Apenas inicia se realmente estava pausado
            if download_item.status in [DownloadStatus.PAUSED, DownloadStatus.WAITING]:
                # Adiciona à fila para iniciar
                self.download_manager.add_download(download_item)
                download_item.status = DownloadStatus.WAITING

                # Atualiza GUI
                for row in range(self.download_table.rowCount()):
                    if self.download_table.item(row, 0).text() == filename:
                        status_item = self.download_table.item(row, 1)
                        status_item.setText(DownloadStatus.WAITING.value)
                        status_item.setBackground(QColor(255, 255, 255))
                        break

                self.update_toolbar_buttons()
            return

        # Se tem thread rodando, pausa ou retoma
        if download_item.status == DownloadStatus.DOWNLOADING:
            # Pausa a thread
            download_item.thread.pause()
            download_item.status = DownloadStatus.PAUSED

            for row in range(self.download_table.rowCount()):
                if self.download_table.item(row, 0).text() == filename:
                    status_item = self.download_table.item(row, 1)
                    status_item.setText(DownloadStatus.PAUSED.value)
                    status_item.setBackground(QColor(255, 255, 224))
                    break

            self.save_downloads()
            self.update_toolbar_buttons()

        elif download_item.status == DownloadStatus.PAUSED:
            # Retoma a thread
            download_item.thread.resume()
            download_item.status = DownloadStatus.DOWNLOADING

            for row in range(self.download_table.rowCount()):
                if self.download_table.item(row, 0).text() == filename:
                    status_item = self.download_table.item(row, 1)
                    status_item.setText(DownloadStatus.DOWNLOADING.value)
                    status_item.setBackground(QColor(173, 216, 230))
                    break

            self.save_downloads()
            self.update_toolbar_buttons()

        elif download_item.status == DownloadStatus.WAITING:
            # Se está aguardando mas tem thread, não faz nada
            # Aguarda iniciar para depois poder pausar
            pass
    
    def cancel_download(self, filename):
        if filename not in self.downloads:
            return

        download_item = self.downloads[filename]

        if download_item.thread and download_item.thread.isRunning():
            download_item.thread.cancel()
            download_item.thread.wait()

        self.update_status(filename, DownloadStatus.CANCELLED, self.t('status_cancelled_by_user'))

    def restart_download(self, filename):
        """Recomeça um download cancelado do zero"""
        if filename not in self.downloads:
            return

        download_item = self.downloads[filename]

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

        log(f"[RESTART] Download reiniciado: {filename}")

        # Adiciona à fila novamente
        self.download_manager.add_download(download_item)

        # Atualiza GUI
        for row in range(self.download_table.rowCount()):
            if self.download_table.item(row, 0).text() == filename:
                # Atualiza status
                status_item = self.download_table.item(row, 1)
                status_item.setText(DownloadStatus.WAITING.value)
                status_item.setBackground(QColor(240, 240, 255))  # Azul muito claro
                status_item.setForeground(QColor(0, 0, 139))  # Azul escuro

                # Reset progresso
                progress_bar = self.download_table.cellWidget(row, 2)
                if progress_bar:
                    progress_bar.setValue(0)

                # Reset tamanho
                if download_item.total_bytes > 0:
                    size_text = f"0 B / {format_size(download_item.total_bytes)}"
                else:
                    size_text = self.t('calculating')
                size_item = self.download_table.item(row, 3)
                if size_item:
                    size_item.setText(size_text)

                # Reset velocidade
                speed_item = self.download_table.item(row, 4)
                if speed_item:
                    speed_item.setText("0 B/s")

                # Limpa mensagem de erro
                msg_item = self.download_table.item(row, 6)
                if msg_item:
                    msg_item.setText("")

                break

        # Atualiza toolbar
        self.update_toolbar_buttons()
    
    def clear_completed(self):
        rows_to_remove = []
        
        for row in range(self.download_table.rowCount()):
            filename = self.download_table.item(row, 0).text()
            if filename in self.downloads:
                status = self.downloads[filename].status
                if status in [DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, 
                            DownloadStatus.ERROR]:
                    rows_to_remove.append(row)
                    del self.downloads[filename]
        
        for row in reversed(rows_to_remove):
            self.download_table.removeRow(row)
    
    def cancel_all(self):
        for filename in list(self.downloads.keys()):
            self.cancel_download(filename)
    
    def update_concurrent_limit(self, value):
        self.max_concurrent = value
        if self.download_manager:
            self.download_manager.update_max_concurrent(value)
        self.settings.setValue('max_concurrent', value)
        log(f"[CONFIG] Downloads simultâneos alterado para: {value}")

    def update_segments_per_file(self, value):
        self.segments_per_file = value
        self.settings.setValue('segments_per_file', value)
        log(f"[CONFIG] Conexões por arquivo alterado para: {value}")

    def change_language(self, index):
        """Muda o idioma da interface"""
        new_language = self.language_combo.itemData(index)

        if new_language == self.current_language:
            return  # Não precisa fazer nada se é o mesmo idioma

        # Salva o novo idioma
        self.settings.setValue('language', new_language)
        log(f"[CONFIG] Idioma alterado para: {new_language}")

        # Confirma com o usuário que o app será reiniciado
        reply = QMessageBox.question(
            self,
            'Reiniciar / Restart',
            'O aplicativo precisa ser reiniciado para aplicar o novo idioma.\n'
            'The application needs to restart to apply the new language.\n\n'
            'Deseja reiniciar agora?\n'
            'Do you want to restart now?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
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
            current_index = 0 if self.current_language == 'pt-BR' else 1
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(current_index)
            self.language_combo.blockSignals(False)

    def show_context_menu(self, position):
        """Mostra menu de contexto ao clicar com botão direito na tabela"""
        # Pega o item clicado
        item = self.download_table.itemAt(position)
        if not item:
            return

        row = item.row()
        column = item.column()

        # Menu para coluna de mensagem (coluna 6)
        if column == 6:
            msg_item = self.download_table.item(row, 6)
            if msg_item and msg_item.text():
                # Cria o menu
                menu = QApplication.instance().sender().parentWidget().window()
                context_menu = QMenu(menu)

                # Adiciona ação de copiar
                copy_action = context_menu.addAction(self.t('context_copy'))
                copy_action.triggered.connect(lambda: self.copy_message_to_clipboard(msg_item.text()))

                # Mostra o menu na posição do cursor
                context_menu.exec(self.download_table.viewport().mapToGlobal(position))

        # Menu para coluna de arquivo (coluna 0)
        elif column == 0:
            filename_item = self.download_table.item(row, 0)
            if filename_item:
                filename = filename_item.text()

                # Pega o download_item
                if filename in self.downloads:
                    download_item = self.downloads[filename]
                    file_path = os.path.join(download_item.dest_folder, download_item.filename)

                    # Cria o menu
                    menu = QApplication.instance().sender().parentWidget().window()
                    context_menu = QMenu(menu)

                    # Adiciona ação de abrir arquivo (só se o arquivo existir)
                    if os.path.exists(file_path):
                        open_file_action = context_menu.addAction(self.t('context_open_file'))
                        open_file_action.triggered.connect(lambda: self.open_file(file_path))

                    # Adiciona ação de abrir pasta (só se a pasta existir)
                    if os.path.exists(download_item.dest_folder):
                        open_folder_action = context_menu.addAction(self.t('context_open_folder'))
                        open_folder_action.triggered.connect(lambda: self.open_folder(download_item.dest_folder))

                    # Mostra o menu na posição do cursor
                    context_menu.exec(self.download_table.viewport().mapToGlobal(position))

    def copy_message_to_clipboard(self, text):
        """Copia texto para a área de transferência"""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        log(f"[CLIPBOARD] Mensagem copiada: {text[:50]}..." if len(text) > 50 else f"[CLIPBOARD] Mensagem copiada: {text}")

    def open_file(self, file_path):
        """Abre o arquivo com o programa padrão do sistema"""
        try:
            if platform.system() == 'Windows':
                os.startfile(file_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', file_path])
            else:  # Linux e outros
                subprocess.run(['xdg-open', file_path])
            log(f"[FILE] Abrindo arquivo: {file_path}")
        except Exception as e:
            log(f"[FILE] Erro ao abrir arquivo: {e}")
            QMessageBox.warning(self, self.t('error'), f"Could not open file: {str(e)}")

    def open_folder(self, folder_path):
        """Abre a pasta no gerenciador de arquivos"""
        try:
            if platform.system() == 'Windows':
                os.startfile(folder_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', folder_path])
            else:  # Linux e outros
                subprocess.run(['xdg-open', folder_path])
            log(f"[FOLDER] Abrindo pasta: {folder_path}")
        except Exception as e:
            log(f"[FOLDER] Erro ao abrir pasta: {e}")
            QMessageBox.warning(self, self.t('error'), f"Could not open folder: {str(e)}")

    def on_download_table_double_click(self, row, column):
        """Trata duplo clique na tabela de downloads - abre o arquivo"""
        # Só processa se clicar na coluna de arquivo (coluna 0)
        if column == 0:
            filename_item = self.download_table.item(row, 0)
            if filename_item:
                filename = filename_item.text()

                # Pega o download_item
                if filename in self.downloads:
                    download_item = self.downloads[filename]
                    file_path = os.path.join(download_item.dest_folder, download_item.filename)

                    # Abre o arquivo se ele existir
                    if os.path.exists(file_path):
                        self.open_file(file_path)
                    else:
                        QMessageBox.warning(self, self.t('error'),
                                          f"File not found: {file_path}")

    def show_history(self):
        if not self.recent_identifiers:
            QMessageBox.information(self, self.t('history_button'),
                                  self.t('history_empty'))
            return

        from PyQt6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle(self.t('history_title'))
        dialog.setGeometry(200, 200, 500, 400)

        layout = QVBoxLayout(dialog)

        label = QLabel(self.t('history_instruction'))
        layout.addWidget(label)

        history_list = QListWidget()
        history_list.addItems(self.recent_identifiers)
        history_list.itemDoubleClicked.connect(
            lambda item: self.load_from_history(item.text(), dialog))
        layout.addWidget(history_list)

        button_layout = QHBoxLayout()

        clear_btn = QPushButton(self.t('history_clear'))
        clear_btn.clicked.connect(lambda: self.clear_history(dialog))

        close_btn = QPushButton(self.t('history_close'))
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
        reply = QMessageBox.question(self, self.t('confirm'),
                                     self.t('confirm_clear_history'),
                                     QMessageBox.StandardButton.Yes |
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.recent_identifiers = []
            self.save_recent_identifiers()
            self.update_completer()
            dialog.close()
            QMessageBox.information(self, self.t('success'), self.t('success_history_cleared'))
    
    def update_completer(self):
        self.completer.model().setStringList(self.recent_identifiers)

    def update_search_completer(self):
        self.search_completer.model().setStringList(self.recent_searches)

    def show_search_history(self):
        if not self.recent_searches:
            QMessageBox.information(self, self.t('search_history_button'),
                                  self.t('search_history_empty'))
            return

        from PyQt6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle(self.t('search_history_title'))
        dialog.setGeometry(200, 200, 600, 400)

        layout = QVBoxLayout(dialog)

        label = QLabel(self.t('search_history_instruction'))
        layout.addWidget(label)

        history_list = QListWidget()
        history_list.addItems(self.recent_searches)
        history_list.itemDoubleClicked.connect(
            lambda item: self.load_search_from_history(item.text(), dialog))
        layout.addWidget(history_list)

        button_layout = QHBoxLayout()

        clear_button = QPushButton(self.t('history_clear'))
        clear_button.clicked.connect(lambda: self.clear_search_history(dialog))
        button_layout.addWidget(clear_button)

        close_button = QPushButton(self.t('history_close'))
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)
        dialog.exec()

    def load_search_from_history(self, query, dialog):
        self.search_query_input.setText(query)
        dialog.close()
        self.tabs_widget.setCurrentIndex(0)  # Muda para a aba de busca
        self.search_archive()

    def clear_search_history(self, dialog):
        reply = QMessageBox.question(self, self.t('confirm'),
                                     self.t('confirm_clear_search_history'),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.recent_searches = []
            self.save_recent_searches()
            self.update_search_completer()
            dialog.close()
            QMessageBox.information(self, self.t('success'), self.t('success_search_history_cleared'))

    def closeEvent(self, event):
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


def main():
    app = QApplication(sys.argv)
    gui = InternetArchiveGUI()
    gui.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()