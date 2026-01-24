"""Internet Archive Downloader GUI"""

import sys
import time
import json
import os
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

        # Carrega configuração de logging e aplica globalmente
        enable_logging = self.settings.value('enable_logging', True, type=bool)
        self.set_logging_enabled(enable_logging)

        self.recent_identifiers = self.load_recent_identifiers()
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
            # Salva todos exceto completados e cancelados
            if download_item.status not in [DownloadStatus.COMPLETED, DownloadStatus.CANCELLED]:
                # Atualiza downloaded_bytes com o tamanho atual do arquivo se existir
                dest_path = os.path.join(download_item.dest_folder, download_item.filename)
                if os.path.exists(dest_path):
                    download_item.downloaded_bytes = os.path.getsize(dest_path)
                    if download_item.total_bytes > 0:
                        download_item.progress = int((download_item.downloaded_bytes / download_item.total_bytes) * 100)
                
                log(f"[SAVE] {download_item.filename}:")
                log(f"       total_bytes={download_item.total_bytes} ({format_size(download_item.total_bytes)})")
                log(f"       downloaded_bytes={download_item.downloaded_bytes} ({format_size(download_item.downloaded_bytes)})")
                log(f"       progress={download_item.progress}%")
                
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
        self.setWindowTitle('Internet Archive Downloader')
        self.setGeometry(100, 100, 900, 700)

        # Adiciona barra de status
        self.statusBar().showMessage('Pronto')

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.tabs_widget = QTabWidget()
        self.tabs_widget.setStyleSheet('QTabWidget::pane { border: 1px solid #ccc; } QTabBar::tab { font-size: 13px; padding: 8px 15px; }')
        layout.addWidget(self.tabs_widget)

        tab1 = self.create_search_tab()
        self.tabs_widget.addTab(tab1, "🔍 Buscar no Arquivo")

        tab2 = self.create_identifier_tab()
        self.tabs_widget.addTab(tab2, "Buscar por Identifier")

        tab3 = self.create_url_tab()
        self.tabs_widget.addTab(tab3, "Download Direto por URL")

        tab4 = self.create_download_manager_tab()
        self.tabs_widget.addTab(tab4, "Gerenciador de Downloads")

        tab5 = self.create_settings_tab()
        self.tabs_widget.addTab(tab5, "⚙️ Configurações")

    def on_tab_changed(self, index):
        """Salva a aba selecionada quando o usuário muda de aba"""
        self.settings.setValue('last_tab_index', index)
        log(f"[CONFIG] Aba alterada para índice: {index}")

    def create_search_tab(self):
        """Cria a aba de busca no Internet Archive"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Título
        title = QLabel('Buscar Conteúdo no Internet Archive')
        title.setStyleSheet('font-size: 18px; font-weight: bold; padding: 5px;')
        layout.addWidget(title)

        # Campo de busca
        search_layout = QHBoxLayout()
        search_label = QLabel('Buscar:')
        search_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.search_query_input = QLineEdit()
        self.search_query_input.setPlaceholderText('Ex: documentario nasa, musica classica, livro python...')
        self.search_query_input.setStyleSheet('font-size: 13px; padding: 5px;')
        self.search_query_input.returnPressed.connect(self.search_archive)  # Enter para buscar

        # Filtro de tipo de mídia
        mediatype_label = QLabel('Tipo:')
        mediatype_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.mediatype_combo = QComboBox()
        self.mediatype_combo.setStyleSheet('font-size: 13px; padding: 3px;')
        self.mediatype_combo.addItems([
            'Todos',
            'Áudio (audio)',
            'Vídeo (movies)',
            'Texto (texts)',
            'Imagens (image)',
            'Software (software)',
            'Web (web)',
            'Coleções (collection)',
            'Dados (data)'
        ])

        self.search_archive_btn = QPushButton('Buscar')
        self.search_archive_btn.setStyleSheet('font-size: 13px; font-weight: bold; padding: 5px 15px;')
        self.search_archive_btn.clicked.connect(self.search_archive)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_query_input)
        search_layout.addWidget(mediatype_label)
        search_layout.addWidget(self.mediatype_combo)
        search_layout.addWidget(self.search_archive_btn)
        layout.addLayout(search_layout)

        # Dica de sintaxe
        syntax_hint = QLabel('💡 Dica: Use aspas para frases exatas ("machine learning"), AND/OR para combinar termos, NOT para excluir')
        syntax_hint.setStyleSheet('color: #555; font-size: 11px; font-style: italic; padding: 3px;')
        syntax_hint.setWordWrap(True)
        layout.addWidget(syntax_hint)

        # Label dos resultados
        self.search_results_label = QLabel('')
        self.search_results_label.setStyleSheet('font-size: 13px; font-weight: bold; padding: 5px;')
        layout.addWidget(self.search_results_label)

        # Controles de paginação
        pagination_layout = QHBoxLayout()
        self.prev_page_btn = QPushButton('◀ Anterior')
        self.prev_page_btn.setStyleSheet('font-size: 12px; padding: 5px 15px;')
        self.prev_page_btn.clicked.connect(self.previous_page)
        self.prev_page_btn.setEnabled(False)

        self.page_info_label = QLabel('')
        self.page_info_label.setStyleSheet('font-size: 12px; font-weight: bold;')
        self.page_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.next_page_btn = QPushButton('Próxima ▶')
        self.next_page_btn.setStyleSheet('font-size: 12px; padding: 5px 15px;')
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)

        pagination_layout.addWidget(self.prev_page_btn)
        pagination_layout.addWidget(self.page_info_label)
        pagination_layout.addWidget(self.next_page_btn)
        layout.addLayout(pagination_layout)

        # Tabela de resultados
        results_hint = QLabel('Resultados (clique duas vezes em uma linha para carregar os arquivos):')
        results_hint.setStyleSheet('font-size: 12px; padding: 3px;')
        layout.addWidget(results_hint)

        self.search_results_table = QTableWidget()
        self.search_results_table.setStyleSheet('font-size: 12px;')
        self.search_results_table.setColumnCount(5)
        self.search_results_table.setHorizontalHeaderLabels([
            'Título', 'Identifier', 'Tipo', 'Downloads', 'Descrição'
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
            QMessageBox.warning(self, 'Atenção', 'Por favor, insira um termo de busca.')
            return

        # Pega o tipo de mídia selecionado
        mediatype_text = self.mediatype_combo.currentText()
        mediatype_map = {
            'Todos': '',
            'Áudio (audio)': 'audio',
            'Vídeo (movies)': 'movies',
            'Texto (texts)': 'texts',
            'Imagens (image)': 'image',
            'Software (software)': 'software',
            'Web (web)': 'web',
            'Coleções (collection)': 'collection',
            'Dados (data)': 'data'
        }
        mediatype = mediatype_map.get(mediatype_text, '')

        # Monta a query
        if mediatype:
            full_query = f'{query} AND mediatype:{mediatype}'
        else:
            full_query = query

        self.search_results_label.setText(f'Buscando por: {query}...')
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
                title = result.get('title', 'Sem título')
                description = result.get('description', 'Sem descrição')
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
                self.search_results_label.setText('Nenhum resultado encontrado.')
                self.page_info_label.setText('')
                QMessageBox.information(self, 'Sem Resultados',
                                      f'Nenhum item encontrado para "{query}".')
            else:
                # Reset página para a primeira e limpa ordenação
                self.current_search_page = 0
                self.current_sort_column = None
                self.current_sort_order = Qt.SortOrder.AscendingOrder
                self.update_search_page_display()
                log(f"[SEARCH] {count} resultados encontrados")

        except Exception as e:
            log(f"[SEARCH] Erro: {e}")
            QMessageBox.critical(self, 'Erro', f'Erro ao buscar: {str(e)}')
            self.search_results_label.setText('Erro na busca.')
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
        self.search_results_label.setText(f'{total_results} resultado(s) encontrado(s). Duplo clique para carregar arquivos.')
        self.page_info_label.setText(f'Página {self.current_search_page + 1} de {total_pages} (mostrando {start_idx + 1}-{end_idx} de {total_results})')

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
        id_label = QLabel('Identifier:')
        id_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText('Ex: rick-astley-never-gonna-give-you-up')
        self.id_input.setStyleSheet('font-size: 13px; padding: 5px;')
        self.id_input.returnPressed.connect(self.search_files)  # Enter para buscar

        self.completer = QCompleter(self.recent_identifiers)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.id_input.setCompleter(self.completer)

        self.search_btn = QPushButton('Buscar Arquivos')
        self.search_btn.setStyleSheet('font-size: 13px; font-weight: bold; padding: 5px 15px;')
        self.search_btn.clicked.connect(self.search_files)

        self.history_btn = QPushButton('📋 Histórico')
        self.history_btn.setStyleSheet('font-size: 13px; padding: 5px 10px;')
        self.history_btn.setToolTip('Ver identifiers recentes')
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
        filter_label = QLabel('🔍 Filtrar:')
        filter_label.setStyleSheet('font-size: 13px; font-weight: bold;')
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText('Digite para filtrar arquivos...')
        self.filter_input.setStyleSheet('font-size: 12px; padding: 5px;')
        self.filter_input.textChanged.connect(self.filter_files)
        self.clear_filter_btn = QPushButton('✕')
        self.clear_filter_btn.setStyleSheet('font-size: 13px; padding: 5px;')
        self.clear_filter_btn.setMaximumWidth(35)
        self.clear_filter_btn.setToolTip('Limpar filtro')
        self.clear_filter_btn.clicked.connect(lambda: self.filter_input.clear())

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_input)
        filter_layout.addWidget(self.clear_filter_btn)
        layout.addLayout(filter_layout)

        list_label = QLabel('Arquivos disponíveis (selecione os que deseja baixar):')
        list_label.setStyleSheet('font-size: 12px; font-weight: bold; padding: 5px;')
        layout.addWidget(list_label)

        hint_label = QLabel('💡 Dica: Clique duas vezes em um arquivo para adicioná-lo à fila usando a pasta padrão')
        hint_label.setStyleSheet('color: #555; font-size: 11px; font-style: italic; padding: 3px;')
        layout.addWidget(hint_label)

        self.file_list = QListWidget()
        self.file_list.setStyleSheet('font-size: 12px;')
        self.file_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.file_list.itemDoubleClicked.connect(self.add_file_on_double_click)
        layout.addWidget(self.file_list)

        download_layout = QHBoxLayout()
        self.download_btn = QPushButton('Adicionar à Fila de Download')
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

        url_label = QLabel('Cole a URL completa do arquivo:')
        url_label.setStyleSheet('font-size: 13px; font-weight: bold; padding: 5px;')
        layout.addWidget(url_label)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('Ex: https://archive.org/download/identifier/filename.ext')
        self.url_input.setStyleSheet('font-size: 13px; padding: 8px;')
        self.url_input.returnPressed.connect(self.add_url_to_queue)  # Enter para adicionar à fila
        layout.addWidget(self.url_input)

        url_example = QLabel('Formato: https://archive.org/download/{identifier}/{filename}')
        url_example.setStyleSheet('color: #555; font-size: 11px; padding: 3px;')
        layout.addWidget(url_example)

        self.direct_download_btn = QPushButton('Adicionar à Fila de Download')
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
            'Arquivo', 'Status', 'Progresso', 'Tamanho', 'Velocidade', 'Conexões', 'Ações', 'Mensagem'
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

        layout.addWidget(self.download_table)

        control_layout = QHBoxLayout()
        self.clear_completed_btn = QPushButton('Limpar Concluídos')
        self.clear_completed_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        self.cancel_all_btn = QPushButton('Cancelar Todos')
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
        title = QLabel('Configurações Gerais')
        title.setStyleSheet('font-size: 18px; font-weight: bold; padding: 5px;')
        layout.addWidget(title)

        layout.addSpacing(10)

        # Seção: Conta do Internet Archive
        account_group_label = QLabel('🔐 Conta do Internet Archive')
        account_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(account_group_label)

        account_desc = QLabel('Configure sua conta para acessar recursos privados e fazer uploads:')
        account_desc.setStyleSheet('font-size: 12px;')
        layout.addWidget(account_desc)

        # Status da conta
        self.account_status_label = QLabel()
        self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px;')
        self.update_account_status()
        layout.addWidget(self.account_status_label)

        # Email
        email_layout = QHBoxLayout()
        email_label = QLabel('Email:')
        email_label.setStyleSheet('font-size: 12px;')
        email_label.setMinimumWidth(80)
        self.ia_email_input = QLineEdit()
        self.ia_email_input.setPlaceholderText('seu-email@exemplo.com')
        self.ia_email_input.setStyleSheet('font-size: 12px; padding: 5px;')
        email_layout.addWidget(email_label)
        email_layout.addWidget(self.ia_email_input)
        layout.addLayout(email_layout)

        # Senha
        password_layout = QHBoxLayout()
        password_label = QLabel('Senha:')
        password_label.setStyleSheet('font-size: 12px;')
        password_label.setMinimumWidth(80)
        self.ia_password_input = QLineEdit()
        self.ia_password_input.setPlaceholderText('sua-senha')
        self.ia_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ia_password_input.setStyleSheet('font-size: 12px; padding: 5px;')
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.ia_password_input)
        layout.addLayout(password_layout)

        # Botões de ação
        account_buttons_layout = QHBoxLayout()
        self.ia_login_btn = QPushButton('Fazer Login')
        self.ia_login_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.ia_login_btn.clicked.connect(self.ia_login)

        self.ia_logout_btn = QPushButton('Resetar Credenciais')
        self.ia_logout_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.ia_logout_btn.clicked.connect(self.ia_logout)

        account_buttons_layout.addWidget(self.ia_login_btn)
        account_buttons_layout.addWidget(self.ia_logout_btn)
        account_buttons_layout.addStretch()
        layout.addLayout(account_buttons_layout)

        account_note = QLabel('💡 Nota: As credenciais são armazenadas localmente em ~/.config/ia.ini')
        account_note.setStyleSheet('color: #555; font-size: 11px; font-style: italic;')
        account_note.setWordWrap(True)
        layout.addWidget(account_note)

        layout.addSpacing(20)

        # Seção: Pasta Padrão
        folder_group_label = QLabel('📁 Pasta Padrão para Downloads')
        folder_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(folder_group_label)

        folder_layout = QHBoxLayout()
        folder_desc = QLabel('Pasta onde os arquivos serão salvos ao clicar 2x na lista:')
        folder_desc.setStyleSheet('font-size: 12px;')
        folder_layout.addWidget(folder_desc)
        layout.addLayout(folder_layout)

        folder_control_layout = QHBoxLayout()
        self.default_folder_input = QLineEdit()
        self.default_folder_input.setPlaceholderText('Nenhuma pasta padrão configurada')
        self.default_folder_input.setText(self.default_download_folder)
        self.default_folder_input.setStyleSheet('font-size: 12px; padding: 5px;')
        self.default_folder_input.setReadOnly(True)

        self.choose_folder_btn = QPushButton('Escolher Pasta...')
        self.choose_folder_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.choose_folder_btn.clicked.connect(self.choose_default_folder)

        self.clear_folder_btn = QPushButton('Limpar')
        self.clear_folder_btn.setStyleSheet('font-size: 12px; padding: 6px 12px;')
        self.clear_folder_btn.clicked.connect(self.clear_default_folder)

        folder_control_layout.addWidget(self.default_folder_input)
        folder_control_layout.addWidget(self.choose_folder_btn)
        folder_control_layout.addWidget(self.clear_folder_btn)
        layout.addLayout(folder_control_layout)

        layout.addSpacing(20)

        # Seção: Performance
        perf_group_label = QLabel('⚡ Performance de Downloads')
        perf_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(perf_group_label)

        concurrent_layout = QHBoxLayout()
        concurrent_label = QLabel('Downloads simultâneos:')
        concurrent_label.setStyleSheet('font-size: 12px;')
        concurrent_label.setToolTip('Quantos arquivos podem ser baixados ao mesmo tempo')
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setStyleSheet('font-size: 12px; padding: 3px;')
        self.concurrent_spin.setMinimum(1)
        self.concurrent_spin.setMaximum(10)
        self.concurrent_spin.setValue(self.max_concurrent)
        self.concurrent_spin.valueChanged.connect(self.update_concurrent_limit)
        concurrent_layout.addWidget(concurrent_label)
        concurrent_layout.addWidget(self.concurrent_spin)
        concurrent_layout.addStretch()
        layout.addLayout(concurrent_layout)

        segments_layout = QHBoxLayout()
        segments_label = QLabel('Conexões por arquivo:')
        segments_label.setStyleSheet('font-size: 12px;')
        segments_label.setToolTip('Número de conexões simultâneas para cada arquivo (download acelerado)')
        self.segments_spin = QSpinBox()
        self.segments_spin.setStyleSheet('font-size: 12px; padding: 3px;')
        self.segments_spin.setMinimum(1)
        self.segments_spin.setMaximum(16)
        self.segments_spin.setValue(self.segments_per_file)
        self.segments_spin.setToolTip('Número de conexões simultâneas para cada arquivo (download acelerado)\n\nNOTA: Esta configuração só afeta downloads NOVOS.\nDownloads em andamento mantêm o número de conexões original.')
        self.segments_spin.valueChanged.connect(self.update_segments_per_file)
        segments_layout.addWidget(segments_label)
        segments_layout.addWidget(self.segments_spin)
        segments_layout.addStretch()
        layout.addLayout(segments_layout)

        layout.addSpacing(10)

        perf_note = QLabel('💡 Mais conexões por arquivo = download mais rápido (útil quando o servidor limita a velocidade por conexão)')
        perf_note.setStyleSheet('color: #555; font-size: 11px; font-style: italic;')
        perf_note.setWordWrap(True)
        layout.addWidget(perf_note)

        layout.addSpacing(20)

        # Seção: Debug e Logs
        debug_group_label = QLabel('🐛 Debug e Logs')
        debug_group_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(debug_group_label)

        self.enable_logging_checkbox = QCheckBox('Exibir logs detalhados no console')
        self.enable_logging_checkbox.setStyleSheet('font-size: 12px;')
        self.enable_logging_checkbox.setChecked(self.settings.value('enable_logging', True, type=bool))
        self.enable_logging_checkbox.stateChanged.connect(self.toggle_logging)
        layout.addWidget(self.enable_logging_checkbox)

        logging_note = QLabel('💡 Desabilite os logs para melhorar a performance em downloads muito grandes')
        logging_note.setStyleSheet('color: #555; font-size: 11px; font-style: italic;')
        logging_note.setWordWrap(True)
        layout.addWidget(logging_note)

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
                self.account_status_label.setText(f'✓ Conta configurada')
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
                            self.account_status_label.setText('✓ Conta configurada (arquivo encontrado)')
                            self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px; color: green; font-weight: bold;')
                            log(f"[ACCOUNT] Credenciais encontradas em: {config_file}")
                            return

            self.account_status_label.setText('✗ Nenhuma conta configurada')
            self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px; color: #888;')
            log("[ACCOUNT] Nenhuma credencial encontrada")

        except Exception as e:
            log(f"[ACCOUNT] Erro ao verificar status: {e}")
            import traceback
            traceback.print_exc()
            self.account_status_label.setText('? Status desconhecido')
            self.account_status_label.setStyleSheet('font-size: 12px; padding: 5px; color: #888;')

    def ia_login(self):
        """Faz login na conta do Internet Archive"""
        email = self.ia_email_input.text().strip()
        password = self.ia_password_input.text().strip()

        if not email or not password:
            QMessageBox.warning(self, 'Atenção', 'Por favor, preencha email e senha.')
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
                QMessageBox.information(self, 'Sucesso',
                                      'Login realizado com sucesso!\n\n'
                                      'Suas credenciais foram salvas.')
                log(f"[ACCOUNT] Login bem-sucedido para: {email}")
            else:
                QMessageBox.warning(self, 'Erro', 'Falha ao fazer login. Verifique suas credenciais.')

        except Exception as e:
            log(f"[ACCOUNT] Erro ao fazer login: {e}")
            QMessageBox.critical(self, 'Erro',
                               f'Erro ao fazer login:\n{str(e)}\n\n'
                               f'Verifique suas credenciais e tente novamente.')

    def ia_logout(self):
        """Remove credenciais do Internet Archive"""
        reply = QMessageBox.question(self, 'Confirmar',
                                     'Deseja realmente resetar suas credenciais do Internet Archive?\n\n'
                                     'Isso removerá o arquivo de configuração local.',
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
                    QMessageBox.information(self, 'Sucesso', 'Credenciais removidas com sucesso!')
                else:
                    QMessageBox.information(self, 'Informação', 'Nenhuma configuração encontrada para remover.')

            except Exception as e:
                log(f"[ACCOUNT] Erro ao remover credenciais: {e}")
                QMessageBox.critical(self, 'Erro', f'Erro ao remover credenciais:\n{str(e)}')

    def choose_default_folder(self):
        """Abre diálogo para escolher pasta padrão"""
        folder = QFileDialog.getExistingDirectory(self, 'Escolha a pasta padrão para downloads', self.default_download_folder)

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
            QMessageBox.warning(self, 'Pasta Padrão não Configurada',
                              'Por favor, configure uma pasta padrão na aba "Configurações" antes de usar o duplo clique.\n\n'
                              'Ou use o botão "Adicionar à Fila de Download" para escolher uma pasta específica.')
            return

        filename = item.data(Qt.ItemDataRole.UserRole)

        if filename in self.downloads:
            QMessageBox.information(self, 'Já na Fila',
                                  f'O arquivo "{filename}" já está na fila de downloads.')
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
        self.statusBar().showMessage(f'✓ Adicionado à fila: {filename}', 3000)

    def start_download_manager(self):
        self.download_manager = DownloadManager(self.max_concurrent)
        self.download_manager.download_started.connect(self.on_download_started)
        self.download_manager.start()
    
    def search_files(self):
        identifier = self.id_input.text().strip()
        
        if not identifier:
            QMessageBox.warning(self, 'Atenção', 'Por favor, insira um identifier.')
            return
            
        self.status_label.setText(f'Buscando arquivos do item: {identifier}...')
        self.file_list.clear()
        self.search_btn.setEnabled(False)
        
        try:
            self.item = ia.get_item(identifier)
            
            if not self.item.exists:
                QMessageBox.warning(self, 'Erro', f'Item "{identifier}" não encontrado.')
                self.status_label.setText('')
                self.search_btn.setEnabled(True)
                return
            
            files = list(self.item.files)
            
            if not files:
                QMessageBox.information(self, 'Info', 'Nenhum arquivo encontrado neste item.')
                self.status_label.setText('')
                self.search_btn.setEnabled(True)
                return
            
            self.all_files = files
                
            for file in files:
                item_widget = QListWidgetItem(f"{file['name']} ({format_size(file.get('size', 0))})")
                item_widget.setData(Qt.ItemDataRole.UserRole, file['name'])
                self.file_list.addItem(item_widget)
            
            self.status_label.setText(f'{len(files)} arquivo(s) encontrado(s).')
            self.download_btn.setEnabled(True)

            self.add_to_recent(identifier)

            # Salva como último identifier usado
            self.last_identifier = identifier
            self.settings.setValue('last_identifier', identifier)
            log(f"[CONFIG] Último identifier salvo: {identifier}")
            
        except Exception as e:
            QMessageBox.critical(self, 'Erro', f'Erro ao buscar arquivos: {str(e)}')
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
            QMessageBox.warning(self, 'Atenção', 'Selecione pelo menos um arquivo.')
            return
        
        dest_folder = QFileDialog.getExistingDirectory(self, 'Escolha a pasta de destino')
        
        if not dest_folder:
            return
        
        identifier = self.id_input.text().strip()
        
        for item in selected_items:
            filename = item.data(Qt.ItemDataRole.UserRole)
            
            if filename in self.downloads:
                QMessageBox.warning(self, 'Atenção', 
                                  f'Arquivo "{filename}" já está na fila.')
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
        
        QMessageBox.information(self, 'Sucesso', 
                              f'{len(selected_items)} arquivo(s) adicionado(s) à fila.')
    
    def add_url_to_queue(self):
        url = self.url_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, 'Atenção', 'Por favor, insira uma URL.')
            return
        
        dest_folder = QFileDialog.getExistingDirectory(self, 'Escolha a pasta de destino')
        
        if not dest_folder:
            return
        
        filename = url.split('/')[-1]

        if filename in self.downloads:
            QMessageBox.warning(self, 'Atenção',
                              f'Arquivo "{filename}" já está na fila.')
            return

        download_item = DownloadItem("", filename, dest_folder, url=url, segments=self.segments_per_file)
        self.downloads[filename] = download_item
        self.add_download_to_table(download_item)
        self.download_manager.add_download(download_item)
        
        QMessageBox.information(self, 'Sucesso', 'Arquivo adicionado à fila.')
        self.url_input.clear()
    
    def add_download_to_table(self, download_item):
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        
        self.download_table.setItem(row, 0, QTableWidgetItem(download_item.filename))
        
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
            size_text = "Calculando..."
        
        log(f"[TABLE] Texto do tamanho: {size_text}")
        
        size_item = QTableWidgetItem(size_text)
        self.download_table.setItem(row, 3, size_item)
        
        speed_item = QTableWidgetItem("0 B/s")
        self.download_table.setItem(row, 4, speed_item)

        # Coluna de conexões
        connections_text = f"{download_item.segments}x" if download_item.segments > 1 else "1x"
        connections_item = QTableWidgetItem(connections_text)
        connections_item.setToolTip(f"{download_item.segments} conexão(ões) simultânea(s)")
        self.download_table.setItem(row, 5, connections_item)

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(2, 2, 2, 2)

        # Texto do botão baseado no status atual
        pause_btn_text = 'Retomar' if download_item.status == DownloadStatus.PAUSED else 'Pausar'
        pause_btn = QPushButton(pause_btn_text)
        pause_btn.setStyleSheet('font-size: 11px; padding: 4px 8px;')
        pause_btn.clicked.connect(lambda: self.toggle_pause(download_item.filename))

        # Botão Cancelar/Recomeçar
        if download_item.status == DownloadStatus.CANCELLED:
            cancel_btn = QPushButton('Recomeçar')
            cancel_btn.setStyleSheet('font-size: 11px; padding: 4px 8px;')
            cancel_btn.clicked.connect(lambda: self.restart_download(download_item.filename))
        else:
            cancel_btn = QPushButton('Cancelar')
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
            
            # Salva automaticamente quando o status muda
            if status in [DownloadStatus.COMPLETED, DownloadStatus.ERROR, DownloadStatus.PAUSED]:
                self.save_downloads()
        
        for row in range(self.download_table.rowCount()):
            if self.download_table.item(row, 0).text() == filename:
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
                        pause_btn.setText('Pausar')
                    elif status == DownloadStatus.PAUSED:
                        pause_btn.setText('Retomar')
                    elif status == DownloadStatus.WAITING:
                        pause_btn.setText('Pausar')

                    # Atualiza botão Cancelar/Recomeçar
                    if status == DownloadStatus.CANCELLED:
                        # Reconecta o botão para recomeçar
                        cancel_btn.setText('Recomeçar')
                        cancel_btn.clicked.disconnect()
                        cancel_btn.clicked.connect(lambda fn=filename: self.restart_download(fn))
                    elif cancel_btn.text() == 'Recomeçar':
                        # Se estava como "Recomeçar" mas não está mais cancelado, volta para "Cancelar"
                        cancel_btn.setText('Cancelar')
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
                            pause_btn.setText('Pausar')
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
                    pause_btn.setText('Retomar')
                    status_item = self.download_table.item(row, 1)
                    status_item.setText(DownloadStatus.PAUSED.value)
                    status_item.setBackground(QColor(255, 255, 224))
                    self.save_downloads()
                    
                elif download_item.status == DownloadStatus.PAUSED:
                    # Retoma a thread
                    download_item.thread.resume()
                    download_item.status = DownloadStatus.DOWNLOADING
                    pause_btn.setText('Pausar')
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

        self.update_status(filename, DownloadStatus.CANCELLED, "Cancelado pelo usuário")

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
                    size_text = "Calculando..."
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

                    pause_btn = QPushButton('Pausar')
                    pause_btn.setStyleSheet('font-size: 11px; padding: 4px 8px;')
                    pause_btn.clicked.connect(lambda: self.toggle_pause(filename))

                    cancel_btn = QPushButton('Cancelar')
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

    def show_context_menu(self, position):
        """Mostra menu de contexto ao clicar com botão direito na tabela"""
        # Pega o item clicado
        item = self.download_table.itemAt(position)
        if not item:
            return

        row = item.row()
        column = item.column()

        # Só mostra o menu se clicar na coluna de mensagem (coluna 7)
        if column == 7:
            msg_item = self.download_table.item(row, 7)
            if msg_item and msg_item.text():
                # Cria o menu
                menu = QApplication.instance().sender().parentWidget().window()
                context_menu = QMenu(menu)

                # Adiciona ação de copiar
                copy_action = context_menu.addAction("📋 Copiar mensagem")
                copy_action.triggered.connect(lambda: self.copy_message_to_clipboard(msg_item.text()))

                # Mostra o menu na posição do cursor
                context_menu.exec(self.download_table.viewport().mapToGlobal(position))

    def copy_message_to_clipboard(self, text):
        """Copia texto para a área de transferência"""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        log(f"[CLIPBOARD] Mensagem copiada: {text[:50]}..." if len(text) > 50 else f"[CLIPBOARD] Mensagem copiada: {text}")

    def show_history(self):
        if not self.recent_identifiers:
            QMessageBox.information(self, 'Histórico', 
                                  'Nenhum identifier no histórico ainda.')
            return
        
        from PyQt6.QtWidgets import QDialog
        
        dialog = QDialog(self)
        dialog.setWindowTitle('Histórico de Identifiers')
        dialog.setGeometry(200, 200, 500, 400)
        
        layout = QVBoxLayout(dialog)
        
        label = QLabel('Clique duas vezes em um identifier para buscá-lo:')
        layout.addWidget(label)
        
        history_list = QListWidget()
        history_list.addItems(self.recent_identifiers)
        history_list.itemDoubleClicked.connect(
            lambda item: self.load_from_history(item.text(), dialog))
        layout.addWidget(history_list)
        
        button_layout = QHBoxLayout()
        
        clear_btn = QPushButton('Limpar Histórico')
        clear_btn.clicked.connect(lambda: self.clear_history(dialog))
        
        close_btn = QPushButton('Fechar')
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
        reply = QMessageBox.question(self, 'Confirmar', 
                                     'Deseja realmente limpar todo o histórico?',
                                     QMessageBox.StandardButton.Yes | 
                                     QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.recent_identifiers = []
            self.save_recent_identifiers()
            self.update_completer()
            dialog.close()
            QMessageBox.information(self, 'Sucesso', 'Histórico limpo com sucesso!')
    
    def update_completer(self):
        self.completer.model().setStringList(self.recent_identifiers)
    
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