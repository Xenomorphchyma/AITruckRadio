import unittest
from pathlib import Path

from ai_truck_radio_app.audio_transition import music_speech_crossfade_command


class AudioTransitionTests(unittest.TestCase):
    def test_command_streams_only_unplayed_tail_and_full_speech(self):
        command = music_speech_crossfade_command(
            ffmpeg="ffmpeg",
            music_path=Path("song.mp3"),
            speech_path=Path("speech.mp3"),
            music_duration_sec=180,
            overlap_sec=4,
            bitrate_kbps=128,
            music_volume=0.78,
            speech_volume=1.45,
        )
        self.assertEqual("176.000", command[command.index("-ss") + 1])
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("acrossfade=d=4.000", filter_graph)
        self.assertIn("volume=0.780", filter_graph)
        self.assertIn("volume=1.450", filter_graph)
        self.assertEqual("pipe:1", command[-1])

    def test_overlap_is_clamped_to_music_duration(self):
        command = music_speech_crossfade_command(
            ffmpeg="ffmpeg",
            music_path=Path("short.mp3"),
            speech_path=Path("speech.mp3"),
            music_duration_sec=1,
            overlap_sec=5,
            bitrate_kbps=999,
            music_volume=99,
            speech_volume=0,
        )
        self.assertEqual("0.050", command[command.index("-ss") + 1])
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("acrossfade=d=0.950", graph)
        self.assertEqual("320k", command[command.index("-b:a") + 1])


if __name__ == "__main__":
    unittest.main()
