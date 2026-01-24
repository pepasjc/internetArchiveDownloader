# Utilitários e funções auxiliares

# Flag global para controlar logs
ENABLE_LOGGING = True

def log(*args, **kwargs):
    """Imprime log apenas se os logs estiverem habilitados"""
    if ENABLE_LOGGING:
        print(*args, **kwargs)

def set_logging_enabled(enabled):
    """Define se os logs devem ser exibidos"""
    global ENABLE_LOGGING
    ENABLE_LOGGING = enabled

def format_size(size):
    """Formata tamanho em bytes para formato legível"""
    try:
        size = float(size)
        if size < 0:
            return "N/A"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
    except:
        return "N/A"
