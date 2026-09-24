from __future__ import annotations

import copy
import http.client
import io
import json
import sys
import threading
import time
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_truck_radio_app.audio_process import AudioProcessRunner
import ai_truck_radio_app.tts as tts_module
from ai_truck_radio_app.config import DEFAULT_CONFIG, normalize_config
from ai_truck_radio_app.engine import RadioEngine
from ai_truck_radio_app.lmstudio import LMStudioClient
from ai_truck_radio_app.server import make_handler, parse_multipart
from ai_truck_radio_app.tts import TTS
from ai_truck_radio_app.settings_schema import settings_schema


def test_normalize_config_preserves_explicit_audio_values() -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(
        {
            "speech_takeover_sec": 0.8,
            "speech_voice_volume": 0.5,
            "speech_bed_volume": 0.2,
            "speech_loudnorm_i": -18.0,
        }
    )
    normalized = normalize_config(cfg)
    assert normalized["speech_takeover_sec"] == 0.8
    assert normalized["speech_voice_volume"] == 0.5
    assert normalized["speech_bed_volume"] == 0.2
    assert normalized["speech_loudnorm_i"] == -18.0


def test_normalize_config_recovers_invalid_audio_values_without_overriding_valid_ones() -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update({"speech_takeover_sec": "bad", "speech_voice_volume": "NaN", "speech_bed_volume": "inf"})
    normalized = normalize_config(cfg)
    assert normalized["speech_takeover_sec"] == DEFAULT_CONFIG["speech_takeover_sec"]
    assert normalized["speech_voice_volume"] == DEFAULT_CONFIG["speech_voice_volume"]
    assert normalized["speech_bed_volume"] == DEFAULT_CONFIG["speech_bed_volume"]


def test_cleanup_generated_files_does_not_race_radio_startup() -> None:
    engine = RadioEngine.__new__(RadioEngine)
    engine.lifecycle_lock = threading.RLock()
    engine.plan_lock = threading.RLock()
    engine._startup_in_progress = True
    engine.startup_thread = None
    engine.broadcast_thread = None
    engine.plan_prepare_thread = None

    assert engine.cleanup_generated_radio_files() == {"files": 0, "dirs": 0}


@pytest.mark.parametrize("backend", ["none", "sapi", "piper"])
def test_omnivoice_migration_preserves_explicit_tts_backend(backend: str) -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["omnivoice_core_profile_version"] = 0
    cfg["tts_backend"] = backend

    normalized = normalize_config(cfg)

    assert normalized["tts_backend"] == backend
    assert normalized["omnivoice_core_profile_version"] == 1


def test_omnivoice_migration_sets_default_when_tts_backend_is_absent() -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.pop("tts_backend")
    cfg["omnivoice_core_profile_version"] = 0

    normalized = normalize_config(cfg)

    assert normalized["tts_backend"] == "omnivoice"


def test_settings_schema_covers_all_runtime_defaults() -> None:
    schema = settings_schema(DEFAULT_CONFIG)
    assert set(DEFAULT_CONFIG).issubset(schema)
    assert schema["lm_enabled"]["type"] == "boolean"
    assert schema["lm_max_tokens"]["type"] == "integer"
    assert schema["lm_temperature"]["type"] == "number"


def test_multipart_audio_payload_keeps_trailing_crlf_bytes() -> None:
    boundary = "upload-boundary"
    audio = b"RIFF\x00\x01\r\n"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="audio"; filename="sample.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode("ascii") + audio + f"\r\n--{boundary}--\r\n".encode("ascii")
    handler = SimpleNamespace(
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
        rfile=io.BytesIO(body),
    )
    fields, files = parse_multipart(handler)  # type: ignore[arg-type]
    assert fields == {}
    assert files["audio"]["filename"] == "sample.wav"
    assert files["audio"]["content"] == audio


class _GuardEngine:
    def __init__(self) -> None:
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.lm = SimpleNamespace(list_models=lambda: [], pick_model=lambda: "local-model")


