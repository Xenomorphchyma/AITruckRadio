from __future__ import annotations
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CFG = BASE / 'config.json'

candidates = [
    BASE / '.venv_omnivoice' / 'Scripts' / 'python.exe',
]
py = None
for p in candidates:
    if p.exists():
        py = p
        break
if py is None:
    print('ERROR: root OmniVoice venv not found.')
    print('Expected for example:')
    print(r'  D:\Projects\AITruckRadio\.venv_omnivoice\Scripts\python.exe')
    raise SystemExit(1)

test_root = py.parents[2]
# py = .../.venv_omnivoice/Scripts/python.exe -> parents[2] = project root
hf_home = test_root / '.hf_cache'
torch_home = test_root / '.torch_cache'

if CFG.exists():
    try:
        data = json.loads(CFG.read_text(encoding='utf-8-sig'))
    except Exception as e:
        print(f'ERROR: cannot read config.json: {e}')
        raise SystemExit(1)
else:
    data = {}

def rel_or_abs(p: Path) -> str:
    try:
        return str(p.relative_to(BASE)).replace('/', '\\')
    except Exception:
        return str(p)

data.update({
    'tts_backend': 'omnivoice',
    'tts_fallback_chain': ['piper', 'sapi'],
    'show_experimental_tts_backends': False,
    'omnivoice_core_profile_version': 2,
    'radio_director_profile_version': 1,
    'lm_append_no_think': False,
    'lm_max_tokens': max(int(data.get('lm_max_tokens', 0) or 0), 760),
    'lm_timeout_sec': max(int(data.get('lm_timeout_sec', 0) or 0), 90),
    'dj_talk_profile': data.get('dj_talk_profile') or 'mixed',
    'dj_medium_talk_chance': float(data.get('dj_medium_talk_chance', 0.38) or 0.38),
    'dj_long_talk_chance': float(data.get('dj_long_talk_chance', 0.20) or 0.20),
    'omnivoice_python': rel_or_abs(py),
    'omnivoice_hf_home': rel_or_abs(hf_home),
    'omnivoice_hf_hub_cache': rel_or_abs(hf_home / 'hub'),
    'omnivoice_hf_xet_cache': rel_or_abs(hf_home / 'xet'),
    'omnivoice_torch_home': rel_or_abs(torch_home),
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
print('[OK] Main radio now reuses existing OmniVoice environment:')
print(' python:', rel_or_abs(py))
print(' HF_HOME:', rel_or_abs(hf_home))
print(' TORCH_HOME:', rel_or_abs(torch_home))
print('Next: run scripts\\tests\\test_tts_windows.bat, then run_radio.bat')
