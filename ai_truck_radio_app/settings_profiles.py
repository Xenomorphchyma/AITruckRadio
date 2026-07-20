# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import math
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from ai_truck_radio_app.config import DEFAULT_CONFIG, save_json


BUILTIN_PROFILE_ID = "default"
BUILTIN_PROFILE_NAME = "По умолчанию"
_PROFILE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_INVALID_NAME_RE = re.compile(r"[\x00-\x1f<>:\"/\\|?*]")
_SENSITIVE_PARTS = ("password", "secret", "token", "credential", "api_key")
_LOCAL_PATH_SUFFIXES = (
    "_dir",
    "_file",
    "_path",
    "_python",
    "_home",
    "_cache",
    "_exe",
)
_EXCLUDED_KEYS = {
    "host",
    "port",
    "hosts",
    "music_dir",
    "cache_dir",
    "lm_base_url",
    "lmstudio_tts_base_url",
    "omnivoice_ref_audio",
    "omnivoice_ref_text",
    "guest_ref_audio",
    "guest_ref_text",
    "f5_tts_ref_audio",
    "f5_tts_ref_text",
    "f5_tts_model_cfg",
    "piper_model",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_profile_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip()
    if not 2 <= len(name) <= 48:
        raise ValueError("Название профиля должно содержать от 2 до 48 символов.")
    if _INVALID_NAME_RE.search(name) or not any(char.isalnum() for char in name):
        raise ValueError("В названии профиля есть недопустимые символы.")
    if name.casefold() == BUILTIN_PROFILE_NAME.casefold():
        raise ValueError("Название «По умолчанию» зарезервировано.")
    return name


def _is_safe_profile_key(key: str, default: Any) -> bool:
    lowered = key.casefold()
    if key in _EXCLUDED_KEYS:
        return False
    if any(part in lowered for part in _SENSITIVE_PARTS):
        return False
    if lowered.endswith(_LOCAL_PATH_SUFFIXES):
        return False
    if "ref_audio" in lowered or "ref_text" in lowered or "ckpt" in lowered or "vocab" in lowered:
        return False
    return isinstance(default, (str, bool, int, float)) and default is not None


def profile_safe_keys(defaults: Mapping[str, Any] = DEFAULT_CONFIG) -> frozenset[str]:
    return frozenset(key for key, value in defaults.items() if _is_safe_profile_key(key, value))


def _compatible_value(value: Any, default: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int) and not isinstance(default, bool):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    return isinstance(value, str) and len(value) <= 16_000


def safe_profile_snapshot(
    config: Mapping[str, Any], defaults: Mapping[str, Any] = DEFAULT_CONFIG
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in profile_safe_keys(defaults):
        value = config.get(key, defaults[key])
        if _compatible_value(value, defaults[key]):
            result[key] = copy.deepcopy(value)
    return result


class SettingsProfileStore:
    """Atomic, validated storage for non-sensitive configuration profiles."""

    def __init__(self, path: Path, defaults: Mapping[str, Any] = DEFAULT_CONFIG) -> None:
        self.path = Path(path)
        self.defaults = defaults
        self._lock = threading.RLock()

    def _load(self) -> list[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        source = raw.get("profiles", []) if isinstance(raw, dict) else []
        result: list[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for item in source[:100] if isinstance(source, list) else []:
            if not isinstance(item, dict):
                continue
            profile_id = str(item.get("id") or "")
            try:
                name = validate_profile_name(item.get("name"))
            except ValueError:
                continue
            folded = name.casefold()
            if not _PROFILE_ID_RE.fullmatch(profile_id) or profile_id in seen_ids or folded in seen_names:
                continue
            raw_settings = item.get("settings")
            source_settings: Dict[str, Any] = raw_settings if isinstance(raw_settings, dict) else {}
            settings = safe_profile_snapshot(source_settings, self.defaults)
            # Loading must not fill missing values with defaults: older profile
            # files intentionally apply only the keys they contain.
            settings = {key: value for key, value in settings.items() if key in source_settings}
            result.append(
                {
                    "id": profile_id,
                    "name": name,
                    "settings": settings,
                    "created_at": str(item.get("created_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                }
            )
            seen_ids.add(profile_id)
            seen_names.add(folded)
        return result

    def _save(self, profiles: list[Dict[str, Any]]) -> None:
        save_json(self.path, {"version": 1, "profiles": profiles})

    @staticmethod
    def _metadata(item: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "builtin": False,
            "created_at": str(item.get("created_at") or ""),
            "updated_at": str(item.get("updated_at") or ""),
        }

    def list_profiles(self) -> list[Dict[str, Any]]:
        with self._lock:
            profiles = self._load()
        return [
            {"id": BUILTIN_PROFILE_ID, "name": BUILTIN_PROFILE_NAME, "builtin": True},
            *(self._metadata(item) for item in profiles),
        ]

    def create(self, name: Any, config: Mapping[str, Any]) -> Dict[str, Any]:
        clean_name = validate_profile_name(name)
        with self._lock:
            profiles = self._load()
            if any(item["name"].casefold() == clean_name.casefold() for item in profiles):
                raise ValueError("Профиль с таким названием уже существует.")
            if len(profiles) >= 40:
                raise ValueError("Можно сохранить не более 40 пользовательских профилей.")
            timestamp = _now_iso()
            item = {
                "id": secrets.token_hex(16),
                "name": clean_name,
                "settings": safe_profile_snapshot(config, self.defaults),
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            profiles.append(item)
            self._save(profiles)
            return self._metadata(item)

    def rename(self, profile_id: Any, name: Any) -> Dict[str, Any]:
        clean_id = str(profile_id or "")
        if clean_id == BUILTIN_PROFILE_ID:
            raise ValueError("Встроенный профиль нельзя переименовать.")
        if not _PROFILE_ID_RE.fullmatch(clean_id):
            raise ValueError("Некорректный идентификатор профиля.")
        clean_name = validate_profile_name(name)
        with self._lock:
            profiles = self._load()
            if any(item["id"] != clean_id and item["name"].casefold() == clean_name.casefold() for item in profiles):
                raise ValueError("Профиль с таким названием уже существует.")
            item = next((entry for entry in profiles if entry["id"] == clean_id), None)
            if item is None:
                raise ValueError("Профиль не найден.")
            item["name"] = clean_name
            item["updated_at"] = _now_iso()
            self._save(profiles)
            return self._metadata(item)

    def delete(self, profile_id: Any) -> Dict[str, Any]:
        clean_id = str(profile_id or "")
        if clean_id == BUILTIN_PROFILE_ID:
            raise ValueError("Встроенный профиль нельзя удалить.")
        if not _PROFILE_ID_RE.fullmatch(clean_id):
            raise ValueError("Некорректный идентификатор профиля.")
        with self._lock:
            profiles = self._load()
            item = next((entry for entry in profiles if entry["id"] == clean_id), None)
            if item is None:
                raise ValueError("Профиль не найден.")
            self._save([entry for entry in profiles if entry["id"] != clean_id])
            return self._metadata(item)

    def settings_for_apply(self, profile_id: Any) -> Dict[str, Any]:
        clean_id = str(profile_id or "")
        if clean_id == BUILTIN_PROFILE_ID:
            return safe_profile_snapshot(self.defaults, self.defaults)
        if not _PROFILE_ID_RE.fullmatch(clean_id):
            raise ValueError("Некорректный идентификатор профиля.")
        with self._lock:
            item = next((entry for entry in self._load() if entry["id"] == clean_id), None)
            if item is None:
                raise ValueError("Профиль не найден.")
            return copy.deepcopy(item["settings"])
