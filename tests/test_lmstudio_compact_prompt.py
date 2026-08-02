# -*- coding: utf-8 -*-
from __future__ import annotations

from ai_truck_radio_app.dialogue_quality import FakeLMStudioClient, make_track
from ai_truck_radio_app.lmstudio import LMStudioClient


def _large_context() -> dict:
    repeated_news = "УНИКАЛЬНАЯ НОВОСТЬ: в городском саду открылась выставка."
    return {
        "intro_allowed": False,
        "two_hosts": True,
        "hosts": [{"name": "Максим"}, {"name": "Ирина"}],
        "all_host_names": ["Максим", "Ирина", "Алексей"],
        "computer_hour": 16,
        "time_text": "16:05, понедельник, 13 июля 2026",
        "spoken_time_text": "шестнадцать часов пять минут дня",
        "weather_city": "Хабаровск",
        "weather_text": "Хабаровск: дождь, плюс 17 градусов, ветер 4 метра в секунду",
        "news_text": repeated_news,
        "greeting_text": "Светлана передаёт привет коллегам.",
        "entertainment_text": "Загадка: что становится мокрее, пока сушит?",
        "entertainment_instruction": "Задать загадку без ответа.",
        "previous_track_info": "ПРОФИЛЬ_ПРЕДЫДУЩЕГО " + "очень длинный архив " * 300,
        "next_track_info": "ПРОФИЛЬ_СЛЕДУЮЩЕГО " + "ещё один длинный архив " * 300,
        "recent_host_texts": [f"СТАРЫЙ_ЭФИР_{index} " + "повтор " * 80 for index in range(12)],
        "dj_length": "short",
        "dj_instruction": "Погода, новость, привет и короткая загадка.",
        "dj_topic_label": "слушатели",
    }


def _post_payload(client: FakeLMStudioClient) -> dict:
    return next(request["payload"] for request in client.requests if request["method"] == "POST")


def test_model_probe_distinguishes_offline_server_from_empty_model_list() -> None:
    client = LMStudioClient({"lm_base_url": "http://127.0.0.1:1234/v1", "lm_timeout_sec": 1, "lm_model": "local-model"})
    client._request_json = lambda *_args, **_kwargs: {"data": []}  # type: ignore[method-assign]
    assert client.probe_models() == {"reachable": True, "models": [], "error": ""}

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    client._request_json = unavailable  # type: ignore[method-assign]
    probe = client.probe_models()
    assert probe["reachable"] is False
    assert probe["models"] == []
    assert "connection refused" in probe["error"]


def test_compact_prompt_is_bounded_prioritized_and_preserves_speaker_schema() -> None:
    ctx = _large_context()
    client = FakeLMStudioClient(
        ["Максим: Продолжаем эфир.\nИрина: А сейчас музыка."],
        {
            "lm_host_prompt_max_chars": 4200,
            "lm_host_system_max_chars": 500,
            "lm_max_tokens": 2000,
            "lm_append_no_think": True,
            "radio_persona": "Большая персона. " * 300,
        },
    )
    client.generate_host_line(
        make_track({"artist": "Алёна", "title": "Маяк"}, label="previous"),
        make_track({"artist": "Север", "title": "Тихий свет"}, label="next"),
        ctx,
    )
    payload = _post_payload(client)
    system_prompt = payload["messages"][0]["content"]
    prompt = payload["messages"][1]["content"]

    assert len(system_prompt) <= 500
    assert len(prompt) <= 4200
    assert payload["max_tokens"] == 360
    for required in (
        "[ПРИОРИТЕТНЫЕ ФАКТЫ]",
        "[СХЕМА ОТВЕТА]",
        "Максим",
        "Ирина",
        "Алёна — Маяк",
        "Север — Тихий свет",
        "Хабаровск",
        "УНИКАЛЬНАЯ НОВОСТЬ",
        "Светлана",
        "Загадка",
        "/no_think",
    ):
        assert required in prompt
    assert prompt.count("УНИКАЛЬНАЯ НОВОСТЬ") == 1
    assert "СТАРЫЙ_ЭФИР_0" not in prompt
    assert len(prompt) < len(ctx["previous_track_info"]) + len(ctx["next_track_info"])


