"""Bounded, non-blocking fan-out for the live MP3 stream."""
from __future__ import annotations

import queue
import threading


class StreamBroadcaster:
    """Own subscriber queues and their counters independently of radio state.

    A slow listener loses old chunks instead of holding up the broadcast.  None
    is the end-of-stream marker, with the same delivery policy as an audio chunk.
    Broadcasting snapshots the listeners under the lock and never waits for a
    consumer; a disconnected listener may still receive an in-flight chunk.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, queue.Queue[bytes | None]] = {}
        self._next_id = 1
        self._total_clients = 0

    def add_subscriber(self, max_chunks: int = 256) -> tuple[int, queue.Queue[bytes | None]]:
        chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=max(16, max_chunks))
        with self._lock:
            sid = self._next_id
            self._next_id += 1
            self._subscribers[sid] = chunks
            self._total_clients += 1
        return sid, chunks

    def remove_subscriber(self, sid: int) -> None:
        # Cleanup may be requested more than once for a disconnected client.
        with self._lock:
            self._subscribers.pop(sid, None)

    def client_counts(self) -> tuple[int, int]:
        """Return total and active clients from one consistent snapshot."""
        with self._lock:
            return self._total_clients, len(self._subscribers)

    def broadcast(self, chunk: bytes | None) -> None:
        with self._lock:
            targets = list(self._subscribers.values())
        for chunks in targets:
            try:
                chunks.put_nowait(chunk)
            except queue.Full:
                # Keep recent audio, with room for the next burst of chunks.
                try:
                    while chunks.qsize() > max(2, chunks.maxsize // 2):
                        chunks.get_nowait()
                except queue.Empty:
                    pass
                try:
                    chunks.put_nowait(chunk)
                except queue.Full:
                    pass
