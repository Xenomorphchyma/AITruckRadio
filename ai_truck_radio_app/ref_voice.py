# -*- coding: utf-8 -*-
from __future__ import annotations

import difflib
import gc
import io
import re
import os
import shutil
import sys
import tempfile
import threading
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_truck_radio_app.config import BASE_DIR


ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".oga", ".opus", ".aac", ".wma"}
_WHISPER_LOCK = threading.RLock()
_WHISPER_MODELS: Dict[tuple[str, str, str], Any] = {}
_GIGAAM_MODELS: Dict[tuple[str, str], Any] = {}
_ASR_NOISE_RE = re.compile(
    r"(?i)(?:<\|[^>]{1,80}\|>|\[(?:music|музыка|тишина|аплодисменты|шум)\]|"
    r"\bсубтитры\b|\bпродолжение\s+следует\b|\bспасибо\s+за\s+просмотр\b|https?://|www\.)"
)
_RU_UNITS = ("ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
_RU_TEENS = {
    10: "десять", 11: "одиннадцать", 12: "двенадцать", 13: "тринадцать", 14: "четырнадцать",
    15: "пятнадцать", 16: "шестнадцать", 17: "семнадцать", 18: "восемнадцать", 19: "девятнадцать",
}
_RU_TENS = {20: "двадцать", 30: "тридцать", 40: "сорок", 50: "пятьдесят", 60: "шестьдесят", 70: "семьдесят", 80: "восемьдесят", 90: "девяносто"}
_RU_HUNDREDS = {100: "сто", 200: "двести", 300: "триста", 400: "четыреста", 500: "пятьсот", 600: "шестьсот", 700: "семьсот", 800: "восемьсот", 900: "девятьсот"}


_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


@dataclass
class ReferenceResult:
    target_type: str
    host_index: Optional[int]
    ref_audio: str
    ref_text_file: str
    ref_text: str
    asr_model: str
    asr_ok: bool
    asr_error: str = ""


@dataclass(frozen=True)
class AsrPassResult:
    text: str
    ok: bool
    error: str
    warnings: tuple[str, ...]
    model_name: str
    device: str
    compute_type: str


@dataclass(frozen=True)
class TranscriptValidation:
    text: str
    ok: bool
    error: str
    word_count: int = 0
    expected_language: str = ""
    language_ratio: float = 0.0


@dataclass(frozen=True)
class TranscriptComparison:
    manual: TranscriptValidation
    asr: TranscriptValidation
    similarity: float
    ok: bool
    preferred_text: str
    error: str = ""
    requires_review: bool = False
    warning: str = ""


@dataclass(frozen=True)
class ReferenceQualityReport:
    audio_path: str
    text_path: str
    audio_ok: bool
    transcript: TranscriptValidation
    duration_sec: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    comparison: Optional[TranscriptComparison] = None
    warnings: tuple[str, ...] = ()
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.audio_ok and self.transcript.ok and (self.comparison is None or self.comparison.ok) and not self.error


def safe_voice_slug(value: str, fallback: str = "voice") -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    raw = raw.translate(_TRANSLIT)
    raw = raw.encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return raw[:60] or fallback


def references_dir() -> Path:
    path = BASE_DIR / "references"
    path.mkdir(parents=True, exist_ok=True)
    return path


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def validate_reference_transcript(
    text: str,
    *,
    expected_language: str = "ru",
    min_chars: int = 6,
    max_chars: int = 1600,
    min_words: int = 2,
    max_words: int = 240,
    min_language_ratio: float = 0.55,
) -> TranscriptValidation:
    """Validate ASR/manual reference text before it can reach a clone backend.

    The checks are deterministic and deliberately conservative. An invalid
    transcript becomes an empty fallback in the ASR path; manual uploads are
    rejected so an unrelated or hallucinated phrase is never paired with audio.
    """
    raw = str(text or "")
    if any(char == "\ufffd" or (ord(char) < 32 and char not in "\r\n\t") for char in raw):
        return TranscriptValidation("", False, "Текст содержит повреждённые или управляющие символы.")
    cleaned = unicodedata.normalize("NFKC", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return TranscriptValidation("", False, "Текст reference-аудио пустой.")
    if len(cleaned) < max(1, int(min_chars)):
        return TranscriptValidation("", False, f"Текст слишком короткий: {len(cleaned)} символов.")
    if len(cleaned) > max(1, int(max_chars)):
        return TranscriptValidation("", False, f"Текст слишком длинный: {len(cleaned)} символов.")
    if _ASR_NOISE_RE.search(cleaned):
        return TranscriptValidation("", False, "Текст похож на ASR-шум, служебную метку или ссылку.")

    words = re.findall(r"[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)?", cleaned)
    if len(words) < max(1, int(min_words)):
        return TranscriptValidation("", False, f"Недостаточно слов в расшифровке: {len(words)}.")
    if len(words) > max(1, int(max_words)):
        return TranscriptValidation("", False, f"Слишком много слов в расшифровке: {len(words)}.")
    normalized_words = [word.casefold().replace("ё", "е") for word in words]
    if len(words) >= 6 and max(normalized_words.count(word) for word in set(normalized_words)) / len(words) > 0.5:
        return TranscriptValidation("", False, "ASR зациклилась на повторении одного слова.")
    if re.search(r"(?i)\b([A-Za-zА-Яа-яЁё-]+)(?:\s+\1){3,}\b", cleaned):
        return TranscriptValidation("", False, "ASR вернула повторяющийся фрагмент.")

    letters = [char for char in cleaned if char.isalpha()]
    if len(letters) < 4:
        return TranscriptValidation("", False, "В расшифровке недостаточно буквенного текста.")
    language = str(expected_language or "").strip().lower().replace("_", "-").split("-", 1)[0]
    language_ratio = 1.0
    if language == "ru":
        language_ratio = sum("а" <= char.casefold() <= "я" or char.casefold() == "ё" for char in letters) / len(letters)
    elif language == "en":
        language_ratio = sum("a" <= char.casefold() <= "z" for char in letters) / len(letters)
    if language in {"ru", "en"} and language_ratio < max(0.0, min(1.0, float(min_language_ratio))):
        return TranscriptValidation(
            "",
            False,
            f"Язык текста не похож на {language}: доля ожидаемых букв {language_ratio:.0%}.",
            len(words),
            language,
            language_ratio,
        )
    return TranscriptValidation(cleaned, True, "", len(words), language, language_ratio)


def compare_reference_transcripts(
    manual_text: str,
    asr_text: str,
    *,
    expected_language: str = "ru",
    min_similarity: float = 0.72,
    review_similarity: float = 0.985,
) -> TranscriptComparison:
    """Compare user text with ASR instead of silently trusting either source."""
    manual = validate_reference_transcript(manual_text, expected_language=expected_language)
    asr = validate_reference_transcript(asr_text, expected_language=expected_language)
    if manual.ok and not asr.ok:
        return TranscriptComparison(manual, asr, 0.0, True, manual.text, "ASR-текст отклонён; используется проверенный manual-текст.")
    if asr.ok and not manual.ok:
        return TranscriptComparison(manual, asr, 0.0, True, asr.text, "Manual-текст отклонён; используется проверенный ASR-текст.")
    if not manual.ok and not asr.ok:
        return TranscriptComparison(manual, asr, 0.0, False, "", "И manual, и ASR-текст не прошли проверку.")

    manual_normalized = _normalize_transcript_for_comparison(manual.text, expected_language)
    asr_normalized = _normalize_transcript_for_comparison(asr.text, expected_language)
    similarity = difflib.SequenceMatcher(None, manual_normalized, asr_normalized, autojunk=False).ratio()
    threshold = max(0.0, min(1.0, float(min_similarity)))
    if similarity < threshold:
        return TranscriptComparison(
            manual,
            asr,
            similarity,
            False,
            "",
            f"Manual и ASR заметно расходятся: совпадение {similarity:.0%}, требуется проверка человеком.",
        )
    review_threshold = max(threshold, min(1.0, float(review_similarity)))
    if similarity < review_threshold:
        return TranscriptComparison(
            manual,
            asr,
            similarity,
            True,
            manual.text,
            requires_review=True,
            warning=(
                f"Manual сохранён, но отличается от ASR: совпадение {similarity:.0%}. "
                "Имена и спорные слова нужно проверить на слух."
            ),
        )
    return TranscriptComparison(manual, asr, similarity, True, manual.text)


def _ru_number_words(value: int) -> str:
    if value < 0 or value > 999:
        return str(value)
    if value < 10:
        return _RU_UNITS[value]
    parts: List[str] = []
    hundreds = value // 100 * 100
    remainder = value % 100
    if hundreds:
        parts.append(_RU_HUNDREDS[hundreds])
    if remainder in _RU_TEENS:
        parts.append(_RU_TEENS[remainder])
    else:
        tens = remainder // 10 * 10
        units = remainder % 10
        if tens:
            parts.append(_RU_TENS[tens])
        if units:
            parts.append(_RU_UNITS[units])
    return " ".join(parts)


def _normalize_transcript_for_comparison(text: str, expected_language: str) -> str:
    language = str(expected_language or "").strip().lower().replace("_", "-").split("-", 1)[0]
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё]+|\d+", str(text or "").casefold().replace("ё", "е"))
    normalized: List[str] = []
    for word in tokens:
        if word.isdigit() and language == "ru":
            normalized.extend(_ru_number_words(int(word)).split())
        elif language == "ru" and word == "че":
            normalized.append("что")
        else:
            normalized.append(word)
    return " ".join(normalized)


def _release_accelerator_cache() -> None:
    gc.collect()
    torch_module = sys.modules.get("torch")
    cuda = getattr(torch_module, "cuda", None) if torch_module is not None else None
    if cuda is not None and callable(getattr(cuda, "is_available", None)) and cuda.is_available():
        empty_cache = getattr(cuda, "empty_cache", None)
        if callable(empty_cache):
            empty_cache()


def release_reference_asr_models() -> int:
    """Drop cached Whisper models and release accelerator memory best-effort."""
    with _WHISPER_LOCK:
        count = len(_WHISPER_MODELS) + len(_GIGAAM_MODELS)
        _WHISPER_MODELS.clear()
        _GIGAAM_MODELS.clear()
    _release_accelerator_cache()
    return count


def inspect_reference_pair(
    cfg: Dict[str, Any],
    audio_path: Path,
    text_path: Optional[Path] = None,
    *,
    asr_text: str = "",
) -> ReferenceQualityReport:
    """Inspect an on-disk audio/sidecar pair without loading ASR or TTS."""
    text_path = text_path or audio_path.with_suffix(".txt")
    audio_error = _reference_audio_error(cfg, audio_path)
    duration = 0.0
    sample_rate = 0
    channels = 0
    warnings: List[str] = []
    if not audio_error and audio_path.suffix.lower() == ".wav":
        with wave.open(str(audio_path), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            duration = wav_file.getnframes() / sample_rate if sample_rate > 0 else 0.0
        if not 3.0 <= duration <= 15.0:
            warnings.append("Для voice clone обычно лучше фрагмент длиной 3–15 секунд.")
        if channels != 1:
            warnings.append(f"Reference WAV содержит {channels} канала; mono обычно экономнее и предсказуемее.")
        if sample_rate < 16000:
            warnings.append(f"Низкая частота дискретизации reference WAV: {sample_rate} Гц.")

    try:
        sidecar = text_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        sidecar = ""
        text_error = f"Reference-текст не прочитан: {exc}"
    else:
        text_error = ""
    expected_language = str(cfg.get("reference_asr_language", "ru") or "").strip()
    transcript = validate_reference_transcript(sidecar, expected_language=expected_language)
    comparison = None
    if str(asr_text or "").strip():
        comparison = compare_reference_transcripts(
            sidecar,
            asr_text,
            expected_language=expected_language,
            min_similarity=float(cfg.get("reference_asr_manual_min_similarity", 0.72) or 0.72),
            review_similarity=float(cfg.get("reference_asr_manual_review_similarity", 0.985) or 0.985),
        )
        if comparison.warning:
            warnings.append(comparison.warning)
    if duration > 0 and transcript.ok:
        words_per_second = transcript.word_count / duration
        if words_per_second < 0.5 or words_per_second > 5.5:
            warnings.append(f"Необычная плотность расшифровки: {words_per_second:.1f} слова/сек.")
    errors = [value for value in (audio_error, text_error, transcript.error if not transcript.ok else "") if value]
    if comparison is not None and not comparison.ok:
        errors.append(comparison.error)
    return ReferenceQualityReport(
        str(audio_path),
        str(text_path),
        not audio_error,
        transcript,
        duration,
        sample_rate,
        channels,
        comparison,
        tuple(warnings),
        "; ".join(errors),
    )


def _reference_audio_error(cfg: Dict[str, Any], audio_path: Path) -> str:
    if audio_path.suffix.lower() not in ALLOWED_AUDIO_EXTS:
        return f"Неподдерживаемый формат reference-аудио: {audio_path.suffix or 'без расширения'}."
    if not audio_path.is_file():
        return f"Reference-аудио не найдено: {audio_path}"
    size = audio_path.stat().st_size
    if size < 256:
        return "Reference-аудио слишком короткое или повреждено."
    if size > 80 * 1024 * 1024:
        return "Reference-аудио превышает лимит 80 МБ."
    if audio_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(audio_path), "rb") as wav_file:
                rate = wav_file.getframerate()
                frames = wav_file.getnframes()
                duration = frames / rate if rate > 0 else 0.0
        except (EOFError, wave.Error) as exc:
            return f"Повреждённый WAV-файл: {exc}"
        min_duration = max(0.2, float(cfg.get("reference_asr_min_audio_sec", 0.8) or 0.8))
        max_duration = max(min_duration, float(cfg.get("reference_asr_max_audio_sec", 90.0) or 90.0))
        if duration < min_duration:
            return f"Reference-аудио слишком короткое: {duration:.2f} сек."
        if duration > max_duration:
            return f"Reference-аудио слишком длинное: {duration:.1f} сек., максимум {max_duration:.1f}."
    return ""


def write_reference_files(
    target_type: str,
    name: str,
    filename: str,
    data: bytes,
    ref_text: str,
    *,
    expected_language: str = "ru",
) -> tuple[str, str]:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise ValueError("Поддерживаются только аудиофайлы: wav, mp3, flac, m4a, ogg, opus, aac, wma.")
    if not data:
        raise ValueError("Файл reference-аудио пустой.")
    if len(data) > 80 * 1024 * 1024:
        raise ValueError("Reference-аудио слишком большое. Лучше загрузить короткий фрагмент до 80 МБ.")
    if ext == ".wav":
        try:
            with wave.open(io.BytesIO(data), "rb") as wav_file:
                rate = wav_file.getframerate()
                duration = wav_file.getnframes() / rate if rate > 0 else 0.0
        except (EOFError, wave.Error) as exc:
            raise ValueError(f"Reference WAV повреждён: {exc}") from exc
        if duration < 0.2:
            raise ValueError(f"Reference WAV слишком короткий: {duration:.2f} сек.")
        if duration > 180.0:
            raise ValueError(f"Reference WAV слишком длинный: {duration:.1f} сек.")
    prepared_text = ""
    if str(ref_text or "").strip():
        transcript = validate_reference_transcript(ref_text, expected_language=expected_language)
        if not transcript.ok:
            raise ValueError("Reference-текст отклонён: " + transcript.error)
        prepared_text = transcript.text

    slug = safe_voice_slug(name, "guest" if target_type == "guest" else "host")
    prefix = "guest" if target_type == "guest" else "host"
    audio_path = references_dir() / f"{prefix}_{slug}_ref{ext}"
    text_path = audio_path.with_suffix(".txt")
    # Replace both user-facing files atomically; a crash cannot leave a partial
    # audio/text pair that the TTS worker later consumes.
    def atomic_write(path: Path, content: bytes) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".upload", dir=str(path.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    atomic_write(audio_path, data)
    atomic_write(text_path, prepared_text.encode("utf-8"))
    return rel_path(audio_path), rel_path(text_path)


def _transcribe_reference_pass(
    cfg: Dict[str, Any],
    audio_path: Path,
    whisper_model: Any,
    *,
    model_name: str,
    device: str,
    compute_type: str,
    keep_model_loaded: bool,
) -> AsrPassResult:
    """Run one isolated Whisper pass and reject low-confidence output."""
    language = str(cfg.get("reference_asr_language", "ru") or "ru").strip() or None
    beam_size = max(1, int(float(cfg.get("reference_asr_beam_size", 5) or 5)))
    model_key = (model_name, device, compute_type)
    raw_cache_dir = Path(str(cfg.get("reference_asr_cache_dir", ".hf_cache/asr") or ".hf_cache/asr"))
    cache_dir = raw_cache_dir if raw_cache_dir.is_absolute() else BASE_DIR / raw_cache_dir
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    model: Any = None
    try:
        if keep_model_loaded:
            with _WHISPER_LOCK:
                model = _WHISPER_MODELS.get(model_key)
                if model is None:
                    model = whisper_model(model_name, device=device, compute_type=compute_type, download_root=str(cache_dir))
                    _WHISPER_MODELS[model_key] = model
        else:
            model = whisper_model(model_name, device=device, compute_type=compute_type, download_root=str(cache_dir))
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            word_timestamps=False,
        )
        accepted_segments = []
        accepted_logprobs: List[float] = []
        accepted_compression_ratios: List[float] = []
        accepted_no_speech: List[float] = []
        max_no_speech = max(0.0, min(1.0, float(cfg.get("reference_asr_max_no_speech_prob", 0.8) or 0.8)))
        for segment in segments:
            segment_text = str(getattr(segment, "text", "") or "").strip()
            no_speech_prob = float(getattr(segment, "no_speech_prob", 0.0) or 0.0)
            if segment_text and no_speech_prob <= max_no_speech:
                accepted_segments.append(segment_text)
                accepted_no_speech.append(no_speech_prob)
                if getattr(segment, "avg_logprob", None) is not None:
                    accepted_logprobs.append(float(segment.avg_logprob))
                if getattr(segment, "compression_ratio", None) is not None:
                    accepted_compression_ratios.append(float(segment.compression_ratio))
        text = " ".join(accepted_segments)
        hard_min_logprob = float(cfg.get("reference_asr_min_avg_logprob", -1.1) or -1.1)
        hard_max_compression = float(cfg.get("reference_asr_max_compression_ratio", 3.0) or 3.0)
        if accepted_logprobs and sum(accepted_logprobs) / len(accepted_logprobs) < hard_min_logprob:
            return AsrPassResult("", False, "ASR-текст отклонён: слишком низкая уверенность распознавания.", (), model_name, device, compute_type)
        if accepted_compression_ratios and max(accepted_compression_ratios) > hard_max_compression:
            return AsrPassResult("", False, "ASR-текст отклонён: подозрительное повторение/сжатие результата.", (), model_name, device, compute_type)

        confidence_warnings: List[str] = []
        warning_logprob = float(cfg.get("reference_asr_warn_avg_logprob", -0.55) or -0.55)
        warning_no_speech = float(cfg.get("reference_asr_warn_no_speech_prob", 0.35) or 0.35)
        if accepted_logprobs and sum(accepted_logprobs) / len(accepted_logprobs) < warning_logprob:
            confidence_warnings.append("ASR не вполне уверена в отдельных словах; проверьте имена на слух.")
        if accepted_no_speech and max(accepted_no_speech) > warning_no_speech:
            confidence_warnings.append("В reference-аудио высока вероятность пауз или неречевого участка.")
        expected_language = str(cfg.get("reference_asr_language", "ru") or "").strip().lower()
        detected_language = str(getattr(info, "language", "") or "").strip().lower()
        detected_probability = float(getattr(info, "language_probability", 0.0) or 0.0)
        min_probability = max(0.0, min(1.0, float(cfg.get("reference_asr_min_language_probability", 0.55) or 0.55)))
        if expected_language and detected_language and detected_language != expected_language and detected_probability >= min_probability:
            return AsrPassResult(
                "",
                False,
                f"ASR определила язык {detected_language} с вероятностью {detected_probability:.0%}, ожидался {expected_language}.",
                (),
                model_name,
                device,
                compute_type,
            )
        transcript = validate_reference_transcript(
            text,
            expected_language=expected_language,
            min_chars=int(cfg.get("reference_asr_transcript_min_chars", 6) or 6),
            max_chars=int(cfg.get("reference_asr_transcript_max_chars", 1600) or 1600),
            min_words=int(cfg.get("reference_asr_transcript_min_words", 2) or 2),
            max_words=int(cfg.get("reference_asr_transcript_max_words", 240) or 240),
            min_language_ratio=float(cfg.get("reference_asr_min_language_ratio", 0.55) or 0.55),
        )
        if not transcript.ok:
            return AsrPassResult("", False, "ASR-текст отклонён: " + transcript.error, (), model_name, device, compute_type)
        return AsrPassResult(transcript.text, True, "", tuple(confidence_warnings), model_name, device, compute_type)
    except Exception as exc:
        if keep_model_loaded:
            with _WHISPER_LOCK:
                if _WHISPER_MODELS.get(model_key) is model:
                    _WHISPER_MODELS.pop(model_key, None)
        return AsrPassResult("", False, str(exc), (), model_name, device, compute_type)
    finally:
        if not keep_model_loaded:
            model = None
            _release_accelerator_cache()


def _append_unique(messages: List[str], *values: str) -> None:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in messages:
            messages.append(cleaned)


def _transcribe_gigaam_pass(
    cfg: Dict[str, Any],
    audio_path: Path,
    gigaam_module: Any,
    *,
    model_name: str,
    keep_model_loaded: bool,
) -> AsrPassResult:
    """Run one GigaAM-v3 pass using its official short-audio API."""
    raw_device = str(cfg.get("reference_asr_device", "cpu") or "cpu").strip().lower()
    device = "" if raw_device in {"", "auto"} else raw_device
    model_key = (model_name, device or "auto")
    raw_cache_dir = Path(str(cfg.get("reference_asr_cache_dir", ".hf_cache/asr") or ".hf_cache/asr"))
    cache_dir = raw_cache_dir if raw_cache_dir.is_absolute() else BASE_DIR / raw_cache_dir
    cache_dir = cache_dir / "gigaam"
    model: Any = None
    original_path = os.environ.get("PATH", "")
    ffmpeg_path = Path(str(cfg.get("ffmpeg_path", "") or "").strip())
    if ffmpeg_path.is_file():
        os.environ["PATH"] = str(ffmpeg_path.parent) + os.pathsep + original_path
    giga_model_module = sys.modules.get("gigaam.model")
    original_audio_loader = getattr(giga_model_module, "load_audio", None) if giga_model_module is not None else None
    use_soundfile_loader = not (ffmpeg_path.is_file() or shutil.which("ffmpeg"))

    def load_audio_without_ffmpeg(path: str, sample_rate: int = 16000) -> Any:
        """Read common reference formats without requiring global FFmpeg."""
        import soundfile as sf  # type: ignore
        import torch  # type: ignore
        import torchaudio  # type: ignore

        samples, source_rate = sf.read(path, dtype="float32", always_2d=True)
        mono = samples.mean(axis=1)
        tensor = torch.from_numpy(mono)
        if int(source_rate) != int(sample_rate):
            tensor = torchaudio.functional.resample(tensor, int(source_rate), int(sample_rate))
        return tensor.contiguous()

    if use_soundfile_loader and giga_model_module is not None:
        setattr(giga_model_module, "load_audio", load_audio_without_ffmpeg)
    try:
        load_kwargs = {
            "device": device or None,
            "download_root": str(cache_dir),
            "fp16_encoder": not (device or "cpu").startswith("cpu"),
        }
        if keep_model_loaded:
            with _WHISPER_LOCK:
                model = _GIGAAM_MODELS.get(model_key)
                if model is None:
                    model = gigaam_module.load_model(model_name, **load_kwargs)
                    _GIGAAM_MODELS[model_key] = model
        else:
            model = gigaam_module.load_model(model_name, **load_kwargs)
        raw_result = model.transcribe(str(audio_path))
        text = str(getattr(raw_result, "text", raw_result) or "").strip()
        transcript = validate_reference_transcript(
            text,
            expected_language=str(cfg.get("reference_asr_language", "ru") or "ru"),
            min_chars=int(cfg.get("reference_asr_transcript_min_chars", 6) or 6),
            max_chars=int(cfg.get("reference_asr_transcript_max_chars", 1600) or 1600),
            min_words=int(cfg.get("reference_asr_transcript_min_words", 2) or 2),
            max_words=int(cfg.get("reference_asr_transcript_max_words", 240) or 240),
            min_language_ratio=float(cfg.get("reference_asr_min_language_ratio", 0.55) or 0.55),
        )
        if not transcript.ok:
            return AsrPassResult("", False, "GigaAM-текст отклонён: " + transcript.error, (), model_name, device or "auto", "fp16" if load_kwargs["fp16_encoder"] else "fp32")
        return AsrPassResult(transcript.text, True, "", (), model_name, device or "auto", "fp16" if load_kwargs["fp16_encoder"] else "fp32")
    except Exception as exc:
        if keep_model_loaded:
            with _WHISPER_LOCK:
                if _GIGAAM_MODELS.get(model_key) is model:
                    _GIGAAM_MODELS.pop(model_key, None)
        return AsrPassResult("", False, str(exc), (), model_name, device or "auto", "")
    finally:
        if use_soundfile_loader and giga_model_module is not None and original_audio_loader is not None:
            setattr(giga_model_module, "load_audio", original_audio_loader)
        os.environ["PATH"] = original_path
        if not keep_model_loaded:
            model = None
            _release_accelerator_cache()


def _finish_reference_transcript(
    cfg: Dict[str, Any],
    selected: AsrPassResult,
    *,
    manual_text: str,
    warnings: List[str],
) -> tuple[str, bool, str]:
    if not selected.ok:
        return "", False, selected.error
    manual = str(manual_text or "").strip()
    if manual:
        comparison = compare_reference_transcripts(
            manual,
            selected.text,
            expected_language=str(cfg.get("reference_asr_language", "ru") or "").strip().lower(),
            min_similarity=float(cfg.get("reference_asr_manual_min_similarity", 0.72) or 0.72),
            review_similarity=float(cfg.get("reference_asr_manual_review_similarity", 0.985) or 0.985),
        )
        if not comparison.ok:
            return "", False, comparison.error
        _append_unique(warnings, comparison.warning)
        return comparison.preferred_text, True, " ".join(warnings)
    return selected.text, True, " ".join(warnings)


def _transcribe_reference_gigaam(
    cfg: Dict[str, Any],
    audio_path: Path,
    *,
    manual_text: str,
    level: str,
) -> tuple[str, bool, str]:
    try:
        import gigaam  # type: ignore
    except Exception as exc:
        return "", False, (
            "GigaAM не установлен. Установите официальный пакет salute-developers/GigaAM "
            "в основное окружение приложения (pip install -e .[torch]). "
            f"({exc})"
        )
    keep_loaded = bool(cfg.get("reference_asr_keep_model_loaded", False))
    if level == "fast":
        selected = _transcribe_gigaam_pass(cfg, audio_path, gigaam, model_name="v3_e2e_ctc", keep_model_loaded=keep_loaded)
        return _finish_reference_transcript(cfg, selected, manual_text=manual_text, warnings=[])
    selected = _transcribe_gigaam_pass(cfg, audio_path, gigaam, model_name="v3_e2e_rnnt", keep_model_loaded=keep_loaded)
    warnings: List[str] = []
    if level == "maximum":
        reviewer = _transcribe_gigaam_pass(cfg, audio_path, gigaam, model_name="v3_e2e_ctc", keep_model_loaded=False)
        if reviewer.ok and selected.ok:
            consensus = compare_reference_transcripts(
                selected.text,
                reviewer.text,
                expected_language=str(cfg.get("reference_asr_language", "ru") or "ru"),
                min_similarity=0.0,
                review_similarity=1.0,
            )
            floor = max(0.0, min(1.0, float(cfg.get("reference_asr_review_consensus_similarity", 0.86) or 0.86)))
            _append_unique(warnings, "Двойная проверка GigaAM: RNNT + CTC.")
            if consensus.similarity < floor:
                _append_unique(warnings, f"Варианты GigaAM расходятся: совпадение {consensus.similarity:.0%}; проверьте текст на слух.")
        elif not selected.ok and reviewer.ok:
            selected = reviewer
            _append_unique(warnings, "GigaAM RNNT не сработал; использован результат CTC.")
        elif not reviewer.ok:
            _append_unique(warnings, f"Второй проход GigaAM недоступен: {reviewer.error}")
    return _finish_reference_transcript(cfg, selected, manual_text=manual_text, warnings=warnings)


def transcribe_reference_audio(
    cfg: Dict[str, Any],
    audio_path: Path,
    *,
    manual_text: str = "",
    profile: str = "",
    backend: str = "",
    level: str = "",
) -> tuple[str, bool, str]:
    """Transcribe a reference with a fast pass and optional stronger review.

    The large reviewer runs only when the primary pass is uncertain, disagrees
    with manual text, or no manual text exists. Models are uncached by default,
    so occasional reference checks do not reserve RAM/VRAM during broadcasts.
    """
    if not bool(cfg.get("reference_asr_enabled", True)):
        return "", False, "ASR выключен в настройках."
    selected_backend = str(backend or cfg.get("reference_asr_backend", "faster-whisper") or "faster-whisper").strip().lower()
    selected_level = str(level or "").strip().lower()
    if selected_level not in {"", "fast", "balanced", "maximum"}:
        return "", False, f"Неизвестный уровень распознавания: {selected_level}"
    audio_error = _reference_audio_error(cfg, audio_path)
    if audio_error:
        return "", False, audio_error
    if selected_backend in {"gigaam", "giga", "giga-am"}:
        legacy_level = {"fast": "fast", "auto": "balanced", "accurate": "maximum"}.get(str(profile or "").strip().lower(), "balanced")
        return _transcribe_reference_gigaam(
            cfg,
            audio_path,
            manual_text=manual_text,
            level=selected_level or legacy_level,
        )
    if selected_backend not in {"faster-whisper", "faster_whisper", "whisper"}:
        return "", False, f"Неизвестный ASR backend: {selected_backend}"
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:
        return "", False, (
            "faster-whisper не установлен. Установи его в основное окружение: "
            ".\\.venv\\Scripts\\python.exe -m pip install -r requirements-optional-asr.txt"
            f" ({exc})"
        )

    whisper_level_models = {
        "fast": "Systran/faster-whisper-small",
        "balanced": "large-v3-turbo",
        "maximum": "Systran/faster-whisper-large-v3",
    }
    primary_model = whisper_level_models.get(selected_level) or str(cfg.get("reference_asr_model", "Systran/faster-whisper-small") or "Systran/faster-whisper-small")
    primary_device = str(cfg.get("reference_asr_device", "auto") or "auto")
    primary_compute = str(cfg.get("reference_asr_compute_type", "auto") or "auto")
    keep_model_loaded = bool(cfg.get("reference_asr_keep_model_loaded", False))
    primary = _transcribe_reference_pass(
        cfg,
        audio_path,
        WhisperModel,
        model_name=primary_model,
        device=primary_device,
        compute_type=primary_compute,
        keep_model_loaded=keep_model_loaded,
    )

    expected_language = str(cfg.get("reference_asr_language", "ru") or "").strip().lower()
    manual = str(manual_text or "").strip()
    manual_primary_comparison: Optional[TranscriptComparison] = None
    if manual and primary.ok:
        manual_primary_comparison = compare_reference_transcripts(
            manual,
            primary.text,
            expected_language=expected_language,
            min_similarity=float(cfg.get("reference_asr_manual_min_similarity", 0.72) or 0.72),
            review_similarity=float(cfg.get("reference_asr_manual_review_similarity", 0.985) or 0.985),
        )

    asr_profile = str(profile or "").strip().lower()
    if asr_profile not in {"", "fast", "auto", "accurate"}:
        return "", False, f"Неизвестный режим распознавания: {asr_profile}"
    review_enabled = bool(cfg.get("reference_asr_review_enabled", False)) and asr_profile != "fast" and not selected_level
    review_model = str(cfg.get("reference_asr_review_model", "large-v3-turbo") or "").strip()
    review_device = str(cfg.get("reference_asr_review_device", "cpu") or "cpu")
    review_compute = str(cfg.get("reference_asr_review_compute_type", "int8") or "int8")
    review_key = (review_model, review_device, review_compute)
    primary_key = (primary_model, primary_device, primary_compute)
    force_review = asr_profile in {"", "accurate"} and not manual
    should_review = review_enabled and bool(review_model) and review_key != primary_key and (
        force_review
        or not primary.ok
        or bool(primary.warnings)
        or (manual_primary_comparison is not None and (
            not manual_primary_comparison.ok or manual_primary_comparison.requires_review
        ))
    )

    selected = primary
    review: Optional[AsrPassResult] = None
    warnings: List[str] = list(primary.warnings)
    if should_review:
        review = _transcribe_reference_pass(
            cfg,
            audio_path,
            WhisperModel,
            model_name=review_model,
            device=review_device,
            compute_type=review_compute,
            keep_model_loaded=False,
        )
        if review.ok:
            selected = review
            _append_unique(warnings, *review.warnings, f"Усиленная ASR-проверка: {review_model}.")
            if primary.ok:
                consensus = compare_reference_transcripts(
                    primary.text,
                    review.text,
                    expected_language=expected_language,
                    min_similarity=0.0,
                    review_similarity=1.0,
                )
                consensus_floor = max(0.0, min(1.0, float(cfg.get("reference_asr_review_consensus_similarity", 0.86) or 0.86)))
                if consensus.similarity < consensus_floor:
                    _append_unique(
                        warnings,
                        f"Быстрая и усиленная ASR расходятся: совпадение {consensus.similarity:.0%}; проверьте спорные слова на слух.",
                    )
        elif primary.ok:
            _append_unique(warnings, f"Усиленная ASR недоступна, оставлен быстрый результат: {review.error}")

    if not selected.ok:
        errors = [primary.error]
        if review is not None:
            errors.append(review.error)
        return "", False, " Усиленная проверка: ".join(value for value in errors if value)

    if manual:
        comparison = compare_reference_transcripts(
            manual,
            selected.text,
            expected_language=expected_language,
            min_similarity=float(cfg.get("reference_asr_manual_min_similarity", 0.72) or 0.72),
            review_similarity=float(cfg.get("reference_asr_manual_review_similarity", 0.985) or 0.985),
        )
        if not comparison.ok:
            return "", False, comparison.error
        _append_unique(warnings, comparison.warning)
        return comparison.preferred_text, True, " ".join(warnings)
    return selected.text, True, " ".join(warnings)
