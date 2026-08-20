# -*- coding: utf-8 -*-
"""Offline dialogue quality contracts used by the regression corpus.

This module intentionally contains no model, TTS, or network dependency.  The
fake client exercises the real :class:`LMStudioClient` prompt/cleanup path while
returning canned completion payloads, so dialogue regressions can be checked in
CI and on a machine without LM Studio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ai_truck_radio_app.lmstudio import LMStudioClient
from ai_truck_radio_app.text_processing import context_violations_for_host_text, parse_dialogue_segments
from ai_truck_radio_app.tracks import Track


_TERMINAL_PUNCTUATION = ".!?…"
_META_PATTERNS = (
    r"```",
    r"<\s*/?\s*(?:think|analysis|reasoning)\b",
    r"(?im)^\s*(?:assistant|system|user)\s*:",
    r"(?i)\b(?:план блока|следующий трек\s*:|предыдущий трек\s*:|инструкция для модели)\b",
)
_TTS_UNSAFE_PATTERNS = (
    r"(?m)^\s*[-–—•*]+\s+",
    r"\([^\n]{0,180}(?:включается|подводит|ремарка|музыка)\)",
    r"\[[^\]\n]{1,80}\]",
    r"[\U00010000-\U0010ffff]",
)
_SPEAKER_LIKE_PREFIX_RE = re.compile(
    r"(?<![\wА-Яа-яЁё])"
    r"(?P<label>[А-ЯЁA-Z][А-Яа-яЁёA-Za-z-]{1,31}"
    r"(?:\s+[А-ЯЁA-Z][А-Яа-яЁёA-Za-z-]{1,31}){0,2})\s*[:：]"
)
_AUTHORITY_CLAIM_PATTERNS = (
    re.compile(r"\bуч[её]ные\s+(?:доказали|установили|выяснили|подтвердили|считают)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:эксперты|специалисты|исследователи|аналитики|медики|метеорологи)\s+"
        r"(?:утверждают|заявляют|считают|доказали|установили|выяснили|подтвердили|предупреждают|сообщают)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bисследовани(?:е|я)\s+(?:показало|показали|доказало|доказали|подтверждает|подтверждают)\b", re.IGNORECASE),
    re.compile(r"\bпо\s+данным\s+(?P<source>[^,.;!?\n:]{2,100})", re.IGNORECASE),
    re.compile(r"\bсогласно\s+(?:данным|исследованию|отч[её]ту|опросу)\s+(?P<source>[^,.;!?\n:]{2,100})", re.IGNORECASE),
)
_CONTEXT_EVIDENCE_KEY_PARTS = (
    "news",
    "weather",
    "greeting",
    "entertainment",
    "track_info",
    "profile",
    "fact",
    "source",
    "evidence",
    "research",
)


@dataclass(frozen=True)
class DialogueQualityReport:
    """Result of checking one already-generated radio dialogue."""

    text: str
    segments: Tuple[Tuple[Optional[str], str], ...]
    violations: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.violations


def make_track(value: Optional[Dict[str, str]], *, label: str) -> Optional[Track]:
    """Build a metadata-only track suitable for prompt tests (the file need not exist)."""
    if not value:
        return None
    return Track(
        path=Path(f"{label}.mp3"),
        artist=str(value.get("artist") or ""),
        title=str(value.get("title") or label),
    )


def fallback_dialogue(ctx: Dict[str, Any]) -> str:
    """A deterministic, TTS-safe fallback for corpus tests and offline callers."""
    names = [
        str(host.get("name") or "").strip()
        for host in (ctx.get("hosts") or [])
        if isinstance(host, dict) and str(host.get("name") or "").strip()
    ]
    if len(names) >= 2:
        return (
            f"{names[0]}: Небольшая эфирная связка, и снова возвращаемся к музыке.\n"
            f"{names[1]}: Оставайтесь с нами, следующий трек уже рядом."
        )
    if names:
        return f"{names[0]}: Небольшая эфирная связка, и снова возвращаемся к музыке."
    return "Ведущий: Небольшая эфирная связка, и снова возвращаемся к музыке."


class FakeLMStudioClient(LMStudioClient):
    """Deterministic in-memory LM Studio transport for dialogue tests.

    ``completions`` are returned in order for POST ``/chat/completions`` calls.
    No request reaches ``urllib``; captured payloads make prompt assertions
    possible without starting an HTTP server.
    """

    def __init__(self, completions: Sequence[str], cfg: Optional[Dict[str, Any]] = None):
        defaults: Dict[str, Any] = {
            "lm_base_url": "http://offline.invalid/v1",
            "lm_timeout_sec": 1,
            "lm_model": "offline-dialogue-model",
            "lm_temperature": 0.0,
            "lm_max_tokens": 620,
            "max_host_text_chars": 900,
            "radio_persona": "Офлайн-проверка диалогов для радио.",
            "tts_debug_log": False,
            "lm_append_no_think": False,
            "season_reality_guard_enabled": True,
            "host_creative_fact_mode": False,
        }
        defaults.update(cfg or {})
        super().__init__(defaults)
        self._completions = list(completions)
        self.requests: List[Dict[str, Any]] = []
        self._last_completion: Optional[str] = None

    def _request_json(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        del timeout
        self.requests.append({"method": method, "url": url, "payload": payload})
        if method == "GET" and url.endswith("/models"):
            return {"data": [{"id": "offline-dialogue-model"}]}
        if method == "POST" and url.endswith("/chat/completions"):
            if not self._completions:
                raise AssertionError("FakeLMStudioClient received more completion requests than canned responses")
            self._last_completion = str(self._completions.pop(0))
            return {"choices": [{"message": {"content": self._last_completion}}]}
        raise AssertionError(f"Unexpected offline request: {method} {url}")

    def generate_host_line(self, previous_track: Optional[Track], next_track: Optional[Track], ctx: Dict[str, Any]) -> str:
        result = super().generate_host_line(previous_track, next_track, ctx)
        # ``clean_host_text`` intentionally selects a varied runtime fallback for
        # an empty model answer.  Tests need a stable answer, so replace only that
        # last-resort branch after the production cleanup path has been exercised.
        return fallback_dialogue(ctx) if self._last_completion == "" else result


def _speaker_names(ctx: Dict[str, Any], contract: Dict[str, Any]) -> List[str]:
    configured = contract.get("allowed_speakers")
    if configured is None:
        configured = [host.get("name") for host in (ctx.get("hosts") or []) if isinstance(host, dict)]
    return [str(name).strip() for name in configured if str(name).strip()]


def _speaker_configs(ctx: Dict[str, Any], contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Preserve aliases for configured speakers while honoring a contract subset."""
    names = _speaker_names(ctx, contract)
    by_name = {
        str(host.get("name") or "").strip().casefold(): host
        for host in (ctx.get("hosts") or [])
        if isinstance(host, dict) and str(host.get("name") or "").strip()
    }
    return [dict(by_name.get(name.casefold()) or {"name": name}) for name in names]


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def _unknown_speaker_labels(text: str, hosts: Sequence[Dict[str, Any]], ctx: Dict[str, Any], contract: Dict[str, Any]) -> List[str]:
    allowed: set[str] = set()
    allowed.update({
        _normalized("Вопрос"),
        _normalized("Варианты"),
        _normalized("Варианты ответа"),
        _normalized("Правильный ответ"),
    })
    for host in hosts:
        allowed.add(_normalized(host.get("name")))
        aliases = host.get("aliases") or []
        if isinstance(aliases, list):
            allowed.update(_normalized(alias) for alias in aliases if str(alias).strip())
    allowed.update(_normalized(label) for label in (contract.get("allowed_content_labels") or []) if str(label).strip())
    for item in ctx.get("horoscope_expected") or []:
        if isinstance(item, dict) and str(item.get("sign") or "").strip():
            allowed.add(_normalized(item["sign"]))

    unknown: List[str] = []
    for match in _SPEAKER_LIKE_PREFIX_RE.finditer(text):
        label = match.group("label").strip()
        if _normalized(label) not in allowed:
            unknown.append(label)
    return list(dict.fromkeys(unknown))


