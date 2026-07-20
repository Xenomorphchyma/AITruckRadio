# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import traceback

from omnivoice_render import (
    apply_ffmpeg_path,
    append_tail_silence,
    normalize_ru_tts_text,
    sanitize_instruct,
)


def jprint(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description='Persistent OmniVoice worker for AI Truck Radio')
    ap.add_argument('--model', default='k2-fsa/OmniVoice')
    ap.add_argument('--device', default='cuda:0', choices=['auto', 'cuda:0', 'cpu'])
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('HF_HOME', str(root / '.hf_cache'))
    os.environ.setdefault('HF_HUB_CACHE', str(root / '.hf_cache' / 'hub'))
    os.environ.setdefault('HF_XET_CACHE', str(root / '.hf_cache' / 'xet'))
    os.environ.setdefault('TORCH_HOME', str(root / '.torch_cache'))
    os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
    os.environ.setdefault('HF_XET_HIGH_PERFORMANCE', '1')
    apply_ffmpeg_path(root)

    try:
        import torch
        import soundfile as sf
        from omnivoice import OmniVoice
    except Exception as e:
        jprint({'ok': False, 'stage': 'import', 'error': repr(e), 'traceback': traceback.format_exc()[-3000:]})
        return 2

    cuda_available = bool(torch.cuda.is_available())
    gpu_name = ''
    try:
        if cuda_available:
            gpu_name = str(torch.cuda.get_device_name(0))
    except Exception:
        gpu_name = ''
    if args.device == 'auto':
        device_map = 'cuda:0' if cuda_available else 'cpu'
    else:
        device_map = args.device
    if str(device_map).startswith('cuda') and not cuda_available:
        print('[OmniVoice worker] WARNING: cuda device requested, but torch.cuda.is_available() is False; loading will likely fail or fall back slowly.', file=sys.stderr, flush=True)
    dtype = torch.float16 if str(device_map).startswith('cuda') else torch.float32

    try:
        print(f'[OmniVoice worker] cuda_available={cuda_available} gpu={gpu_name or "none"}', file=sys.stderr, flush=True)
        print(f'[OmniVoice worker] loading model={args.model} device={device_map} dtype={dtype}', file=sys.stderr, flush=True)
        model = OmniVoice.from_pretrained(args.model, device_map=device_map, dtype=dtype)
        jprint({'ok': True, 'stage': 'ready', 'device': device_map, 'dtype': str(dtype), 'cuda_available': cuda_available, 'gpu': gpu_name})
    except Exception as e:
        jprint({'ok': False, 'stage': 'load', 'error': repr(e), 'traceback': traceback.format_exc()[-4000:]})
        return 3

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            job = json.loads(raw)
            job_id = str(job.get('job_id') or '')
            out = Path(str(job.get('out') or ''))
            text = str(job.get('text') or '').strip()
            if not text:
                raise ValueError('empty text')
            pronunciation_file = str(job.get('pronunciation_file') or 'prompts/pronunciation_ru.tsv')
            pp = Path(pronunciation_file)
            if not pp.is_absolute():
                pp = root / pp
            normalized_text = text
            if bool(job.get('normalize_ru', True)):
                normalized_text = normalize_ru_tts_text(text, pp if pp.exists() else None)

            mode = str(job.get('mode') or 'clone').lower().strip()
            kwargs = {
                'text': normalized_text,
                'num_step': int(job.get('steps') or 16),
                'speed': float(job.get('speed') or 1.0),
            }
            instruct = sanitize_instruct(str(job.get('instruct') or '').strip() or None)
            if mode == 'auto':
                mode = 'clone' if str(job.get('ref_audio') or '').strip() else 'design'
            if mode == 'clone':
                ref_audio = Path(str(job.get('ref_audio') or ''))
                if not ref_audio.is_absolute():
                    ref_audio = root / ref_audio
                if not ref_audio.exists():
                    raise FileNotFoundError(f'ref audio not found: {ref_audio}')
                ref_text = str(job.get('ref_text') or '').strip()
                if not ref_text:
                    sidecar = ref_audio.with_suffix('.txt')
                    if sidecar.exists():
                        ref_text = sidecar.read_text(encoding='utf-8-sig', errors='replace').strip()
                kwargs['ref_audio'] = str(ref_audio)
                if ref_text:
                    kwargs['ref_text'] = ref_text
                if instruct:
                    kwargs['instruct'] = instruct
            elif mode == 'design':
                if instruct:
                    kwargs['instruct'] = instruct
            else:
                raise ValueError(f'unsupported mode: {mode}')

            audio = model.generate(**kwargs)
            if audio is None:
                raise RuntimeError('model.generate returned None')
            if isinstance(audio, tuple):
                audio = audio[0]
            if hasattr(audio, 'detach'):
                audio = audio.detach().cpu().numpy()
            if isinstance(audio, list):
                if not audio:
                    raise RuntimeError('model.generate returned empty list')
                audio = audio[0]
                if hasattr(audio, 'detach'):
                    audio = audio.detach().cpu().numpy()
            sample_rate = 24000
            audio = append_tail_silence(audio, sample_rate, int(job.get('tail_silence_ms') or 260))
            out.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out), audio, sample_rate)
            jprint({'ok': True, 'stage': 'render', 'job_id': job_id, 'out': str(out), 'bytes': out.stat().st_size, 'normalized_text': normalized_text})
        except Exception as e:
            jprint({'ok': False, 'stage': 'render', 'job_id': locals().get('job_id', ''), 'error': repr(e), 'traceback': traceback.format_exc()[-4000:]})

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
