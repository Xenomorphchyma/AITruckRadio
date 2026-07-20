import tempfile
import time
import unittest
from pathlib import Path

from ai_truck_radio_app.show_plan_store import ShowPlanStore
from ai_truck_radio_app.tracks import PlannedItem


class ShowPlanStoreTests(unittest.TestCase):
    def make_store(self, root: Path, **kwargs):
        music = root / "music"
        cache = root / "cache"
        music.mkdir()
        cache.mkdir()
        return ShowPlanStore(root / "plan.json", music_root=music, cache_root=cache, **kwargs)

    def test_round_trip_preserves_resume_state_and_reservations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root)
            song = root / "music" / "song.mp3"
            speech = root / "cache" / "spoken.mp3"
            song.write_bytes(b"ID3 song")
            speech.write_bytes(b"ID3 speech")
            items = [
                PlannedItem("music", song, "Song", duration_sec=120),
                PlannedItem(
                    "speech",
                    speech,
                    "Hosts",
                    "Text",
                    10,
                    ["riddle:test"],
                    [{"draft_id": "news-1", "title": "News", "summary": "Summary", "status": "scheduled"}],
                ),
            ]
            store.save(items, next_index=1, stale_audio_indices={1})

            restored = store.load()

            self.assertEqual("restored", restored.reason)
            self.assertEqual(1, restored.next_index)
            self.assertEqual({1}, restored.stale_audio_indices)
            self.assertEqual(["riddle:test"], restored.items[1].history_keys)
            self.assertEqual("news-1", restored.items[1].news_items[0]["draft_id"])

    def test_rejects_path_outside_application_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root)
            outside = root / "secret.mp3"
            outside.write_bytes(b"secret")
            store.save([PlannedItem("speech", outside, "Unsafe")])
            self.assertIn("unsafe", store.load().reason)

    def test_expired_plan_is_not_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root, max_age_hours=1)
            song = root / "music" / "song.mp3"
            song.write_bytes(b"ID3")
            store.save([PlannedItem("music", song, "Song")])
            text = store.output_path.read_text(encoding="utf-8")
            store.output_path.write_text(text.replace(str(int(time.time())), "1", 1), encoding="utf-8")
            self.assertEqual("saved plan expired", store.load().reason)


if __name__ == "__main__":
    unittest.main()