def _flatten_text(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        out: List[str] = []
        for nested in value.values():
            out.extend(_flatten_text(nested))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for nested in value:
            out.extend(_flatten_text(nested))
        return out
    return []


def _context_evidence(ctx: Dict[str, Any], contract: Dict[str, Any]) -> str:
    """Return only fields intended to carry facts, never prompt instructions."""
    requested_fields = {_normalized(field) for field in (contract.get("authority_context_fields") or [])}
    values: List[str] = []
    for key, value in ctx.items():
        normalized_key = _normalized(key)
        explicitly_requested = normalized_key in requested_fields
        is_instruction = any(part in normalized_key for part in ("instruction", "prompt", "rule", "retry"))
        if explicitly_requested or (not is_instruction and any(part in normalized_key for part in _CONTEXT_EVIDENCE_KEY_PARTS)):
            values.extend(_flatten_text(value))
    return _normalized("\n".join(values))


def _unsupported_authority_claims(text: str, ctx: Dict[str, Any], contract: Dict[str, Any]) -> List[str]:
    evidence = _context_evidence(ctx, contract)
    allowed_claims = [_normalized(value) for value in (contract.get("allowed_authority_claims") or []) if str(value).strip()]
    allowed_sources = [_normalized(value) for value in (contract.get("allowed_authority_sources") or []) if str(value).strip()]
    unsupported: List[str] = []
    for pattern in _AUTHORITY_CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            claim = match.group(0).strip()
            normalized_claim = _normalized(claim)
            if normalized_claim and normalized_claim in evidence:
                continue
            if any(normalized_claim in allowed or allowed in normalized_claim for allowed in allowed_claims):
                continue
            source = _normalized(match.groupdict().get("source"))
            if source and (source in evidence or any(source in allowed or allowed in source for allowed in allowed_sources)):
                continue
            unsupported.append(claim)
    return list(dict.fromkeys(unsupported))


def _contains_any(text: str, values: Iterable[str]) -> bool:
    low = text.lower()
    return any(str(value).lower() in low for value in values)


def evaluate_dialogue_quality(text: str, ctx: Optional[Dict[str, Any]] = None, contract: Optional[Dict[str, Any]] = None) -> DialogueQualityReport:
    """Check speaker labels, ordering, context, and TTS-facing safety.

    The contract is deliberately small and data-driven: ``speaker_sequence``,
    ``required_fragments``, ``forbidden_fragments``, ``forbidden_facts``,
    ``max_chars``, and ``max_segment_chars``.  It keeps scenario-specific facts
    in the corpus instead of pretending a generic regex can fact-check Russian.
    """
    ctx = ctx or {}
    contract = contract or {}
    text = str(text or "").strip()
    violations: List[str] = []
    if not text:
        return DialogueQualityReport(text, (), ("пустой текст для эфира",))

    max_chars = int(contract.get("max_chars", 900) or 900)
    if len(text) > max_chars:
        violations.append(f"текст длиннее лимита: {len(text)} > {max_chars}")
    for pattern in _META_PATTERNS:
        if re.search(pattern, text):
            violations.append("в эфирном тексте остался markdown, thinking или служебная мета-информация")
            break
    allow_tags = bool(contract.get("allow_omnivoice_tags", False))
    for pattern in _TTS_UNSAFE_PATTERNS:
        if allow_tags and pattern == r"\[[^\]\n]{1,80}\]":
            continue
        if re.search(pattern, text):
            violations.append("текст небезопасен для TTS: ремарка, маркер списка или неподдерживаемый тег")
            break

    allowed_names = _speaker_names(ctx, contract)
    hosts = _speaker_configs(ctx, contract)
    unknown_labels = _unknown_speaker_labels(text, hosts, ctx, contract)
    if unknown_labels:
        violations.append("неизвестный префикс говорящего: " + ", ".join(unknown_labels))
    segments = tuple(parse_dialogue_segments(text, hosts))
    spoken_hosts = [name for name, spoken in segments if name and spoken]
    if allowed_names and (not spoken_hosts or any(name is None for name, _ in segments)):
        violations.append("реплики должны иметь подписи разрешённых ведущих")
    unexpected = [name for name in spoken_hosts if name not in allowed_names]
    if unexpected:
        violations.append("обнаружен неразрешённый ведущий: " + ", ".join(unexpected))

    expected_sequence = [str(name) for name in (contract.get("speaker_sequence") or [])]
    if expected_sequence and spoken_hosts != expected_sequence:
        violations.append(f"неверная очередность ведущих: {spoken_hosts!r}, ожидалось {expected_sequence!r}")

    max_segment_chars = int(contract.get("max_segment_chars", 420) or 420)
    for name, spoken in segments:
        if len(spoken) > max_segment_chars:
            violations.append(f"реплика {name or 'без подписи'} длиннее лимита: {len(spoken)} > {max_segment_chars}")
        if spoken and spoken[-1] not in _TERMINAL_PUNCTUATION:
            violations.append(f"реплика {name or 'без подписи'} оборвана без конечной пунктуации")

    required = [str(value) for value in (contract.get("required_fragments") or [])]
    missing = [value for value in required if value.lower() not in text.lower()]
    if missing:
        violations.append("не хватает обязательного контекста: " + ", ".join(missing))
    forbidden = [str(value) for value in (contract.get("forbidden_fragments") or [])]
    forbidden_facts = [str(value) for value in (contract.get("forbidden_facts") or [])]
    blocked = [value for value in forbidden + forbidden_facts if value.lower() in text.lower()]
    if blocked:
        violations.append("запрещённый или неподтверждённый факт/образ: " + ", ".join(blocked))
    unsupported_authority = _unsupported_authority_claims(text, ctx, contract)
    if unsupported_authority:
        violations.append("неподтверждённая ссылка на авторитет: " + ", ".join(unsupported_authority))
    if _contains_any(text, ("грузовик", "дальнобо", "кабина", "симулятор", "за рулём", "за рулем", "трасс")):
        violations.append("неуместное дорожное или игровое клише")

    violations.extend(context_violations_for_host_text(text, ctx))
    return DialogueQualityReport(text, segments, tuple(dict.fromkeys(violations)))
