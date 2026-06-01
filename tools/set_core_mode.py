from __future__ import annotations
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CFG = BASE / 'config.json'

CORE_UPDATES = {
    'tts_backend': 'piper',
    'tts_fallback_chain': ['piper', 'sapi'],
    'show_experimental_tts_backends': False,
    'qwen3_tts_persistent_worker': False,
    'qwen3_tts_gpu_memory_limit_gb': 0,
    'qwen3_tts_device_map': 'cuda:0',
    'weather_enabled': False,
}

if CFG.exists():
    try:
        data = json.loads(CFG.read_text(encoding='utf-8-sig'))
    except Exception as e:
        print(f'ERROR: cannot read config.json: {e}')
        raise SystemExit(1)
else:
    data = {}

for k, v in CORE_UPDATES.items():
    data[k] = v

# Keep LM Studio for text generation; only TTS is reset.
data.setdefault('lm_enabled', True)
data.setdefault('lm_base_url', 'http://127.0.0.1:1234/v1')
data.setdefault('lm_model', 'local-model')

CFG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('Core mode enabled: TTS=piper, fallback=piper/sapi, experimental TTS hidden.')
