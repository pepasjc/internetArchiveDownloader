import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QListWidget,
                             QLabel, QFileDialog, QProgressBar, QMessageBox,
                             QTabWidget, QListWidgetItem, QSpinBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QAbstractItemView, QCompleter, QMenu)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition, QSettings
from PyQt6.QtGui import QColor, QAction, QClipboard
import internetarchive as ia
from pathlib import Path
from enum import Enum
from queue import Queue
import time
import json
import os
import requests


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


class SegmentDownloadThread(QThread):
    """Thread para baixar um segmento específico do arquivo"""
    progress_updated = pyqtSignal(int, int)  # segment_id, bytes_downloaded
    segment_completed = pyqtSignal(int)  # segment_id
    segment_error = pyqtSignal(int, str)  # segment_id, error_msg

    def __init__(self, segment_id, url, dest_path, start_byte, end_byte, progress_dict, progress_mutex):
        super().__init__()
        self.segment_id = segment_id
        self.url = url
        self.dest_path = dest_path
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.is_cancelled = False
        self.is_paused = False
        self.mutex = QMutex()
        self.pause_condition = QWaitCondition()
        self.downloaded = 0
        # Compartilha o dict de progresso diretamente
        self.progress_dict = progress_dict
        self.progress_mutex = progress_mutex
        self.completed = False
        self.error_msg = None

    def run(self):
        try:
            print(f"[SEGMENT {self.segment_id}] Iniciando download...")
            session = ia.get_session()
            print(f"[SEGMENT {self.segment_id}] Sessão obtida")

            # Verifica se já existe arquivo parcial deste segmento
            segment_file = f"{self.dest_path}.part{self.segment_id}"
            if os.path.exists(segment_file):
                self.downloaded = os.path.getsize(segment_file)
                print(f"[SEGMENT {self.segment_id}] Arquivo parcial: {self.downloaded} bytes")

            # Se já baixou tudo, não precisa fazer nada
            total_segment_size = self.end_byte - self.start_byte + 1
            if self.downloaded >= total_segment_size:
                print(f"[SEGMENT {self.segment_id}] Já completo!")
                self.completed = True
                return

            # Range request para este segmento
            current_start = self.start_byte + self.downloaded
            headers = {'Range': f'bytes={current_start}-{self.end_byte}'}

            print(f"[SEGMENT {self.segment_id}] Fazendo request: {headers}")
            response = session.get(self.url, stream=True, timeout=30, headers=headers)
            response.raise_for_status()
            print(f"[SEGMENT {self.segment_id}] Response OK: {response.status_code}")

            # Abre em modo append se estiver continuando
            mode = 'ab' if self.downloaded > 0 else 'wb'

            with open(segment_file, mode) as f:
                chunk_count = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if self.is_cancelled:
                        print(f"[SEGMENT {self.segment_id}] Cancelado")
                        return

                    self.mutex.lock()
                    while self.is_paused and not self.is_cancelled:
                        self.pause_condition.wait(self.mutex)
                    self.mutex.unlock()

                    if chunk:
                        f.write(chunk)
                        self.downloaded += len(chunk)
                        chunk_count += 1

                        # Atualiza o dict compartilhado a cada 50 chunks (aprox a cada 400KB)
                        if chunk_count % 50 == 0:
                            self.progress_mutex.lock()
                            self.progress_dict[self.segment_id] = self.downloaded
                            self.progress_mutex.unlock()

                        if chunk_count % 100 == 0:  # Log a cada 100 chunks
                            print(f"[SEGMENT {self.segment_id}] Progresso: {self.downloaded} bytes")

                # Atualiza progresso final
                self.progress_mutex.lock()
                self.progress_dict[self.segment_id] = self.downloaded
                self.progress_mutex.unlock()

            print(f"[SEGMENT {self.segment_id}] Saiu do loop de download. Cancelado: {self.is_cancelled}")

            if not self.is_cancelled:
                print(f"[SEGMENT {self.segment_id}] Completo! Total: {self.downloaded} bytes")
                self.completed = True
                print(f"[SEGMENT {self.segment_id}] Marcado como completo: completed={self.completed}")
            else:
                print(f"[SEGMENT {self.segment_id}] NÃO marcado como completo pois foi cancelado")

        except Exception as e:
            print(f"[SEGMENT {self.segment_id}] ERRO: {str(e)}")
            import traceback
            traceback.print_exc()
            if not self.is_cancelled:
                self.error_msg = str(e)
                print(f"[SEGMENT {self.segment_id}] Erro armazenado: {self.error_msg}")

        print(f"[SEGMENT {self.segment_id}] Thread finalizando. completed={self.completed}, error_msg={self.error_msg}, cancelled={self.is_cancelled}")

    def cancel(self):
        self.is_cancelled = True
        self.resume()

    def pause(self):
        self.mutex.lock()
        self.is_paused = True
        self.mutex.unlock()

    def resume(self):
        self.mutex.lock()
        self.is_paused = False
        self.pause_condition.wakeAll()
        self.mutex.unlock()


class SingleDownloadThread(QThread):
    progress_updated = pyqtSignal(str, dict)
    status_changed = pyqtSignal(str, DownloadStatus, str)

    def __init__(self, download_item):
        super().__init__()
        self.download_item = download_item
        self.is_cancelled = False
        self.is_paused = False
        self.mutex = QMutex()
        self.pause_condition = QWaitCondition()
        self.segment_threads = []
        
    def run(self):
        try:
            self.status_changed.emit(self.download_item.filename,
                                    DownloadStatus.DOWNLOADING, "")

            print(f"[THREAD] Iniciando download: {self.download_item.filename}")
            print(f"[THREAD] Segmentos: {self.download_item.segments}")

            if self.download_item.url:
                parts = self.download_item.url.split('/')
                if 'archive.org' in self.download_item.url and 'download' in parts:
                    download_idx = parts.index('download')
                    identifier = parts[download_idx + 1]
                    filename = '/'.join(parts[download_idx + 2:])

                    print(f"[THREAD] Usando identifier: {identifier}, filename: {filename}")
                    item = ia.get_item(identifier)
                    self._download_with_progress(item, filename)
                else:
                    raise Exception("URL inválida - apenas URLs do archive.org são suportadas")
            else:
                print(f"[THREAD] Usando item_id: {self.download_item.item_id}")
                item = ia.get_item(self.download_item.item_id)
                self._download_with_progress(item, self.download_item.filename)

            if not self.is_cancelled:
                self.status_changed.emit(self.download_item.filename,
                                        DownloadStatus.COMPLETED, "")

        except Exception as e:
            print(f"[THREAD ERROR] {str(e)}")
            import traceback
            traceback.print_exc()
            if not self.is_cancelled:
                self.status_changed.emit(self.download_item.filename,
                                        DownloadStatus.ERROR, str(e))
    
    def _download_with_progress(self, item, filename):
        dest_path = os.path.join(self.download_item.dest_folder, filename)

        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        else:
            os.makedirs(self.download_item.dest_folder, exist_ok=True)

        file_info = None
        for f in item.files:
            if f['name'] == filename:
                file_info = f
                break

        if not file_info:
            raise Exception("Arquivo não encontrado no item")

        # Pega o tamanho total do metadata do arquivo - força Python int (ilimitado)
        total_size = int(file_info.get('size', 0))

        print(f"[DOWNLOAD] Total size: {total_size} bytes ({self._format_size(total_size)})")
        print(f"[DOWNLOAD] Segmentos configurados: {self.download_item.segments}")

        # Verifica se já existe arquivo completo
        if os.path.exists(dest_path):
            downloaded = int(os.path.getsize(dest_path))
            if downloaded >= total_size:
                self.progress_updated.emit(
                    self.download_item.filename,
                    {
                        'progress': 100,
                        'downloaded': downloaded,
                        'total': total_size,
                        'speed': 0.0
                    }
                )
                return

        identifier = item.identifier
        download_url = f"https://archive.org/download/{identifier}/{filename}"

        # Se usar apenas 1 segmento, usa download simples
        if self.download_item.segments == 1:
            self._download_single_segment(download_url, dest_path, total_size)
        else:
            self._download_multi_segment(download_url, dest_path, total_size)

    def _download_single_segment(self, download_url, dest_path, total_size):
        """Download tradicional (1 conexão)"""
        session = ia.get_session()

        # Verifica se já existe arquivo parcial
        downloaded = 0
        if os.path.exists(dest_path):
            downloaded = int(os.path.getsize(dest_path))

        # Emite progresso inicial
        initial_progress = int((downloaded * 100) // total_size) if total_size > 0 else 0
        self.progress_updated.emit(
            self.download_item.filename,
            {
                'progress': initial_progress,
                'downloaded': downloaded,
                'total': total_size,
                'speed': 0.0
            }
        )

        try:
            headers = {}
            if downloaded > 0:
                headers['Range'] = f'bytes={downloaded}-'

            response = session.get(download_url, stream=True, timeout=30, headers=headers)

            if downloaded > 0 and response.status_code not in [200, 206]:
                downloaded = 0
                response = session.get(download_url, stream=True, timeout=30)

            response.raise_for_status()

            start_time = time.time()
            last_update_time = start_time
            last_downloaded = downloaded

            mode = 'ab' if downloaded > 0 and response.status_code == 206 else 'wb'
            if mode == 'wb':
                downloaded = 0

            with open(dest_path, mode) as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.is_cancelled:
                        return

                    self.mutex.lock()
                    while self.is_paused and not self.is_cancelled:
                        self.pause_condition.wait(self.mutex)
                        if not self.is_paused:
                            start_time = time.time()
                            last_update_time = start_time
                            last_downloaded = downloaded
                    self.mutex.unlock()

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        current_time = time.time()
                        if current_time - last_update_time >= 0.5:
                            time_diff = current_time - last_update_time
                            bytes_diff = downloaded - last_downloaded
                            speed = bytes_diff / time_diff if time_diff > 0 else 0
                            progress = int((downloaded * 100) // total_size) if total_size > 0 else 0

                            self.progress_updated.emit(
                                self.download_item.filename,
                                {
                                    'progress': progress,
                                    'downloaded': downloaded,
                                    'total': total_size,
                                    'speed': float(speed)
                                }
                            )

                            last_update_time = current_time
                            last_downloaded = downloaded

            if not self.is_cancelled:
                self.progress_updated.emit(
                    self.download_item.filename,
                    {
                        'progress': 100,
                        'downloaded': downloaded,
                        'total': total_size,
                        'speed': 0.0
                    }
                )

        except requests.exceptions.RequestException as e:
            raise Exception(f"Erro de rede: {str(e)}")

    def _download_multi_segment(self, download_url, dest_path, total_size):
        """Download acelerado (múltiplas conexões simultâneas)"""
        num_segments = self.download_item.segments
        segment_size = total_size // num_segments

        print(f"[MULTI-SEGMENT] Dividindo arquivo em {num_segments} partes de ~{self._format_size(segment_size)}")
        print(f"[MULTI-SEGMENT] URL: {download_url}")
        print(f"[MULTI-SEGMENT] Dest: {dest_path}")

        # Verifica se já existe arquivo final completo
        if os.path.exists(dest_path) and os.path.getsize(dest_path) >= total_size:
            self.progress_updated.emit(
                self.download_item.filename,
                {'progress': 100, 'downloaded': total_size, 'total': total_size, 'speed': 0.0}
            )
            return

        # Cria threads para cada segmento
        self.segment_threads = []
        self.segment_progress = {}
        self.segment_progress_mutex = QMutex()

        # Emite progresso inicial com tamanho total
        initial_downloaded = 0
        self.progress_updated.emit(
            self.download_item.filename,
            {
                'progress': 0,
                'downloaded': initial_downloaded,
                'total': total_size,
                'speed': 0.0
            }
        )

        print(f"[MULTI-SEGMENT] Criando {num_segments} threads...")
        for i in range(num_segments):
            start_byte = i * segment_size
            end_byte = ((i + 1) * segment_size - 1) if i < num_segments - 1 else (total_size - 1)

            print(f"[MULTI-SEGMENT] Segmento {i}: bytes {start_byte}-{end_byte}")

            # Inicializa progresso
            self.segment_progress[i] = 0

            # Verifica se já existe arquivo parcial deste segmento
            segment_file = f"{dest_path}.part{i}"
            if os.path.exists(segment_file):
                self.segment_progress[i] = os.path.getsize(segment_file)
                print(f"[MULTI-SEGMENT] Segmento {i} parcial encontrado: {self.segment_progress[i]} bytes")

            # Cria thread passando o dict compartilhado
            thread = SegmentDownloadThread(i, download_url, dest_path, start_byte, end_byte,
                                          self.segment_progress, self.segment_progress_mutex)
            self.segment_threads.append(thread)

        # Inicia todas as threads
        print(f"[MULTI-SEGMENT] Iniciando threads...")
        for i, thread in enumerate(self.segment_threads):
            thread.start()
            print(f"[MULTI-SEGMENT] Thread {i} iniciada")

        # Monitora progresso
        start_time = time.time()
        last_update_time = start_time
        last_total_downloaded = sum(self.segment_progress.values())

        print(f"[MULTI-SEGMENT] Entrando no loop de monitoramento...")
        loop_count = 0
        max_loops = 100000  # Previne loop infinito (aprox 2.7 horas para um download)

        while loop_count < max_loops and any(thread.isRunning() for thread in self.segment_threads):
            loop_count += 1
            if loop_count % 50 == 0:  # Log a cada 5 segundos
                running = sum(1 for t in self.segment_threads if t.isRunning())
                completed = sum(1 for t in self.segment_threads if t.completed)
                errors = sum(1 for t in self.segment_threads if t.error_msg)
                print(f"[MULTI-SEGMENT] Loop {loop_count}: {running}/{num_segments} threads rodando, completos: {completed}, erros: {errors}")

            if self.is_cancelled:
                print(f"[MULTI-SEGMENT] Cancelando todas as threads...")
                for thread in self.segment_threads:
                    thread.cancel()
                for thread in self.segment_threads:
                    thread.wait()
                return

            # Verifica pausar/retomar
            self.mutex.lock()
            if self.is_paused:
                print(f"[MULTI-SEGMENT] Pausando...")
                for thread in self.segment_threads:
                    thread.pause()
                self.pause_condition.wait(self.mutex)
                print(f"[MULTI-SEGMENT] Retomando...")
                for thread in self.segment_threads:
                    thread.resume()
                start_time = time.time()
                last_update_time = start_time
                last_total_downloaded = sum(self.segment_progress.values())
            self.mutex.unlock()

            # Atualiza progresso
            current_time = time.time()
            if current_time - last_update_time >= 0.5:
                # Lê o progresso total de forma thread-safe
                self.segment_progress_mutex.lock()
                total_downloaded = sum(self.segment_progress.values())
                self.segment_progress_mutex.unlock()

                time_diff = current_time - last_update_time
                bytes_diff = total_downloaded - last_total_downloaded
                speed = bytes_diff / time_diff if time_diff > 0 else 0
                progress = int((total_downloaded * 100) // total_size) if total_size > 0 else 0

                self.progress_updated.emit(
                    self.download_item.filename,
                    {
                        'progress': progress,
                        'downloaded': total_downloaded,
                        'total': total_size,
                        'speed': float(speed)
                    }
                )

                last_update_time = current_time
                last_total_downloaded = total_downloaded

            time.sleep(0.1)

        # Aguarda threads terminarem completamente
        print(f"[MULTI-SEGMENT] Saiu do loop. Aguardando threads...")
        for i, thread in enumerate(self.segment_threads):
            if thread.isRunning():
                print(f"[MULTI-SEGMENT] Aguardando thread {i}...")
                thread.wait(5000)  # Aguarda até 5 segundos

        # Debug: mostra status detalhado de cada thread
        print(f"[MULTI-SEGMENT] Status detalhado das threads:")
        for i, thread in enumerate(self.segment_threads):
            print(f"  Thread {i}: running={thread.isRunning()}, completed={thread.completed}, cancelled={thread.is_cancelled}, error={thread.error_msg}")

        # Conta completos e erros
        segments_completed = sum(1 for t in self.segment_threads if t.completed)
        print(f"[MULTI-SEGMENT] Todas threads terminaram. Segmentos completos: {segments_completed}/{num_segments}")

        # Verifica se houve erros
        errors = [(i, t.error_msg) for i, t in enumerate(self.segment_threads) if t.error_msg]
        if errors:
            error_msgs = [f"Segmento {seg_id}: {msg}" for seg_id, msg in errors]
            error_str = "\n".join(error_msgs)
            print(f"[MULTI-SEGMENT] ERROS: {error_str}")
            raise Exception(error_str)

        # Verifica se todos os arquivos .part existem e têm o tamanho correto
        all_segments_on_disk = True
        expected_segment_sizes = []
        actual_segment_sizes = []

        for i in range(num_segments):
            segment_file = f"{dest_path}.part{i}"
            start_byte = i * segment_size
            end_byte = ((i + 1) * segment_size - 1) if i < num_segments - 1 else (total_size - 1)
            expected_size = end_byte - start_byte + 1
            expected_segment_sizes.append(expected_size)

            if os.path.exists(segment_file):
                actual_size = os.path.getsize(segment_file)
                actual_segment_sizes.append(actual_size)
                print(f"[MULTI-SEGMENT] Segmento {i}: esperado={expected_size}, atual={actual_size}, ok={actual_size >= expected_size}")
                if actual_size < expected_size:
                    all_segments_on_disk = False
            else:
                actual_segment_sizes.append(0)
                print(f"[MULTI-SEGMENT] Segmento {i}: arquivo não existe!")
                all_segments_on_disk = False

        print(f"[MULTI-SEGMENT] Todos segmentos no disco com tamanho correto: {all_segments_on_disk}")

        # Junta os segmentos no arquivo final
        print(f"[MULTI-SEGMENT] Verificando condições de merge:")
        print(f"  - is_cancelled: {self.is_cancelled}")
        print(f"  - segments_completed: {segments_completed}/{num_segments}")
        print(f"  - all_segments_on_disk: {all_segments_on_disk}")

        # Faz merge se não foi cancelado E (todos segmentos marcados como completos OU todos arquivos estão no disco)
        should_merge = not self.is_cancelled and (segments_completed == num_segments or all_segments_on_disk)

        if should_merge:
            print(f"[MULTI-SEGMENT] Juntando {num_segments} segmentos...")
            try:
                self._merge_segments(dest_path, num_segments)
                print(f"[MULTI-SEGMENT] Merge concluído com sucesso!")
            except Exception as e:
                print(f"[MULTI-SEGMENT] ERRO ao fazer merge: {e}")
                import traceback
                traceback.print_exc()
                raise

            self.progress_updated.emit(
                self.download_item.filename,
                {'progress': 100, 'downloaded': total_size, 'total': total_size, 'speed': 0.0}
            )
            print(f"[MULTI-SEGMENT] Concluído!")
        else:
            print(f"[MULTI-SEGMENT] Download não completou. Cancelado: {self.is_cancelled}, Completos: {segments_completed}/{num_segments}, Disco OK: {all_segments_on_disk}")
            print(f"[MULTI-SEGMENT] ATENÇÃO: Segmentos NÃO foram consolidados! Arquivos .part permanecem no disco.")


    def _merge_segments(self, dest_path, num_segments):
        """Junta os segmentos em um arquivo final"""
        with open(dest_path, 'wb') as output_file:
            for i in range(num_segments):
                segment_file = f"{dest_path}.part{i}"
                if os.path.exists(segment_file):
                    with open(segment_file, 'rb') as seg_file:
                        output_file.write(seg_file.read())
                    # Remove arquivo temporário
                    os.remove(segment_file)
                else:
                    raise Exception(f"Segmento {i} não encontrado!")

        print(f"[MULTI-SEGMENT] Arquivo final criado: {dest_path}")
    
    def _format_size(self, size):
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
    
    def cancel(self):
        self.is_cancelled = True
        # Cancela todos os segmentos se houver
        for thread in self.segment_threads:
            thread.cancel()
        self.resume()

    def pause(self):
        self.mutex.lock()
        self.is_paused = True
        self.mutex.unlock()
        # Pausa todos os segmentos se houver
        for thread in self.segment_threads:
            thread.pause()

    def resume(self):
        self.mutex.lock()
        self.is_paused = False
        self.pause_condition.wakeAll()
        self.mutex.unlock()
        # Retoma todos os segmentos se houver
        for thread in self.segment_threads:
            thread.resume()


class DownloadManager(QThread):
    download_started = pyqtSignal(str)
    all_completed = pyqtSignal()
    
    def __init__(self, max_concurrent):
        super().__init__()
        self.max_concurrent = max_concurrent
        self.download_queue = Queue()
        self.active_downloads = []
        self.is_running = True
        
    def add_download(self, download_item):
        self.download_queue.put(download_item)
    
    def run(self):
        while self.is_running or not self.download_queue.empty() or self.active_downloads:
            self.active_downloads = [d for d in self.active_downloads 
                                    if d.thread and d.thread.isRunning()]
            
            while (len(self.active_downloads) < self.max_concurrent and 
                   not self.download_queue.empty()):
                download_item = self.download_queue.get()
                
                thread = SingleDownloadThread(download_item)
                download_item.thread = thread
                
                self.active_downloads.append(download_item)
                self.download_started.emit(download_item.filename)
                thread.start()
            
            time.sleep(0.1)
        
        self.all_completed.emit()
    
    def update_max_concurrent(self, value):
        self.max_concurrent = value
    
    def stop(self):
        self.is_running = False


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

        self.recent_identifiers = self.load_recent_identifiers()
        self.all_files = []
        self.initUI()
        self.start_download_manager()
        self.load_downloads()
        
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
        
        print(f"\n[LOAD] Carregando {len(downloads_data)} download(s) salvos...")
        print(f"[LOAD] JSON sample: {json_str[:200]}...")
        
        for data in downloads_data:
            try:
                download_item = DownloadItem.from_dict(data)
                
                print(f"\n[LOAD] Arquivo: {download_item.filename}")
                print(f"[LOAD] Total bytes do dict: {download_item.total_bytes}")
                
                # SEMPRE busca o tamanho do IA para garantir que está correto
                if download_item.item_id:
                    print(f"[LOAD] Buscando tamanho correto do IA para: {download_item.item_id}")
                    try:
                        item = ia.get_item(download_item.item_id)
                        for f in item.files:
                            if f['name'] == download_item.filename:
                                download_item.total_bytes = abs(int(f.get('size', 0)))
                                print(f"[LOAD] Total bytes correto do IA: {download_item.total_bytes} ({self._format_size(download_item.total_bytes)})")
                                break
                    except Exception as e:
                        print(f"[LOAD] Erro ao buscar do IA: {e}")
                
                # Atualiza downloaded_bytes com o tamanho atual do arquivo
                dest_path = os.path.join(download_item.dest_folder, download_item.filename)
                if os.path.exists(dest_path):
                    download_item.downloaded_bytes = os.path.getsize(dest_path)
                    print(f"[LOAD] Arquivo encontrado no disco: {download_item.downloaded_bytes} bytes ({self._format_size(download_item.downloaded_bytes)})")
                    if download_item.total_bytes > 0:
                        download_item.progress = int((download_item.downloaded_bytes / download_item.total_bytes) * 100)
                        print(f"[LOAD] Progresso calculado: {download_item.progress}%")
                else:
                    print(f"[LOAD] Arquivo não encontrado no disco: {dest_path}")
                    download_item.downloaded_bytes = 0
                    download_item.progress = 0
                
                print(f"[LOAD] Status: {download_item.status.value}")
                print(f"[LOAD] Final: total={download_item.total_bytes}, downloaded={download_item.downloaded_bytes}, progress={download_item.progress}%")
                
                self.downloads[download_item.filename] = download_item
                self.add_download_to_table(download_item)
                
            except Exception as e:
                print(f"[LOAD] Erro ao carregar download: {e}")
                import traceback
                traceback.print_exc()
    
    def save_downloads(self):
        """Salva downloads atuais com todos os metadados"""
        downloads_data = []
        
        print(f"\n[SAVE] Salvando downloads...")
        
        for download_item in self.downloads.values():
            # Salva todos exceto completados e cancelados
            if download_item.status not in [DownloadStatus.COMPLETED, DownloadStatus.CANCELLED]:
                # Atualiza downloaded_bytes com o tamanho atual do arquivo se existir
                dest_path = os.path.join(download_item.dest_folder, download_item.filename)
                if os.path.exists(dest_path):
                    download_item.downloaded_bytes = os.path.getsize(dest_path)
                    if download_item.total_bytes > 0:
                        download_item.progress = int((download_item.downloaded_bytes / download_item.total_bytes) * 100)
                
                print(f"[SAVE] {download_item.filename}:")
                print(f"       total_bytes={download_item.total_bytes} ({self._format_size(download_item.total_bytes)})")
                print(f"       downloaded_bytes={download_item.downloaded_bytes} ({self._format_size(download_item.downloaded_bytes)})")
                print(f"       progress={download_item.progress}%")
                
                # Converte para dict que já salva como string
                downloads_data.append(download_item.to_dict())
        
        # Salva como JSON string diretamente, sem usar QSettings nativamente com números grandes
        json_str = json.dumps(downloads_data, ensure_ascii=False)
        print(f"[SAVE] JSON sample: {json_str[:200]}...")
        
        # Salva como texto puro para evitar conversão automática do QSettings
        self.settings.setValue('downloads_json', json_str)
        print(f"[SAVE] {len(downloads_data)} download(s) salvos\n")
    
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

        tabs = QTabWidget()
        layout.addWidget(tabs)

        tab1 = self.create_identifier_tab()
        tabs.addTab(tab1, "Buscar por Identifier")

        tab2 = self.create_url_tab()
        tabs.addTab(tab2, "Download Direto por URL")

        tab3 = self.create_download_manager_tab()
        tabs.addTab(tab3, "Gerenciador de Downloads")

        tab4 = self.create_settings_tab()
        tabs.addTab(tab4, "⚙️ Configurações")
        
    def create_identifier_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        id_layout = QHBoxLayout()
        id_label = QLabel('Identifier:')
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText('Ex: rick-astley-never-gonna-give-you-up')
        
        self.completer = QCompleter(self.recent_identifiers)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.id_input.setCompleter(self.completer)
        
        self.search_btn = QPushButton('Buscar Arquivos')
        self.search_btn.clicked.connect(self.search_files)
        
        self.history_btn = QPushButton('📋 Histórico')
        self.history_btn.setToolTip('Ver identifiers recentes')
        self.history_btn.clicked.connect(self.show_history)
        
        id_layout.addWidget(id_label)
        id_layout.addWidget(self.id_input)
        id_layout.addWidget(self.history_btn)
        id_layout.addWidget(self.search_btn)
        layout.addLayout(id_layout)
        
        filter_layout = QHBoxLayout()
        filter_label = QLabel('🔍 Filtrar:')
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText('Digite para filtrar arquivos...')
        self.filter_input.textChanged.connect(self.filter_files)
        self.clear_filter_btn = QPushButton('✕')
        self.clear_filter_btn.setMaximumWidth(30)
        self.clear_filter_btn.setToolTip('Limpar filtro')
        self.clear_filter_btn.clicked.connect(lambda: self.filter_input.clear())
        
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_input)
        filter_layout.addWidget(self.clear_filter_btn)
        layout.addLayout(filter_layout)
        
        list_label = QLabel('Arquivos disponíveis (selecione os que deseja baixar):')
        layout.addWidget(list_label)

        hint_label = QLabel('💡 Dica: Clique duas vezes em um arquivo para adicioná-lo à fila usando a pasta padrão')
        hint_label.setStyleSheet('color: gray; font-size: 10px; font-style: italic;')
        layout.addWidget(hint_label)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.file_list.itemDoubleClicked.connect(self.add_file_on_double_click)
        layout.addWidget(self.file_list)
        
        download_layout = QHBoxLayout()
        self.download_btn = QPushButton('Adicionar à Fila de Download')
        self.download_btn.clicked.connect(self.add_to_queue)
        self.download_btn.setEnabled(False)
        download_layout.addStretch()
        download_layout.addWidget(self.download_btn)
        layout.addLayout(download_layout)
        
        self.status_label = QLabel('')
        layout.addWidget(self.status_label)
        
        return tab
    
    def create_url_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        url_label = QLabel('Cole a URL completa do arquivo:')
        layout.addWidget(url_label)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('Ex: https://archive.org/download/identifier/filename.ext')
        layout.addWidget(self.url_input)
        
        url_example = QLabel('Formato: https://archive.org/download/{identifier}/{filename}')
        url_example.setStyleSheet('color: gray; font-size: 10px;')
        layout.addWidget(url_example)
        
        self.direct_download_btn = QPushButton('Adicionar à Fila de Download')
        self.direct_download_btn.clicked.connect(self.add_url_to_queue)
        layout.addWidget(self.direct_download_btn)
        
        layout.addStretch()
        return tab
    
    def create_download_manager_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.download_table = QTableWidget()
        self.download_table.setColumnCount(8)
        self.download_table.setHorizontalHeaderLabels([
            'Arquivo', 'Status', 'Progresso', 'Tamanho', 'Velocidade', 'Conexões', 'Ações', 'Mensagem'
        ])
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
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        self.cancel_all_btn = QPushButton('Cancelar Todos')
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
        title.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(title)

        layout.addSpacing(10)

        # Seção: Pasta Padrão
        folder_group_label = QLabel('📁 Pasta Padrão para Downloads')
        folder_group_label.setStyleSheet('font-size: 12px; font-weight: bold;')
        layout.addWidget(folder_group_label)

        folder_layout = QHBoxLayout()
        folder_desc = QLabel('Pasta onde os arquivos serão salvos ao clicar 2x na lista:')
        folder_layout.addWidget(folder_desc)
        layout.addLayout(folder_layout)

        folder_control_layout = QHBoxLayout()
        self.default_folder_input = QLineEdit()
        self.default_folder_input.setPlaceholderText('Nenhuma pasta padrão configurada')
        self.default_folder_input.setText(self.default_download_folder)
        self.default_folder_input.setReadOnly(True)

        self.choose_folder_btn = QPushButton('Escolher Pasta...')
        self.choose_folder_btn.clicked.connect(self.choose_default_folder)

        self.clear_folder_btn = QPushButton('Limpar')
        self.clear_folder_btn.clicked.connect(self.clear_default_folder)

        folder_control_layout.addWidget(self.default_folder_input)
        folder_control_layout.addWidget(self.choose_folder_btn)
        folder_control_layout.addWidget(self.clear_folder_btn)
        layout.addLayout(folder_control_layout)

        layout.addSpacing(20)

        # Seção: Performance
        perf_group_label = QLabel('⚡ Performance de Downloads')
        perf_group_label.setStyleSheet('font-size: 12px; font-weight: bold;')
        layout.addWidget(perf_group_label)

        concurrent_layout = QHBoxLayout()
        concurrent_label = QLabel('Downloads simultâneos:')
        concurrent_label.setToolTip('Quantos arquivos podem ser baixados ao mesmo tempo')
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
        segments_label = QLabel('Conexões por arquivo:')
        segments_label.setToolTip('Número de conexões simultâneas para cada arquivo (download acelerado)')
        self.segments_spin = QSpinBox()
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
        perf_note.setStyleSheet('color: gray; font-size: 10px; font-style: italic;')
        perf_note.setWordWrap(True)
        layout.addWidget(perf_note)

        layout.addStretch()

        return tab

    def choose_default_folder(self):
        """Abre diálogo para escolher pasta padrão"""
        folder = QFileDialog.getExistingDirectory(self, 'Escolha a pasta padrão para downloads', self.default_download_folder)

        if folder:
            self.default_download_folder = folder
            self.default_folder_input.setText(folder)
            self.settings.setValue('default_download_folder', folder)
            print(f"[CONFIG] Pasta padrão definida: {folder}")

    def clear_default_folder(self):
        """Limpa a pasta padrão"""
        self.default_download_folder = ''
        self.default_folder_input.setText('')
        self.settings.setValue('default_download_folder', '')
        print("[CONFIG] Pasta padrão removida")

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

        print(f"[QUICK-ADD] Arquivo adicionado via duplo clique: {filename} -> {self.default_download_folder}")

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
                item_widget = QListWidgetItem(f"{file['name']} ({self._format_size(file.get('size', 0))})")
                item_widget.setData(Qt.ItemDataRole.UserRole, file['name'])
                self.file_list.addItem(item_widget)
            
            self.status_label.setText(f'{len(files)} arquivo(s) encontrado(s).')
            self.download_btn.setEnabled(True)
            
            self.add_to_recent(identifier)
            
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
    
    def _format_size(self, size):
        try:
            size = int(size)
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024:
                    return f"{size:.1f} {unit}"
                size /= 1024
            return f"{size:.1f} TB"
        except:
            return "N/A"
    
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
        print(f"[TABLE] Adicionando à tabela: downloaded={download_item.downloaded_bytes}, total={download_item.total_bytes}")
        
        if download_item.total_bytes > 0:
            size_text = f"{self._format_size(download_item.downloaded_bytes)} / {self._format_size(download_item.total_bytes)}"
        else:
            size_text = "Calculando..."
        
        print(f"[TABLE] Texto do tamanho: {size_text}")
        
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
        pause_btn.clicked.connect(lambda: self.toggle_pause(download_item.filename))

        # Botão Cancelar/Recomeçar
        if download_item.status == DownloadStatus.CANCELLED:
            cancel_btn = QPushButton('Recomeçar')
            cancel_btn.clicked.connect(lambda: self.restart_download(download_item.filename))
        else:
            cancel_btn = QPushButton('Cancelar')
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
        print(f"[UPDATE_PROGRESS] RECEBIDO: filename={filename}")
        print(f"[UPDATE_PROGRESS] RECEBIDO: data={data} (type={type(data)})")
        
        # Extrai dados do dicionário
        progress = data.get('progress', 0)
        downloaded = data.get('downloaded', 0)
        total = data.get('total', 0)
        speed = data.get('speed', 0.0)
        
        print(f"[UPDATE_PROGRESS] EXTRAÍDO: progress={progress}%, downloaded={downloaded}, total={total}, speed={speed}")
        
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
                
                size_text = f"{self._format_size(downloaded)} / {self._format_size(total)}"
                print(f"[UPDATE_PROGRESS] size_text={size_text}")
                
                size_item = self.download_table.item(row, 3)
                if size_item:
                    size_item.setText(size_text)
                    print(f"[UPDATE_PROGRESS] Tamanho atualizado na GUI: {size_text}")
                
                speed_text = f"{self._format_size(speed)}/s" if speed > 0 else "0 B/s"
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
                print(f"[RESTART] Arquivo principal removido: {dest_path}")
            except Exception as e:
                print(f"[RESTART] Erro ao remover arquivo principal: {e}")

        # Remove segmentos parciais se existirem
        for i in range(download_item.segments):
            segment_file = f"{dest_path}.part{i}"
            if os.path.exists(segment_file):
                try:
                    os.remove(segment_file)
                    print(f"[RESTART] Segmento {i} removido: {segment_file}")
                except Exception as e:
                    print(f"[RESTART] Erro ao remover segmento {i}: {e}")

        # Reset estado do download_item
        download_item.status = DownloadStatus.WAITING
        download_item.progress = 0
        download_item.downloaded_bytes = 0
        download_item.error_msg = ""
        download_item.thread = None

        print(f"[RESTART] Download reiniciado: {filename}")

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
                    size_text = f"0 B / {self._format_size(download_item.total_bytes)}"
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
                    pause_btn.clicked.connect(lambda: self.toggle_pause(filename))

                    cancel_btn = QPushButton('Cancelar')
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
        print(f"[CONFIG] Downloads simultâneos alterado para: {value}")

    def update_segments_per_file(self, value):
        self.segments_per_file = value
        self.settings.setValue('segments_per_file', value)
        print(f"[CONFIG] Conexões por arquivo alterado para: {value}")

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
        print(f"[CLIPBOARD] Mensagem copiada: {text[:50]}..." if len(text) > 50 else f"[CLIPBOARD] Mensagem copiada: {text}")

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