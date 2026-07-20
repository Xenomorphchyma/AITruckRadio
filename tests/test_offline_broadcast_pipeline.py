from __future__ import annotations

from pathlib import Path

from ai_truck_radio_app.audio_transition import music_speech_crossfade_command
from ai_truck_radio_app.lmstudio import build_compact_host_prompt
from ai_truck_radio_app.news_agent import NewsAgent
from ai_truck_radio_app.show_plan_store import ShowPlanStore
from ai_truck_radio_app.tracks import PlannedItem, Track


class OfflineNewsLM:
    def __init__(self) -> None:
        self.calls = 0

    def list_models(self) -> list[str]:
        return ["offline-small-model"]

    def generate_plain_text(self, *_args: object, **_kwargs: object) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {
                "items": [
                    {
                        "title": "Город открыл новую библиотеку",
                        "summary": "Новая городская библиотека открылась сегодня и уже принимает посетителей.",
                        "source_ids": [1, 2],
                    }
                ]
            }
        return {
            "items": [
                {
                    "draft_id": "news-1",
                    "decision": "verified",
                    "source_ids": [1, 2],
                    "notes": "Событие подтверждено двумя независимыми источниками.",
                }
            ]
        }


def test_full_offline_news_prompt_plan_and_audio_contract(tmp_path: Path) -> None:
    cache_file = tmp_path / "news.json"
    history_file = tmp_path / "news-history.json"
    cfg = {
        "news_agent_cache_file": str(cache_file),
        "news_agent_history_file": str(history_file),
        "news_agent_queries": "новости города",
        "news_agent_min_page_chars": 20,
        "news_agent_max_pages": 4,
        "news_agent_min_independent_domains": 2,
        "news_agent_source_ttl_sec": 3600,
        "news_agent_cache_ttl_sec": 3600,
        "news_agent_factcheck_enabled": True,
        "news_agent_structured_output": True,
        "news_agent_no_think": True,
        "news_agent_model": "local-model",
        "lm_model": "local-model",
        "lm_compact_host_prompt": True,
        "lm_host_prompt_max_chars": 4800,
        "radio_persona": "Готовь короткий безопасный текст музыкального радио.",
    }

    def search(_query: str, _timeout: int, _limit: int) -> list[dict]:
        return [
            {"url": "https://city.example/news/library", "title": "Открытие библиотеки"},
            {"url": "https://press.example/events/library", "title": "Новая библиотека"},
        ]

    def read(url: str, _timeout: int, _max_chars: int) -> dict:
        return {
            "url": url,
            "title": "Новая библиотека открылась",
            "text": "Сегодня в городе открылась новая библиотека. Учреждение уже принимает посетителей.",
            "published_at": "2026-07-13T09:00:00Z",
        }

    agent = NewsAgent(cfg, OfflineNewsLM(), search_fn=search, read_fn=read, now_fn=lambda: 1_752_397_200)
    pack = agent.build(force=True)
    assert pack["fallback_used"] is False
    assert pack["items"][0]["status"] == "verified"
    scheduled = agent.select_next(pack, mode="planned")
    assert scheduled and scheduled["status"] == "scheduled"

    previous = Track(tmp_path / "previous.mp3", "Исполнитель", "Прошлый трек")
    following = Track(tmp_path / "next.mp3", "Исполнитель", "Следующий трек")
    prompt = build_compact_host_prompt(
        cfg,
        previous,
        following,
        {
            "hosts": [{"name": "Максим"}, {"name": "Ирина"}],
            "all_host_names": ["Максим", "Ирина"],
            "two_hosts": True,
            "time_text": "12:00, понедельник, 13 июля 2026",
            "news_text": scheduled["summary"],
            "dj_instruction": "Коротко сообщи новость и подведи к музыке.",
            "dj_topic_label": "проверенная новость",
            "dj_length": "short",
        },
    )
    assert scheduled["summary"] in prompt
    assert len(prompt) <= 4800
    assert "[ПРИОРИТЕТНЫЕ ФАКТЫ]" in prompt

    music_root = tmp_path / "music"
    cache_root = tmp_path / "cache"
    music_root.mkdir()
    (cache_root / "spoken").mkdir(parents=True)
    music = music_root / "track.mp3"
    speech = cache_root / "spoken" / "speech.mp3"
    music.write_bytes(b"music")
    speech.write_bytes(b"speech")
    item = PlannedItem(
        "speech",
        speech,
        "Ведущие",
        "Максим: Проверенная новость. Ирина: А теперь музыка.",
        8.0,
        history_keys=["rubric-key"],
        news_items=[scheduled],
    )
    store = ShowPlanStore(tmp_path / "plan.json", music_root=music_root, cache_root=cache_root)
    store.save([PlannedItem("music", music, "Трек", duration_sec=180.0), item], next_index=1)
    restored = store.load()
    assert restored.next_index == 1
    assert restored.items[1].news_items[0]["status"] == "scheduled"

    command = music_speech_crossfade_command(
        ffmpeg="ffmpeg",
        music_path=music,
        speech_path=speech,
        music_duration_sec=180,
        overlap_sec=4,
        bitrate_kbps=128,
        music_volume=0.78,
        speech_volume=1.45,
    )
    assert "acrossfade=d=4.000" in command[command.index("-filter_complex") + 1]
    assert command[-2:] == ["mp3", "pipe:1"]
