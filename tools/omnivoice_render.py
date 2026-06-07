from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import traceback

VERSION = '0.4.8-render'


VALID_EN_INSTRUCT = {
    'american accent', 'australian accent', 'british accent', 'canadian accent',
    'child', 'chinese accent', 'elderly', 'female', 'high pitch', 'indian accent',
    'japanese accent', 'korean accent', 'low pitch', 'male', 'middle-aged',
    'moderate pitch', 'portuguese accent', 'russian accent', 'teenager',
    'very high pitch', 'very low pitch', 'whisper', 'young adult',
}

# Small built-in pronunciation dictionary for common radio strings and Russian homographs.
# You can override/extend it in prompts\pronunciation_ru.tsv.
BUILTIN_RU_REPLACEMENTS: list[tuple[str, str]] = [
    ('Дальнобой FM', 'Дальнобой эф эм'),
    ('FM', 'эф эм'),
    ('AI', 'эй ай'),
    ('ETS2', 'е тэ эс два'),
    ('Euro Truck Simulator 2', 'Евро трак симулятор два'),
    ('тест голоса', 'тест го́лоса'),
    ('проверяем голоса', 'проверяем голоса́'),
    ('голосам', 'голоса́м'),
    ('голосами', 'голоса́ми'),
    ('голосА', 'голоса́'),
    ('гОлоса', 'го́лоса'),
    ('на самой', 'на са́мой'),
    ('самой', 'са́мой'),
    ('самое', 'са́мое'),
    ('все слушатели', 'все́ слушатели'),
    ('всем слушателям', 'все́м слушателям'),
    ('сейчас', 'сейча́с'),
    ('погода', 'пого́да'),
    ('погоду', 'пого́ду'),
    ('градусов', 'гра́дусов'),
    ('ветер', 'ве́тер'),
    ('городе', 'го́роде'),
    ('слушатели', 'слу́шатели'),
    ('следующий трек', 'сле́дующий тре́к'),
]


def apply_ffmpeg_path(root: Path) -> None:
    """Try to make pydub/OmniVoice see FFmpeg without installing it globally."""
    candidates: list[str] = []
    env_ffmpeg = os.environ.get('AI_TRUCK_RADIO_FFMPEG') or os.environ.get('FFMPEG_PATH')
    if env_ffmpeg:
        candidates.append(env_ffmpeg)
    for cfg in [root / 'config.json', root.parent / 'config.json']:
        if cfg.exists():
            try:
                import json
                data = json.loads(cfg.read_text(encoding='utf-8-sig'))
                val = data.get('ffmpeg_path') or data.get('ffmpeg')
                if val:
                    candidates.append(str(val))
            except Exception:
                pass
    for c in candidates:
        cp = Path(c)
        if cp.is_file():
            os.environ['PATH'] = str(cp.parent) + os.pathsep + os.environ.get('PATH', '')
            os.environ.setdefault('FFMPEG_BINARY', str(cp))
            print('[OmniVoice] FFmpeg path added:', cp)
            return
        if cp.is_dir() and (cp / 'ffmpeg.exe').exists():
            os.environ['PATH'] = str(cp) + os.pathsep + os.environ.get('PATH', '')
            os.environ.setdefault('FFMPEG_BINARY', str(cp / 'ffmpeg.exe'))
            print('[OmniVoice] FFmpeg dir added:', cp)
            return


def read_text(path: str | None, required: bool = False) -> str | None:
    if not path:
        if required:
            raise ValueError('missing required text path')
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'text file not found: {p}')
    text = p.read_text(encoding='utf-8-sig').strip()
    if required and not text:
        raise ValueError(f'text file is empty: {p}')
    return text


