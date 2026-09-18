"""Interruptible audio subprocess streaming with bounded diagnostic buffers."""
from __future__ import annotations

import queue
import io
import subprocess
import threading
import time
from typing import Callable, Sequence, cast


class AudioProcessRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    def interrupt(self) -> None:
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass

    def stream(
        self,
        command: Sequence[str],
        *,
        stop: threading.Event,
        skip: threading.Event,
        publish: Callable[[bytes], None],
        report_error: Callable[[str], None],
        idle_timeout: float = 30.0,
    ) -> bool:
        if stop.is_set() or skip.is_set():
            return False
        process = subprocess.Popen(
            list(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self._lock:
            self._process = process
        chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=16)
        closing = threading.Event()
        errors = bytearray()
        read_errors: list[str] = []

        def put(chunk: bytes | None) -> None:
            while not closing.is_set():
                try:
                    chunks.put(chunk, timeout=0.1)
                    return
                except queue.Full:
                    continue

        def read_audio() -> None:
            try:
                if process.stdout is None:
                    raise RuntimeError("FFmpeg process started without stdout")
                while not closing.is_set():
                    chunk = cast(io.BufferedReader, process.stdout).read1(16 * 1024)
                    if not chunk:
                        break
                    put(chunk)
            except (OSError, RuntimeError) as exc:
                read_errors.append(str(exc))
            finally:
                put(None)

        def read_stderr() -> None:
            try:
                if process.stderr is None:
                    return
                while chunk := cast(io.BufferedReader, process.stderr).read1(4096):
                    errors.extend(chunk)
                    del errors[:-8192]
            except OSError:
                pass

        readers = [threading.Thread(target=read_audio, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
        for reader in readers:
            reader.start()
        last_audio = time.monotonic()
        produced_audio = False
        try:
            while not stop.is_set() and not skip.is_set():
                try:
                    chunk = chunks.get(timeout=0.1)
                except queue.Empty:
                    if time.monotonic() - last_audio >= idle_timeout:
                        report_error(f"FFmpeg не отдаёт аудио более {idle_timeout:g} секунд; элемент пропущен.")
                        return False
                    continue
                if chunk is None:
                    # stdout may close before the process itself exits.
                    deadline = time.monotonic() + min(idle_timeout, 5.0)
                    while process.poll() is None:
                        if stop.wait(0.05) or skip.is_set():
                            return False
                        if time.monotonic() >= deadline:
                            report_error("FFmpeg закрыл аудиопоток, но не завершился.")
                            return False
                    readers[1].join(timeout=1.0)
                    if process.returncode != 0 or read_errors or not produced_audio:
                        detail = bytes(errors).decode("utf-8", errors="replace").strip()
                        report_error(f"FFmpeg завершился без аудио или с ошибкой {process.returncode}: {detail or '; '.join(read_errors)}")
                        return False
                    return not stop.is_set() and not skip.is_set()
                last_audio = time.monotonic()
                produced_audio = True
                publish(chunk)
            return False
        finally:
            closing.set()
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3.0)
                except OSError:
                    pass
            for reader in readers:
                reader.join(timeout=1.0)
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            with self._lock:
                if self._process is process:
                    self._process = None
