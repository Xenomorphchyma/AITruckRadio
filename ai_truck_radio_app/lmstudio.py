# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ai_truck_radio_app.config import RUS_MONTHS, RUS_WEEKDAYS, log, require_http_url
from ai_truck_radio_app.text_processing import clean_host_text, sanitize_general_radio_text
from ai_truck_radio_app.tracks import Track


def _current_time_text() -> str:
    now = time.localtime()
    weekday = RUS_WEEKDAYS[now.tm_wday]
    month = RUS_MONTHS[now.tm_mon - 1]
    return f"{now.tm_hour:02d}:{now.tm_min:02d}, {weekday}, {now.tm_mday} {month} {now.tm_year}"


def _compact_prompt_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    limit = max(1, int(max_chars))
    if len(text) <= limit:
        return text
    clipped = text[: max(1, limit - 1)].rstrip()
    boundary = max(clipped.rfind(". "), clipped.rfind("; "), clipped.rfind(", "), clipped.rfind(" "))
    if boundary >= max(20, limit // 2):
        clipped = clipped[:boundary].rstrip(" ,;")
    return clipped + "…"


def _prompt_daypart(ctx: Dict[str, Any]) -> str:
    hour = int(ctx.get("computer_hour", time.localtime().tm_hour) or 0)
    if 5 <= hour <= 11:
        return "утро"
    if 12 <= hour <= 17:
        return "день"
    if 18 <= hour <= 22:
        return "вечер"
    return "ночь"


def _host_output_token_limit(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> int:
    configured = max(96, int(cfg.get("lm_max_tokens", 620) or 620))
    length = str(ctx.get("dj_length", "short") or "short").lower()
    length_cap = {"short": 360, "medium": 520, "long": 760}.get(length, 520)
    horoscope_count = len(ctx.get("horoscope_expected") or [])
    if horoscope_count:
        length_cap = max(length_cap, min(900, 180 + horoscope_count * 60))
    reasoning = str(cfg.get("lm_reasoning_effort", "auto") or "auto").strip().lower()
    reasoning_reserve = {"low": 400, "medium": 800, "high": 1200}.get(reasoning, 0)
    if reasoning_reserve:
        # LM Studio accounts hidden reasoning and final text against the same
        # max_tokens budget. Preserve the normal radio-text allowance instead
        # of letting a thinking model consume it before producing an answer.
        length_cap += reasoning_reserve
    hard_cap = max(96, int(cfg.get("lm_host_max_tokens", 760) or 760))
    if reasoning_reserve:
        hard_cap = max(hard_cap, 1400)
    return max(96, min(configured, length_cap, hard_cap))


def _compact_host_system(cfg: Dict[str, Any]) -> str:
    limit = max(240, min(2000, int(cfg.get("lm_host_system_max_chars", 900) or 900)))
    persona = str(cfg.get("radio_persona") or "Ты пишешь готовый русский текст музыкального радио.")
    return _compact_prompt_text(persona, limit)


def build_compact_host_prompt(
    cfg: Dict[str, Any],
    previous_track: Optional[Track],
    next_track: Optional[Track],
    ctx: Dict[str, Any],
) -> str:
    """Build a bounded, priority-ordered prompt suitable for a small local LM."""
    max_chars = max(2600, min(12000, int(cfg.get("lm_host_prompt_max_chars", 4800) or 4800)))
    intro = bool(ctx.get("intro_allowed", False))
    hosts = [host for host in (ctx.get("hosts") or []) if isinstance(host, dict) and str(host.get("name") or "").strip()]
    host_names = [str(host.get("name") or "").strip() for host in hosts] or ["Ведущий"]
    two_hosts = bool(ctx.get("two_hosts") and len(host_names) >= 2)
    previous_name = previous_track.display_name if previous_track else "НЕТ"
    nonblocking_intro = intro and not bool(cfg.get("startup_intro_blocking", True))
    if nonblocking_intro and not cfg.get("startup_intro_track_specific", False):
        next_name = "первый трек из локального плейлиста"
    else:
        next_name = next_track.display_name if next_track else "следующий трек из локального плейлиста"

    dj_length = str(ctx.get("dj_length", "short") or "short").lower()
    task = _compact_prompt_text(ctx.get("dj_instruction") or "Короткая радиоподводка.", 260)
    topic = _compact_prompt_text(ctx.get("dj_topic_label") or "музыка", 100)
    time_text = str(ctx.get("time_text") or _current_time_text())
    spoken_time = str(ctx.get("spoken_time_text") or "").strip()
    combined_time = time_text if not spoken_time or spoken_time in time_text else f"{time_text}; вслух: {spoken_time}"
    mode = "СТАРТ ЭФИРА, предыдущих треков не было" if intro else "ЭФИР УЖЕ ИДЁТ"

    core_lines = [
        "[ЗАДАЧА]",
        f"{task} Тема: {topic}.",
        "[ПРИОРИТЕТНЫЕ ФАКТЫ]",
        f"Станция: {_compact_prompt_text(ctx.get('station_name') or 'Волна FM', 100)}.",
        f"Режим: {mode}.",
        f"Ведущие: {', '.join(host_names)}.",
        f"Предыдущий трек: {'НЕТ' if intro else _compact_prompt_text(previous_name, 220)}.",
        f"Следующий трек: {_compact_prompt_text(next_name, 220)}.",
        f"Время: {_compact_prompt_text(combined_time, 260)}; сейчас {_prompt_daypart(ctx)}.",
    ]

    weather = str(ctx.get("weather_text") or "").strip()
    weather_city = str(ctx.get("weather_city") or "").strip()
    if weather and weather_city and weather_city.casefold() not in weather.casefold():
        weather = f"{weather_city}; {weather}"
    entertainment = str(ctx.get("entertainment_text") or "").strip()
    horoscope_parts = []
    for item in ctx.get("horoscope_expected") or []:
        if not isinstance(item, dict):
            continue
        sign = str(item.get("sign") or "").strip()
        forecast = str(item.get("text") or "").strip()
        if sign and forecast:
            horoscope_parts.append(f"{sign}: {forecast}")
    verified_horoscope = " | ".join(horoscope_parts)
    normalized_entertainment = " ".join(entertainment.casefold().split())
    if verified_horoscope and all(" ".join(part.casefold().split()) in normalized_entertainment for part in horoscope_parts):
        verified_horoscope = ""

    recent_unique: List[str] = []
    seen_recent = set()
    for item in reversed(list(ctx.get("recent_host_texts") or [])):
        compact = _compact_prompt_text(item, 180)
        key = compact.casefold()
        if compact and key not in seen_recent:
            recent_unique.append(compact)
            seen_recent.add(key)
        if len(recent_unique) >= 2:
            break
    recent_unique.reverse()

    optional_fields = [
        ("Исправить прошлую ошибку", ctx.get("retry_reason"), 300),
        ("Рубрика", entertainment, 1000),
        ("Проверенные прогнозы", verified_horoscope, 1200),
        ("Инструкция рубрики", ctx.get("entertainment_instruction"), 300),
        ("Погода", weather, 380),
        ("Новость", ctx.get("news_text"), 420),
        ("Привет слушателя", ctx.get("greeting_text"), 260),
        ("Гость", "Разрешены реплики Гость:; гость не заменяет ведущих" if ctx.get("force_guest") else "", 180),
        ("Профиль предыдущего", ctx.get("previous_track_info") if not intro else "", 420),
        ("Профиль следующего", ctx.get("next_track_info"), 420),
        ("Стиль", f"{ctx.get('style') or ''} {ctx.get('style_prompt') or ''}", 220),
        ("Не повторять", " || ".join(recent_unique), 380),
    ]

    if dj_length == "long":
        length_rule = "5–7 коротких реплик" if two_hosts else "5–7 предложений"
    elif dj_length == "medium":
        length_rule = "около 4 коротких реплик" if two_hosts else "3–4 предложения"
    else:
        length_rule = "2–3 короткие реплики" if two_hosts else "1–2 предложения"
    prefixes = ", ".join(f"«{name}:»" for name in host_names)
    if two_hosts:
        speaker_rule = f"Допустимые подписи — {prefixes}. Каждый из первых двух ведущих должен сказать содержательную реплику."
    else:
        forbidden_names = [
            str(name).strip()
            for name in (ctx.get("all_host_names") or [])
            if str(name).strip() and str(name).strip() not in host_names
        ]
        forbidden = f" Другие подписи запрещены: {', '.join(forbidden_names)}." if forbidden_names else ""
        speaker_rule = f"Единственная допустимая подпись — {prefixes}.{forbidden}"

    dynamic_rules = []
    if intro:
        dynamic_rules.append(
            "На старте нельзя утверждать, что музыка уже звучала, и нельзя выдумывать вчерашний эфир; "
            "подводи только к первому треку."
        )
    else:
        dynamic_rules.append(
            "Эфир уже идёт: не говори «доброе утро/добрый день/добрый вечер», «здравствуйте, слушатели», "
            "«добро пожаловать», «начинаем эфир», «начало нового дня» или «готовы к новому дню» и не приветствуй станцию заново; "
            "следующий трек не называй уже прозвучавшим."
        )
    if weather:
        dynamic_rules.append("Погоду пересказывай только из строки «Погода», сохрани город и числа.")
    else:
        dynamic_rules.append(
            "Проверенных данных о погоде НЕТ: не упоминай погоду, температуру, солнце, "
            "осадки, облачность, ветер, рассвет или закат и не делай выводов о них по времени."
        )
    entertainment_hint = f"{topic} {ctx.get('entertainment_instruction') or ''}".casefold()
    if ctx.get("riddle_answer_block"):
        dynamic_rules.append(
            "В блоке ответа сначала назови ответ и не задавай новую загадку. "
            "Это загадка из предыдущего выхода ведущих, не называй её вчерашней."
        )
    elif ctx.get("riddle_question_block"):
        dynamic_rules.append("Задай загадку без ответа; ответ будет в следующий выход, не обещай «завтра».")
    elif "загад" in entertainment_hint:
        # Legacy callers may not carry explicit rubric flags.  Prefer question
        # mode unless the instruction clearly identifies a past riddle: the
        # phrase «ответ прозвучит» belongs to a question and used to be
        # misclassified as an answer block.
        if "прошл" in entertainment_hint and "назови ответ" in entertainment_hint:
            dynamic_rules.append("В блоке ответа сначала назови ответ и не задавай новую загадку.")
        else:
            dynamic_rules.append("Задай загадку без ответа; ответ будет в следующий выход, не обещай «завтра».")
    if horoscope_parts:
        dynamic_rules.append("Внутри реплики сохрани метки знаков вида «Овен: прогноз» для каждого проверенного знака.")
    if "неправиль" in entertainment_hint or "неверн" in entertainment_hint:
        dynamic_rules.append(
            "Неверный игровой ответ явно обозначь как намеренно неверный, не как факт. "
            "Настоящий правильный ответ из данных не произноси вообще, даже перед исправлением или шуткой."
        )
    if ctx.get("allow_omnivoice_nonverbal_tags"):
        dynamic_rules.append(
            "Допустим максимум один тег после подписи: [laughter], [sigh], [confirmation-en], [question-en], "
            "[question-ah], [question-oh], [question-ei], [question-yi], [surprise-ah], [surprise-oh], "
            "[surprise-wa], [surprise-yo], [dissatisfaction-hnn]."
        )
    if ctx.get("force_guest"):
        dynamic_rules.append(
            "Гость должен получить отдельную содержательную реплику с подписью «Гость:». "
            "Гость пересказывает только подготовленную историю из поля «Рубрика»: не придумывай ему имя, "
            "биографию, поездку, событие или другую историю."
        )
    suffix_lines = [
        "[СХЕМА ОТВЕТА]",
        speaker_rule,
        f"Объём: {length_rule}. Каждая смена говорящего — новая строка «Имя: текст».",
        "[ЖЁСТКИЕ ОГРАНИЧЕНИЯ]",
        "Только готовый русский текст эфира: без markdown, thinking, списков, служебных слов, вложенных подписей и ремарок.",
        "Не выдумывай факты: реальные сведения бери только из блока фактов. Без игр, VR, кабин, грузовиков, рейсов, трасс и дорожных клише.",
        "Не меняй имена, город, числа и названия треков. Текст должен быть безопасен для TTS; последняя реплика заканчивается . ! ? или …",
        *dynamic_rules,
    ]
    if cfg.get("lm_append_no_think", True):
        suffix_lines.append("/no_think")

    core = "\n".join(core_lines)
    suffix = "\n".join(suffix_lines)
    remaining = max(0, max_chars - len(core) - len(suffix) - 2)
    selected: List[str] = []
    seen_values = set()
    for label, value, field_limit in optional_fields:
        compact = _compact_prompt_text(value, field_limit)
        normalized = compact.casefold()
        if not compact or normalized in seen_values:
            continue
        line = f"{label}: {compact}"
        if len(line) + 1 <= remaining:
            selected.append(line)
            remaining -= len(line) + 1
            seen_values.add(normalized)
            continue
        value_budget = remaining - len(label) - 3
        if value_budget >= 60:
            line = f"{label}: {_compact_prompt_text(compact, value_budget)}"
            selected.append(line)
            remaining -= len(line) + 1
            seen_values.add(normalized)
    middle = "\n".join(selected)
    return core + ("\n" + middle if middle else "") + "\n" + suffix


class LMStudioClient:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.base_url = str(cfg["lm_base_url"]).rstrip("/")
        self.timeout = int(cfg.get("lm_timeout_sec", 25))
        self.model = str(cfg.get("lm_model") or "local-model")

    def _request_json(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        url = require_http_url(url)
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=int(timeout or self.timeout)) as resp:  # nosec B310
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1200]
            raise RuntimeError(f"LM Studio HTTP {exc.code}: {detail}") from exc
        return json.loads(raw)

    def list_models(self) -> List[str]:
        return list(self.probe_models()["models"])

    def probe_models(self) -> Dict[str, Any]:
        """Distinguish a reachable server with no model from no server at all."""
        try:
            data = self._request_json("GET", f"{self.base_url}/models")
            catalog_models: List[str] = []
            for item in data.get("data", []):
                if isinstance(item, dict) and item.get("id"):
                    catalog_models.append(str(item["id"]))

            # Since LM Studio 0.4, the OpenAI-compatible /v1/models endpoint may
            # contain the whole downloaded catalogue.  The native endpoint is
            # the authoritative source for what is actually loaded right now.
            loaded_models: List[str] = []
            native_url = self.base_url[:-3] + "/api/v1/models" if self.base_url.endswith("/v1") else ""
            if native_url:
                try:
                    native = self._request_json("GET", native_url)
                    for item in native.get("models", []):
                        if not isinstance(item, dict) or not item.get("loaded_instances"):
                            continue
                        key = str(item.get("key") or "").strip()
                        if key:
                            loaded_models.append(key)
                        for instance in item.get("loaded_instances") or []:
                            instance_id = str(instance.get("id") or "").strip() if isinstance(instance, dict) else ""
                            if instance_id and instance_id not in loaded_models:
                                loaded_models.append(instance_id)
                except Exception:
                    # Older LM Studio versions expose only loaded models through
                    # /v1/models and do not implement the native catalogue API.
                    loaded_models = list(catalog_models)
            else:
                loaded_models = list(catalog_models)
            return {
                "reachable": True,
                "models": loaded_models,
                "catalog_models": catalog_models,
                "error": "",
            }
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            return {"reachable": False, "models": [], "catalog_models": [], "error": message[:500]}

    def pick_model(self) -> str:
        models = self.list_models()
        wanted = str(self.cfg.get("lm_model") or "local-model")
        if models:
            if wanted == "local-model" or wanted not in models:
                return models[0]
            return wanted
        return wanted

    def _apply_reasoning_effort(self, payload: Dict[str, Any], *, no_think: bool = False) -> None:
        effort = str(self.cfg.get("lm_reasoning_effort", "auto") or "auto").strip().lower()
        if no_think and effort == "auto":
            effort = "none"
        if effort in {"none", "minimal", "low", "medium", "high"}:
            # LM Studio maps ``none`` to the model's public reasoning=off
            # capability. Unlike a textual /no_think hint this prevents hidden
            # reasoning tokens from consuming the whole radio reply budget.
            payload["reasoning_effort"] = effort

    def generate_plain_text(
        self,
        prompt: str,
        *,
        system: str = "Ты пишешь готовый русский текст для радио.",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
        model: Optional[str] = None,
        structured_output: bool = False,
        response_schema: Optional[Dict[str, Any]] = None,
        no_think: bool = False,
    ) -> str:
        selected_model = str(model or self.pick_model())
        if selected_model == "local-model":
            models = self.list_models()
            selected_model = models[0] if models else selected_model
        prepared_system = str(system or "")
        if no_think:
            prepared_system = "no_think. Output the final answer immediately without a long reasoning preamble.\n" + prepared_system
        payload = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": prepared_system},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(self.cfg.get("lm_temperature", 0.78) if temperature is None else temperature),
            "max_tokens": int(max_tokens or min(1200, int(self.cfg.get("lm_max_tokens", 760) or 760))),
            "stream": False,
        }
        self._apply_reasoning_effort(payload, no_think=no_think)
        if structured_output:
            schema = response_schema or {
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"],
                "additionalProperties": False,
            }
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "radio_generated_object",
                    "strict": True,
                    "schema": schema,
                },
            }
        data = self._request_json("POST", f"{self.base_url}/chat/completions", payload, timeout=timeout)
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        # Never treat private chain-of-thought as a ready radio script/JSON.
        return str(msg.get("content") or "").strip()

    def generate_host_line(self, previous_track: Optional[Track], next_track: Optional[Track], ctx: Dict[str, Any]) -> str:
        """Generate one host break.

        v069 deliberately returns to the simpler v048 live prompt style: the engine
        decides previous/next track, timing and voices; the model only writes the
        radio text. The previous over-specified prompt made some local models
        echo the prompt, use bullet lists, and ignore the second host.
        """
        if self.cfg.get("lm_compact_host_prompt", True):
            model = self.pick_model()
            prompt = build_compact_host_prompt(self.cfg, previous_track, next_track, ctx)
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _compact_host_system(self.cfg)},
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(self.cfg.get("lm_temperature", 0.78)),
                "max_tokens": _host_output_token_limit(self.cfg, ctx),
                "stream": False,
            }
            self._apply_reasoning_effort(payload)
            data = self._request_json("POST", f"{self.base_url}/chat/completions", payload)
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("LM Studio вернул пустой choices")
            msg = choices[0].get("message") or {}
            raw_text = str(msg.get("content") or "").strip()
            cleaned = sanitize_general_radio_text(
                clean_host_text(raw_text, int(self.cfg.get("max_host_text_chars", 4000) or 4000))
            )
            if self.cfg.get("tts_debug_log", True):
                log("LM Studio вернул черновик ведущих: " + " ".join(cleaned.split())[:500])
            return cleaned

        model = self.pick_model()
        intro_allowed = bool(ctx.get("intro_allowed", False))
        prev_name = previous_track.display_name if previous_track else "ещё ничего не играло"
        intro_is_nonblocking = intro_allowed and not bool(self.cfg.get("startup_intro_blocking", True))
        if intro_allowed:
            if intro_is_nonblocking and not self.cfg.get("startup_intro_track_specific", False):
                next_name = "первый трек из локального плейлиста"
                track_specific_rule = "Это самое начало эфира. Предыдущих треков НЕ БЫЛО. Для неблокирующей стартовой вставки НЕ называй конкретный следующий трек."
            else:
                next_name = next_track.display_name if next_track else "первый трек из локального плейлиста"
                track_specific_rule = (
                    "ЭТО САМОЕ НАЧАЛО ЭФИРА: предыдущих песен и прошлых треков НЕ БЫЛО. "
                    "Нельзя говорить: 'только что звучало', 'перед нами было', 'мы слушали', 'предыдущий трек', 'после прошлого трека'. "
                    "Единственная музыка, которую можно назвать, — первый/следующий трек из поля ниже. "
                    "Финальная подводка может назвать только этот первый/следующий трек."
                )
        else:
            next_name = next_track.display_name if next_track else "следующий трек из локального плейлиста"
            track_specific_rule = (
                "Предыдущий трек уже прозвучал или сейчас заканчивается. Следующий трек будет включён после этой речи. "
                "Если называешь музыку в финальной подводке, называй только СЛЕДУЮЩИЙ трек из поля ниже."
            )

        hosts = ctx.get("hosts") or []
        dj_length = str(ctx.get("dj_length", "short") or "short").lower()
        dj_instruction = str(ctx.get("dj_instruction", "Короткая радиоподводка."))
        dj_topic_label = str(ctx.get("dj_topic_label", "музыка"))

        if dj_length == "long":
            solo_rule = "Пиши 5-7 законченных предложений."
            duo_rule = "Пиши 5-7 коротких реплик суммарно. Не делай механическое чередование: можно дать одному ведущему две короткие реакции подряд, если так живее."
        elif dj_length == "medium":
            solo_rule = "Пиши 3-4 законченных предложения."
            duo_rule = "Пиши 4 короткие реплики суммарно. Не обязательно строго по очереди: допускаются короткие реакции, подхваты и быстрые ответы."
        else:
            solo_rule = "Пиши 1-2 коротких законченных предложения."
            duo_rule = "Пиши 2-3 короткие реплики суммарно, если третья нужна для живой реакции."

        # Special minimal retry prompt: if the first attempt failed to include both
        # hosts, do not repeat the huge context. Local small models obey this much
        # better than a second giant prompt.
        force_duo_retry = False  # v075: не используем короткий retry без времени/погоды/контекста
        if force_duo_retry and ctx.get("two_hosts") and len(hosts) >= 2:
            prompt = (
                "Нужен только эфирный диалог двух радиоведущих. Без списков, без markdown, без ремарок в скобках.\n"
                f"Верни ровно 4 строки в таком формате:\n"
                f"{hosts[0]['name']}: короткая живая реплика.\n"
                f"{hosts[1]['name']}: короткая живая реплика.\n"
                f"{hosts[0]['name']}: короткая подводка к треку.\n"
                f"{hosts[1]['name']}: финальная короткая реплика перед музыкой.\n"
                f"Следующий трек: {next_name}.\n"
                "Не пиши ничего кроме этих четырёх строк. Не используй дефисы в начале строк."
            )
        else:
            if ctx.get("two_hosts") and len(hosts) >= 2:
                host_names = ", ".join(str(h.get("name", "Ведущий")).strip() for h in hosts)
                allowed_prefixes = ", ".join(f"{str(h.get('name','Ведущий')).strip()}:" for h in hosts)
                host_rule = (
                    f"В эфире ведущие: {host_names}. "
                    f"Каждая реплика начинается строго с одного из этих имён и двоеточия: {allowed_prefixes}. "
                    f"{duo_rule} "
                    "Если ведущих больше двух, не обязательно каждому давать реплику в каждом блоке, но выбранные ведущие должны звучать естественно. "
                    "Нельзя писать списком через дефисы. Нельзя писать сценические ремарки. "
                    "Можно коротко подколоть, усмехнуться, отреагировать на фразу другого и сразу продолжить мысль, но без стендап-монолога. "
                    "Если это первая вставка эфира, минимум два ведущих обязательно говорят содержательно."
                )
            else:
                host_name = str(hosts[0].get("name", "Ведущий")).strip() if hosts else "Ведущий"
                example_bad_name = "Ирина"
                all_host_names = [
                    str(x).strip()
                    for x in (ctx.get("all_host_names") or [])
                    if str(x).strip()
                ]
                forbidden_names = [x for x in all_host_names if x != host_name]
                if forbidden_names:
                    example_bad_name = forbidden_names[0]
                forbidden_line = (
                    f" Запрещено использовать имена и префиксы других ведущих: {', '.join(f'{x}:' for x in forbidden_names)}."
                    if forbidden_names else ""
                )
                host_rule = (
                    f"Один ведущий: {host_name}. Начни ответ строго с '{host_name}:'. {solo_rule}"
                    f"{forbidden_line} Нельзя писать вложенные префиксы вроде '{host_name}: {example_bad_name}:'; после '{host_name}:' сразу идёт текст ведущего."
                )

            extra_lines = []
            if ctx.get("time_text"):
                extra_lines.append(f"Дата и время: {ctx['time_text']}")
            if ctx.get("spoken_time_text"):
                extra_lines.append(f"Время для произнесения вслух: {ctx['spoken_time_text']}")
            if ctx.get("daypart_text"):
                extra_lines.append(f"Время суток для ориентира: {ctx['daypart_text']}")
            if ctx.get("exact_time_text"):
                extra_lines.append(f"Точный час: {ctx['exact_time_text']}")
            if ctx.get("weather_text"):
                extra_lines.append(f"Погода: {ctx['weather_text']}")
            else:
                extra_lines.append(
                    "Проверенных данных о погоде нет. Не упоминай погоду, температуру, солнце, "
                    "осадки, облачность, ветер, рассвет или закат."
                )
            if ctx.get("weather_city"):
                extra_lines.append(
                    f"Единственный город для погоды и местного контекста: {ctx['weather_city']}. "
                    "Не заменяй его Москвой или другим городом и не добавляй город из памяти модели."
                )
            if ctx.get("news_text"):
                extra_lines.append(f"Новость станции: {ctx['news_text']}")
            if ctx.get("greeting_text"):
                extra_lines.append(f"Привет слушателя: {ctx['greeting_text']}")
            if ctx.get("entertainment_text"):
                extra_lines.append(f"Рубрика эфира: {ctx['entertainment_text']}")
            if ctx.get("entertainment_instruction"):
                extra_lines.append(f"Как встроить рубрику: {ctx['entertainment_instruction']}")
            if ctx.get("force_guest"):
                extra_lines.append("В этом блоке есть гость. Можно использовать реплики 'Гость:'. Гость не заменяет ведущих, а появляется как короткий звонок/история в эфире.")
                if ctx.get('guest_ref_status') and not ctx['guest_ref_status'].get('audio_exists'):
                    extra_lines.append("У гостя нет отдельного reference-аудио, поэтому голос будет стандартным/ближайшим доступным. Текст всё равно должен быть от имени 'Гость:'.")
            if ctx.get("allow_omnivoice_nonverbal_tags"):
                extra_lines.append(
                    "OmniVoice non-verbal tags: если эмоция действительно нужна, поставь максимум ОДИН официальный английский тег в начале одной реплики, сразу после 'Имя:'. "
                    "Разрешённый whitelist: [laughter], [sigh], [confirmation-en], [question-en], [question-ah], [question-oh], [question-ei], [question-yi], [surprise-ah], [surprise-oh], [surprise-wa], [surprise-yo], [dissatisfaction-hnn]. "
                    "Пример формата: 'Ирина: [laughter] Вот это поворот.' Не используй русские теги вроде [смех], [вздох], [удивление]. Не ставь больше одного тега в блоке. Не ставь тег в середину или конец реплики."
                )
            if ctx.get("retry_reason"):
                extra_lines.append(f"Ошибки предыдущей попытки, которые нужно исправить: {ctx['retry_reason']}")
            if (not intro_allowed) and ctx.get("previous_track_info"):
                extra_lines.append(f"Профиль предыдущего трека: {ctx['previous_track_info']}")
            if ctx.get("next_track_info"):
                extra_lines.append(f"Профиль следующего трека: {ctx['next_track_info']}")
            if ctx.get("previous_track_info") or ctx.get("next_track_info"):
                extra_lines.append("Используй профили треков чаще: можно кратко обсудить настроение, факт, исполнителя или красивую подводку, но не перегружай эфир справкой.")
            extras = "\n".join(extra_lines) if extra_lines else "Дополнительных данных нет."

            startup_context = (
                "город и проверенная погода" if ctx.get("weather_text") else "город без догадок о погоде"
            )
            continuity_rule = (
                f"Это первая стартовая речь сразу после запуска радио. Это типичное открытие станции: приветствие, название радио, кто ведёт эфир, текущее время, {startup_context}, затем подводка только к первому следующему треку. "
                "Предыдущих треков ещё не было вообще. Запрещено обсуждать музыку, которая якобы уже звучала, или выдумывать вчерашнюю программу."
                if intro_allowed else
                "Эфир уже идёт. Не говори 'добро пожаловать', не начинай станцию заново, не здоровайся каждый раз. "
                "Если обсуждаешь предыдущую песню, говори 'только что звучала/звучал', а не 'сегодня утром', 'ранее', 'давно', 'несколько часов назад'."
            )
            season_rule = (
                "Учитывай реальный месяц из даты. Не говори, что на улице реально снег, мороз или вьюга, если это не подтверждает дата/погода. "
                "Зимние образы в песне называй образами трека, а не реальностью за окном."
                if self.cfg.get("season_reality_guard_enabled", True) else ""
            )
            radio_topics = "температуре и погоде" if ctx.get("weather_text") else "городе и коротких человеческих наблюдениях"
            radio_rule = (
                "Это обычное душевное музыкальное радио для слушателей, не ролевая трансляция и не сцена из игры. "
                "Запрещены любые игровые и автомобильные ролевые образы: VR, игры, симуляторы, кабины, грузовики, рейсы, трассы, водители, дальнобойщики, фары, дорожные знаки и ситуация за рулём. "
                f"Говори только о музыке, настроении, времени, слушателях, {radio_topics}."
            )
            recent = ctx.get("recent_host_texts") or []
            recent_text = "\n".join(f"- {x}" for x in recent[-5:]) if recent else "пока нет"
            hour_now = int(ctx.get("computer_hour", time.localtime().tm_hour) or 0)
            if 5 <= hour_now <= 11:
                daypart_now = "утро"
                forbidden_dayparts = "день/вечер/ночь/полночь"
            elif 12 <= hour_now <= 17:
                daypart_now = "день"
                forbidden_dayparts = "вечер/ночь/полночь/утро"
            elif 18 <= hour_now <= 22:
                daypart_now = "вечер"
                forbidden_dayparts = "утро/день/ночь/полночь"
            else:
                daypart_now = "ночь"
                forbidden_dayparts = "утро/день/вечер, если не как образ трека"
            clock_rule = (
                f"Точное локальное время компьютера сейчас: {ctx.get('time_text') or _current_time_text()}. Для произнесения вслух используй эту формулировку: {ctx.get('spoken_time_text') or ctx.get('time_text') or _current_time_text()}. Сейчас по времени суток: {daypart_now}. "
                f"Это единственный источник времени. Запрещено говорить про {forbidden_dayparts}, если это не соответствует указанному времени. "
                "Время передаётся как контекст для каждого выхода ведущих: можно ориентироваться на него каждый раз, но проговаривать вслух нужно только когда это звучит естественно. "
                "Если называешь время в эфире, пиши его словами и с уточнением времени суток: не '11:12', а 'одиннадцать часов двенадцать минут утра/дня/вечера/ночи'."
            )
            creative_fact_rule = (
                "Можно добавлять живые факты, ассоциации и маленькие воображаемые зарисовки по теме трека, названия или настроения. "
                "Желательно иногда брать тему из профиля предыдущей/следующей песни: настроение, исполнитель, жанр, факт, или красивый radio_angle. "
                "Можно иногда дать короткий факт из мира, не связанный с музыкой, но только как лёгкую радиозарисовку. "
                "Если факт не дан в профиле трека/новостях/погоде, не подавай его как проверенную справку: формулируй мягко — 'а представьте', 'есть любопытная ассоциация', 'можно вспомнить'."
            ) if self.cfg.get("host_creative_fact_mode", True) else "Факты о реальных песнях и артистах бери только из профиля трека, новостей или погоды."

            station_name = str(ctx.get("station_name") or "Волна FM")
            style_name = str(ctx.get('style', 'радио'))
            weather_rule = (
                "Если говоришь о погоде, назови город, температуру в градусах и ветер/облачность строго из поля 'Погода'. Не превращай погоду в игровую или автомобильную сцену."
                if ctx.get("weather_text") else
                "Проверенных данных о погоде нет: запрещено упоминать погоду, температуру, солнце, осадки, облачность, ветер, рассвет или закат и делать выводы о них из времени."
            )
            prompt = (
                f"Формат: обычное музыкальное радио для всех слушателей. Название станции: {station_name}. Стиль: {style_name} — {ctx.get('style_prompt') or ''}\n"
                f"{continuity_rule}\n{season_rule}\n{radio_rule}\n{track_specific_rule}\n{clock_rule}\n{creative_fact_rule}\n"
                f"{weather_rule}\n"
                "Абсолютно запрещено в эфирном тексте: VR, игры, симуляторы, игровые бренды, кабины, грузовики, рейсы, трассы, водители, дальнобойщики, фары, дорожные знаки, штрафы, зеркала и ситуация за рулём.\n"
                f"Номер вставки за запуск: {ctx.get('speech_blocks_played', 0) + 1}\n"
                f"Сыграно треков за запуск: {ctx.get('tracks_played', 0)}\n"
                + ("Предыдущий трек: НЕТ, это начало эфира.\n" if intro_allowed else f"Трек, который уже звучал или сейчас заканчивается: {prev_name}\n")
                + f"Следующий трек, который реально будет включён после речи: {next_name}\n"
                f"{extras}\n\n"
                f"Последние вставки, которые нельзя повторять по фразам и образам:\n{recent_text}\n\n"
                + (("Структура стартовой речи: приветствие станции; представление ведущих; текущее время; "
                    + ("город и проверенная погода с градусами; " if ctx.get("weather_text") else "город без сведений о погоде; ")
                    + "короткое настроение эфира; подводка только к первому треку.\n") if intro_allowed else "")
                + f"Задача блока: {dj_instruction}\n"
                f"Тема блока: {dj_topic_label}\n"
                f"{host_rule}\n"
                "Пиши только готовый текст эфира. Не объясняй задачу. Не пиши списки. Не ставь дефисы в начале строк. "
                "Не пиши ремарки в круглых скобках или звёздочках вроде '(включается следующий трек)' или '*подводит к музыке*'. "
                + ("Квадратные скобки разрешены только для одного официального английского OmniVoice non-verbal tag из whitelist выше; русские теги и любые другие квадратные ремарки запрещены. " if ctx.get("allow_omnivoice_nonverbal_tags") else "Не пиши квадратные ремарки и TTS-теги. ")
                + "Каждую смену говорящего пиши с новой реплики в формате 'Имя: текст'. После имени и двоеточия сразу должен идти текст или один разрешённый OmniVoice-тег. Не оставляй пустые 'Имя:' в конце. "
                + "Не произноси технические слова 'ПРЕДЫДУЩИЙ ТРЕК', 'СЛЕДУЮЩИЙ ТРЕК', 'План блока'. "
                "Если название трека в поле выше написано по-русски, не заменяй его латиницей из баз данных. "
                "Говори о музыке уважительно и позитивно, находи сильную сторону трека. "
                "Если дана рубрика эфира, встрои её естественно, но строго соблюдай инструкцию рубрики. Для загадки нельзя говорить 'завтра', 'завтра утром', 'вечером' или 'утром': ответ только в следующий выход ведущих. Если это блок ответа на загадку, сначала назови ответ и НЕ задавай новую загадку. Для гороскопа называй каждый знак в формате 'Овен: текст', 'Телец: текст'. "
                "Обычное общение не должно пропадать из-за рубрик: совмести рубрику с живой репликой, фактом, пожеланием или музыкальной подводкой. "
                "В дуо ведущие могут шутить друг с другом и смеяться, но без стендапа на полчаса. "
                "Диалог должен звучать как живой эфир: короткие реакции, подхваты, обращение по имени, лёгкий смешок или шутка допустимы; не превращай это в сухой обмен репликами по очереди. "
                "Не пиши вложенные префиксы говорящих: формат 'Максим: Ирина: текст' запрещён. "
                "Не повторяй старые образы из прошлых вставок. Не используй дорожные клише. "
                "Для TTS ставь ударения в частых словах, если уместно: эфи́р, му́зыка, тре́к, го́лоса, голоса́. "
                "Закончи последнюю реплику точкой, вопросительным или восклицательным знаком."
            )

        if self.cfg.get("lm_append_no_think", True):
            prompt += "\n/no_think"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": str(self.cfg["radio_persona"])},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(self.cfg.get("lm_temperature", 0.78)),
            "max_tokens": int(self.cfg.get("lm_max_tokens", 620)),
            "stream": False,
        }
        self._apply_reasoning_effort(payload)
        data = self._request_json("POST", f"{self.base_url}/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LM Studio вернул пустой choices")
        msg = choices[0].get("message") or {}
        raw_text = str(msg.get("content") or "").strip()
        cleaned = sanitize_general_radio_text(clean_host_text(raw_text, int(self.cfg.get("max_host_text_chars", 4000) or 4000)))
        if self.cfg.get("tts_debug_log", True):
            log("LM Studio вернул черновик ведущих: " + " ".join(cleaned.split())[:500])
        return cleaned

