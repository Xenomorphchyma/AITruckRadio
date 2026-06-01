# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_truck_radio_app.config import load_config, log  # noqa: E402
from ai_truck_radio_app.tts import TTS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Render one test TTS phrase using AI Truck Radio config")
    ap.add_argument("--text", default="Максим: Проверка голоса радиоведущего. Если ты это слышишь, синтез речи работает.")
    ap.add_argument("--backend", default="", help="override tts_backend: qwen3_tts, silero, piper, sapi")
    ap.add_argument("--out", default="cache/test_tts_output.mp3")
    args = ap.parse_args()

    cfg = load_config()
    if args.backend:
        cfg["tts_backend"] = args.backend
    cfg["tts_debug_log"] = True

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    log(f"TEST TTS backend={cfg.get('tts_backend')} text={args.text}")
    tts = TTS(cfg)
    mp3 = tts.get_or_create_dialogue_mp3(args.text, cfg.get("hosts") or [])
    if not mp3 or not Path(mp3).exists():
        log("TEST TTS FAILED: mp3 не создан")
        return 2
    shutil.copyfile(mp3, out)
    log(f"TEST TTS OK: {out} ({out.stat().st_size} bytes)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
