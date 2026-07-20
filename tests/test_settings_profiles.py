# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import http.client
import json
import threading
import urllib.parse
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_truck_radio_app.server as server_module
from ai_truck_radio_app.config import DEFAULT_CONFIG
from ai_truck_radio_app.server import make_handler
from ai_truck_radio_app.settings_profiles import SettingsProfileStore


class _Engine:
    def __init__(self) -> None:
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.lm = SimpleNamespace(list_models=lambda: [], pick_model=lambda: "local-model")
        self.last_updates: dict[str, object] = {}

    def update_config(self, updates: dict[str, object]) -> None:
        self.cfg.update(updates)
        self.last_updates = dict(updates)


def _request(port: int, method: str, path: str, values: dict[str, object] | None = None) -> tuple[int, dict]:
    body = urllib.parse.urlencode(values or {}) if method == "POST" else None
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if body is not None else {}
    connection = http.client.HTTPConnection("127.0.0.1", port)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, payload


def test_store_excludes_local_paths_reference_voices_and_hosts(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    store = SettingsProfileStore(path)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(
        {
            "music_volume": 0.61,
            "music_dir": "D:/private/music",
            "omnivoice_ref_audio": "references/private.wav",
            "guest_ref_text": "references/private.txt",
            "piper_model": "D:/private/voice.onnx",
            "hosts": [{"name": "Секретный ведущий", "omnivoice_ref_audio": "private.wav"}],
        }
    )

    created = store.create("Ночной эфир", cfg)
    saved = json.loads(path.read_text(encoding="utf-8"))["profiles"][0]["settings"]

    assert created["name"] == "Ночной эфир"
    assert saved["music_volume"] == 0.61
    assert "music_dir" not in saved
    assert "omnivoice_ref_audio" not in saved
    assert "guest_ref_text" not in saved
    assert "piper_model" not in saved
    assert "hosts" not in saved
    assert "host" not in saved
    assert "port" not in saved


def test_builtin_profile_is_apply_only_and_names_are_validated(tmp_path: Path) -> None:
    store = SettingsProfileStore(tmp_path / "profiles.json")

    profiles = store.list_profiles()
    assert profiles[0] == {"id": "default", "name": "По умолчанию", "builtin": True}
    assert store.settings_for_apply("default")["music_volume"] == DEFAULT_CONFIG["music_volume"]
    assert "music_dir" not in store.settings_for_apply("default")
    with pytest.raises(ValueError, match="нельзя переименовать"):
        store.rename("default", "Новый профиль")
    with pytest.raises(ValueError, match="нельзя удалить"):
        store.delete("default")
    with pytest.raises(ValueError, match="недопустимые"):
        store.create("../bad", DEFAULT_CONFIG)
    with pytest.raises(ValueError, match="зарезервировано"):
        store.create("По умолчанию", DEFAULT_CONFIG)


def test_profile_http_lifecycle_applies_only_safe_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_path = tmp_path / "profiles.json"
    monkeypatch.setattr(server_module, "SETTINGS_PROFILES_PATH", profile_path)
    engine = _Engine()
    engine.cfg["music_volume"] = 0.61
    engine.cfg["music_dir"] = "D:/private/music"
    server = HTTPServer(("127.0.0.1", 0), make_handler(engine, engine.cfg))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, listing = _request(server.server_port, "GET", "/api/settings_profiles")
        assert status == 200
        assert listing["profiles"][0]["builtin"] is True

        status, created = _request(
            server.server_port, "POST", "/api/settings_profiles/create", {"name": "Дальний рейс"}
        )
        assert status == 200
        profile_id = created["profile"]["id"]

        status, renamed = _request(
            server.server_port,
            "POST",
            "/api/settings_profiles/rename",
            {"id": profile_id, "name": "Спокойный рейс"},
        )
        assert status == 200
        assert renamed["profile"]["name"] == "Спокойный рейс"

        engine.cfg["music_volume"] = 1.2
        engine.cfg["music_dir"] = "E:/keep-this-path"
        status, applied = _request(
            server.server_port, "POST", "/api/settings_profiles/apply", {"id": profile_id}
        )
        assert status == 200
        assert applied["updates"]["music_volume"] == 0.61
        assert "music_dir" not in applied["updates"]
        assert engine.cfg["music_volume"] == 0.61
        assert engine.cfg["music_dir"] == "E:/keep-this-path"

        status, deleted = _request(
            server.server_port, "POST", "/api/settings_profiles/delete", {"id": profile_id}
        )
        assert status == 200
        assert deleted["profile"]["name"] == "Спокойный рейс"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
