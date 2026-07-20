# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
import wave

import pytest

import ai_truck_radio_app.ref_voice as ref_voice
from ai_truck_radio_app.ref_voice import (
    compare_reference_transcripts,
    inspect_reference_pair,
    release_reference_asr_models,
    transcribe_reference_audio,
    validate_reference_transcript,
    write_reference_files,
)


def _write_wav(path: Path, duration: float = 1.0) -> bytes:
    rate = 16000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x00\x00" * int(rate * duration))
    return path.read_bytes()


def _install_fake_whisper(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str,
    text_by_model: dict[str, str] | None = None,
    language: str = "ru",
    language_probability: float = 0.99,
    no_speech_prob: float = 0.0,
    avg_logprob: float = -0.2,
    compression_ratio: float = 1.1,
) -> type:
    module = ModuleType("faster_whisper")

    class FakeWhisperModel:
        created: list[tuple[str, str, str]] = []

        def __init__(self, model_name: str, *, device: str, compute_type: str, **_kwargs: object):
            self.created.append((model_name, device, compute_type))
            self.text = (text_by_model or {}).get(model_name, text)

        def transcribe(self, *_args: object, **_kwargs: object) -> tuple[list[SimpleNamespace], SimpleNamespace]:
            segments = [
                SimpleNamespace(
                    text=self.text,
                    no_speech_prob=no_speech_prob,
                    avg_logprob=avg_logprob,
                    compression_ratio=compression_ratio,
                )
            ]
            info = SimpleNamespace(language=language, language_probability=language_probability)
            return segments, info

    module.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return FakeWhisperModel


def _install_fake_gigaam(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text_by_model: dict[str, str],
) -> ModuleType:
    module = ModuleType("gigaam")
    module.created = []  # type: ignore[attr-defined]

    class FakeGigaModel:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def transcribe(self, _audio_path: str) -> str:
            return text_by_model[self.model_name]

    def load_model(model_name: str, **kwargs: object) -> FakeGigaModel:
        module.created.append((model_name, kwargs.get("device"), kwargs.get("fp16_encoder")))  # type: ignore[attr-defined]
        return FakeGigaModel(model_name)

    module.load_model = load_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gigaam", module)
    return module


def test_repository_reference_sidecars_pass_structural_quality_checks() -> None:
    root = Path(__file__).parents[1] / "references"
    for stem in ("maxim_ref", "irina_ref"):
        report = inspect_reference_pair({"reference_asr_language": "ru"}, root / f"{stem}.wav")
        assert report.ok, f"{stem}: {report.error}"
        assert 3.0 <= report.duration_sec <= 15.0
        assert report.sample_rate == 44100
        assert report.channels == 2
        assert 2 <= report.transcript.word_count <= 240
        assert report.transcript.language_ratio >= 0.55
        assert any("mono" in warning for warning in report.warnings)


@pytest.mark.parametrize(
    ("text", "error_fragment"),
    [
        ("Спасибо за просмотр", "ASR-шум"),
        ("да да да да да да да да", "повтор"),
        ("This reference contains only English speech", "Язык"),
        ("\ufffd повреждено", "повреждённые"),
    ],
)
def test_transcript_validator_rejects_noise_repetition_wrong_language_and_encoding(text: str, error_fragment: str) -> None:
    result = validate_reference_transcript(text, expected_language="ru")
    assert not result.ok
    assert error_fragment in result.error
    assert result.text == ""


def test_manual_and_asr_comparison_requires_close_transcripts() -> None:
    close = compare_reference_transcripts(
        "Добрый вечер, это тестовая фраза ведущего.",
        "Добрый вечер это тестовая фраза ведущего",
    )
    mismatch = compare_reference_transcripts(
        "Добрый вечер, это тестовая фраза ведущего.",
        "Сегодня в городе ожидается сильный дождь.",
    )
    assert close.ok and close.similarity >= 0.72
    assert close.preferred_text.startswith("Добрый вечер")
    assert not mismatch.ok
    assert mismatch.preferred_text == ""
    assert "расходятся" in mismatch.error

    name_warning = compare_reference_transcripts(
        "В гостях была Диана Берлин, известная радиоведущая.",
        "В гостях была Зиана Берлин, известная радиоведущая.",
    )
    assert name_warning.ok and name_warning.requires_review
    assert name_warning.preferred_text.startswith("В гостях была Диана")
    assert "проверить на слух" in name_warning.warning

    spoken_number = compare_reference_transcripts(
        "Чё-то, мне стукнуло сорок пять.",
        "Что-то... Мне стукнуло 45.",
    )
    assert spoken_number.ok
    assert spoken_number.similarity == 1.0
    assert not spoken_number.requires_review


