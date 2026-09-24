"""Machine-readable settings metadata shared by API and client-rendered panels.

Labels deliberately do not live here: UI copy remains a presentation concern.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping


SETTINGS_SCHEMA: Dict[str, Dict[str, Any]] = {
    "port": {"type": "integer", "min": 1, "max": 65535},
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


def _inferred_spec(key: str, value: Any) -> Dict[str, Any]:
    """Infer conservative metadata for settings without a hand-written entry.

    The API exposes this metadata to the panel, so naming based bounds keep
    newly added probability and timeout fields from silently accepting values
    that can break scheduling or audio behaviour.
    """
    if isinstance(value, bool):
        value_type = "boolean"
    elif isinstance(value, int):
        value_type = "integer"
    elif isinstance(value, float):
        value_type = "number"
    elif isinstance(value, str):
        value_type = "string"
    elif isinstance(value, list):
        value_type = "array"
    elif isinstance(value, dict):
        value_type = "object"
    else:
        return {}

    spec: Dict[str, Any] = {"type": value_type}
    lower = key.lower()
    if value_type in {"number", "integer"}:
        if key == "port":
            spec.update(min=1, max=65535)
        elif key == "f5_tts_seed":
            # F5-TTS uses -1 as the documented random-seed sentinel.
            spec.update(min=-1, max=2_147_483_647)
        elif lower.endswith(("_chance", "_fraction", "_ratio")):
            spec.update(min=0, max=1)
        elif lower.endswith(("_timeout_sec", "_delay_sec", "_cooldown_sec")):
            spec.update(min=0, max=86400)
        elif lower.endswith("_hour"):
            spec.update(min=0, max=23)
        elif value_type == "integer":
            spec["min"] = 0
    return spec


def settings_schema(defaults: Mapping[str, Any] | None = None) -> Dict[str, Dict[str, Any]]:
    """Return metadata for every runtime setting, with safe type fallbacks.

    Explicit entries above carry UI ranges. Remaining fields are inferred from
    ``DEFAULT_CONFIG`` so newly added settings still have machine-readable
    metadata for the panel and API.
    """
    if defaults is None:
        from ai_truck_radio_app.config import DEFAULT_CONFIG

        defaults = DEFAULT_CONFIG
    result = {key: dict(value) for key, value in SETTINGS_SCHEMA.items()}
    for key, value in defaults.items():
        if key in result:
            continue
        spec = _inferred_spec(key, value)
        if spec:
            result[key] = spec
    return result


def validate_setting_updates(updates: Mapping[str, Any], defaults: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Validate already-coerced API values against the public settings schema.

    ``/api/save_config`` performs form parsing and type coercion first.  This
    final pass applies the same range contract to both hand-written and
    forward-compatible fields, preventing a new scalar setting from bypassing
    validation merely because it was omitted from an older field list.
    """
    schema = settings_schema(defaults)
    validated: Dict[str, Any] = {}
    for key, value in updates.items():
        spec = schema.get(key)
        if not spec:
            continue
        value_type = spec.get("type")
        if value_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{key} должен быть логическим значением.")
        elif value_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} должен быть целым числом.")
            if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
                raise ValueError(f"{key} вне допустимого диапазона {spec.get('min', '-∞')}–{spec.get('max', '∞')}.")
        elif value_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{key} должен быть конечным числом.")
            if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
                raise ValueError(f"{key} вне допустимого диапазона {spec.get('min', '-∞')}–{spec.get('max', '∞')}.")
        elif value_type == "string" and not isinstance(value, str):
            raise ValueError(f"{key} должен быть строкой.")
        elif value_type == "array" and not isinstance(value, list):
            raise ValueError(f"{key} должен быть массивом.")
        elif value_type == "object" and not isinstance(value, dict):
            raise ValueError(f"{key} должен быть объектом.")
        validated[key] = value
    return validated
