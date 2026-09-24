from pathlib import Path

import pytest

from ai_truck_radio_app.show_plan_editor import ShowPlanEditor
from ai_truck_radio_app.tracks import PlannedItem


def _item(tmp_path: Path, kind: str = "speech", name: str = "speech.mp3") -> PlannedItem:
    path = tmp_path / name
    path.write_bytes(b"ID3")
    return PlannedItem(kind, path, "Ведущие" if kind == "speech" else "Трек", "Текст" if kind == "speech" else "", 5)


def test_audio_path_rejects_existing_file_outside_cache(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = _item(tmp_path, name="outside.mp3")

    assert ShowPlanEditor.audio_path([outside], 1, set(), cache) is None


def test_mutate_duplicate_keeps_stale_audio_marker(tmp_path: Path):
    item = _item(tmp_path)
    items = [item]
    stale = {id(item)}

    result = ShowPlanEditor.mutate(
        items,
        stale,
        index=1,
        action="duplicate",
        target_index=0,
        active_index=-1,
        next_index=0,
    )

    assert result == {"action": "duplicate", "selected_index": 2, "count": 2}
    assert id(items[1]) in stale
    assert items[1].text == item.text


def test_preview_omits_later_items_without_truncating_script(tmp_path: Path):
    first = _item(tmp_path, name="first.mp3")
    second = _item(tmp_path, name="second.mp3")
    first.text = "а" * 4_000
    second.text = "второй полный текст"

    preview = ShowPlanEditor.preview(
        [first, second],
        active_index=0,
        stale_audio_ids=set(),
        cfg={"show_plan_preview_items": 80, "show_plan_preview_max_chars": 4_000},
    )

    assert len(preview) == 1
    assert preview[0]["text"] == first.text


def test_mutate_rejects_past_items(tmp_path: Path):
    items = [_item(tmp_path)]
    with pytest.raises(ValueError, match="Нельзя менять"):
        ShowPlanEditor.mutate(
            items,
            set(),
            index=1,
            action="delete",
            target_index=0,
            active_index=-1,
            next_index=1,
        )
