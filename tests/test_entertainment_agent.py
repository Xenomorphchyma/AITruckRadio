# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_truck_radio_app.entertainment_agent import (
    EntertainmentAgent,
    SIGNS,
    _compact_evidence,
    _retain_factchecked_originals,
    _validate_pack,
)
from ai_truck_radio_app.entertainment_history import clear_history, filter_unused, mark_used, prompt_exclusions
from ai_truck_radio_app.web_research import SearchParser


def fallback_pack():
    return {
        "horoscope": [{"sign": sign, "text": f"Fallback {sign}"} for sign in SIGNS],
        "riddles": [{"question": "Fallback?", "options": ["A", "B"], "answer": "A", "explanation": "Fallback"}],
        "wrong_games": [{"question": "Fallback?", "correct": "A", "wrong_examples": ["B", "C", "D"]}],
        "guest_stories": [],
    }


class EntertainmentAgentTests(unittest.TestCase):
    def test_search_parser_ignores_navigation_after_domain_filtering(self) -> None:
        parser = SearchParser()
        parser.feed(
            '<a href="https://r.search.yahoo.com/x/RU=https%3A%2F%2Fexample.com%2Friddle/RK=1/RS=x">'
            "Example riddle</a>"
        )
        self.assertEqual(parser.results[0]["url"], "https://example.com/riddle")

    def test_evidence_marks_topic_and_source(self) -> None:
        text = _compact_evidence(
            [{"topic": "riddles", "url": "https://example.com", "title": "Test", "text": "Evidence"}],
            2000,
        )
        self.assertIn("[SOURCE 1]", text)
        self.assertIn("TOPIC: riddles", text)

    def test_accepts_only_riddle_with_confirmed_source_and_answer_option(self) -> None:
        data = {
            "riddles": [
                {
                    "question": "Сколько дней в неделе?",
                    "options": ["Шесть", "Семь", "Восемь"],
                    "answer": "Семь",
                    "explanation": "Это календарная неделя.",
                    "source_ids": [1],
                },
                {
                    "question": "Непроверенная загадка?",
                    "options": ["Да", "Нет"],
                    "answer": "Может быть",
                    "explanation": "Ответа среди вариантов нет.",
                    "source_ids": [1],
                },
            ]
        }
        result = _validate_pack(data, fallback_pack(), 12, 1)
        self.assertEqual(len(result["riddles"]), 1)
        self.assertEqual(result["riddles"][0]["answer"], "Семь")

    def test_partial_horoscope_does_not_replace_fallback(self) -> None:
        data = {
            "horoscope": [
                {"sign": "Овен", "text": "Спокойно проверьте планы и оставьте место для приятной импровизации.", "source_ids": [1]}
            ]
        }
        fallback = fallback_pack()
        result = _validate_pack(data, fallback, 12, 1)
        self.assertEqual(result["horoscope"], fallback["horoscope"])

    def test_invalid_source_id_rejects_generated_game(self) -> None:
        data = {
            "wrong_games": [
                {
                    "question": "Столица Франции?",
                    "correct": "Париж",
                    "wrong_examples": ["Луна", "Чайник", "Суббота"],
                    "comment": "Отвечаем неправильно.",
                    "source_ids": [99],
                }
            ]
        }
        fallback = fallback_pack()
        result = _validate_pack(data, fallback, 12, 1)
        self.assertEqual(result["wrong_games"], fallback["wrong_games"])

    def test_history_filters_used_riddle_and_exposes_only_short_question(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = {
                "entertainment_history_file": str(Path(tmp) / "history.json"),
                "entertainment_history_max_items": 100,
            }
            used = {"question": "Что можно услышать, но нельзя увидеть?", "answer": "Эхо"}
            fresh = {"question": "Что становится мокрее, пока сушит?", "answer": "Полотенце"}
            mark_used(cfg, "riddle", used, mode="live")
            self.assertEqual(filter_unused(cfg, "riddle", [used, fresh]), [fresh])
            self.assertEqual(prompt_exclusions(cfg), [used["question"]])
            paraphrase = {"question": "Что нельзя увидеть, но можно услышать?", "answer": "Эхо"}
            self.assertEqual(filter_unused(cfg, "riddle", [paraphrase]), [])

    def test_factcheck_keeps_original_game_payload(self) -> None:
        original = [{
            "question": "Какой химический символ у серебра?",
            "correct": "Ag",
            "wrong_examples": ["Au", "Cu", "Zn"],
        }]
        checked = [{
            "question": "Какой символ у серебра?",
            "correct": "Ag",
            "wrong_examples": ["Au"],
        }]
        self.assertEqual(_retain_factchecked_originals(original, checked), original)

    def test_daily_cache_contains_sources_validation_and_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = {
                "entertainment_daily_cache_dir": tmp,
                "entertainment_model": "test-model",
            }
            lm = type("FakeLM", (), {"list_models": lambda self: ["test-model"]})()
            agent = EntertainmentAgent(cfg, lm)
            pack = fallback_pack()
            validation = {"raw_counts": {"riddles": 1}, "fallback_used": {"riddles": False}}
            research = {
                "queries": ["test query"],
                "pages": [{
                    "source_id": 1,
                    "topic": "riddles",
                    "query": "test query",
                    "title": "Source",
                    "url": "https://example.com",
                    "text": "Evidence text",
                }],
            }
            path = agent._save_daily_cache(pack, research, validation)
            self.assertTrue(path.exists())
            loaded = agent.load_daily_cache()
            self.assertEqual(loaded["riddles"], pack["riddles"])
            self.assertEqual(loaded["_validation"], validation)
            self.assertEqual(loaded["_research"]["sources"][0]["url"], "https://example.com")

    def test_clear_history_removes_only_history_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            cfg = {"entertainment_history_file": str(path), "entertainment_history_max_items": 100}
            mark_used(cfg, "riddle", {"question": "Test?"})
            self.assertEqual(clear_history(cfg), 1)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
