"""Run one non-mutating GigaAM transcription against a local reference file."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from ai_truck_radio_app.ref_voice import transcribe_reference_audio


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", nargs="?", default="references/maxim_ref.wav")
    parser.add_argument("--level", choices=["fast", "balanced", "maximum"], default="fast")
    args = parser.parse_args()
    config_path = BASE_DIR / "config.json"
    project_cfg = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
    text, ok, warning = transcribe_reference_audio(
        {
            **project_cfg,
            "reference_asr_enabled": True,
            "reference_asr_language": "ru",
            "reference_asr_device": "cpu",
            "reference_asr_cache_dir": ".hf_cache/asr",
            "reference_asr_keep_model_loaded": False,
        },
        Path(args.audio),
        backend="gigaam",
        level=args.level,
    )
    print(f"ok={ok}")
    print(f"text={text}")
    print(f"warning={warning}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
