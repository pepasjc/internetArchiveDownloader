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
    QCompleter, QMenu, QCheckBox, QDialog, QComboBox
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor

# Importa os módulos locais
from models import DownloadStatus, DownloadItem
from threads import DownloadManager
from utils import log, set_logging_enabled, format_size
from translations import Translator

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

        self.initUI()
        self.start_download_manager()
        self.load_downloads()

        # Restaura a aba selecionada (após initUI)
        last_tab = self.settings.value('last_tab_index', 0, type=int)
        self.tabs_widget.setCurrentIndex(last_tab)

        # Conecta o sinal APÓS restaurar a aba (para não sobrescrever durante a inicialização)
        self.tabs_widget.currentChanged.connect(self.on_tab_changed)

        # Auto-busca o último identifier se houver
        if self.last_identifier:
            log(f"[STARTUP] Auto-buscando último identifier: {self.last_identifier}")
            self.search_files()
        
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
                
                # SEMPRE busca o tamanho do IA para garantir que está correto
                if download_item.item_id:
                    log(f"[LOAD] Buscando tamanho correto do IA para: {download_item.item_id}")
                    try:
                        item = ia.get_item(download_item.item_id)
                        for f in item.files:
                            if f['name'] == download_item.filename:
                                download_item.total_bytes = abs(int(f.get('size', 0)))
                                log(f"[LOAD] Total bytes correto do IA: {download_item.total_bytes} ({format_size(download_item.total_bytes)})")
                                break
                    except Exception as e:
                        log(f"[LOAD] Erro ao buscar do IA: {e}")
                
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
        self.setGeometry(100, 100, 900, 700)

        # Adiciona barra de status
        self.statusBar().showMessage(self.t('status_ready'))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.tabs_widget = QTabWidget()
        self.tabs_widget.setStyleSheet('QTabWidget::pane { border: 1px solid #ccc; } QTabBar::tab { font-size: 13px; padding: 8px 15px; }')
        layout.addWidget(self.tabs_widget)

        tab1 = self.create_search_tab()
        self.tabs_widget.addTab(tab1, self.t('tab_search'))

        tab2 = self.create_identifier_tab()
        self.tabs_widget.addTab(tab2, self.t('tab_identifier'))

        tab3 = self.create_url_tab()
        self.tabs_widget.addTab(tab3, self.t('tab_url'))

        tab4 = self.create_download_manager_tab()
        self.tabs_widget.addTab(tab4, self.t('tab_downloads'))

        tab5 = self.create_settings_tab()
        self.tabs_widget.addTab(tab5, self.t('tab_settings'))

    def on_tab_changed(self, index):
        """Salva a aba selecionada quando o usuário muda de aba"""
        self.settings.setValue('last_tab_index', index)
        log(f"[CONFIG] Aba alterada para índice: {index}")

    def create_search_tab(self):
        """Cria a aba de busca no Internet Archive"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Título
        title = QLabel(self.t('search_title'))
        title.setStyleSheet('font-size: 18px; font-weight: bold; padding: 5px;')
        layout.addWidget(title)

        # Campo de busca
        search_layout = QHBoxLayout()
        search_label = QLabel(self.t('search_label'))
        search_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.search_query_input = QLineEdit()
        self.search_query_input.setPlaceholderText(self.t('search_placeholder'))
        self.search_query_input.setStyleSheet('font-size: 13px; padding: 5px;')
        self.search_query_input.returnPressed.connect(self.search_archive)  # Enter para buscar

        # Autocomplete para histórico de buscas
        self.search_completer = QCompleter(self.recent_searches)
        self.search_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search_query_input.setCompleter(self.search_completer)

        # Filtro de tipo de mídia
        mediatype_label = QLabel(self.t('search_type_label'))
        mediatype_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.mediatype_combo = QComboBox()
        self.mediatype_combo.setStyleSheet('font-size: 13px; padding: 3px;')
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
        self.search_archive_btn.setStyleSheet('font-size: 13px; font-weight: bold; padding: 5px 15px;')
        self.search_archive_btn.clicked.connect(self.search_archive)

        self.search_history_btn = QPushButton(self.t('search_history_button'))
        self.search_history_btn.setStyleSheet('font-size: 13px; padding: 5px 15px;')
        self.search_history_btn.clicked.connect(self.show_search_history)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_query_input)
        search_layout.addWidget(mediatype_label)
        search_layout.addWidget(self.mediatype_combo)
        search_layout.addWidget(self.search_archive_btn)
        search_layout.addWidget(self.search_history_btn)
        layout.addLayout(search_layout)

        # Dica de sintaxe
        syntax_hint = QLabel(self.t('search_hint'))
        syntax_hint.setStyleSheet('color: #555; font-size: 11px; font-style: italic; padding: 3px;')
        syntax_hint.setWordWrap(True)
        layout.addWidget(syntax_hint)

        # Label dos resultados
        self.search_results_label = QLabel('')
        self.search_results_label.setStyleSheet('font-size: 13px; font-weight: bold; padding: 5px;')
        layout.addWidget(self.search_results_label)

        # Controles de paginação
        pagination_layout = QHBoxLayout()
        self.prev_page_btn = QPushButton(self.t('search_previous'))
        self.prev_page_btn.setStyleSheet('font-size: 12px; padding: 5px 15px;')
        self.prev_page_btn.clicked.connect(self.previous_page)
        self.prev_page_btn.setEnabled(False)

        self.page_info_label = QLabel('')
        self.page_info_label.setStyleSheet('font-size: 12px; font-weight: bold;')
        self.page_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.next_page_btn = QPushButton(self.t('search_next'))
        self.next_page_btn.setStyleSheet('font-size: 12px; padding: 5px 15px;')
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)

        pagination_layout.addWidget(self.prev_page_btn)
        pagination_layout.addWidget(self.page_info_label)
        pagination_layout.addWidget(self.next_page_btn)
        layout.addLayout(pagination_layout)

        # Tabela de resultados
        results_hint = QLabel(self.t('search_results_hint'))
        results_hint.setStyleSheet('font-size: 12px; padding: 3px;')
        layout.addWidget(results_hint)

        self.search_results_table = QTableWidget()
        self.search_results_table.setStyleSheet('font-size: 12px;')
        self.search_results_table.setColumnCount(5)
        self.search_results_table.setHorizontalHeaderLabels([
            self.t('col_title'), self.t('col_identifier'), self.t('col_type'),
            self.t('col_downloads'), self.t('col_description')
        ])

        # Configuração das colunas
        self.search_results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Título
        self.search_results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # Identifier
        self.search_results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Tipo
        self.search_results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Downloads
        self.search_results_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # Descrição

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
                    'mediatype': mediatype_result
                })

                count += 1

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
            4: 'description'
        }

        sort_key = column_keys.get(column)
        if not sort_key:
            return

        # Ordena o cache completo
        reverse = (self.current_sort_order == Qt.SortOrder.DescendingOrder)

        if sort_key == 'downloads':
            # Para downloads, ordena numericamente
            self.search_results_cache.sort(key=lambda x: x[sort_key], reverse=reverse)
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

            # Descrição
            desc_item = QTableWidgetItem(result['description'])
            self.search_results_table.setItem(row, 4, desc_item)

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
        """Carrega os arquivos de um item da busca (tabela)"""
        # Pega o identifier da primeira coluna (Título) da linha clicada
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

    def create_identifier_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        id_layout = QHBoxLayout()
        id_label = QLabel(self.t('identifier_label'))
        id_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText(self.t('identifier_placeholder'))
        self.id_input.setStyleSheet('font-size: 13px; padding: 5px;')
        self.id_input.returnPressed.connect(self.search_files)  # Enter para buscar

        self.completer = QCompleter(self.recent_identifiers)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.id_input.setCompleter(self.completer)

        self.search_btn = QPushButton(self.t('search_files_button'))
        self.search_btn.setStyleSheet('font-size: 13px; font-weight: bold; padding: 5px 15px;')
        self.search_btn.clicked.connect(self.search_files)

        self.history_btn = QPushButton(self.t('history_button'))
        self.history_btn.setStyleSheet('font-size: 13px; padding: 5px 10px;')
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
        filter_label = QLabel(self.t('filter_label'))
        filter_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(self.t('filter_placeholder'))
        self.filter_input.setStyleSheet('font-size: 12px; padding: 5px;')
        self.filter_input.textChanged.connect(self.filter_files)
        self.clear_filter_btn = QPushButton('✕')
        self.clear_filter_btn.setStyleSheet('font-size: 13px; padding: 5px;')
        self.clear_filter_btn.setMaximumWidth(35)
        self.clear_filter_btn.setToolTip(self.t('clear_filter_tooltip'))
        self.clear_filter_btn.clicked.connect(lambda: self.filter_input.clear())

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_input)
        filter_layout.addWidget(self.clear_filter_btn)
        layout.addLayout(filter_layout)

        list_label = QLabel(self.t('files_label'))
        list_label.setStyleSheet('font-size: 12px; font-weight: bold; padding: 5px;')
        layout.addWidget(list_label)

        hint_label = QLabel(self.t('double_click_hint'))
        hint_label.setStyleSheet('color: #555; font-size: 11px; font-style: italic; padding: 3px;')
        layout.addWidget(hint_label)

        self.file_list = QListWidget()
        self.file_list.setStyleSheet('font-size: 12px;')
        self.file_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.file_list.itemDoubleClicked.connect(self.add_file_on_double_click)
        layout.addWidget(self.file_list)

        download_layout = QHBoxLayout()
        self.download_btn = QPushButton(self.t('add_to_queue_button'))
        self.download_btn.setStyleSheet('font-size: 13px; font-weight: bold; padding: 8px 20px;')
        self.download_btn.clicked.connect(self.add_to_queue)
        self.download_btn.setEnabled(False)
        download_layout.addStretch()
        download_layout.addWidget(self.download_btn)
        layout.addLayout(download_layout)

        self.status_label = QLabel('')
        self.status_label.setStyleSheet('font-size: 12px; font-weight: bold; padding: 5px;')
        layout.addWidget(self.status_label)

        return tab
    
    def create_url_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        url_label = QLabel(self.t('url_label'))
        url_label.setStyleSheet('font-size: 13px; font-weight: bold; padding: 5px;')
        layout.addWidget(url_label)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(self.t('url_placeholder'))
        self.url_input.setStyleSheet('font-size: 13px; padding: 8px;')
        self.url_input.returnPressed.connect(self.add_url_to_queue)  # Enter para adicionar à fila
        layout.addWidget(self.url_input)

        url_example = QLabel(self.t('url_format'))
        url_example.setStyleSheet('color: #555; font-size: 11px; padding: 3px;')
        layout.addWidget(url_example)

        self.direct_download_btn = QPushButton(self.t('direct_download_button'))
        self.direct_download_btn.setStyleSheet('font-size: 13px; font-weight: bold; padding: 10px 20px;')
        self.direct_download_btn.clicked.connect(self.add_url_to_queue)
        layout.addWidget(self.direct_download_btn)

        layout.addStretch()
        return tab
    
    def create_download_manager_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.download_table = QTableWidget()
        self.download_table.setStyleSheet('font-size: 12px;')
        self.download_table.setColumnCount(8)
        self.download_table.setHorizontalHeaderLabels([
            self.t('dm_col_file'), self.t('dm_col_status'), self.t('dm_col_progress'),
            self.t('dm_col_size'), self.t('dm_col_speed'), self.t('dm_col_connections'),
            self.t('dm_col_actions'), self.t('dm_col_message')
        ])
        # Aumenta altura das linhas para melhor visibilidade
        self.download_table.verticalHeader().setDefaultSectionSize(35)

        self.download_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.download_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.download_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.download_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.download_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.download_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Conexões
        self.download_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Ações
        self.download_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)  # Mensagem
        self.download_table.setColumnWidth(2, 200)
        self.download_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.download_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.download_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.download_table.customContextMenuRequested.connect(self.show_context_menu)
        self.download_table.cellDoubleClicked.connect(self.on_download_table_double_click)

        layout.addWidget(self.download_table)

        control_layout = QHBoxLayout()
        self.clear_completed_btn = QPushButton(self.t('dm_clear_completed'))
        self.clear_completed_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        self.cancel_all_btn = QPushButton(self.t('dm_cancel_all'))
        self.cancel_all_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.cancel_all_btn.clicked.connect(self.cancel_all)

        control_layout.addWidget(self.clear_completed_btn)
        control_layout.addWidget(self.cancel_all_btn)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        return tab

    def create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Título
        title = QLabel(self.t('settings_title'))
        title.setStyleSheet('font-size: 18px; font-weight: bold; padding: 5px;')
        layout.addWidget(title)

        layout.addSpacing(10)

        # Seção: Conta do Internet Archive
        account_group_label = QLabel(self.t('account_section'))
        account_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(account_group_label)

        account_desc = QLabel(self.t('account_description'))
        account_desc.setStyleSheet('font-size: 12px;')
        layout.addWidget(account_desc)

        # Status da conta
        self.account_status_label = QLabel()
        self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px;')
        self.update_account_status()
        layout.addWidget(self.account_status_label)

        # Email
        email_layout = QHBoxLayout()
        email_label = QLabel(self.t('account_email'))
        email_label.setStyleSheet('font-size: 12px;')
        email_label.setMinimumWidth(80)
        self.ia_email_input = QLineEdit()
        self.ia_email_input.setPlaceholderText(self.t('account_email_placeholder'))
        self.ia_email_input.setStyleSheet('font-size: 12px; padding: 5px;')
        email_layout.addWidget(email_label)
        email_layout.addWidget(self.ia_email_input)
        layout.addLayout(email_layout)

        # Senha
        password_layout = QHBoxLayout()
        password_label = QLabel(self.t('account_password'))
        password_label.setStyleSheet('font-size: 12px;')
        password_label.setMinimumWidth(80)
        self.ia_password_input = QLineEdit()
        self.ia_password_input.setPlaceholderText(self.t('account_password_placeholder'))
        self.ia_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ia_password_input.setStyleSheet('font-size: 12px; padding: 5px;')
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.ia_password_input)
        layout.addLayout(password_layout)

        # Botões de ação
        account_buttons_layout = QHBoxLayout()
        self.ia_login_btn = QPushButton(self.t('account_login'))
        self.ia_login_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.ia_login_btn.clicked.connect(self.ia_login)

        self.ia_logout_btn = QPushButton(self.t('account_logout'))
        self.ia_logout_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.ia_logout_btn.clicked.connect(self.ia_logout)

        account_buttons_layout.addWidget(self.ia_login_btn)
        account_buttons_layout.addWidget(self.ia_logout_btn)
        account_buttons_layout.addStretch()
        layout.addLayout(account_buttons_layout)

        account_note = QLabel(self.t('account_note'))
        account_note.setStyleSheet('color: #555; font-size: 11px; font-style: italic;')
        account_note.setWordWrap(True)
        layout.addWidget(account_note)

        layout.addSpacing(20)

        # Seção: Pasta Padrão
        folder_group_label = QLabel(self.t('folder_section'))
        folder_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(folder_group_label)

        folder_layout = QHBoxLayout()
        folder_desc = QLabel(self.t('folder_description'))
        folder_desc.setStyleSheet('font-size: 12px;')
        folder_layout.addWidget(folder_desc)
        layout.addLayout(folder_layout)

        folder_control_layout = QHBoxLayout()
        self.default_folder_input = QLineEdit()
        self.default_folder_input.setPlaceholderText(self.t('folder_placeholder'))
        self.default_folder_input.setText(self.default_download_folder)
        self.default_folder_input.setStyleSheet('font-size: 12px; padding: 5px;')
        self.default_folder_input.setReadOnly(True)

        self.choose_folder_btn = QPushButton(self.t('folder_choose'))
        self.choose_folder_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.choose_folder_btn.clicked.connect(self.choose_default_folder)

        self.clear_folder_btn = QPushButton(self.t('folder_clear'))
        self.clear_folder_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.clear_folder_btn.clicked.connect(self.clear_default_folder)

        folder_control_layout.addWidget(self.default_folder_input)
        folder_control_layout.addWidget(self.choose_folder_btn)
        folder_control_layout.addWidget(self.clear_folder_btn)
        layout.addLayout(folder_control_layout)

        layout.addSpacing(20)

        # Seção: Performance
        perf_group_label = QLabel(self.t('perf_section'))
        perf_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(perf_group_label)

        concurrent_layout = QHBoxLayout()
        concurrent_label = QLabel(self.t('perf_concurrent'))
        concurrent_label.setStyleSheet('font-size: 12px;')
        concurrent_label.setToolTip(self.t('perf_concurrent_tooltip'))
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setStyleSheet('font-size: 12px;')
        self.concurrent_spin.setMinimum(1)
        self.concurrent_spin.setMaximum(10)
        self.concurrent_spin.setValue(self.max_concurrent)
        self.concurrent_spin.valueChanged.connect(self.update_concurrent_limit)
        concurrent_layout.addWidget(concurrent_label)
        concurrent_layout.addWidget(self.concurrent_spin)
        concurrent_layout.addStretch()
        layout.addLayout(concurrent_layout)

        segments_layout = QHBoxLayout()
        segments_label = QLabel(self.t('perf_connections'))
        segments_label.setStyleSheet('font-size: 12px;')
        segments_label.setToolTip(self.t('perf_connections_tooltip'))
        self.segments_spin = QSpinBox()
        self.segments_spin.setStyleSheet('font-size: 12px;')
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
        perf_note.setStyleSheet('color: #555; font-size: 11px; font-style: italic;')
        perf_note.setWordWrap(True)
        layout.addWidget(perf_note)

        layout.addSpacing(20)

        # Seção: Debug e Logs
        debug_group_label = QLabel(self.t('debug_section'))
        debug_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(debug_group_label)

        self.enable_logging_checkbox = QCheckBox(self.t('debug_logging'))
        self.enable_logging_checkbox.setStyleSheet('font-size: 12px;')
        self.enable_logging_checkbox.setChecked(self.settings.value('enable_logging', True, type=bool))
        self.enable_logging_checkbox.stateChanged.connect(self.toggle_logging)
        layout.addWidget(self.enable_logging_checkbox)

        logging_note = QLabel(self.t('debug_note'))
        logging_note.setStyleSheet('color: #555; font-size: 11px; font-style: italic;')
        logging_note.setWordWrap(True)
        layout.addWidget(logging_note)

        layout.addSpacing(20)

        # Seção: Idioma / Language
        language_group_label = QLabel('🌐 Idioma / Language')
        language_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(language_group_label)

        language_layout = QHBoxLayout()
        language_label = QLabel('Idioma da interface / Interface language:')
        language_label.setStyleSheet('font-size: 12px;')
        self.language_combo = QComboBox()
        self.language_combo.setStyleSheet('font-size: 12px; padding: 3px;')
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
        language_note.setStyleSheet('color: #555; font-size: 11px; font-style: italic;')
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
                self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px; color: green; font-weight: bold;')
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
                            self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px; color: green; font-weight: bold;')
                            log(f"[ACCOUNT] Credenciais encontradas em: {config_file}")
                            return

            self.account_status_label.setText(self.t('account_not_configured'))
            self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px; color: #888;')
            log("[ACCOUNT] Nenhuma credencial encontrada")

        except Exception as e:
            log(f"[ACCOUNT] Erro ao verificar status: {e}")
            import traceback
            traceback.print_exc()
            self.account_status_label.setText(self.t('account_unknown'))
            self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px; color: #888;')

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
    
    def add_url_to_queue(self):
        url = self.url_input.text().strip()

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
        self.url_input.clear()
    
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

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(2, 2, 2, 2)

        # Texto do botão baseado no status atual
        pause_btn_text = self.t('action_resume') if download_item.status == DownloadStatus.PAUSED else self.t('action_pause')
        pause_btn = QPushButton(pause_btn_text)
        pause_btn.setStyleSheet('font-size: 11px; padding: 4px 8px;')
        pause_btn.clicked.connect(lambda: self.toggle_pause(download_item.filename))

        # Botão Cancelar/Recomeçar
        if download_item.status == DownloadStatus.CANCELLED:
            cancel_btn = QPushButton(self.t('action_restart'))
            cancel_btn.setStyleSheet('font-size: 11px; padding: 4px 8px;')
            cancel_btn.clicked.connect(lambda: self.restart_download(download_item.filename))
        else:
            cancel_btn = QPushButton(self.t('action_cancel'))
            cancel_btn.setStyleSheet('font-size: 11px; padding: 4px 8px;')
            cancel_btn.clicked.connect(lambda: self.cancel_download(download_item.filename))

        actions_layout.addWidget(pause_btn)
        actions_layout.addWidget(cancel_btn)
        self.download_table.setCellWidget(row, 6, actions_widget)

        self.download_table.setItem(row, 7, QTableWidgetItem(download_item.error_msg))
    
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
                
                # Atualiza o botão baseado no novo status
                actions_widget = self.download_table.cellWidget(row, 6)
                if actions_widget:
                    pause_btn = actions_widget.layout().itemAt(0).widget()
                    cancel_btn = actions_widget.layout().itemAt(1).widget()

                    # Atualiza botão Pausar/Retomar
                    if status == DownloadStatus.DOWNLOADING:
                        pause_btn.setText(self.t('action_pause'))
                    elif status == DownloadStatus.PAUSED:
                        pause_btn.setText(self.t('action_resume'))
                    elif status == DownloadStatus.WAITING:
                        pause_btn.setText(self.t('action_pause'))

                    # Atualiza botão Cancelar/Recomeçar
                    if status == DownloadStatus.CANCELLED:
                        # Reconecta o botão para recomeçar
                        cancel_btn.setText(self.t('action_restart'))
                        cancel_btn.clicked.disconnect()
                        cancel_btn.clicked.connect(lambda fn=filename: self.restart_download(fn))
                    elif cancel_btn.text() == self.t('action_restart'):
                        # Se estava como "Recomeçar" mas não está mais cancelado, volta para "Cancelar"
                        cancel_btn.setText(self.t('action_cancel'))
                        cancel_btn.clicked.disconnect()
                        cancel_btn.clicked.connect(lambda fn=filename: self.cancel_download(fn))

                msg_item = self.download_table.item(row, 7)
                msg_item.setText(error_msg)
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
                        actions_widget = self.download_table.cellWidget(row, 6)
                        if actions_widget:
                            pause_btn = actions_widget.layout().itemAt(0).widget()
                            pause_btn.setText(self.t('action_pause'))
                        status_item = self.download_table.item(row, 1)
                        status_item.setText(DownloadStatus.WAITING.value)
                        status_item.setBackground(QColor(255, 255, 255))
                        break
            return
        
        # Se tem thread rodando, pausa ou retoma
        for row in range(self.download_table.rowCount()):
            if self.download_table.item(row, 0).text() == filename:
                actions_widget = self.download_table.cellWidget(row, 6)
                if not actions_widget:
                    return
                    
                pause_btn = actions_widget.layout().itemAt(0).widget()
                
                if download_item.status == DownloadStatus.DOWNLOADING:
                    # Pausa a thread
                    download_item.thread.pause()
                    download_item.status = DownloadStatus.PAUSED
                    pause_btn.setText(self.t('action_resume'))
                    status_item = self.download_table.item(row, 1)
                    status_item.setText(DownloadStatus.PAUSED.value)
                    status_item.setBackground(QColor(255, 255, 224))
                    self.save_downloads()

                elif download_item.status == DownloadStatus.PAUSED:
                    # Retoma a thread
                    download_item.thread.resume()
                    download_item.status = DownloadStatus.DOWNLOADING
                    pause_btn.setText(self.t('action_pause'))
                    status_item = self.download_table.item(row, 1)
                    status_item.setText(DownloadStatus.DOWNLOADING.value)
                    status_item.setBackground(QColor(173, 216, 230))
                    self.save_downloads()
                    
                elif download_item.status == DownloadStatus.WAITING:
                    # Se está aguardando mas tem thread, não faz nada
                    # Aguarda iniciar para depois poder pausar
                    pass
                    
                break
    
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
                msg_item = self.download_table.item(row, 7)
                if msg_item:
                    msg_item.setText("")

                # Atualiza botões
                actions_widget = self.download_table.cellWidget(row, 6)
                if actions_widget:
                    # Remove o widget antigo e cria um novo
                    self.download_table.removeCellWidget(row, 6)

                    # Cria novo widget de ações
                    new_actions_widget = QWidget()
                    new_actions_layout = QHBoxLayout(new_actions_widget)
                    new_actions_layout.setContentsMargins(2, 2, 2, 2)

                    pause_btn = QPushButton(self.t('action_pause'))
                    pause_btn.setStyleSheet('font-size: 11px; padding: 4px 8px;')
                    pause_btn.clicked.connect(lambda: self.toggle_pause(filename))

                    cancel_btn = QPushButton(self.t('action_cancel'))
                    cancel_btn.setStyleSheet('font-size: 11px; padding: 4px 8px;')
                    cancel_btn.clicked.connect(lambda: self.cancel_download(filename))

                    new_actions_layout.addWidget(pause_btn)
                    new_actions_layout.addWidget(cancel_btn)
                    self.download_table.setCellWidget(row, 6, new_actions_widget)

                break
    
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

        # Menu para coluna de mensagem (coluna 7)
        if column == 7:
            msg_item = self.download_table.item(row, 7)
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