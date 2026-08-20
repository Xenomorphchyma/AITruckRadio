from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

import ai_truck_radio_app.engine as engine_module
from ai_truck_radio_app.context import read_news_line, should_include_news
from ai_truck_radio_app.engine import RadioEngine
from ai_truck_radio_app.news_agent import NewsAgent
from ai_truck_radio_app.news_history import load_events


class FakeLM:
    def __init__(self, *responses: dict) -> None:
        self.responses = [json.dumps(response, ensure_ascii=False) for response in responses]
        self.calls = []

    def list_models(self):
        return ["fake-news-model"]

    def generate_plain_text(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.responses:
            raise AssertionError("Unexpected LM call")
        return self.responses.pop(0)


def make_cfg(tmp_path: Path) -> dict:
    news_file = tmp_path / "news.txt"
    news_file.write_text("# manual fallback\nЛокальная редакция сообщает о городском событии.\n", encoding="utf-8")
    return {
        "lm_model": "local-model",
        "news_file": str(news_file),
        "news_lines_per_insert": 1,
        "news_agent_queries": ["city event"],
        "news_agent_official_domains": ["official.gov"],
        "news_agent_cache_file": str(tmp_path / "news-cache.json"),
        "news_agent_history_file": str(tmp_path / "news-history.json"),
        "news_agent_results_per_query": 8,
        "news_agent_max_pages": 8,
        "news_agent_min_page_chars": 20,
        "news_agent_page_chars": 2000,
        "news_agent_total_evidence_chars": 10000,
        "news_agent_source_ttl_sec": 3600,
        "news_agent_cache_ttl_sec": 1800,
        "news_agent_min_independent_domains": 2,
        "news_agent_max_items": 8,
        "news_agent_factcheck_enabled": True,
    }


def source_fakes():
    search_calls = []
    read_calls = []

    def search(query, timeout, limit):
        search_calls.append((query, timeout, limit))
        if query.startswith("site:official.gov"):
            return [{"url": "https://official.gov/briefing", "title": "Official briefing"}]
        return [
            {"url": "https://first.example/story", "title": "First report"},
            {"url": "https://second.example/confirmation", "title": "Independent confirmation"},
            {"url": "https://www.first.example/story", "title": "Duplicate URL"},
        ]

    pages = {
        "https://first.example/story": {
            "url": "https://first.example/story",
            "title": "City event reported",
            "text": "The city event was confirmed by the local service. " * 4,
            "published_at": "2026-07-13T08:00:00Z",
        },
        "https://second.example/confirmation": {
            "url": "https://second.example/confirmation",
            "title": "Second newsroom confirms event",
            "text": "An independent newsroom confirmed the same city event. " * 4,
            "published_at": "2026-07-13T08:05:00Z",
        },
        "https://official.gov/briefing": {
            "url": "https://official.gov/briefing",
            "title": "Agency briefing",
            "text": "The agency published its official briefing and exact figures. " * 4,
            "published_at": "2026-07-13T08:10:00Z",
        },
    }

    def read(url, timeout, max_chars):
        read_calls.append((url, timeout, max_chars))
        return dict(pages[url])

    return search, read, search_calls, read_calls


def draft_response():
    return {
        "items": [
            {
                "title": "Городская служба подтвердила событие",
                "summary": "Городская служба сообщила о событии, а независимая редакция подтвердила основные детали.",
                "source_ids": [2, 3],
            },
            {
                "title": "Ведомство выпустило официальный брифинг",
                "summary": "Ведомство опубликовало официальный брифинг с проверенными редакцией точными данными.",
                "source_ids": [1],
            },
            {
                "title": "Сообщение только одного издания",
                "summary": "Пока эту отдельную деталь описывает только одна редакция, независимого подтверждения ещё нет.",
                "source_ids": [2],
            },
            {
                "title": "Новость с несуществующим источником",
                "summary": "У этой новости достаточно длинный текст, но ссылка на источник некорректна и должна быть отклонена.",
                "source_ids": [99],
            },
            {
                "title": "Черновик с противоречащими источниками",
                "summary": "Оба источника упомянули тему, но их сведения противоречат формулировке этого редакционного черновика.",
                "source_ids": [2, 3],
            },
        ]
    }


def factcheck_response():
    return {
        "items": [
            {"draft_id": "news-1", "decision": "verified", "source_ids": [2, 3], "notes": "Два независимых подтверждения."},
            {"draft_id": "news-2", "decision": "verified", "source_ids": [1], "notes": "Официальная публикация."},
            {"draft_id": "news-3", "decision": "verified", "source_ids": [2], "notes": "Других подтверждений нет."},
            {"draft_id": "news-5", "decision": "rejected", "source_ids": [2, 3], "notes": "Черновик противоречит источникам."},
        ]
    }


def test_collection_uses_injected_io_source_ids_and_official_path(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    search, read, search_calls, read_calls = source_fakes()
    agent = NewsAgent(cfg, search_fn=search, read_fn=read, now_fn=lambda: 1000)

    research = agent.collect_sources()

    assert [source["source_id"] for source in research["sources"]] == [1, 2, 3]
    assert any(call[0] == "site:official.gov city event" for call in search_calls)
    assert len(read_calls) == 3
    by_url = {source["url"]: source for source in research["sources"]}
    assert by_url["https://first.example/story"]["published_at"] == "2026-07-13T08:00:00Z"
    assert research["sources"][0]["fetched_at"] == 1000
    assert research["sources"][0]["expires_at"] == 4600
    assert research["sources"][0]["official"] is True
    assert research["sources"][0]["official_path"] is True


def test_collection_expands_section_into_direct_article_links(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    cfg["news_agent_official_domains"] = ["official.gov"]

    def search(_query, _timeout, _limit):
        return [{"url": "https://official.gov/news", "title": "News"}]

    def read(url, _timeout, _max_chars):
        if url == "https://official.gov/news":
            return {
                "url": url,
                "title": "News",
                "text": "Новости ведомства " * 10,
                "published_at": "",
                "links": [
                    "https://official.gov/sport-football",
                    "https://official.gov/2026/08/03/fresh-story",
                ],
            }
        return {
            "url": url,
            "title": "Fresh story",
            "text": "Подробности подтверждённой свежей новости. " * 5,
            "published_at": "2026-08-03T06:30:00Z",
            "links": [],
        }

    research = NewsAgent(cfg, search_fn=search, read_fn=read, now_fn=lambda: 1000).collect_sources()
    assert research["sources"][0]["url"] == "https://official.gov/2026/08/03/fresh-story"
    assert research["sources"][0]["direct_article"] is True
    assert research["sources"][0]["official"] is True


def test_collection_runs_search_jobs_concurrently(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    cfg["news_agent_queries"] = ["one", "two"]
    cfg["news_agent_official_domains"] = ["official.gov"]
    cfg["news_agent_search_workers"] = 4
    started = []

    def search(query, _timeout, _limit):
        started.append(query)
        time.sleep(0.03)
        return []

    before = time.monotonic()
    NewsAgent(cfg, search_fn=search, read_fn=lambda *_: {}, now_fn=lambda: 1000).collect_sources()
    elapsed = time.monotonic() - before
    assert len(started) == 4
    assert elapsed < 0.1


def test_two_pass_factcheck_independent_domains_and_official_source(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    search, read, _, _ = source_fakes()
    lm = FakeLM(draft_response(), factcheck_response())
    agent = NewsAgent(cfg, lm, search_fn=search, read_fn=read, now_fn=lambda: 1000)

    pack = agent.build(force=True)
    by_id = {item["draft_id"]: item for item in pack["items"]}

    assert len(lm.calls) == 2
    assert lm.calls[0]["response_schema"]["required"] == ["items"]
    assert "Вторым независимым проходом" in lm.calls[1]["prompt"]
    assert by_id["news-1"]["status"] == "verified"
    assert by_id["news-1"]["status_reason"] == "independent_domains"
    assert by_id["news-1"]["source_domains"] == ["first.example", "second.example"]
    assert by_id["news-2"]["status"] == "verified"
    assert by_id["news-2"]["official_source_ids"] == [1]
    assert by_id["news-2"]["status_reason"] == "official_source"
    assert by_id["news-3"]["status"] == "review"
    assert by_id["news-3"]["status_reason"] == "insufficient_independent_domains"
    assert by_id["news-4"]["status"] == "rejected"
    assert by_id["news-5"]["status"] == "rejected"
    assert by_id["news-5"]["status_reason"] == "factcheck_rejected"
    assert [entry["status"] for entry in by_id["news-1"]["status_history"]] == ["draft", "verified"]
    assert pack["fallback_used"] is False


def test_official_homepage_without_publication_date_cannot_verify_story(tmp_path: Path) -> None:
    agent = NewsAgent(make_cfg(tmp_path), FakeLM(), now_fn=lambda: 1000)
    items = [{
        "draft_id": "news-1",
        "title": "Недостаточно подтверждённая новость",
        "summary": "Этот текст достаточно длинный для проверки статуса источника.",
        "status": "draft",
        "status_history": [{"status": "draft", "at": 1000}],
        "expires_at": 4600,
    }]
    sources = [{
        "source_id": 1,
        "url": "https://official.gov/",
        "independent_domain": "official.gov",
        "official": True,
        "published_at": "",
        "expires_at": 4600,
    }]
    checked = {"items": [{
        "draft_id": "news-1",
        "decision": "verified",
        "source_ids": [1],
        "notes": "Модель ошибочно согласилась.",
    }]}

    agent._factcheck_items(items, checked, sources, 1000)

    assert items[0]["status"] == "review"
    assert items[0]["status_reason"] == "sources_missing_direct_url_or_date"
    assert items[0]["official_source_ids"] == []


def test_valid_cache_skips_search_and_lm(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    search, read, search_calls, _ = source_fakes()
    first_lm = FakeLM(draft_response(), factcheck_response())
    first = NewsAgent(cfg, first_lm, search_fn=search, read_fn=read, now_fn=lambda: 1000).build(force=True)

    def unexpected_search(query, timeout, limit):
        raise AssertionError("valid cache must skip search")

    cached = NewsAgent(cfg, FakeLM(), search_fn=unexpected_search, read_fn=read, now_fn=lambda: 1100).build()

    assert cached == first
    assert len(search_calls) == 2


def test_expired_cache_is_not_reused(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    search, read, _, _ = source_fakes()
    NewsAgent(cfg, FakeLM(draft_response(), factcheck_response()), search_fn=search, read_fn=read, now_fn=lambda: 1000).build(force=True)

    expired = NewsAgent(cfg, FakeLM(), search_fn=search, read_fn=read, now_fn=lambda: 2801).load_cache()

    assert expired is None


def test_fallback_file_works_without_network_or_lm(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    fallback_path = Path(cfg["news_file"])
    fallback_path.write_text("# comment\nПервая ручная новость. Только проверенный редактором текст.\nВторая ручная новость.\n", encoding="utf-8")
    search_calls = []

    def empty_search(query, timeout, limit):
        search_calls.append(query)
        return []

    agent = NewsAgent(cfg, None, search_fn=empty_search, read_fn=lambda *_: {}, now_fn=lambda: 2000)
    pack = agent.build(force=True)

    assert pack["fallback_used"] is True
    assert pack["fallback_reason"] == "sources_or_lm_unavailable"
    assert [item["status"] for item in pack["items"]] == ["review", "review"]
    assert all(item["origin"] == "fallback_file" and not item["source_ids"] for item in pack["items"])
    scheduled = agent.select_next(pack, at=2100)
    assert scheduled and scheduled["status"] == "scheduled"
    aired = agent.mark_aired(scheduled, at=2200)
    assert aired["status"] == "aired"
    assert [event["status"] for event in load_events(cfg)] == ["scheduled", "aired"]
    assert search_calls


def test_history_deduplicates_a_previously_scheduled_story(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    search, read, _, _ = source_fakes()
    first_agent = NewsAgent(cfg, FakeLM(draft_response(), factcheck_response()), search_fn=search, read_fn=read, now_fn=lambda: 1000)
    first_pack = first_agent.build(force=True)
    scheduled = first_agent.select_next(first_pack, at=1200)
    assert scheduled is not None
    first_agent.mark_aired(scheduled, at=1300)

    second_agent = NewsAgent(cfg, FakeLM(draft_response(), factcheck_response()), search_fn=search, read_fn=read, now_fn=lambda: 1400)
    second_pack = second_agent.build(force=True)
    repeated = next(item for item in second_pack["items"] if item.get("draft_id") == scheduled.get("draft_id"))

    assert repeated["status"] == "rejected"
    assert repeated["status_reason"] == "duplicate"


def test_released_schedule_can_be_selected_again(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    search, read, _, _ = source_fakes()
    agent = NewsAgent(cfg, FakeLM(draft_response(), factcheck_response()), search_fn=search, read_fn=read, now_fn=lambda: 1000)
    pack = agent.build(force=True)
    scheduled = agent.select_next(pack, mode="planned", at=1100)
    assert scheduled and scheduled["status"] == "scheduled"
    released = agent.release(scheduled, mode="plan_deleted", at=1200)
    assert released["status"] == "verified"
    again = agent.select_next(pack, mode="planned", at=1300)
    assert again and again["draft_id"] == scheduled["draft_id"]


def test_news_chance_is_applied_once_and_file_reader_does_not_repeat_it(tmp_path: Path) -> None:
    path = tmp_path / "news.txt"
    path.write_text("Проверенная строка редакции.\n", encoding="utf-8")
    cfg = {"news_enabled": True, "news_chance": 0.5, "news_file": str(path), "news_lines_per_insert": 1}
    calls = []

    def random_once():
        calls.append(True)
        return 0.25

    assert should_include_news(cfg, random_once) is True
    assert len(calls) == 1
    cfg["news_chance"] = 0.0
    assert read_news_line(cfg) == "Проверенная строка редакции."


def test_explicit_empty_planned_news_override_skips_a_second_chance(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = RadioEngine.__new__(RadioEngine)
    engine.cfg = {
        "night_mode_enabled": False,
        "station_style": "универсальное радио",
        "time_context_enabled": False,
        "weather_enabled": False,
        "listener_greetings_enabled": False,
        "entertainment_enabled": False,
        "tts_backend": "none",
        "hosts": [],
    }
    engine.speech_blocks_played = 1
    engine.tracks_played = 0
    engine.last_hour_announcement_hour = -1
    engine.last_greeting_track_index = -9999
    engine.next_greeting_after = 4
    engine.recent_host_texts = []

    def unexpected_chance(cfg):
        raise AssertionError("planned override must not roll news_chance again")

    monkeypatch.setattr(engine_module, "should_include_news", unexpected_chance)
    context = engine.build_context(selected_hosts=[], two_hosts=False, overrides={"news_text": ""})

    assert context["news_text"] == ""
