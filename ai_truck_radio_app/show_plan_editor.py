from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

from ai_truck_radio_app.text_processing import parse_dialogue_segments
from ai_truck_radio_app.tracks import PlannedItem


class ShowPlanEditor:
    """Pure show-plan editing helpers used by :class:`RadioEngine`.

    The engine still owns locks, persistence, TTS and content reservations. This
    class only performs bounded view generation and deterministic list edits so
    those behaviors can be tested without starting the radio runtime.
    """

    @staticmethod
    def preview(
        items: List[PlannedItem],
        active_index: int,
        stale_audio_ids: Set[int],
        cfg: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Build a bounded, lossless preview of a prepared show plan."""
        item_limit = max(1, int(cfg.get("show_plan_preview_items", 80) or 80))
        char_limit = max(4_000, int(cfg.get("show_plan_preview_max_chars", 120_000) or 120_000))
        result: List[Dict[str, Any]] = []
        used_chars = 0
        for index, item in enumerate(items[:item_limit]):
            text = item.text or ""
            hosts: List[str] = []
            if item.kind == "speech":
                for host, _spoken in parse_dialogue_segments(text, cfg.get("hosts") or []):
                    clean_host = str(host or "").strip()
                    if clean_host and clean_host not in hosts:
                        hosts.append(clean_host)
            # Do not truncate a script: omit later entries instead, so an
            # editor cannot accidentally save a truncated script back to disk.
            if result and used_chars + len(text) > char_limit:
                break
            used_chars += len(text)
            result.append(
                {
                    "idx": index + 1,
                    "kind": item.kind,
                    "title": item.title,
                    "duration_sec": round(float(item.duration_sec or 0.0), 1),
                    "text": text,
                    "hosts": hosts,
                    "active": index == active_index,
                    "audio_ready": ShowPlanEditor.audio_is_current(item, stale_audio_ids),
                }
            )
        return result

    @staticmethod
    def audio_is_current(item: PlannedItem, stale_audio_ids: Set[int]) -> bool:
        """Return whether a speech item still points at usable generated audio."""
        return item.kind == "speech" and id(item) not in stale_audio_ids and item.path.is_file()

    @staticmethod
    def audio_path(
        items: List[PlannedItem],
        index: int,
        stale_audio_ids: Set[int],
        cache_dir: Path,
    ) -> Path | None:
        """Resolve one-based plan audio while constraining it to the cache."""
        zero_index = index - 1
        if zero_index < 0 or zero_index >= len(items):
            return None
        item = items[zero_index]
        if not ShowPlanEditor.audio_is_current(item, stale_audio_ids):
            return None
        path = item.path.resolve()
        try:
            path.relative_to(cache_dir.resolve())
        except ValueError:
            return None
        return path

    @staticmethod
    def mutate(
        items: List[PlannedItem],
        stale_audio_ids: Set[int],
        *,
        index: int,
        action: str,
        target_index: int,
        active_index: int,
        next_index: int,
    ) -> Dict[str, Any]:
        """Apply one safe structural edit to the future part of a plan.

        ``items`` and ``stale_audio_ids`` are mutated in place under the
        caller's lock. Keeping ownership with the engine preserves existing
        callers that inspect or replace these public lists directly.
        """
        action = str(action or "").strip().lower()
        if action not in {"duplicate", "insert_after", "delete", "move"}:
            raise ValueError("Неизвестное действие с элементом шоу-плана.")
        zero_index = index - 1
        if zero_index < 0 or zero_index >= len(items):
            raise ValueError("Элемент шоу-плана не найден.")
        if zero_index <= active_index or zero_index < next_index:
            raise ValueError("Нельзя менять уже идущий или завершённый элемент эфира.")
        item = items[zero_index]

        if action == "delete":
            removed = items.pop(zero_index)
            stale_audio_ids.discard(id(removed))
            selected_index = min(index, len(items))
        elif action == "move":
            target_zero = target_index - 1
            if target_zero < next_index or target_zero >= len(items):
                raise ValueError("Переместить блок можно только в будущую часть плана.")
            moved = items.pop(zero_index)
            items.insert(target_zero, moved)
            selected_index = target_zero + 1
        else:
            if action == "insert_after":
                source = item if item.kind == "speech" else next(
                    (candidate for candidate in items if candidate.kind == "speech"),
                    None,
                )
                if source is None:
                    raise ValueError("В плане нет речевого блока, из которого можно создать черновик.")
                clone = PlannedItem(
                    kind="speech",
                    path=source.path,
                    title="Новая реплика ведущего",
                    text="Введите текст новой реплики.",
                    duration_sec=source.duration_sec,
                )
                stale_audio_ids.add(id(clone))
            else:
                clone = PlannedItem(
                    kind=item.kind,
                    path=item.path,
                    title=item.title,
                    text=item.text,
                    duration_sec=item.duration_sec,
                    history_keys=list(item.history_keys),
                    news_items=[dict(news) for news in item.news_items],
                )
                if id(item) in stale_audio_ids:
                    stale_audio_ids.add(id(clone))
            items.insert(zero_index + 1, clone)
            selected_index = index + 1

        return {"action": action, "selected_index": selected_index, "count": len(items)}
