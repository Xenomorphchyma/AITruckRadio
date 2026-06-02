# -*- coding: utf-8 -*-
from __future__ import annotations

import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ai_truck_radio_app.config import DEFAULT_CONFIG, RUS_MONTHS, RUS_WEEKDAYS

OMNIVOICE_NONVERBAL_TAGS = {
    "[laughter]",
    "[sigh]",
    "[confirmation-en]",
    "[question-en]",
    "[question-ah]",
    "[question-oh]",
    "[question-ei]",
    "[question-yi]",
    "[surprise-ah]",
    "[surprise-oh]",
    "[surprise-wa]",
    "[surprise-yo]",
    "[dissatisfaction-hnn]",
}

RU_NONVERBAL_TAG_ALIASES = {
    "смех": "[laughter]",
    "смеется": "[laughter]",
    "смеётся": "[laughter]",
    "посмеялся": "[laughter]",
    "смешок": "[laughter]",
    "вздох": "[sigh]",
    "вздыхает": "[sigh]",
    "удивление": "[surprise-ah]",
    "удивился": "[surprise-ah]",
    "вопрос": "[question-en]",
    "подтверждение": "[confirmation-en]",
    "согласие": "[confirmation-en]",
    "недовольство": "[dissatisfaction-hnn]",
}


def _current_time_text() -> str:
    now = time.localtime()
    weekday = RUS_WEEKDAYS[now.tm_wday]
    month = RUS_MONTHS[now.tm_mon - 1]
    return f"{now.tm_hour:02d}:{now.tm_min:02d}, {weekday}, {now.tm_mday} {month} {now.tm_year}"


def clean_host_text(text: str, max_chars: int = 4000) -> str:
    text = text.replace("\r", "\n")
    # Убираем thinking-теги, если модель всё-таки их вернула.
    lower = text.lower()
    while "<think>" in lower and "</think>" in lower:
        start = lower.find("<think>")
        end = lower.find("</think>", start)
        text = text[:start] + text[end + len("</think>"):]
        lower = text.lower()
    text = text.replace("```", "")
    # Убираем сценические ремарки и маркдауны до парсинга ведущих.
    text = re.sub(r"<0x[0-9A-Fa-f]{2,8}>", "", text)
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"\*+\s*(В конце блока|Включается|Подводит|После этой речи|Музыка включается).*?(?:\*+|$)", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\([^\n]{0,220}(включается|включаем|следующий трек|подводит|ремарка|музыка)[^\n]{0,220}\)", "", text, flags=re.IGNORECASE)
    lines = []
    for raw in text.splitlines():
        line = " ".join(raw.strip().split())
        if not line:
            continue
        # Модель иногда пишет после имени список: Максим:
        # - реплика. Дефис не должен попадать в эфир и не должен ломать TTS.
        line = re.sub(r"^[-–—•*]+\s*", "", line).strip()
        if not line:
            continue
        for prefix in ["Ведущий:", "DJ:", "Радиоведущий:"]:
            if line.lower().startswith(prefix.lower()):
                line = line[len(prefix):].strip()
        if line:
            lines.append(line)
    text = "\n".join(lines) if lines else " ".join(text.split())
    max_chars = max(600, int(max_chars or 4000))
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "."
    text = trim_to_complete_sentence(text)
    return text.strip() or random.choice(DEFAULT_CONFIG["fallback_host_phrases"])