def test_get_management_routes_reject_host_rebinding() -> None:
    engine = _GuardEngine()
    server = HTTPServer(("127.0.0.1", 0), make_handler(engine, engine.cfg))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.request("GET", "/", headers={"Host": "evil.example"})
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        conn.close()
        assert response.status == 403
        assert payload["ok"] is False
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_audio_runner_streams_output_and_drains_stderr() -> None:
    runner = AudioProcessRunner()
    chunks: list[bytes] = []
    errors: list[str] = []
    ok = runner.stream(
        [sys.executable, "-c", "import sys;sys.stderr.write('diagnostic'*100000);sys.stdout.buffer.write(b'x'*50000)"],
        stop=threading.Event(),
        skip=threading.Event(),
        publish=chunks.append,
        report_error=errors.append,
        idle_timeout=2,
    )
    assert ok is True
    assert b"".join(chunks) == b"x" * 50000
    assert errors == []


def test_audio_runner_stop_interrupts_a_silent_child() -> None:
    runner = AudioProcessRunner()
    stop = threading.Event()
    skip = threading.Event()
    errors: list[str] = []
    result: list[bool] = []
    thread = threading.Thread(
        target=lambda: result.append(
            runner.stream(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                stop=stop,
                skip=skip,
                publish=lambda _chunk: None,
                report_error=errors.append,
                idle_timeout=60,
            )
        ),
        daemon=True,
    )
    thread.start()
    time.sleep(0.2)
    stop.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result == [False]


def test_tts_cleanup_keeps_protected_plan_audio() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tts = TTS({"cache_dir": tmp, "max_cached_spoken_files": 1})
        protected = tts.cache_dir / "host_plan.mp3"
        latest = tts.cache_dir / "host_latest.mp3"
        protected.write_bytes(b"x")
        time.sleep(0.01)
        latest.write_bytes(b"x")
        tts.set_protected_cache_paths([protected])
        tts.cleanup_cache()
        assert protected.exists()
        assert latest.exists()


@pytest.mark.parametrize("output_size", [0, 8])
def test_sapi_rejects_missing_or_partial_wav(tmp_path: Path, monkeypatch, output_size: int) -> None:
    """A successful SAPI process must also leave a usable output file."""
    tts = TTS({"cache_dir": str(tmp_path), "tts_debug_log": False})
    monkeypatch.setattr(
        tts_module.shutil,
        "which",
        lambda name: "powershell.exe" if name in {"powershell", "powershell.exe"} else None,
    )

    def fake_run(*_args, **_kwargs):
        (tts.tmp_dir / "host_sapi.wav").write_bytes(b"x" * output_size)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tts_module, "run_subprocess", fake_run)
    assert tts._sapi_to_wav("Проверка", "sapi", {}) is None


def test_unknown_tts_backend_is_reported_instead_of_silently_becoming_sapi(tmp_path: Path) -> None:
    """A typo in the selected backend must not unexpectedly invoke Windows SAPI."""
    tts = TTS({
        "cache_dir": str(tmp_path),
        "tts_backend": "made_up_backend",
        "tts_fallback_enabled": False,
        "tts_debug_log": False,
    })
    assert tts.get_or_create_mp3("Проверка") is None


def test_tts_runtime_status_checks_piper_model_and_executable(tmp_path: Path) -> None:
    model = tmp_path / "voice.onnx"
    python = tmp_path / "python.exe"
    cfg = {
        "cache_dir": str(tmp_path / "cache"),
        "tts_backend": "piper",
        "piper_model": str(model),
        "piper_python": str(python),
        "piper_exe": str(tmp_path / "missing-piper.exe"),
    }
    tts = TTS(cfg)
    assert tts.runtime_status()["tts_status"] == "missing_model"
    model.write_bytes(b"onnx")
    assert tts.runtime_status()["tts_status"] == "missing_executable"
    python.write_bytes(b"stub")
    status = tts.runtime_status()
    assert status["tts_ready"] is True
    assert status["tts_status"] == "on_demand"


def test_tts_runtime_status_checks_silero_helper(tmp_path: Path, monkeypatch) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    monkeypatch.setattr(tts_module, "BASE_DIR", tmp_path)
    tts = TTS({"cache_dir": str(tmp_path / "cache"), "tts_backend": "silero", "piper_python": str(tmp_path / "python.exe")})
    assert tts.runtime_status()["tts_status"] == "missing_helper"
    (tools_dir / "silero_render.py").write_text("# test helper", encoding="utf-8")
    (tmp_path / "python.exe").write_bytes(b"stub")
    assert tts.runtime_status()["tts_ready"] is True


