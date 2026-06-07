# AI Truck Radio

Локальное нейро-радио с веб-панелью, музыкой, ведущими, плановым/live-эфиром, рубриками и OmniVoice.

Основной запуск:

```bat
run_radio.bat
```

После запуска открой:

```text
http://127.0.0.1:8765/
```

Радио не стартует само: включай эфир из панели.

Для установки/проверки OmniVoice смотри:

```text
scripts\omnivoice\install_omnivoice_windows.bat
use_existing_omnivoice_env.bat
```

Музыка лежит в `music/`, reference-голоса — в `references/`, описания треков — в `cache/track_profiles.json`.

Для GitHub локальные окружения, модели, музыка, reference-голоса, `config.json`, runtime-кэши и архивы релизов исключены через `.gitignore`.

Документация:

- карта модулей: `docs/ARCHITECTURE_RU.md`;
- агент рубрик и защита от повторов: `docs/ENTERTAINMENT_AGENT_RU.md`;
- текущие технические пробелы: `docs/PROJECT_GAPS_RU.md`;
- исследование треков: `docs/TRACK_PROFILES_RU.md`.
