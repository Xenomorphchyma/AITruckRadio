# -*- coding: utf-8 -*-
"""
AI Truck Radio
Локальное бесплатное нейро-радио с живыми ведущими, музыкой, рубриками и веб-панелью.

Главное:
- Эфир идёт в фоне, даже если слушателей нет.
- Игра/браузер подключаются к уже текущему эфиру, а не запускают плейлист заново.
- Веб-панель сама не стартует поток, пока пользователь не нажал кнопку включения радио.
- Есть плавные fade-in/fade-out через FFmpeg.
- Есть ведущие, новости из файла, время/дата, погода через Open-Meteo/wttr fallback, плановый и live-эфир.
- Стиль станции можно менять из веб-панели.
- Есть кнопка Next в панели и глобальный хоткей Ctrl+Alt+N на Windows.

Нужно:
- ffmpeg.exe: в PATH или путь в config.json.
- LM Studio Local Server: http://127.0.0.1:1234/v1.
- OmniVoice как основной TTS: scripts/omnivoice/install_omnivoice_windows.bat.
- Piper опционально как лёгкий fallback: scripts/maintenance/install_piper_windows.bat.
"""

from __future__ import annotations

import argparse
import os
import signal
import threading
from http.server import ThreadingHTTPServer
from typing import Any, Dict

from ai_truck_radio_app.engine import RadioEngine
from ai_truck_radio_app.server import make_ets2_line, make_handler
from ai_truck_radio_app.config import (
    APP_NAME,
    APP_VERSION,
    BASE_DIR,
    executable_exists,
    find_ffprobe,
    load_config,
    log,
    rel_path,
)


def print_startup_help(cfg: Dict[str, Any], engine: RadioEngine) -> None:
    log(f"{APP_NAME} {APP_VERSION}")
    log(f"Папка проекта: {BASE_DIR}")
    log(f"Папка музыки: {engine.music_dir}")
    log(f"Найдено треков: {len(engine.tracks)}")
    ffmpeg = str(cfg.get("ffmpeg_path", "ffmpeg"))
    log(f"FFmpeg: {'OK' if executable_exists(ffmpeg) else 'НЕ НАЙДЕН'} ({ffmpeg})")
    ffprobe = find_ffprobe(cfg)
    log(f"FFprobe: {'OK' if executable_exists(ffprobe) else 'НЕ НАЙДЕН'} ({ffprobe})")
    if cfg.get("lm_enabled", True):
        models = engine.lm.list_models()
        if models:
            log(f"LM Studio виден. Модели: {', '.join(models[:5])}")
            log(f"Используемая модель: {engine.lm.pick_model()}")
        else:
            log("LM Studio пока не виден на /v1/models. Включи Local Server в LM Studio или будет fallback.")
    log("Строка для ETS2 live_streams.sii:")
    print(make_ets2_line(cfg), flush=True)
    log(f"Веб-панель: http://{cfg['host']}:{int(cfg['port'])}/")
    log(f"Стрим:     http://{cfg['host']}:{int(cfg['port'])}/stream.mp3")
    log("Next hotkey: Ctrl+Alt+N (если включено и Windows разрешила зарегистрировать хоткей)")


def start_hotkey_thread(engine: RadioEngine) -> None:
    if os.name != "nt" or not engine.cfg.get("hotkey_enabled", True):
        return
    def worker() -> None:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            MOD_ALT = 0x0001
            MOD_CONTROL = 0x0002
            MOD_NOREPEAT = 0x4000
            VK_N = ord('N')
            hotkey_id = 1001
            if not user32.RegisterHotKey(None, hotkey_id, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_N):
                log("Не удалось зарегистрировать Ctrl+Alt+N. Возможно, хоткей уже занят.")
                return
            log("Глобальный хоткей Ctrl+Alt+N включён")
            msg = wintypes.MSG()
            while not engine.stop_event.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == 0x0312 and msg.wParam == hotkey_id:
                    engine.request_skip("Ctrl+Alt+N")
            user32.UnregisterHotKey(None, hotkey_id)
        except Exception as e:
            log(f"Хоткей не запустился: {e}")
    threading.Thread(target=worker, name="HotkeyThread", daemon=True).start()


def ensure_data_files() -> None:
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    news = data_dir / "news.txt"
    if not news.exists():
        news.write_text(
            "# Каждая непустая строка — отдельная новость/заметка для эфира. Можно писать своё.\n"
            "На стоянке у виртуальной трассы сегодня обещают крепкий кофе и свободные места для тех, кто доехал без штрафов.\n"
            "Станция учится не просто включать музыку, а вести эфир как настоящее дорожное радио.\n",
            encoding="utf-8",
        )
    greetings = data_dir / "greetings.txt"
    if not greetings.exists():
        greetings.write_text(
            "# Каждая непустая строка — отдельный привет/пожелание для эфира.\n"
            "Привет всем, кто идёт ночным рейсом и не забывает смотреть в зеркала перед перестроением.\n"
            "Передайте привет Андрею: ровной трассы, спокойных развязок и без штрафов на маршруте.\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Truck Radio")
    parser.add_argument("--no-pregen", action="store_true", help="не создавать вставки ведущего на старте")
    parser.add_argument("--print-ets2-line", action="store_true", help="только вывести строку для live_streams.sii")
    args = parser.parse_args()

    cfg = load_config()
    rel_path(cfg, "music_dir").mkdir(parents=True, exist_ok=True)
    rel_path(cfg, "cache_dir").mkdir(parents=True, exist_ok=True)
    ensure_data_files()

    if args.print_ets2_line:
        print(make_ets2_line(cfg))
        return 0

    engine = RadioEngine(cfg)
    print_startup_help(cfg, engine)

    if not args.no_pregen:
        try:
            engine.pre_generate()
        except Exception as e:
            log(f"Предгенерация пропущена из-за ошибки: {e}")

    server = ThreadingHTTPServer((str(cfg["host"]), int(cfg["port"])), make_handler(engine, cfg, start_hotkey_thread))
    should_stop = threading.Event()

    if cfg.get("radio_autostart", False):
        engine.start(clean_generated=bool(cfg.get("clean_generated_on_start", True)))
    else:
        log("Автозапуск радио выключен. Включи эфир из веб-панели.")
        engine.set_now("Радио остановлено — включи из панели", "stopped")
    start_hotkey_thread(engine)

    def _stop(signum=None, frame=None):
        if not should_stop.is_set():
            should_stop.set()
            log("Остановка сервера...")
            engine.stop()
            threading.Thread(target=server.shutdown, daemon=True).start()

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except Exception:
        pass

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        engine.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
