"""Multi-language support for Internet Archive Downloader GUI"""

TRANSLATIONS = {
    'pt-BR': {
        # Window and Status
        'window_title': 'Internet Archive Downloader',
        'status_ready': 'Pronto',

        # Tab names
        'tab_search': '🔍 Buscar no Arquivo',
        'tab_identifier': 'Buscar por Identifier',
        'tab_url': 'Download Direto por URL',
        'tab_downloads': 'Gerenciador de Downloads',
        'tab_settings': '⚙️ Configurações',

        # Search Tab
        'search_title': 'Buscar Conteúdo no Internet Archive',
        'search_label': 'Buscar:',
        'search_placeholder': 'Ex: documentario nasa, musica classica, livro python...',
        'search_type_label': 'Tipo:',
        'search_button': 'Buscar',
        'search_hint': '💡 Dica: Use aspas para frases exatas ("machine learning"), AND/OR para combinar termos, NOT para excluir',
        'search_results_hint': 'Resultados (clique duas vezes em uma linha para carregar os arquivos):',
        'search_previous': '◀ Anterior',
        'search_next': 'Próxima ▶',

        # Media types
        'media_all': 'Todos',
        'media_audio': 'Áudio (audio)',
        'media_video': 'Vídeo (movies)',
        'media_text': 'Texto (texts)',
        'media_image': 'Imagens (image)',
        'media_software': 'Software (software)',
        'media_web': 'Web (web)',
        'media_collection': 'Coleções (collection)',
        'media_data': 'Dados (data)',

        # Search results table columns
        'col_title': 'Título',
        'col_identifier': 'Identifier',
        'col_type': 'Tipo',
        'col_downloads': 'Downloads',
        'col_matching_files': 'Arquivos',
        'col_description': 'Descrição',

        # Search results messages
        'searching_for': 'Buscando por: {query}...',
        'no_results': 'Nenhum resultado encontrado.',
        'no_results_found': 'Nenhum item encontrado para "{query}".',
        'results_found': '{count} resultado(s) encontrado(s). Duplo clique para carregar arquivos.',
        'page_info': 'Página {current} de {total} (mostrando {start}-{end} de {count})',
        'search_error': 'Erro na busca.',

        # Identifier Tab
        'identifier_label': 'Identifier:',
        'identifier_placeholder': 'Ex: rick-astley-never-gonna-give-you-up',
        'search_files_button': 'Buscar Arquivos',
        'history_button': '📋 Histórico',
        'history_tooltip': 'Ver identifiers recentes',
        'filter_label': '🔍 Filtrar:',
        'filter_placeholder': 'Digite para filtrar arquivos...',
        'clear_filter_tooltip': 'Limpar filtro',
        'files_label': 'Arquivos disponíveis (selecione os que deseja baixar):',
        'double_click_hint': '💡 Dica: Clique duas vezes em um arquivo para adicioná-lo à fila usando a pasta padrão',
        'add_to_queue_button': 'Adicionar à Fila de Download',

        # Identifier messages
        'searching_item': 'Buscando arquivos do item: {identifier}...',
        'item_not_found': 'Item "{identifier}" não encontrado.',
        'no_files_found': 'Nenhum arquivo encontrado neste item.',
        'files_found': '{count} arquivo(s) encontrado(s).',

        # URL Tab
        'url_label': 'Cole a URL completa do arquivo:',
        'url_placeholder': 'Ex: https://archive.org/download/identifier/filename.ext',
        'url_format': 'Formato: https://archive.org/download/{identifier}/{filename}',
        'direct_download_button': 'Adicionar à Fila de Download',

        # Download Manager Tab
        'dm_col_file': 'Arquivo',
        'dm_col_status': 'Status',
        'dm_col_progress': 'Progresso',
        'dm_col_size': 'Tamanho',
        'dm_col_speed': 'Velocidade',
        'dm_col_connections': 'Conexões',
        'dm_col_actions': 'Ações',
        'dm_col_message': 'Mensagem',
        'dm_clear_completed': 'Limpar Concluídos',
        'dm_cancel_all': 'Cancelar Todos',

        # Download actions
        'action_pause': 'Pausar',
        'action_resume': 'Retomar',
        'action_cancel': 'Cancelar',
        'action_restart': 'Recomeçar',
        'action_remove': 'Remover',
        'add_url_button': 'Adicionar URL',
        'add_url_title': 'Adicionar Download por URL',
        'add_url_prompt': 'Digite a URL do arquivo para download:',

        # Warnings
        'warn_remove_active': 'Não é possível remover um download ativo. Cancele ou aguarde a conclusão primeiro.',

        # Settings Tab
        'settings_title': 'Configurações Gerais',

        # Account section
        'account_section': '🔐 Conta do Internet Archive',
        'account_description': 'Configure sua conta para acessar recursos privados e fazer uploads:',
        'account_configured': '✓ Conta configurada',
        'account_configured_file': '✓ Conta configurada (arquivo encontrado)',
        'account_not_configured': '✗ Nenhuma conta configurada',
        'account_unknown': '? Status desconhecido',
        'account_email': 'Email:',
        'account_email_placeholder': 'seu-email@exemplo.com',
        'account_password': 'Senha:',
        'account_password_placeholder': 'sua-senha',
        'account_login': 'Fazer Login',
        'account_logout': 'Resetar Credenciais',
        'account_note': '💡 Nota: As credenciais são armazenadas localmente em ~/.config/ia.ini',

        # Folder section
        'folder_section': '📁 Pasta Padrão para Downloads',
        'folder_description': 'Pasta onde os arquivos serão salvos ao clicar 2x na lista:',
        'folder_placeholder': 'Nenhuma pasta padrão configurada',
        'folder_choose': 'Escolher Pasta...',
        'folder_clear': 'Limpar',
        'folder_dialog_title': 'Escolha a pasta padrão para downloads',

        # Performance section
        'perf_section': '⚡ Performance de Downloads',
        'perf_concurrent': 'Downloads simultâneos:',
        'perf_concurrent_tooltip': 'Quantos arquivos podem ser baixados ao mesmo tempo',
        'perf_connections': 'Conexões por arquivo:',
        'perf_connections_tooltip': 'Número de conexões simultâneas para cada arquivo (download acelerado)',
        'perf_connections_note_tooltip': 'Número de conexões simultâneas para cada arquivo (download acelerado)\n\nNOTA: Esta configuração só afeta downloads NOVOS.\nDownloads em andamento mantêm o número de conexões original.',
        'perf_note': '💡 Mais conexões por arquivo = download mais rápido (útil quando o servidor limita a velocidade por conexão)',

        # Debug section
        'debug_section': '🐛 Debug e Logs',
        'debug_logging': 'Exibir logs detalhados no console',
        'debug_note': '💡 Desabilite os logs para melhorar a performance em downloads muito grandes',

        # Language section
        'language_section': '🌐 Idioma / Language',
        'language_label': 'Idioma da interface:',
        'language_portuguese': 'Português (Brasil)',
        'language_english': 'English (US)',
        'language_note': '💡 Nota: O aplicativo será reiniciado para aplicar o novo idioma',

        # Messages and Dialogs
        'warning': 'Atenção',
        'error': 'Erro',
        'success': 'Sucesso',
        'info': 'Informação',
        'confirm': 'Confirmar',
        'no_results_title': 'Sem Resultados',

        # Warning messages
        'warn_search_empty': 'Por favor, insira um termo de busca.',
        'warn_identifier_empty': 'Por favor, insira um identifier.',
        'warn_url_empty': 'Por favor, insira uma URL.',
        'warn_no_files_selected': 'Selecione pelo menos um arquivo.',
        'warn_already_queued': 'O arquivo "{filename}" já está na fila de downloads.',
        'warn_file_already_queued': 'Arquivo "{filename}" já está na fila.',
        'warn_no_default_folder': 'Por favor, configure uma pasta padrão na aba "Configurações" antes de usar o duplo clique.\n\nOu use o botão "Adicionar à Fila de Download" para escolher uma pasta específica.',
        'warn_account_fill': 'Por favor, preencha email e senha.',

        # Info messages
        'info_already_queued': 'Já na Fila',
        'info_added_to_queue': '✓ Adicionado à fila: {filename}',
        'info_files_added': '{count} arquivo(s) adicionado(s) à fila.',
        'info_file_added': 'Arquivo adicionado à fila.',
        'info_no_default_folder_title': 'Pasta Padrão não Configurada',

        # Error messages
        'error_search': 'Erro ao buscar: {error}',
        'error_load_files': 'Erro ao buscar arquivos: {error}',
        'error_login': 'Erro ao fazer login:\n{error}\n\nVerifique suas credenciais e tente novamente.',
        'error_logout': 'Erro ao remover credenciais:\n{error}',

        # Success messages
        'success_login': 'Login realizado com sucesso!\n\nSuas credenciais foram salvas.',
        'success_logout': 'Credenciais removidas com sucesso!',
        'success_logout_none': 'Nenhuma configuração encontrada para remover.',
        'success_history_cleared': 'Histórico limpo com sucesso!',

        # Confirm messages
        'confirm_logout': 'Deseja realmente resetar suas credenciais do Internet Archive?\n\nIsso removerá o arquivo de configuração local.',
        'confirm_clear_history': 'Deseja realmente limpar todo o histórico?',

        # History dialog
        'history_title': 'Histórico de Identifiers',
        'history_empty': 'Nenhum identifier no histórico ainda.',
        'history_instruction': 'Clique duas vezes em um identifier para buscá-lo:',
        'history_clear': 'Limpar Histórico',
        'history_close': 'Fechar',

        # Search history
        'search_history_button': '📜 Histórico',
        'search_history_title': 'Histórico de Buscas',
        'search_history_empty': 'Nenhuma busca no histórico ainda.',
        'search_history_instruction': 'Clique duas vezes em uma busca para executá-la:',
        'confirm_clear_search_history': 'Deseja realmente limpar todo o histórico de buscas?',
        'success_search_history_cleared': 'Histórico de buscas limpo com sucesso!',

        # Matching files dialog
        'matching_files_title': 'Arquivos Correspondentes',
        'no_matching_files': 'Nenhum arquivo corresponde aos termos da busca.',
        'matching_files_instruction': 'Encontrados {count} arquivo(s) correspondente(s). Clique em "Adicionar" para baixar ou "Ver Todos" para visualizar todos os arquivos do item.',
        'loading_matching_files': 'Carregando arquivos correspondentes...',
        'error_loading_files': 'Erro ao carregar arquivos:\n{error}',
        'col_filename': 'Nome do Arquivo',
        'col_size': 'Tamanho',
        'col_format': 'Formato',
        'col_action': 'Ação',
        'add_to_queue': '+ Adicionar',
        'view_all_files': '📋 Ver Todos os Arquivos',
        'close': 'Fechar',

        # Context menu
        'context_copy': '📋 Copiar mensagem',
        'context_open_file': '📂 Abrir arquivo',
        'context_open_folder': '📁 Abrir pasta',
        'context_show_matching_files': '🔍 Mostrar Arquivos Correspondentes',

        # Tooltips
        'tooltip_connections': '{count} conexão(ões) simultânea(s)',
        'tooltip_id': 'ID',
        'tooltip_added': 'Adicionado',
        'tooltip_completed': 'Concluído',

        # Download status
        'status_waiting': 'Aguardando',
        'status_downloading': 'Baixando',
        'status_paused': 'Pausado',
        'status_completed': 'Concluído',
        'status_error': 'Erro',
        'status_cancelled': 'Cancelado',
        'status_cancelled_by_user': 'Cancelado pelo usuário',

        # Misc
        'calculating': 'Calculando...',
        'no_title': 'Sem título',
        'no_description': 'Sem descrição',
    },

    'en': {
        # Window and Status
        'window_title': 'Internet Archive Downloader',
        'status_ready': 'Ready',

        # Tab names
        'tab_search': '🔍 Search Archive',
        'tab_identifier': 'Search by Identifier',
        'tab_url': 'Direct URL Download',
        'tab_downloads': 'Download Manager',
        'tab_settings': '⚙️ Settings',

        # Search Tab
        'search_title': 'Search Content on Internet Archive',
        'search_label': 'Search:',
        'search_placeholder': 'Ex: nasa documentary, classical music, python book...',
        'search_type_label': 'Type:',
        'search_button': 'Search',
        'search_hint': '💡 Tip: Use quotes for exact phrases ("machine learning"), AND/OR to combine terms, NOT to exclude',
        'search_results_hint': 'Results (double-click a row to load files):',
        'search_previous': '◀ Previous',
        'search_next': 'Next ▶',

        # Media types
        'media_all': 'All',
        'media_audio': 'Audio (audio)',
        'media_video': 'Video (movies)',
        'media_text': 'Text (texts)',
        'media_image': 'Images (image)',
        'media_software': 'Software (software)',
        'media_web': 'Web (web)',
        'media_collection': 'Collections (collection)',
        'media_data': 'Data (data)',

        # Search results table columns
        'col_title': 'Title',
        'col_identifier': 'Identifier',
        'col_type': 'Type',
        'col_downloads': 'Downloads',
        'col_matching_files': 'Files',
        'col_description': 'Description',

        # Search results messages
        'searching_for': 'Searching for: {query}...',
        'no_results': 'No results found.',
        'no_results_found': 'No items found for "{query}".',
        'results_found': '{count} result(s) found. Double-click to load files.',
        'page_info': 'Page {current} of {total} (showing {start}-{end} of {count})',
        'search_error': 'Search error.',

        # Identifier Tab
        'identifier_label': 'Identifier:',
        'identifier_placeholder': 'Ex: rick-astley-never-gonna-give-you-up',
        'search_files_button': 'Search Files',
        'history_button': '📋 History',
        'history_tooltip': 'View recent identifiers',
        'filter_label': '🔍 Filter:',
        'filter_placeholder': 'Type to filter files...',
        'clear_filter_tooltip': 'Clear filter',
        'files_label': 'Available files (select the ones you want to download):',
        'double_click_hint': '💡 Tip: Double-click a file to add it to the queue using the default folder',
        'add_to_queue_button': 'Add to Download Queue',

        # Identifier messages
        'searching_item': 'Searching files for item: {identifier}...',
        'item_not_found': 'Item "{identifier}" not found.',
        'no_files_found': 'No files found for this item.',
        'files_found': '{count} file(s) found.',

        # URL Tab
        'url_label': 'Paste the complete file URL:',
        'url_placeholder': 'Ex: https://archive.org/download/identifier/filename.ext',
        'url_format': 'Format: https://archive.org/download/{identifier}/{filename}',
        'direct_download_button': 'Add to Download Queue',

        # Download Manager Tab
        'dm_col_file': 'File',
        'dm_col_status': 'Status',
        'dm_col_progress': 'Progress',
        'dm_col_size': 'Size',
        'dm_col_speed': 'Speed',
        'dm_col_connections': 'Connections',
        'dm_col_actions': 'Actions',
        'dm_col_message': 'Message',
        'dm_clear_completed': 'Clear Completed',
        'dm_cancel_all': 'Cancel All',

        # Download actions
        'action_pause': 'Pause',
        'action_resume': 'Resume',
        'action_cancel': 'Cancel',
        'action_restart': 'Restart',
        'action_remove': 'Remove',
        'add_url_button': 'Add URL',
        'add_url_title': 'Add Download by URL',
        'add_url_prompt': 'Enter the file URL to download:',

        # Warnings
        'warn_remove_active': 'Cannot remove an active download. Please cancel or wait for completion first.',

        # Settings Tab
        'settings_title': 'General Settings',

        # Account section
        'account_section': '🔐 Internet Archive Account',
        'account_description': 'Configure your account to access private resources and upload:',
        'account_configured': '✓ Account configured',
        'account_configured_file': '✓ Account configured (file found)',
        'account_not_configured': '✗ No account configured',
        'account_unknown': '? Unknown status',
        'account_email': 'Email:',
        'account_email_placeholder': 'your-email@example.com',
        'account_password': 'Password:',
        'account_password_placeholder': 'your-password',
        'account_login': 'Login',
        'account_logout': 'Reset Credentials',
        'account_note': '💡 Note: Credentials are stored locally at ~/.config/ia.ini',

        # Folder section
        'folder_section': '📁 Default Download Folder',
        'folder_description': 'Folder where files will be saved when double-clicking the list:',
        'folder_placeholder': 'No default folder configured',
        'folder_choose': 'Choose Folder...',
        'folder_clear': 'Clear',
        'folder_dialog_title': 'Choose default download folder',

        # Performance section
        'perf_section': '⚡ Download Performance',
        'perf_concurrent': 'Concurrent downloads:',
        'perf_concurrent_tooltip': 'How many files can be downloaded at the same time',
        'perf_connections': 'Connections per file:',
        'perf_connections_tooltip': 'Number of simultaneous connections for each file (accelerated download)',
        'perf_connections_note_tooltip': 'Number of simultaneous connections for each file (accelerated download)\n\nNOTE: This setting only affects NEW downloads.\nOngoing downloads keep their original connection count.',
        'perf_note': '💡 More connections per file = faster download (useful when the server limits speed per connection)',

        # Debug section
        'debug_section': '🐛 Debug and Logs',
        'debug_logging': 'Show detailed logs in console',
        'debug_note': '💡 Disable logs to improve performance on very large downloads',

        # Language section
        'language_section': '🌐 Language / Idioma',
        'language_label': 'Interface language:',
        'language_portuguese': 'Português (Brasil)',
        'language_english': 'English (US)',
        'language_note': '💡 Note: The application will restart to apply the new language',

        # Messages and Dialogs
        'warning': 'Warning',
        'error': 'Error',
        'success': 'Success',
        'info': 'Information',
        'confirm': 'Confirm',
        'no_results_title': 'No Results',

        # Warning messages
        'warn_search_empty': 'Please enter a search term.',
        'warn_identifier_empty': 'Please enter an identifier.',
        'warn_url_empty': 'Please enter a URL.',
        'warn_no_files_selected': 'Select at least one file.',
        'warn_already_queued': 'File "{filename}" is already in the download queue.',
        'warn_file_already_queued': 'File "{filename}" is already in the queue.',
        'warn_no_default_folder': 'Please configure a default folder in the "Settings" tab before using double-click.\n\nOr use the "Add to Download Queue" button to choose a specific folder.',
        'warn_account_fill': 'Please fill in email and password.',

        # Info messages
        'info_already_queued': 'Already in Queue',
        'info_added_to_queue': '✓ Added to queue: {filename}',
        'info_files_added': '{count} file(s) added to queue.',
        'info_file_added': 'File added to queue.',
        'info_no_default_folder_title': 'Default Folder Not Configured',

        # Error messages
        'error_search': 'Search error: {error}',
        'error_load_files': 'Error loading files: {error}',
        'error_login': 'Login error:\n{error}\n\nCheck your credentials and try again.',
        'error_logout': 'Error removing credentials:\n{error}',

        # Success messages
        'success_login': 'Login successful!\n\nYour credentials have been saved.',
        'success_logout': 'Credentials removed successfully!',
        'success_logout_none': 'No configuration found to remove.',
        'success_history_cleared': 'History cleared successfully!',

        # Confirm messages
        'confirm_logout': 'Do you really want to reset your Internet Archive credentials?\n\nThis will remove the local configuration file.',
        'confirm_clear_history': 'Do you really want to clear all history?',

        # History dialog
        'history_title': 'Identifier History',
        'history_empty': 'No identifiers in history yet.',
        'history_instruction': 'Double-click an identifier to search for it:',
        'history_clear': 'Clear History',
        'history_close': 'Close',

        # Search history
        'search_history_button': '📜 History',
        'search_history_title': 'Search History',
        'search_history_empty': 'No searches in history yet.',
        'search_history_instruction': 'Double-click a search to execute it:',
        'confirm_clear_search_history': 'Do you really want to clear all search history?',
        'success_search_history_cleared': 'Search history cleared successfully!',

        # Matching files dialog
        'matching_files_title': 'Matching Files',
        'no_matching_files': 'No files match the search terms.',
        'matching_files_instruction': 'Found {count} matching file(s). Click "Add" to download or "View All" to see all files in the item.',
        'loading_matching_files': 'Loading matching files...',
        'error_loading_files': 'Error loading files:\n{error}',
        'col_filename': 'Filename',
        'col_size': 'Size',
        'col_format': 'Format',
        'col_action': 'Action',
        'add_to_queue': '+ Add',
        'view_all_files': '📋 View All Files',
        'close': 'Close',

        # Context menu
        'context_copy': '📋 Copy message',
        'context_open_file': '📂 Open File',
        'context_open_folder': '📁 Open Folder',
        'context_show_matching_files': '🔍 Show Matching Files',

        # Tooltips
        'tooltip_connections': '{count} simultaneous connection(s)',
        'tooltip_id': 'ID',
        'tooltip_added': 'Added',
        'tooltip_completed': 'Completed',

        # Download status
        'status_waiting': 'Waiting',
        'status_downloading': 'Downloading',
        'status_paused': 'Paused',
        'status_completed': 'Completed',
        'status_error': 'Error',
        'status_cancelled': 'Cancelled',
        'status_cancelled_by_user': 'Cancelled by user',

        # Misc
        'calculating': 'Calculating...',
        'no_title': 'No title',
        'no_description': 'No description',
    }
}


def get_translation(lang, key, **kwargs):
    """
    Get a translated string for the given language and key.
    Supports formatting with kwargs (e.g., {filename}, {count}, etc.)

    Args:
        lang: Language code ('pt-BR' or 'en')
        key: Translation key
        **kwargs: Optional format parameters

    Returns:
        Translated and formatted string
    """
    # Default to Portuguese if language not found
    if lang not in TRANSLATIONS:
        lang = 'pt-BR'

    # Get the translation
    text = TRANSLATIONS[lang].get(key, TRANSLATIONS['pt-BR'].get(key, key))

    # Format with kwargs if provided
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass  # If a format key is missing, return unformatted

    return text


class Translator:
    """Helper class for translations"""

    def __init__(self, lang='pt-BR'):
        self.lang = lang

    def set_language(self, lang):
        """Change the current language"""
        if lang in TRANSLATIONS:
            self.lang = lang

    def get(self, key, **kwargs):
        """Get a translated string"""
        return get_translation(self.lang, key, **kwargs)

    def __call__(self, key, **kwargs):
        """Shorthand for get()"""
        return self.get(key, **kwargs)