def normalize_omnivoice_nonverbal_tags(text: str, *, enabled: bool = True) -> str:
    """Keep only OmniVoice-supported inline non-verbal tags.

    Unsupported square-bracket notes are removed so the TTS does not read random
    stage directions. The LM prompt asks for official English tags directly, but
    common Russian aliases are mapped as an error-handling fallback.
    """
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        inner = match.group(1).strip().lower()
        normalized = f"[{inner}]"
        if enabled and normalized in OMNIVOICE_NONVERBAL_TAGS:
            return normalized
        alias = RU_NONVERBAL_TAG_ALIASES.get(inner)
        if enabled and alias:
            return alias
        return ""

    text = re.sub(r"\[([^\[\]\n]{1,40})\]", repl, text)
    # Empty dangling speaker markers like "Ирина:." are prompt artifacts, not speech.
    text = re.sub(r"(?<![\wА-Яа-яЁё])([А-ЯЁ][А-Яа-яЁёA-Za-z-]{1,32})\s*[:：]\s*[.!?]?\s*$", "", text).strip()
    text = re.sub(r"(?<![\wА-Яа-яЁё])([А-ЯЁ][А-Яа-яЁёA-Za-z-]{1,32})\s*[:：]\s*,\s*", r"\1: ", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_omnivoice_nonverbal_tags(text: str) -> str:
    if not text:
        return text
    return re.sub(r"\s+", " ", re.sub(r"\[[^\[\]\n]{1,40}\]", "", text)).strip()


def sanitize_general_radio_text(text: str) -> str:
    """General cleanup for truck-simulator roleplay phrases.

    It is deliberately generic: no artist/song-specific substitutions, only
    removal/rewording of the unwanted broadcast framing.
    """
    if not text:
        return text
    replacements = [
        (r"(?i)\bдальнобойщикам\b", "слушателям"),
        (r"(?i)\bдальнобоям\b", "слушателям"),
        (r"(?i)\bдальнобойщики\b", "слушатели"),
        (r"(?i)\bдальнобойщик\s+Андрей\b", "слушатель Андрей"),
        (r"(?i)\bводитель\s+Андрей\b", "слушатель Андрей"),
        (r"(?i)\bза\s+рул[её]м\b", "у приёмника"),
        (r"(?i)\bв\s+кабине\s+(?:своего\s+)?грузовика\b", "у себя"),
        (r"(?i)\bиз\s+кабины\s+грузовика\b", "из студии"),
        (r"(?i)\bкабина\s+грузовика\b", "вечерняя атмосфера"),
        (r"(?i)\bсалон\s+грузовика\b", "домашний плейлист"),
        (r"(?i)\bгрузовик[ае]?\b", "эфир"),
        (r"(?i)\bрейс[а-яё]*\b", "эфир"),
        (r"(?i)\bна\s+трассе\b", "в эфире"),
        (r"(?i)\bтрасса\b", "эфир"),
        (r"(?i)\bEuro\s+Truck\s+Simulator\s*2?\b", "музыкальный эфир"),
        (r"(?i)\bфары\s+режут\s+темноту\b", "вечер звучит особенно атмосферно"),
        (r"(?i)\bснег\s+хрустит\s+под\s+кол[её]сами\b", "зимний образ звучит только в самой песне"),
        (r"(?i)\bдолгих\s+ночных\s+поездок\b", "позднего вечера"),
    ]
    for pat, repl in replacements:
        text = re.sub(pat, repl, text)
    text = re.sub(r"(?i)\s*на\s+трассе\s+[А-ЯA-ZЁ][^.!?\n]{0,80}\s*[-–—]\s*[А-ЯA-ZЁ][^.!?\n]{0,80}", "", text)
    text = re.sub(r"(?i)\bдорогие\s+водители\b", "дорогие слушатели", text)
    return " ".join(text.split())


def trim_to_complete_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] in ".!?…":
        return text
    # Если модель всё-таки обрезалась по max_tokens, не даём TTS читать оборванный хвост.
    last = max(text.rfind("."), text.rfind("!"), text.rfind("?"), text.rfind("…"))
    if last > max(40, len(text) // 3):
        return text[:last + 1].strip()
    return text + "."


def host_alias_map(hosts: List[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for host in hosts:
        if not isinstance(host, dict):
            continue
        canonical = str(host.get("name", "")).strip()
        if not canonical:
            continue
        keys = [canonical]
        aliases = host.get("aliases") or []
        if isinstance(aliases, list):
            keys.extend(str(a).strip() for a in aliases if str(a).strip())
        for key in keys:
            mapping[key.lower()] = canonical
    return mapping


def host_aliases(hosts: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for host in hosts:
        if not isinstance(host, dict):
            continue
        name = str(host.get("name", "")).strip()
        if name:
            names.append(name)
        aliases = host.get("aliases") or []
        if isinstance(aliases, list):
            names.extend(str(a).strip() for a in aliases if str(a).strip())
    # Длинные имена первыми, чтобы "Максим" не резался как "Макс".
    return sorted(set(names), key=len, reverse=True)


def parse_dialogue_segments(text: str, hosts: List[Dict[str, Any]]) -> List[Tuple[Optional[str], str]]:
    aliases = host_aliases(hosts)
    if not aliases:
        return [(None, strip_spoken_host_names(text, []))]
    canonical_by_alias = host_alias_map(hosts)
    name_re = "|".join(re.escape(n) for n in aliases)

    # Важный фикс: модель часто пишет в одну строку: "Максим: ... Ирина: ...".
    # Поэтому ищем маркеры ведущих по всему тексту, а не только в начале строки.
    one_line = " ".join(text.replace("\r", "\n").split())
    marker_re = re.compile(rf"(?<![\wА-Яа-яЁё])({name_re})\s*[:：]\s*", flags=re.IGNORECASE)
    matches = list(marker_re.finditer(one_line))
    segments: List[Tuple[Optional[str], str]] = []
    if matches:
        for i, m in enumerate(matches):
            found = m.group(1).strip()
            host = canonical_by_alias.get(found.lower(), found)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(one_line)
            spoken = one_line[start:end].strip(" \t\n—-;,")
            spoken = strip_spoken_host_names(spoken, aliases)
            spoken = trim_to_complete_sentence(spoken)
            if spoken:
                segments.append((host, spoken))
        if segments:
            return segments

    # Резервный построчный парсер для красивого многострочного формата.
    current_host: Optional[str] = None
    current_parts: List[str] = []

    def flush() -> None:
        nonlocal current_parts, current_host
        spoken = " ".join(" ".join(p.strip().split()) for p in current_parts if p.strip()).strip()
        spoken = strip_spoken_host_names(spoken, aliases)
        spoken = trim_to_complete_sentence(spoken)
        if spoken:
            segments.append((current_host, spoken))
        current_parts = []

    for raw in text.replace("\r", "\n").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(rf"^({name_re})\s*[:：—-]\s*(.+)$", line, flags=re.IGNORECASE)
        if m:
            flush()
            found = m.group(1).strip()
            current_host = canonical_by_alias.get(found.lower(), found)
            current_parts.append(m.group(2).strip())
        else:
            current_parts.append(line)
    flush()
    if segments:
        return segments
    return [(None, strip_spoken_host_names(text, aliases))]


def normalize_generated_radio_text(text: str) -> str:
    """Light post-edit before TTS/panel: fix common Russian stresses and remove weird LLM slogans."""
    if not text:
        return text
    # Remove a weird phrase Qwen sometimes invented in tests; keep sentence readable.
    text = re.sub(r'(?i)\bдальше\s*[-–—]\s*дышай[!.,;:]*\s*', '', text)
    text = re.sub(r'(?i)\bдальше\s+дышай[!.,;:]*\s*', '', text)
    replacements = [
        ('тест голоса', 'тест го́лоса'),
        ('тест Голоса', 'тест го́лоса'),
        ('тембр голоса', 'тембр го́лоса'),
        ('звучание голоса', 'звучание го́лоса'),
        ('проверяем голоса', 'проверяем голоса́'),
        ('проверка голоса', 'проверка го́лоса'),
        ('голосА', 'голоса́'),
        ('гОлоса', 'го́лоса'),
        ('Дальнобой FM', 'Дальнобойщик ЭФЭМ'),
        ('дальнобой FM', 'Дальнобойщик ЭФЭМ'),
        ('FM', 'ЭФЭМ'),
    ]
    for src, dst in replacements:
        text = text.replace(src, dst)
    # Fix accidental missing space after English/artist names and Russian words: битAaron -> бит Aaron.
    text = re.sub(r'([А-Яа-яЁё])([A-Z][A-Za-z])', r'\1 \2', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text




def postprocess_host_text_for_air(text: str, ctx: Optional[Dict[str, Any]] = None) -> str:
    """Final safety cleanup before TTS: remove prompt leaks, stage directions,
    broken emoji hex chunks, and startup references to non-existing previous songs.
    """
    ctx = ctx or {}
    text = str(text or "")
    text = re.sub(r"<0x[0-9A-Fa-f]{2,8}>", "", text)
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"\*+\s*(В конце блока|Включается|Подводит|После этой речи|Музыка включается).*?(?:\*+|$)", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\([^\n]{0,160}(улыб|мягко|энергично|подводит|ремарка|сме[её]тся|включаем|включается|следующий трек)[^\n]{0,160}\)", "", text, flags=re.IGNORECASE)
    bad_prefix = re.compile(r"^(Стиль станции|План блока|Главная тема блока|ПРЕДЫДУЩИЙ ТРЕК|СЛЕДУЮЩИЙ ТРЕК|Инструкция|Правила|Формат|Системный промпт|Дополнительных новостей)\s*[:：]", re.IGNORECASE)
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or bad_prefix.match(line):
            continue
        if line.lower() in {"/no_think", "no_think"}:
            continue
        lines.append(line)
    text = " ".join(lines).strip()
    host_names = [
        str(h.get("name", "")).strip()
        for h in (ctx.get("hosts") or [])
        if isinstance(h, dict) and str(h.get("name", "")).strip()
    ]
    all_host_names = [
        str(x).strip()
        for x in (ctx.get("all_host_names") or [])
        if str(x).strip()
    ]
    if host_names:
        allowed = list(dict.fromkeys(host_names))
        forbidden = [x for x in dict.fromkeys(all_host_names) if x not in allowed]
        for name in allowed:
            name_re = re.escape(name)
            text = re.sub(rf"({name_re}\s*[:：])\s*\1+", rf"\1 ", text)
            for bad_name in forbidden:
                bad_re = re.escape(bad_name)
                text = re.sub(rf"({name_re}\s*[:：])\s*(?:{bad_re}\s*[:：]\s*)+", rf"\1 ", text)
    prev = str(ctx.get("previous_track_name") or ctx.get("planned_previous_track") or "").lower()
    if not prev or "ничего" in prev or "ещё" in prev or "еще" in prev:
        text = re.sub(r"\b[Вв]\s+предыдущих\s+песнях[^.!?]*[.!?]", "", text)
        text = re.sub(r"\b[Пп]редыдущие\s+песни[^.!?]*[.!?]", "", text)
        text = re.sub(r"\b[Мм]ы\s+только\s+что\s+услышали[^.!?]*[.!?]", "", text)
        text = re.sub(r"\b[Мм]ы\s+услышали[^.!?]*[.!?]", "", text)
        text = re.sub(r"\b[Пп]осле\s+предыдущего\s+трека[^.!?]*[.!?]", "", text)
        text = re.sub(r"\b[Пп]осле\s+прошлого\s+трека[^.!?]*[.!?]", "", text)
        text = re.sub(r"\b[Ии]\s*так,?\s*[^.!?]{0,80}\b(перед нами было|было настоящее|мы слушали)[^.!?]*[.!?]", "", text)
        text = re.sub(r"\b[Пп]еред\s+нами\s+было[^.!?]*[.!?]", "", text)
        text = re.sub(r"\b[Мм]ы\s+слушали[^.!?]*[.!?]", "", text)
    stress_enabled = bool(ctx.get("host_should_use_stress_marks", True))
    if stress_enabled:
        replacements = [
            ("тест голоса", "тест го́лоса"),
            ("тембр голоса", "тембр го́лоса"),
            ("проверяем голоса", "проверяем голоса́"),
            ("радиоэфир", "радиоэфи́р"),
            ("эфир", "эфи́р"),
            ("дорога зовет", "доро́га зовёт"),
            ("музыка", "му́зыка"),
            ("все слушатели", "все́ слушатели"),
            ("всем слушателям", "все́м слушателям"),
            ("на самой", "на са́мой"),
            ("самой", "са́мой"),
            ("погода", "пого́да"),
            ("погоду", "пого́ду"),
            ("градусов", "гра́дусов"),
            ("ветер", "ве́тер"),
            ("сейчас", "сейча́с"),
        ]
        for a, b in replacements:
            text = re.sub(a, b, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return trim_to_complete_sentence(text) if text else text



def expected_daypart_for_hour(hour: int) -> str:
    if 5 <= hour <= 11:
        return "утро"
    if 12 <= hour <= 17:
        return "день"
    if 18 <= hour <= 22:
        return "вечер"
    return "ночь"


def context_violations_for_host_text(text: str, ctx: Optional[Dict[str, Any]] = None) -> List[str]:
    """Detect LLM context drift before TTS.

    The model is allowed to be creative, but not to lie about basic runtime
    context: exact computer time, startup/no previous track, and real weather.
    """
    ctx = ctx or {}
    low = " ".join(str(text or "").lower().split())
    out: List[str] = []
    hour = int(ctx.get("computer_hour", time.localtime().tm_hour) or 0)
    daypart = expected_daypart_for_hour(hour)
    if ctx.get("host_strict_clock_guard", True):
        # Hard factual mismatch: at 15:00 the model must not say it is evening,
        # night, or almost midnight. Do not flag words in exact song titles; this
        # is intentionally about broadcast time phrases/greetings.
        if daypart == "день":
            patterns = [
                r"\bдобрый\s+вечер\b", r"\bсегодня\s+ночью\b", r"\bэтой\s+ночью\b",
                r"\bуже\s+почти\s+полноч", r"\bпочти\s+полноч", r"\bсейчас\s+ноч",
                r"\bвечерн(?:ий|яя|ее|его|ем|им)\s+эфи", r"\bночн(?:ой|ая|ое|ого|ом)\s+эфи",
            ]
            if any(re.search(p, low, flags=re.IGNORECASE) for p in patterns):
                out.append(f"сейчас по компьютеру день ({ctx.get('time_text') or _current_time_text()}), нельзя говорить про вечер/ночь/полночь")
        elif daypart == "вечер":
            if re.search(r"\bдоброе\s+утро\b|\bсейчас\s+утро\b|\bполдень\b|\bполноч", low, flags=re.IGNORECASE):
                out.append(f"сейчас вечер ({ctx.get('time_text') or _current_time_text()}), нельзя путать время суток")
        elif daypart == "утро":
            if re.search(r"\bдобрый\s+вечер\b|\bсегодня\s+ночью\b|\bполноч", low, flags=re.IGNORECASE):
                out.append(f"сейчас утро ({ctx.get('time_text') or _current_time_text()}), нельзя говорить про вечер/ночь/полночь")
        else:  # ночь
            if re.search(r"\bдобрый\s+день\b|\bдоброе\s+утро\b|\bсейчас\s+день\b", low, flags=re.IGNORECASE):
                out.append(f"сейчас ночь ({ctx.get('time_text') or _current_time_text()}), нельзя путать время суток")
    prev = str(ctx.get("previous_track_name") or ctx.get("planned_previous_track") or "").lower()
    if ctx.get("intro_allowed") and (not prev or "ничего" in prev or "ещё" in prev or "еще" in prev):
        startup_bad = [
            r"\bтолько\s+что\s+звучал", r"\bтолько\s+что\s+слушал", r"\bмы\s+слушали\b",
            r"\bперед\s+нами\s+было\b", r"\bпредыдущ", r"\bпосле\s+прошлого\s+трека\b",
        ]
        if any(re.search(p, low, flags=re.IGNORECASE) for p in startup_bad):
            out.append("это старт эфира, предыдущих треков ещё не было")
    roleplay_bad = ["кабина грузовика", "салон грузовика", "грузовик", "дальнобойщика", "дальнобоя", "рейс", "за рулем", "за рулём"]
    if any(x in low for x in roleplay_bad):
        out.append("это обычное музыкальное радио, не трансляция из грузовика/рейса")
    if re.search(r"\([^\n]{0,160}(включается|включаем|следующий трек|подводит)[^\n]{0,160}\)|\*[^\n]{0,160}(включается|подводит|следующий трек)[^\n]{0,160}\*", str(text or ""), flags=re.IGNORECASE):
        out.append("нельзя писать сценические ремарки вроде 'включается трек'")
    return out


def repair_time_context_text(text: str, ctx: Optional[Dict[str, Any]] = None) -> str:
    """Last-resort cleanup if all retries failed. Prefer retry, but never let
    blatant clock lies reach TTS.
    """
    ctx = ctx or {}
    hour = int(ctx.get("computer_hour", time.localtime().tm_hour) or 0)
    if expected_daypart_for_hour(hour) == "утро":
        text = re.sub(r"(?i)\bдобрый\s+вечер\b", "Доброе утро", text)
        text = re.sub(r"(?i)\bсегодня\s+ночью\b", "сегодня утром", text)
        text = re.sub(r"(?i)\bвечерн(?:ий|яя|ее|его|ем|им)\b", "утренний", text)
        text = re.sub(r"(?i)\bпраздник\s+вечера\b", "праздник этого эфира", text)
    if expected_daypart_for_hour(hour) == "день":
        text = re.sub(r"(?i)\bдобрый\s+вечер\b", "Добрый день", text)
        text = re.sub(r"(?i)\bуже\s+почти\s+полночь\b", f"сейчас {ctx.get('time_text') or _current_time_text()}", text)
        text = re.sub(r"(?i)\bпочти\s+полночь\b", f"сейчас {ctx.get('time_text') or _current_time_text()}", text)
        text = re.sub(r"(?i)\bсегодня\s+ночью\b", "сегодня днём", text)
        text = re.sub(r"(?i)\bэтой\s+ночью\b", "сегодня", text)
        text = re.sub(r"(?i)\bночной\s+эфир\b", "дневной эфир", text)
        text = re.sub(r"(?i)\bвечерний\s+эфир\b", "дневной эфир", text)
    return text

def strip_spoken_host_names(text: str, host_names: List[str]) -> str:
    out_lines = []
    prefixes = ["Ведущий", "DJ", "Радиоведущий"] + list(host_names)
    prefix_re = "|".join(re.escape(p) for p in sorted(set(prefixes), key=len, reverse=True) if p)
    for raw in text.replace("\r", "\n").splitlines():
        line = " ".join(raw.strip().split())
        if not line:
            continue
        if prefix_re:
            line = re.sub(rf"^(?:{prefix_re})\s*[:：]\s*", "", line, flags=re.IGNORECASE).strip()
        line = re.sub(r"^[-–—•*]+\s*", "", line).strip()
        if line:
            out_lines.append(line)
    return "\n".join(out_lines).strip()


