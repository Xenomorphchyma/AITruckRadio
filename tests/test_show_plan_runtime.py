import copy
import http.client
import json
import tempfile
import threading
import unittest
import urllib.parse
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock

from ai_truck_radio_app.config import DEFAULT_CONFIG
from ai_truck_radio_app.engine import RadioEngine
from ai_truck_radio_app.server import make_handler
from ai_truck_radio_app.tracks import PlannedItem


class _PlanTTS:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)

    def get_or_create_dialogue_mp3(self, text, _hosts):
        path = self.cache_dir / "spoken" / "edited.mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("ID3" + text).encode("utf-8"))
        return path


class _FailingPlanTTS:
    def get_or_create_dialogue_mp3(self, _text, _hosts):
        raise RuntimeError("synthesis failed")


class ShowPlanRuntimeTests(unittest.TestCase):
    def make_engine(self, root):
        engine = RadioEngine.__new__(RadioEngine)
        engine.cfg = {"max_host_text_chars": 4000, "show_plan_preview_items": 80, "show_plan_preview_max_chars": 120000}
        engine.cache_dir = Path(root) / "cache"
        engine.cache_dir.mkdir()
        engine.plan_lock = threading.Lock()
        engine.show_plan_active_index = -1
        engine.show_plan_index = 0
        engine.show_plan_status = ""
        engine._show_plan_stale_audio_ids = set()
        engine.tts = _PlanTTS(engine.cache_dir)
        engine._save_current_show_plan = lambda: None
        return engine

    def test_edit_invalidates_old_audio_and_rerender_restores_matching_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.make_engine(tmp)
            old = engine.cache_dir / "spoken" / "old.mp3"
            old.parent.mkdir(parents=True)
            old.write_bytes(b"ID3 old")
            item = PlannedItem("speech", old, "Ведущие", "Старый текст", 12)
            engine.show_plan = [item]

            saved = engine.update_show_plan_item_text(1, "Новый полный текст", rerender=False)
            self.assertFalse(saved["audio_ready"])
            self.assertIsNone(engine.get_show_plan_item_audio(1))
            self.assertEqual("Новый полный текст", item.text)

            rendered = engine.update_show_plan_item_text(1, "Новый полный текст", rerender=True)
            self.assertTrue(rendered["audio_ready"])
            self.assertEqual("ID3Новый полный текст", engine.get_show_plan_item_audio(1).read_text(encoding="utf-8"))

    def test_preview_preserves_whole_text_and_marks_current_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.make_engine(tmp)
            audio = engine.cache_dir / "spoken" / "one.mp3"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"ID3")
            full_text = "Полный текст " * 80
            item = PlannedItem("speech", audio, "Ведущие", full_text, 10)
            preview = engine._show_plan_preview([item], 0, set())
            self.assertEqual(full_text, preview[0]["text"])
            self.assertTrue(preview[0]["active"])
            self.assertTrue(preview[0]["audio_ready"])

    def test_preview_reports_every_canonical_host_from_one_line_dialogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.make_engine(tmp)
            engine.cfg["hosts"] = [
                {"name": "Максим", "aliases": ["Макс"]},
                {"name": "Ирина", "aliases": ["Ира"]},
            ]
            audio = engine.cache_dir / "spoken" / "duo.mp3"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"ID3")
            item = PlannedItem(
                "speech",
                audio,
                "Ведущие в эфире",
                "Максим: Начинаем эфир. Ира: И продолжаем вместе.",
                10,
            )

            preview = engine._show_plan_preview([item], -1, set())

            self.assertEqual(["Максим", "Ирина"], preview[0]["hosts"])

    def test_failed_rerender_preserves_previous_text_and_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.make_engine(tmp)
            old = engine.cache_dir / "spoken" / "old.mp3"
            old.parent.mkdir(parents=True)
            old.write_bytes(b"ID3 old")
            item = PlannedItem("speech", old, "Ведущие", "Старый текст", 12)
            engine.show_plan = [item]
            engine.tts = _FailingPlanTTS()

            with self.assertRaisesRegex(ValueError, "прежняя озвучка сохранена"):
                engine.update_show_plan_item_text(1, "Новый текст", rerender=True)
            self.assertEqual("Старый текст", item.text)
            self.assertEqual(old.resolve(), engine.get_show_plan_item_audio(1).resolve())

    def test_future_plan_items_can_be_duplicated_inserted_moved_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self.make_engine(tmp)
            speech = engine.cache_dir / "spoken" / "speech.mp3"
            speech.parent.mkdir(parents=True)
            speech.write_bytes(b"ID3")
            music = engine.cache_dir / "music.mp3"
            music.write_bytes(b"ID3")
            engine.show_plan = [
                PlannedItem("speech", speech, "Ведущие", "Текст", 5),
                PlannedItem("music", music, "Трек", "", 120),
            ]

            duplicated = engine.mutate_show_plan_item(1, "duplicate")
            self.assertEqual(2, duplicated["selected_index"])
            self.assertEqual(3, len(engine.show_plan))
            inserted = engine.mutate_show_plan_item(3, "insert_after")
            self.assertEqual("speech", engine.show_plan[inserted["selected_index"] - 1].kind)
            self.assertIn(id(engine.show_plan[3]), engine._show_plan_stale_audio_ids)
            moved = engine.mutate_show_plan_item(4, "move", target_index=2)
            self.assertEqual(2, moved["selected_index"])
            deleted = engine.mutate_show_plan_item(2, "delete")
            self.assertEqual(3, deleted["count"])

    def test_riddle_option_count_is_applied_without_losing_answer(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.cfg = {"riddle_options_count": 2}
        options = engine._riddle_options({"answer": "верный", "options": ["верный", "неверный", "ещё неверный"]})
        self.assertEqual(2, len(options))
        self.assertIn("верный", options)

    def test_tts_status_distinguishes_uninitialized_persistent_worker(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.cfg = {"tts_backend": "omnivoice", "omnivoice_persistent_worker": True}
        engine.tts = type("TTS", (), {"omnivoice_worker": None})()
        self.assertEqual(
            {"tts_backend": "omnivoice", "tts_ready": False, "tts_status": "not_initialized"},
            engine._tts_runtime_status(),
        )

    def test_omnivoice_service_can_start_and_stop_without_radio(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.cfg = {"tts_backend": "omnivoice", "omnivoice_persistent_worker": True, "hosts": []}
        engine.tts_service_lock = threading.RLock()
        engine.tts_service_thread = None
        engine.tts_service_status = "not_initialized"
        engine.tts_service_error = ""

        class FakeTTS:
            omnivoice_worker = None

            def start_omnivoice_worker(self, _hosts):
                proc = type("Proc", (), {"poll": lambda _self: None})()
                self.omnivoice_worker = type("Worker", (), {"proc": proc, "stop_requested": threading.Event()})()
                return True

            def stop_omnivoice_worker(self):
                existed = self.omnivoice_worker is not None
                self.omnivoice_worker = None
                return existed

        engine.tts = FakeTTS()
        started, _message = engine.start_omnivoice_service_async()
        self.assertTrue(started)
        engine.tts_service_thread.join(timeout=1)
        self.assertTrue(engine._tts_runtime_status()["tts_ready"])
        stopped, _message = engine.stop_omnivoice_service()
        self.assertTrue(stopped)
        self.assertEqual("stopped", engine._tts_runtime_status()["tts_status"])

    def test_background_plan_generation_does_not_replace_now_playing(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.cfg = {"show_plan_duration_minutes": 1}
        engine.show_plan_last_generation_sec = 0
        engine.show_plan_status = ""
        engine.show_plan_progress = {}
        engine.tracks = []
        engine.set_now = Mock()
        engine.is_running = lambda: True
        engine.pop_next_track = lambda: None

        self.assertEqual([], engine._build_preplanned_show_locked())
        engine.set_now.assert_not_called()

    def test_plan_skip_is_consumed_after_one_item(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.cfg = {
            "show_plan_enabled": True,
            "show_plan_rebuild_on_start": False,
            "show_plan_prepare_next_threshold_minutes": 0,
            "show_plan_prepare_next_fraction": 0.9,
            "show_plan_prepare_next_threshold_items": 0,
            "speech_takeover_enabled": False,
            "show_plan_continuous_extend": False,
            "show_plan_live_after_exhausted": False,
        }
        engine.plan_lock = threading.Lock()
        engine.state_lock = threading.Lock()
        engine.stop_event = threading.Event()
        engine.skip_event = threading.Event()
        engine.show_plan_last_generation_sec = 0
        engine.show_plan_status = "готов"
        engine.show_plan_index = 0
        engine.show_plan_active_index = -1
        engine.next_show_plan = []
        engine.plan_prepare_thread = None
        engine.pending_music_speech_transition = None
        engine.tracks_played = 0
        engine.show_plan = [
            PlannedItem("music", Path("first.mp3"), "Первый", "", 120),
            PlannedItem("music", Path("second.mp3"), "Второй", "", 120),
        ]
        played = []

        def stream(path, _kind, *, limit_sec=None):
            played.append((path.name, engine.skip_event.is_set(), limit_sec))
            if path.name == "first.mp3":
                engine.skip_event.set()
            return False

        engine._stream_path_plain_to_broadcast = stream
        engine._start_prepare_next_show_plan = lambda: None
        engine._transition_pause = lambda: None
        engine._save_current_show_plan = lambda: None
        engine.set_now = lambda *_args: None

        engine._air_preplanned_show()

        self.assertEqual(["first.mp3", "second.mp3"], [item[0] for item in played])
        self.assertFalse(played[1][1], "skip leaked into the next planned item")


class _ApiEngine:
    def __init__(self, audio):
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.lm = type("LM", (), {"list_models": lambda _self: [], "pick_model": lambda _self: "local-model"})()
        self.audio = audio
        self.edits = []
        self.actions = []
        self.cancelled = False
        self.show_plan_status = "готов"

    def get_show_plan_item_audio(self, index):
        return self.audio if index == 1 else None

    def update_show_plan_item_text(self, index, text, *, rerender):
        self.edits.append((index, text, rerender))
        return {"index": index, "text": text, "audio_ready": rerender, "rerendered": rerender}

    def mutate_show_plan_item(self, index, action, *, target_index=0):
        self.actions.append((index, action, target_index))
        return {"action": action, "selected_index": target_index or index, "count": 3}

    def cancel_show_plan_generation(self):
        self.cancelled = True
        return True


class ShowPlanApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.audio = Path(self.tmp.name) / "speech.mp3"
        self.audio.write_bytes(b"ID3 preview")
        self.engine = _ApiEngine(self.audio)
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(self.engine, self.engine.cfg))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.tmp.cleanup()

    def test_item_text_and_audio_contract(self):
        body = urllib.parse.urlencode({"index": "1", "text": "Исправленная реплика", "rerender": "true"})
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("POST", "/api/show_plan/item/text", body, {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))})
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(200, response.status)
        self.assertTrue(payload["audio_ready"])
        self.assertEqual([(1, "Исправленная реплика", True)], self.engine.edits)

        conn.request("GET", "/api/show_plan/item/audio?index=1")
        response = conn.getresponse()
        self.assertEqual(200, response.status)
        self.assertEqual("audio/mpeg", response.getheader("Content-Type"))
        self.assertEqual(b"ID3 preview", response.read())
        conn.close()

    def test_item_action_contract(self):
        body = urllib.parse.urlencode({"index": "2", "action": "move", "target_index": "3"})
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("POST", "/api/show_plan/item/action", body, {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))})
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(200, response.status)
        self.assertEqual(3, payload["selected_index"])
        self.assertEqual([(2, "move", 3)], self.engine.actions)
        conn.close()

    def test_plan_cancel_contract(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("POST", "/api/show_plan/cancel", "", {"Content-Length": "0"})
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(200, response.status)
        self.assertTrue(payload["cancelled"])
        self.assertTrue(self.engine.cancelled)
        conn.close()


if __name__ == "__main__":
    unittest.main()
