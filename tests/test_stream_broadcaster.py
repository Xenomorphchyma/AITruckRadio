from __future__ import annotations

import queue
import threading

from ai_truck_radio_app.stream_broadcaster import StreamBroadcaster


def test_remove_is_idempotent_and_does_not_hide_other_clients() -> None:
    broadcaster = StreamBroadcaster()
    first, _ = broadcaster.add_subscriber()
    second, second_queue = broadcaster.add_subscriber()

    broadcaster.remove_subscriber(first)
    broadcaster.remove_subscriber(first)
    broadcaster.broadcast(b"audio")

    assert broadcaster.client_counts() == (2, 1)
    assert second_queue.get_nowait() == b"audio"
    broadcaster.remove_subscriber(second)


def test_slow_subscriber_keeps_recent_chunk_and_stop_marker() -> None:
    broadcaster = StreamBroadcaster()
    _sid, chunks = broadcaster.add_subscriber(max_chunks=16)

    for index in range(40):
        broadcaster.broadcast(str(index).encode())
    broadcaster.broadcast(None)

    values = []
    while True:
        try:
            value = chunks.get_nowait()
        except queue.Empty:
            break
        values.append(value)
    assert values[-1] is None
    assert values[-2] == b"39"
    assert len(values) <= 9


def test_concurrent_add_remove_and_broadcast_preserves_consistent_counts() -> None:
    broadcaster = StreamBroadcaster()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(100):
                sid, _queue = broadcaster.add_subscriber()
                broadcaster.broadcast(b"x")
                broadcaster.remove_subscriber(sid)
        except BaseException as error:  # pragma: no cover - assertion reports the worker failure
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert broadcaster.client_counts() == (400, 0)