@pytest.mark.parametrize("event_name", ["stop", "skip", "timeout"])
def test_audio_runner_interrupts_without_stdout(event_name: str) -> None:
    runner = AudioProcessRunner()
    stop, skip = threading.Event(), threading.Event()
    errors: list[str] = []
    # Wait for process registration instead of assuming process startup speed.
    def cancel() -> None:
        deadline = time.monotonic() + 3
        while runner._process is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if event_name == "stop":
            stop.set()
            runner.interrupt()
        elif event_name == "skip":
            skip.set()

    thread = threading.Thread(target=cancel, daemon=True)
    thread.start()
    started = time.monotonic()
    assert runner.stream(
        [sys.executable, "-c", "import time;time.sleep(30)"],
        stop=stop, skip=skip, publish=lambda _: None, report_error=errors.append,
        idle_timeout=0.2 if event_name == "timeout" else 60,
    ) is False
    thread.join(timeout=3)
    assert time.monotonic() - started < 5
    assert runner._process is None
    assert bool(errors) == (event_name == "timeout")


def test_never_block_setting_overrides_due_synchronous_generation() -> None:
    engine = RadioEngine.__new__(RadioEngine)
    engine.cfg = {"never_block_for_dj": True, "live_blocking_dj_when_due": True}
    engine.previous_track = None
    engine.speech_blocks_played = 1
    engine.prepare_lock = threading.Lock()
    engine.prepare_thread = None
    engine.peek_next_track = lambda: None
    engine.take_prepared_dj = lambda *_: None
    engine.should_insert_dj = lambda: True
    engine.create_dj_segment = Mock(side_effect=AssertionError("must prepare asynchronously"))
    assert engine.make_dj_mp3() is None
    engine.create_dj_segment.assert_not_called()


def test_empty_reasoning_completion_is_retried_once_with_reasoning_disabled() -> None:
    client = LMStudioClient({"lm_base_url": "http://127.0.0.1:1234/v1", "lm_model": "test", "tts_debug_log": False})
    client.pick_model = lambda: "test"
    payloads = []

    def request(_method, _url, payload):
        payloads.append(payload)
        if len(payloads) == 1:
            return {"choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": "internal"}}]}
        return {"choices": [{"message": {"content": "Максим: Продолжаем наш эфир."}}]}

    client._request_json = request
    assert "Продолжаем наш эфир" in client.generate_host_line(None, None, {})
    assert len(payloads) == 2
    assert "reasoning_effort" not in payloads[0]
    assert payloads[1]["reasoning_effort"] == "none"


def test_update_config_refreshes_paths_clients_and_persisted_values(tmp_path: Path, monkeypatch) -> None:
    import ai_truck_radio_app.engine as engine_module

    saved_config = tmp_path / "config.json"
    monkeypatch.setattr(engine_module, "CONFIG_PATH", saved_config)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update({
        "music_dir": str(tmp_path / "music_old"), "cache_dir": str(tmp_path / "cache_old"),
        "show_plan_output_file": str(tmp_path / "plan.json"), "show_plan_restore_on_start": False,
        "news_agent_enabled": False, "track_profiles_enabled": False, "tts_backend": "none",
    })
    engine = RadioEngine(cfg)
    new_music = tmp_path / "music_new"
    new_music.mkdir()
    (new_music / "song.mp3").write_bytes(b"ID3")
    new_cache = tmp_path / "cache_new"
    engine.update_config({
        "music_dir": str(new_music), "cache_dir": str(new_cache),
        "news_agent_queries": "новые новости", "lm_base_url": "http://127.0.0.1:12345/v1",
        "speech_voice_volume": 0.6,
    })
    assert engine.music_dir == new_music
    assert len(engine.tracks) == 1
    assert engine.cache_dir == new_cache
    assert engine.tts.cache_dir == new_cache / "spoken"
    assert engine.news_agent.cfg["news_agent_queries"] == "новые новости"
    assert engine.news_agent.lm is engine.lm
    assert engine.show_plan_store.cache_root == new_cache.resolve()
    assert engine.show_plan_store.music_root == new_music.resolve()
    assert json.loads(saved_config.read_text(encoding="utf-8"))["speech_voice_volume"] == 0.6