def test_compact_prompt_is_materially_smaller_than_legacy_prompt() -> None:
    ctx = _large_context()
    previous = make_track({"artist": "Алёна", "title": "Маяк"}, label="previous")
    next_track = make_track({"artist": "Север", "title": "Тихий свет"}, label="next")
    compact = FakeLMStudioClient(["Максим: Тест.\nИрина: Музыка."], {"lm_compact_host_prompt": True})
    legacy = FakeLMStudioClient(["Максим: Тест.\nИрина: Музыка."], {"lm_compact_host_prompt": False})
    compact.generate_host_line(previous, next_track, ctx)
    legacy.generate_host_line(previous, next_track, ctx)
    compact_prompt = _post_payload(compact)["messages"][1]["content"]
    legacy_prompt = _post_payload(legacy)["messages"][1]["content"]
    assert len(compact_prompt) <= 4800
    assert len(compact_prompt) < len(legacy_prompt) * 0.5


def test_compact_prompt_forbids_weather_when_only_city_is_configured() -> None:
    ctx = _large_context()
    ctx["weather_text"] = ""
    client = FakeLMStudioClient(["Максим: В студии хорошее настроение."], {"lm_compact_host_prompt": True})
    client.generate_host_line(None, make_track({"artist": "Север", "title": "Тихий свет"}, label="next"), ctx)
    prompt = _post_payload(client)["messages"][1]["content"]

    assert "Проверенных данных о погоде НЕТ" in prompt
    assert "Погода: Хабаровск" not in prompt
    assert "не делай выводов о них по времени" in prompt


def test_explicit_riddle_question_flag_never_turns_into_answer_mode() -> None:
    ctx = _large_context()
    ctx.update({
        "riddle_question_block": True,
        "entertainment_instruction": "Задай загадку; ответ прозвучит в следующий выход ведущих.",
    })
    client = FakeLMStudioClient(["Максим: Загадка."], {"lm_compact_host_prompt": True})
    client.generate_host_line(None, make_track({"artist": "Север", "title": "Свет"}, label="next"), ctx)
    prompt = _post_payload(client)["messages"][1]["content"]

    assert "Задай загадку без ответа" in prompt
    assert "В блоке ответа сначала назови ответ" not in prompt


def test_explicit_riddle_answer_flag_uses_answer_mode() -> None:
    ctx = _large_context()
    ctx.update({
        "riddle_answer_block": True,
        "entertainment_instruction": "Назови ответ на прошлую загадку.",
    })
    client = FakeLMStudioClient(["Максим: Ответ — время."], {"lm_compact_host_prompt": True})
    client.generate_host_line(None, make_track({"artist": "Север", "title": "Свет"}, label="next"), ctx)
    prompt = _post_payload(client)["messages"][1]["content"]

    assert "В блоке ответа сначала назови ответ" in prompt
    assert "не называй её вчерашней" in prompt


def test_wrong_answer_prompt_forbids_saying_the_real_answer() -> None:
    ctx = _large_context()
    ctx.update({
        "wrong_game_question": "Какого цвета огурец?",
        "wrong_game_correct_answer": "зелёный",
        "entertainment_instruction": "Ответь намеренно неправильно.",
        "dj_topic_label": "игра «ответь неправильно»",
    })
    client = FakeLMStudioClient(["Ирина: Фиолетовый."], {"lm_compact_host_prompt": True})
    client.generate_host_line(None, make_track({"artist": "Север", "title": "Свет"}, label="next"), ctx)
    prompt = _post_payload(client)["messages"][1]["content"]

    assert "Настоящий правильный ответ" in prompt
    assert "не произноси вообще" in prompt


def test_guest_prompt_forbids_inventing_another_story_or_name() -> None:
    ctx = _large_context()
    ctx.update({
        "force_guest": True,
        "guest_name": "Гость",
        "guest_story_data": {"story": "Гость проснулся от припева любимой песни."},
        "entertainment_text": "Гость проснулся от припева любимой песни.",
    })
    ctx["hosts"] = [{"name": "Максим"}, {"name": "Ирина"}, {"name": "Гость"}]
    client = FakeLMStudioClient(["Гость: История."], {"lm_compact_host_prompt": True})
    client.generate_host_line(None, make_track({"artist": "Север", "title": "Свет"}, label="next"), ctx)
    prompt = _post_payload(client)["messages"][1]["content"]

    assert "не придумывай ему имя" in prompt
    assert "другую историю" in prompt


def test_structured_plain_text_schema_is_unchanged_by_host_prompt_compaction() -> None:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    client = FakeLMStudioClient(['{"answer":"готово"}'])
    result = client.generate_plain_text("Верни объект", structured_output=True, response_schema=schema)
    payload = _post_payload(client)
    assert result == '{"answer":"готово"}'
    assert payload["response_format"]["json_schema"]["schema"] == schema
    assert payload["response_format"]["json_schema"]["strict"] is True
