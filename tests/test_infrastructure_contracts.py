from __future__ import annotations

import builtins
import json
from pathlib import Path

from ai_truck_radio_app.config import DEFAULT_CONFIG
from tools import omnivoice_probe


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_config_example_matches_runtime_defaults() -> None:
    example = json.loads((PROJECT_ROOT / "config.example.json").read_text(encoding="utf-8"))

    assert example.keys() == DEFAULT_CONFIG.keys()
    assert example == DEFAULT_CONFIG


def test_config_example_has_no_legacy_road_branding() -> None:
    text = (PROJECT_ROOT / "config.example.json").read_text(encoding="utf-8").casefold()

    for legacy_phrase in ("ai дальнобой", "road radio", "дальнобой fm", "дорожного радио"):
        assert legacy_phrase not in text


def test_tts_batch_changes_to_project_root() -> None:
    script = (PROJECT_ROOT / "scripts" / "tests" / "test_tts_windows.bat").read_text(encoding="utf-8").casefold()

    assert 'set "root=%~dp0..\\.."' in script
    assert 'cd /d "%root%"' in script
    assert '".venv\\scripts\\python.exe" "tools\\test_tts_backend.py"' in script


def test_omnivoice_probe_fails_when_required_import_is_missing(monkeypatch) -> None:
    real_import = builtins.__import__

    def fail_required_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"torch", "soundfile", "omnivoice"}:
            raise ImportError(f"missing test dependency: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_required_import)

    assert omnivoice_probe.main() == 1
