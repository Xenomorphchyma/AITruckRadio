# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, List, Optional

from ai_truck_radio_app.config import RUS_MONTHS, RUS_WEEKDAYS, log
from ai_truck_radio_app.text_processing import clean_host_text, sanitize_general_radio_text
from ai_truck_radio_app.tracks import Track


def _current_time_text() -> str:
    now = time.localtime()
    weekday = RUS_WEEKDAYS[now.tm_wday]
    month = RUS_MONTHS[now.tm_mon - 1]
    return f"{now.tm_hour:02d}:{now.tm_min:02d}, {weekday}, {now.tm_mday} {month} {now.tm_year}"


class LMStudioClient:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.base_url = str(cfg["lm_base_url"]).rstrip("/")
        self.timeout = int(cfg.get("lm_timeout_sec", 25))
        self.model = str(cfg.get("lm_model") or "local-model")

    def _request_json(self, method: str, url: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

    def list_models(self) -> List[str]:
        try:
            data = self._request_json("GET", f"{self.base_url}/models")
            models = []
            for item in data.get("data", []):
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
            return models
        except Exception:
            return []

    def pick_model(self) -> str:
        models = self.list_models()
        wanted = str(self.cfg.get("lm_model") or "local-model")
        if models:
            if wanted == "local-model" or wanted not in models:
                return models[0]
            return wanted
        return wanted

    def generate_plain_text(self, prompt: str, *, system: str = "Ты пишешь готовый русский текст для радио.", temperature: Optional[float] = None, max_tokens: Optional[int] = None, timeout: Optional[int] = None) -> str:
        model = self.pick_model()
        old_timeout = self.timeout
        if timeout:
            self.timeout = int(timeout)
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(self.cfg.get("lm_temperature", 0.78) if temperature is None else temperature),
                "max_tokens": int(max_tokens or min(1200, int(self.cfg.get("lm_max_tokens", 760) or 760))),
                "stream": False,
            }
            data = self._request_json("POST", f"{self.base_url}/chat/completions", payload)
            choices = data.get("choices") or []
            if not choices:
                return ""
            msg = choices[0].get("message") or {}
            return str(msg.get("content") or "").strip()
        finally:
            self.timeout = old_timeout

    def generate_host_line(self, previous_track: Optional[Track], next_track: Optional[Track], ctx: Dict[str, Any]) -> str:
        """Generate one host break.

        v069 deliberately returns to the simpler v048 live prompt style: the engine
        decides previous/next track, timing and voices; the model only writes the
        radio text. The previous over-specified prompt made some local models
        echo the prompt, use bullet lists, and ignore the second host.
        """
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
            duo_rule = "Пиши 5-7 коротких реплик суммарно, чередуй ведущих естественно."
        elif dj_length == "medium":
            solo_rule = "Пиши 3-4 законченных предложения."
            duo_rule = "Пиши 4 короткие реплики суммарно, чередуй ведущих."
        else:
            solo_rule = "Пиши 1-2 коротких законченных предложения."
            duo_rule = "Пиши ровно 2 короткие реплики суммарно."

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
                    "Если это первая вставка эфира, минимум два ведущих обязательно говорят содержательно."
                )
            else:
                host_name = hosts[0]["name"] if hosts else "Ведущий"
                host_rule = f"Один ведущий: {host_name}. Начни ответ строго с '{host_name}:'. {solo_rule}"

            extra_lines = []
            if ctx.get("time_text"):
                extra_lines.append(f"Дата и время: {ctx['time_text']}")
            if ctx.get("spoken_time_text"):
                extra_lines.append(f"Время для произнесения вслух: {ctx['spoken_time_text']}")
            if ctx.get("exact_time_text"):
                extra_lines.append(f"Точный час: {ctx['exact_time_text']}")
            if ctx.get("weather_text"):
                extra_lines.append(f"Погода: {ctx['weather_text']}")
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

            continuity_rule = (
                "Это первая стартовая речь сразу после запуска радио. Это типичное открытие станции: приветствие, название радио, кто ведёт эфир, текущее время, город и погода/температура/ветер, затем подводка только к первому следующему треку. "
                "Предыдущих треков ещё не было вообще. Запрещено обсуждать музыку, которая якобы уже звучала."
                if intro_allowed else
                "Эфир уже идёт. Не говори 'добро пожаловать', не начинай станцию заново, не здоровайся каждый раз. "
                "Если обсуждаешь предыдущую песню, говори 'только что звучала/звучал', а не 'сегодня утром', 'ранее', 'давно', 'несколько часов назад'."
            )
            season_rule = (
                "Учитывай реальный месяц из даты. Не говори, что на улице реально снег, мороз или вьюга, если это не подтверждает дата/погода. "
                "Зимние образы в песне называй образами трека, а не реальностью за окном."
                if self.cfg.get("season_reality_guard_enabled", True) else ""
            )
            radio_rule = (
                "Это обычное музыкальное радио для слушателей, а не ролевая трансляция из кабины грузовика. "
                "Запрещено обращаться к аудитории как к дальнобойщикам или водителям; запрещено придумывать водителя Андрея, рейс, кабину, салон грузовика, грузовик, знаки, фары, конкретную трассу и ситуацию 'за рулём'. "
                "Не упоминай Euro Truck Simulator и не делай вид, будто слушатель прямо сейчас едет в грузовике. "
                "Говори о музыке, настроении, времени, слушателях, городе, температуре, погоде и коротких человеческих наблюдениях."
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
                "Если называешь время в эфире, пиши его словами, а не цифрами: не '11:12', а 'одиннадцать часов двенадцать минут'."
            )
            creative_fact_rule = (
                "Можно добавлять живые факты, ассоциации и маленькие воображаемые зарисовки по теме трека, названия или настроения. "
                "Желательно иногда брать тему из профиля предыдущей/следующей песни: настроение, исполнитель, жанр, факт, или красивый radio_angle. "
                "Можно иногда дать короткий факт из мира, не связанный с музыкой, но только как лёгкую радиозарисовку. "
                "Если факт не дан в профиле трека/новостях/погоде, не подавай его как проверенную справку: формулируй мягко — 'а представьте', 'есть любопытная ассоциация', 'можно вспомнить'."
            ) if self.cfg.get("host_creative_fact_mode", True) else "Факты о реальных песнях и артистах бери только из профиля трека, новостей или погоды."

            style_name = str(ctx.get('style', 'радио'))
            if 'дальноб' in style_name.lower():
                style_name = style_name + ' (только название станции, не тема про грузовики)'
            prompt = (
                f"Формат: обычное музыкальное радио для всех слушателей. Стиль/название: {style_name} — {ctx.get('style_prompt') or ''}\n"
                f"{continuity_rule}\n{season_rule}\n{radio_rule}\n{track_specific_rule}\n{clock_rule}\n{creative_fact_rule}\n"
                "Если говоришь о погоде, назови город, температуру в градусах и ветер/облачность из поля 'Погода'. Не превращай погоду в рассказ про рейс, кабину, трассу или грузовик.\n"
                "Запрещённые образы для этого проекта: кабина грузовика, салон грузовика, водитель Андрей, дальнобойщики как аудитория, рейс, трасса, фары режут темноту, снег под колёсами, дорожные знаки.\n"
                f"Номер вставки за запуск: {ctx.get('speech_blocks_played', 0) + 1}\n"
                f"Сыграно треков за запуск: {ctx.get('tracks_played', 0)}\n"
                + ("Предыдущий трек: НЕТ, это начало эфира.\n" if intro_allowed else f"Трек, который уже звучал или сейчас заканчивается: {prev_name}\n")
                + f"Следующий трек, который реально будет включён после речи: {next_name}\n"
                f"{extras}\n\n"
                f"Последние вставки, которые нельзя повторять по фразам и образам:\n{recent_text}\n\n"
                + ("Структура стартовой речи: приветствие станции; представление ведущих; текущее время; город и погода с градусами; короткое настроение эфира; подводка только к первому треку.\n" if intro_allowed else "")
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


