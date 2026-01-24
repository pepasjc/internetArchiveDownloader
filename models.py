"""Modelos de dados para o Internet Archive Downloader"""

from enum import Enum


class DownloadStatus(Enum):
    WAITING = "Aguardando"
    DOWNLOADING = "Baixando"
    PAUSED = "Pausado"
    COMPLETED = "Concluído"
    CANCELLED = "Cancelado"
    ERROR = "Erro"


class DownloadItem:
    def __init__(self, item_id, filename, dest_folder, url=None, segments=1):
        self.item_id = item_id
        self.filename = filename
        self.dest_folder = dest_folder
        self.url = url
        self.segments = segments  # Número de partes/conexões simultâneas
        self.status = DownloadStatus.WAITING
        self.progress = 0
        self.error_msg = ""
        self.thread = None
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed = 0

    def to_dict(self):
        """Serializa para salvar"""
        return {
            'item_id': self.item_id,
            'filename': self.filename,
            'dest_folder': self.dest_folder,
            'url': self.url,
            'segments': self.segments,
            'status': self.status.value,
            'progress': self.progress,
            'downloaded_bytes': str(self.downloaded_bytes),  # Salva como string para evitar overflow
            'total_bytes': str(self.total_bytes)  # Salva como string para evitar overflow
        }

    @staticmethod
    def from_dict(data):
        """Desserializa ao carregar"""
        item = DownloadItem(
            data['item_id'],
            data['filename'],
            data['dest_folder'],
            data.get('url'),
            data.get('segments', 1)
        )

        # Restaura status - SEMPRE coloca como pausado ao carregar
        # Para que o usuário precise clicar em "Retomar" manualmente
        status_str = data.get('status', 'Pausado')
        if status_str in ['Baixando', 'Aguardando']:
            item.status = DownloadStatus.PAUSED
        elif status_str == 'Pausado':
            item.status = DownloadStatus.PAUSED
        elif status_str == 'Concluído':
            item.status = DownloadStatus.COMPLETED
        elif status_str == 'Erro':
            item.status = DownloadStatus.ERROR
        elif status_str == 'Cancelado':
            item.status = DownloadStatus.CANCELLED
        else:
            item.status = DownloadStatus.PAUSED

        item.progress = data.get('progress', 0)

        # Converte de string para int (evita overflow do JSON)
        try:
            downloaded_str = data.get('downloaded_bytes', '0')
            total_str = data.get('total_bytes', '0')

            # Se ainda vier como int (dados antigos), converte
            if isinstance(downloaded_str, int):
                downloaded_str = str(abs(downloaded_str) if downloaded_str > 0 else 0)
            if isinstance(total_str, int):
                # Se for negativo, pode ser overflow - ignora e busca do IA depois
                total_str = '0' if total_str < 0 else str(total_str)

            item.downloaded_bytes = int(downloaded_str)
            item.total_bytes = int(total_str)
        except:
            item.downloaded_bytes = 0
            item.total_bytes = 0

        return item
