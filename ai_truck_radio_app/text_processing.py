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

    stage_aliases = {
        r"усмех\w*|хихик\w*|сме[её]тся|смешок|со смехом": "[laughter]",
        r"вздых\w*|со вздохом": "[sigh]",
        r"удивл[её]нно|с удивлением": "[surprise-ah]",
        r"недовольн\w*|ворчит": "[dissatisfaction-hnn]",
    }
    for pattern, tag in stage_aliases.items():
        text = re.sub(rf"\(\s*(?:{pattern})\s*\)", tag if enabled else "", text, flags=re.IGNORECASE)
    text = re.sub(r"\([^()\n]{1,100}\)", "", text)

    def repl(match: re.Match[str]) -> str:
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
    # Models sometimes put the emotion between the speaker and the colon:
    # ``Ирина [laughter]:``.  The dialogue parser then attributes that line to
    # the previous speaker.  OmniVoice expects the tag after the colon too.
    text = re.sub(
        r"(?<![\wА-Яа-яЁё])([А-ЯЁA-Z][А-Яа-яЁёA-Za-z-]{1,31})\s*(\[[^\]\n]{1,40}\])\s*[:：]",
        r"\1: \2",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def strip_omnivoice_nonverbal_tags(text: str) -> str:
    if not text:
        return text
    return re.sub(r"\s+", " ", re.sub(r"\[[^\[\]\n]{1,40}\]", "", text)).strip()


def sanitize_general_radio_text(text: str) -> str:
    """General cleanup for game/truck-simulator roleplay phrases.

    It is deliberately generic: no artist/song-specific substitutions, only
    removal/rewording of the unwanted broadcast framing.
    """
    if not text:
        return text
    banned_sentence = re.compile(
        r"(?i)(?:^|(?<=[.!?…])\s+)[^.!?…\n]{0,220}"
        r"(?:\bVR\b|виртуальн|Euro\s+Truck|Simulator|симулятор|кабин|грузовик|дальнобо|рейс|"
        r"за\s+рул[её]м|трасс|фары|зеркал[ао]|штраф[а-яё]*|перестроен[а-яё]*)"
        r"[^.!?…\n]*[.!?…]?"
    )
    text = banned_sentence.sub(" ", text)
    replacements = [
        (r"(?i)\bдальнобойщикам\b", "слушателям"),
        (r"(?i)\bдальнобоям\b", "слушателям"),
        (r"(?i)\bдальнобойщики\b", "слушатели"),
        (r"(?i)\bдальнобойщик\s+Андрей\b", "слушатель Андрей"),
        (r"(?i)\bводитель\s+Андрей\b", "слушатель Андрей"),
        (r"(?i)\bза\s+рул[её]м\b", "у приёмника"),
        (r"(?i)\bв\s+VR\b", "в эфире"),
        (r"(?i)\bVR\b", "эфир"),
        (r"(?i)\bвиртуальн(?:ая|ой|ую|ые|ых|ом|ым)?\s+трасс[а-яё]*\b", "музыкальный эфир"),
        (r"(?i)\bсимулятор[а-яё]*\b", "эфир"),
        (r"(?i)\bв\s+кабине\s+(?:своего\s+)?грузовика\b", "у себя"),
        (r"(?i)\bиз\s+кабины\s+грузовика\b", "из студии"),
        (r"(?i)\bкабина\s+грузовика\b", "атмосфера студии"),
        (r"(?i)\bкабин[аеуы]?\b", "эфир"),
        (r"(?i)\bсалон\s+грузовика\b", "домашний плейлист"),
        (r"(?i)\bгрузовик[ае]?\b", "эфир"),
        (r"(?i)\bрейс[а-яё]*\b", "эфир"),
        (r"(?i)\bна\s+трассе\b", "в эфире"),
        (r"(?i)\bтрасса\b", "эфир"),
        (r"(?i)\bEuro\s+Truck\s+Simulator\s*2?\b", "музыкальный эфир"),
        (r"(?i)\bфары\s+режут\s+темноту\b", "музыка звучит особенно атмосферно"),
        (r"(?i)\bснег\s+хрустит\s+под\s+кол[её]сами\b", "зимний образ звучит только в самой песне"),
        (r"(?i)\bдолгих\s+ночных\s+поездок\b", "спокойного эфира"),
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
        ('FM', 'ЭФЭМ'),
    ]
    for src, dst in replacements:
        text = text.replace(src, dst)
    # Small local models occasionally copy the correct minute value but change
    # the feminine number required by «минута/минуты».
    minute_forms = {
        "пятьдесят один": "пятьдесят одна",
        "сорок один": "сорок одна",
        "тридцать один": "тридцать одна",
        "двадцать один": "двадцать одна",
        "один": "одна",
        "пятьдесят два": "пятьдесят две",
        "сорок два": "сорок две",
        "тридцать два": "тридцать две",
        "двадцать два": "двадцать две",
        "два": "две",
    }
    for wrong, correct in minute_forms.items():
        text = re.sub(rf"(?i)\b{wrong}\s+минут(?:а|ы)\b", f"{correct} минуты" if correct.endswith("две") else f"{correct} минута", text)
    # Small models also use an accusative form here: «пятьдесят одну
    # минуту».  In a clock reading the nominative form is required.
    accusative_minute_forms = {
        "пятьдесят одну": "пятьдесят одна",
        "сорок одну": "сорок одна",
        "тридцать одну": "тридцать одна",
        "двадцать одну": "двадцать одна",
        "одну": "одна",
    }
    for wrong, correct in accusative_minute_forms.items():
        text = re.sub(rf"(?i)\b{wrong}\s+минуту\b", f"{correct} минута", text)
    # Fix accidental missing space after English/artist names and Russian words: битAaron -> бит Aaron.
    text = re.sub(r'([А-Яа-яЁё])([A-Z][A-Za-z])', r'\1 \2', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def soften_tts_exclamations(text: str) -> str:
    """Prevent reference voices from turning every exclamation into a shout."""
    if not text:
        return text
    text = re.sub(r"!{2,}", ".", text)
    text = re.sub(r"(?<!\?)!", ".", text)
    return re.sub(r"\.{2,}", ".", text)




def postprocess_host_text_for_air(text: str, ctx: Optional[Dict[str, Any]] = None) -> str:
    """Final safety cleanup before TTS: remove prompt leaks, stage directions,
    broken emoji hex chunks, and startup references to non-existing previous songs.
    """
    ctx = ctx or {}
    text = str(text or "")
    text = re.sub(r"<0x[0-9A-Fa-f]{2,8}>", "", text)
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"\*+\s*(В конце блока|Включается|Подводит|После этой речи|Музыка включается).*?(?:\*+|$)", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\([^\n]{0,160}(улыб|мягко|энергично|подводит|ремарка|включаем|включается|следующий трек)[^\n]{0,160}\)", "", text, flags=re.IGNORECASE)
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
        all_markers = "|".join(re.escape(x) for x in dict.fromkeys(all_host_names) if x)
        for bad_name in forbidden:
            bad_re = re.escape(bad_name)
            if all_markers:
                text = re.sub(
                    rf"(?<![\wА-Яа-яЁё]){bad_re}\s*[:：]\s*.*?(?=(?<![\wА-Яа-яЁё])(?:{all_markers})\s*[:：]|$)",
                    "",
                    text,
                    flags=re.IGNORECASE,
                )
        for name in allowed:
            name_re = re.escape(name)
            text = re.sub(rf"({name_re}\s*[:：])\s*\1+", r"\1 ", text)
            for bad_name in forbidden:
                bad_re = re.escape(bad_name)
                text = re.sub(rf"({name_re}\s*[:：])\s*(?:{bad_re}\s*[:：]\s*)+", r"\1 ", text)
            # Markdown remnants and small-model punctuation occasionally yield
            # «Максим:.реплика».  Keep labels consistent for the panel and TTS.
            text = re.sub(rf"(?i)\b({name_re})\s*[:：]\s*[.]?\s*", r"\1: ", text)
        allowed_markers = "|".join(re.escape(name) for name in allowed)
        if text and not re.match(rf"^\s*(?:{allowed_markers})\s*[:：]", text, flags=re.IGNORECASE):
            # Keep panel text and TTS segmentation consistent: otherwise the
            # parser drops everything before the first labelled replica.
            text = f"{allowed[0]}: {text}"
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
            def preserve_case(match: re.Match[str], replacement: str = b) -> str:
                return replacement[:1].upper() + replacement[1:] if match.group(0)[:1].isupper() else replacement

            text = re.sub(a, preserve_case, text, flags=re.IGNORECASE)
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
    # TTS stress marks are combining accents (for example, ``пого́да``).
    # Strip them for factual guards so the generated pronunciation form cannot
    # bypass checks written for ordinary Russian spelling.
    # Remove only TTS stress marks.  NFD + removing every combining mark also
    # turns Russian «й» into «и» and makes ordinary words such as
    # «здравствуйте» impossible to match reliably.
    folded = low.replace("\u0301", "").replace("ё", "е")
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
            r"\bперед\s+нами\s+было\b", r"\bпосле\s+прошлого\s+трека\b",
        ]
        if any(re.search(p, low, flags=re.IGNORECASE) for p in startup_bad):
            out.append("это старт эфира, предыдущих треков ещё не было")
        if re.search(r"\bпосле\s+вчерашн\w+[^.!?]{0,80}\b(?:эфир|вечер|музык)\w*", folded, flags=re.IGNORECASE):
            out.append("это старт подготовленного эфира; нельзя выдумывать вчерашнюю программу или музыку")
    if not ctx.get("intro_allowed"):
        repeated_greeting = (
            r"\b(?:доброе\s+утро|добрый\s+день|добрый\s+вечер|доброй\s+ночи)\b|"
            r"\b(?:волна\s+(?:эфэм|fm)|станци\w*)[^.!?]{0,60}\bприветству\w*|"
            r"\b(?:добро\s+пожаловать|начинаем\s+эфир|открываем\s+эфир|с\s+вами\s+снова)\b|"
            r"\b(?:рад|рада|рады)\s+(?:снова\s+)?приветствовать\b|"
            r"\bприветству\w*\s+(?:всех\s+)?(?:слушател\w*|вас)\b|"
            r"\bздравствуй(?:те)?\s*,?\s*(?:дорог\w*\s+|уважаем\w*\s+)?(?:слушател\w*|друзья)\b|"
            r"\bвсем\s+привет\b|"
            r"\b(?:начало|начинаем|начн[её]м)\s+(?:этого\s+|нового\s+)?дн\w*\b|"
            r"\bготов\w*\s+(?:встречать\s+|к\s+)?нов\w+\s+дн\w*\b|"
            r"\bнов\w+\s+день\s+(?:начин\w*|начал\w*|старт\w*)\b|"
            r"\bстанци\w*[^.!?]{0,40}\bначинает\s+(?:свою\s+)?работу\b"
        )
        if re.search(repeated_greeting, folded, flags=re.IGNORECASE):
            out.append("эфир уже идёт; нельзя повторно здороваться или заново приветствовать слушателей")
        host_names = [
            str(host.get("name") or "").strip()
            for host in (ctx.get("hosts") or [])
            if isinstance(host, dict) and str(host.get("name") or "").strip()
        ]
        if host_names:
            host_markers = "|".join(re.escape(name) for name in host_names)
            if re.search(
                rf"(?<!\w)(?:{host_markers})\s*[:：]\s*привет\s+всем\b",
                folded,
                flags=re.IGNORECASE,
            ):
                out.append("эфир уже идёт; ведущий не должен начинать новый блок с повторного приветствия")
    roleplay_bad = ["кабина грузовика", "салон грузовика", "грузовик", "дальнобойщика", "дальнобоя", "рейс", "за рулем", "за рулём", "vr", "симулятор"]
    if any(x in low for x in roleplay_bad):
        out.append("это обычное музыкальное радио, без игровых и автомобильных ролевых образов")
    if re.search(r"\([^\n]{0,160}(включается|включаем|следующий трек|подводит)[^\n]{0,160}\)|\*[^\n]{0,160}(включается|подводит|следующий трек)[^\n]{0,160}\*", str(text or ""), flags=re.IGNORECASE):
        out.append("нельзя писать сценические ремарки вроде 'включается трек'")
    weather_city = str(ctx.get("weather_city") or "").strip()
    if weather_city and not re.search(r"москв", weather_city, flags=re.IGNORECASE) and re.search(r"\bмоскв\w*", low, flags=re.IGNORECASE):
        out.append(f"город эфира и погоды — {weather_city}; Москву называть нельзя")
    if not str(ctx.get("weather_text") or "").strip():
        unverified_weather_patterns = [
            r"\bпогод\w*",
            r"\bтемператур\w*",
            r"\b(?:плюс|минус)\s+\d{1,2}\s+градус",
            r"\b\d{1,2}\s+градус(?:а|ов)?\b",
            r"\b(?:на\s+улице|за\s+окном)\s+(?:тепл|холод|жарк|ясн|пасмур|солнеч|облач|ветрен|дожд|снеж|морозн)\w*",
            r"\b(?:солнышк|солнц)\w*\s+(?:свет|выгля|вышл|поднял|сел|садит|зашл|проснул)\w*",
            r"\b(?:солнышк|солнц)\w*[^.!?]{0,40}\b(?:проснул|встал|взош)\w*",
            r"\b(?:идет|льет|начал|ожидает)\w*\s+(?:дожд|снег)\w*",
            r"\b(?:дождлив|снежн|ветрен|солнечн|облачн|пасмурн|морозн)\w*",
            r"\b(?:рассвет|закат)\w*",
        ]
        if any(re.search(pattern, folded, flags=re.IGNORECASE) for pattern in unverified_weather_patterns):
            out.append(
                "нет проверенных данных о погоде; нельзя упоминать погоду, температуру, "
                "солнце, осадки, ветер, рассвет или закат"
            )
    expected_horoscope = ctx.get("horoscope_expected") or []
    if expected_horoscope:
        if re.search(r"\bпрогноз\s+(?:был|будет)\s+(?:про|о)\b", low, flags=re.IGNORECASE):
            out.append("гороскоп нужно читать как настоящий прогноз, а не пересказывать его тему")
        for item in expected_horoscope:
            sign = str(item.get("sign") or "").strip() if isinstance(item, dict) else ""
            if sign and not re.search(rf"(?<!\w){re.escape(sign)}\s*:", str(text or ""), flags=re.IGNORECASE):
                out.append(f"в гороскопе отсутствует точная строка «{sign}: прогноз»")
        expected_signs = {
            str(item.get("sign") or "").strip().casefold()
            for item in expected_horoscope
            if isinstance(item, dict) and str(item.get("sign") or "").strip()
        }
        zodiac_forms = {
            "овен": r"овен|овны",
            "телец": r"телец|тельцы",
            "близнецы": r"близнецы",
            "рак": r"рак|раки",
            "лев": r"лев|львы",
            "дева": r"дева|девы",
            "весы": r"весы",
            "скорпион": r"скорпион|скорпионы",
            "стрелец": r"стрелец|стрельцы",
            "козерог": r"козерог|козероги",
            "водолей": r"водолей|водолеи",
            "рыбы": r"рыбы",
        }
        for canonical, forms in zodiac_forms.items():
            if canonical not in expected_signs and re.search(rf"(?<!\w)(?:{forms})\s*:", folded, flags=re.IGNORECASE):
                out.append(f"в этом блоке нет проверенного прогноза для знака «{canonical.capitalize()}»")
        if re.search(
            r"\bостальн\w*\s+знак\w*[^.!?]{0,50}\b(?:завтра|утром|вечером|ночью)\b",
            folded,
            flags=re.IGNORECASE,
        ):
            out.append("продолжение гороскопа можно обещать только в следующий выход, без выдуманного времени")
    if ctx.get("riddle_question_block"):
        answer_reveal_patterns = [
            r"\bправильн\w*\s+ответ\w*(?:\s+на\s+[^.!?]{1,40})?\s*(?:[—–:=-]|это\b|является\b)",
            r"\bответ\s+на\s+(?:нашу|эту|сегодняшн\w+)\s+загадк\w*\s*[—–:=-]",
            r"\bответ(?:ом)?\s+(?:является|будет|это)\b",
        ]
        if any(re.search(pattern, folded, flags=re.IGNORECASE) for pattern in answer_reveal_patterns):
            out.append("в блоке вопроса нельзя раскрывать или объявлять ответ на загадку")
        delayed_daypart = (
            r"\bответ\w*[^.!?]{0,80}\b(?:завтра|утром|вечером|ночью)\b|"
            r"\b(?:до\s+встречи|встретимся)[^.!?]{0,30}\b(?:завтра|утром|вечером|ночью)\b"
        )
        if re.search(delayed_daypart, folded, flags=re.IGNORECASE):
            out.append("ответ должен прозвучать в следующий выход ведущих, без обещаний утра, вечера или завтра")
    if ctx.get("riddle_answer_block"):
        if re.search(r"\bвчерашн\w*\s+загад", folded, flags=re.IGNORECASE):
            out.append("ответ относится к предыдущему выходу ведущих, а не ко вчерашнему эфиру")
        answer = str(ctx.get("riddle_correct_answer") or "").strip()
        normalized_answer = answer.casefold().replace("\u0301", "").replace("ё", "е")
        answer_variants = {normalized_answer}
        answer_variants.add(re.sub(r"^(?:число|слово|буква)\s+", "", normalized_answer))
        answer_variants.discard("")
        if answer_variants and not any(
            re.search(rf"(?<!\w){re.escape(variant)}(?!\w)", folded)
            for variant in answer_variants
        ):
            out.append("в блоке ответа не прозвучал проверенный правильный ответ на загадку")
        if not re.search(r"\b(?:ответ|разгадк)\w*\b", folded):
            out.append("ответ на загадку нужно объявить явно, а не оставлять как догадку в разговоре")
    wrong_correct = str(ctx.get("wrong_game_correct_answer") or "").strip()
    if wrong_correct:
        normalized_correct = wrong_correct.casefold().replace("\u0301", "").replace("ё", "е")
        if normalized_correct and re.search(rf"(?<!\w){re.escape(normalized_correct)}(?!\w)", folded, flags=re.IGNORECASE):
            out.append("в игре «ответь неправильно» прозвучал настоящий правильный ответ")
    if ctx.get("force_guest"):
        guest_name = str(ctx.get("guest_name") or "Гость").strip() or "Гость"
        if not re.search(rf"(?<!\w){re.escape(guest_name)}\s*[:：]", str(text or ""), flags=re.IGNORECASE):
            out.append(f"гость должен получить отдельную реплику с подписью «{guest_name}:»")
        story_data = ctx.get("guest_story_data") or {}
        if not isinstance(story_data, dict):
            story_data = {}
        story = str(story_data.get("story") or story_data.get("text") or "").strip()
        if story:
            generic_stems = {
                "гость", "истори", "музык", "песня", "композ", "слушат", "радио",
                "эфир", "настро", "расска", "хорош", "сегодн",
            }

            def distinctive_stems(value: str) -> set[str]:
                tokens = re.findall(r"[а-яё]{6,}", value.casefold())
                return {token[:6] for token in tokens if token[:6] not in generic_stems}

            expected_story_stems = distinctive_stems(story)
            configured_names = [
                str(host.get("name") or "").strip()
                for host in (ctx.get("hosts") or [])
                if isinstance(host, dict) and str(host.get("name") or "").strip()
            ]
            if guest_name.casefold() not in {name.casefold() for name in configured_names}:
                configured_names.append(guest_name)
            speaker_markers = "|".join(re.escape(name) for name in configured_names)
            guest_match = re.search(
                rf"(?<!\w){re.escape(guest_name)}\s*[:：]\s*(.*?)(?=(?<!\w)(?:{speaker_markers})\s*[:：]|$)",
                folded,
                flags=re.IGNORECASE,
            ) if speaker_markers else None
            guest_spoken = guest_match.group(1) if guest_match else ""
            spoken_story_stems = distinctive_stems(guest_spoken)
            needed = min(len(expected_story_stems), max(2, (len(expected_story_stems) + 1) // 2))
            if needed and len(expected_story_stems & spoken_story_stems) < needed:
                out.append("реплика гостя не сохраняет проверенную историю из подготовленного пакета")
            declared_name = re.search(
                r"\bменя\s+зовут\s+([А-ЯЁ][А-Яа-яЁё-]{1,31})",
                str(text or ""),
                flags=re.IGNORECASE,
            )
            if declared_name and declared_name.group(1).casefold() not in story.casefold():
                out.append("гость назвал вымышленное имя, которого нет в подготовленной истории")
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
    weather_city = str(ctx.get("weather_city") or "").strip()
    if weather_city and not re.search(r"москв", weather_city, flags=re.IGNORECASE):
        text = re.sub(r"(?i)\bмоскв(?:а|е|ы|ой|у)\b", weather_city, text)
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