def test_dialogue_cache_cleanup_cannot_remove_earlier_speaker(tmp_path: Path, monkeypatch) -> None:
    tts = TTS({"cache_dir": str(tmp_path), "max_cached_spoken_files": 1, "tts_debug_log": False})

    def synthesize(text, *_args):
        path = tts.cache_dir / f"host_{tts.text_hash(text)}.mp3"
        path.write_bytes(b"x" * 2048)
        tts.cleanup_cache()
        return path

    def concatenate(parts, output):
        assert len(parts) == 3
        assert all(part.is_file() for part in parts)
        output.write_bytes(b"x" * 2048)
        return output

    monkeypatch.setattr(tts, "get_or_create_mp3", synthesize)
    monkeypatch.setattr(tts, "_concat_mp3_files", concatenate)
    result = tts.get_or_create_dialogue_mp3(
        "Максим: Первый голос.\nИрина: Второй голос.\nМаксим: Продолжаем эфир.",
        [{"name": "Максим"}, {"name": "Ирина"}],
    )
    assert result and result.is_file()


def test_tts_cleanup_keeps_persisted_audio_with_relative_paths(tmp_path: Path) -> None:
    tts = TTS({"cache_dir": str(tmp_path), "max_cached_spoken_files": 1})
    planned = tts.cache_dir / "host_plan.mp3"
    planned.write_bytes(b"x")
    (tts.cache_dir / "host_latest.mp3").write_bytes(b"x")
    plan_dir = tmp_path / "show_plans"
    plan_dir.mkdir()
    (plan_dir / "plan.json").write_text(json.dumps({"items": [{"kind": "speech", "path": "spoken/host_plan.mp3"}]}))
    tts.cleanup_cache()
    assert planned.exists()


def test_cache_protection_follows_runtime_plan_and_stream_changes(tmp_path: Path) -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update({
        "music_dir": str(tmp_path / "music"), "cache_dir": str(tmp_path / "cache"),
        "show_plan_output_file": str(tmp_path / "plan.json"), "show_plan_restore_on_start": False,
        "news_agent_enabled": False, "track_profiles_enabled": False, "tts_backend": "none",
        "max_cached_spoken_files": 1,
    })
    engine = RadioEngine(cfg)
    paths = [engine.tts.cache_dir / f"host_{index}.mp3" for index in range(4)]
    for path in paths:
        path.write_bytes(b"x")
    engine._building_plan_audio_paths = [paths[0]]
    engine._streaming_audio_paths = [paths[1]]
    engine.prepared_dj = SimpleNamespace(mp3=paths[2])
    engine.tts.cleanup_cache()
    assert all(path.exists() for path in paths)
    engine._building_plan_audio_paths = []
    engine._streaming_audio_paths = []
    engine.prepared_dj = None
    engine.tts.cleanup_cache()
    assert sum(path.exists() for path in paths) == 1


def test_cancelled_plan_audio_is_removed_but_published_audio_is_kept(tmp_path: Path) -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update({"music_dir": str(tmp_path / "music"), "cache_dir": str(tmp_path / "cache"), "tts_backend": "none"})
    engine = RadioEngine(cfg)
    stale = engine.tts.cache_dir / "host_cancelled.mp3"
    published = engine.tts.cache_dir / "host_published.mp3"
    stale.write_bytes(b"x")
    published.write_bytes(b"x")
    engine.show_plan = [SimpleNamespace(kind="speech", path=published)]
    engine._building_plan_audio_paths = [stale]
    engine._discard_unpublished_plan_audio([SimpleNamespace(kind="speech", path=stale)])
    assert not stale.exists()
    assert published.exists()


def test_web_redirect_is_checked_before_private_target_is_contacted(monkeypatch) -> None:
    import ai_truck_radio_app.web_research as research

    contacted = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            contacted.append(self.path)
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/private")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"private data")

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    start = f"http://127.0.0.1:{server.server_port}/start"
    monkeypatch.setattr(research, "_public_url", lambda url: url == start)
    try:
        with pytest.raises(ValueError, match="non-public"):
            research._fetch(start, 2, 4096)
        assert contacted == ["/start"]
        # Public redirects retain the previous behavior.
        monkeypatch.setattr(research, "_public_url", lambda _: True)
        assert research._fetch(start, 2, 4096)[0] == b"private data"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
