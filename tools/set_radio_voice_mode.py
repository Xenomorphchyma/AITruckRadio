# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CONFIG = BASE / "config.json"

def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    cfg["tts_backend"] = "qwen3_tts"
    cfg["qwen3_tts_persistent_worker"] = True
    cfg["qwen3_tts_device_map"] = "cuda:0"
    cfg["qwen3_tts_dtype"] = "auto"
    cfg["qwen3_tts_attn_implementation"] = "sdpa"
    cfg["qwen3_tts_gpu_memory_limit_gb"] = 0
    cfg["qwen3_tts_cpu_memory_limit_gb"] = 48
    cfg["qwen3_tts_do_sample"] = True
    cfg["qwen3_tts_instruct_variants_enabled"] = True
    cfg["qwen3_tts_auto_retry_stable_gpu"] = True
    cfg["qwen3_tts_hide_known_warnings"] = True
    cfg["qwen3_tts_runtime_profile_version"] = 3

    defaults = {
        "Максим": {
            "host_voice_profile_version": 5,
            "qwen3_tts_speaker": "Ryan",
            "qwen3_tts_instruct": "Русский мужской FM-радиоведущий в прямом эфире. Уверенный баритон, энергичная дорожная подача, улыбка в голосе, яркие короткие акценты как на радио, темп бодрый, не аудиокнига, не спокойный диктор, не монотонно.",
            "qwen3_tts_instruct_variants": [
                "Русский мужской FM-радиоведущий в прямом эфире. Уверенный баритон, энергичная дорожная подача, улыбка в голосе, яркие короткие акценты как на радио, темп бодрый, не аудиокнига, не спокойный диктор, не монотонно.",
                "Мужской голос ночного дорожного FM: харизма ведущего, живые интонации, уверенная артикуляция, чуть быстрее обычной речи, рекламно-радиойная энергия без крика.",
                "Энергичный русский радиоведущий для трассы: бодрая подача, натуральные паузы, лёгкая ирония, эмоциональные акценты на названиях песен и дороге, ощущение живого эфира.",
            ],
        },
        "Ирина": {
            "host_voice_profile_version": 5,
            "qwen3_tts_speaker": "Serena",
            "qwen3_tts_instruct": "Русская женская FM-радиоведущая в прямом эфире. Явно женский светлый голос, бодрая современная подача, улыбка в голосе, живые короткие акценты, дружелюбная энергия, не аудиокнига, не спокойный диктор, заметно отличается от мужского ведущего.",
            "qwen3_tts_instruct_variants": [
                "Русская женская FM-радиоведущая в прямом эфире. Явно женский светлый голос, бодрая современная подача, улыбка в голосе, живые короткие акценты, дружелюбная энергия, не аудиокнига, не спокойный диктор, заметно отличается от мужского ведущего.",
                "Женская русская соведущая дорожного радио: светлый тембр, FM-энергия, лёгкий юмор, живые короткие акценты, чуть бодрее разговорного темпа, не робот и не аудиокнига.",
                "Женский голос ночного радио: явно женский, улыбка в голосе, уверенная радиоподача, аккуратная эмоциональность, ощущение настоящей станции, естественная энергичная речь.",
            ],
        },
    }

    hosts = cfg.setdefault("hosts", [])
    for name in ("Максим", "Ирина"):
        found = False
        for h in hosts:
            if isinstance(h, dict) and h.get("name") == name:
                h.update(defaults[name])
                found = True
                break
        if not found:
            new_host = {"name": name}
            new_host.update(defaults[name])
            hosts.append(new_host)

    shutil.rmtree(BASE / "cache" / "spoken", ignore_errors=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Qwen3-TTS radio voice mode enabled. Old cache\\spoken was cleared.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