def test_write_reference_files_validates_wav_and_manual_text_before_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    audio = _write_wav(source)
    output = tmp_path / "references"
    output.mkdir()
    monkeypatch.setattr(ref_voice, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ref_voice, "references_dir", lambda: output)

    audio_name, text_name = write_reference_files("host", "Максим", "voice.wav", audio, "Точная тестовая фраза ведущего.")
    assert (tmp_path / audio_name).is_file()
    assert (tmp_path / text_name).read_text(encoding="utf-8") == "Точная тестовая фраза ведущего."

    with pytest.raises(ValueError, match="ASR-шум"):
        write_reference_files("host", "Ирина", "bad.wav", audio, "Спасибо за просмотр")
    with pytest.raises(ValueError, match="повреждён"):
        write_reference_files("host", "Ирина", "broken.wav", b"RIFF" + b"\x00" * 300, "Точная фраза ведущего.")


def test_asr_uses_low_memory_default_validates_output_and_releases_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    fake_model = _install_fake_whisper(monkeypatch, text="Добрый день, это точная тестовая фраза.")
    release_reference_asr_models()

    text, ok, error = transcribe_reference_audio(
        {"reference_asr_enabled": True, "reference_asr_language": "ru"},
        audio,
    )
    assert ok and not error
    assert text == "Добрый день, это точная тестовая фраза."
    assert fake_model.created == [("Systran/faster-whisper-small", "auto", "auto")]
    assert ref_voice._WHISPER_MODELS == {}


