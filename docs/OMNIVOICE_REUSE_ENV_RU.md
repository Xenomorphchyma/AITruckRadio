# Использование уже установленного OmniVoice

OmniVoice должен жить прямо в корне проекта:

- `.venv_omnivoice`
- `.hf_cache`
- `.torch_cache`

Если эти папки уже есть, заново `scripts\omnivoice\install_omnivoice_windows.bat` запускать не нужно.

1. Запусти `use_existing_omnivoice_env.bat`.
2. Проверь `scripts\tests\test_tts_windows.bat`.
3. Запусти `run_radio.bat`.

Скрипт пропишет в `config.json`:

- `omnivoice_python` на `.venv_omnivoice\Scripts\python.exe`;
- `omnivoice_hf_home` на `.hf_cache`;
- `omnivoice_torch_home` на `.torch_cache`.
