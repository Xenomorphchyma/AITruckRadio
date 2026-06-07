# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_truck_radio_app.config import (
    APP_VERSION,
    BASE_DIR,
    CONFIG_PATH,
    DEFAULT_CONFIG,
    MUSIC_EXTS,
    RUS_MONTHS,
    RUS_WEEKDAYS,
    executable_exists,
    find_ffprobe,
    log,
    normalize_config,
    rel_path,
    require_http_url,
    save_json,
)
from ai_truck_radio_app.context import (
    WeatherClient,
    current_time_text,
    current_time_text_at_offset,
    current_time_spoken_text_at_offset,
    daypart_name_for_hour,
    exact_hour_announcement_text,
    is_night_now,
    read_greeting_line,
    read_greeting_line_unique,
    read_news_line,
    style_prompt,
)
from ai_truck_radio_app.entertainment_agent import EntertainmentAgent
from ai_truck_radio_app.entertainment_history import filter_unused, mark_used
from ai_truck_radio_app.lmstudio import LMStudioClient
from ai_truck_radio_app.server import make_ets2_line
from ai_truck_radio_app.text_processing import (
    clean_host_text,
    context_violations_for_host_text,
    normalize_omnivoice_nonverbal_tags,
    normalize_generated_radio_text,
    postprocess_host_text_for_air,
    repair_time_context_text,
    sanitize_general_radio_text,
    soften_tts_exclamations,
)
from ai_truck_radio_app.tracks import (
    PlannedItem,
    PreparedDJ,
    Track,
    ffprobe_duration,
    load_track_profiles,
    scan_music,
    short_track_profile,
    track_key,
)
from ai_truck_radio_app.tts import TTS


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class RadioEngine:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.music_dir = rel_path(cfg, "music_dir")
        self.cache_dir = rel_path(cfg, "cache_dir")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tracks = scan_music(self.music_dir)
        self.track_queue: List[Track] = []
        self.previous_track: Optional[Track] = None
        self.reserved_next_track: Optional[Track] = None
        self.last_station_id_track_index = -9999
        self.played_since_dj = 0
        self.next_dj_after = self._random_dj_gap()
        self.lm = LMStudioClient(cfg)
        self.entertainment_agent = EntertainmentAgent(cfg, self.lm)
        self.tts = TTS(cfg)
        self.weather = WeatherClient(cfg)
        self.track_profiles = load_track_profiles(cfg) if cfg.get("track_profiles_enabled", True) else {}

        self.state_lock = threading.Lock()
        self.subs_lock = threading.Lock()
        self.subscribers: Dict[int, queue.Queue[Optional[bytes]]] = {}
        self.next_sub_id = 1

        self.now_playing = "Запуск эфира"
        self.current_kind = "startup"
        self.current_started_ts = time.time()
        self.last_host_text = ""
        self.last_error = ""
        self.used_lm_model = ""
        self.total_clients = 0
        self.active_clients = 0
        self.tracks_played = 0
        self.speech_blocks_played = 0
        self.skip_requested_by = ""
        self.recent_host_texts: List[str] = []
        self.prepared_dj: Optional[PreparedDJ] = None
        self.prepare_thread: Optional[threading.Thread] = None
        self.prepare_lock = threading.Lock()
        self.prepared_status = "нет заранее готовой вставки"
        self.intro_played_or_skipped = False
        self.last_hour_announcement_hour = -1
        self.last_greeting_track_index = -9999
        self.next_greeting_after = random.randint(
            max(1, int(cfg.get("listener_greetings_every_tracks_min", 4) or 4)),
            max(1, int(cfg.get("listener_greetings_every_tracks_max", 8) or 8)),
        )
        self.show_plan: List[PlannedItem] = []
        self.show_plan_index = 0
        self.show_plan_status = "плановый режим выключен"
        self.next_show_plan: List[PlannedItem] = []
        self.plan_prepare_thread: Optional[threading.Thread] = None
        self.plan_lock = threading.Lock()
        self.track_profile_thread: Optional[threading.Thread] = None
        self.track_profile_status = "профили треков не обновлялись"
        self.track_profile_progress: Dict[str, Any] = {"current": 0, "total": 0, "percent": 0, "detail": ""}
        self.show_plan_progress: Dict[str, Any] = {"current": 0, "total": 0, "percent": 0, "detail": ""}
        self.show_plan_last_generation_sec = 0.0

        self.entertainment_pack: Dict[str, Any] = {}
        self.entertainment_pack_date = ""
        self.entertainment_status = "рубрики не готовились"
        self.entertainment_block_count = 0
        self.last_entertainment_block = -9999
        self.last_guest_block = -9999
        self.horoscope_index = 0
        self.horoscope_blocks_since_riddle = 0
        self.horoscope_blocks_before_riddle_target = random.randint(
            max(1, int(cfg.get("horoscope_blocks_before_riddle_min", 2) or 2)),
            max(1, int(cfg.get("horoscope_blocks_before_riddle_max", 3) or 3)),
        )
        self.pending_riddle: Optional[Dict[str, Any]] = None
        self.last_riddle_block = -9999
        self.last_wrong_game_block = -9999

        self.stop_event = threading.Event()
        self.skip_event = threading.Event()
        self.startup_cancel_event = threading.Event()
        self.broadcast_thread: Optional[threading.Thread] = None
        self.startup_thread: Optional[threading.Thread] = None

    def is_running(self) -> bool:
        return bool(self.broadcast_thread and self.broadcast_thread.is_alive() and not self.stop_event.is_set())

    def is_starting(self) -> bool:
        return bool(self.startup_thread and self.startup_thread.is_alive())

    def start_async(self, clean_generated: Optional[bool] = None) -> bool:
        if self.is_running() or self.is_starting():
            return False
        self.startup_cancel_event.clear()
        with self.state_lock:
            self.now_playing = "Эфир запускается"
            self.current_kind = "startup"
            self.current_started_ts = time.time()

        def worker() -> None:
            try:
                self.start(clean_generated=clean_generated)
            except Exception as e:
                self.set_error(f"Не удалось запустить радио: {e}")
                with self.state_lock:
                    self.now_playing = "Ошибка запуска радио"
                    self.current_kind = "stopped"
                log(f"Фоновый запуск радио завершился ошибкой: {e}")

        self.startup_thread = threading.Thread(target=worker, name="RadioStartup", daemon=True)
        self.startup_thread.start()
        return True

    def cleanup_generated_radio_files(self) -> Dict[str, int]:
        """Delete generated speech/planned-show leftovers, but keep user assets and track profiles."""
        targets = [
            self.cache_dir / "spoken",
            self.cache_dir / "tmp",
            self.cache_dir / "show_plans",
        ]
        removed_files = 0
        removed_dirs = 0
        for root in targets:
            try:
                if not root.exists():
                    root.mkdir(parents=True, exist_ok=True)
                    continue
                for item in root.iterdir():
                    try:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                            removed_dirs += 1
                        else:
                            item.unlink(missing_ok=True)
                            removed_files += 1
                    except Exception as e:
                        log(f"Не удалось удалить {item}: {e}")
                root.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                log(f"Не удалось очистить {root}: {e}")
        return {"files": removed_files, "dirs": removed_dirs}

    def _reset_runtime_state_for_new_air(self) -> None:
        # Важно: если пользователь уже нажал "Сгенерировать план", старт радио
        # не должен выбрасывать этот план. Раньше именно это ломало плановый режим:
        # панель готовила речь/музыку, а кнопка "Включить радио" начинала всё с нуля.
        keep_ready_plan = bool(self.cfg.get("show_plan_enabled", False) and self.show_plan)
        kept_plan = self.show_plan if keep_ready_plan else []
        kept_index = self.show_plan_index if keep_ready_plan else 0
        kept_next = self.next_show_plan if keep_ready_plan else []
        kept_status = self.show_plan_status
        with self.state_lock:
            self.now_playing = "Эфир готовится"
            self.current_kind = "startup"
            self.current_started_ts = time.time()
            self.last_error = ""
            self.skip_requested_by = ""
        with self.prepare_lock:
            self.prepared_dj = None
            self.prepared_status = "нет заранее готовой вставки"
        self.track_queue = []
        self.previous_track = None
        self.reserved_next_track = None
        self.last_station_id_track_index = -9999
        self.played_since_dj = 0
        self.next_dj_after = self._random_dj_gap()
        self.intro_played_or_skipped = False
        if keep_ready_plan:
            self.show_plan = kept_plan
            self.show_plan_index = min(max(0, kept_index), len(kept_plan))
            self.next_show_plan = kept_next
            self.show_plan_status = kept_status or f"готовый план ждёт запуска: {len(kept_plan)} элементов"
        else:
            self.show_plan = []
            self.show_plan_index = 0
            self.next_show_plan = []
            self.show_plan_status = "плановый режим выключен" if not self.cfg.get("show_plan_enabled", False) else "план будет собран при запуске"

    def start(self, clean_generated: Optional[bool] = None) -> None:
        if self.broadcast_thread and self.broadcast_thread.is_alive():
            return
        if clean_generated is None:
            clean_generated = bool(self.cfg.get("clean_generated_on_start", True))
        # Старт/стоп радио закрывает TTS worker. Persistent OmniVoice живёт только внутри
        # одного запущенного эфира и не должен перезапускаться между речевыми блоками.
        try:
            self.tts.close()
        except Exception:
            pass
        self.tts = TTS(self.cfg)
        if clean_generated and self.cfg.get("show_plan_enabled", False) and self.show_plan:
            # Готовый план уже содержит mp3-речь в cache/spoken и json в cache/show_plans.
            # Нельзя чистить их при обычной кнопке "Включить радио".
            clean_generated = False
            log("Готовый план уже есть — не очищаю cache/spoken и cache/show_plans перед стартом")
        if clean_generated:
            stats = self.cleanup_generated_radio_files()
            log(f"Старые сгенерированные файлы очищены: {stats['files']} файлов, {stats['dirs']} папок")
        self.lm = LMStudioClient(self.cfg)
        self.entertainment_agent = EntertainmentAgent(self.cfg, self.lm)
        self.weather = WeatherClient(self.cfg)
        self.track_profiles = load_track_profiles(self.cfg) if self.cfg.get("track_profiles_enabled", True) else {}
        try:
            self.tts.prewarm_omnivoice_worker(self.cfg.get("hosts") or [])
        except Exception as e:
            log(f"OmniVoice prewarm пропущен: {e}")
        if self.startup_cancel_event.is_set():
            log("Запуск радио отменён во время подготовки OmniVoice")
            return
        if self.cfg.get("entertainment_enabled", False) and self.cfg.get("horoscope_generate_before_radio", True):
            try:
                self.prepare_entertainment_pack("radio_start")
                log("Рубрики перед эфиром готовы: " + self.entertainment_status)
            except Exception as e:
                log(f"Не удалось подготовить рубрики перед эфиром: {e}")
        if self.startup_cancel_event.is_set():
            log("Запуск радио отменён во время подготовки рубрик")
            return
        self.stop_event.clear()
        self.skip_event.clear()
        self._reset_runtime_state_for_new_air()
        self.broadcast_thread = threading.Thread(target=self._broadcast_loop, name="RadioBroadcast", daemon=True)
        self.broadcast_thread.start()

    def stop(self) -> None:
        self.startup_cancel_event.set()
        self.stop_event.set()
        self.skip_event.set()
        self._broadcast(None)
        try:
            self.tts.close()
        except Exception:
            pass
        with self.state_lock:
            self.now_playing = "Радио остановлено"
            self.current_kind = "stopped"
            self.current_started_ts = time.time()

    def restart(self, clean_generated: Optional[bool] = None) -> None:
        if clean_generated is None:
            clean_generated = bool(self.cfg.get("clean_generated_on_restart", True))
        self.stop()
        if self.broadcast_thread and self.broadcast_thread.is_alive():
            self.broadcast_thread.join(timeout=5.0)
        self.start(clean_generated=clean_generated)

    def request_skip(self, by: str = "panel") -> None:
        with self.state_lock:
            self.skip_requested_by = by
        self.skip_event.set()
        log(f"Запрошен следующий трек ({by})")

    def add_subscriber(self) -> Tuple[int, queue.Queue[Optional[bytes]]]:
        max_chunks = max(16, int(self.cfg.get("subscriber_queue_chunks", 256)))
        q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=max_chunks)
        with self.subs_lock:
            sid = self.next_sub_id
            self.next_sub_id += 1
            self.subscribers[sid] = q
        with self.state_lock:
            self.total_clients += 1
            self.active_clients += 1
        if self.cfg.get("log_client_events", False):
            log(f"Клиент #{sid} подключился к /stream.mp3")
        return sid, q

    def remove_subscriber(self, sid: int) -> None:
        with self.subs_lock:
            self.subscribers.pop(sid, None)
        with self.state_lock:
            self.active_clients = max(0, self.active_clients - 1)
        if self.cfg.get("log_client_events", False):
            log(f"Клиент #{sid} отключился от /stream.mp3")

    def _broadcast(self, chunk: Optional[bytes]) -> None:
        with self.subs_lock:
            targets = list(self.subscribers.items())
        for _sid, q in targets:
            try:
                q.put_nowait(chunk)
            except queue.Full:
                # Live-radio логика: если клиент не успевает, выкидываем старые чанки, а не тормозим эфир.
                try:
                    while q.qsize() > max(2, q.maxsize // 2):
                        q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(chunk)
                except Exception:
                    pass

    def _random_dj_gap(self) -> int:
        lo = max(1, int(self.cfg.get("dj_every_n_tracks_min", 1)))
        hi = max(lo, int(self.cfg.get("dj_every_n_tracks_max", 2)))
        return random.randint(lo, hi)

    def refresh_tracks(self) -> None:
        tracks = scan_music(self.music_dir)
        with self.state_lock:
            self.tracks = tracks
            self.track_queue = []
        log(f"Музыка пересканирована: {len(tracks)} файлов")

    def _refill_queue(self) -> None:
        if not self.track_queue:
            self.tracks = scan_music(self.music_dir)
            self.track_queue = list(self.tracks)
            if self.cfg.get("shuffle", True):
                random.shuffle(self.track_queue)

    def peek_next_track(self) -> Optional[Track]:
        self._refill_queue()
        return self.track_queue[0] if self.track_queue else None

    def pop_next_track(self) -> Optional[Track]:
        # Если ведущий уже объявил конкретный следующий трек, играем именно его.
        reserved = getattr(self, "reserved_next_track", None)
        if reserved is not None:
            self.reserved_next_track = None
            try:
                self.track_queue = [x for x in self.track_queue if getattr(x, "path", None) != getattr(reserved, "path", None)]
            except Exception:
                pass
            log(f"Играю зарезервированный объявленный трек: {reserved.display_name}")
            return reserved
        self._refill_queue()
        if not self.track_queue:
            return None
        return self.track_queue.pop(0)

    def set_now(self, text: str, kind: str) -> None:
        with self.state_lock:
            self.now_playing = text
            self.current_kind = kind
            self.current_started_ts = time.time()

    def set_error(self, text: str) -> None:
        with self.state_lock:
            self.last_error = text

    def should_insert_dj(self) -> bool:
        if self.played_since_dj < self.next_dj_after:
            return False
        if not self.previous_track:
            return False
        return True

    def should_insert_after_current_track(self) -> bool:
        """Нужно ли готовить ведущих уже во время текущей песни."""
        return (self.played_since_dj + 1) >= self.next_dj_after

    def _select_hosts_for_insert(self, intro_allowed: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
        """Choose hosts by block type and per-host participation weight."""
        all_hosts = [h for h in (self.cfg.get("hosts") or []) if isinstance(h, dict) and str(h.get("name", "")).strip()]
        hosts = [h for h in all_hosts if h.get("enabled", True) is not False]
        if not hosts:
            hosts = all_hosts[:]
        if not hosts:
            return [], False

        pool_key = "intro_enabled" if intro_allowed else "regular_enabled"
        pool = [h for h in hosts if h.get(pool_key, True) is not False] or hosts

        if intro_allowed:
            count = int(self.cfg.get("host_intro_count", 2) or 2)
        else:
            min_count = max(1, int(self.cfg.get("host_regular_count_min", 1) or 1))
            max_count = max(min_count, int(self.cfg.get("host_regular_count_max", 2) or 2))
            multi_chance = clamp(float(self.cfg.get("host_regular_multi_chance", 0.18) or 0.18), 0.0, 1.0)
            count = random.randint(min_count + 1, max_count) if max_count > min_count and random.random() < multi_chance else min_count
        count = max(1, min(len(pool), count))

        remaining = list(pool)
        chosen: List[Dict[str, Any]] = []
        while remaining and len(chosen) < count:
            weights = []
            for host in remaining:
                try:
                    weights.append(max(0.01, float(host.get("air_weight", 1.0) or 1.0)))
                except Exception:
                    weights.append(1.0)
            selected = random.choices(remaining, weights=weights, k=1)[0]
            chosen.append(selected)
            remaining.remove(selected)
        return chosen, len(chosen) >= 2

    def _choose_dj_plan(self, intro_allowed: bool, has_news: bool, has_weather: bool) -> Dict[str, str]:
        """Chooses the next host segment style.

        This is intentionally lightweight: generation still happens in LM Studio,
        but the radio engine decides whether this should be a short liner, a
        medium break, or a longer realistic talk block.
        """
        profile = str(self.cfg.get("dj_talk_profile", "mixed") or "mixed").strip().lower()
        if intro_allowed:
            length = "medium"
        elif profile in {"short", "medium", "long"}:
            length = profile
        else:
            p_long = clamp(float(self.cfg.get("dj_long_talk_chance", 0.20)), 0.0, 1.0)
            p_medium = clamp(float(self.cfg.get("dj_medium_talk_chance", 0.38)), 0.0, 1.0)
            r = random.random()
            if r < p_long:
                length = "long"
            elif r < p_long + p_medium:
                length = "medium"
            else:
                length = "short"

        topic_mode = str(self.cfg.get("dj_topic_mode", "auto") or "auto").strip().lower()
        candidates = []
        if topic_mode == "road_story":
            topic_mode = "listener_story"
        if topic_mode in {"news", "weather", "music", "listener_story"}:
            candidates = [topic_mode]
        else:
            candidates = ["music", "next_track", "previous_track", "listener_story"]
            if has_news:
                candidates += ["news", "news"]
            if has_weather:
                candidates += ["weather", "weather"]
            if is_night_now(self.cfg):
                candidates += ["night_mood"]
        topic = random.choice(candidates) if candidates else "music"

        if length == "short":
            instruction = "Короткая радиоподводка: 1-2 предложения всего, 10-20 секунд речи."
        elif length == "medium":
            instruction = "Средний эфирный блок: 3-5 предложений всего, примерно 25-45 секунд речи. Можно чуть обсудить тему, но без подкаста."
        else:
            instruction = "Длинный эфирный блок: 6-9 предложений всего, примерно 60-90 секунд речи. Это мини-разговор ведущего/ведущих, но всё равно радиоформат, не лекция."
        topic_labels = {
            "music": "музыка и настроение эфира",
            "next_track": "подводка к следующему треку",
            "previous_track": "короткое послевкусие предыдущего трека",
            "news": "новость станции",
            "weather": "погода: город, температура и настроение дня",
            "listener_story": "короткая живая зарисовка из эфира: город, слушатель, погода или настроение",
            "night_mood": "ночной эфир: спокойная музыка, городские огни, настроение позднего часа",
        }
        return {"length": length, "topic": topic, "topic_label": topic_labels.get(topic, topic), "instruction": instruction}

    def _fallback_entertainment_pack(self) -> Dict[str, Any]:
        today = time.strftime('%d.%m.%Y')
        signs = [
            ('Овен', 'День хорошо подходит для смелого шага и честного разговора. Музыка поможет поймать нужный темп.'),
            ('Телец', 'Ставка на спокойствие и вкус к деталям сегодня особенно выигрышна. Не спешите — хороший ритм сам найдётся.'),
            ('Близнецы', 'Сегодня легко заводятся новые темы и неожиданные идеи. Отличный момент для любопытных разговоров в эфире.'),
            ('Рак', 'День просит уюта и мягкого внимания к себе. Хорошая песня может стать маленькой паузой для перезагрузки.'),
            ('Лев', 'Вам идёт уверенная подача и немного блеска. Сегодня можно смело показать характер, но без лишней суеты.'),
            ('Дева', 'Порядок в мелочах даст ощущение контроля. Если день шумный, музыка поможет собрать мысли в одну линию.'),
            ('Весы', 'Хорошее время для равновесия, красивых жестов и лёгких решений. Не спорьте с настроением — настройте его.'),
            ('Скорпион', 'День с глубиной: можно услышать больше, чем сказано вслух. Подойдёт музыка с атмосферой и внутренним напряжением.'),
            ('Стрелец', 'Хочется движения, новых впечатлений и широкой перспективы. Даже обычный день может открыть неожиданный поворот.'),
            ('Козерог', 'Сегодня выигрывает терпение и спокойная собранность. Маленький шаг вперёд всё равно остаётся шагом вперёд.'),
            ('Водолей', 'Идеи приходят не по расписанию, зато метко. Дайте себе право на необычную мысль и хороший музыкальный эксперимент.'),
            ('Рыбы', 'День мягкий, образный и немного мечтательный. Хорошая мелодия может подсказать ответ лучше любого совета.'),
        ]
        riddles = [
            {'question': 'Что можно услышать, но нельзя увидеть?', 'options': ['эхо', 'ветер', 'радио', 'мысль'], 'answer': 'эхо', 'explanation': 'Эхо слышно, но увидеть его нельзя — зато в эфире оно звучит почти как маленький спецэффект.'},
            {'question': 'Что становится больше, если его перевернуть?', 'options': ['число шесть', 'чашка', 'карта', 'лампа'], 'answer': 'число шесть', 'explanation': 'Шесть превращается в девять — простая, но приятная загадка на внимательность.'},
            {'question': 'Что идёт, но не имеет ног?', 'options': ['время', 'дождь', 'музыка', 'поезд'], 'answer': 'время', 'explanation': 'Время идёт, а мы только успеваем ставить хорошие треки.'},
            {'question': 'Что можно держать, не касаясь руками?', 'options': ['обещание', 'зонт', 'микрофон', 'гитару'], 'answer': 'обещание', 'explanation': 'Обещание держат словом — в радиоэфире это особенно красиво.'},
        ]
        games = [
            {'question': 'Какого цвета огурец?', 'correct': 'зелёный', 'wrong_examples': ['фиолетовый в горошек', 'прозрачно-радиоактивный', 'цвета утренней сирены'], 'comment': 'В этой игре нужно отвечать неправильно, но не слишком правильно. Если скажешь “чёрный, когда сгнил” — это почти правда и засчитывается как провал.'},
            {'question': 'Что говорит собака?', 'correct': 'гав', 'wrong_examples': ['проверка микрофона', 'сейчас будет припев', 'поставьте следующий трек'], 'comment': 'Главное — не сказать “гав”, иначе ведущий проиграл.'},
            {'question': 'Сколько ног у кошки?', 'correct': 'четыре', 'wrong_examples': ['семь с половиной', 'столько, сколько нужно для танца', 'одна запасная в кармане'], 'comment': 'Ответ должен быть явно неправильным, а не хитрой правдой.'},
        ]
        guest_stories = [
            {'name': 'Гость', 'story': 'Слушатель вспоминает, как одна песня случайно стала саундтреком к важному дню, и просит передать привет всем, кто сейчас у приёмника.', 'angle': 'короткий тёплый звонок в эфир'},
            {'name': 'Гость', 'story': 'Гость рассказывает смешной случай: хотел поставить будильник, а в итоге проснулся от припева любимой песни и весь день ходил с хорошим настроением.', 'angle': 'лёгкая история от слушателя'},
            {'name': 'Гость', 'story': 'Слушатель делится, что иногда одна хорошая композиция меняет настроение сильнее любой новости.', 'angle': 'доброжелательная музыкальная зарисовка'},
        ]
        return {'date': today, 'horoscope': [{'sign': s, 'text': t} for s, t in signs], 'riddles': riddles, 'wrong_games': games, 'guest_stories': guest_stories}

    def _parse_json_object_from_text(self, text: str) -> Dict[str, Any]:
        raw = str(text or '').strip()
        if '```' in raw:
            raw = raw.replace('```json', '').replace('```', '').strip()
        a, b = raw.find('{'), raw.rfind('}')
        if a >= 0 and b > a:
            raw = raw[a:b+1]
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _fetch_web_text(self, url: str, timeout: Optional[int] = None) -> str:
        timeout = int(timeout or self.cfg.get('rubric_web_timeout_sec', 10) or 10)
        url = require_http_url(url)
        req = urllib.request.Request(url, headers={
            'User-Agent': str(self.cfg.get('rubric_web_user_agent') or 'AITruckRadio/0.7 local radio'),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
            raw = r.read(350000).decode('utf-8', errors='replace')
        raw = re.sub(r'(?is)<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>', ' ', raw)
        raw = re.sub(r'(?s)<[^>]+>', ' ', raw)
        raw = html.unescape(raw)
        raw = re.sub(r'\s+', ' ', raw).strip()
        return raw[:6000]

    def _web_horoscope_pack(self) -> List[Dict[str, str]]:
        """Best-effort current horoscope fetch. If sites block/change, caller falls back to LM/fallback."""
        signs = [
            ('Овен','aries'),('Телец','taurus'),('Близнецы','gemini'),('Рак','cancer'),('Лев','leo'),('Дева','virgo'),
            ('Весы','libra'),('Скорпион','scorpio'),('Стрелец','sagittarius'),('Козерог','capricorn'),('Водолей','aquarius'),('Рыбы','pisces')
        ]
        out: List[Dict[str, str]] = []
        # Mail.ru horoscope URLs are stable enough for a first attempt; every item is optional.
        for ru, slug in signs:
            try:
                txt = self._fetch_web_text(f'https://horo.mail.ru/prediction/{slug}/today/')
                # Pick a readable fragment around the sign name/date area.
                m = re.search(r'(?:Сегодня|День|Вам|Сейчас|Не\s+стоит|Стоит)[^.?!]{40,420}[.?!]', txt, flags=re.I)
                val = (m.group(0) if m else txt[:420]).strip()
                if len(val) > 60:
                    out.append({'sign': ru, 'text': val[:520], 'source': 'horo.mail.ru'})
            except Exception as e:
                if len(out) == 0:
                    log(f'Гороскоп: веб-источник недоступен или заблокирован: {e}')
                break
            time.sleep(0.25)
        return out if len(out) >= 6 else []

    def _web_riddle_pack(self) -> List[Dict[str, Any]]:
        """Best-effort online riddles. Fallback/LM is used when web is blocked."""
        urls = [
            'https://zagadki.info/',
            'https://deti-online.com/zagadki/',
            'https://nukadeti.ru/zagadki',
            'https://rustih.ru/zagadki/',
        ]
        found: List[Dict[str, Any]] = []
        failures = []
        for url in urls:
            try:
                txt = self._fetch_web_text(url, timeout=int(self.cfg.get('rubric_web_timeout_sec', 18) or 18))
                # This is intentionally conservative: web riddles are often unstructured.
                pieces = re.split(r'\s{2,}| Ответ: | Отгадка: | Показать ответ ', txt)
                for i, piece in enumerate(pieces[:160]):
                    q = piece.strip(' —-:;')
                    if '?' in q and 20 <= len(q) <= 180 and 'cookie' not in q.lower():
                        found.append({
                            'question': q[:180],
                            'options': ['вариант А', 'вариант Б', 'вариант В', 'вариант Г'],
                            'answer': 'ответ будет уточнён ведущими',
                            'explanation': 'Загадка взята из открытого источника; ведущие могут обсудить её как игру на внимательность.',
                            'source': url,
                        })
                    if len(found) >= 8:
                        return found
            except Exception as e:
                failures.append(f'{url}: {e}')
                continue
        if failures and not found:
            log('Загадки: веб-источники недоступны/заблокированы, использую LM или fallback. Последняя ошибка: ' + failures[-1])
        return found

    def _guest_host_cfg(self) -> Dict[str, Any]:
        name = str(self.cfg.get('guest_name') or 'Гость').strip() or 'Гость'
        voice_mode = str(self.cfg.get('guest_voice_mode') or 'design').strip().lower()
        if voice_mode not in {'design', 'reference', 'auto'}:
            voice_mode = 'design'
        ref_audio = Path(str(self.cfg.get('guest_ref_audio') or 'references/guest_ref.wav'))
        if not ref_audio.is_absolute():
            ref_audio = BASE_DIR / ref_audio
        ref_text = Path(str(self.cfg.get('guest_ref_text') or 'references/guest_ref.txt'))
        if not ref_text.is_absolute():
            ref_text = BASE_DIR / ref_text
        host = {
            'name': name,
            'aliases': list(dict.fromkeys([name, 'Гость', 'Слушатель'])),
            'persona': str(self.cfg.get('guest_role') or 'слушатель с короткой живой историей'),
            'omnivoice_instruct': str(self.cfg.get('guest_voice_instruct') or 'male, young adult, russian accent, moderate pitch'),
        }
        use_reference = ref_audio.exists() and voice_mode in {'reference', 'auto'}
        if use_reference:
            host['omnivoice_mode'] = 'clone'
            host['omnivoice_ref_audio'] = str(ref_audio)
            if ref_text.exists():
                host['omnivoice_ref_text'] = str(ref_text)
        else:
            host['omnivoice_mode'] = 'design'
        return host

    def _guest_ref_status(self) -> Dict[str, Any]:
        ref_audio = Path(str(self.cfg.get('guest_ref_audio') or 'references/guest_ref.wav'))
        if not ref_audio.is_absolute():
            ref_audio = BASE_DIR / ref_audio
        ref_text = Path(str(self.cfg.get('guest_ref_text') or 'references/guest_ref.txt'))
        if not ref_text.is_absolute():
            ref_text = BASE_DIR / ref_text
        return {'audio': str(ref_audio), 'audio_exists': ref_audio.exists(), 'text': str(ref_text), 'text_exists': ref_text.exists()}

    def prepare_entertainment_pack(self, reason: str = 'auto') -> Dict[str, Any]:
        if not self.cfg.get('entertainment_enabled', False):
            return {}
        today = time.strftime('%Y-%m-%d')
        if self.entertainment_pack and self.entertainment_pack_date == today:
            return self.entertainment_pack
        self.entertainment_status = 'готовлю рубрики: гороскопы, загадки и игры...'
        pack = self._fallback_entertainment_pack()
        if self.cfg.get('entertainment_agent_enabled', True) and self.cfg.get('entertainment_generate_with_lm', True) and self.cfg.get('lm_enabled', True):
            try:
                cached_pack = self.entertainment_agent.load_daily_cache()
                pack = cached_pack or self.entertainment_agent.build(pack)
                self.entertainment_status = (
                    ("дневной кэш загружен: " if cached_pack else "агент подготовил рубрики: ")
                    + f"{len(pack.get('horoscope') or [])} знаков, "
                    f"{len(pack.get('riddles') or [])} загадок, {len(pack.get('wrong_games') or [])} игр"
                )
                self.entertainment_pack = pack
                self.entertainment_pack_date = today
                self.horoscope_index = 0
                self.horoscope_blocks_since_riddle = 0
                self.pending_riddle = None
                return pack
            except Exception as e:
                self.entertainment_status = 'агент рубрик не ответил, использую прежний fallback'
                log(f'Агент рубрик не смог собрать пакет: {e}')
        horoscope_mode = str(self.cfg.get('horoscope_source_mode', 'web_then_lm') or 'web_then_lm')
        riddle_mode = str(self.cfg.get('riddle_source_mode', 'web_then_lm') or 'web_then_lm')
        if horoscope_mode in {'web_then_lm', 'web_only'}:
            web_hor = self._web_horoscope_pack()
            if web_hor:
                pack['horoscope'] = web_hor[:12]
                self.entertainment_status = 'гороскопы взяты из веб-источника'
        if riddle_mode in {'web_then_lm', 'web_only'}:
            web_riddles = self._web_riddle_pack()
            if web_riddles:
                pack['riddles'] = web_riddles[:max(1, int(self.cfg.get('entertainment_pack_max_items', 12) or 12))]
                self.entertainment_status = 'загадки взяты из веб-источника'
        need_lm_hor = horoscope_mode != 'web_only' and (not pack.get('horoscope') or horoscope_mode == 'lm_by_date')
        need_lm_riddles = riddle_mode != 'web_only' and (not pack.get('riddles') or riddle_mode == 'lm_by_date')
        if self.cfg.get('entertainment_generate_with_lm', True) and self.cfg.get('lm_enabled', True) and (need_lm_hor or need_lm_riddles or self.cfg.get('wrong_answer_game_enabled', True) or self.cfg.get('guest_enabled', False)):
            try:
                prompt = (
                    f'Дата сегодня: {current_time_text()}. Создай JSON для развлекательного музыкального радио. '
                    'Нужны: horoscope — 12 знаков зодиака с коротким актуальным дружелюбным прогнозом на сегодня; '
                    'riddles — 8 загадок с 4 вариантами ответа, правильным ответом и коротким объяснением; '
                    'wrong_games — 8 вопросов для игры “ответь неправильно”: вопрос, правильный ответ, 3 смешных явно неправильных ответа и комментарий; '
                    'guest_stories — 6 коротких историй для гостя/слушателя в эфире, без политики, медицины и личных данных. '
                    'Никакой политики, медицины, финансовых советов. Не пиши markdown. Только JSON с ключами horoscope, riddles, wrong_games, guest_stories.'
                )
                txt = self.lm.generate_plain_text(
                    prompt,
                    system='Ты готовишь безопасные развлекательные рубрики для радио. Верни только валидный JSON.',
                    temperature=0.65,
                    max_tokens=1800,
                    timeout=int(self.cfg.get('entertainment_pack_timeout_sec', 90) or 90),
                )
                data = self._parse_json_object_from_text(txt)
                horoscope = data.get('horoscope')
                riddles = data.get('riddles')
                wrong_games = data.get('wrong_games')
                guest_stories = data.get('guest_stories')
                if need_lm_hor and isinstance(horoscope, list) and len(horoscope) >= 6:
                    pack['horoscope'] = horoscope[:12]
                if need_lm_riddles and isinstance(riddles, list) and riddles:
                    pack['riddles'] = riddles[:max(1, int(self.cfg.get('entertainment_pack_max_items', 12) or 12))]
                if isinstance(wrong_games, list) and wrong_games:
                    pack['wrong_games'] = wrong_games[:max(1, int(self.cfg.get('entertainment_pack_max_items', 12) or 12))]
                if isinstance(guest_stories, list) and guest_stories:
                    pack['guest_stories'] = guest_stories[:max(1, int(self.cfg.get('guest_story_count', 6) or 6))]
                self.entertainment_status = 'рубрики подготовлены через web/LM Studio'
            except Exception as e:
                self.entertainment_status = 'рубрики взяты из fallback: веб/LM не успели ответить'
                log(f'Не удалось сгенерировать рубрики через LM Studio, беру fallback: {e}')
        else:
            self.entertainment_status = 'рубрики подготовлены из fallback'
        self.entertainment_pack = pack
        self.entertainment_pack_date = today
        self.horoscope_index = 0
        self.horoscope_blocks_since_riddle = 0
        self.pending_riddle = None
        return pack

    def _choose_entertainment_for_block(self, *, intro: bool = False, planned: bool = False, block_index: Optional[int] = None) -> Dict[str, Any]:
        current_block = self.speech_blocks_played if block_index is None else int(block_index)
        if intro or not self.cfg.get('entertainment_enabled', False):
            return {}
        if planned and not self.cfg.get('entertainment_in_planned', True):
            return {}
        if (not planned) and not self.cfg.get('entertainment_in_live', True):
            return {}
        # Ответ на загадку имеет приоритет и должен выйти на следующей речи.
        if self.pending_riddle:
            r = self.pending_riddle
            self.pending_riddle = None
            self.last_entertainment_block = current_block
            self.entertainment_block_count += 1
            q = str(r.get('question') or '')
            ans = str(r.get('answer') or '')
            expl = str(r.get('explanation') or '')
            return {
                'entertainment_text': f'БЛОК ОТВЕТА НА ПРОШЛУЮ ЗАГАДКУ. Вопрос был: «{q}». Правильный ответ: {ans}. Объяснение: {expl}. НЕ задавай новую загадку в этом блоке.',
                'entertainment_instruction': 'Сразу назови ответ на прошлую загадку, коротко обсуди его и пошути с соведущим. Нельзя говорить, что ответ будет завтра/утром/позже. Нельзя задавать новую загадку. Затем аккуратно подведи к следующей музыке.',
                'dj_topic_label': 'ответ на загадку и музыкальная подводка',
                'dj_length': 'medium',
                'riddle_answer_block': True,
            }
        if (current_block - self.last_entertainment_block) < max(0, int(self.cfg.get('entertainment_min_blocks_between', 1) or 1)):
            return {}
        if random.random() > float(self.cfg.get('entertainment_chance', 0.55) or 0.55):
            return {}
        pack = self.prepare_entertainment_pack('block')
        history_date = time.strftime("%Y-%m-%d")
        history_mode = "planned" if planned else "live"
        # Гость в эфире: короткая история/звонок. Может вклиниваться реже остальных рубрик.
        guest_allowed = bool(self.cfg.get('guest_enabled', False)) and ((planned and self.cfg.get('guest_in_planned', True)) or ((not planned) and self.cfg.get('guest_in_live', True)))
        if guest_allowed and (current_block - self.last_guest_block) >= int(self.cfg.get('guest_min_blocks_between', 6) or 6):
            if random.random() < float(self.cfg.get('guest_chance', 0.14) or 0.14):
                guests = filter_unused(self.cfg, "guest_story", pack.get('guest_stories') or [])
                if guests:
                    g = random.choice(guests)
                    mark_used(self.cfg, "guest_story", g, mode=history_mode)
                    self.last_guest_block = current_block
                    self.last_entertainment_block = current_block
                    self.entertainment_block_count += 1
                    return {
                        'entertainment_text': 'Гость в эфире. История гостя: ' + json.dumps(g, ensure_ascii=False),
                        'entertainment_instruction': 'Сделай короткий живой разговор с гостем. Ведущий задаёт 1 вопрос, Гость отвечает историей, второй ведущий может улыбнуться/пошутить. Затем мягко подведите к следующей музыке.',
                        'dj_topic_label': 'гость в эфире и музыкальная подводка',
                        'dj_length': 'medium',
                        'force_guest': True,
                    }
        # Игра “ответь неправильно” может вклиниться между гороскопами/загадками.
        if self.cfg.get('wrong_answer_game_enabled', True) and (current_block - self.last_wrong_game_block) >= int(self.cfg.get('wrong_answer_game_min_blocks_between', 4) or 4):
            if random.random() < float(self.cfg.get('wrong_answer_game_chance', 0.18) or 0.18):
                games = filter_unused(self.cfg, "wrong_game", pack.get('wrong_games') or [])
                if games:
                    g = random.choice(games)
                    mark_used(self.cfg, "wrong_game", g, mode=history_mode)
                    self.last_wrong_game_block = current_block
                    self.last_entertainment_block = current_block
                    self.entertainment_block_count += 1
                    return {
                        'entertainment_text': 'Мини-игра «ответь неправильно». ' + json.dumps(g, ensure_ascii=False),
                        'entertainment_instruction': 'Один ведущий задаёт вопрос, второй должен ответить явно неправильно. Если ответ хоть как-то правильный или хитро правдивый — он проиграл. Обсудите это весело и коротко, затем подведите к следующей музыке.',
                        'dj_topic_label': 'игра «ответь неправильно» и музыкальная подводка',
                        'dj_length': 'medium',
                    }
        # Чередование: 2–3 гороскопа, затем загадка.
        if self.cfg.get('riddles_enabled', True) and self.horoscope_blocks_since_riddle >= self.horoscope_blocks_before_riddle_target:
            if (current_block - self.last_riddle_block) >= int(self.cfg.get('riddle_min_blocks_between', 3) or 3):
                riddles = filter_unused(self.cfg, "riddle", pack.get('riddles') or [])
                if riddles:
                    r = random.choice(riddles)
                    mark_used(self.cfg, "riddle", r, mode=history_mode)
                    self.pending_riddle = r
                    self.last_riddle_block = current_block
                    self.last_entertainment_block = current_block
                    self.horoscope_blocks_since_riddle = 0
                    self.horoscope_blocks_before_riddle_target = random.randint(
                        max(1, int(self.cfg.get('horoscope_blocks_before_riddle_min', 2) or 2)),
                        max(1, int(self.cfg.get('horoscope_blocks_before_riddle_max', 3) or 3)),
                    )
                    opts = r.get('options') or []
                    return {
                        'entertainment_text': f'БЛОК НОВОЙ ЗАГАДКИ. Загадка: {r.get("question", "")}. Варианты ответа: {", ".join(map(str, opts))}. НЕ называй правильный ответ сейчас. Скажи строго: ответ прозвучит в следующий выход ведущих после одной из песен. Не говори завтра, утром или вечером.',
                        'entertainment_instruction': 'Задай загадку с вариантами, оставь интригу только до следующего выхода ведущих. Запрещено обещать ответ завтра/утром/вечером. Затем подведи к следующей музыке.',
                        'dj_topic_label': 'загадка с вариантами ответа',
                        'dj_length': 'medium',
                        'riddle_question_block': True,
                    }
        if self.cfg.get('horoscope_enabled', True):
            hor = filter_unused(self.cfg, "horoscope", pack.get('horoscope') or [], history_date)
            if hor:
                lo = max(1, int(self.cfg.get('horoscope_chunk_min', 2) or 2))
                hi = max(lo, int(self.cfg.get('horoscope_chunk_max', 3) or 3))
                count = random.randint(lo, hi)
                chunk = hor[:count]
                for item in chunk:
                    mark_used(self.cfg, "horoscope", item, date=history_date, mode=history_mode)
                self.horoscope_index += len(chunk)
                self.horoscope_blocks_since_riddle += 1
                self.last_entertainment_block = current_block
                self.entertainment_block_count += 1
                done = len(chunk) >= len(hor)
                return {
                    'entertainment_text': 'Гороскоп на сегодня. Обязательно назови каждый знак отдельно в формате «Овен: ...», «Телец: ...». Знаки и тексты: ' + json.dumps(chunk, ensure_ascii=False) + (' Это последний блок гороскопа, после него больше не объявляй гороскопы.' if done else ' В конце можно сказать, что остальные знаки продолжим в следующий раз.'),
                    'entertainment_instruction': 'Прочитай каждый переданный прогноз по смыслу полностью, без пересказа вида «прогноз был про любовь». Название знака не изменяй и пиши строго «Знак: прогноз». Затем сделай обычную подводку к следующей музыке.',
                    'horoscope_expected': chunk,
                    'dj_topic_label': 'гороскоп и музыкальная подводка',
                    'dj_length': 'medium',
                }
        return {}

    def build_context(self, selected_hosts: Optional[List[Dict[str, Any]]] = None, two_hosts: Optional[bool] = None, intro_allowed_override: Optional[bool] = None, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        night = is_night_now(self.cfg)
        style = str(self.cfg.get("station_style") or "универсальное радио")
        intro_allowed = self.speech_blocks_played == 0 if intro_allowed_override is None else bool(intro_allowed_override)
        if selected_hosts is None or two_hosts is None:
            selected_hosts, two = self._select_hosts_for_insert(bool(intro_allowed))
            if two_hosts is None:
                two_hosts = two
        time_text = ""
        spoken_time_text = ""
        exact_time_text = ""
        time_offset_sec = 0.0
        if overrides and overrides.get("time_offset_sec") not in [None, ""]:
            try:
                time_offset_sec = float(overrides.get("time_offset_sec") or 0.0)
            except Exception:
                time_offset_sec = 0.0
        elif intro_allowed:
            try:
                time_offset_sec = float(self.cfg.get("startup_intro_time_lead_sec", 60) or 60)
            except Exception:
                time_offset_sec = 60.0
        if self.cfg.get("time_context_enabled", True):
            # Время всегда берём с компьютера, но для заранее подготовленной речи
            # передаём ожидаемое время выхода в эфир, а не время начала генерации.
            time_text = current_time_text_at_offset(time_offset_sec)
            spoken_time_text = current_time_spoken_text_at_offset(time_offset_sec)
            exact_time_text = exact_hour_announcement_text(self.cfg)
            if exact_time_text:
                hour_key = time.localtime(time.time() + time_offset_sec).tm_hour
                if self.last_hour_announcement_hour == hour_key and not intro_allowed:
                    exact_time_text = ""
        speech_time = time.localtime(time.time() + time_offset_sec)
        computer_hour = int(speech_time.tm_hour)
        computer_minute = int(speech_time.tm_min)
        all_host_names = [
            str(h.get("name", "")).strip()
            for h in (self.cfg.get("hosts") or [])
            if isinstance(h, dict) and str(h.get("name", "")).strip()
        ]
        weather_text = ""
        if self.cfg.get("weather_enabled", False):
            if intro_allowed or random.random() < float(self.cfg.get("weather_context_chance", 0.25)):
                weather_text = self.weather.get_weather_text()
        news_text = ""
        if self.cfg.get("news_enabled", True) and random.random() < float(self.cfg.get("news_chance", 0.35)):
            news_text = read_news_line(self.cfg)
        greeting_text = ""
        if self.cfg.get("listener_greetings_enabled", True):
            due = (self.tracks_played - self.last_greeting_track_index) >= max(1, int(self.next_greeting_after or 1))
            chance_ok = random.random() < float(self.cfg.get("listener_greetings_chance", 0.22))
            if due and (intro_allowed or chance_ok):
                greeting_text = read_greeting_line(self.cfg)
        dj_plan = self._choose_dj_plan(bool(intro_allowed), bool(news_text), bool(weather_text))
        planned_mode = bool(overrides and overrides.get("plan_mode") == "prepared_program")
        entertainment_block_index: Optional[int] = None
        if overrides and overrides.get("speech_blocks_played") not in [None, ""]:
            try:
                entertainment_block_index = int(overrides.get("speech_blocks_played") or 0)
            except Exception:
                entertainment_block_index = None
        entertainment_overrides: Dict[str, Any] = {}
        if not (overrides and overrides.get("entertainment_text")):
            entertainment_overrides = self._choose_entertainment_for_block(intro=bool(intro_allowed), planned=planned_mode, block_index=entertainment_block_index)
        tts_backend = str(self.cfg.get("tts_backend", "")).lower().strip()
        allow_omni_tags = (
            tts_backend in {"omnivoice", "omnivoice_tts", "omni", "omni_voice"}
            and bool(self.cfg.get("omnivoice_nonverbal_tags_enabled", True))
            and random.random() < clamp(float(self.cfg.get("omnivoice_nonverbal_tags_chance", 0.25) or 0.25), 0.0, 1.0)
        )
        ctx = {
            "station_name": str(self.cfg.get("station_name") or "Волна FM"),
            "style": style,
            "style_prompt": style_prompt(style, night),
            "is_night": night,
            "intro_allowed": bool(intro_allowed and self.cfg.get("greeting_only_first_insert", True)),
            "speech_blocks_played": self.speech_blocks_played,
            "tracks_played": self.tracks_played,
            "time_text": time_text,
            "spoken_time_text": spoken_time_text if time_text else "",
            "computer_hour": computer_hour,
            "computer_minute": computer_minute,
            "daypart_text": daypart_name_for_hour(computer_hour),
            "time_offset_sec": time_offset_sec,
            "expected_speech_time_text": time_text,
            "host_strict_clock_guard": bool(self.cfg.get("host_strict_clock_guard", True)),
            "exact_time_text": exact_time_text,
            "weather_text": weather_text,
            "weather_city": str(self.cfg.get("weather_city") or "").strip(),
            "news_text": news_text,
            "greeting_text": greeting_text,
            "two_hosts": bool(two_hosts and len(selected_hosts or []) >= 2),
            "hosts": selected_hosts or [],
            "all_host_names": all_host_names,
            "recent_host_texts": list(self.recent_host_texts),
            "host_mode": str(self.cfg.get("host_mode", "mostly_solo")),
            "dj_plan": dj_plan,
            "dj_length": dj_plan.get("length", "short"),
            "dj_topic": dj_plan.get("topic", "music"),
            "dj_topic_label": dj_plan.get("topic_label", "музыка"),
            "dj_instruction": dj_plan.get("instruction", "Короткая радиоподводка."),
            "allow_omnivoice_nonverbal_tags": allow_omni_tags,
        }
        if entertainment_overrides:
            ctx.update(entertainment_overrides)
        if overrides:
            for k, v in overrides.items():
                if v not in [None, ""]:
                    ctx[k] = v
        return ctx

    def _record_host_text_as_aired(self, text: str) -> None:
        with self.state_lock:
            self.last_host_text = text
            compact = " ".join(text.split())[:300]
            if compact:
                self.recent_host_texts.append(compact)
                limit = max(1, int(self.cfg.get("recent_context_items", 5)))
                self.recent_host_texts = self.recent_host_texts[-limit:]

    def create_dj_segment(self, previous_track: Optional[Track], next_track: Optional[Track], *, intro_allowed: Optional[bool] = None, mark_aired: bool = False, context_overrides: Optional[Dict[str, Any]] = None) -> Optional[PreparedDJ]:
        selected_hosts, two = self._select_hosts_for_insert(bool(intro_allowed))
        text = ""
        ctx: Dict[str, Any] = {}
        if self.cfg.get("lm_enabled", True):
            try:
                self.used_lm_model = self.lm.pick_model()
                ctx = self.build_context(selected_hosts=selected_hosts, two_hosts=two, intro_allowed_override=intro_allowed, overrides=context_overrides)
                if ctx.get('force_guest'):
                    guest_host = self._guest_host_cfg()
                    if not any(isinstance(h, dict) and str(h.get('name','')).strip().lower() == str(guest_host.get('name','')).strip().lower() for h in selected_hosts):
                        selected_hosts = list(selected_hosts) + [guest_host]
                    ctx['hosts'] = selected_hosts
                    ctx['guest_ref_status'] = self._guest_ref_status()
                ctx["previous_track_name"] = previous_track.display_name if previous_track else "ещё ничего не играло"
                ctx["next_track_name"] = next_track.display_name if next_track else "следующий трек не выбран"
                ctx["host_should_use_stress_marks"] = bool(self.cfg.get("host_should_use_stress_marks", True))
                if self.cfg.get("track_profiles_enabled", True) and self.cfg.get("track_profiles_include_in_prompt", True):
                    ctx["previous_track_info"] = short_track_profile(previous_track, self.track_profiles, self.music_dir)
                    ctx["next_track_info"] = short_track_profile(next_track, self.track_profiles, self.music_dir)
                def _duo_missing_names(candidate_text: str) -> List[str]:
                    names_present = [str(h.get("name", "")).strip() for h in selected_hosts[:2]]
                    return [nm for nm in names_present if nm and not re.search(rf"(?m)(^|\s){re.escape(nm)}\s*:", candidate_text)]

                raw_text = self.lm.generate_host_line(previous_track, next_track, ctx)
                text = postprocess_host_text_for_air(raw_text, ctx)
                # Проверяем базовый runtime-контекст до TTS. Если модель вдруг
                # говорит про полночь в 15:00 или вспоминает прошлый трек на
                # стартовом эфире, повторяем запрос с тем же полным контекстом.
                context_attempts = max(1, int(self.cfg.get("host_clock_retry_attempts", 3) or 3))
                for context_attempt in range(1, context_attempts + 1):
                    violations = context_violations_for_host_text(text, ctx)
                    if not violations:
                        break
                    log("LM Studio нарушил контекст эфира — повторяю запрос " + str(context_attempt) + "/" + str(context_attempts) + ": " + "; ".join(violations))
                    ctx_retry = dict(ctx)
                    ctx_retry["retry_reason"] = "; ".join(violations)
                    if intro_allowed and two and len(selected_hosts) >= 2:
                        ctx_retry["force_duo_intro_dialogue"] = True
                    raw_text = self.lm.generate_host_line(previous_track, next_track, ctx_retry)
                    text = postprocess_host_text_for_air(raw_text, ctx_retry)
                    ctx = ctx_retry
                if context_violations_for_host_text(text, ctx):
                    log("LM Studio всё ещё путает время/контекст — применяю последнюю безопасную чистку перед TTS")
                    text = repair_time_context_text(text, ctx)
                # For an opening where the selected mode is duo, the second host is mandatory.
                # Do not let old configs silently disable this with strict_duo_intro_require_both=False.
                if intro_allowed and two and len(selected_hosts) >= 2:
                    attempts = max(2, int(self.cfg.get("strict_duo_intro_retry_attempts", 4) or 4))
                    missing = _duo_missing_names(text)
                    for attempt in range(1, attempts + 1):
                        if not missing:
                            break
                        log(f"LM Studio вернул вступление без {', '.join(missing)} — повторяю запрос {attempt}/{attempts} с требованием полноценного диалога")
                        ctx_retry = dict(ctx)
                        ctx_retry["force_duo_intro_dialogue"] = True
                        ctx_retry["duo_retry_attempt"] = attempt
                        raw_text = self.lm.generate_host_line(previous_track, next_track, ctx_retry)
                        text = postprocess_host_text_for_air(raw_text, ctx_retry)
                        ctx = ctx_retry
                        missing = _duo_missing_names(text)
                    if missing:
                        self.set_error("LM Studio не смогла дать стартовый диалог с обоими ведущими. Вставка отклонена, чтобы не выпускать соло вместо диалога.")
                        log("Стартовая вставка отклонена: LM Studio так и не дала обоих ведущих без служебных ремарок")
                        return None
                final_violations = context_violations_for_host_text(text, ctx)
                if final_violations:
                    log("Финальная чистка контекста перед TTS: " + "; ".join(final_violations))
                    text = repair_time_context_text(sanitize_general_radio_text(text), ctx)
                    if ctx.get("horoscope_expected") and any("гороскоп" in item for item in final_violations):
                        host_name = str((selected_hosts[0] if selected_hosts else {}).get("name") or "Ведущий").strip()
                        forecasts = []
                        for item in ctx.get("horoscope_expected") or []:
                            if not isinstance(item, dict):
                                continue
                            sign = str(item.get("sign") or "").strip()
                            forecast = str(item.get("text") or "").strip()
                            if sign and forecast:
                                forecasts.append(f"{sign}: {forecast}")
                        if forecasts:
                            text = f"{host_name}: Гороскоп на сегодня. " + " ".join(forecasts)
                            log("Гороскоп собран из проверенного пакета без повторного пересказа моделью")
            except Exception as e:
                self.set_error(f"LM Studio недоступен или не ответил: {e}")
                log(f"LM Studio не ответил, беру fallback-фразу: {e}")
        if not text:
            fallback_names = [
                str(h.get("name") or "").strip()
                for h in selected_hosts
                if isinstance(h, dict) and str(h.get("name") or "").strip()
            ]
            if len(fallback_names) >= 2:
                text = (
                    f"{fallback_names[0]}: Держим эфир живым и тёплым, следующий трек уже рядом. "
                    f"{fallback_names[1]}: Оставайтесь с нами, впереди хорошая музыка."
                )
            elif fallback_names:
                text = f"{fallback_names[0]}: Держим эфир живым и тёплым, следующий трек уже рядом."
            else:
                text = random.choice(list(self.cfg.get("fallback_host_phrases") or DEFAULT_CONFIG["fallback_host_phrases"]))
        text = sanitize_general_radio_text(postprocess_host_text_for_air(normalize_generated_radio_text(clean_host_text(text, int(self.cfg.get("max_host_text_chars", 4000) or 4000))), ctx))
        text = normalize_omnivoice_nonverbal_tags(
            text,
            enabled=bool(self.cfg.get("omnivoice_nonverbal_tags_enabled", True))
            and str(self.cfg.get("tts_backend", "")).lower().strip() in {"omnivoice", "omnivoice_tts", "omni", "omni_voice"},
        )
        text = soften_tts_exclamations(text)
        # На всякий случай не даём повторному блоку снова открывать эфир.
        if not (intro_allowed or False):
            text = re.sub(r"(?i)\b(добро пожаловать|начинаем эфир|с вами снова)\b[^.!?…]*[.!?…]?", "", text).strip() or text
        if self.cfg.get("tts_debug_log", True):
            log("Текст для TTS: " + " ".join(text.split())[:500])
        mp3 = self.tts.get_or_create_dialogue_mp3(text, selected_hosts or self.cfg.get("hosts") or [])
        if not mp3:
            self.set_error("Не удалось создать озвучку ведущего. Радио продолжит музыку без вставки.")
            log("DJ segment: текст есть, но TTS не вернул mp3")
            return None
        if self.cfg.get("tts_debug_log", True):
            try:
                log(f"DJ segment: mp3 готов: {mp3} ({mp3.stat().st_size} байт)")
            except Exception:
                log(f"DJ segment: mp3 готов: {mp3}")
        if mark_aired:
            self._record_host_text_as_aired(text)
            try:
                if ctx.get("greeting_text"):
                    self.last_greeting_track_index = self.tracks_played
                    lo = max(1, int(self.cfg.get("listener_greetings_every_tracks_min", 4) or 4))
                    hi = max(lo, int(self.cfg.get("listener_greetings_every_tracks_max", 8) or 8))
                    self.next_greeting_after = random.randint(lo, hi)
                if ctx.get("exact_time_text"):
                    self.last_hour_announcement_hour = time.localtime().tm_hour
            except Exception:
                pass
        if next_track is not None and bool(self.cfg.get("startup_intro_reserve_first_track", True)):
            self.reserved_next_track = next_track
            log(f"Зарезервирован следующий трек для объявленной вставки: {next_track.display_name}")
        return PreparedDJ(
            mp3=mp3,
            text=text,
            previous_key=track_key(previous_track),
            next_key=track_key(next_track),
            created_ts=time.time(),
        )

    def make_dj_mp3(self) -> Optional[Path]:
        prepared = self.take_prepared_dj(self.previous_track, self.peek_next_track())
        if (
            not prepared
            and self.speech_blocks_played == 0
            and not bool(self.cfg.get("startup_intro_blocking", True))
            and str(self.cfg.get("startup_late_intro_policy", "discard")) == "first_break"
        ):
            prepared = self.take_late_startup_intro_if_any()
        if prepared:
            self._record_host_text_as_aired(prepared.text)
            self.played_since_dj = 0
            self.next_dj_after = self._random_dj_gap()
            return prepared.mp3

        if self.cfg.get("live_blocking_dj_when_due", True) and self.should_insert_dj():
            log("Live: вставка ведущих обязательна по интервалу, готовлю синхронно перед следующей музыкой")
            seg = self.create_dj_segment(self.previous_track, self.peek_next_track(), intro_allowed=False, mark_aired=True)
            if seg:
                self.played_since_dj = 0
                self.next_dj_after = self._random_dj_gap()
                return seg.mp3

        # Живой эфир не должен замирать из-за LLM/TTS. Если заранее подготовленная
        # вставка ещё не готова, лучше продолжить музыку и дождаться следующей
        # подходящей вставки, чем держать локальный стрим в тишине.
        if self.cfg.get("never_block_for_dj", True):
            with self.prepare_lock:
                alive = bool(self.prepare_thread and self.prepare_thread.is_alive())
                if alive:
                    self.prepared_status = "вставка ещё готовится, эфир продолжает музыку"
                else:
                    self.prepared_status = "готовой вставки нет, эфир продолжает музыку"
            log("Готовой вставки ведущих нет — не блокирую эфир, продолжаю музыку")
            return None

        seg = self.create_dj_segment(self.previous_track, self.peek_next_track(), intro_allowed=self.speech_blocks_played == 0, mark_aired=True)
        if seg:
            self.played_since_dj = 0
            self.next_dj_after = self._random_dj_gap()
            return seg.mp3
        return None

    def pre_generate(self) -> None:
        # Старую стартовую предгенерацию выключаем: она показывала текст в панели,
        # но не попадала в эфир. Теперь реальные вставки готовятся асинхронно во время музыки.
        return

    def take_prepared_dj(self, previous_track: Optional[Track], next_track: Optional[Track]) -> Optional[PreparedDJ]:
        with self.prepare_lock:
            seg = self.prepared_dj
            if not seg:
                return None
            if seg.previous_key != track_key(previous_track) or seg.next_key != track_key(next_track):
                return None
            self.prepared_dj = None
            self.prepared_status = "готовая вставка взята в эфир"
            return seg

    def take_late_startup_intro_if_any(self) -> Optional[PreparedDJ]:
        # Если стартовая озвучка готовилась дольше окна ожидания, она раньше
        # навсегда зависала как stale prepared_dj: previous_key=None уже не
        # совпадал с previous_track после первой песни. Теперь забираем её
        # в первый ближайший перерыв, но только пока ещё не было ни одной речи.
        with self.prepare_lock:
            seg = self.prepared_dj
            if not seg:
                return None
            if seg.previous_key != track_key(None):
                return None
            self.prepared_dj = None
            self.prepared_status = "поздняя стартовая вставка взята в ближайший перерыв"
            log("Поздняя стартовая вставка будет выведена в эфир в ближайший перерыв")
            return seg

    def start_prepare_dj_for_after_track(self, current_track: Track, reason: str = "track_start") -> None:
        due_after_current = self.should_insert_after_current_track()
        if (not self.cfg.get("async_prepare_dj", True)) and not (due_after_current and self.cfg.get("live_force_early_prepare_when_due", True)):
            return
        next_track = self.peek_next_track()
        if not due_after_current:
            if self.cfg.get("live_prepare_trace_logs", True):
                log(f"Live: пока не готовлю ведущих после трека: {current_track.display_name}; счётчик {self.played_since_dj + 1}/{self.next_dj_after}")
            return
        if self.cfg.get("live_prepare_trace_logs", True):
            log(f"Live: условие вставки выполнено, ранняя подготовка ({reason}) для трека: {current_track.display_name}; следующий: {next_track.display_name if next_track else 'не выбран'}")
        with self.prepare_lock:
            if self.prepare_thread and self.prepare_thread.is_alive():
                return
            if self.prepared_dj and self.speech_blocks_played == 0 and self.prepared_dj.previous_key == track_key(None):
                # Не перетираем позднюю стартовую вставку обычной подготовкой.
                self.prepared_status = "стартовая вставка готова и ждёт ближайший перерыв"
                return
            if self.prepared_dj and self.prepared_dj.previous_key == track_key(current_track) and self.prepared_dj.next_key == track_key(next_track):
                return
            self.prepared_status = f"готовлю следующую вставку ведущих заранее ({reason}) во время текущего трека..."
            log(f"Live: заранее готовлю ведущих ({reason}) после трека: {current_track.display_name}; следующий: {next_track.display_name if next_track else 'не выбран'}")

        def worker() -> None:
            try:
                time_offset = 0.0
                if self.cfg.get("live_expected_speech_time_enabled", True):
                    try:
                        dur = ffprobe_duration(self.cfg, current_track.path)
                        with self.state_lock:
                            elapsed = max(0.0, time.time() - float(self.current_started_ts or time.time()))
                        time_offset = max(0.0, float(dur or 0.0) - elapsed)
                    except Exception:
                        time_offset = 0.0
                seg = self.create_dj_segment(current_track, next_track, intro_allowed=False, mark_aired=False, context_overrides={"time_offset_sec": time_offset} if time_offset > 0 else None)
                with self.prepare_lock:
                    self.prepared_dj = seg
                    self.prepared_status = "вставка ведущих подготовлена" if seg else "не удалось подготовить вставку"
                if seg:
                    log("Следующая вставка ведущих заранее подготовлена")
            except Exception as e:
                with self.prepare_lock:
                    self.prepared_status = f"ошибка подготовки: {e}"
                log(f"Не удалось заранее подготовить ведущих: {e}")
        self.prepare_thread = threading.Thread(target=worker, name="PrepareDJ", daemon=True)
        self.prepare_thread.start()

    def _audio_filter(self, path: Path, kind: str, duration_override: Optional[float] = None) -> str:
        if not self.cfg.get("fade_enabled", True):
            return "aresample=44100,aformat=channel_layouts=stereo"
        duration = duration_override if duration_override is not None else ffprobe_duration(self.cfg, path)
        if kind == "speech":
            fade_in = max(0.0, float(self.cfg.get("speech_fade_in_sec", 0.15)))
            fade_out = max(0.0, float(self.cfg.get("speech_fade_out_sec", 0.25)))
        else:
            fade_in = max(0.0, float(self.cfg.get("music_fade_in_sec", 1.2)))
            fade_out = max(0.0, float(self.cfg.get("music_fade_out_sec", 2.8)))
        filters = ["aresample=44100", "aformat=channel_layouts=stereo"]
        if kind == "speech" and self.cfg.get("speech_radio_processing_enabled", True):
            # Лёгкая радио-обработка: чистим низ, добавляем presence, сжимаем динамику,
            # нормализуем громкость и ловим пики. Это не студийный мастеринг, но
            # сильно помогает TTS звучать ближе к эфиру.
            filters.append("highpass=f=70")
            filters.append("lowpass=f=15500")
            if self.cfg.get("speech_presence_eq_enabled", True):
                gain = clamp(float(self.cfg.get("speech_presence_gain_db", 3.0)), -3.0, 8.0)
                filters.append(f"equalizer=f=3400:t=q:w=1.05:g={gain:.2f}")
            if self.cfg.get("speech_compressor_enabled", True):
                filters.append("acompressor=threshold=0.10:ratio=3.2:attack=6:release=140:makeup=2.2")
            if self.cfg.get("speech_loudnorm_enabled", True):
                target_i = clamp(float(self.cfg.get("speech_loudnorm_i", -14.0)), -22.0, -10.0)
                filters.append(f"loudnorm=I={target_i:.1f}:TP=-1.3:LRA=8")
        if fade_in > 0.01:
            filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if duration and fade_out > 0.01 and duration > fade_out + 0.5:
            start = max(0.0, duration - fade_out)
            filters.append(f"afade=t=out:st={start:.3f}:d={fade_out:.3f}")
        if kind == "speech" and self.cfg.get("speech_radio_processing_enabled", True) and self.cfg.get("speech_limiter_enabled", True):
            filters.append("alimiter=limit=0.96")
        return ",".join(filters)

    def _speech_bed_files(self) -> List[Path]:
        bed_dir = Path(str(self.cfg.get("speech_bed_dir", "beds")))
        if not bed_dir.is_absolute():
            bed_dir = BASE_DIR / bed_dir
        if not bed_dir.exists():
            return []
        return [p for p in bed_dir.rglob("*") if p.is_file() and p.suffix.lower() in MUSIC_EXTS]

    def _pick_speech_bed(self) -> Optional[Path]:
        files = self._speech_bed_files()
        return random.choice(files) if files else None

    def _jingle_files(self) -> List[Path]:
        jingle_dir = Path(str(self.cfg.get("jingle_dir", "jingles")))
        if not jingle_dir.is_absolute():
            jingle_dir = BASE_DIR / jingle_dir
        if not jingle_dir.exists():
            return []
        return [p for p in jingle_dir.rglob("*") if p.is_file() and p.suffix.lower() in MUSIC_EXTS]

    def _pick_jingle(self) -> Optional[Path]:
        files = self._jingle_files()
        return random.choice(files) if files else None

    def _stream_auto_sweep_jingle(self) -> bool:
        ffmpeg = str(self.cfg.get("ffmpeg_path", "ffmpeg"))
        if not executable_exists(ffmpeg):
            return False
        bitrate = int(self.cfg.get("bitrate_kbps", 128))
        vol = clamp(float(self.cfg.get("jingle_volume", 0.28)), 0.0, 1.0)
        # Короткий двухтональный sweep/stinger на случай, если пользователь ещё не положил свои jingles.
        filter_complex = (
            f"[0:a][1:a]concat=n=2:v=0:a=1,volume={vol:.3f},"
            "afade=t=in:st=0:d=0.015,afade=t=out:st=0.245:d=0.055,alimiter=limit=0.94[out]"
        )
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-re", "-i", "sine=frequency=740:sample_rate=44100:duration=0.12",
            "-f", "lavfi", "-i", "sine=frequency=1180:sample_rate=44100:duration=0.18",
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-ar", "44100", "-ac", "2", "-b:a", f"{bitrate}k", "-f", "mp3", "pipe:1",
        ]
        log("Короткий sweep/jingle после ведущих")
        return self._run_ffmpeg_pipe_to_broadcast(cmd)

    def _stream_jingle_after_speech(self) -> bool:
        if not self.cfg.get("jingle_enabled", True):
            return False
        chance = clamp(float(self.cfg.get("jingle_chance_after_speech", 0.55)), 0.0, 1.0)
        if random.random() > chance:
            return False
        jingle = self._pick_jingle()
        if jingle:
            log(f"Jingle после ведущих: {jingle.name}")
            return self._stream_path_plain_to_broadcast(jingle, "jingle")
        if self.cfg.get("auto_generate_sweep_jingle", True):
            return self._stream_auto_sweep_jingle()
        return False

    def _station_id_files(self) -> List[Path]:
        sid_dir = Path(str(self.cfg.get("station_id_dir", "station_ids")))
        if not sid_dir.is_absolute():
            sid_dir = BASE_DIR / sid_dir
        if not sid_dir.exists():
            return []
        return [p for p in sid_dir.rglob("*") if p.is_file() and p.suffix.lower() in MUSIC_EXTS]

    def _pick_station_id_file(self) -> Optional[Path]:
        files = self._station_id_files()
        return random.choice(files) if files else None

    def _maybe_air_station_id(self) -> bool:
        """Short station ident between tracks when there is no host block.
        User can drop files into station_ids/*.mp3/wav/flac.
        """
        if not self.cfg.get("station_id_enabled", True):
            return False
        if self.stop_event.is_set() or self.skip_event.is_set():
            return False
        if self.should_insert_dj():
            return False
        every = max(1, int(float(self.cfg.get("station_id_every_tracks", 2) or 2)))
        if (self.tracks_played - self.last_station_id_track_index) < every:
            return False
        chance = clamp(float(self.cfg.get("station_id_chance", 0.45)), 0.0, 1.0)
        if random.random() > chance:
            return False
        sid = self._pick_station_id_file()
        if sid:
            self.last_station_id_track_index = self.tracks_played
            self.set_now("Фирменная вставка станции", "station_id")
            log(f"Station ID между треками: {sid.name}")
            ok = self._stream_path_plain_to_broadcast(sid, "jingle")
            self._transition_pause()
            return ok
        if self.cfg.get("station_id_fallback_tts_enabled", False):
            texts = self.cfg.get("station_id_fallback_texts") or DEFAULT_CONFIG.get("station_id_fallback_texts") or []
            text = random.choice(list(texts)) if texts else "AI Радио. Музыка продолжается!"
            hosts = self.cfg.get("hosts") or []
            mp3 = self.tts.get_or_create_dialogue_mp3(text, hosts)
            if mp3:
                self.last_station_id_track_index = self.tracks_played
                self.set_now("Фирменная вставка станции", "station_id")
                log("Station ID fallback TTS: " + text)
                ok = self._stream_path_to_broadcast(mp3, "speech")
                self._transition_pause()
                return ok
        return False

    def _run_ffmpeg_pipe_to_broadcast(self, cmd: List[str]) -> bool:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ok = True
        try:
            if proc.stdout is None:
                raise RuntimeError("FFmpeg music process started without stdout")
            while not self.stop_event.is_set():
                if self.skip_event.is_set():
                    ok = False
                    break
                chunk = proc.stdout.read(16 * 1024)
                if not chunk:
                    break
                self._broadcast(chunk)
            if self.skip_event.is_set() or self.stop_event.is_set():
                ok = False
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            if ok:
                rc = proc.wait(timeout=5) if proc.poll() is None else proc.returncode
                if rc not in (0, None):
                    err = b""
                    if proc.stderr:
                        err = proc.stderr.read(4096)
                    self.set_error(f"FFmpeg завершился с ошибкой {rc}: {err.decode('utf-8', errors='replace')}")
                    ok = False
        except Exception as e:
            self.set_error(f"Ошибка фонового эфира: {e}")
            ok = False
        finally:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        return ok

    def _stream_speech_with_bed_to_broadcast(self, speech_path: Path) -> bool:
        bed_mode = str(self.cfg.get("speech_bed_mode", "generated") or "generated").lower().strip()
        if bed_mode == "off":
            return self._stream_path_plain_to_broadcast(speech_path, "speech")
        bed = self._pick_speech_bed() if bed_mode in {"file", "auto"} else None
        use_generated_bed = bed is None and bed_mode in {"generated", "auto"}
        if not bed and not use_generated_bed:
            return self._stream_path_plain_to_broadcast(speech_path, "speech")
        ffmpeg = str(self.cfg.get("ffmpeg_path", "ffmpeg"))
        if not executable_exists(ffmpeg):
            return self._stream_path_plain_to_broadcast(speech_path, "speech")
        duration = ffprobe_duration(self.cfg, speech_path) or 25.0
        duration = max(1.0, min(duration + 0.15, 90.0))
        bitrate = int(self.cfg.get("bitrate_kbps", 128))
        bed_vol = clamp(float(self.cfg.get("speech_bed_volume", 0.12)), 0.0, 1.0)
        voice_vol = clamp(float(self.cfg.get("speech_voice_volume", 1.0)), 0.1, 2.0)
        fade = clamp(float(self.cfg.get("speech_bed_fade_sec", 0.6)), 0.0, max(0.0, duration / 2.0 - 0.05))
        voice_filter = self._audio_filter(speech_path, "speech") + f",volume={voice_vol:.3f}"
        bed_chain = f"[0:a]aresample=44100,aformat=channel_layouts=stereo,volume={bed_vol:.3f},atrim=duration={duration:.3f}"
        if fade > 0.01:
            bed_chain += f",afade=t=in:st=0:d={fade:.3f},afade=t=out:st={max(0.0, duration - fade):.3f}:d={fade:.3f}"
        bed_chain += "[bed]"
        filter_complex = (
            f"[1:a]{voice_filter}[voice];"
            f"{bed_chain};"
            "[voice][bed]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.96[out]"
        )
        if use_generated_bed:
            bed_source = str(self.cfg.get("speech_generated_bed_filter", "anoisesrc=color=pink:sample_rate=44100:amplitude=0.018") or "anoisesrc=color=pink:sample_rate=44100:amplitude=0.018")
            input_args = ["-f", "lavfi", "-re", "-i", bed_source]
            bed_name = "мягкая сгенерированная радиоподложка"
        else:
            input_args = ["-stream_loop", "-1", "-i", str(bed)]
            bed_name = bed.name if bed else "фон"
        cmd = [
            ffmpeg,
            "-hide_banner", "-loglevel", "error",
            *input_args,
            "-re", "-i", str(speech_path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-ar", "44100", "-ac", "2", "-b:a", f"{bitrate}k",
            "-f", "mp3",
            "pipe:1",
        ]
        log(f"Ведущие идут на тихом фоне: {bed_name}")
        return self._run_ffmpeg_pipe_to_broadcast(cmd)

    def _stream_path_plain_to_broadcast(self, path: Path, kind: str, limit_sec: Optional[float] = None) -> bool:
        ffmpeg = str(self.cfg.get("ffmpeg_path", "ffmpeg"))
        if not executable_exists(ffmpeg):
            msg = "FFmpeg не найден. Для локального MP3-стрима нужен ffmpeg.exe."
            self.set_error(msg)
            log(msg)
            self._broadcast_silence(3)
            return False
        bitrate = int(self.cfg.get("bitrate_kbps", 128))
        filter_duration = limit_sec if limit_sec and limit_sec > 0 else None
        cmd = [
            ffmpeg,
            "-hide_banner", "-loglevel", "error",
            "-re",
            "-i", str(path),
        ]
        if limit_sec and limit_sec > 0:
            cmd += ["-t", f"{float(limit_sec):.3f}"]
        volume_filter = ""
        if kind == "speech":
            volume_filter = f",volume={clamp(float(self.cfg.get('speech_voice_volume', 1.45)), 0.1, 3.0):.3f}"
        elif kind == "music":
            volume_filter = f",volume={clamp(float(self.cfg.get('music_volume', 0.78)), 0.1, 1.5):.3f}"
        cmd += [
            "-vn",
            "-af", (self._audio_filter(path, kind, filter_duration) + volume_filter),
            "-ar", "44100", "-ac", "2", "-b:a", f"{bitrate}k",
            "-f", "mp3",
            "pipe:1",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ok = True
        try:
            if proc.stdout is None:
                raise RuntimeError("FFmpeg speech process started without stdout")
            while not self.stop_event.is_set():
                if self.skip_event.is_set():
                    ok = False
                    break
                chunk = proc.stdout.read(16 * 1024)
                if not chunk:
                    break
                self._broadcast(chunk)
            if self.skip_event.is_set() or self.stop_event.is_set():
                ok = False
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            if ok:
                rc = proc.wait(timeout=5) if proc.poll() is None else proc.returncode
                if rc not in (0, None):
                    err = b""
                    if proc.stderr:
                        err = proc.stderr.read(4096)
                    self.set_error(f"FFmpeg завершился с ошибкой {rc}: {err.decode('utf-8', errors='replace')}")
                    ok = False
        except Exception as e:
            self.set_error(f"Ошибка фонового эфира: {e}")
            ok = False
        finally:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        return ok

    def _stream_path_to_broadcast(self, path: Path, kind: str) -> bool:
        if kind == "speech" and self.cfg.get("speech_bed_enabled", True):
            return self._stream_speech_with_bed_to_broadcast(path)
        return self._stream_path_plain_to_broadcast(path, kind)


    def _start_live_prepare_timer_for_track(self, track: Track, planned_dj_after: bool) -> None:
        """Safety timer: if a live DJ insert is due after this song, start preparing
        at a configurable fraction of the song too. This makes the behaviour
        visible and robust: track-start preparation happens immediately, and the
        midpoint timer is a backup if the first trigger was skipped by config/race.
        """
        if not planned_dj_after or not self.cfg.get("async_prepare_dj", True):
            return
        duration = ffprobe_duration(self.cfg, track.path) or 0.0
        if duration <= 8.0:
            return
        fraction = clamp(float(self.cfg.get("live_prepare_trigger_fraction", 0.50) or 0.50), 0.05, 0.90)
        delay = max(3.0, duration * fraction)
        if self.cfg.get("live_prepare_trace_logs", True):
            log(f"Live: контрольная подготовка ведущих запланирована через {delay:.1f} сек. ({fraction:.0%} трека)")

        def timer() -> None:
            end_at = time.time() + delay
            while not self.stop_event.is_set() and time.time() < end_at:
                if self.skip_event.is_set():
                    return
                time.sleep(0.25)
            if self.stop_event.is_set() or self.skip_event.is_set():
                return
            # Если уже готово/готовится, start_prepare сам тихо не задублирует из-за lock.
            self.start_prepare_dj_for_after_track(track, reason="mid_track")

        threading.Thread(target=timer, name="LivePrepareMidTrack", daemon=True).start()

    def _stream_track_to_broadcast(self, track: Track, planned_dj_after: bool) -> bool:
        if planned_dj_after and self.cfg.get("live_prepare_at_track_start_when_due", True):
            self.start_prepare_dj_for_after_track(track, reason="track_start")
        self._start_live_prepare_timer_for_track(track, planned_dj_after)
        """Stream music. If a DJ block is planned right after it, trim the last second
        and fade at the trim point so speech can enter immediately instead of silence.
        This is a practical radio segue: not a full two-source crossfade yet, but it
        feels like the host catches the tail of the song instead of waiting in dead air.
        """
        limit_sec: Optional[float] = None
        if planned_dj_after and self.cfg.get("speech_takeover_enabled", True):
            duration = ffprobe_duration(self.cfg, track.path)
            takeover = max(0.0, float(self.cfg.get("speech_takeover_sec", 1.15)))
            min_track = max(1.0, float(self.cfg.get("speech_takeover_min_track_sec", 45.0)))
            if duration and takeover > 0.05 and duration > min_track + takeover:
                if self.cfg.get("speech_takeover_only_if_prepared", False):
                    with self.prepare_lock:
                        can_takeover = bool(
                            self.prepared_dj
                            and self.prepared_dj.previous_key == track_key(track)
                            and self.prepared_dj.next_key == track_key(self.peek_next_track())
                        )
                else:
                    can_takeover = True
                if can_takeover:
                    limit_sec = max(1.0, duration - takeover)
                    log(f"Radio segue: перехватываю хвост трека на {takeover:.1f} сек., чтобы ведущие вошли без тишины")
        return self._stream_path_plain_to_broadcast(track.path, "music", limit_sec=limit_sec)

    def _broadcast_silence(self, seconds: float) -> None:
        ffmpeg = str(self.cfg.get("ffmpeg_path", "ffmpeg"))
        if not executable_exists(ffmpeg):
            time.sleep(max(0.2, seconds))
            return
        bitrate = int(self.cfg.get("bitrate_kbps", 128))
        seconds = max(0.1, float(seconds))
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-re", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{seconds:.3f}",
            "-b:a", f"{bitrate}k", "-f", "mp3", "pipe:1",
        ]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.stdout is None:
                raise RuntimeError("FFmpeg planned item process started without stdout")
            while not self.stop_event.is_set():
                chunk = proc.stdout.read(16 * 1024)
                if not chunk:
                    break
                self._broadcast(chunk)
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            time.sleep(seconds)

    def _transition_pause(self) -> None:
        seconds = max(0.0, float(self.cfg.get("transition_silence_sec", 0.18)))
        if seconds > 0.01:
            self._broadcast_silence(seconds)

    def _air_dj_segment(self) -> bool:
        mp3 = self.make_dj_mp3()
        if not mp3 or self.stop_event.is_set():
            return False
        self.set_now("Ведущие в эфире", "speech")
        log("В эфире ведущие")
        ok = self._stream_path_to_broadcast(mp3, "speech")
        if ok:
            with self.state_lock:
                self.speech_blocks_played += 1
            self._stream_jingle_after_speech()
        self._transition_pause()
        return ok

    def _prepare_startup_intro_blocking(self) -> bool:
        """Синхронно готовит и сразу выводит стартовую вставку перед первой музыкой.

        Это основной режим для реалистичного радио: если включено приветствие,
        эфир сначала ждёт текст+TTS, отдаёт ведущих, и только потом запускает
        первый трек. Никаких поздних стартовых вставок между песнями.
        """
        next_track = self.peek_next_track()
        self.prepared_status = "готовлю стартовую вставку перед первой песней..."
        self.set_now("Готовлю стартовую вставку ведущих", "preparing")
        log("Готовлю стартовую вставку ведущих перед первой песней")
        seg = self.create_dj_segment(None, next_track, intro_allowed=True, mark_aired=False)
        if not seg or self.stop_event.is_set():
            self.prepared_status = "стартовую вставку подготовить не удалось, запускаю музыку"
            log("Стартовую вставку подготовить не удалось — запускаю музыку")
            return False
        self.prepared_status = "стартовая вставка взята в эфир перед первой песней"
        if next_track is not None and bool(self.cfg.get("startup_intro_reserve_first_track", True)):
            self.reserved_next_track = next_track
            log(f"Стартовая вставка объявила первый трек, резервирую его: {next_track.display_name}")
        self._record_host_text_as_aired(seg.text)
        self.set_now("Ведущие открывают эфир", "speech")
        log("В эфире стартовая вставка ведущих перед первой песней")
        ok = self._stream_path_to_broadcast(seg.mp3, "speech")
        if ok:
            with self.state_lock:
                self.speech_blocks_played += 1
            self._stream_jingle_after_speech()
        self._transition_pause()
        self.played_since_dj = 0
        self.next_dj_after = self._random_dj_gap()
        return bool(ok)

    def _prepare_startup_intro_nonblocking(self) -> None:
        """Готовит стартовую вставку, но не держит радио в вечной тишине."""
        next_track = self.peek_next_track()
        with self.prepare_lock:
            if self.prepare_thread and self.prepare_thread.is_alive():
                return
            self.prepared_dj = None
            self.prepared_status = "готовлю стартовую вставку ведущих..."

        def worker() -> None:
            try:
                self.set_now("Готовлю стартовую вставку ведущих", "preparing")
                log("Готовлю стартовую вставку ведущих")
                seg = self.create_dj_segment(None, next_track, intro_allowed=True, mark_aired=False)
                with self.prepare_lock:
                    self.prepared_dj = seg
                    self.prepared_status = "стартовая вставка подготовлена" if seg else "стартовую вставку подготовить не удалось"
                if seg:
                    log("Стартовая вставка ведущих подготовлена и ждёт эфира")
            except Exception as e:
                with self.prepare_lock:
                    self.prepared_status = f"ошибка стартовой вставки: {e}"
                log(f"Ошибка подготовки стартовой вставки: {e}")

        self.prepare_thread = threading.Thread(target=worker, name="PrepareStartupDJ", daemon=True)
        self.prepare_thread.start()

    def _take_startup_intro_if_ready(self) -> Optional[PreparedDJ]:
        with self.prepare_lock:
            seg = self.prepared_dj
            if not seg:
                return None
            if seg.previous_key != track_key(None):
                return None
            self.prepared_dj = None
            self.prepared_status = "стартовая вставка взята в эфир"
            return seg


    def _planned_dj_instruction(self, length: str) -> Tuple[str, str]:
        length = (length or "medium").lower()
        if length == "intro_long":
            return "long", "Длинное первое вступление: 8-12 предложений или 6-8 реплик. Обсуди текущее время, погоду если она есть, настроение ведущих, формат станции и атмосферу дня, аккуратно назови первый трек и только потом подведи к музыке. Это единственное полноценное открытие эфира."
        if length == "long":
            return "long", "Длинный подготовленный эфирный блок: 6-10 предложений, живой мини-разговор с завязкой, коротким наблюдением и мягкой подводкой к музыке."
        if length == "short":
            return "short", "Короткая подготовленная подводка: 1-2 предложения, без приветствия заново."
        return "medium", "Средний подготовленный эфирный блок: 3-5 предложений, живо и по делу, как на настоящем радио."

    def _plan_output_path(self) -> Path:
        out = Path(str(self.cfg.get("show_plan_output_file", "cache/show_plans/last_show_plan.json")))
        if not out.is_absolute():
            out = BASE_DIR / out
        out.parent.mkdir(parents=True, exist_ok=True)
        return out

    def _build_preplanned_show(self) -> List[PlannedItem]:
        """Builds and pre-renders a realistic radio show for a target duration.

        This mode intentionally waits for LM+TTS before music starts: the user can
        choose 15/60/120 minutes and let the smart model prepare text, greetings,
        time marks, news/weather and song links ahead of time.
        """
        target_sec = max(60.0, float(self.cfg.get("show_plan_duration_minutes", 15) or 15) * 60.0)
        generation_started_ts = time.time()
        self.show_plan_status = f"готовлю программу эфира минимум на {target_sec/60:.0f} мин: музыка + речь + переходы..."
        self.show_plan_progress = {"current": 0, "total": 100, "percent": 0, "detail": "подбираю музыкальную сетку"}
        self.set_now(self.show_plan_status, "planning")
        log(self.show_plan_status)

        # Select enough tracks first, so every speech block knows the real previous/next track.
        selected: List[Tuple[Track, float]] = []
        total_music = 0.0
        guard = 0
        while total_music < target_sec and guard < max(10, len(self.tracks) * 8):
            self.show_plan_progress = {"current": int(min(total_music, target_sec)), "total": int(target_sec), "percent": int(min(35, (total_music / max(1.0, target_sec)) * 35)), "detail": f"музыкальная сетка: {len(selected)} треков, {total_music/60:.1f}/{target_sec/60:.0f} мин"}
            guard += 1
            tr = self.pop_next_track()
            if not tr:
                break
            dur = ffprobe_duration(self.cfg, tr.path) or 210.0
            dur = max(30.0, float(dur))
            selected.append((tr, dur))
            total_music += dur
        if not selected:
            self.show_plan_status = "не удалось построить план: нет треков"
            return []

        items: List[PlannedItem] = []
        planned_elapsed = 0.0
        planned_speech_blocks = 0
        start_ts = time.time()
        announced_hours: set[int] = set()
        used_greetings: set[str] = set()

        def plan_time_text(elapsed: float) -> Tuple[str, str, str]:
            ts = time.localtime(start_ts + elapsed)
            main = f"{ts.tm_hour:02d}:{ts.tm_min:02d}, {RUS_WEEKDAYS[ts.tm_wday]}, {ts.tm_mday} {RUS_MONTHS[ts.tm_mon-1]} {ts.tm_year}"
            spoken = current_time_spoken_text_at_offset((start_ts + elapsed) - time.time())
            exact = ""
            if self.cfg.get("exact_hour_time_announce_enabled", True) and ts.tm_min <= int(self.cfg.get("exact_hour_window_minutes", 3) or 3):
                if ts.tm_hour not in announced_hours:
                    exact = exact_hour_announcement_text(self.cfg, ts)
                    announced_hours.add(ts.tm_hour)
            return main, spoken, exact

        def add_speech(prev_track: Optional[Track], next_track: Optional[Track], intro: bool, reason: str, elapsed: float) -> None:
            nonlocal planned_elapsed, planned_speech_blocks
            self.show_plan_status = f"генерирую и озвучиваю блок ведущих: {reason}"
            self.show_plan_progress = {"current": int(min(planned_elapsed, target_sec)), "total": int(target_sec), "percent": int(35 + min(55, (planned_elapsed / max(1.0, target_sec)) * 55)), "detail": self.show_plan_status}
            length = "intro_long" if (intro and self.cfg.get("show_plan_intro_long_opening", True)) else ("medium" if intro else ("long" if random.random() < float(self.cfg.get("show_plan_long_block_chance", 0.24) or 0.24) else random.choice(["short", "medium", "medium"])))
            length, instruction = self._planned_dj_instruction(length)
            ttext, spoken_ttext, exact = plan_time_text(elapsed)
            greeting = ""
            if self.cfg.get("listener_greetings_enabled", True) and (intro or random.random() < float(self.cfg.get("listener_greetings_chance", 0.22) or 0.22)):
                if self.cfg.get("show_plan_unique_greetings", True):
                    greeting = read_greeting_line_unique(self.cfg, used_greetings)
                else:
                    greeting = read_greeting_line(self.cfg)
            news = read_news_line(self.cfg) if self.cfg.get("news_enabled", True) and random.random() < float(self.cfg.get("news_chance", 0.35) or 0.35) else ""
            weather = self.weather.get_weather_text() if self.cfg.get("weather_enabled", False) and random.random() < float(self.cfg.get("weather_context_chance", 0.25) or 0.25) else ""
            overrides = {
                "time_text": ttext,
                "spoken_time_text": spoken_ttext,
                "exact_time_text": exact,
                "greeting_text": greeting,
                "news_text": news,
                "weather_text": weather,
                "dj_length": length,
                "dj_instruction": instruction,
                "dj_topic_label": reason,
                "speech_blocks_played": planned_speech_blocks,
                "plan_mode": "prepared_program",
                "planned_previous_track": prev_track.display_name if prev_track else "ещё ничего не играло",
                "planned_next_track": next_track.display_name if next_track else "следующий трек не выбран",
            }
            seg = self.create_dj_segment(prev_track, next_track, intro_allowed=intro, mark_aired=False, context_overrides=overrides)
            if not seg:
                return
            dur = ffprobe_duration(self.cfg, seg.mp3) or 25.0
            items.append(PlannedItem(kind="speech", path=seg.mp3, title="Ведущие в эфире", text=seg.text, duration_sec=float(dur)))
            planned_elapsed += float(dur)
            planned_speech_blocks += 1
            # Remember generated text while planning to reduce repetition in later planned blocks.
            self._record_host_text_as_aired(seg.text)

        if bool(self.cfg.get("show_plan_include_intro", True)):
            add_speech(None, selected[0][0], True, "открытие заранее подготовленного эфира и мягкая подводка к первому треку", planned_elapsed)

        min_gap = max(1, int(self.cfg.get("show_plan_min_tracks_between_speech", self.cfg.get("dj_every_n_tracks_min", 1)) or 1))
        max_gap = max(min_gap, int(self.cfg.get("show_plan_max_tracks_between_speech", self.cfg.get("dj_every_n_tracks_max", 3)) or 3))
        gap = random.randint(min_gap, max_gap)
        since_speech = 0
        for i, (tr, dur) in enumerate(selected):
            items.append(PlannedItem(kind="music", path=tr.path, title=tr.display_name, duration_sec=dur))
            planned_elapsed += dur
            since_speech += 1
            next_tr = selected[i + 1][0] if i + 1 < len(selected) else None
            if next_tr and since_speech >= gap:
                add_speech(tr, next_tr, False, "живой блок между песнями: музыка, время, новости, погода, настроение или привет слушателя", planned_elapsed)
                since_speech = 0
                gap = random.randint(min_gap, max_gap)

        self.show_plan_last_generation_sec = max(0.0, time.time() - generation_started_ts)
        meta = {
            "created_ts": int(time.time()),
            "target_minutes": float(self.cfg.get("show_plan_duration_minutes", 15) or 15),
            "estimated_seconds": planned_elapsed,
            "generation_seconds": self.show_plan_last_generation_sec,
            "music_plan": [
                {"title": tr.display_name, "path": str(tr.path), "duration_sec": dur}
                for tr, dur in selected
            ],
            "items": [
                {"kind": it.kind, "path": str(it.path), "title": it.title, "text": it.text, "duration_sec": it.duration_sec}
                for it in items
            ],
        }
        try:
            save_json(self._plan_output_path(), meta)
        except Exception as e:
            log(f"Не удалось сохранить план эфира: {e}")
        self.show_plan_status = f"программа готова: {len(items)} элементов, {planned_elapsed/60:.1f} мин; генерация заняла {self.show_plan_last_generation_sec/60:.1f} мин"
        self.show_plan_progress = {"current": int(planned_elapsed), "total": int(max(planned_elapsed, target_sec)), "percent": 100, "detail": "готово: музыка + речь + переходы"}
        log(self.show_plan_status)
        return items

    def _start_prepare_next_show_plan(self) -> None:
        if not self.cfg.get("show_plan_continuous_extend", True):
            return
        with self.plan_lock:
            if self.next_show_plan:
                return
            if self.plan_prepare_thread and self.plan_prepare_thread.is_alive():
                return
            def worker() -> None:
                try:
                    self.show_plan_status = "заранее готовлю следующий блок планового эфира..."
                    log(self.show_plan_status)
                    items = self._build_preplanned_show()
                    with self.plan_lock:
                        self.next_show_plan = items
                    if items:
                        self.show_plan_status = f"следующий блок готов: {len(items)} элементов"
                        self.show_plan_progress = {"current": len(items), "total": len(items), "percent": 100, "detail": self.show_plan_status}
                        log(self.show_plan_status)
                except Exception as e:
                    self.show_plan_status = f"следующий план не собрался: {e}"
                    log(self.show_plan_status)
            self.plan_prepare_thread = threading.Thread(target=worker, name="PrepareNextShowPlan", daemon=True)
            self.plan_prepare_thread.start()

    def start_track_profiles_build(self, limit: Optional[int] = None, force_existing: Optional[bool] = None) -> bool:
        """Build/update cache\track_profiles.json in background from the web panel."""
        if self.track_profile_thread and self.track_profile_thread.is_alive():
            return False

        def worker() -> None:
            try:
                force = bool(self.cfg.get("track_profiles_force_rebuild_existing", False) if force_existing is None else force_existing)
                self.track_profile_status = ("пересобираю все профили: веб-поиск, чтение страниц и проверка через LM Studio..." if force else "исследую только новые/неописанные треки через веб-поиск и LM Studio...")
                self.track_profile_progress = {"current": 0, "total": 0, "percent": 0, "detail": "запуск анализатора"}
                log(self.track_profile_status)
                script = BASE_DIR / "tools" / "build_track_profiles.py"
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUNBUFFERED"] = "1"
                # По умолчанию достраиваем только новые треки. Если включить галку
                # "пересобрать существующие", старые профили тоже обновятся.
                env["AI_TRUCK_RADIO_TRACK_PROFILE_FORCE"] = "1" if force else "0"
                if limit and int(limit) > 0:
                    env["AI_TRUCK_RADIO_TRACK_PROFILE_LIMIT"] = str(int(limit))
                cmd = [sys.executable, "-u", str(script)]
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(BASE_DIR),
                    env=env,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if proc.stdout is None:
                    raise RuntimeError("Track profile process started without stdout")
                tail: List[str] = []
                for raw_line in proc.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue
                    tail.append(line)
                    tail = tail[-50:]
                    log("TrackProfiles: " + line)
                    m = re.search(r"PROGRESS\s+(\d+)\s*/\s*(\d+)\s+(.*)$", line)
                    if m:
                        cur = int(m.group(1))
                        total = max(1, int(m.group(2)))
                        detail = m.group(3).strip()
                        self.track_profile_progress = {"current": cur, "total": total, "percent": int(cur * 100 / total), "detail": detail}
                        self.track_profile_status = f"описания музыки: {cur}/{total} — {detail}"
                    elif line.startswith("[TrackProfiles] analyzing:"):
                        self.track_profile_progress["detail"] = line.split(":", 1)[-1].strip()
                rc = proc.wait()
                if rc != 0:
                    self.track_profile_status = f"ошибка описаний треков: код {rc}"
                else:
                    self.track_profiles = load_track_profiles(self.cfg) if self.cfg.get("track_profiles_enabled", True) else {}
                    self.track_profile_progress = {"current": len(self.track_profiles), "total": len(self.track_profiles), "percent": 100 if self.track_profiles else 0, "detail": "готово"}
                    self.track_profile_status = f"описания треков готовы: {len(self.track_profiles)} записей"
                log(self.track_profile_status)
            except Exception as e:
                self.track_profile_status = f"ошибка описаний треков: {e}"
                self.track_profile_progress["detail"] = str(e)
                log(self.track_profile_status)

        self.track_profile_thread = threading.Thread(target=worker, name="BuildTrackProfiles", daemon=True)
        self.track_profile_thread.start()
        return True

    def start_show_plan_generation(self, duration_minutes: Optional[int] = None) -> bool:
        with self.plan_lock:
            if self.plan_prepare_thread and self.plan_prepare_thread.is_alive():
                return False
        if duration_minutes:
            self.cfg["show_plan_duration_minutes"] = int(duration_minutes)
        self.cfg["show_plan_enabled"] = True
        self.cfg["show_plan_rebuild_on_start"] = False
        save_json(CONFIG_PATH, self.cfg)
        def worker() -> None:
            try:
                items = self._build_preplanned_show()
                with self.plan_lock:
                    self.show_plan = items
                    self.show_plan_index = 0
                    self.next_show_plan = []
                if items:
                    self.show_plan_status = f"подготовленный эфир готов: {len(items)} элементов"
                    self.show_plan_progress = {"current": len(items), "total": len(items), "percent": 100, "detail": self.show_plan_status}
                else:
                    self.show_plan_status = "подготовленный эфир не удалось собрать"
                    self.show_plan_progress = {"current": 0, "total": 1, "percent": 0, "detail": self.show_plan_status}
            except Exception as e:
                self.show_plan_status = f"ошибка подготовки эфира: {e}"
                log(self.show_plan_status)
        with self.plan_lock:
            self.plan_prepare_thread = threading.Thread(target=worker, name="GenerateShowPlan", daemon=True)
            self.plan_prepare_thread.start()
        return True

    def _air_preplanned_show(self) -> None:
        if not self.show_plan or bool(self.cfg.get("show_plan_rebuild_on_start", True)):
            self.show_plan = self._build_preplanned_show()
            self.show_plan_index = 0
            self.cfg["show_plan_rebuild_on_start"] = False
        if not self.show_plan:
            self._broadcast_silence(3)
            return
        while not self.stop_event.is_set() and self.show_plan_index < len(self.show_plan):
            if not bool(self.cfg.get("show_plan_enabled", False)):
                self.show_plan_status = "плановый эфир остановлен: включён live-режим"
                return
            item = self.show_plan[self.show_plan_index]
            self.show_plan_index += 1
            total_plan_items = max(1, len(self.show_plan))
            remaining_items = max(0, len(self.show_plan) - self.show_plan_index)
            remaining_sec = sum(float(x.duration_sec or 0.0) for x in self.show_plan[self.show_plan_index:])
            gen_margin_min = max(float(self.cfg.get("show_plan_prepare_next_threshold_minutes", 4) or 4), (float(self.show_plan_last_generation_sec or 0.0) / 60.0) + 1.0)
            fraction_threshold = clamp(float(self.cfg.get("show_plan_prepare_next_fraction", 0.50) or 0.50), 0.10, 0.90)
            progress_fraction = self.show_plan_index / total_plan_items
            need_next_by_items = remaining_items <= int(self.cfg.get("show_plan_prepare_next_threshold_items", 3) or 3)
            need_next_by_time = remaining_sec <= gen_margin_min * 60.0
            need_next_by_fraction = progress_fraction >= fraction_threshold
            if need_next_by_items or need_next_by_time or need_next_by_fraction:
                reason = "по половине программы" if need_next_by_fraction else ("по времени до конца" if need_next_by_time else "по оставшимся элементам")
                log(f"Плановый эфир: запускаю подготовку следующего плана заранее ({reason}); прогресс {progress_fraction:.0%}, осталось {remaining_sec/60:.1f} мин")
                self._start_prepare_next_show_plan()
            if item.kind == "speech":
                self._record_host_text_as_aired(item.text)
                self.set_now(item.title or "Ведущие", "speech")
                log(f"Плановый эфир: ведущие ({self.show_plan_index}/{len(self.show_plan)})")
                ok = self._stream_path_to_broadcast(item.path, "speech")
                if ok:
                    with self.state_lock:
                        self.speech_blocks_played += 1
                    self._stream_jingle_after_speech()
                self._transition_pause()
            else:
                self.set_now(item.title, "music")
                log(f"Плановый эфир: играет {item.title}")
                # If the next planned item is speech, catch the tail of the song.
                next_is_speech = self.show_plan_index < len(self.show_plan) and self.show_plan[self.show_plan_index].kind == "speech"
                limit_sec = None
                if next_is_speech and self.cfg.get("speech_takeover_enabled", True):
                    takeover = max(0.0, float(self.cfg.get("speech_takeover_sec", 1.15) or 1.15))
                    if item.duration_sec > takeover + 45:
                        limit_sec = max(1.0, item.duration_sec - takeover)
                        log(f"Плановый segue: перехватываю хвост трека на {takeover:.1f} сек., чтобы ведущие вошли без тишины")
                self._stream_path_plain_to_broadcast(item.path, "music", limit_sec=limit_sec)
                with self.state_lock:
                    self.tracks_played += 1
                self._transition_pause()
        if self.show_plan_index >= len(self.show_plan):
            with self.plan_lock:
                if self.next_show_plan:
                    self.show_plan = self.next_show_plan
                    self.next_show_plan = []
                    self.show_plan_index = 0
                    self.show_plan_status = f"перешёл на следующий подготовленный блок: {len(self.show_plan)} элементов"
                    return
            if self.cfg.get("show_plan_continuous_extend", True):
                self.show_plan_status = "программа закончилась; следующий блок ещё готовится — держу эфир случайной музыкой"
                log(self.show_plan_status)
                self._start_prepare_next_show_plan()
                self.show_plan = []
                self.show_plan_index = 0
                if self.cfg.get("show_plan_fill_music_while_generating", True):
                    self._air_filler_music_until_next_plan()
            else:
                self.show_plan_status = "плановый эфир закончился"
                self.show_plan = []
                self.show_plan_index = 0
                if self.cfg.get("show_plan_live_after_exhausted", True):
                    self.cfg["show_plan_enabled"] = False

    def _air_filler_music_until_next_plan(self) -> None:
        """Keep the station alive with random music while the next prepared
        program is still rendering. Tracks popped here are removed from the
        normal queue, so the next generated plan will not immediately reuse them.
        """
        while not self.stop_event.is_set():
            with self.plan_lock:
                if self.next_show_plan:
                    self.show_plan = self.next_show_plan
                    self.next_show_plan = []
                    self.show_plan_index = 0
                    self.show_plan_status = f"следующий подготовленный блок принят в эфир: {len(self.show_plan)} элементов"
                    log(self.show_plan_status)
                    return
                still_generating = bool(self.plan_prepare_thread and self.plan_prepare_thread.is_alive())
            if not still_generating:
                # Попробуем запустить ещё раз; если не стартует, уйдём в live/тишину по настройкам.
                self._start_prepare_next_show_plan()
                with self.plan_lock:
                    still_generating = bool(self.plan_prepare_thread and self.plan_prepare_thread.is_alive())
                if not still_generating:
                    if self.cfg.get("show_plan_live_after_exhausted", True):
                        self.cfg["show_plan_enabled"] = False
                    return
            tr = self.pop_next_track()
            if not tr:
                self._broadcast_silence(2)
                continue
            self.set_now("Музыкальная пауза, пока готовится следующий блок: " + tr.display_name, "music")
            log("План готовится, временно играет музыка: " + tr.display_name)
            self._stream_track_to_broadcast(tr, planned_dj_after=False)
            self.previous_track = tr
            with self.state_lock:
                self.tracks_played += 1
            self._transition_pause()

    def _broadcast_loop(self) -> None:
        log("Фоновый радио-эфир запущен. Он идёт даже без слушателей.")
        while not self.stop_event.is_set():
            self.skip_event.clear()
            if not self.tracks:
                self.refresh_tracks()
            if not self.tracks:
                self.set_now(f"Нет музыки в {self.music_dir}", "empty")
                self._broadcast_silence(float(self.cfg.get("empty_radio_silence_seconds", 10)))
                continue

            if bool(self.cfg.get("show_plan_enabled", False)):
                self._air_preplanned_show()
                continue

            # Старт эфира: по умолчанию ждём текст+TTS и реально отдаём ведущих
            # перед первой песней. Неблокирующий режим оставлен только как ручной
            # аварийный вариант через config.json.
            if (not self.intro_played_or_skipped) and bool(self.cfg.get("intro_before_first_track", True)):
                self.intro_played_or_skipped = True
                if bool(self.cfg.get("startup_intro_blocking", True)):
                    self._prepare_startup_intro_blocking()
                else:
                    self._prepare_startup_intro_nonblocking()
                    wait_until = time.time() + max(0.0, float(self.cfg.get("startup_intro_wait_sec", 6)))
                    intro_seg: Optional[PreparedDJ] = None
                    while not self.stop_event.is_set() and time.time() < wait_until:
                        intro_seg = self._take_startup_intro_if_ready()
                        if intro_seg:
                            break
                        self._broadcast_silence(0.25)
                    if intro_seg and not self.stop_event.is_set():
                        self._record_host_text_as_aired(intro_seg.text)
                        self.set_now("Ведущие открывают эфир", "speech")
                        log("В эфире стартовая вставка ведущих")
                        intro_ok = self._stream_path_to_broadcast(intro_seg.mp3, "speech")
                        with self.state_lock:
                            self.speech_blocks_played += 1
                        if intro_ok:
                            self._stream_jingle_after_speech()
                        self._transition_pause()
                        self.played_since_dj = 0
                        self.next_dj_after = self._random_dj_gap()
                    else:
                        with self.prepare_lock:
                            if self.prepare_thread and self.prepare_thread.is_alive():
                                if str(self.cfg.get("startup_late_intro_policy", "discard")) == "first_break":
                                    self.prepared_status = "стартовая вставка ещё готовится и выйдет позже"
                                else:
                                    self.prepared_dj = None
                                    self.prepared_status = "стартовая вставка не успела, пропускаю её"
                            else:
                                self.prepared_status = "стартовая вставка не готова, запускаю музыку"
                        log("Стартовая вставка не успела подготовиться — запускаю музыку без ожидания")

            dj_due_before_music = self.should_insert_dj()
            if dj_due_before_music and not self.skip_event.is_set():
                self._air_dj_segment()
            elif self.previous_track is not None and not self.skip_event.is_set():
                self._maybe_air_station_id()

            if self.skip_event.is_set():
                self.skip_event.clear()

            track = self.pop_next_track()
            if not track:
                self._broadcast_silence(1)
                continue
            self.set_now(track.display_name, "music")
            log(f"Играет: {track.display_name}")
            # Пока песня звучит, готовим следующую речь, если по плану она нужна после этой песни.
            planned_dj_after = self.should_insert_after_current_track()
            if planned_dj_after:
                log(f"Live: после текущего трека должна быть речь, запускаю подготовку прямо в начале трека: {track.display_name}")
                self.start_prepare_dj_for_after_track(track, reason="track_start")
            else:
                self.start_prepare_dj_for_after_track(track, reason="before_music")
            finished = self._stream_track_to_broadcast(track, planned_dj_after)
            if finished:
                self.previous_track = track
                self.played_since_dj += 1
                with self.state_lock:
                    self.tracks_played += 1
                self._transition_pause()
            else:
                # skip не должен засчитываться как нормально доигранный трек.
                if self.skip_event.is_set():
                    self.skip_event.clear()
                    self._transition_pause()
        self._broadcast(None)
        log("Фоновый радио-эфир остановлен")

    def update_config(self, updates: Dict[str, Any]) -> None:
        before_cfg = dict(self.cfg)
        self.cfg.update(updates)
        self.cfg = normalize_config(self.cfg)
        save_json(CONFIG_PATH, self.cfg)
        changed_keys = {k for k in updates.keys() if before_cfg.get(k) != self.cfg.get(k)}
        # Клиенты зависят от актуального cfg; пересоздаём helper'ы.
        # TTS/OmniVoice пересоздаём только когда голосовые настройки реально изменились,
        # а не просто прилетели неизменными из формы.
        tts_affecting = {
            "tts_backend", "omnivoice_python", "omnivoice_model", "omnivoice_device", "omnivoice_mode",
            "omnivoice_steps", "omnivoice_speed", "omnivoice_ref_audio", "omnivoice_ref_text", "omnivoice_instruct",
            "omnivoice_persistent_worker", "omnivoice_prewarm_on_radio_start", "omnivoice_normalize_ru", "omnivoice_pronunciation_file",
            "qwen3_tts_python", "qwen3_tts_model_id", "qwen3_tts_device_map", "qwen3_tts_dtype",
            "piper_exe", "piper_python", "piper_voice", "piper_model", "sapi_voice_contains", "f5_tts_python",
        }
        self.lm = LMStudioClient(self.cfg)
        self.entertainment_agent = EntertainmentAgent(self.cfg, self.lm)
        if any(k in changed_keys for k in tts_affecting):
            try:
                self.tts.close()
            except Exception:
                pass
            self.tts = TTS(self.cfg)
        else:
            self.tts.cfg = self.cfg
        self.weather = WeatherClient(self.cfg)
        self.next_dj_after = self._random_dj_gap()
        with self.prepare_lock:
            self.prepared_dj = None
            self.prepared_status = "готовая live-вставка сброшена после изменения настроек"
        plan_affecting = {
            "strict_duo_intro_retry_attempts", "show_plan_duration_minutes", "show_plan_min_tracks_between_speech", "show_plan_max_tracks_between_speech",
            "show_plan_long_block_chance", "show_plan_include_intro", "show_plan_intro_long_opening",
            "station_style", "host_mode", "host_solo_name", "track_profiles_enabled", "track_profiles_file",
            "news_enabled", "weather_enabled", "listener_greetings_enabled", "lm_model", "lm_temperature", "lm_max_tokens",
            "tts_backend", "omnivoice_mode", "omnivoice_device", "omnivoice_python",
            "entertainment_model", "entertainment_agent_enabled", "entertainment_agent_results_per_query",
            "entertainment_agent_max_pages", "entertainment_agent_pages_per_topic",
            "entertainment_agent_min_page_chars", "entertainment_agent_page_chars",
            "entertainment_agent_total_evidence_chars", "entertainment_agent_factcheck_enabled",
            "entertainment_daily_cache_dir", "entertainment_pack_max_items",
        }
        if any(k in changed_keys for k in plan_affecting):
            self.show_plan = []
            self.show_plan_index = 0
            self.next_show_plan = []
            self.show_plan_status = "план сброшен: изменились параметры, влияющие на программу"
            self.entertainment_pack = {}
            self.entertainment_pack_date = ""
        self.set_error("")

    def status_snapshot(self) -> Dict[str, Any]:
        with self.state_lock:
            snap = {
                "app_version": APP_VERSION,
                "now_playing": self.now_playing,
                "current_kind": self.current_kind,
                "current_started_ts": self.current_started_ts,
                "last_host_text": self.last_host_text,
                "last_error": self.last_error,
                "used_lm_model": self.used_lm_model or str(self.cfg.get("lm_model", "local-model")),
                "total_clients": self.total_clients,
                "active_clients": self.active_clients,
                "tracks_played": self.tracks_played,
                "speech_blocks_played": self.speech_blocks_played,
                "skip_requested_by": self.skip_requested_by,
                "played_since_dj": self.played_since_dj,
                "next_dj_after": self.next_dj_after,
                "show_plan_status": self.show_plan_status,
                "show_plan_enabled": bool(self.cfg.get("show_plan_enabled", False)),
                "air_mode": "Плановый" if bool(self.cfg.get("show_plan_enabled", False)) else "Live",
                "show_plan_index": self.show_plan_index,
                "show_plan_items": len(self.show_plan),
                "show_plan_next_items": len(self.next_show_plan),
                "show_plan_generating": bool(self.plan_prepare_thread and self.plan_prepare_thread.is_alive()),
                "track_profile_status": self.track_profile_status,
                "track_profile_building": bool(self.track_profile_thread and self.track_profile_thread.is_alive()),
                "track_profile_count": len(self.track_profiles),
                "entertainment_status": self.entertainment_status,
                "entertainment_enabled": bool(self.cfg.get("entertainment_enabled", False)),
                "guest_ref_status": self._guest_ref_status(),
                "horoscope_index": self.horoscope_index,
                "pending_riddle": bool(self.pending_riddle),
                "track_profile_progress": dict(self.track_profile_progress),
                "show_plan_progress": dict(self.show_plan_progress),
                "show_plan_last_generation_sec": self.show_plan_last_generation_sec,
                "show_plan_preview": [
                    {
                        "idx": i + 1,
                        "kind": it.kind,
                        "title": it.title,
                        "duration_sec": round(float(it.duration_sec or 0.0), 1),
                        "text": (it.text or "")[:220],
                        "active": i == self.show_plan_index,
                    }
                    for i, it in enumerate(self.show_plan[:int(self.cfg.get("show_plan_preview_items", 80) or 80)])
                ],
                "radio_running": self.is_running(),
                "radio_starting": self.is_starting(),
            }
        with self.prepare_lock:
            snap["prepared_status"] = self.prepared_status
            snap["prepared_ready"] = bool(self.prepared_dj)
        snap.update({
            "music_count": len(self.tracks),
            "music_dir": str(self.music_dir),
            "ffmpeg_ok": executable_exists(str(self.cfg.get("ffmpeg_path", "ffmpeg"))),
            "ffprobe_ok": executable_exists(find_ffprobe(self.cfg)),
            "stream_url": f"http://{self.cfg['host']}:{int(self.cfg['port'])}/stream.mp3",
            "ets2_line": make_ets2_line(self.cfg),
            "station_style": str(self.cfg.get("station_style", "душевное радио")),
            "weather_city": str(self.cfg.get("weather_city", "")),
            "weather_enabled": bool(self.cfg.get("weather_enabled", False)),
            "news_enabled": bool(self.cfg.get("news_enabled", True)),
            "two_hosts_enabled": bool(self.cfg.get("two_hosts_enabled", True)),
            "host_mode": str(self.cfg.get("host_mode", "mostly_solo")),
            "fade_enabled": bool(self.cfg.get("fade_enabled", True)),
            "speech_bed_enabled": bool(self.cfg.get("speech_bed_enabled", True)),
            "hotkey_enabled": bool(self.cfg.get("hotkey_enabled", True)),
            "night_now": is_night_now(self.cfg),
            "time_text": current_time_text(),
        })
        return snap

