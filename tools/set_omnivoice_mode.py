from __future__ import annotations
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CFG = BASE / 'config.json'

if CFG.exists():
    try:
        data = json.loads(CFG.read_text(encoding='utf-8-sig'))
    except Exception as e:
        print(f'ERROR: cannot read config.json: {e}')
        raise SystemExit(1)
else:
    data = {}

data.update({
    'tts_backend': 'omnivoice',
    'tts_fallback_chain': ['piper', 'sapi'],
    'show_experimental_tts_backends': False,
    'omnivoice_core_profile_version': 1,
    'omnivoice_python': '.venv_omnivoice\\Scripts\\python.exe',
    'omnivoice_model': 'k2-fsa/OmniVoice',
    'omnivoice_device': 'cuda:0',
    'omnivoice_mode': 'clone',
    'omnivoice_steps': 16,
    'omnivoice_speed': 1.0,
    'omnivoice_tail_silence_ms': 260,
    'omnivoice_persistent_worker': True,
    'omnivoice_pronunciation_file': 'prompts/pronunciation_ru.tsv',
    'omnivoice_normalize_ru': True,
    'tts_fallback_enabled': True,
})

hosts = data.get('hosts')
if not isinstance(hosts, list) or len(hosts) < 2:
    hosts = [
        {'name': 'Максим', 'aliases': ['Макс']},
        {'name': 'Ирина', 'aliases': ['Лина', 'Ира']},
    ]
for host in hosts:
    if not isinstance(host, dict):
        continue
    name = str(host.get('name', '')).lower()
    if 'ирин' in name or 'лина' in name or 'ира' in name:
        host['omnivoice_ref_audio'] = host.get('omnivoice_ref_audio') or 'references/irina_ref.wav'
        host['omnivoice_ref_text'] = host.get('omnivoice_ref_text') or ''
        host['omnivoice_instruct'] = 'female, middle-aged, russian accent, moderate pitch'
    else:
        host['omnivoice_ref_audio'] = host.get('omnivoice_ref_audio') or 'references/maxim_ref.wav'
        host['omnivoice_ref_text'] = host.get('omnivoice_ref_text') or ''
        host['omnivoice_instruct'] = 'male, middle-aged, russian accent, low pitch'

data['hosts'] = hosts
CFG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('OmniVoice mode enabled: TTS=omnivoice, persistent worker ON, fallback=piper/sapi.')
print('Put references in references\\maxim_ref.wav/.txt and references\\irina_ref.wav/.txt for clone mode.')
