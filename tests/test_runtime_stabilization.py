import tempfile
import threading
import time
import unittest

from ai_truck_radio_app.engine import RadioEngine
from ai_truck_radio_app.tts import TTS


class RuntimeStabilizationTests(unittest.TestCase):
    def test_plan_builds_are_serialized(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.plan_lock = threading.Lock()
        engine.plan_build_lock = threading.Lock()
        engine._plan_generation = 1
        running = 0
        peak = 0
        guard = threading.Lock()

        def build(_generation):
            nonlocal running, peak
            with guard:
                running += 1
                peak = max(peak, running)
            time.sleep(0.03)
            with guard:
                running -= 1
            return []

        engine._build_preplanned_show_locked = build
        threads = [threading.Thread(target=engine._build_preplanned_show, args=(1,)) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, peak)

    def test_stale_plan_generation_does_not_enter_builder(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.plan_lock = threading.Lock()
        engine.plan_build_lock = threading.Lock()
        engine._plan_generation = 2
        engine._build_preplanned_show_locked = lambda _generation: self.fail("stale plan must not build")
        self.assertEqual([], engine._build_preplanned_show(1))

    def test_active_plan_generation_can_be_cancelled(self):
        engine = RadioEngine.__new__(RadioEngine)
        engine.plan_lock = threading.Lock()
        engine.plan_prepare_thread = type("RunningThread", (), {"is_alive": lambda _self: True})()
        engine._plan_generation = 7
        engine._plan_cancel_requested_generation = None
        engine.show_plan_status = "готовлю"
        engine.show_plan_progress = {"current": 3, "total": 10, "percent": 30, "detail": "готовлю"}

        self.assertTrue(engine.cancel_show_plan_generation())
        self.assertEqual(8, engine._plan_generation)
        self.assertEqual(7, engine._plan_cancel_requested_generation)
        self.assertIn("отменяю", engine.show_plan_status)
        self.assertIn("останавливаю", engine.show_plan_progress["detail"])

    def test_complete_cache_signature_changes_for_unlisted_voice_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"cache_dir": tmp, "bitrate_kbps": 128, "ffmpeg_path": "ffmpeg"}
            tts = TTS(cfg)
            first = tts._cache_signature("omnivoice", "Host", {"omnivoice_steps": 16, "new_voice_timbre": "a"})
            second = tts._cache_signature("omnivoice", "Host", {"omnivoice_steps": 16, "new_voice_timbre": "b"})
            self.assertNotEqual(first, second)

    def test_dialogue_files_are_in_bounded_cache_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"cache_dir": tmp, "max_cached_spoken_files": 1}
            tts = TTS(cfg)
            old = tts.cache_dir / "dialogue_old.mp3"
            new = tts.cache_dir / "host_new.mp3"
            old.write_bytes(b"x")
            time.sleep(0.01)
            new.write_bytes(b"x")
            tts.cleanup_cache()
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())
