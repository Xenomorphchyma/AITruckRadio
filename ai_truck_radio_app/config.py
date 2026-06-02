# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


APP_NAME = "AI Truck Radio"
APP_VERSION = "0.8.0-host-ui-time-rubric-fixes"
BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config.json"
MUSIC_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".opus", ".wma"}

RUS_WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
RUS_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8765,
    "station_name": "AI Дальнобой FM",
    "station_genre": "AI / Road Radio",
    "station_language": "RU",
    "bitrate_kbps": 128,

    "music_dir": "music",
    "cache_dir": "cache",
    "shuffle": True,

    "ffmpeg_path": "ffmpeg",
    "ffprobe_path": "",  # пусто = попробовать ffprobe рядом с ffmpeg или из PATH

    "lm_enabled": True,
    "lm_base_url": "http://127.0.0.1:1234/v1",
    "lm_model": "local-model",  # local-model = первая модель из LM Studio /v1/models
    "lm_temperature": 0.78,
    "lm_max_tokens": 760,
    "lm_timeout_sec": 90,
    "lm_append_no_think": False,  # False = разрешаем Thinking в LM Studio, если он включён в модели

    "tts_backend": "omnivoice",  # core: omnivoice | piper | sapi | none
    "show_experimental_tts_backends": False,
    "sapi_voice_contains": "",
    "sapi_rate": 0,
    "sapi_volume": 100,

    "piper_exe": "piper",
    "piper_python": ".venv\\Scripts\\python.exe",
    "piper_voice": "ru_RU-ruslan-medium",
    "piper_data_dir": "voices",
    "piper_model": "voices/ru_RU-ruslan-medium.onnx",
    "piper_extra_args": [],

    "omnivoice_python": ".venv_omnivoice\\Scripts\\python.exe",
    "omnivoice_hf_home": ".hf_cache",
    "omnivoice_hf_hub_cache": ".hf_cache/hub",
    "omnivoice_hf_xet_cache": ".hf_cache/xet",
    "omnivoice_torch_home": ".torch_cache",
    "omnivoice_model": "k2-fsa/OmniVoice",
    "omnivoice_device": "cuda:0",  # cuda:0 | cpu | auto
    "omnivoice_mode": "clone",  # clone | design | auto
    "omnivoice_steps": 16,
    "omnivoice_speed": 1.0,
    "omnivoice_tail_silence_ms": 260,
    "omnivoice_persistent_worker": True,
    "omnivoice_worker_start_timeout_sec": 420,
    "omnivoice_worker_job_timeout_sec": 420,
    "omnivoice_pronunciation_file": "prompts/pronunciation_ru.tsv",
    "omnivoice_normalize_ru": True,
    "omnivoice_nonverbal_tags_enabled": True,
    "omnivoice_nonverbal_tags_chance": 0.25,
    "omnivoice_ref_audio": "references/maxim_ref.wav",
    "omnivoice_ref_text": "",
    "omnivoice_instruct": "male, middle-aged, russian accent, low pitch",

    "silero_repo_dir": "silero-models",  # папка с исходниками snakers4/silero-models; пусто = torch.hub попробует сам
    "silero_language": "ru",
    "silero_model": "v4_ru",
    "silero_speaker": "aidar",
    "silero_sample_rate": 48000,
    "silero_device": "cpu",
    "silero_put_accent": True,
    "silero_put_yo": True,

    "qwen3_tts_python": ".venv_qwen3_tts\\Scripts\\python.exe",
    "qwen3_tts_model_id": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "qwen3_tts_mode": "voice_design",  # voice_design | custom_voice
    "qwen3_tts_language": "Russian",
    "qwen3_tts_device_map": "cuda:0",
    "qwen3_tts_dtype": "auto",
    "qwen3_tts_attn_implementation": "sdpa",
    "qwen3_tts_gpu_memory_limit_gb": 0,
    "qwen3_tts_cpu_memory_limit_gb": 48,
    "qwen3_tts_auto_retry_stable_gpu": True,
    "qwen3_tts_runtime_profile_version": 3,
    "qwen3_tts_max_new_tokens": 1024,
    "qwen3_tts_do_sample": True,
    "qwen3_tts_persistent_worker": True,
    "qwen3_tts_hide_known_warnings": True,
    "qwen3_tts_worker_start_timeout_sec": 420,
    "qwen3_tts_worker_job_timeout_sec": 420,
    "qwen3_tts_instruct_variants_enabled": True,
    "qwen3_tts_speaker": "Ryan",
    "qwen3_tts_instruct": "Энергичный, тёплый русский радиоведущий. Голос живой, уверенный, радиоформатный, с улыбкой и умеренной экспрессией, без роботичности и без театрального переигрывания.",

    "lmstudio_tts_base_url": "http://127.0.0.1:1234/v1",
    "lmstudio_tts_model": "local-model",
    "lmstudio_tts_voice": "default",
    "lmstudio_tts_response_format": "mp3",
    "lmstudio_tts_speed": 1.0,
    "lmstudio_tts_timeout_sec": 180,

    "f5_tts_python": ".venv_f5_tts\\Scripts\\python.exe",
    "f5_tts_model": "F5TTS_Base",
    "f5_tts_ckpt_file": "hf://hotstone228/F5-TTS-Russian/model_last.safetensors",
    "f5_tts_vocab_file": "hf://hotstone228/F5-TTS-Russian/vocab.txt",
    "f5_tts_model_cfg": "",
    "f5_tts_vocoder": "vocos",
    "f5_tts_ref_audio": "references/maxim_ref.wav",
    "f5_tts_ref_text": "",
    "f5_tts_output_format": "wav",
    "f5_tts_timeout_sec": 900,
    "f5_tts_use_cuda": True,
    "f5_tts_nfe_step": 32,
    "f5_tts_sway_sampling_coef": -1.0,
    "f5_tts_speed": 1.0,
    "f5_tts_remove_silence": True,
    "f5_tts_seed": -1,

    "tts_speak_host_names": False,
    "tts_dialogue_split_hosts": True,
    "tts_dialogue_pause_ms": 180,

    "dj_every_n_tracks_min": 1,
    "dj_every_n_tracks_max": 2,
    "dj_max_seconds_hint": 90,
    "dj_talk_profile": "mixed",  # short | medium | long | mixed
    "dj_short_talk_chance": 0.42,
    "dj_medium_talk_chance": 0.38,
    "dj_long_talk_chance": 0.20,
    "dj_topic_mode": "auto",  # auto | music | news | weather | road_story
    "intro_before_first_track": True,
    "async_prepare_dj": True,
    "prepared_dj_status_in_panel": True,
    "pre_generate_on_start": 0,
    "startup_intro_wait_sec": 6,
    "startup_intro_blocking": True,
    "never_block_for_dj": True,
    "startup_late_intro_policy": "discard",  # first_break | discard
    "startup_intro_track_specific": True,
    "startup_intro_no_previous_music_rule": True,
    "tts_fallback_enabled": True,
    "tts_fallback_chain": ["piper", "sapi"],
    "tts_debug_log": True,
    "tts_subprocess_timeout_sec": 900,
    "max_cached_spoken_files": 180,

    "continuous_radio_engine": True,
    "radio_autostart": False,
    "clean_generated_on_start": True,
    "clean_generated_on_restart": True,
    "log_client_events": False,
    "subscriber_queue_chunks": 256,
    "empty_radio_silence_seconds": 10,

    "fade_enabled": True,
    "music_fade_in_sec": 0.65,
    "music_fade_out_sec": 0.55,
    "speech_fade_in_sec": 0.03,
    "speech_fade_out_sec": 0.18,
    "transition_silence_sec": 0.0,
    "speech_takeover_enabled": True,
    "speech_takeover_sec": 4.0,
    "speech_takeover_min_track_sec": 45.0,
    "speech_takeover_only_if_prepared": True,

    "speech_bed_enabled": True,
    "speech_bed_dir": "beds",
    "speech_bed_volume": 0.07,  # -23 dB примерно; реальная радио-подложка не должна спорить с речью
    "speech_voice_volume": 1.45,
    "music_volume": 0.78,
    "speech_bed_fade_sec": 0.65,
    "speech_radio_processing_enabled": True,
    "speech_compressor_enabled": True,
    "speech_presence_eq_enabled": True,
    "speech_presence_gain_db": 3.0,
    "speech_loudnorm_enabled": True,
    "speech_loudnorm_i": -12.5,
    "speech_limiter_enabled": True,
    "speech_bed_mode": "generated",  # generated | file | off; generated = мягкая радиоподложка без резкого чужого трека
    "speech_generated_bed_filter": "anoisesrc=color=pink:sample_rate=44100:amplitude=0.018",
    "jingle_enabled": True,
    "jingle_dir": "jingles",
    "jingle_chance_after_speech": 0.55,
    "jingle_volume": 0.28,
    "auto_generate_sweep_jingle": True,

    # Короткие фирменные вставки между треками, если ведущего нет.
    "station_id_enabled": True,
    "station_id_dir": "station_ids",
    "station_id_every_tracks": 2,
    "station_id_chance": 0.45,
    "station_id_volume": 1.0,
    "station_id_fallback_tts_enabled": False,
    "station_id_fallback_texts": [
        "Дорожное радио. Музыка рядом!",
        "AI Радио — музыка, настроение и хороший день.",
        "Дорожная волна. Оставайтесь с нами!"
    ],
    # Рубрики и игры между песнями: гороскопы, загадки, игра “ответь неправильно”.
    "entertainment_enabled": False,
    "entertainment_in_live": True,
    "entertainment_in_planned": True,
    "entertainment_integration_mode": "auto_mix",  # auto_mix | separate | combine
    "entertainment_chance": 0.55,
    "entertainment_min_blocks_between": 1,

    "horoscope_enabled": True,
    "horoscope_generate_before_radio": True,
    "horoscope_chunk_min": 2,
    "horoscope_chunk_max": 3,
    "horoscope_blocks_before_riddle_min": 2,
    "horoscope_blocks_before_riddle_max": 3,

    "riddles_enabled": True,
    "riddle_min_blocks_between": 3,
    "riddle_options_count": 4,

    "wrong_answer_game_enabled": True,
    "wrong_answer_game_chance": 0.18,
    "wrong_answer_game_min_blocks_between": 4,

    "entertainment_generate_with_lm": True,
    "entertainment_pack_timeout_sec": 150,
    "entertainment_pack_max_items": 12,
    "entertainment_status_in_panel": True,
    "horoscope_source_mode": "web_then_lm",  # web_then_lm | lm_by_date | web_only
    "riddle_source_mode": "web_then_lm",  # web_then_lm | lm_by_date | web_only
    "rubric_web_timeout_sec": 18,
    "rubric_web_user_agent": "AITruckRadio/0.7 local radio",
    "guest_enabled": False,
    "guest_in_live": True,
    "guest_in_planned": True,
    "guest_generate_before_radio": True,
    "guest_name": "Гость",
    "guest_role": "слушатель с историей",
    "guest_voice_mode": "design",  # design | reference | auto
    "guest_voice_instruct": "male, young adult, russian accent, moderate pitch",
    "guest_ref_audio": "references/guest_ref.wav",
    "guest_ref_text": "references/guest_ref.txt",
    "guest_chance": 0.14,
    "guest_min_blocks_between": 6,
    "guest_story_count": 6,
    "guest_voice_warning_in_panel": True,
    "live_blocking_dj_when_due": True,
    "live_prepare_at_track_start_when_due": True,
    "live_prepare_trigger_fraction": 0.50,
    "live_prepare_trace_logs": True,
    "live_force_early_prepare_when_due": True,
    "startup_intro_reserve_first_track": True,
    "host_should_use_stress_marks": True,
    "host_duo_intro_in_mostly_solo": True,
    "strict_duo_intro_require_both": True,
    "strict_duo_intro_retry_attempts": 3,
    "avoid_road_cliche_prompt": True,
    "season_reality_guard_enabled": True,
    "hotkey_enabled": True,
    "hotkey_ctrl_alt_next": True,

    "station_style": "универсальное радио",
    "available_styles": ["универсальное радио", "уютное радио", "киберпанк", "дальнобой FM", "хоррор-эфир"],
    "night_mode_enabled": True,
    "night_start_hour": 22,
    "night_end_hour": 6,
    "time_context_enabled": True,
    "time_context_chance": 1.00,
    "weather_context_chance": 0.25,
    "host_creative_fact_mode": True,
    "host_strict_clock_guard": True,
    "startup_intro_time_lead_sec": 60,
    "live_expected_speech_time_enabled": True,
    "omnivoice_prewarm_on_radio_start": True,
    "host_use_track_profile_chance": 0.80,
    "host_general_fact_chance": 0.35,
    "host_clock_retry_attempts": 3,
    "startup_context_retry_attempts": 4,
    "greeting_only_first_insert": True,
    "recent_context_items": 5,
    "track_profiles_enabled": True,
    "track_profiles_file": "cache/track_profiles.json",
    "track_profiles_include_in_prompt": True,
    "track_profiles_auto_build": False,
    "track_profiles_force_rebuild_existing": False,
    "track_profiles_web_lookup_enabled": True,
    "track_profiles_web_lookup_provider": "musicbrainz+wikipedia",
    "track_profiles_progress_file": "cache/track_profiles_progress.json",
    "track_profiles_fact_mode": "web_then_lm",  # web_then_lm | safe_lm_only
    "track_profiles_wikipedia_enabled": True,
    "track_profiles_wikipedia_languages": "ru,en,uk,de",
    "track_profiles_wikidata_enabled": True,
    "track_profiles_deezer_enabled": True,
    "track_profiles_itunes_enabled": True,
    "track_profiles_enrich_missing_web_only": False,
    "track_profiles_enrich_only_if_no_sources": True,
    "track_profiles_build_timeout_sec": 3600,
    "track_profiles_web_delay_sec": 1.2,
    "track_profiles_wikipedia_cooldown_sec": 90,
    "track_profiles_musicbrainz_cooldown_sec": 60,

    # Плановый режим: заранее собрать живой эфир на 15/60/120 минут и только потом играть.
    "show_plan_enabled": False,
    "show_plan_duration_minutes": 15,
    "show_plan_block_until_ready": True,
    "show_plan_include_intro": True,
    "show_plan_rebuild_on_start": False,
    "show_plan_output_file": "cache/show_plans/last_show_plan.json",
    "show_plan_min_tracks_between_speech": 1,
    "show_plan_max_tracks_between_speech": 3,
    "show_plan_long_block_chance": 0.24,
    "show_plan_status_in_panel": True,
    "show_plan_continuous_extend": True,
    "show_plan_prepare_next_threshold_items": 3,
    "show_plan_prepare_next_threshold_minutes": 4,
    "show_plan_prepare_next_fraction": 0.50,
    "show_plan_live_after_exhausted": True,
    "show_plan_intro_long_opening": True,
    "show_plan_unique_greetings": True,
    "show_plan_fill_music_while_generating": True,
    "show_plan_auto_enable_after_generation": True,
    "show_plan_preview_items": 80,

    # Реалистичные эфирные якоря.
    "exact_hour_time_announce_enabled": True,
    "exact_hour_window_minutes": 3,
    "listener_greetings_enabled": True,
    "listener_greetings_file": "data/greetings.txt",
    "listener_greetings_chance": 0.22,
    "listener_greetings_every_tracks_min": 4,
    "listener_greetings_every_tracks_max": 8,

    # Диагностика: не потерял ли парсер диалогов часть текста перед TTS.
    "tts_parse_validation_enabled": True,
    "tts_parse_validation_min_ratio": 0.86,
    "max_host_text_chars": 4000,

    "two_hosts_enabled": True,  # legacy switch; new setting below is host_mode
    "host_mode": "mostly_solo",  # always_solo | always_duo | mostly_solo | smart_multi
    "host_favorite_names": "Максим, Ирина",
    "host_favorite_chance": 0.75,
    "host_multi_chance": 0.35,
    "host_active_count_min": 1,
    "host_active_count_max": 2,
    "host_duo_chance": 0.42,
    "host_duo_intro_in_mostly_solo": True,
    "host_solo_name": "Максим",
    "hosts": [
        {
            "name": "Максим",
            "enabled": True,
            "aliases": ["Макс"],
            "host_voice_profile_version": 5,
            "persona": "живой активный дорожный FM-ведущий: быстрые тёплые заходы, улыбка в голосе, энергия прямого эфира, короткие острые акценты, не сонный диктор и не аудиокнига",
            "piper_voice": "ru_RU-ruslan-medium",
            "piper_model": "voices/ru_RU-ruslan-medium.onnx",
            "silero_speaker": "aidar",
            "qwen3_tts_mode": "voice_design",
            "qwen3_tts_speaker": "Ryan",
            "qwen3_tts_instruct": "Русский мужской FM-радиоведущий в прямом эфире. Уверенный баритон, энергичная дорожная подача, улыбка в голосе, яркие короткие акценты как на радио, темп бодрый, не аудиокнига, не спокойный диктор, не монотонно.",
            "f5_tts_ref_audio": "references/maxim_ref.wav",
            "f5_tts_ref_text": "",
            "omnivoice_ref_audio": "references/maxim_ref.wav",
            "omnivoice_ref_text": "",
            "omnivoice_instruct": "male, middle-aged, russian accent, low pitch",
            "qwen3_tts_instruct_variants": [
                "Русский мужской FM-радиоведущий в прямом эфире. Уверенный баритон, энергичная дорожная подача, улыбка в голосе, яркие короткие акценты как на радио, темп бодрый, не аудиокнига, не спокойный диктор, не монотонно.",
                "Мужской голос ночного дорожного FM: харизма ведущего, живые интонации, уверенная артикуляция, чуть быстрее обычной речи, рекламно-радиойная энергия без крика.",
                "Энергичный русский радиоведущий для трассы: бодрая подача, натуральные паузы, лёгкая ирония, эмоциональные акценты на названиях песен и дороге, ощущение живого эфира."
            ],
        },
        {
            "name": "Ирина",
            "enabled": True,
            "aliases": ["Лина", "Ира"],
            "host_voice_profile_version": 5,
            "persona": "живая активная FM-соведущая: светлая энергичная подача, улыбка в голосе, быстрые реакции, дружелюбный драйв, не сонная дикторская читка",
            "piper_voice": "ru_RU-irina-medium",
            "piper_model": "voices/ru_RU-irina-medium.onnx",
            "silero_speaker": "xenia",
            "qwen3_tts_mode": "voice_design",
            "qwen3_tts_speaker": "Serena",
            "qwen3_tts_instruct": "Русская женская FM-радиоведущая в прямом эфире. Явно женский светлый голос, бодрая современная подача, улыбка в голосе, живые короткие акценты, дружелюбная энергия, не аудиокнига, не спокойный диктор, заметно отличается от мужского ведущего.",
            "f5_tts_ref_audio": "references/irina_ref.wav",
            "f5_tts_ref_text": "",
            "omnivoice_ref_audio": "references/irina_ref.wav",
            "omnivoice_ref_text": "",
            "omnivoice_instruct": "female, middle-aged, russian accent, moderate pitch",
            "qwen3_tts_instruct_variants": [
                "Русская женская FM-радиоведущая в прямом эфире. Явно женский светлый голос, бодрая современная подача, улыбка в голосе, живые короткие акценты, дружелюбная энергия, не аудиокнига, не спокойный диктор, заметно отличается от мужского ведущего.",
                "Женская русская соведущая дорожного радио: светлый тембр, FM-энергия, лёгкий юмор, живые короткие акценты, чуть бодрее разговорного темпа, не робот и не аудиокнига.",
                "Женский голос ночного радио: явно женский, улыбка в голосе, уверенная радиоподача, аккуратная эмоциональность, ощущение настоящей станции, естественная энергичная речь."
            ],
        },
    ],

    "news_enabled": True,
    "news_file": "data/news.txt",
    "news_lines_per_insert": 1,
    "news_chance": 0.35,

    "weather_enabled": False,
    "weather_city": "Moscow",
    "weather_units": "metric",  # metric | us
    "weather_provider": "open-meteo",  # open-meteo | wttr | auto
    "weather_cache_minutes": 45,
    "weather_timeout_sec": 4,
    "weather_error_cooldown_sec": 600,
    "weather_compact_api": True,

    "radio_persona": (
        "Ты пишешь текст для локального музыкального радио. Оно может звучать в игре, в дороге, в браузере или на фоне обычного дня, поэтому не привязывай эфир только к одной игре или симулятору. "
        "Говори по-русски, живо, тепло, в стиле настоящего радио, без мата, без канцелярита и без ощущения ChatGPT. "
        "Не цитируй тексты песен. Можно делать живые факты, ассоциации и творческие наблюдения, но реальные справочные факты о песнях и артистах лучше брать из профилей треков/новостей/метаданных. "
        "Это текст для TTS: в неоднозначных русских словах можно ставить ударение знаком акут над гласной: го́лоса, голоса́. "
        "Не злоупотребляй ударениями: ставь их только там, где слово часто читается неправильно. "
        "Формат: радиоведущий/ведущие между треками. Иногда это короткая подводка, иногда полноценный небольшой эфирный разговор. Следуй длине, которую задаёт пользовательский промпт. "
        "Делай цельный эфирный текст без внутренних ремарок, служебных инструкций, markdown и объяснений того, как ты выполняешь задачу. "
        "Это обычное музыкальное радио для любой аудитории: дома, в браузере, в игре, на фоне. Это НЕ ролевая трансляция из грузовика и НЕ эфир только для Euro Truck Simulator. Нельзя обращаться к аудитории как к дальнобоям/водителям, описывать кабину, салон грузовика, рейс, фары, трассу и дорожные знаки как сцену эфира. "
        "Основа эфира — музыка, слушатели, время, город, температура, погода и живое общение ведущих. Дорожные метафоры максимум редко и нейтрально, без симулятора и без кабины. "
        "Не придумывай странные слоганы вроде \"дальше-дышай\" и не цепляйся за старую песню, если в контексте уже другой трек."
    ),

    "fallback_host_phrases": [
        "Максим: Держим эфир живым и тёплым — следующий тре́к уже рядом.\nИрина: Оставайтесь с нами, впереди ещё хорошая му́зыка.",
        "Максим: Небольшая эфирная связка — и снова возвращаемся к му́зыке.\nИрина: Следующий тре́к добавит настроения этому часу.",
        "Максим: Передаём привет всем, кто сейчас слушает нас фоном.\nИрина: Небольшая музыкальная передышка — и дальше по эфи́ру.",
        "Максим: Это пауза между песнями, чтобы эфир не превращался просто в папку с му́зыкой.\nИрина: Дальше будет ещё интереснее.",
        "Максим: Где бы ты ни слушал — в игре, браузере или просто дома — мы рядом.\nИрина: Следующий тре́к уже на подходе.",
    ],
}


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def deep_merge(defaults: Dict[str, Any], loaded: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(defaults)
    for k, v in loaded.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Подтягивает новые поля в старый config.json без перетирания пользовательских настроек."""
    default_hosts = DEFAULT_CONFIG.get("hosts") or []
    legacy_name_map = {"Макс": "Максим", "Лина": "Ирина"}

    def host_keys(h: Dict[str, Any]) -> List[str]:
        keys = []
        name = str(h.get("name", "")).strip()
        if name:
            keys.append(name)
        aliases = h.get("aliases") or []
        if isinstance(aliases, list):
            keys.extend(str(a).strip() for a in aliases if str(a).strip())
        return keys

    by_name: Dict[str, Dict[str, Any]] = {}
    for h in default_hosts:
        if not isinstance(h, dict):
            continue
        for key in host_keys(h):
            by_name[key.lower()] = h

    hosts = cfg.get("hosts")
    if not isinstance(hosts, list) or not hosts:
        cfg["hosts"] = [dict(h) for h in default_hosts]
    else:
        normalized = []
        for i, host in enumerate(hosts):
            if not isinstance(host, dict):
                continue
            raw_name = str(host.get("name") or "").strip()
            canonical_name = legacy_name_map.get(raw_name, raw_name)
            base_default = by_name.get(canonical_name.lower())
            if base_default is None and i < len(default_hosts) and isinstance(default_hosts[i], dict):
                base_default = default_hosts[i]
            base = dict(base_default or {})
            base.update(host)
            # Voice profiles changed in v0.3.0. If old configs had the previous calm prompts,
            # refresh only the voice-related Qwen3-TTS fields so users get separate livelier voices.
            try:
                old_voice_ver = int(host.get("host_voice_profile_version", 0) or 0)
                new_voice_ver = int((base_default or {}).get("host_voice_profile_version", 0) or 0)
            except Exception:
                old_voice_ver, new_voice_ver = 0, 0
            if base_default and new_voice_ver and old_voice_ver < new_voice_ver:
                for vk in ["host_voice_profile_version", "qwen3_tts_mode", "qwen3_tts_speaker", "qwen3_tts_instruct", "qwen3_tts_instruct_variants", "persona"]:
                    if vk in base_default:
                        base[vk] = base_default[vk]
            if raw_name in legacy_name_map:
                base["name"] = legacy_name_map[raw_name]
            elif canonical_name:
                base["name"] = canonical_name
            elif base.get("name"):
                base["name"] = str(base["name"])
            else:
                base["name"] = f"Ведущий {i + 1}"
            # Если пользовательский старый конфиг не имел alias, добавляем alias из дефолта.
            if base_default and not isinstance(base.get("aliases"), list):
                base["aliases"] = list(base_default.get("aliases") or [])
            normalized.append(base)
        if len(normalized) < 2 and len(default_hosts) >= 2:
            for h in default_hosts[len(normalized):2]:
                normalized.append(dict(h))
        cfg["hosts"] = normalized

    # Runtime migration v0.4.5: OmniVoice became the main heavy TTS backend.
    try:
        omni_core_ver = int(cfg.get("omnivoice_core_profile_version", 0) or 0)
    except Exception:
        omni_core_ver = 0
    if omni_core_ver < 1:
        cfg["omnivoice_core_profile_version"] = 1
        cfg["tts_backend"] = "omnivoice"
        cfg["tts_fallback_chain"] = ["piper", "sapi"]
        cfg["show_experimental_tts_backends"] = False
        cfg["omnivoice_persistent_worker"] = True
        cfg["omnivoice_mode"] = "clone"
        cfg["omnivoice_device"] = "cuda:0"

    # Runtime migration v0.4.9: planned radio + louder processed voice + greetings/time marks.
    try:
        director_ver = int(cfg.get("radio_director_profile_version", 0) or 0)
    except Exception:
        director_ver = 0
    if director_ver < 3:
        cfg["radio_director_profile_version"] = 3
        cfg.setdefault("transition_silence_sec", 0.0)
        cfg.setdefault("music_fade_out_sec", 0.55)
        cfg.setdefault("speech_fade_in_sec", 0.03)
        cfg.setdefault("speech_takeover_enabled", True)
        cfg.setdefault("speech_takeover_sec", 4.0)
        cfg.setdefault("track_profiles_enabled", True)
        cfg.setdefault("track_profiles_file", "cache/track_profiles.json")
        cfg.setdefault("track_profiles_include_in_prompt", True)
        cfg.setdefault("track_profiles_force_rebuild_existing", False)
        cfg["lm_append_no_think"] = False
        cfg["lm_max_tokens"] = max(int(cfg.get("lm_max_tokens", 0) or 0), 760)
        cfg["lm_timeout_sec"] = max(int(cfg.get("lm_timeout_sec", 0) or 0), 90)
        cfg["dj_max_seconds_hint"] = max(int(cfg.get("dj_max_seconds_hint", 0) or 0), 90)
        cfg.setdefault("dj_talk_profile", "mixed")
        cfg.setdefault("dj_short_talk_chance", 0.42)
        cfg.setdefault("dj_medium_talk_chance", 0.38)
        cfg.setdefault("dj_long_talk_chance", 0.20)
        cfg.setdefault("dj_topic_mode", "auto")
        cfg.setdefault("speech_radio_processing_enabled", True)
        cfg.setdefault("speech_compressor_enabled", True)
        cfg.setdefault("speech_presence_eq_enabled", True)
        cfg.setdefault("speech_presence_gain_db", 3.0)
        cfg.setdefault("speech_loudnorm_enabled", True)
        cfg.setdefault("speech_limiter_enabled", True)
        cfg.setdefault("jingle_enabled", True)
        cfg.setdefault("jingle_dir", "jingles")
        cfg.setdefault("jingle_chance_after_speech", 0.55)
        cfg.setdefault("jingle_volume", 0.28)
        cfg.setdefault("auto_generate_sweep_jingle", True)
        cfg.setdefault("station_id_enabled", True)
        cfg.setdefault("station_id_dir", "station_ids")
        cfg.setdefault("station_id_every_tracks", 2)
        cfg.setdefault("station_id_chance", 0.45)
        cfg.setdefault("station_id_volume", 1.0)
        cfg.setdefault("station_id_fallback_tts_enabled", False)
        cfg.setdefault("station_id_fallback_texts", DEFAULT_CONFIG.get("station_id_fallback_texts", []))
    for _k in [
        "entertainment_enabled", "entertainment_in_live", "entertainment_in_planned", "horoscope_enabled",
        "riddles_enabled", "wrong_answer_game_enabled", "entertainment_generate_with_lm",
        "horoscope_generate_before_radio", "entertainment_status_in_panel", "omnivoice_nonverbal_tags_enabled",
    ]:
        cfg.setdefault(_k, DEFAULT_CONFIG.get(_k))
    for _k in [
        "entertainment_integration_mode",
    ]:
        cfg.setdefault(_k, DEFAULT_CONFIG.get(_k))
    for _k in [
        "entertainment_chance", "wrong_answer_game_chance", "omnivoice_nonverbal_tags_chance",
    ]:
        cfg.setdefault(_k, DEFAULT_CONFIG.get(_k))
    for _k in [
        "entertainment_min_blocks_between", "horoscope_chunk_min", "horoscope_chunk_max",
        "horoscope_blocks_before_riddle_min", "horoscope_blocks_before_riddle_max",
        "riddle_min_blocks_between", "riddle_options_count", "wrong_answer_game_min_blocks_between",
        "entertainment_pack_timeout_sec", "entertainment_pack_max_items", "max_host_text_chars",
    ]:
        cfg.setdefault(_k, DEFAULT_CONFIG.get(_k))
        cfg.setdefault("live_blocking_dj_when_due", True)
        cfg.setdefault("startup_intro_reserve_first_track", True)
        cfg.setdefault("startup_intro_no_previous_music_rule", True)
        cfg.setdefault("host_should_use_stress_marks", True)
        cfg.setdefault("host_duo_intro_in_mostly_solo", True)
        cfg.setdefault("avoid_road_cliche_prompt", True)
        cfg.setdefault("season_reality_guard_enabled", True)
    cfg.setdefault("host_duo_intro_in_mostly_solo", True)
    cfg.setdefault("strict_duo_intro_require_both", True)
    cfg.setdefault("strict_duo_intro_retry_attempts", 3)
    try:
        if float(cfg.get("speech_takeover_sec", 4.0) or 4.0) <= 1.2:
            cfg["speech_takeover_sec"] = 4.0
    except Exception:
        cfg["speech_takeover_sec"] = 4.0
    cfg.setdefault("track_profiles_deezer_enabled", True)
    cfg.setdefault("track_profiles_itunes_enabled", True)
    cfg.setdefault("track_profiles_enrich_only_if_no_sources", True)
    cfg.setdefault("live_prepare_at_track_start_when_due", True)
    cfg.setdefault("live_prepare_trigger_fraction", 0.50)
    cfg.setdefault("live_prepare_trace_logs", True)
    cfg.setdefault("live_force_early_prepare_when_due", True)
    cfg.setdefault("avoid_road_cliche_prompt", True)
    cfg.setdefault("season_reality_guard_enabled", True)
    cfg.setdefault("host_creative_fact_mode", True)
    cfg.setdefault("host_strict_clock_guard", True)
    cfg.setdefault("startup_intro_time_lead_sec", 60)
    cfg.setdefault("live_expected_speech_time_enabled", True)
    cfg.setdefault("omnivoice_prewarm_on_radio_start", True)
    cfg.setdefault("omnivoice_nonverbal_tags_enabled", True)
    cfg.setdefault("omnivoice_nonverbal_tags_chance", 0.25)
    cfg.setdefault("guest_voice_mode", "design")
    cfg.setdefault("guest_voice_instruct", "male, young adult, russian accent, moderate pitch")
    cfg.setdefault("host_clock_retry_attempts", 3)
    cfg.setdefault("startup_context_retry_attempts", 4)
    cfg.setdefault("show_plan_enabled", False)
    cfg.setdefault("show_plan_duration_minutes", 15)
    cfg.setdefault("show_plan_include_intro", True)
    cfg.setdefault("show_plan_rebuild_on_start", True)
    cfg.setdefault("speech_bed_mode", "generated")
    cfg["speech_voice_volume"] = max(float(cfg.get("speech_voice_volume", 1.0) or 1.0), 1.40)
    cfg.setdefault("music_volume", 0.78)
    cfg["speech_bed_volume"] = min(float(cfg.get("speech_bed_volume", 0.09) or 0.09), 0.08)
    cfg["speech_loudnorm_i"] = max(float(cfg.get("speech_loudnorm_i", -12.5) or -12.5), -12.5)
    cfg.setdefault("exact_hour_time_announce_enabled", True)
    cfg.setdefault("listener_greetings_enabled", True)
    if str(cfg.get("news_file", "news.txt")).strip().lower() == "news.txt":
        cfg["news_file"] = "data/news.txt"
    if str(cfg.get("listener_greetings_file", "greetings.txt")).strip().lower() == "greetings.txt":
        cfg["listener_greetings_file"] = "data/greetings.txt"
    cfg.setdefault("listener_greetings_file", "data/greetings.txt")
    cfg.setdefault("tts_parse_validation_enabled", True)
    cfg.setdefault("max_host_text_chars", 4000)

    # Runtime migration v0.5.1: panel-first workflow + continuous planned chunks.
    try:
        panel_ver = int(cfg.get("radio_panel_profile_version", 0) or 0)
    except Exception:
        panel_ver = 0
    if panel_ver < 2:
        cfg["radio_panel_profile_version"] = 2
        cfg.setdefault("radio_autostart", False)
        cfg.setdefault("show_plan_continuous_extend", True)
        cfg.setdefault("show_plan_prepare_next_threshold_items", 3)
        cfg.setdefault("show_plan_prepare_next_threshold_minutes", 4)
        cfg.setdefault("show_plan_live_after_exhausted", True)
        cfg.setdefault("show_plan_intro_long_opening", True)
        cfg.setdefault("show_plan_unique_greetings", True)
        cfg.setdefault("show_plan_prepare_next_fraction", 0.50)
        cfg.setdefault("show_plan_fill_music_while_generating", True)
        cfg.setdefault("show_plan_auto_enable_after_generation", True)
        cfg.setdefault("show_plan_preview_items", 80)
        cfg.setdefault("show_plan_rebuild_on_start", False)
        cfg.setdefault("show_plan_block_until_ready", True)
        cfg.setdefault("track_profiles_web_lookup_enabled", True)
        cfg.setdefault("track_profiles_wikipedia_enabled", True)
        cfg.setdefault("track_profiles_wikipedia_languages", "ru,en,uk,de")
        cfg.setdefault("track_profiles_wikidata_enabled", True)
        cfg.setdefault("track_profiles_deezer_enabled", True)
        cfg.setdefault("track_profiles_itunes_enabled", True)
        cfg.setdefault("track_profiles_enrich_missing_web_only", False)
        cfg.setdefault("track_profiles_enrich_only_if_no_sources", True)
        cfg.setdefault("track_profiles_fact_mode", "web_then_lm")
        cfg.setdefault("track_profiles_force_rebuild_existing", False)
        cfg.setdefault("track_profiles_progress_file", "cache/track_profiles_progress.json")
        cfg.setdefault("station_id_enabled", True)
        cfg.setdefault("station_id_dir", "station_ids")
        cfg.setdefault("station_id_every_tracks", 2)
        cfg.setdefault("station_id_chance", 0.45)
        cfg.setdefault("live_blocking_dj_when_due", True)
        cfg.setdefault("startup_intro_reserve_first_track", True)
        cfg.setdefault("startup_intro_no_previous_music_rule", True)
        cfg.setdefault("host_should_use_stress_marks", True)
        cfg.setdefault("host_duo_intro_in_mostly_solo", True)
        cfg.setdefault("avoid_road_cliche_prompt", True)
        cfg.setdefault("season_reality_guard_enabled", True)
    cfg.setdefault("host_duo_intro_in_mostly_solo", True)
    cfg.setdefault("strict_duo_intro_require_both", True)
    cfg.setdefault("strict_duo_intro_retry_attempts", 3)
    cfg.setdefault("track_profiles_deezer_enabled", True)
    cfg.setdefault("track_profiles_itunes_enabled", True)
    cfg.setdefault("track_profiles_enrich_only_if_no_sources", True)
    cfg.setdefault("live_prepare_at_track_start_when_due", True)
    cfg.setdefault("live_prepare_trigger_fraction", 0.50)
    cfg.setdefault("live_prepare_trace_logs", True)
    cfg.setdefault("live_force_early_prepare_when_due", True)
    cfg.setdefault("avoid_road_cliche_prompt", True)
    cfg.setdefault("season_reality_guard_enabled", True)


    # v0.5.6 safety: these defaults must appear even for existing configs that already passed older migrations.
    cfg.setdefault("station_id_enabled", True)
    cfg.setdefault("station_id_dir", "station_ids")
    cfg.setdefault("station_id_every_tracks", 2)
    cfg.setdefault("station_id_chance", 0.45)
    cfg.setdefault("station_id_volume", 1.0)
    cfg.setdefault("station_id_fallback_tts_enabled", False)
    cfg.setdefault("station_id_fallback_texts", DEFAULT_CONFIG.get("station_id_fallback_texts", []))
    cfg.setdefault("live_blocking_dj_when_due", True)
    cfg.setdefault("startup_intro_reserve_first_track", True)
    cfg.setdefault("host_should_use_stress_marks", True)
    cfg.setdefault("host_duo_intro_in_mostly_solo", True)
    cfg.setdefault("avoid_road_cliche_prompt", True)
    cfg.setdefault("season_reality_guard_enabled", True)
    cfg.setdefault("host_duo_intro_in_mostly_solo", True)
    cfg.setdefault("strict_duo_intro_require_both", True)
    cfg.setdefault("strict_duo_intro_retry_attempts", 3)
    cfg.setdefault("track_profiles_deezer_enabled", True)
    cfg.setdefault("track_profiles_itunes_enabled", True)
    cfg.setdefault("track_profiles_enrich_only_if_no_sources", True)
    cfg.setdefault("live_prepare_at_track_start_when_due", True)
    cfg.setdefault("live_prepare_trigger_fraction", 0.50)
    cfg.setdefault("live_prepare_trace_logs", True)
    cfg.setdefault("live_force_early_prepare_when_due", True)
    cfg.setdefault("avoid_road_cliche_prompt", True)
    cfg.setdefault("season_reality_guard_enabled", True)

    for dir_key, fallback in [("speech_bed_dir", "beds"), ("jingle_dir", "jingles"), ("station_id_dir", "station_ids")]:
        d = Path(str(cfg.get(dir_key, fallback)))
        if not d.is_absolute():
            d = BASE_DIR / d
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return cfg

def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_json(CONFIG_PATH, DEFAULT_CONFIG)
        log(f"Создан config.json: {CONFIG_PATH}")
        return dict(DEFAULT_CONFIG)
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = normalize_config(deep_merge(DEFAULT_CONFIG, loaded))
        save_json(CONFIG_PATH, cfg)
        return cfg
    except Exception as e:
        backup = CONFIG_PATH.with_suffix(".broken.json")
        shutil.copy2(CONFIG_PATH, backup)
        log(f"config.json повреждён, копия: {backup}. Использую настройки по умолчанию. Ошибка: {e}")
        cfg = normalize_config(dict(DEFAULT_CONFIG))
        save_json(CONFIG_PATH, cfg)
        return cfg


def rel_path(cfg: Dict[str, Any], key: str) -> Path:
    p = Path(str(cfg[key]))
    if not p.is_absolute():
        p = BASE_DIR / p
    return p


def executable_exists(cmd: str) -> bool:
    if not cmd:
        return False
    p = Path(cmd)
    if p.is_absolute() or "\\" in cmd or "/" in cmd:
        return p.exists()
    return shutil.which(cmd) is not None


def resolve_executable(cmd: str) -> str:
    if not cmd:
        return cmd
    p = Path(cmd)
    if p.is_absolute() or "\\" in cmd or "/" in cmd:
        return str(p)
    return shutil.which(cmd) or cmd


def find_ffprobe(cfg: Dict[str, Any]) -> str:
    explicit = str(cfg.get("ffprobe_path") or "").strip()
    if explicit and executable_exists(explicit):
        return explicit
    ffmpeg = str(cfg.get("ffmpeg_path", "ffmpeg"))
    p = Path(ffmpeg)
    if p.is_absolute() or "\\" in ffmpeg or "/" in ffmpeg:
        probe = p.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if probe.exists():
            return str(probe)
    return shutil.which("ffprobe") or "ffprobe"


def run_subprocess(args: List[str], timeout: Optional[int] = None, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


