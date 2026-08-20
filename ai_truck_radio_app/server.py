# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import ipaddress
import math
import mimetypes
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable, Dict, Optional
from pathlib import Path

from ai_truck_radio_app.config import (
    BASE_DIR,
    APP_NAME,
    APP_VERSION,
    CONFIG_PATH,
    DEFAULT_CONFIG,
    log,
    save_json,
)
from ai_truck_radio_app.entertainment_history import clear_history
from ai_truck_radio_app.panel import render_panel
from ai_truck_radio_app.ref_voice import inspect_reference_pair, transcribe_reference_audio, write_reference_files
from ai_truck_radio_app.settings_profiles import SettingsProfileStore


MAX_FORM_BYTES = 1 * 1024 * 1024
MAX_UPLOAD_BYTES = 82 * 1024 * 1024
SETTINGS_PROFILES_PATH = BASE_DIR / "settings_profiles.json"


class RequestTooLarge(ValueError):
    pass


def _content_length(handler: BaseHTTPRequestHandler, limit: int) -> int:
    raw = handler.headers.get("Content-Length", "0") or "0"
    try:
        length = int(raw)
    except ValueError as exc:
        raise ValueError("Некорректный Content-Length.") from exc
    if length < 0:
        raise ValueError("Некорректный Content-Length.")
    if length > limit:
        raise RequestTooLarge(f"Размер запроса превышает лимит {limit // (1024 * 1024)} МБ.")
    return length


def _is_loopback_host(value: str) -> bool:
    value = value.strip().lower().strip("[]")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _finite_number(raw: Any, key: str, *, minimum: float = -1_000_000.0, maximum: float = 1_000_000.0) -> float:
    try:
        value = float(str(raw).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} должен быть числом.") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} должен быть конечным числом в диапазоне {minimum:g}–{maximum:g}.")
    return value


def _safe_history_setting(value: str) -> str:
    raw = str(value or "").strip()
    candidate = Path(raw)
    if not raw or candidate.is_absolute():
        raise ValueError("Журнал рубрик должен быть относительным путём внутри cache/.")
    resolved = (BASE_DIR / candidate).resolve()
    cache_root = (BASE_DIR / "cache").resolve()
    try:
        resolved.relative_to(cache_root)
    except ValueError as exc:
        raise ValueError("Журнал рубрик можно хранить только внутри cache/.") from exc
    return resolved.relative_to(BASE_DIR.resolve()).as_posix()