def sanitize_instruct(text: str | None) -> str | None:
    """OmniVoice accepts only a closed list of instruct tags.
    Drop unsupported prose so the model does not raise ValueError.
    Style like 'radio presenter' must come from reference audio/post-processing, not instruct.
    """
    if not text:
        return text
    raw_items = [x.strip().lower() for x in text.replace('，', ',').split(',') if x.strip()]
    kept = []
    dropped = []
    for item in raw_items:
        if item in VALID_EN_INSTRUCT:
            kept.append(item)
        else:
            dropped.append(item)
    if dropped:
        print('[OmniVoice] dropped unsupported instruct items:', ', '.join(dropped))
        print('[OmniVoice] valid instruct tags only:', ', '.join(kept) if kept else '(none)')
    return ', '.join(kept) if kept else None


def load_pronunciation_table(path: Path | None) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if path and path.exists():
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '\t' in line:
                src, dst = line.split('\t', 1)
            elif '=>' in line:
                src, dst = line.split('=>', 1)
            elif '=' in line:
                src, dst = line.split('=', 1)
            else:
                continue
            src = src.strip()
            dst = dst.strip()
            if src and dst:
                items.append((src, dst))
    return items


def replace_whole_word_ru(text: str, src: str, dst: str) -> str:
    """Replace src as a Russian/Latin word or phrase without touching longer words."""
    # For multi-word or non-word items, direct replace is safer.
    if re.search(r'\s', src) or not re.match(r'^[A-Za-zА-Яа-яЁё0-9_-]+$', src):
        return text.replace(src, dst)
    pattern = re.compile(rf'(?<![A-Za-zА-Яа-яЁё0-9_-]){re.escape(src)}(?![A-Za-zА-Яа-яЁё0-9_-])', re.IGNORECASE)
    return pattern.sub(dst, text)


def normalize_ru_tts_text(text: str, pronunciation_file: Path | None = None) -> str:
    original = text
    text = text.replace('\r', ' ').replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    # Avoid characters that some TTS models may read awkwardly or clip around.
    text = text.replace('—', ', ').replace('–', ', ')
    text = text.replace(':', '. ')
    text = re.sub(r'\s+([,.!?])', r'\1', text)
    text = re.sub(r'([,.!?])([^\s])', r'\1 \2', text)
    text = re.sub(r'\s+', ' ', text).strip()

    replacements = BUILTIN_RU_REPLACEMENTS + load_pronunciation_table(pronunciation_file)
    # Longer keys first so 'Дальнобой FM' wins over 'FM'.
    for src, dst in sorted(replacements, key=lambda x: len(x[0]), reverse=True):
        text = replace_whole_word_ru(text, src, dst)

    # Ending punctuation gives the decoder a cleaner stop point; helps with clipped final words.
    if text and text[-1] not in '.!?…':
        text += '.'
    # Tiny trailing pause marker. It is not usually spoken, but helps the model not eat the last syllable.
    if not text.endswith('...'):
        text += ' ...'

    if text != original:
        print('[OmniVoice] normalized TTS text:', text[:220].replace('\n', ' '))
    return text


def append_tail_silence(audio, sample_rate: int, ms: int):
    if ms <= 0:
        return audio
    try:
        import numpy as np
        arr = audio
        if isinstance(arr, list):
            arr = np.asarray(arr)
        if getattr(arr, 'ndim', 1) == 1:
            pad = np.zeros(int(sample_rate * ms / 1000), dtype=arr.dtype)
        else:
            pad = np.zeros((int(sample_rate * ms / 1000), arr.shape[1]), dtype=arr.dtype)
        return np.concatenate([arr, pad], axis=0)
    except Exception:
        return audio


