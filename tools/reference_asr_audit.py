# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_truck_radio_app.config import load_config  # noqa: E402
from ai_truck_radio_app.ref_voice import (  # noqa: E402
    compare_reference_transcripts,
    transcribe_reference_audio,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare faster-whisper models on local reference voices")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["Systran/faster-whisper-small", "large-v3-turbo"],
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("audio", nargs="*", type=Path)
    args = parser.parse_args()

    audio_files = args.audio or sorted((ROOT / "references").glob("*_ref.wav"))
    base_cfg = load_config()
    results: list[dict[str, Any]] = []
    for model_name in args.models:
        for raw_audio in audio_files:
            audio_path = raw_audio if raw_audio.is_absolute() else ROOT / raw_audio
            text_path = audio_path.with_suffix(".txt")
            manual = text_path.read_text(encoding="utf-8-sig", errors="replace").strip() if text_path.is_file() else ""
            cfg = dict(base_cfg)
            cfg.update(
                {
                    "reference_asr_enabled": True,
                    "reference_asr_model": model_name,
                    "reference_asr_device": args.device,
                    "reference_asr_compute_type": args.compute_type,
                    "reference_asr_beam_size": args.beam_size,
                    "reference_asr_review_enabled": False,
                    "reference_asr_keep_model_loaded": False,
                }
            )
            started = time.perf_counter()
            transcript, ok, warning = transcribe_reference_audio(cfg, audio_path)
            elapsed = time.perf_counter() - started
            comparison = compare_reference_transcripts(manual, transcript) if manual and transcript else None
            results.append(
                {
                    "audio": str(audio_path),
                    "model": model_name,
                    "device": args.device,
                    "compute_type": args.compute_type,
                    "elapsed_sec": round(elapsed, 3),
                    "ok": ok,
                    "text": transcript,
                    "warning": warning,
                    "manual_similarity": round(comparison.similarity, 4) if comparison else None,
                    "requires_review": comparison.requires_review if comparison else None,
                }
            )
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    return 0 if all(item["ok"] for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
