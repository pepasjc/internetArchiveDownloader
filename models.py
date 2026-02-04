"""Modelos de dados para o Internet Archive Downloader"""

from enum import Enum
from datetime import datetime
import uuid


class DownloadStatus(Enum):
    WAITING = "Aguardando"
    DOWNLOADING = "Baixando"
    PAUSED = "Pausado"
    COMPLETED = "Concluído"
    CANCELLED = "Cancelado"
    ERROR = "Erro"


class DownloadItem:
    def __init__(self, item_id, filename, dest_folder, url=None, segments=1, unique_id=None):
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

        # Tracking information
        self.unique_id = unique_id if unique_id else str(uuid.uuid4())
        self.date_added = datetime.now()
        self.date_completed = None

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
            'total_bytes': str(self.total_bytes),  # Salva como string para evitar overflow
            'unique_id': self.unique_id,
            'date_added': self.date_added.isoformat(),
            'date_completed': self.date_completed.isoformat() if self.date_completed else None
        }

    @staticmethod
    def from_dict(data):
        """Desserializa ao carregar"""
        # Pega unique_id do dict ou gera um novo (para dados antigos)
        unique_id = data.get('unique_id', str(uuid.uuid4()))

        item = DownloadItem(
            data['item_id'],
            data['filename'],
            data['dest_folder'],
            data.get('url'),
            data.get('segments', 1),
            unique_id
        )

        # Restaura status - SEMPRE coloca como pausado ao carregar
        # Para que o usuário precise clicar em "Retomar" manualmente
        # EXCETO para downloads completos, cancelados ou com erro
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

        # Restaura datas (com backwards compatibility)
        try:
            date_added_str = data.get('date_added')
            if date_added_str:
                item.date_added = datetime.fromisoformat(date_added_str)
            else:
                # Para dados antigos sem data, usa data atual
                item.date_added = datetime.now()
        except:
            item.date_added = datetime.now()

        try:
            date_completed_str = data.get('date_completed')
            if date_completed_str:
                item.date_completed = datetime.fromisoformat(date_completed_str)
            else:
                item.date_completed = None
        except:
            item.date_completed = None

        return item
