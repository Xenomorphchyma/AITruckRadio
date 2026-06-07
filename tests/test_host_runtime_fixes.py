import random
import unittest

from ai_truck_radio_app.config import require_http_url
from ai_truck_radio_app.engine import RadioEngine
from ai_truck_radio_app.text_processing import (
    context_violations_for_host_text,
    normalize_omnivoice_nonverbal_tags,
    postprocess_host_text_for_air,
    soften_tts_exclamations,
)


class HostRuntimeFixesTests(unittest.TestCase):
    def test_only_http_urls_are_accepted(self):
        self.assertEqual("http://127.0.0.1:1234/v1", require_http_url("http://127.0.0.1:1234/v1"))
        with self.assertRaises(ValueError):
            require_http_url("file:///C:/secret.txt")

    def make_engine(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.cfg = {
            "host_intro_count": 2,
            "host_regular_count_min": 1,
            "host_regular_count_max": 1,
            "host_regular_multi_chance": 0.0,
            "hosts": [
                {
                    "name": "Максим",
                    "enabled": True,
                    "intro_enabled": True,
                    "regular_enabled": True,
                    "air_weight": 1.0,
                },
                {
                    "name": "Ирина",
                    "enabled": True,
                    "intro_enabled": True,
                    "regular_enabled": True,
                    "air_weight": 0.0,
                },
            ],
        }
        return engine

    def test_intro_and_regular_host_counts_are_independent(self):
        engine = self.make_engine()
        intro, intro_multi = engine._select_hosts_for_insert(True)
        regular, regular_multi = engine._select_hosts_for_insert(False)
        self.assertEqual({"Максим", "Ирина"}, {host["name"] for host in intro})
        self.assertTrue(intro_multi)
        self.assertEqual(1, len(regular))
        self.assertFalse(regular_multi)

    def test_low_weight_host_is_rare_but_not_disabled(self):
        engine = self.make_engine()
        engine.cfg["hosts"][1]["air_weight"] = 0.2
        random.seed(7)
        names = [engine._select_hosts_for_insert(False)[0][0]["name"] for _ in range(500)]
        self.assertGreater(names.count("Ирина"), 0)
        self.assertLess(names.count("Ирина"), names.count("Максим"))

    def test_parenthetical_laughter_becomes_omnivoice_tag(self):
        text = normalize_omnivoice_nonverbal_tags("Ирина: (усмехаясь) Вот это поворот.")
        self.assertEqual("Ирина: [laughter] Вот это поворот.", text)

    def test_unselected_host_line_is_removed(self):
        text = postprocess_host_text_for_air(
            "Максим: Доброе утро. Ирина: А теперь погода. Максим: Дальше музыка.",
            {
                "hosts": [{"name": "Максим"}],
                "all_host_names": ["Максим", "Ирина"],
                "host_should_use_stress_marks": False,
            },
        )
        self.assertNotIn("Ирина:", text)
        self.assertIn("Максим: Доброе утро.", text)
        self.assertIn("Максим: Дальше музыка.", text)

    def test_exclamation_is_softened_for_tts(self):
        self.assertEqual("Максим: Доброе утро.", soften_tts_exclamations("Максим: Доброе утро!"))

    def test_wrong_city_and_broken_horoscope_are_rejected(self):
        ctx = {
            "host_strict_clock_guard": False,
            "weather_city": "Комсомольск-на-Амуре",
            "horoscope_expected": [{"sign": "Овен", "text": "Не спешите с решениями."}],
        }
        violations = context_violations_for_host_text(
            "Максим: В Москве ясно. Овн: прогноз был про осторожность.",
            ctx,
        )
        self.assertTrue(any("Москву" in item for item in violations))
        self.assertTrue(any("Овен" in item for item in violations))
        self.assertTrue(any("пересказывать" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
