# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_truck_radio_app.dialogue_quality import (
    FakeLMStudioClient,
    evaluate_dialogue_quality,
    fallback_dialogue,
    make_track,
)


CORPUS_PATH = Path(__file__).parent / "dialogue_corpus" / "radio_dialogues.json"


def load_corpus() -> list[dict]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", load_corpus(), ids=lambda case: case["id"])
def test_dialogue_regression_corpus_is_offline_and_tts_safe(case: dict) -> None:
    client = FakeLMStudioClient([case["raw_response"]])
    text = client.generate_host_line(
        make_track(case.get("previous"), label="previous"),
        make_track(case.get("next"), label="next"),
        case["context"],
    )

    report = evaluate_dialogue_quality(text, case["context"], case["expects"])
    assert report.ok, f"{case['id']}: {report.violations}; text={text!r}"
    assert all(request["url"].startswith("http://offline.invalid/") for request in client.requests)
    assert any(request["method"] == "POST" for request in client.requests)
    assert not client._completions


def test_fake_transport_is_deterministic_and_never_uses_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def network_must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in dialogue corpus tests")

    monkeypatch.setattr("urllib.request.urlopen", network_must_not_run)
    ctx = {"hosts": [{"name": "Максим"}]}
    first = FakeLMStudioClient([""]).generate_host_line(None, None, ctx)
    second = FakeLMStudioClient([""]).generate_host_line(None, None, ctx)
    assert first == second == fallback_dialogue(ctx)


def test_quality_contract_rejects_wrong_speaker_order_unsupported_fact_and_road_cliche() -> None:
    ctx = {
        "hosts": [{"name": "Максим"}, {"name": "Ирина"}],
        "all_host_names": ["Максим", "Ирина"],
        "computer_hour": 14,
        "time_text": "14:00, понедельник, 13 июля 2026",
    }
    report = evaluate_dialogue_quality(
        "Ирина: Учёные доказали, что эта песня лечит усталость в кабине грузовика. Максим: Дальше музыка.",
        ctx,
        {"speaker_sequence": ["Максим", "Ирина"], "forbidden_facts": ["Учёные доказали"]},
    )
    assert not report.ok
    assert any("очередность" in item for item in report.violations)
    assert any("неподтверждённый" in item for item in report.violations)
    assert any("дорожное" in item for item in report.violations)


def test_quality_contract_rejects_leftover_meta_markdown_and_unlabelled_tts_text() -> None:
    report = evaluate_dialogue_quality(
        "```\n<think>plan</think>\n- Включается музыка\n```",
        {"hosts": [{"name": "Максим"}]},
        {},
    )
    assert not report.ok
    assert any("markdown" in item for item in report.violations)
    assert any("TTS" in item for item in report.violations)
    assert any("подписи" in item for item in report.violations)


def test_quality_contract_rejects_unknown_speaker_prefix_before_parsing() -> None:
    ctx = {"hosts": [{"name": "Максим"}], "computer_hour": 14}
    report = evaluate_dialogue_quality(
        "Алексей: Этой реплики в эфире быть не должно. Максим: Продолжаем музыку.",
        ctx,
        {"speaker_sequence": ["Максим"]},
    )
    assert not report.ok
    assert any("неизвестный префикс" in item and "Алексей" in item for item in report.violations)


def test_quality_contract_allows_rubric_content_labels() -> None:
    report = evaluate_dialogue_quality(
        "Максим: Вопрос: сколько ног у кошки? Варианты: обещание, зонт или микрофон.",
        {"hosts": [{"name": "Максим"}], "computer_hour": 14},
        {"speaker_sequence": ["Максим"]},
    )
    assert report.ok, report.violations


def test_quality_contract_allows_horoscope_and_data_driven_content_labels() -> None:
    ctx = {
        "hosts": [{"name": "Ирина"}],
        "computer_hour": 14,
        "horoscope_expected": [{"sign": "Овен", "text": "Не спешите."}],
    }
    report = evaluate_dialogue_quality(
        "Ирина: Гороскоп на сегодня. Овен: не спешите. Итог: оставьте время для музыки.",
        ctx,
        {"speaker_sequence": ["Ирина"], "allowed_content_labels": ["Итог"]},
    )
    assert report.ok, report.violations


def test_quality_contract_rejects_unsupported_authority_claim() -> None:
    report = evaluate_dialogue_quality(
        "Максим: Эксперты утверждают, что эта песня улучшает память. Дальше музыка.",
        {
            "hosts": [{"name": "Максим"}],
            "computer_hour": 14,
            "entertainment_instruction": "Скажи, что эксперты утверждают нечто интересное.",
        },
        {"speaker_sequence": ["Максим"]},
    )
    assert not report.ok
    assert any("неподтверждённая ссылка на авторитет" in item for item in report.violations)


def test_quality_contract_allows_authority_claim_grounded_in_context_or_contract() -> None:
    ctx = {
        "hosts": [{"name": "Максим"}],
        "computer_hour": 14,
        "news_text": "По данным городской метеостанции, ветер ослабевает.",
    }
    grounded = evaluate_dialogue_quality(
        "Максим: По данным городской метеостанции, ветер ослабевает. Продолжаем музыку.",
        ctx,
        {"speaker_sequence": ["Максим"]},
    )
    explicitly_allowed = evaluate_dialogue_quality(
        "Максим: Исследования показывают: знакомая музыка помогает настроиться на работу.",
        {"hosts": [{"name": "Максим"}], "computer_hour": 14},
        {
            "speaker_sequence": ["Максим"],
            "allowed_authority_claims": ["Исследования показывают"],
        },
    )
    assert grounded.ok, grounded.violations
    assert explicitly_allowed.ok, explicitly_allowed.violations