def main() -> int:
    ap = argparse.ArgumentParser(description='Small OmniVoice test runner for AI Truck Radio')
    ap.add_argument('--mode', choices=['design', 'clone', 'auto'], default='clone')
    ap.add_argument('--model', default='k2-fsa/OmniVoice')
    ap.add_argument('--text', default=None)
    ap.add_argument('--text-file', default=None)
    ap.add_argument('--output', required=True)
    ap.add_argument('--ref-audio', default=None)
    ap.add_argument('--ref-text', default=None)
    ap.add_argument('--ref-text-file', default=None)
    ap.add_argument('--instruct', default=None)
    ap.add_argument('--instruct-file', default=None)
    ap.add_argument('--device', default='auto', choices=['auto', 'cuda:0', 'cpu'])
    ap.add_argument('--steps', type=int, default=16)
    ap.add_argument('--speed', type=float, default=1.0)
    ap.add_argument('--no-ru-normalize', action='store_true')
    ap.add_argument('--pronunciation-file', default=None)
    ap.add_argument('--tail-silence-ms', type=int, default=220)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault('HF_HOME', str(root / '.hf_cache'))
    os.environ.setdefault('HF_HUB_CACHE', str(root / '.hf_cache' / 'hub'))
    os.environ.setdefault('TORCH_HOME', str(root / '.torch_cache'))
    os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
    os.environ.setdefault('HF_XET_HIGH_PERFORMANCE', '1')
    os.environ.setdefault('PYTHONUTF8', '1')
    apply_ffmpeg_path(root)

    text = str(args.text if args.text is not None else read_text(args.text_file, required=True) or "")
    pronunciation_file = Path(args.pronunciation_file) if args.pronunciation_file else (root / 'prompts' / 'pronunciation_ru.tsv')
    if not args.no_ru_normalize:
        text = normalize_ru_tts_text(text, pronunciation_file if pronunciation_file.exists() else None)
    instruct = args.instruct if args.instruct is not None else read_text(args.instruct_file, required=False)
    instruct = sanitize_instruct(instruct)

    print(f'[OmniVoice test wrapper] version {VERSION}')
    print('[OmniVoice] cwd:', Path.cwd())

    try:
        import torch
        import soundfile as sf
        from omnivoice import OmniVoice
    except Exception:
        print('[ERROR] Import failed.')
        traceback.print_exc()
        return 2

    if args.device == 'auto':
        device_map = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    else:
        device_map = args.device

    dtype = torch.float16 if device_map.startswith('cuda') else torch.float32

    print('[OmniVoice] model:', args.model)
    print('[OmniVoice] device_map:', device_map)
    print('[OmniVoice] dtype:', dtype)
    print('[OmniVoice] mode:', args.mode)
    print('[OmniVoice] output:', args.output)
    print('[OmniVoice] text:', text[:220].replace('\n', ' '))
    if instruct:
        print('[OmniVoice] instruct:', instruct[:160].replace('\n', ' '))

    try:
        model = OmniVoice.from_pretrained(args.model, device_map=device_map, dtype=dtype)
        if model is None:
            raise RuntimeError('OmniVoice.from_pretrained returned None')
        kwargs = {
            'text': text,
            'num_step': args.steps,
            'speed': args.speed,
        }

        if args.mode == 'clone':
            if not args.ref_audio:
                raise ValueError('clone mode needs --ref-audio')
            ref_audio = Path(args.ref_audio)
            if not ref_audio.exists():
                raise FileNotFoundError(f'ref audio not found: {ref_audio}')
            ref_text = args.ref_text if args.ref_text is not None else read_text(args.ref_text_file, required=False)
            kwargs['ref_audio'] = str(ref_audio)
            if ref_text:
                # Ref text must stay literal, do not stress-normalize it unless the ref itself contains that pronunciation.
                kwargs['ref_text'] = ref_text
                print('[OmniVoice] ref_text:', ref_text[:220].replace('\n', ' '))
            if instruct:
                kwargs['instruct'] = instruct
        elif args.mode == 'design':
            if instruct:
                kwargs['instruct'] = instruct

        print('[OmniVoice] generating...')
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
        audio = append_tail_silence(audio, sample_rate, args.tail_silence_ms)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), audio, sample_rate)
        print('[OmniVoice] wrote:', out.resolve())
        print('[OmniVoice] size:', out.stat().st_size)
        print('[OmniVoice] tail silence ms:', args.tail_silence_ms)
        return 0
    except Exception:
        print('[ERROR] OmniVoice generation failed.')
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
