"""Machine-readable settings metadata shared by API and client-rendered panels.

Labels deliberately do not live here: UI copy remains a presentation concern.
"""
from __future__ import annotations

from typing import Any, Dict


SETTINGS_SCHEMA: Dict[str, Dict[str, Any]] = {
    "bitrate_kbps": {"type": "integer", "min": 16, "max": 512},
    "show_plan_duration_minutes": {"type": "integer", "min": 1, "max": 1440},
    "reference_asr_beam_size": {"type": "integer", "min": 1, "max": 20},
    "reference_asr_review_consensus_similarity": {"type": "number", "min": 0, "max": 1},
    "entertainment_history_max_items": {"type": "integer", "min": 100, "max": 100000},
    "show_plan_long_block_chance": {"type": "number", "min": 0, "max": 1},
    "listener_greetings_chance": {"type": "number", "min": 0, "max": 1},
    "station_id_chance": {"type": "number", "min": 0, "max": 1},
    "reference_asr_enabled": {"type": "boolean"},
    "reference_asr_review_enabled": {"type": "boolean"},
    "music_dir": {"type": "string"},
    "ffmpeg_path": {"type": "string"},
    "hosts": {"type": "array"},
}
