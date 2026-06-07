# Архитектура проекта

Главная точка входа остаётся `ai_truck_radio.py`. Сейчас это тонкий bootstrap: аргументы CLI, загрузка конфига, создание `RadioEngine`, запуск HTTP-сервера и корректная остановка.

Вынесенные модули:

- `ai_truck_radio_app/config.py` — константы, `DEFAULT_CONFIG`, миграции `config.json`, работа с путями и ffmpeg helpers.
- `ai_truck_radio_app/context.py` — погода, время, стиль эфира, новости и приветы из `data/`.
- `ai_truck_radio_app/engine.py` — основной `RadioEngine`: эфирный цикл, плановый эфир, рубрики, подготовка ведущих, стриминг аудио подписчикам.
- `ai_truck_radio_app/lmstudio.py` — клиент LM Studio и генерация текста ведущих.
- `ai_truck_radio_app/panel.py` — HTML/CSS/JS веб-панели.
- `ai_truck_radio_app/server.py` — HTTP API, `/stream.mp3`, `/status.json`, сохранение настроек из панели.
- `ai_truck_radio_app/text_processing.py` — чистка текста, парсинг диалогов ведущих, защита от ремарок и контекстных ошибок.
- `ai_truck_radio_app/tracks.py` — модели треков, парсинг имён файлов, сканирование музыки, профили треков, ffprobe duration.
- `ai_truck_radio_app/entertainment_agent.py` — поиск, сборка и фактчек гороскопов, загадок и игровых вопросов.
- `ai_truck_radio_app/entertainment_history.py` — постоянный журнал использованных рубрик и защита от повторов.
- `ai_truck_radio_app/web_research.py` — общий безопасный поиск и чтение публичных HTML-страниц.
- `ai_truck_radio_app/tts.py` — TTS orchestration, OmniVoice/Qwen workers, Piper/SAPI/fallback backend-и.

Следующий разумный этап распила — разделить `RadioEngine` на эфирный цикл, плановый эфир и рубрики/игры.
