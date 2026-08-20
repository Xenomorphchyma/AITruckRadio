# AI Truck Radio — практическое руководство

Локальное музыкальное радио для Windows: непрерывный MP3-поток, ведущие через LM Studio, OmniVoice/SAPI/Piper, рубрики и веб-панель управления. Сервер и эфир работают локально; публикация в интернет в базовую конфигурацию не входит.

Подробная идея проекта, основные принципы и обзор возможностей находятся в [главном README](README.md). Этот документ сосредоточен на локальной установке, настройке моделей и проверках.

## Что потребуется

- Windows 10/11 и Python 3.13. Именно Python 3.13 проверяется в CI; `setup_windows.bat` сначала ищет его, затем пробует доступный Python 3.
- `ffmpeg.exe` и `ffprobe.exe` в `PATH` либо путь к ним в панели/`config.json`.
- Музыкальные файлы в `music/` (`mp3`, `flac`, `wav`, `ogg`, `m4a`, `aac`, `opus`, `wma`).
- LM Studio с включённым Local Server на `http://127.0.0.1:1234/v1`, если нужны генерируемые реплики и исследования треков. Без LM Studio используются запасные реплики.
- Для основного нейроголоса — отдельное окружение OmniVoice. Без него Windows SAPI остаётся доступным fallback; Piper можно установить отдельно.

## Быстрый старт

1. Создай основное окружение:

   ```bat
   setup_windows.bat
   ```

2. Положи музыку в `music/`. При необходимости запусти LM Studio Local Server.
3. Запусти панель:

   ```bat
   run_radio.bat
   ```

4. Открой [http://127.0.0.1:8765/](http://127.0.0.1:8765/) и нажми **Включить радио**.

`run_radio.bat` запускает сервер управления, но по умолчанию не включает сам эфир. Остановить сервер можно через `Ctrl+C`. При первом запуске `config.json` создаётся автоматически из встроенных defaults; `config.example.json` — актуальный безопасный пример для сравнения, а не файл с пользовательскими секретами.

Локальный поток доступен по адресу `http://127.0.0.1:8765/stream.mp3`.

## Панель и режимы эфира

В панели собраны пульт старта/остановки и skip, встроенный плеер, состояние LM/TTS, редактор станции и ведущих, загрузка reference-голоса, настройки рубрик, построение описаний треков и диагностика.

- **Live** готовит реплики ведущих по ходу эфира между музыкальными треками. Этот режим быстрее стартует, но зависит от текущей скорости LM Studio и TTS.
- **Плановый** заранее собирает программу из музыки и озвученных блоков. План можно сгенерировать и проверить в панели до включения эфира; во время работы режим разрешено переключить обратно на Live.

Для автоматической расшифровки загружаемого reference-аудио установи необязательную ASR-зависимость:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-optional-asr.txt
```

Ручной reference-текст работает и без ASR-пакета.

Для специализированного распознавания русской речи через GigaAM установи отдельный backend:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-optional-gigaam.txt
```

В загрузчике reference-голоса можно независимо выбрать Whisper или GigaAM и уровень качества. GigaAM `Быстро` использует `v3_e2e_ctc`, `Баланс` — `v3_e2e_rnnt`, а `Максимальная точность` сравнивает результаты RNNT и CTC. Модели загружаются только для обработки файла и по умолчанию освобождают память после неё.

У Whisper уровни соответствуют реальным моделям: `Быстро` — `faster-whisper-small`, `Баланс` — `large-v3-turbo`, `Максимальная точность` — полная `large-v3`. После обработки модель по умолчанию выгружается, поэтому она не занимает память LM Studio или OmniVoice во время эфира. Все ASR-веса сохраняются на диске в `.hf_cache/asr` и повторно не скачиваются.

Сравнить модели на локальных reference-файлах без LM Studio:

```bat
.venv\Scripts\python.exe tools\reference_asr_audit.py
```

## Голоса

OmniVoice устанавливается в отдельное окружение, чтобы его тяжёлые зависимости не смешивались с основным приложением:

```bat
scripts\omnivoice\install_omnivoice_windows.bat
scripts\omnivoice\verify_omnivoice_windows.bat
scripts\omnivoice\set_omnivoice_mode.bat
scripts\tests\test_tts_windows.bat
```

Reference-аудио и текст хранятся в `references/`. Лёгкий Piper fallback устанавливается через `scripts\maintenance\install_piper_windows.bat`.

## Проверки для разработки

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m compileall -q ai_truck_radio.py ai_truck_radio_app tools tests
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m pytest -q
```

Автономный корпус разговоров находится в `tests/dialogue_corpus/radio_dialogues.json` и запускается отдельно так:

```bat
.venv\Scripts\python.exe -m pytest tests\test_dialogue_quality.py -q
```

Эта проверка не запускает LM Studio, сеть или TTS: детерминированный fake-клиент прогоняет solo/duo, Live и плановый эфир, музыку, погоду, новости, приветы, гороскоп, загадки, игру с неправильными ответами, гостя, очистку сломанного ответа и fallback. Контракт отдельно проверяет роли ведущих, порядок реплик, TTS-безопасность, контекст и неподтверждённые ссылки на источники.

CI дополнительно запускает Pyright, Bandit и поиск случайно добавленных секретов. Покрытие тестами собирается как диагностическая метрика без хрупкого обязательного процента.

## Важные каталоги

- `music/` — музыка;
- `references/` — reference-голоса;
- `data/news.txt` и `data/greetings.txt` — локальные эфирные материалы;
- `cache/track_profiles.json` — проверенные описания треков;
- `beds/`, `jingles/`, `station_ids/` — звуковое оформление;
- `prompts/pronunciation_ru.tsv` — словарь произношения.

Локальные окружения, модели, музыка, reference-файлы, `config.json` и runtime-кэши исключены из Git через `.gitignore`.

## Документация

- [PROJECT_GUIDE_RU.md](PROJECT_GUIDE_RU.md) — подробная карта возможностей и настроек;
- [docs/ARCHITECTURE_RU.md](docs/ARCHITECTURE_RU.md) — модули и потоки данных;
- [docs/OMNIVOICE_CORE_RU.md](docs/OMNIVOICE_CORE_RU.md) — установка и диагностика OmniVoice;
- [docs/ENTERTAINMENT_AGENT_RU.md](docs/ENTERTAINMENT_AGENT_RU.md) — рубрики и защита от повторов;
- [docs/TRACK_PROFILES_RU.md](docs/TRACK_PROFILES_RU.md) — исследование музыки;
- [docs/PROJECT_GAPS_RU.md](docs/PROJECT_GAPS_RU.md) — известные ограничения.

## Лицензия

Код AI Truck Radio распространяется по лицензии [MIT](LICENSE). Пользователь самостоятельно отвечает за права на добавленные музыку, голоса, модели и интернет-материалы.
