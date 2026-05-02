"""Classes de threads para gerenciamento de downloads"""

import os
import time
import threading
from http.client import IncompleteRead
from urllib.parse import unquote

import internetarchive as ia
import requests
from requests.exceptions import ChunkedEncodingError
from urllib3.exceptions import ProtocolError
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition

from models import DownloadStatus
from utils import log, format_size


def _is_retryable_error(e):
    """Verifica se o erro é transiente e pode ser tentado novamente (5xx, timeout, conexão)"""
    if isinstance(e, requests.exceptions.HTTPError):
        return e.response is not None and e.response.status_code >= 500
    return isinstance(e, (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
        requests.exceptions.ContentDecodingError,
        requests.exceptions.RequestException,
        ProtocolError,
        IncompleteRead,
    ))


def _build_stream_headers(range_header=None):
    """Cabeçalhos mais estáveis para downloads longos e retomáveis."""
    headers = {
        'Accept-Encoding': 'identity',
    }
    if range_header:
        headers['Range'] = range_header
    return headers


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
        log(f"[SEGMENT {self.segment_id}] Iniciando download...")

        segment_file = f"{self.dest_path}.part{self.segment_id}"
        total_segment_size = self.end_byte - self.start_byte + 1

        # Verifica se já existe arquivo parcial deste segmento
        if os.path.exists(segment_file):
            self.downloaded = os.path.getsize(segment_file)
            log(f"[SEGMENT {self.segment_id}] Arquivo parcial: {self.downloaded} bytes")

        # Se já baixou tudo, não precisa fazer nada
        if self.downloaded >= total_segment_size:
            log(f"[SEGMENT {self.segment_id}] Já completo!")
            self.completed = True
            return

        max_retries = 5
        base_delay = 5  # segundos

        for attempt in range(max_retries + 1):
            if self.is_cancelled:
                return

            # A partir da 2ª tentativa, relê o progresso do disco para retomar corretamente
            if attempt > 0:
                if os.path.exists(segment_file):
                    self.downloaded = os.path.getsize(segment_file)
                else:
                    self.downloaded = 0
                log(f"[SEGMENT {self.segment_id}] Tentativa {attempt + 1}/{max_retries + 1}, retomando de {self.downloaded} bytes")

                if self.downloaded >= total_segment_size:
                    log(f"[SEGMENT {self.segment_id}] Já completo!")
                    self.completed = True
                    return

            try:
                session = ia.get_session()
                log(f"[SEGMENT {self.segment_id}] Sessão obtida")

                # Range request para este segmento
                current_start = self.start_byte + self.downloaded
                headers = _build_stream_headers(f'bytes={current_start}-{self.end_byte}')

                log(f"[SEGMENT {self.segment_id}] Fazendo request: {headers}")
                response = session.get(self.url, stream=True, timeout=30, headers=headers)
                response.raise_for_status()
                log(f"[SEGMENT {self.segment_id}] Response OK: {response.status_code}")

                # Segmentos exigem suporte a Range. Se o servidor ignorar o Range,
                # recomeçamos a tentativa em vez de corromper o arquivo .part.
                if response.status_code != 206:
                    raise Exception(
                        f"Servidor não retornou conteúdo parcial para o segmento "
                        f"{self.segment_id} (status {response.status_code})"
                    )

                # Abre em modo append se estiver continuando
                mode = 'ab' if self.downloaded > 0 else 'wb'

                try:
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
                finally:
                    response.close()

                if not self.is_cancelled and self.downloaded < total_segment_size:
                    missing = total_segment_size - self.downloaded
                    raise ChunkedEncodingError(
                        f"Segmento {self.segment_id} terminou incompleto: "
                        f"faltam {missing} bytes"
                    )

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

                log(f"[SEGMENT {self.segment_id}] Thread finalizando. completed={self.completed}, error_msg={self.error_msg}, cancelled={self.is_cancelled}")
                return  # Sucesso - sai do loop de tentativas

            except Exception as e:
                if self.is_cancelled:
                    log(f"[SEGMENT {self.segment_id}] Cancelado durante erro")
                    return

                if attempt < max_retries and _is_retryable_error(e):
                    delay = min(base_delay * (2 ** attempt), 60)
                    log(f"[SEGMENT {self.segment_id}] Erro transiente (tentativa {attempt + 1}/{max_retries + 1}): {e}. Aguardando {delay}s antes de tentar novamente...")
                    # Aguarda com verificação de cancelamento a cada 100ms
                    for _ in range(delay * 10):
                        if self.is_cancelled:
                            return
                        time.sleep(0.1)
                else:
                    log(f"[SEGMENT {self.segment_id}] ERRO: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self.error_msg = str(e)
                    log(f"[SEGMENT {self.segment_id}] Thread finalizando. completed={self.completed}, error_msg={self.error_msg}, cancelled={self.is_cancelled}")
                    return

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
            self.status_changed.emit(self.download_item.unique_id,
                                    DownloadStatus.DOWNLOADING, "")

            log(f"[THREAD] Iniciando download: {self.download_item.filename}")
            log(f"[THREAD] Segmentos: {self.download_item.segments}")

            # Reset trackers usados pela verificação final
            self._final_dest_path = None
            self._final_total_size = 0

            if self.download_item.url:
                parts = self.download_item.url.split('/')
                if 'archive.org' in self.download_item.url and 'download' in parts:
                    download_idx = parts.index('download')
                    identifier = parts[download_idx + 1]
                    filename = unquote('/'.join(parts[download_idx + 2:]))

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
                # Sanity check: arquivo final precisa existir e ter tamanho >= total.
                # Evita marcar como COMPLETED quando o download silenciosamente falhou.
                dest = self._final_dest_path
                expected = self._final_total_size
                if dest and expected > 0:
                    actual = os.path.getsize(dest) if os.path.exists(dest) else 0
                    if actual < expected:
                        raise Exception(
                            f"Download terminou incompleto: "
                            f"{format_size(actual)}/{format_size(expected)} no disco"
                        )
                self.status_changed.emit(self.download_item.unique_id,
                                        DownloadStatus.COMPLETED, "")

        except Exception as e:
            log(f"[THREAD ERROR] {str(e)}")
            import traceback
            traceback.print_exc()
            if not self.is_cancelled:
                self.status_changed.emit(self.download_item.unique_id,
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

        # Guarda para verificação final em run() antes de emitir COMPLETED
        self._final_dest_path = dest_path
        self._final_total_size = total_size

        log(f"[DOWNLOAD] Total size: {total_size} bytes ({format_size(total_size)})")
        log(f"[DOWNLOAD] Segmentos configurados: {self.download_item.segments}")

        # Verifica se já existe arquivo completo
        if os.path.exists(dest_path):
            downloaded = int(os.path.getsize(dest_path))
            if downloaded >= total_size:
                self.progress_updated.emit(
                    self.download_item.unique_id,
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
        max_retries = 5
        base_delay = 5  # segundos

        # Verifica se já existe arquivo parcial
        downloaded = 0
        if os.path.exists(dest_path):
            downloaded = int(os.path.getsize(dest_path))

        # Emite progresso inicial
        initial_progress = int((downloaded * 100) // total_size) if total_size > 0 else 0
        self.progress_updated.emit(
            self.download_item.unique_id,
            {
                'progress': initial_progress,
                'downloaded': downloaded,
                'total': total_size,
                'speed': 0.0
            }
        )

        for attempt in range(max_retries + 1):
            if self.is_cancelled:
                return

            # A partir da 2ª tentativa, relê o progresso do disco para retomar corretamente
            if attempt > 0:
                if os.path.exists(dest_path):
                    downloaded = int(os.path.getsize(dest_path))
                else:
                    downloaded = 0
                log(f"[SINGLE] Tentativa {attempt + 1}/{max_retries + 1}, retomando de {downloaded} bytes")

            try:
                session = ia.get_session()
                headers = _build_stream_headers()
                if downloaded > 0:
                    headers = _build_stream_headers(f'bytes={downloaded}-')

                response = session.get(download_url, stream=True, timeout=30, headers=headers)

                if downloaded > 0 and response.status_code not in [200, 206]:
                    response.close()
                    downloaded = 0
                    response = session.get(
                        download_url,
                        stream=True,
                        timeout=30,
                        headers=_build_stream_headers()
                    )

                response.raise_for_status()

                start_time = time.time()
                last_update_time = start_time
                last_downloaded = downloaded

                mode = 'ab' if downloaded > 0 and response.status_code == 206 else 'wb'
                if mode == 'wb':
                    downloaded = 0

                try:
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
                                        self.download_item.unique_id,
                                        {
                                            'progress': progress,
                                            'downloaded': downloaded,
                                            'total': total_size,
                                            'speed': float(speed)
                                        }
                                    )

                                    last_update_time = current_time
                                    last_downloaded = downloaded
                finally:
                    response.close()

                if not self.is_cancelled and downloaded < total_size:
                    missing = total_size - downloaded
                    raise ChunkedEncodingError(
                        f"Download terminou incompleto: faltam {missing} bytes"
                    )

                if not self.is_cancelled:
                    self.progress_updated.emit(
                        self.download_item.unique_id,
                        {
                            'progress': 100,
                            'downloaded': downloaded,
                            'total': total_size,
                            'speed': 0.0
                        }
                    )
                return  # Sucesso - sai do loop de tentativas

            except requests.exceptions.RequestException as e:
                if self.is_cancelled:
                    return

                if attempt < max_retries and _is_retryable_error(e):
                    delay = min(base_delay * (2 ** attempt), 60)
                    log(f"[SINGLE] Erro transiente (tentativa {attempt + 1}/{max_retries + 1}): {e}. Aguardando {delay}s antes de tentar novamente...")
                    # Aguarda com verificação de cancelamento a cada 100ms
                    for _ in range(delay * 10):
                        if self.is_cancelled:
                            return
                        time.sleep(0.1)
                else:
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
                self.download_item.unique_id,
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
            self.download_item.unique_id,
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

        # Loop monitora até todas threads pararem. Sem cap arbitrário —
        # cap antigo (~2.78h) marcava downloads grandes como concluídos
        # incorretamente quando o tempo estourava com threads ainda rodando.
        while any(thread.isRunning() for thread in self.segment_threads):
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
                    self.download_item.unique_id,
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
                self.download_item.unique_id,
                {'progress': 100, 'downloaded': total_size, 'total': total_size, 'speed': 0.0}
            )
            log(f"[MULTI-SEGMENT] Concluído!")
        elif self.is_cancelled:
            log(f"[MULTI-SEGMENT] Cancelado pelo usuário. Arquivos .part preservados para retomar.")
        else:
            # Caso de falha silenciosa anterior: agora levanta exceção para que
            # run() emita ERROR (e não COMPLETED). Os .part ficam para retomar.
            actual_total = sum(actual_segment_sizes)
            log(f"[MULTI-SEGMENT] Download não completou. "
                f"Completos: {segments_completed}/{num_segments}, Disco OK: {all_segments_on_disk}")
            log(f"[MULTI-SEGMENT] Arquivos .part preservados para retomar.")
            raise Exception(
                f"Download incompleto: {segments_completed}/{num_segments} segmentos prontos, "
                f"{format_size(actual_total)}/{format_size(total_size)} no disco"
            )

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
        # Wakes _download_single_segment if it is blocked on pause_condition.wait().
        # For multi-segment the monitoring loop polls is_paused and resumes segments
        # on its own, but wakeAll() here is harmless in that case too.
        self.pause_condition.wakeAll()
        self.mutex.unlock()


class DownloadManager(QThread):
    download_started = pyqtSignal(str)
    all_completed = pyqtSignal()

    def __init__(self, max_concurrent):
        super().__init__()
        self.max_concurrent = max_concurrent
        self.pending_downloads = []   # Ordered queue; index 0 = highest priority
        self.force_pending = []       # Force-start queue; bypasses max_concurrent
        self._lock = threading.Lock()
        self.active_downloads = []
        self.removed_download_ids = set()
        self.is_running = True

    def add_download(self, download_item):
        """Add a download to the end of the pending queue."""
        with self._lock:
            self.removed_download_ids.discard(download_item.unique_id)
            self.pending_downloads.append(download_item)

    def add_force_download(self, download_item):
        """Remove item from the pending queue and start it immediately,
        bypassing the max_concurrent limit."""
        with self._lock:
            self.removed_download_ids.discard(download_item.unique_id)
            if download_item in self.pending_downloads:
                self.pending_downloads.remove(download_item)
                self.force_pending.append(download_item)
                return True
        return False

    def remove_download(self, download_item):
        """Remove an item from manager queues and prevent future starts."""
        with self._lock:
            self.removed_download_ids.add(download_item.unique_id)

            removed = False
            if download_item in self.pending_downloads:
                self.pending_downloads.remove(download_item)
                removed = True
            if download_item in self.force_pending:
                self.force_pending.remove(download_item)
                removed = True
            if download_item in self.active_downloads and (
                not download_item.thread or not download_item.thread.isRunning()
            ):
                self.active_downloads.remove(download_item)
                removed = True

            return removed

    def move_up(self, unique_id):
        """Move a pending item one position earlier in the queue (higher priority)."""
        with self._lock:
            for i, item in enumerate(self.pending_downloads):
                if item.unique_id == unique_id and i > 0:
                    self.pending_downloads[i - 1], self.pending_downloads[i] = \
                        self.pending_downloads[i], self.pending_downloads[i - 1]
                    return True
        return False

    def move_down(self, unique_id):
        """Move a pending item one position later in the queue (lower priority)."""
        with self._lock:
            for i, item in enumerate(self.pending_downloads):
                if item.unique_id == unique_id and i < len(self.pending_downloads) - 1:
                    self.pending_downloads[i + 1], self.pending_downloads[i] = \
                        self.pending_downloads[i], self.pending_downloads[i + 1]
                    return True
        return False

    def _start_download(self, download_item):
        """Spin up a SingleDownloadThread for the given item (run-thread only)."""
        with self._lock:
            if download_item.unique_id in self.removed_download_ids:
                return

            thread = SingleDownloadThread(download_item)
            download_item.thread = thread
            self.active_downloads.append(download_item)
            self.download_started.emit(download_item.unique_id)
            thread.start()

    def run(self):
        while True:
            with self._lock:
                has_pending = bool(self.pending_downloads or self.force_pending)

            if not self.is_running and not has_pending and not self.active_downloads:
                break

            self.active_downloads = [d for d in self.active_downloads
                                     if d.thread and d.thread.isRunning()]

            # Always start forced downloads regardless of max_concurrent
            while True:
                with self._lock:
                    if not self.force_pending:
                        break
                    item = self.force_pending.pop(0)
                self._start_download(item)

            # Start normal downloads up to max_concurrent
            while len(self.active_downloads) < self.max_concurrent:
                with self._lock:
                    if not self.pending_downloads:
                        break
                    item = self.pending_downloads.pop(0)
                self._start_download(item)

            time.sleep(0.1)

        self.all_completed.emit()

    def update_max_concurrent(self, value):
        self.max_concurrent = value

    def stop(self):
        self.is_running = False
