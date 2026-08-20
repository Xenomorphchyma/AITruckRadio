import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_truck_radio_app.config import require_http_url
from ai_truck_radio_app.engine import RadioEngine
from ai_truck_radio_app.ref_voice import safe_voice_slug
from ai_truck_radio_app.text_processing import (
    context_violations_for_host_text,
    normalize_omnivoice_nonverbal_tags,
    normalize_generated_radio_text,
    parse_dialogue_segments,
    postprocess_host_text_for_air,
    sanitize_general_radio_text,
    soften_tts_exclamations,
)


class HostRuntimeFixesTests(unittest.TestCase):
    def test_entertainment_status_distinguishes_sources_from_fallback(self):
        pack = {
            "horoscope": [{}] * 12,
            "riddles": [{}] * 6,
            "wrong_games": [{}] * 3,
            "guest_stories": [{}] * 3,
            "_validation": {
                "fallback_used": {
                    "horoscope": True,
                    "riddles": False,
                    "wrong_games": True,
                    "guest_stories": True,
                }
            },
        }
        status = RadioEngine._entertainment_pack_status(pack, cached=False)
        self.assertEqual(
            "агент: из источников — 6 загадок; резервные — 12 прогнозов, 3 игр, 3 гостевых историй",
            status,
        )

    def test_default_listener_greetings_are_time_neutral(self):
        greetings = (Path(__file__).parents[1] / "data" / "greetings.txt").read_text(encoding="utf-8")
        self.assertNotRegex(greetings.casefold(), r"\b(?:утр\w*|вечер\w*|ноч\w*)\b")

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

    def test_emotion_before_colon_keeps_the_correct_speaker(self):
        text = normalize_omnivoice_nonverbal_tags("Максим: Слушаем. Ирина (смеётся): Вот это история.")
        self.assertIn("Ирина: [laughter] Вот это история.", text)
        segments = parse_dialogue_segments(text, [{"name": "Максим"}, {"name": "Ирина"}])
        self.assertEqual(["Максим", "Ирина"], [speaker for speaker, _spoken in segments])

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

    def test_truck_phrases_are_replaced_without_inventing_evening_context(self):
        # Isolate the replacement table from the preceding sentence-level
        # removal guard, which intentionally drops heavily road-themed lines.
        with patch("ai_truck_radio_app.text_processing.re.compile") as compile_mock:
            compile_mock.return_value.sub.side_effect = lambda _replacement, value: value
            text = sanitize_general_radio_text(
                "Кабина грузовика, фары режут темноту — настроение долгих ночных поездок."
            )
        self.assertEqual(
            "атмосфера студии, музыка звучит особенно атмосферно — настроение спокойного эфира.",
            text,
        )
        self.assertNotRegex(text.lower(), r"вечер|ноч")

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

    def test_horoscope_rejects_unverified_extra_signs(self):
        violations = context_violations_for_host_text(
            "Максим: Близнецы: Сегодня легко заводятся новые идеи. Рак: День просит уюта. Овны: Вас ждёт успех.",
            {
                "host_strict_clock_guard": False,
                "horoscope_expected": [
                    {"sign": "Близнецы", "text": "Сегодня легко заводятся новые идеи."},
                    {"sign": "Рак", "text": "День просит уюта."},
                ],
            },
        )
        self.assertTrue(any("нет проверенного прогноза" in item and "Овен" in item for item in violations))

    def test_horoscope_cannot_invent_when_the_rest_will_air(self):
        violations = context_violations_for_host_text(
            "Ирина: Лев: День для уверенного шага. Остальные знаки продолжим завтра.",
            {
                "host_strict_clock_guard": False,
                "horoscope_expected": [{"sign": "Лев", "text": "День для уверенного шага."}],
            },
        )
        self.assertTrue(any("без выдуманного времени" in item for item in violations))

    def test_weather_claim_with_stress_mark_is_rejected_without_weather_data(self):
        violations = context_violations_for_host_text(
            "Максим: Пого́да отличная — светит яркое солнышко над городом.",
            {"host_strict_clock_guard": False, "weather_text": ""},
        )
        self.assertTrue(any("нет проверенных данных о погоде" in item for item in violations))

    def test_neutral_atmosphere_is_allowed_without_weather_data(self):
        violations = context_violations_for_host_text(
            "Максим: В студии отличная атмосфера, впереди хорошая музыка.",
            {"host_strict_clock_guard": False, "weather_text": ""},
        )
        self.assertEqual([], violations)

    def test_mixed_english_is_rejected_but_real_track_names_are_allowed(self):
        ctx = {
            "host_strict_clock_guard": False,
            "previous_track_name": "65daysofstatic — The Undertow",
            "next_track_name": "A-Ha — Take On Me",
        }
        invalid = context_violations_for_host_text(
            "Максим: Это же beautifully, и теперь всё went по-хорошо.", ctx
        )
        valid = context_violations_for_host_text(
            "Максим: Только что звучали 65daysofstatic — The Undertow, дальше A-Ha — Take On Me.", ctx
        )
        self.assertTrue(any("латинские слова" in item for item in invalid))
        self.assertEqual([], valid)

    def test_repeated_daypart_greeting_is_rejected_after_intro(self):
        violations = context_violations_for_host_text(
            "Максим: Доброе утро, Волна FM приветствует вас снова.",
            {"intro_allowed": False, "host_strict_clock_guard": False},
        )
        self.assertTrue(any("эфир уже идёт" in item for item in violations))

    def test_other_restart_phrases_are_rejected_after_intro(self):
        for text in (
            "Максим: Добро пожаловать на Волну FM.",
            "Максим: Начинаем эфир с отличной музыки.",
            "Ирина: Рада снова приветствовать наших слушателей.",
            "Максим: Приветствую слушателей Волны FM.",
            "Максим: Здравствуйте, дорогие слушатели Волны FM.",
            "Ирина: Всем привет, продолжаем программу.",
            "Максим: Это начало нового дня на Волне FM.",
            "Максим: Готов к новому дню и новой музыке.",
            "Ирина: Новый день начинается с нашей станции.",
            "Ирина: Наша станция начинает свою работу.",
        ):
            with self.subTest(text=text):
                violations = context_violations_for_host_text(
                    text, {"intro_allowed": False, "host_strict_clock_guard": False}
                )
                self.assertTrue(any("эфир уже идёт" in item for item in violations))

    def test_daypart_greeting_is_allowed_in_the_actual_intro(self):
        violations = context_violations_for_host_text(
            "Максим: Доброе утро, Волна FM приветствует слушателей.",
            {"intro_allowed": True, "host_strict_clock_guard": False},
        )
        self.assertEqual([], violations)

    def test_riddle_question_allows_options_but_rejects_answer_declaration(self):
        ctx = {"riddle_question_block": True, "host_strict_clock_guard": False}
        valid = context_violations_for_host_text(
            "Максим: Варианты — время, дождь, музыка. Правильный ответ услышим в следующий выход.", ctx
        )
        invalid = context_violations_for_host_text(
            "Ирина: Правильный ответ на нашу загадку — музыка.", ctx
        )
        self.assertEqual([], valid)
        self.assertTrue(any("нельзя раскрывать" in item for item in invalid))

    def test_riddle_answer_cannot_be_called_yesterdays(self):
        violations = context_violations_for_host_text(
            "Максим: Ответ на нашу вчерашнюю загадку — время.",
            {
                "riddle_answer_block": True,
                "riddle_correct_answer": "время",
                "host_strict_clock_guard": False,
            },
        )
        self.assertTrue(any("предыдущему выходу" in item for item in violations))

    def test_riddle_answer_must_be_explicit_and_match_the_verified_answer(self):
        ctx = {
            "riddle_answer_block": True,
            "riddle_correct_answer": "число шесть",
            "host_strict_clock_guard": False,
        }
        vague = context_violations_for_host_text(
            "Максим: Значит, число шесть. При перевороте получается девять.", ctx
        )
        wrong = context_violations_for_host_text(
            "Максим: Правильный ответ — чашка.", ctx
        )
        valid = context_violations_for_host_text(
            "Максим: Правильный ответ — число шесть. При перевороте получается девять.", ctx
        )
        self.assertTrue(any("объявить явно" in item for item in vague))
        self.assertTrue(any("не прозвучал проверенный" in item for item in wrong))
        self.assertEqual([], valid)

    def test_host_cannot_start_regular_block_with_hello_everyone(self):
        violations = context_violations_for_host_text(
            "Максим: Привет всем. Сегодня играем в загадки.",
            {
                "intro_allowed": False,
                "hosts": [{"name": "Максим"}],
                "host_strict_clock_guard": False,
            },
        )
        self.assertTrue(any("повторного приветствия" in item for item in violations))

    def test_riddle_question_cannot_promise_an_evening_or_tomorrow(self):
        ctx = {"riddle_question_block": True, "host_strict_clock_guard": False}
        for text in (
            "Максим: Ответ прозвучит сегодня вечером после песни.",
            "Ирина: До встречи завтра, тогда и назовём ответ.",
        ):
            with self.subTest(text=text):
                violations = context_violations_for_host_text(text, ctx)
                self.assertTrue(any("в следующий выход" in item for item in violations))

    def test_riddle_question_requires_question_options_and_next_exit_promise(self):
        ctx = {
            "riddle_question_block": True,
            "riddle_question_text": "Что можно держать, не касаясь руками?",
            "riddle_options": ["обещание", "зонт", "микрофон", "гитара"],
            "host_strict_clock_guard": False,
        }
        missing = context_violations_for_host_text(
            "Максим: Следующий трек уже на подходе.", ctx
        )
        valid = context_violations_for_host_text(
            "Максим: Что можно держать, не касаясь руками? Варианты: обещание, зонт, микрофон или гитара. Ответ прозвучит в следующий выход ведущих.",
            ctx,
        )
        self.assertTrue(any("не прозвучала подготовленная загадка" in item for item in missing))
        self.assertTrue(any("варианты ответа" in item for item in missing))
        self.assertTrue(any("следующий выход" in item for item in missing))
        self.assertEqual([], valid)

    def test_wrong_answer_game_rejects_the_real_answer(self):
        violations = context_violations_for_host_text(
            "Ирина: Зелёный, хотя потом выберу фиолетовый.",
            {"wrong_game_correct_answer": "зелёный", "host_strict_clock_guard": False},
        )
        self.assertTrue(any("настоящий правильный ответ" in item for item in violations))

    def test_wrong_answer_game_requires_prepared_question_and_wrong_answer(self):
        ctx = {
            "wrong_game_question": "Сколько ног у кошки?",
            "wrong_game_correct_answer": "четыре",
            "wrong_game_wrong_examples": ["семь с половиной", "одна запасная в кармане"],
            "host_strict_clock_guard": False,
        }
        missing = context_violations_for_host_text(
            "Максим: Следующий трек уже на подходе.", ctx
        )
        valid = context_violations_for_host_text(
            "Максим: Сколько ног у кошки? Ирина: Мой неправильный ответ — семь с половиной.",
            ctx,
        )
        self.assertTrue(any("подготовленный вопрос" in item for item in missing))
        self.assertTrue(any("неправильный ответ" in item for item in missing))
        self.assertEqual([], valid)

    def test_guest_block_requires_a_separate_guest_replica(self):
        violations = context_violations_for_host_text(
            "Максим: Наш гость рассказал забавную историю.",
            {"force_guest": True, "guest_name": "Гость", "host_strict_clock_guard": False},
        )
        self.assertTrue(any("Гость:" in item for item in violations))

    def test_guest_must_keep_the_prepared_story_and_not_invent_a_name(self):
        ctx = {
            "force_guest": True,
            "guest_name": "Гость",
            "guest_story_data": {
                "story": "Хотел поставить будильник, а проснулся от припева любимой песни."
            },
            "host_strict_clock_guard": False,
        }
        valid = context_violations_for_host_text(
            "Максим: Что случилось? Гость: Я хотел поставить будильник, но проснулся от припева любимой песни.",
            ctx,
        )
        invalid = context_violations_for_host_text(
            "Максим: Что случилось? Гость: Меня зовут Алексей, однажды я ехал на работу и включил радио.",
            ctx,
        )
        self.assertEqual([], valid)
        self.assertTrue(any("не сохраняет проверенную историю" in item for item in invalid))
        self.assertTrue(any("вымышленное имя" in item for item in invalid))

    def test_stress_replacement_preserves_sentence_capitalization(self):
        text = postprocess_host_text_for_air(
            "Максим: Музыка звучит особенно атмосферно.",
            {"hosts": [{"name": "Максим"}], "all_host_names": ["Максим"]},
        )
        self.assertIn("Му́зыка", text)

    def test_safe_rubric_fallbacks_preserve_their_rules(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.cfg = {"guest_name": "Гость"}
        hosts = [{"name": "Максим"}, {"name": "Ирина"}, {"name": "Гость"}]

        riddle = engine._safe_entertainment_dialogue(
            {
                "riddle_question_block": True,
                "riddle_question_text": "Что идёт, но не имеет ног",
                "riddle_options": ["время", "дождь", "музыка"],
            },
            hosts,
            None,
        )
        self.assertIn("Ответ прозвучит в следующий выход", riddle)
        self.assertFalse(any("нельзя раскрывать" in item for item in context_violations_for_host_text(
            riddle, {"riddle_question_block": True, "host_strict_clock_guard": False}
        )))

        wrong = engine._safe_entertainment_dialogue(
            {
                "wrong_game_question": "Какого цвета огурец",
                "wrong_game_correct_answer": "зелёный",
                "wrong_game_wrong_examples": ["фиолетовый в горошек"],
            },
            hosts,
            None,
        )
        self.assertNotIn("зелёный", wrong.casefold())
        self.assertIn("фиолетовый в горошек", wrong.casefold())

        guest = engine._safe_entertainment_dialogue(
            {
                "force_guest": True,
                "guest_name": "Гость",
                "guest_story_data": {"story": "Проснулся от припева любимой песни."},
            },
            hosts,
            None,
        )
        self.assertIn("У нас на связи гость эфира", guest)
        self.assertIn("Гость: Проснулся от припева", guest)
        self.assertNotIn("в гостях Гость", guest)

    def test_unlabelled_intro_is_assigned_to_first_selected_host(self):
        text = postprocess_host_text_for_air(
            "Доброе утро. Максим: Начинаем эфир. Ирина: Впереди музыка.",
            {
                "hosts": [{"name": "Максим"}, {"name": "Ирина"}],
                "all_host_names": ["Максим", "Ирина"],
                "host_should_use_stress_marks": False,
            },
        )
        self.assertTrue(text.startswith("Максим: Доброе утро."))

    def test_host_label_spacing_and_stray_dot_are_normalized(self):
        text = postprocess_host_text_for_air(
            "Максим:.Продолжаем эфир. Ирина：   Впереди музыка.",
            {
                "hosts": [{"name": "Максим"}, {"name": "Ирина"}],
                "all_host_names": ["Максим", "Ирина"],
                "host_should_use_stress_marks": False,
            },
        )
        self.assertIn("Максим: Продолжаем эфир.", text)
        self.assertIn("Ирина: Впереди музыка.", text)

    def test_generated_minute_grammar_is_repaired(self):
        text = normalize_generated_radio_text("Сейчас девять часов двадцать один минута утра.")
        self.assertIn("двадцать одна минута", text)

    def test_generated_accusative_minute_grammar_is_repaired(self):
        text = normalize_generated_radio_text("Сейчас девять часов пятьдесят одну минуту утра.")
        self.assertIn("пятьдесят одна минута", text)

    def test_sleeping_sun_is_rejected_without_weather_data(self):
        violations = context_violations_for_host_text(
            "Ирина: Солнце ещё не проснулось, начинаем эфир.",
            {"host_strict_clock_guard": False, "weather_text": ""},
        )
        self.assertTrue(any("нет проверенных данных о погоде" in item for item in violations))

    def test_unverified_yesterday_broadcast_is_rejected_on_intro(self):
        violations = context_violations_for_host_text(
            "Ирина: Особенно после вчерашнего замечательного вечера музыки.",
            {
                "intro_allowed": True,
                "planned_previous_track": "ещё ничего не играло",
                "host_strict_clock_guard": False,
            },
        )
        self.assertTrue(any("вчерашнюю программу" in item for item in violations))

    def test_intro_may_explicitly_say_that_previous_tracks_do_not_exist(self):
        violations = context_violations_for_host_text(
            "Максим: Эфир только начинается, предыдущих треков ещё нет.",
            {
                "intro_allowed": True,
                "planned_previous_track": "ещё ничего не играло",
                "host_strict_clock_guard": False,
            },
        )
        self.assertEqual([], violations)

    def test_reference_voice_slug_is_stable_for_cyrillic_names(self):
        self.assertEqual("maksim_efir", safe_voice_slug("Максим эфир"))

    def test_guest_reference_text_file_is_read_before_tts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "guest.wav"
            text = root / "guest.txt"
            audio.write_bytes(b"RIFF")
            text.write_text("Точный текст референса.", encoding="utf-8")
            engine = RadioEngine.__new__(RadioEngine)
            engine.cfg = {
                "guest_name": "Гость",
                "guest_role": "слушатель",
                "guest_voice_mode": "reference",
                "guest_ref_audio": str(audio),
                "guest_ref_text": str(text),
                "guest_voice_instruct": "male, young adult, russian accent, moderate pitch",
            }
            host = engine._guest_host_cfg()
            self.assertEqual("clone", host["omnivoice_mode"])
            self.assertEqual("Точный текст референса.", host["omnivoice_ref_text"])


if __name__ == "__main__":
    unittest.main()
