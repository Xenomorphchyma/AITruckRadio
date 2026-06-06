# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable, Dict, Optional

from ai_truck_radio_app.config import (
    APP_NAME,
    APP_VERSION,
    CONFIG_PATH,
    DEFAULT_CONFIG,
    log,
    save_json,
)
from ai_truck_radio_app.panel import render_panel


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
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else ""
    parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
    return {k: v[-1] if v else "" for k, v in parsed.items()}


def make_handler(engine: Any, cfg: Dict[str, Any], start_hotkey_callback: Optional[Callable[[Any], None]] = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"{APP_NAME}/{APP_VERSION}"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ["/", "/index.html"]:
                self.send_html()
            elif path == "/stream.mp3":
                self.stream_live()
            elif path in ["/status.json", "/api/status"]:
                self.send_json(engine.status_snapshot())
            elif path == "/api/config/defaults":
                self.send_json({"ok": True, "defaults": DEFAULT_CONFIG})
            elif path == "/api/models":
                self.send_json({"models": engine.lm.list_models(), "used": engine.lm.pick_model()})
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/skip":
                engine.request_skip("web")
                self.send_json({"ok": True})
            elif path == "/api/radio/start":
                form = parse_post(self)
                clean = bool_from_form(form.get("clean")) if "clean" in form else bool(engine.cfg.get("clean_generated_on_start", True))
                engine.start(clean_generated=clean)
                start_hotkey_callback(engine) if start_hotkey_callback else None
                self.send_json({"ok": True, "running": engine.is_running(), "cleaned": clean})
            elif path == "/api/radio/stop":
                engine.stop()
                self.send_json({"ok": True, "running": engine.is_running()})
            elif path == "/api/radio/restart":
                form = parse_post(self)
                clean = bool_from_form(form.get("clean")) if "clean" in form else bool(engine.cfg.get("clean_generated_on_restart", True))
                engine.restart(clean_generated=clean)
                start_hotkey_callback(engine) if start_hotkey_callback else None
                self.send_json({"ok": True, "running": engine.is_running(), "cleaned": clean})
            elif path == "/api/clear_generated":
                if engine.is_running():
                    self.send_json({"ok": False, "error": "Сначала останови радио или используй restart."})
                else:
                    stats = engine.cleanup_generated_radio_files()
                    self.send_json({"ok": True, **stats})
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
            elif path == "/api/show_plan/clear":
                with engine.plan_lock:
                    engine.show_plan = []
                    engine.next_show_plan = []
                    engine.show_plan_index = 0
                    engine.show_plan_status = "план очищен"
                self.send_json({"ok": True})
            elif path == "/api/show_plan/disable":
                engine.cfg["show_plan_enabled"] = False
                save_json(CONFIG_PATH, engine.cfg)
                with engine.plan_lock:
                    engine.show_plan_status = "переключаюсь в live-режим; текущий трек/речь аккуратно завершится или будет пропущен"
                engine.skip_event.set()
                self.send_json({"ok": True, "mode": "live"})
            elif path == "/api/show_plan/enable":
                engine.cfg["show_plan_enabled"] = True
                engine.cfg["show_plan_rebuild_on_start"] = False
                save_json(CONFIG_PATH, engine.cfg)
                with engine.plan_lock:
                    have_plan = bool(engine.show_plan and engine.show_plan_index < len(engine.show_plan))
                    engine.show_plan_status = "плановый режим включён; готовый план будет взят после текущего элемента" if have_plan else "плановый режим включён; готового плана нет, запускаю подготовку"
                if not have_plan:
                    engine.start_show_plan_generation(None)
                engine.skip_event.set()
                self.send_json({"ok": True, "mode": "planned", "have_plan": have_plan})
            elif path == "/api/show_plan/prepare_next":
                engine._start_prepare_next_show_plan()
                self.send_json({"ok": True, "status": engine.show_plan_status})
            elif path == "/api/config/reset_key":
                form = parse_post(self)
                key = str(form.get("key", "")).strip()
                if key not in DEFAULT_CONFIG:
                    self.send_json({"ok": False, "error": "Неизвестный параметр"})
                    return
                engine.update_config({key: DEFAULT_CONFIG[key]})
                self.send_json({"ok": True, "key": key, "value": engine.cfg.get(key)})
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
                                clean_hosts.append({
                                    "name": nm,
                                    "enabled": bool(h.get("enabled", True)),
                                    "aliases": aliases,
                                    "persona": str(h.get("persona", "")).strip(),
                                    "omnivoice_ref_audio": str(h.get("omnivoice_ref_audio", "")).strip(),
                                    "omnivoice_ref_text": str(h.get("omnivoice_ref_text", "")).strip(),
                                    "omnivoice_instruct": str(h.get("omnivoice_instruct", "")).strip(),
                                    "omnivoice_steps": h.get("omnivoice_steps", ""),
                                    "omnivoice_speed": h.get("omnivoice_speed", ""),
                                })
                            if clean_hosts:
                                updates["hosts"] = clean_hosts
                    except Exception as e:
                        log(f"Не удалось разобрать hosts_json из панели: {e}")
                checkbox_keys_all = ["weather_enabled", "news_enabled", "two_hosts_enabled", "tts_speak_host_names", "fade_enabled", "speech_bed_enabled", "speech_takeover_enabled", "speech_takeover_only_if_prepared", "track_profiles_enabled", "track_profiles_web_lookup_enabled", "track_profiles_force_rebuild_existing", "night_mode_enabled", "hotkey_enabled", "lm_enabled", "lm_append_no_think", "intro_before_first_track", "startup_intro_blocking", "async_prepare_dj", "qwen3_tts_persistent_worker", "show_experimental_tts_backends", "omnivoice_persistent_worker", "omnivoice_prewarm_on_radio_start", "omnivoice_normalize_ru", "omnivoice_nonverbal_tags_enabled", "speech_radio_processing_enabled", "speech_compressor_enabled", "speech_presence_eq_enabled", "speech_loudnorm_enabled", "speech_limiter_enabled", "jingle_enabled", "auto_generate_sweep_jingle", "show_plan_enabled", "show_plan_block_until_ready", "show_plan_include_intro", "show_plan_rebuild_on_start", "show_plan_continuous_extend", "show_plan_live_after_exhausted", "show_plan_intro_long_opening", "show_plan_unique_greetings", "show_plan_fill_music_while_generating", "show_plan_auto_enable_after_generation", "exact_hour_time_announce_enabled", "listener_greetings_enabled", "tts_parse_validation_enabled", "radio_autostart", "clean_generated_on_start", "clean_generated_on_restart", "station_id_enabled", "station_id_fallback_tts_enabled", "live_blocking_dj_when_due", "live_prepare_at_track_start_when_due", "startup_intro_reserve_first_track", "host_should_use_stress_marks", "host_duo_intro_in_mostly_solo", "strict_duo_intro_require_both", "avoid_road_cliche_prompt", "season_reality_guard_enabled", "host_creative_fact_mode", "host_strict_clock_guard", "live_expected_speech_time_enabled", "omnivoice_prewarm_on_radio_start", "entertainment_enabled", "entertainment_in_live", "entertainment_in_planned", "horoscope_enabled", "horoscope_generate_before_radio", "riddles_enabled", "wrong_answer_game_enabled", "entertainment_generate_with_lm", "entertainment_status_in_panel", "guest_enabled", "guest_in_live", "guest_in_planned", "guest_generate_before_radio", "guest_voice_warning_in_panel", "track_profiles_wikipedia_enabled", "track_profiles_wikidata_enabled", "track_profiles_deezer_enabled", "track_profiles_itunes_enabled", "track_profiles_enrich_missing_web_only", "track_profiles_enrich_only_if_no_sources", "station_id_enabled", "station_id_fallback_tts_enabled", "live_blocking_dj_when_due", "live_prepare_at_track_start_when_due", "startup_intro_reserve_first_track", "host_should_use_stress_marks", "host_duo_intro_in_mostly_solo", "strict_duo_intro_require_both", "avoid_road_cliche_prompt", "season_reality_guard_enabled"]
                checkbox_keys_all = list(dict.fromkeys(checkbox_keys_all))
                if "_checkbox_keys" in form:
                    wanted = {x.strip() for x in form.get("_checkbox_keys", "").split(",") if x.strip()}
                    checkbox_keys = [k for k in checkbox_keys_all if k in wanted]
                else:
                    checkbox_keys = []
                for key in checkbox_keys:
                    updates[key] = bool_from_form(form.get(key))
                for key in ["lm_model", "tts_backend", "dj_talk_profile", "dj_topic_mode", "qwen3_tts_model_id", "qwen3_tts_instruct", "weather_provider", "qwen3_tts_device_map", "qwen3_tts_dtype", "lmstudio_tts_base_url", "lmstudio_tts_model", "lmstudio_tts_voice", "lmstudio_tts_response_format", "omnivoice_model", "omnivoice_device", "omnivoice_mode", "omnivoice_pronunciation_file", "omnivoice_python", "omnivoice_hf_home", "jingle_dir", "speech_bed_dir", "track_profiles_file", "track_profiles_fact_mode", "track_profiles_research_mode", "track_profiles_web_lookup_provider", "track_profiles_wikipedia_languages", "speech_bed_mode", "listener_greetings_file", "show_plan_output_file", "station_id_dir", "entertainment_integration_mode", "horoscope_source_mode", "riddle_source_mode", "guest_name", "guest_role", "guest_voice_mode", "guest_voice_instruct", "guest_ref_audio", "guest_ref_text", "host_favorite_names"]:
                    if key in form:
                        updates[key] = form[key].strip()
                for key in ["dj_every_n_tracks_min", "dj_every_n_tracks_max", "bitrate_kbps", "lm_max_tokens", "lm_timeout_sec", "strict_duo_intro_retry_attempts", "show_plan_duration_minutes", "show_plan_min_tracks_between_speech", "show_plan_max_tracks_between_speech", "show_plan_prepare_next_threshold_items", "show_plan_prepare_next_threshold_minutes", "exact_hour_window_minutes", "listener_greetings_every_tracks_min", "listener_greetings_every_tracks_max", "station_id_every_tracks", "track_profiles_agent_max_queries", "track_profiles_agent_max_pages", "track_profiles_agent_page_chars", "track_profiles_agent_total_evidence_chars", "track_profiles_agent_page_timeout_sec", "track_profiles_agent_max_tokens", "track_profiles_wikipedia_cooldown_sec", "track_profiles_musicbrainz_cooldown_sec", "entertainment_min_blocks_between", "horoscope_chunk_min", "horoscope_chunk_max", "horoscope_blocks_before_riddle_min", "horoscope_blocks_before_riddle_max", "riddle_min_blocks_between", "riddle_options_count", "wrong_answer_game_min_blocks_between", "entertainment_pack_timeout_sec", "entertainment_pack_max_items", "rubric_web_timeout_sec", "guest_min_blocks_between", "guest_story_count", "host_active_count_min", "host_active_count_max", "startup_intro_time_lead_sec", "max_host_text_chars"]:
                    if key in form:
                        try:
                            updates[key] = int(float(str(form[key]).replace(",", ".")))
                        except Exception:
                            pass
                for key in ["music_fade_in_sec", "music_fade_out_sec", "speech_fade_in_sec", "speech_fade_out_sec", "transition_silence_sec", "speech_takeover_sec", "speech_takeover_min_track_sec", "speech_bed_volume", "speech_voice_volume", "music_volume", "speech_presence_gain_db", "jingle_chance_after_speech", "jingle_volume", "host_duo_chance", "dj_short_talk_chance", "dj_medium_talk_chance", "dj_long_talk_chance", "lm_temperature", "qwen3_tts_gpu_memory_limit_gb", "qwen3_tts_cpu_memory_limit_gb", "weather_timeout_sec", "lmstudio_tts_speed", "lmstudio_tts_timeout_sec", "omnivoice_steps", "omnivoice_speed", "omnivoice_tail_silence_ms", "omnivoice_worker_start_timeout_sec", "omnivoice_worker_job_timeout_sec", "speech_loudnorm_i", "show_plan_long_block_chance", "listener_greetings_chance", "tts_parse_validation_min_ratio", "station_id_chance", "station_id_volume", "track_profiles_web_delay_sec", "live_prepare_trigger_fraction", "show_plan_prepare_next_fraction", "entertainment_chance", "wrong_answer_game_chance", "guest_chance", "host_favorite_chance", "host_multi_chance", "omnivoice_nonverbal_tags_chance"]:
                    if key in form:
                        try:
                            updates[key] = float(str(form[key]).replace(",", "."))
                        except Exception:
                            pass
                engine.update_config(updates)
                self.send_json({"ok": True, "updates": updates})
            else:
                self.send_response(404)
                self.end_headers()

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

        def send_json(self, data: Dict[str, Any]) -> None:
            raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

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



