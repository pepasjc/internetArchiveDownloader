"""Classes de threads para gerenciamento de downloads"""

import os
import time
import requests
import internetarchive as ia
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from queue import Queue

from models import DownloadStatus
from utils import log, format_size


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
            log(f"[SEGMENT {self.segment_id}] Iniciando download...")
            session = ia.get_session()
            log(f"[SEGMENT {self.segment_id}] Sessão obtida")

            # Verifica se já existe arquivo parcial deste segmento
            segment_file = f"{self.dest_path}.part{self.segment_id}"
            if os.path.exists(segment_file):
                self.downloaded = os.path.getsize(segment_file)
                log(f"[SEGMENT {self.segment_id}] Arquivo parcial: {self.downloaded} bytes")

            # Se já baixou tudo, não precisa fazer nada
            total_segment_size = self.end_byte - self.start_byte + 1
            if self.downloaded >= total_segment_size:
                log(f"[SEGMENT {self.segment_id}] Já completo!")
                self.completed = True
                return

            # Range request para este segmento
            current_start = self.start_byte + self.downloaded
            headers = {'Range': f'bytes={current_start}-{self.end_byte}'}

            log(f"[SEGMENT {self.segment_id}] Fazendo request: {headers}")
            response = session.get(self.url, stream=True, timeout=30, headers=headers)
            response.raise_for_status()
            log(f"[SEGMENT {self.segment_id}] Response OK: {response.status_code}")

            # Abre em modo append se estiver continuando
            mode = 'ab' if self.downloaded > 0 else 'wb'

            with open(segment_file, mode) as f:
                chunk_count = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if self.is_cancelled:
                        log(f"[SEGMENT {self.segment_id}] Cancelado")
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
                            log(f"[SEGMENT {self.segment_id}] Progresso: {self.downloaded} bytes")

                # Atualiza progresso final
                self.progress_mutex.lock()
                self.progress_dict[self.segment_id] = self.downloaded
                self.progress_mutex.unlock()

            log(f"[SEGMENT {self.segment_id}] Saiu do loop de download. Cancelado: {self.is_cancelled}")

            if not self.is_cancelled:
                log(f"[SEGMENT {self.segment_id}] Completo! Total: {self.downloaded} bytes")
                self.completed = True
                log(f"[SEGMENT {self.segment_id}] Marcado como completo: completed={self.completed}")
            else:
                log(f"[SEGMENT {self.segment_id}] NÃO marcado como completo pois foi cancelado")

        except Exception as e:
            log(f"[SEGMENT {self.segment_id}] ERRO: {str(e)}")
            import traceback
            traceback.print_exc()
            if not self.is_cancelled:
                self.error_msg = str(e)
                log(f"[SEGMENT {self.segment_id}] Erro armazenado: {self.error_msg}")

        log(f"[SEGMENT {self.segment_id}] Thread finalizando. completed={self.completed}, error_msg={self.error_msg}, cancelled={self.is_cancelled}")

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

            log(f"[THREAD] Iniciando download: {self.download_item.filename}")
            log(f"[THREAD] Segmentos: {self.download_item.segments}")

            if self.download_item.url:
                parts = self.download_item.url.split('/')
                if 'archive.org' in self.download_item.url and 'download' in parts:
                    download_idx = parts.index('download')
                    identifier = parts[download_idx + 1]
                    filename = '/'.join(parts[download_idx + 2:])

                    log(f"[THREAD] Usando identifier: {identifier}, filename: {filename}")
                    item = ia.get_item(identifier)
                    self._download_with_progress(item, filename)
                else:
                    raise Exception("URL inválida - apenas URLs do archive.org são suportadas")
            else:
                log(f"[THREAD] Usando item_id: {self.download_item.item_id}")
                item = ia.get_item(self.download_item.item_id)
                self._download_with_progress(item, self.download_item.filename)

            if not self.is_cancelled:
                self.status_changed.emit(self.download_item.filename,
                                        DownloadStatus.COMPLETED, "")

        except Exception as e:
            log(f"[THREAD ERROR] {str(e)}")
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

        log(f"[DOWNLOAD] Total size: {total_size} bytes ({format_size(total_size)})")
        log(f"[DOWNLOAD] Segmentos configurados: {self.download_item.segments}")

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

        log(f"[MULTI-SEGMENT] Dividindo arquivo em {num_segments} partes de ~{format_size(segment_size)}")
        log(f"[MULTI-SEGMENT] URL: {download_url}")
        log(f"[MULTI-SEGMENT] Dest: {dest_path}")

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

        log(f"[MULTI-SEGMENT] Criando {num_segments} threads...")
        for i in range(num_segments):
            start_byte = i * segment_size
            end_byte = ((i + 1) * segment_size - 1) if i < num_segments - 1 else (total_size - 1)

            log(f"[MULTI-SEGMENT] Segmento {i}: bytes {start_byte}-{end_byte}")

            # Inicializa progresso
            self.segment_progress[i] = 0

            # Verifica se já existe arquivo parcial deste segmento
            segment_file = f"{dest_path}.part{i}"
            if os.path.exists(segment_file):
                self.segment_progress[i] = os.path.getsize(segment_file)
                log(f"[MULTI-SEGMENT] Segmento {i} parcial encontrado: {self.segment_progress[i]} bytes")

            # Cria thread passando o dict compartilhado
            thread = SegmentDownloadThread(i, download_url, dest_path, start_byte, end_byte,
                                          self.segment_progress, self.segment_progress_mutex)
            self.segment_threads.append(thread)

        # Inicia todas as threads
        log(f"[MULTI-SEGMENT] Iniciando threads...")
        for i, thread in enumerate(self.segment_threads):
            thread.start()
            log(f"[MULTI-SEGMENT] Thread {i} iniciada")

        # Monitora progresso
        start_time = time.time()
        last_update_time = start_time
        last_total_downloaded = sum(self.segment_progress.values())

        log(f"[MULTI-SEGMENT] Entrando no loop de monitoramento...")
        loop_count = 0
        max_loops = 100000  # Previne loop infinito (aprox 2.7 horas para um download)

        while loop_count < max_loops and any(thread.isRunning() for thread in self.segment_threads):
            loop_count += 1
            if loop_count % 50 == 0:  # Log a cada 5 segundos
                running = sum(1 for t in self.segment_threads if t.isRunning())
                completed = sum(1 for t in self.segment_threads if t.completed)
                errors = sum(1 for t in self.segment_threads if t.error_msg)
                log(f"[MULTI-SEGMENT] Loop {loop_count}: {running}/{num_segments} threads rodando, completos: {completed}, erros: {errors}")

            if self.is_cancelled:
                log(f"[MULTI-SEGMENT] Cancelando todas as threads...")
                for thread in self.segment_threads:
                    thread.cancel()
                for thread in self.segment_threads:
                    thread.wait()
                return

            # Verifica pausar/retomar
            self.mutex.lock()
            is_paused_now = self.is_paused
            self.mutex.unlock()

            if is_paused_now:
                # Se está pausado, pausa todos os segmentos e aguarda
                for thread in self.segment_threads:
                    if not thread.is_paused:
                        thread.pause()

                # Aguarda até que seja retomado (verifica a cada 100ms)
                while True:
                    self.mutex.lock()
                    if not self.is_paused or self.is_cancelled:
                        self.mutex.unlock()
                        break
                    self.mutex.unlock()
                    time.sleep(0.1)

                # Se foi retomado (não cancelado), retoma todos os segmentos
                if not self.is_cancelled:
                    log(f"[MULTI-SEGMENT] Retomando...")
                    for thread in self.segment_threads:
                        thread.resume()
                    start_time = time.time()
                    last_update_time = start_time
                    last_total_downloaded = sum(self.segment_progress.values())

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
        log(f"[MULTI-SEGMENT] Saiu do loop. Aguardando threads...")
        for i, thread in enumerate(self.segment_threads):
            if thread.isRunning():
                log(f"[MULTI-SEGMENT] Aguardando thread {i}...")
                thread.wait(5000)  # Aguarda até 5 segundos

        # Debug: mostra status detalhado de cada thread
        log(f"[MULTI-SEGMENT] Status detalhado das threads:")
        for i, thread in enumerate(self.segment_threads):
            log(f"  Thread {i}: running={thread.isRunning()}, completed={thread.completed}, cancelled={thread.is_cancelled}, error={thread.error_msg}")

        # Conta completos e erros
        segments_completed = sum(1 for t in self.segment_threads if t.completed)
        log(f"[MULTI-SEGMENT] Todas threads terminaram. Segmentos completos: {segments_completed}/{num_segments}")

        # Verifica se houve erros
        errors = [(i, t.error_msg) for i, t in enumerate(self.segment_threads) if t.error_msg]
        if errors:
            error_msgs = [f"Segmento {seg_id}: {msg}" for seg_id, msg in errors]
            error_str = "\n".join(error_msgs)
            log(f"[MULTI-SEGMENT] ERROS: {error_str}")
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
                log(f"[MULTI-SEGMENT] Segmento {i}: esperado={expected_size}, atual={actual_size}, ok={actual_size >= expected_size}")
                if actual_size < expected_size:
                    all_segments_on_disk = False
            else:
                actual_segment_sizes.append(0)
                log(f"[MULTI-SEGMENT] Segmento {i}: arquivo não existe!")
                all_segments_on_disk = False

        log(f"[MULTI-SEGMENT] Todos segmentos no disco com tamanho correto: {all_segments_on_disk}")

        # Junta os segmentos no arquivo final
        log(f"[MULTI-SEGMENT] Verificando condições de merge:")
        log(f"  - is_cancelled: {self.is_cancelled}")
        log(f"  - segments_completed: {segments_completed}/{num_segments}")
        log(f"  - all_segments_on_disk: {all_segments_on_disk}")

        # Faz merge se não foi cancelado E (todos segmentos marcados como completos OU todos arquivos estão no disco)
        should_merge = not self.is_cancelled and (segments_completed == num_segments or all_segments_on_disk)

        if should_merge:
            log(f"[MULTI-SEGMENT] Juntando {num_segments} segmentos...")
            try:
                self._merge_segments(dest_path, num_segments)
                log(f"[MULTI-SEGMENT] Merge concluído com sucesso!")
            except Exception as e:
                log(f"[MULTI-SEGMENT] ERRO ao fazer merge: {e}")
                import traceback
                traceback.print_exc()
                raise

            self.progress_updated.emit(
                self.download_item.filename,
                {'progress': 100, 'downloaded': total_size, 'total': total_size, 'speed': 0.0}
            )
            log(f"[MULTI-SEGMENT] Concluído!")
        else:
            log(f"[MULTI-SEGMENT] Download não completou. Cancelado: {self.is_cancelled}, Completos: {segments_completed}/{num_segments}, Disco OK: {all_segments_on_disk}")
            log(f"[MULTI-SEGMENT] ATENÇÃO: Segmentos NÃO foram consolidados! Arquivos .part permanecem no disco.")

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

        log(f"[MULTI-SEGMENT] Arquivo final criado: {dest_path}")

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
        # Nota: os segmentos serão pausados pelo loop de monitoramento

    def resume(self):
        self.mutex.lock()
        self.is_paused = False
        self.mutex.unlock()
        # Nota: os segmentos serão retomados pelo loop de monitoramento


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
