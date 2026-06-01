# OmniVoice Core

Основной голосовой backend проекта — OmniVoice.
Piper оставлен как лёгкий fallback, SAPI — аварийный fallback Windows.
Qwen3-TTS, F5-TTS и Silero больше не являются рабочими кандидатами проекта.

## Структура

OmniVoice живёт прямо в корне проекта:

- `.venv_omnivoice` — отдельное Python-окружение OmniVoice;
- `.hf_cache` — кэш Hugging Face;
- `.torch_cache` — кэш Torch;
- `tools\omnivoice_render.py` и `tools\omnivoice_worker.py` — рабочие helper-скрипты радио.

`omnivoice_test` больше не используется как отдельный проект.

## Установка и проверка

1. Останови `run_radio.bat`, если он запущен.
2. Запусти `scripts\omnivoice\install_omnivoice_windows.bat`.
3. Запусти `scripts\omnivoice\set_omnivoice_mode.bat`.
4. Положи reference voices:
   - `references\maxim_ref.wav`
   - `references\maxim_ref.txt`
   - `references\irina_ref.wav`
   - `references\irina_ref.txt`
5. Запусти `scripts\tests\test_tts_windows.bat`.
6. Если тест нормальный — запускай `run_radio.bat`.

## Reference voice

Лучше всего:
- 3–10 секунд;
- один человек;
- без музыки и второго голоса;
- `.txt` совпадает с `.wav` буквально.

Не используйте узнаваемый голос реального человека без разрешения.

## Ударения

Файл словаря:

`prompts\pronunciation_ru.tsv`

Примеры:

- `тест го́лоса` — ударение на О, один голос;
- `проверяем голоса́` — ударение на А, много голосов.

LLM теперь тоже получает инструкцию ставить ударения акутом в неоднозначных словах.

## Если модель долго качается

Можно запустить:

- `scripts\omnivoice\install_hf_acceleration_windows.bat`
- `scripts\omnivoice\login_huggingface_windows.bat` — необязательно, но может помочь с лимитами HF;
- `scripts\omnivoice\preload_omnivoice_model.bat`