def _json_safe_value(value: Any, key: str, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError(f"{key} слишком глубоко вложен.")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{key} содержит неконечное число.")
        return value
    if isinstance(value, dict):
        if len(value) > 200:
            raise ValueError(f"{key} содержит слишком много полей.")
        return {str(k): _json_safe_value(v, f"{key}.{k}", depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 200:
            raise ValueError(f"{key} содержит слишком много элементов.")
        return [_json_safe_value(v, key, depth + 1) for v in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError(f"{key} содержит неподдерживаемое значение.")


def bool_from_form(value: Optional[str]) -> bool:
    return str(value or "").lower() in {"1", "true", "on", "yes", "да"}


def make_stream_url(cfg: Dict[str, Any]) -> str:
    return f"http://{cfg['host']}:{int(cfg['port'])}/stream.mp3"


def make_ets2_line(cfg: Dict[str, Any]) -> str:
    """Backward-compatible stream descriptor used by old integrations."""
    url = f"http://{cfg['host']}:{int(cfg['port'])}/stream.mp3"
    station = str(cfg.get("station_name", "AI Truck Radio"))
    genre = str(cfg.get("station_genre", "AI"))
    lang = str(cfg.get("station_language", "RU"))
    bitrate = int(cfg.get("bitrate_kbps", 128))
    return f'stream_data[999]: "{url}|{station}|{genre}|{lang}|{bitrate}|1"'


def parse_post(handler: BaseHTTPRequestHandler) -> Dict[str, str]:
    length = _content_length(handler, MAX_FORM_BYTES)
    raw = handler.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else ""
    parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
    return {k: v[-1] if v else "" for k, v in parsed.items()}


def _parse_disposition(value: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in value.split(";"):
        item = item.strip()
        if "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        result[key.strip().lower()] = raw_value.strip().strip('"')
    return result


def parse_multipart(handler: BaseHTTPRequestHandler) -> tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    content_type = handler.headers.get("Content-Type", "")
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not match:
        raise ValueError("Multipart boundary не найден.")
    boundary = ("--" + match.group(1)).encode("utf-8")
    length = _content_length(handler, MAX_UPLOAD_BYTES)
    raw = handler.rfile.read(length) if length > 0 else b""
    fields: Dict[str, str] = {}
    files: Dict[str, Dict[str, Any]] = {}
    for part in raw.split(boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--" or part.endswith(b"--") and b"\r\n\r\n" not in part:
            continue
        header_blob, sep, body = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers: Dict[str, str] = {}
        for line in header_blob.decode("utf-8", errors="replace").split("\r\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        disp = _parse_disposition(headers.get("content-disposition", ""))
        name = disp.get("name", "")
        if not name:
            continue
        if body.endswith(b"\r\n"):
            body = body[:-2]
        filename = disp.get("filename")
        if filename is not None:
            files[name] = {"filename": filename, "content": body, "content_type": headers.get("content-type", "")}
        else:
            fields[name] = body.decode("utf-8", errors="replace")
    return fields, files


def make_handler(engine: Any, cfg: Dict[str, Any], start_hotkey_callback: Optional[Callable[[Any], None]] = None):
    profile_store = SettingsProfileStore(SETTINGS_PROFILES_PATH, DEFAULT_CONFIG)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"{APP_NAME}/{APP_VERSION}"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _local_request_allowed(self) -> bool:
            """Reject cross-site writes and Host-header rebinding against the local UI."""
            def reject(message: str) -> bool:
                # Consume a small declared body before replying. On Windows this
                # avoids a TCP reset that can hide the useful 403 from clients.
                try:
                    length = _content_length(self, MAX_FORM_BYTES)
                    if length:
                        self.rfile.read(length)
                except Exception:
                    pass
                self.send_json({"ok": False, "error": message}, status=403)
                return False
            if not _is_loopback_host(str(self.client_address[0])):
                return reject("Локальная панель принимает управляющие запросы только с loopback.")
            host_header = str(self.headers.get("Host", "")).strip()
            if host_header:
                host = host_header.rsplit(":", 1)[0] if not host_header.startswith("[") else host_header.split("]", 1)[0] + "]"
                if not _is_loopback_host(host):
                    return reject("Host должен быть localhost или loopback-адресом.")
            origin = str(self.headers.get("Origin", "")).strip()
            if origin:
                parsed = urllib.parse.urlparse(origin)
                if parsed.scheme != "http" or not parsed.hostname or not _is_loopback_host(parsed.hostname):
                    return reject("Cross-origin запрос к локальной панели отклонён.")
            return True

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ["/", "/index.html"]:
                self.send_html()
            elif path == "/stream.mp3":
                self.stream_live()
            elif path in ["/status.json", "/api/status"]:
                self.send_json(engine.status_snapshot())
            elif path == "/api/show_plan/item/audio":
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    index = int(str((query.get("index") or [""])[-1]))
                except (TypeError, ValueError):
                    self.send_json({"ok": False, "error": "index должен быть целым номером элемента."}, status=400)
                    return
                audio_path = engine.get_show_plan_item_audio(index)
                if audio_path is None:
                    self.send_json({"ok": False, "error": "Озвучка для этого речевого элемента недоступна или устарела."}, status=404)
                    return
                self.send_audio_file(audio_path)
            elif path == "/api/config/defaults":
                self.send_json({"ok": True, "defaults": DEFAULT_CONFIG})
            elif path == "/api/settings_profiles":
                self.send_json({"ok": True, "profiles": profile_store.list_profiles()})
            elif path == "/api/reference_voice/quality":
                reports = []
                references = BASE_DIR / "references"
                for audio_path in sorted(references.glob("*.wav")):
                    report = inspect_reference_pair(engine.cfg, audio_path, audio_path.with_suffix(".txt"))
                    reports.append({
                        "name": audio_path.stem,
                        "audio_path": report.audio_path,
                        "text_path": report.text_path,
                        "ok": report.ok,
                        "audio_ok": report.audio_ok,
                        "duration_sec": report.duration_sec,
                        "sample_rate": report.sample_rate,
                        "channels": report.channels,
                        "transcript_ok": report.transcript.ok,
                        "word_count": report.transcript.word_count,
                        "warnings": list(report.warnings),
                        "error": report.error,
                    })
                self.send_json({"ok": True, "reports": reports})
            elif path == "/api/models":
                probe = engine.lm.probe_models() if hasattr(engine.lm, "probe_models") else {
                    "reachable": True,
                    "models": engine.lm.list_models(),
                    "catalog_models": engine.lm.list_models(),
                    "error": "",
                }
                loaded_models = list(probe.get("models") or [])
                models = list(probe.get("catalog_models") or loaded_models)
                configured = {
                    "lm_model": str(engine.cfg.get("lm_model") or "local-model"),
                    "track_analyzer_model": str(engine.cfg.get("track_analyzer_model") or "local-model"),
                    "entertainment_model": str(engine.cfg.get("entertainment_model") or "local-model"),
                }
                self.send_json({
                    "models": models,
                    "loaded_models": loaded_models,
                    "reachable": bool(probe.get("reachable")),
                    "error": str(probe.get("error") or ""),
                    "used": engine.lm.pick_model() if loaded_models else str(engine.cfg.get("lm_model") or "local-model"),
                    "configured": configured,
                    "available": {
                        key: bool(value == "local-model" and loaded_models or value in loaded_models)
                        for key, value in configured.items()
                    },
                })
            else:
                self.send_json({"ok": False, "error": "Маршрут не найден."}, status=404)

        def do_POST(self) -> None:
            if not self._local_request_allowed():
                return
            path = self.path.split("?", 1)[0]
            try:
                self._do_post(path)
            except RequestTooLarge as e:
                self.send_json({"ok": False, "error": str(e)}, status=413)
            except ValueError as e:
                self.send_json({"ok": False, "error": str(e)}, status=400)
            except Exception as e:
                log(f"HTTP API error {path}: {e}")
                self.send_json({"ok": False, "error": "Внутренняя ошибка API."}, status=500)

        def _do_post(self, path: str) -> None:
            if path == "/api/skip":
                engine.request_skip("web")
                self.send_json({"ok": True})
            elif path == "/api/radio/start":
                form = parse_post(self)
                clean = bool_from_form(form.get("clean")) if "clean" in form else bool(engine.cfg.get("clean_generated_on_start", True))
                started = engine.start_async(clean_generated=clean)
                start_hotkey_callback(engine) if start_hotkey_callback else None
                self.send_json({"ok": started, "started": started, "starting": engine.is_starting(), "running": engine.is_running(), "cleaned": clean}, status=202 if started else 409)
            elif path == "/api/radio/stop":
                engine.stop()
                self.send_json({"ok": True, "running": engine.is_running()})
            elif path == "/api/omnivoice/start":
                started, message = engine.start_omnivoice_service_async()
                self.send_json({"ok": True, "started": started, "message": message, **engine._tts_runtime_status()})
            elif path == "/api/omnivoice/stop":
                stopped, message = engine.stop_omnivoice_service()
                self.send_json({"ok": True, "stopped": stopped, "message": message, **engine._tts_runtime_status()})
            elif path == "/api/radio/restart":
                form = parse_post(self)
                clean = bool_from_form(form.get("clean")) if "clean" in form else bool(engine.cfg.get("clean_generated_on_restart", True))
                engine.stop()
                if engine.broadcast_thread and engine.broadcast_thread.is_alive():
                    engine.broadcast_thread.join(timeout=5.0)
                started = engine.start_async(clean_generated=clean)
                start_hotkey_callback(engine) if start_hotkey_callback else None
                self.send_json({"ok": started, "started": started, "starting": engine.is_starting(), "running": engine.is_running(), "cleaned": clean}, status=202 if started else 409)
            elif path == "/api/clear_generated":
                if engine.is_running():
                    self.send_json({"ok": False, "error": "Сначала останови радио или используй restart."}, status=409)
                else:
                    stats = engine.cleanup_generated_radio_files()
                    self.send_json({"ok": True, **stats})
            elif path == "/api/entertainment/history/clear":
                count = clear_history(engine.cfg)
                engine.entertainment_pack = {}
                engine.entertainment_pack_date = ""
                self.send_json({"ok": True, "removed": count})
            elif path == "/api/reference_voice/upload":
                try:
                    form, files = parse_multipart(self)
                    upload = files.get("audio")
                    if not upload:
                        self.send_json({"ok": False, "error": "Файл audio не передан."}, status=400)
                        return
                    target_type = str(form.get("target_type") or "host").strip().lower()
                    if target_type not in {"host", "guest"}:
                        self.send_json({"ok": False, "error": "target_type должен быть host или guest."}, status=400)
                        return
                    hosts = engine.cfg.get("hosts") if isinstance(engine.cfg.get("hosts"), list) else []
                    host_index = None
                    target_name = str(form.get("name") or "").strip()
                    if target_type == "host":
                        try:
                            host_index = int(float(str(form.get("host_index", "0")).replace(",", ".")))
                        except Exception:
                            host_index = 0
                        if host_index < 0 or host_index >= len(hosts) or not isinstance(hosts[host_index], dict):
                            self.send_json({"ok": False, "error": "Выбранный ведущий не найден."}, status=404)
                            return
                        target_name = target_name or str(hosts[host_index].get("name") or f"host_{host_index + 1}").strip()
                    else:
                        target_name = target_name or str(engine.cfg.get("guest_name") or "guest").strip()

                    manual_text = str(form.get("manual_text") or "").strip()
                    asr_backend = str(form.get("asr_backend") or engine.cfg.get("reference_asr_backend") or "faster-whisper").strip().lower()
                    asr_level = str(form.get("asr_level") or "balanced").strip().lower()
                    if asr_backend not in {"faster-whisper", "whisper", "gigaam", "manual"}:
                        self.send_json({"ok": False, "error": "Неизвестный движок распознавания reference-аудио."}, status=400)
                        return
                    if asr_level not in {"fast", "balanced", "maximum"}:
                        self.send_json({"ok": False, "error": "Неизвестный уровень распознавания reference-аудио."}, status=400)
                        return
                    if asr_backend == "manual" and not manual_text:
                        self.send_json({"ok": False, "error": "Для режима «Только мой текст» заполните точную расшифровку."}, status=400)
                        return
                    ref_audio, ref_text_file = write_reference_files(
                        target_type,
                        target_name,
                        str(upload.get("filename") or ""),
                        bytes(upload.get("content") or b""),
                        manual_text,
                    )
                    ref_text = manual_text
                    asr_ok = False
                    asr_error = ""
                    model_labels = {
                        ("faster-whisper", "fast"): "Whisper small",
                        ("faster-whisper", "balanced"): "Whisper large-v3-turbo",
                        ("faster-whisper", "maximum"): "Whisper large-v3",
                        ("whisper", "fast"): "Whisper small",
                        ("whisper", "balanced"): "Whisper large-v3-turbo",
                        ("whisper", "maximum"): "Whisper large-v3",
                        ("gigaam", "fast"): "GigaAM-v3 e2e CTC",
                        ("gigaam", "balanced"): "GigaAM-v3 e2e RNNT",
                        ("gigaam", "maximum"): "GigaAM-v3 e2e RNNT + CTC",
                    }
                    asr_model = model_labels.get((asr_backend, asr_level), "Ручной текст")
                    if bool_from_form(form.get("auto_transcribe")) and asr_backend != "manual":
                        checked_text, asr_ok, asr_error = transcribe_reference_audio(
                            engine.cfg,
                            BASE_DIR / ref_audio,
                            manual_text=manual_text,
                            backend=asr_backend,
                            level=asr_level,
                        )
                        if checked_text:
                            ref_text = checked_text
                            (BASE_DIR / ref_text_file).write_text(ref_text, encoding="utf-8")

                    updates: Dict[str, Any] = {}
                    if target_type == "guest":
                        updates = {
                            "guest_voice_mode": "reference",
                            "guest_ref_audio": ref_audio,
                            "guest_ref_text": ref_text_file,
                        }
                    else:
                        clean_hosts = list(hosts)
                        selected_host_index = int(host_index or 0)
                        host = dict(clean_hosts[selected_host_index])
                        host["omnivoice_mode"] = "clone"
                        host["omnivoice_ref_audio"] = ref_audio
                        host["omnivoice_ref_text"] = ref_text
                        clean_hosts[selected_host_index] = host
                        updates = {"hosts": clean_hosts}
                    engine.update_config(updates)
                    self.send_json({
                        "ok": True,
                        "target_type": target_type,
                        "host_index": host_index,
                        "ref_audio": ref_audio,
                        "ref_text_file": ref_text_file,
                        "ref_text": ref_text,
                        "asr_ok": asr_ok,
                        "asr_error": asr_error,
                        "asr_warning": asr_error if asr_ok else "",
                        "asr_model": asr_model,
                        "asr_backend": asr_backend,
                        "asr_level": asr_level,
                    })
                except RequestTooLarge:
                    raise
                except Exception as e:
                    log(f"Reference upload failed: {e}")
                    self.send_json({"ok": False, "error": str(e)}, status=400)
            elif path == "/api/rescan":
                engine.refresh_tracks()
                self.send_json({"ok": True, "music_count": len(engine.tracks)})
            elif path == "/api/track_profiles/build":
                form = parse_post(self)
                limit = None
                try:
                    if form.get("limit"):
                        limit = int(float(str(form.get("limit", "0")).replace(",", ".")))
                except Exception:
                    limit = None
                force_existing = bool_from_form(form.get("force_existing")) if "force_existing" in form else bool(engine.cfg.get("track_profiles_force_rebuild_existing", False))
                engine.cfg["track_profiles_force_rebuild_existing"] = force_existing
                save_json(CONFIG_PATH, engine.cfg)
                ok = engine.start_track_profiles_build(limit, force_existing=force_existing)
                self.send_json({"ok": True, "started": ok, "status": engine.track_profile_status, "force_existing": force_existing})
            elif path == "/api/track_profiles/cancel":
                cancelled = engine.cancel_track_profiles_build()
                self.send_json({"ok": True, "cancelled": cancelled, "status": engine.track_profile_status})
            elif path == "/api/show_plan/generate":
                form = parse_post(self)
                minutes = None
                try:
                    if form.get("minutes"):
                        minutes = int(float(form.get("minutes", "0")))
                except Exception:
                    minutes = None
                ok = engine.start_show_plan_generation(minutes)
                self.send_json({"ok": True, "started": ok, "status": engine.show_plan_status})
            elif path == "/api/show_plan/cancel":
                cancelled = engine.cancel_show_plan_generation()
                self.send_json({"ok": True, "cancelled": cancelled, "status": engine.show_plan_status})
            elif path == "/api/show_plan/item/text":
                form = parse_post(self)
                try:
                    index = int(str(form.get("index", "")))
                except (TypeError, ValueError):
                    raise ValueError("index должен быть целым номером элемента.")
                result = engine.update_show_plan_item_text(
                    index,
                    form.get("text", ""),
                    rerender=bool_from_form(form.get("rerender")),
                )
                self.send_json({"ok": True, **result})
            elif path == "/api/show_plan/item/action":
                form = parse_post(self)
                try:
                    index = int(str(form.get("index", "")))
                    target_index = int(str(form.get("target_index") or "0"))
                except (TypeError, ValueError):
                    raise ValueError("index и target_index должны быть целыми номерами.")
                result = engine.mutate_show_plan_item(
                    index,
                    form.get("action", ""),
                    target_index=target_index,
                )
                self.send_json({"ok": True, **result})
            elif path == "/api/show_plan/clear":
                removed = engine.clear_show_plan()
                self.send_json({"ok": True, "removed": removed})
            elif path == "/api/news/refresh":
                started = engine.start_news_refresh()
                self.send_json({"ok": True, "started": started, "status": engine.news_status}, status=202 if started else 200)
            elif path == "/api/news/item/status":
                form = parse_post(self)
                item = engine.set_news_item_status(form.get("draft_id", ""), form.get("status", ""))
                self.send_json({"ok": True, "item": item})
            elif path == "/api/show_plan/disable":
                engine.cfg["show_plan_enabled"] = False
                save_json(CONFIG_PATH, engine.cfg)
                with engine.plan_lock:
                    engine.show_plan_status = "переключаюсь в live-режим; текущий трек/речь аккуратно завершится или будет пропущен"
                engine.skip_event.set()
                self.send_json({"ok": True, "mode": "live"})
            elif path == "/api/show_plan/enable":
                with engine.plan_lock:
                    have_plan = bool(engine.show_plan and engine.show_plan_index < len(engine.show_plan))
                    engine.show_plan_status = "плановый режим включён; готовый план будет взят после текущего элемента" if have_plan else "готового плана нет, запускаю подготовку до включения режима"
                if have_plan:
                    engine.cfg["show_plan_enabled"] = True
                    engine.cfg["show_plan_rebuild_on_start"] = False
                    save_json(CONFIG_PATH, engine.cfg)
                else:
                    engine.start_show_plan_generation(None)
                if have_plan:
                    engine.skip_event.set()
                self.send_json({"ok": True, "mode": "planned" if have_plan else "live", "have_plan": have_plan})
            elif path == "/api/show_plan/prepare_next":
                engine._start_prepare_next_show_plan()
                self.send_json({"ok": True, "status": engine.show_plan_status})
            elif path == "/api/config/reset_key":
                form = parse_post(self)
                key = str(form.get("key", "")).strip()
                if key not in DEFAULT_CONFIG:
                    self.send_json({"ok": False, "error": "Неизвестный параметр"}, status=400)
                    return
                engine.update_config({key: DEFAULT_CONFIG[key]})
                self.send_json({"ok": True, "key": key, "value": engine.cfg.get(key)})
            elif path == "/api/settings_profiles/create":
                form = parse_post(self)
                profile = profile_store.create(form.get("name"), engine.cfg)
                self.send_json({"ok": True, "profile": profile, "profiles": profile_store.list_profiles()})
            elif path == "/api/settings_profiles/rename":
                form = parse_post(self)
                profile = profile_store.rename(form.get("id"), form.get("name"))
                self.send_json({"ok": True, "profile": profile, "profiles": profile_store.list_profiles()})
            elif path == "/api/settings_profiles/delete":
                form = parse_post(self)
                profile = profile_store.delete(form.get("id"))
                self.send_json({"ok": True, "profile": profile, "profiles": profile_store.list_profiles()})
            elif path == "/api/settings_profiles/apply":
                form = parse_post(self)
                profile_id = str(form.get("id") or "")
                updates = profile_store.settings_for_apply(profile_id)
                engine.update_config(updates)
                profile = next(
                    (item for item in profile_store.list_profiles() if item["id"] == profile_id),
                    None,
                )
                self.send_json({"ok": True, "profile": profile, "updates": updates})
            elif path == "/api/save_config":
                form = parse_post(self)
                updates: Dict[str, Any] = {}
                if "station_style" in form:
                    updates["station_style"] = form["station_style"]
                if "weather_city" in form:
                    updates["weather_city"] = form["weather_city"].strip()
                if "host_mode" in form:
                    updates["host_mode"] = form["host_mode"].strip()
                if "host_solo_name" in form:
                    updates["host_solo_name"] = form["host_solo_name"].strip()
                if "hosts_json" in form:
                    try:
                        hosts_data = json.loads(form.get("hosts_json") or "[]")
                        if isinstance(hosts_data, list):
                            clean_hosts = []
                            for h in hosts_data:
                                if not isinstance(h, dict):
                                    continue
                                nm = str(h.get("name", "")).strip()
                                if not nm:
                                    continue
                                aliases_raw = h.get("aliases")
                                if isinstance(aliases_raw, str):
                                    aliases = [x.strip() for x in aliases_raw.split(",") if x.strip()]
                                elif isinstance(aliases_raw, list):
                                    aliases = [str(x).strip() for x in aliases_raw if str(x).strip()]
                                else:
                                    aliases = []
                                # Host profiles contain backend-specific fields
                                # that evolve independently. Preserve every
                                # JSON-safe supplied field instead of silently
                                # erasing voices/personas unknown to this server.
                                clean = _json_safe_value(dict(h), "hosts")
                                clean["name"] = nm
                                clean["aliases"] = aliases
                                for flag in ("enabled", "intro_enabled", "regular_enabled"):
                                    if flag in clean:
                                        value = clean[flag]
                                        clean[flag] = bool_from_form(value) if isinstance(value, str) else bool(value)
                                try:
                                    weight = float(clean.get("air_weight", 1.0) or 1.0)
                                except (TypeError, ValueError):
                                    raise ValueError("air_weight ведущего должен быть числом.")
                                if not math.isfinite(weight) or not 0.01 <= weight <= 100.0:
                                    raise ValueError("air_weight ведущего должен быть в диапазоне 0.01–100.")
                                clean["air_weight"] = weight
                                clean_hosts.append(clean)
                            if clean_hosts:
                                updates["hosts"] = clean_hosts
                    except Exception as e:
                        log(f"Не удалось разобрать hosts_json из панели: {e}")
                checkbox_keys_all = ["weather_enabled", "news_enabled", "news_agent_enabled", "news_agent_generate_before_radio", "news_agent_factcheck_enabled", "news_agent_structured_output", "news_agent_no_think", "two_hosts_enabled", "tts_speak_host_names", "fade_enabled", "speech_takeover_enabled", "speech_takeover_only_if_prepared", "speech_takeover_crossfade_enabled", "track_profiles_enabled", "track_profiles_web_lookup_enabled", "track_profiles_agent_factcheck_enabled", "track_profiles_agent_append_no_think", "track_profiles_agent_structured_output", "night_mode_enabled", "hotkey_enabled", "lm_enabled", "lm_append_no_think", "lm_compact_host_prompt", "intro_before_first_track", "startup_intro_blocking", "async_prepare_dj", "qwen3_tts_persistent_worker", "show_experimental_tts_backends", "omnivoice_persistent_worker", "omnivoice_prewarm_on_radio_start", "omnivoice_normalize_ru", "omnivoice_nonverbal_tags_enabled", "reference_asr_enabled", "reference_asr_review_enabled", "reference_asr_keep_model_loaded", "speech_radio_processing_enabled", "speech_compressor_enabled", "speech_presence_eq_enabled", "speech_loudnorm_enabled", "speech_limiter_enabled", "jingle_enabled", "auto_generate_sweep_jingle", "show_plan_enabled", "show_plan_block_until_ready", "show_plan_include_intro", "show_plan_rebuild_on_start", "show_plan_restore_on_start", "show_plan_continuous_extend", "show_plan_live_after_exhausted", "show_plan_intro_long_opening", "show_plan_unique_greetings", "show_plan_fill_music_while_generating", "show_plan_auto_enable_after_generation", "exact_hour_time_announce_enabled", "listener_greetings_enabled", "tts_parse_validation_enabled", "radio_autostart", "clean_generated_on_start", "clean_generated_on_restart", "station_id_enabled", "station_id_fallback_tts_enabled", "live_blocking_dj_when_due", "live_prepare_at_track_start_when_due", "startup_intro_reserve_first_track", "host_should_use_stress_marks", "host_duo_intro_in_mostly_solo", "strict_duo_intro_require_both", "avoid_road_cliche_prompt", "season_reality_guard_enabled", "host_creative_fact_mode", "host_strict_clock_guard", "live_expected_speech_time_enabled", "omnivoice_prewarm_on_radio_start", "entertainment_enabled", "entertainment_in_live", "entertainment_in_planned", "horoscope_enabled", "horoscope_generate_before_radio", "riddles_enabled", "wrong_answer_game_enabled", "entertainment_generate_with_lm", "entertainment_status_in_panel", "guest_enabled", "guest_in_live", "guest_in_planned", "guest_generate_before_radio", "guest_allow_unverified_lm", "guest_voice_warning_in_panel", "track_profiles_wikipedia_enabled", "track_profiles_wikidata_enabled", "track_profiles_deezer_enabled", "track_profiles_itunes_enabled", "track_profiles_enrich_missing_web_only", "track_profiles_enrich_only_if_no_sources"]
                checkbox_keys_all += [
                    "entertainment_agent_enabled",
                    "entertainment_agent_factcheck_enabled",
                    "entertainment_agent_no_think",
                    "entertainment_agent_structured_output",
                ]
                checkbox_keys_all = list(dict.fromkeys(checkbox_keys_all))
                if "_checkbox_keys" in form:
                    wanted = {x.strip() for x in form.get("_checkbox_keys", "").split(",") if x.strip()}
                    # A save is a PATCH.  Old panels listed controls that were
                    # not rendered, so a missing value must never mean False.
                    checkbox_keys = [k for k in checkbox_keys_all if k in wanted and k in form]
                else:
                    checkbox_keys = [k for k in checkbox_keys_all if k in form]
                for key in checkbox_keys:
                    updates[key] = bool_from_form(form.get(key))
                for key in ["music_dir", "ffmpeg_path", "lm_model", "lm_reasoning_effort", "track_analyzer_model", "entertainment_model", "tts_backend", "dj_talk_profile", "dj_topic_mode", "qwen3_tts_model_id", "qwen3_tts_instruct", "weather_provider", "qwen3_tts_device_map", "qwen3_tts_dtype", "lmstudio_tts_base_url", "lmstudio_tts_model", "lmstudio_tts_voice", "lmstudio_tts_response_format", "omnivoice_model", "omnivoice_device", "omnivoice_mode", "omnivoice_pronunciation_file", "omnivoice_python", "omnivoice_hf_home", "jingle_dir", "speech_bed_dir", "track_profiles_file", "track_profiles_fact_mode", "track_profiles_research_mode", "track_profiles_web_lookup_provider", "track_profiles_wikipedia_languages", "speech_bed_mode", "listener_greetings_file", "show_plan_output_file", "station_id_dir", "entertainment_integration_mode", "horoscope_source_mode", "riddle_source_mode", "guest_name", "guest_role", "guest_voice_mode", "guest_voice_instruct", "guest_ref_audio", "guest_ref_text", "host_favorite_names", "reference_asr_backend", "reference_asr_model", "reference_asr_device", "reference_asr_compute_type", "reference_asr_cache_dir", "reference_asr_language", "reference_asr_review_model", "reference_asr_review_device", "reference_asr_review_compute_type"]:
                    if key in form:
                        updates[key] = form[key].strip()
                if "reference_asr_level" in form:
                    level = form["reference_asr_level"].strip().lower()
                    if level not in {"fast", "balanced", "maximum"}:
                        raise ValueError("reference_asr_level должен быть fast, balanced или maximum.")
                    updates["reference_asr_level"] = level
                if "entertainment_history_file" in form:
                    updates["entertainment_history_file"] = _safe_history_setting(form["entertainment_history_file"])
                if "entertainment_daily_cache_dir" in form:
                    updates["entertainment_daily_cache_dir"] = form["entertainment_daily_cache_dir"].strip()
                if "entertainment_history_max_items" in form:
                    updates["entertainment_history_max_items"] = int(
                        _finite_number(form["entertainment_history_max_items"], "entertainment_history_max_items", minimum=100, maximum=100_000)
                    )
                for key in ["dj_every_n_tracks_min", "dj_every_n_tracks_max", "bitrate_kbps", "lm_max_tokens", "lm_timeout_sec", "strict_duo_intro_retry_attempts", "show_plan_duration_minutes", "show_plan_min_tracks_between_speech", "show_plan_max_tracks_between_speech", "show_plan_prepare_next_threshold_items", "show_plan_prepare_next_threshold_minutes", "exact_hour_window_minutes", "listener_greetings_every_tracks_min", "listener_greetings_every_tracks_max", "station_id_every_tracks", "track_profiles_agent_max_queries", "track_profiles_agent_search_results_per_query", "track_profiles_agent_max_pages", "track_profiles_agent_min_page_chars", "track_profiles_agent_page_chars", "track_profiles_agent_total_evidence_chars", "track_profiles_agent_page_timeout_sec", "track_profiles_agent_max_tokens", "track_profiles_wikipedia_cooldown_sec", "track_profiles_musicbrainz_cooldown_sec", "entertainment_min_blocks_between", "horoscope_chunk_min", "horoscope_chunk_max", "horoscope_blocks_before_riddle_min", "horoscope_blocks_before_riddle_max", "riddle_min_blocks_between", "riddle_options_count", "wrong_answer_game_min_blocks_between", "entertainment_pack_timeout_sec", "entertainment_pack_max_items", "rubric_web_timeout_sec", "entertainment_agent_results_per_query", "entertainment_agent_max_pages", "entertainment_agent_pages_per_topic", "entertainment_agent_min_page_chars", "entertainment_agent_page_chars", "entertainment_agent_total_evidence_chars", "entertainment_agent_page_timeout_sec", "entertainment_agent_max_tokens", "guest_min_blocks_between", "guest_story_count", "host_active_count_min", "host_active_count_max", "host_intro_count", "host_regular_count_min", "host_regular_count_max", "startup_intro_time_lead_sec", "max_host_text_chars", "reference_asr_beam_size"]:
                    if key in form:
                        minimum = 16 if key == "bitrate_kbps" else 0
                        maximum = 512 if key == "bitrate_kbps" else 1_000_000
                        value = _finite_number(form[key], key, minimum=minimum, maximum=maximum)
                        if not value.is_integer():
                            raise ValueError(f"{key} должен быть целым числом.")
                        updates[key] = int(value)
                for key in ["music_fade_in_sec", "music_fade_out_sec", "speech_fade_in_sec", "speech_fade_out_sec", "transition_silence_sec", "speech_takeover_sec", "speech_takeover_min_track_sec", "speech_bed_volume", "speech_voice_volume", "music_volume", "speech_presence_gain_db", "jingle_chance_after_speech", "jingle_volume", "host_duo_chance", "host_regular_multi_chance", "dj_short_talk_chance", "dj_medium_talk_chance", "dj_long_talk_chance", "lm_temperature", "track_profiles_agent_temperature", "entertainment_agent_temperature", "qwen3_tts_gpu_memory_limit_gb", "qwen3_tts_cpu_memory_limit_gb", "weather_timeout_sec", "lmstudio_tts_speed", "lmstudio_tts_timeout_sec", "omnivoice_steps", "omnivoice_speed", "omnivoice_tail_silence_ms", "omnivoice_worker_start_timeout_sec", "omnivoice_worker_job_timeout_sec", "speech_loudnorm_i", "show_plan_long_block_chance", "listener_greetings_chance", "tts_parse_validation_min_ratio", "station_id_chance", "station_id_volume", "track_profiles_web_delay_sec", "live_prepare_trigger_fraction", "show_plan_prepare_next_fraction", "entertainment_chance", "wrong_answer_game_chance", "guest_chance", "host_favorite_chance", "host_multi_chance", "omnivoice_nonverbal_tags_chance"]:
                    if key in form:
                        chance_key = key.endswith("_chance") or key in {"live_prepare_trigger_fraction", "show_plan_prepare_next_fraction", "tts_parse_validation_min_ratio"}
                        updates[key] = _finite_number(form[key], key, minimum=0.0 if chance_key else -100_000.0, maximum=1.0 if chance_key else 1_000_000.0)
                # Forward-compatible PATCH fallback: accept every scalar default
                # setting even when a newer panel exposes a field before this
                # server's hand-written lists have been updated. Unknown keys
                # remain ignored, preventing arbitrary config injection.
                for key, raw in form.items():
                    if key in updates or key not in DEFAULT_CONFIG:
                        continue
                    default = DEFAULT_CONFIG[key]
                    if isinstance(default, bool):
                        updates[key] = bool_from_form(raw)
                    elif isinstance(default, int) and not isinstance(default, bool):
                        value = _finite_number(raw, key, minimum=0, maximum=1_000_000)
                        if not value.is_integer():
                            raise ValueError(f"{key} должен быть целым числом.")
                        updates[key] = int(value)
                    elif isinstance(default, float):
                        updates[key] = _finite_number(raw, key)
                    elif isinstance(default, str):
                        if len(raw) > 16_000:
                            raise ValueError(f"{key} слишком длинный.")
                        updates[key] = raw.strip()
                engine.update_config(updates)
                self.send_json({"ok": True, "updates": updates})
            else:
                self.send_json({"ok": False, "error": "Маршрут не найден."}, status=404)

        def stream_live(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            sid, q = engine.add_subscriber()
            try:
                while True:
                    chunk = q.get()
                    if chunk is None:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                engine.remove_subscriber(sid)

        def send_json(self, data: Dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def send_audio_file(self, path: Path) -> None:
            """Serve only engine-approved plan audio with an explicit length/type."""
            try:
                size = path.stat().st_size
                if size <= 0:
                    raise OSError("empty audio")
            except OSError:
                self.send_json({"ok": False, "error": "Аудиофайл больше недоступен."}, status=404)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            with path.open("rb") as audio:
                while chunk := audio.read(64 * 1024):
                    self.wfile.write(chunk)

        def send_html(self) -> None:
            snap = engine.status_snapshot()
            html_body = render_panel(engine, engine.cfg, snap, DEFAULT_CONFIG, APP_NAME, APP_VERSION)
            raw = html_body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler



