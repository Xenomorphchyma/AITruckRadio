# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_truck_radio_app.config import CONFIG_PATH, DEFAULT_CONFIG, deep_merge, log  # noqa: E402
from ai_truck_radio_app.tts import TTS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Render one test TTS phrase using AI Truck Radio config")
    ap.add_argument("--text", default="Максим: Проверка голоса радиоведущего. Если ты это слышишь, синтез речи работает.")
    ap.add_argument("--backend", default="", help="override tts_backend: qwen3_tts, silero, piper, sapi")
    ap.add_argument("--out", default="cache/test_tts_output.mp3")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH, help="config to read without modifying it")
    ap.add_argument("--allow-fallback", action="store_true", help="also exercise the configured fallback chain")
    args = ap.parse_args()

    # The diagnostic must never migrate/rewrite config.json or succeed from a
    # previously cached phrase. App startup owns configuration migrations.
    try:
        loaded = json.loads(args.config.read_text(encoding="utf-8")) if args.config.exists() else {}
        if not isinstance(loaded, dict):
            raise ValueError("configuration must be a JSON object")
    except (OSError, ValueError) as exc:
        log(f"TEST TTS FAILED: не удалось прочитать настройки: {exc}")
        return 2
    cfg = deep_merge(copy.deepcopy(DEFAULT_CONFIG), loaded)
    if args.backend:
        cfg["tts_backend"] = args.backend
    cfg["tts_debug_log"] = True
    cfg["tts_fallback_enabled"] = bool(args.allow_fallback)

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    log(f"TEST TTS backend={cfg.get('tts_backend')} fallback={args.allow_fallback} text={args.text}")
    with tempfile.TemporaryDirectory(prefix="ai-truck-radio-tts-test-") as cache:
        cfg["cache_dir"] = cache
        tts = TTS(cfg)
        try:
            mp3 = tts.get_or_create_dialogue_mp3(args.text, cfg.get("hosts") or [])
            if not mp3 or not Path(mp3).exists():
                log("TEST TTS FAILED: mp3 не создан")
                return 2
            shutil.copyfile(mp3, out)
        finally:
            tts.close()
    log(f"TEST TTS OK: {out} ({out.stat().st_size} bytes)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