def test_asr_cache_is_opt_in_and_can_be_released(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    _install_fake_whisper(monkeypatch, text="Добрый день, это точная тестовая фраза.")
    release_reference_asr_models()
    cfg = {
        "reference_asr_enabled": True,
        "reference_asr_language": "ru",
        "reference_asr_keep_model_loaded": True,
    }
    assert transcribe_reference_audio(cfg, audio)[1]
    assert transcribe_reference_audio(cfg, audio)[1]
    assert len(ref_voice._WHISPER_MODELS) == 1
    assert release_reference_asr_models() == 1
    assert ref_voice._WHISPER_MODELS == {}


def test_asr_strong_reviewer_runs_only_for_ambiguous_manual_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    primary = "В гостях была Зиана Берлин, известная радиоведущая."
    reviewed = "В гостях была Диана Берлин, известная радиоведущая."
    fake_model = _install_fake_whisper(
        monkeypatch,
        text=primary,
        text_by_model={
            "Systran/faster-whisper-small": primary,
            "large-v3-turbo": reviewed,
        },
    )
    release_reference_asr_models()
    cfg = {
        "reference_asr_enabled": True,
        "reference_asr_language": "ru",
        "reference_asr_model": "Systran/faster-whisper-small",
        "reference_asr_device": "cpu",
        "reference_asr_compute_type": "int8",
        "reference_asr_review_enabled": True,
        "reference_asr_review_model": "large-v3-turbo",
        "reference_asr_review_device": "cpu",
        "reference_asr_review_compute_type": "int8",
    }
    text, ok, warning = transcribe_reference_audio(cfg, audio, manual_text=reviewed)
    assert ok
    assert text == reviewed
    assert "Усиленная ASR-проверка" in warning
    assert fake_model.created == [
        ("Systran/faster-whisper-small", "cpu", "int8"),
        ("large-v3-turbo", "cpu", "int8"),
    ]


def test_asr_strong_reviewer_supplies_text_when_manual_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    fake_model = _install_fake_whisper(
        monkeypatch,
        text="Быстрый предварительный вариант текста.",
        text_by_model={
            "large-v3-turbo": "Уточнённый вариант текста для клонирования голоса.",
        },
    )
    release_reference_asr_models()
    text, ok, warning = transcribe_reference_audio(
        {
            "reference_asr_enabled": True,
            "reference_asr_language": "ru",
            "reference_asr_review_enabled": True,
            "reference_asr_review_model": "large-v3-turbo",
            "reference_asr_review_device": "cpu",
            "reference_asr_review_compute_type": "int8",
        },
        audio,
    )
    assert ok
    assert text == "Уточнённый вариант текста для клонирования голоса."
    assert "Усиленная ASR-проверка" in warning
    assert len(fake_model.created) == 2


def test_asr_upload_profiles_control_when_strong_reviewer_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    fake_model = _install_fake_whisper(
        monkeypatch,
        text="Быстрая точная расшифровка тестового голоса.",
        text_by_model={"large-v3-turbo": "Усиленная точная расшифровка тестового голоса."},
    )
    cfg = {
        "reference_asr_enabled": True,
        "reference_asr_language": "ru",
        "reference_asr_review_enabled": True,
        "reference_asr_review_model": "large-v3-turbo",
        "reference_asr_review_device": "cpu",
        "reference_asr_review_compute_type": "int8",
    }

    text, ok, warning = transcribe_reference_audio(cfg, audio, profile="fast")
    assert ok and text.startswith("Быстрая") and not warning
    assert len(fake_model.created) == 1

    fake_model.created.clear()
    text, ok, warning = transcribe_reference_audio(cfg, audio, profile="auto")
    assert ok and text.startswith("Быстрая") and not warning
    assert len(fake_model.created) == 1

    fake_model.created.clear()
    text, ok, warning = transcribe_reference_audio(cfg, audio, profile="accurate")
    assert ok and text.startswith("Усиленная")
    assert "Усиленная ASR-проверка" in warning
    assert len(fake_model.created) == 2


def test_gigaam_levels_use_ctc_rnnt_and_double_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    gigaam = _install_fake_gigaam(
        monkeypatch,
        text_by_model={
            "v3_e2e_ctc": "Точная тестовая фраза русского ведущего.",
            "v3_e2e_rnnt": "Точная тестовая фраза русского ведущего.",
        },
    )
    cfg = {"reference_asr_enabled": True, "reference_asr_language": "ru", "reference_asr_device": "cpu"}

    text, ok, warning = transcribe_reference_audio(cfg, audio, backend="gigaam", level="fast")
    assert ok and text.startswith("Точная") and not warning
    assert [item[0] for item in gigaam.created] == ["v3_e2e_ctc"]  # type: ignore[attr-defined]

    gigaam.created.clear()  # type: ignore[attr-defined]
    text, ok, warning = transcribe_reference_audio(cfg, audio, backend="gigaam", level="balanced")
    assert ok and text.startswith("Точная") and not warning
    assert [item[0] for item in gigaam.created] == ["v3_e2e_rnnt"]  # type: ignore[attr-defined]

    gigaam.created.clear()  # type: ignore[attr-defined]
    text, ok, warning = transcribe_reference_audio(cfg, audio, backend="gigaam", level="maximum")
    assert ok and text.startswith("Точная")
    assert "RNNT + CTC" in warning
    assert [item[0] for item in gigaam.created] == ["v3_e2e_rnnt", "v3_e2e_ctc"]  # type: ignore[attr-defined]


def test_asr_falls_back_to_primary_when_strong_reviewer_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    primary = "Добрый вечер, это точная тестовая фраза ведущего."
    _install_fake_whisper(
        monkeypatch,
        text=primary,
        text_by_model={"large-v3-turbo": "Спасибо за просмотр"},
    )
    release_reference_asr_models()
    text, ok, warning = transcribe_reference_audio(
        {
            "reference_asr_enabled": True,
            "reference_asr_language": "ru",
            "reference_asr_review_enabled": True,
            "reference_asr_review_model": "large-v3-turbo",
            "reference_asr_review_device": "cpu",
            "reference_asr_review_compute_type": "int8",
        },
        audio,
    )
    assert ok
    assert text == primary
    assert "Усиленная ASR недоступна" in warning


def test_asr_rejects_hallucination_language_mismatch_and_manual_disagreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)

    _install_fake_whisper(monkeypatch, text="Спасибо за просмотр")
    text, ok, error = transcribe_reference_audio({"reference_asr_enabled": True}, audio)
    assert not ok and not text and "отклонён" in error

    _install_fake_whisper(monkeypatch, text="This is clearly English speech", language="en")
    text, ok, error = transcribe_reference_audio({"reference_asr_enabled": True}, audio)
    assert not ok and not text and "ожидался ru" in error

    _install_fake_whisper(monkeypatch, text="Сегодня в городе ожидается сильный дождь.")
    text, ok, error = transcribe_reference_audio(
        {"reference_asr_enabled": True},
        audio,
        manual_text="Добрый вечер, это тестовая фраза ведущего.",
    )
    assert not ok and not text and "расходятся" in error


def test_asr_rejects_low_confidence_even_when_text_looks_plausible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "voice.wav"
    _write_wav(audio)
    _install_fake_whisper(
        monkeypatch,
        text="Добрый день, это внешне правдоподобная фраза.",
        avg_logprob=-1.5,
    )
    text, ok, error = transcribe_reference_audio({"reference_asr_enabled": True}, audio)
    assert not ok and not text
    assert "низкая уверенность" in error


def test_missing_audio_fails_before_asr_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)
    text, ok, error = transcribe_reference_audio({"reference_asr_enabled": True}, tmp_path / "missing.wav")
    assert not ok and not text
    assert "не найдено" in error
