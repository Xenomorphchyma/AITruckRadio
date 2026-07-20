# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List

from ai_truck_radio_app.config import BASE_DIR, log
from ai_truck_radio_app.entertainment_history import filter_unused
from ai_truck_radio_app.lmstudio import LMStudioClient
from ai_truck_radio_app.web_research import read_page, search_pages


SIGNS = ["Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева", "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"]
ENTERTAINMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "horoscope": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sign": {"type": "string"},
                    "text": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["sign", "text", "source_ids"],
                "additionalProperties": False,
            },
        },
        "riddles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "string"},
                    "explanation": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["question", "options", "answer", "explanation", "source_ids"],
                "additionalProperties": False,
            },
        },
        "wrong_games": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "correct": {"type": "string"},
                    "wrong_examples": {"type": "array", "items": {"type": "string"}},
                    "comment": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["question", "correct", "wrong_examples", "comment", "source_ids"],
                "additionalProperties": False,
            },
        },
        "guest_stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["title", "text", "source_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["horoscope", "riddles", "wrong_games", "guest_stories"],
    "additionalProperties": False,
}


def _topic_schema(key: str) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {key: ENTERTAINMENT_SCHEMA["properties"][key]},
        "required": [key],
        "additionalProperties": False,
    }


def _compact_evidence(pages: List[Dict[str, str]], total_chars: int) -> str:
    if not pages:
        return "Источники не прочитаны."
    per_page = max(700, total_chars // len(pages))
    blocks = []
    for index, page in enumerate(pages, 1):
        source_id = int(page.get("source_id") or index)
        blocks.append(
            f"[SOURCE {source_id}]\nTOPIC: {page.get('topic', '')}\nURL: {page['url']}\nTITLE: {page.get('title', '')}\n"
            f"TEXT: {page.get('text', '')[:per_page]}"
        )
    return "\n\n".join(blocks)[:total_chars]


def _clean_text(value: Any, limit: int = 500) -> str:
    if isinstance(value, list):
        value = " ".join(str(x).strip() for x in value if str(x).strip())
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _retain_factchecked_originals(original: List[Any], checked: List[Any], question_key: str = "question") -> List[Any]:
    remaining = [item for item in original if isinstance(item, dict)]
    retained = []
    for checked_item in checked:
        if not isinstance(checked_item, dict):
            continue
        target = _clean_text(checked_item.get(question_key), 300).casefold()
        if not target or not remaining:
            continue
        match = max(
            remaining,
            key=lambda item: SequenceMatcher(
                None, target, _clean_text(item.get(question_key), 300).casefold()
            ).ratio(),
        )
        score = SequenceMatcher(None, target, _clean_text(match.get(question_key), 300).casefold()).ratio()
        if score >= 0.45:
            retained.append(match)
            remaining.remove(match)
    return retained


def _valid_source_ids(value: Any, source_count: int) -> List[int]:
    out = []
    for item in value or []:
        try:
            source_id = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= source_id <= source_count and source_id not in out:
            out.append(source_id)
    return out


def _validate_pack(data: Dict[str, Any], fallback: Dict[str, Any], max_items: int, source_count: int) -> Dict[str, Any]:
    out = dict(fallback)
    horoscope = []
    by_sign = {}
    for item in data.get("horoscope") or []:
        if not isinstance(item, dict):
            continue
        sign = _clean_text(item.get("sign"), 30)
        text = _clean_text(item.get("text"), 360)
        source_ids = _valid_source_ids(item.get("source_ids"), source_count)
        if sign in SIGNS and source_ids and len(text) >= 25 and not re.search(r"(?i)\bдиагноз|лекарств|кредит|инвестиц|ставк[аи]|гарантир", text):
            by_sign[sign] = {"sign": sign, "text": text, "source_ids": source_ids}
    for sign in SIGNS:
        if sign in by_sign:
            horoscope.append(by_sign[sign])
    if len(horoscope) == 12:
        out["horoscope"] = horoscope

    riddles = []
    for item in data.get("riddles") or []:
        if not isinstance(item, dict):
            continue
        question = _clean_text(item.get("question"), 220)
        answer = _clean_text(item.get("answer"), 100)
        explanation = _clean_text(item.get("explanation"), 300)
        options = [_clean_text(x, 100) for x in (item.get("options") or []) if _clean_text(x, 100)]
        source_ids = _valid_source_ids(item.get("source_ids"), source_count)
        if source_ids and question and answer and explanation and 2 <= len(options) <= 6 and answer.casefold() in {x.casefold() for x in options}:
            riddles.append({
                "question": question,
                "options": options,
                "answer": answer,
                "explanation": explanation,
                "source_ids": source_ids,
            })
    if riddles:
        out["riddles"] = riddles[:max_items]

    games = []
    for item in data.get("wrong_games") or []:
        if not isinstance(item, dict):
            continue
        question = _clean_text(item.get("question"), 180)
        correct = _clean_text(item.get("correct"), 100)
        wrong = [_clean_text(x, 120) for x in (item.get("wrong_examples") or []) if _clean_text(x, 120)]
        comment = _clean_text(item.get("comment"), 260)
        source_ids = _valid_source_ids(item.get("source_ids"), source_count)
        if source_ids and question and correct and len(wrong) >= 3 and all(x.casefold() != correct.casefold() for x in wrong):
            games.append({
                "question": question,
                "correct": correct,
                "wrong_examples": wrong[:4],
                "comment": comment or "Нужно ответить явно неправильно.",
                "source_ids": source_ids,
            })
    if games:
        out["wrong_games"] = games[:max_items]
    guest_stories = []
    for item in data.get("guest_stories") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), 140)
        text = _clean_text(item.get("text"), 650)
        source_ids = _valid_source_ids(item.get("source_ids"), source_count)
        risky = re.search(
            r"(?i)\b(политик|выбор|войн|убий|погиб|теракт|диагноз|лекарств|кредит|инвестиц|ставк[аи]|гарантир)\w*",
            f"{title} {text}",
        )
        if source_ids and title and 60 <= len(text) <= 650 and not risky:
            guest_stories.append({"title": title, "text": text, "source_ids": source_ids})
    if guest_stories:
        out["guest_stories"] = guest_stories[:max_items]
    return out


class EntertainmentAgent:
    def __init__(self, cfg: Dict[str, Any], lm: LMStudioClient):
        self.cfg = cfg
        self.lm = lm

    def _selected_model(self) -> str:
        configured = str(self.cfg.get("entertainment_model") or self.cfg.get("lm_model") or "local-model")
        if configured != "local-model":
            return configured
        models = self.lm.list_models()
        return models[0] if models else configured

    def _cache_signature(self) -> Dict[str, Any]:
        keys = (
            "entertainment_model",
            "entertainment_agent_results_per_query",
            "entertainment_agent_max_pages",
            "entertainment_agent_pages_per_topic",
            "entertainment_agent_min_page_chars",
            "entertainment_agent_page_chars",
            "entertainment_agent_total_evidence_chars",
            "entertainment_agent_max_tokens",
            "entertainment_agent_temperature",
            "entertainment_agent_factcheck_enabled",
            "entertainment_agent_no_think",
            "entertainment_agent_structured_output",
            "entertainment_pack_max_items",
        )
        signature = {key: self.cfg.get(key) for key in keys}
        signature["resolved_entertainment_model"] = self._selected_model()
        return signature

    def _cache_path(self, date: str | None = None) -> Path:
        root = Path(str(self.cfg.get("entertainment_daily_cache_dir") or "cache/entertainment"))
        if not root.is_absolute():
            root = BASE_DIR / root
        return root / f"{date or time.strftime('%Y-%m-%d')}.json"

    def load_daily_cache(self) -> Dict[str, Any] | None:
        path = self._cache_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or data.get("date") != time.strftime("%Y-%m-%d")
                or data.get("config") != self._cache_signature()
            ):
                return None
            pack = data.get("pack")
            if not isinstance(pack, dict):
                return None
            pack["_research"] = data.get("research") or {}
            pack["_validation"] = data.get("validation") or {}
            pack["_daily_cache"] = str(path)
            return pack
        except FileNotFoundError:
            return None
        except Exception as exc:
            log(f"Не удалось прочитать дневной кэш рубрик {path}: {exc}")
            return None

    def _save_daily_cache(
        self,
        pack: Dict[str, Any],
        research: Dict[str, Any],
        validation: Dict[str, Any],
    ) -> Path:
        path = self._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        sources = []
        for page in research.get("pages") or []:
            sources.append({
                "source_id": page.get("source_id"),
                "topic": page.get("topic"),
                "query": page.get("query"),
                "title": page.get("title"),
                "url": page.get("url"),
                "text_excerpt": str(page.get("text") or "")[:2000],
            })
        report = {
            "schema_version": 1,
            "date": time.strftime("%Y-%m-%d"),
            "created_ts": int(time.time()),
            "config": self._cache_signature(),
            "research": {
                "model": self._selected_model(),
                "queries": research.get("queries") or [],
                "sources": sources,
            },
            "validation": validation,
            "pack": {key: value for key, value in pack.items() if not str(key).startswith("_")},
        }
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _research(self) -> Dict[str, Any]:
        timeout = int(self.cfg.get("entertainment_agent_page_timeout_sec", 15) or 15)
        results = int(self.cfg.get("entertainment_agent_results_per_query", 6) or 6)
        max_pages = int(self.cfg.get("entertainment_agent_max_pages", 6) or 6)
        pages_per_topic = int(self.cfg.get("entertainment_agent_pages_per_topic", 2) or 2)
        page_chars = int(self.cfg.get("entertainment_agent_page_chars", 6000) or 6000)
        today = time.strftime("%d.%m.%Y")
        topics = [
            ("horoscope", f"гороскоп на сегодня {today} все знаки зодиака"),
            ("riddles", "короткие загадки с ответами и вариантами для взрослых"),
            ("quiz", "простые вопросы викторины с однозначными ответами"),
        ]
        if self.cfg.get("guest_enabled", False):
            topics.append(("guest", "короткие добрые истории о культуре музыке творчестве и необычных увлечениях"))
        pages: List[Dict[str, Any]] = []
        seen = set()
        for topic, query in topics:
            topic_pages = 0
            try:
                for result in search_pages(query, timeout, results):
                    if result["url"] in seen:
                        continue
                    seen.add(result["url"])
                    try:
                        page = read_page(result["url"], timeout, page_chars)
                        if len(page["text"]) >= int(self.cfg.get("entertainment_agent_min_page_chars", 300) or 300):
                            page["query"] = query
                            page["topic"] = topic
                            pages.append(page)
                            topic_pages += 1
                            log(f"Рубрики: прочитана страница {page['url']}")
                    except Exception as exc:
                        log(f"Рубрики: страница пропущена {result['url']}: {exc}")
                    if len(pages) >= max_pages or topic_pages >= pages_per_topic:
                        break
            except Exception as exc:
                log(f"Рубрики: поиск не сработал для {query!r}: {exc}")
            if len(pages) >= max_pages:
                break
        for index, page in enumerate(pages, 1):
            page["source_id"] = index
        return {"queries": [query for _, query in topics], "pages": pages}

    def build(self, fallback: Dict[str, Any]) -> Dict[str, Any]:
        research = self._research()
        total_evidence = int(self.cfg.get("entertainment_agent_total_evidence_chars", 16000) or 16000)
        max_items = max(1, int(self.cfg.get("entertainment_pack_max_items", 12) or 12))
        model = self._selected_model()
        topic_prompts = {
            "horoscope": (
                "horoscope",
                "Подготовь лёгкий гороскоп музыкального радио на сегодня. Верни ровно 12 знаков в стандартном порядке. "
                "Каждый текст короткий, без медицины, финансов, политики, опасных советов и без привязки к утру, вечеру или ночи. "
                "Перескажи источник, не копируй его. source_ids должны ссылаться на SOURCE.",
            ),
            "riddles": (
                "riddles",
                f"Выбери до {max_items} коротких загадок с явно указанными в SOURCE ответами. "
                "Для каждой придумай 3-4 варианта, обязательно включив точный правильный ответ. "
                "Не используй загадки без подтверждённого ответа и не повторяй вопросы из журнала:\n{exclusion_text}",
            ),
            "quiz": (
                "wrong_games",
                f"Выбери до {max_items} простых вопросов викторины с однозначным правильным ответом для игры «ответь неправильно». "
                "Правильный ответ бери из SOURCE, а 3-4 смешных неправильных ответа можешь придумать. "
                "Не повторяй вопросы из журнала:\n{exclusion_text}",
            ),
        }
        if self.cfg.get("guest_enabled", False):
            topic_prompts["guest"] = (
                "guest_stories",
                f"Подготовь до {max_items} коротких добрых историй для гостя радио. "
                "Каждая история должна быть аккуратным пересказом SOURCE, без выдуманных имён, цитат и деталей, "
                "без политики, преступлений, медицины, финансов и личных данных. source_ids обязательны.",
            )
        data: Dict[str, Any] = {"horoscope": [], "riddles": [], "wrong_games": [], "guest_stories": []}
        topic_count = max(1, len(topic_prompts))
        for topic, (key, instruction) in topic_prompts.items():
            pages = [page for page in research["pages"] if page.get("topic") == topic]
            if not pages:
                continue
            evidence = _compact_evidence(pages, max(2500, total_evidence // topic_count))
            prompt = (
                f"Дата: {time.strftime('%d.%m.%Y')}.\n{instruction}\n"
                "Верни только JSON заданной структуры, без markdown.\n\nSOURCE:\n" + evidence
            )
            draft = self.lm.generate_plain_text(
                prompt,
                system="Ты редактор безопасных радиорубрик. Используй только прочитанные SOURCE.",
                temperature=float(self.cfg.get("entertainment_agent_temperature", 0.15) or 0.15),
                max_tokens=int(self.cfg.get("entertainment_agent_max_tokens", 2400) or 2400),
                timeout=int(self.cfg.get("entertainment_pack_timeout_sec", 180) or 180),
                model=model,
                structured_output=bool(self.cfg.get("entertainment_agent_structured_output", True)),
                response_schema=_topic_schema(key),
                no_think=bool(self.cfg.get("entertainment_agent_no_think", True)),
            )
            original = json.loads(draft)
            if bool(self.cfg.get("entertainment_agent_factcheck_enabled", True)):
                factcheck_rule = {
                    "horoscope": "Сохрани ровно 12 знаков и их source_ids; убирай только опасные советы.",
                    "riddles": "Проверь вопрос и ответ по SOURCE. Сохрани 3-4 варианта, включая правильный ответ.",
                    "wrong_games": (
                        "Проверь по SOURCE только вопрос и correct. wrong_examples являются специально вымышленными: "
                        "не сверяй и не удаляй их, сохрани 3-4 явно неправильных ответа."
                    ),
                    "guest_stories": "Проверь, что каждая история и все её конкретные детали подтверждены SOURCE.",
                }[key]
                draft = self.lm.generate_plain_text(
                    "Проверь JSON по SOURCE. Удали неподтверждённые элементы, сохрани структуру и верни только JSON. "
                    + factcheck_rule + "\n\n"
                    + draft + "\n\nSOURCE:\n" + evidence,
                    system="Ты строгий фактчекер радиорубрик.",
                    temperature=0.05,
                    max_tokens=int(self.cfg.get("entertainment_agent_max_tokens", 2400) or 2400),
                    timeout=int(self.cfg.get("entertainment_pack_timeout_sec", 180) or 180),
                    model=model,
                    structured_output=bool(self.cfg.get("entertainment_agent_structured_output", True)),
                    response_schema=_topic_schema(key),
                    no_think=bool(self.cfg.get("entertainment_agent_no_think", True)),
                )
            parsed = json.loads(draft)
            if key in {"riddles", "wrong_games", "guest_stories"} and bool(self.cfg.get("entertainment_agent_factcheck_enabled", True)):
                parsed[key] = _retain_factchecked_originals(
                    original.get(key) or [],
                    parsed.get(key) or [],
                    question_key="title" if key == "guest_stories" else "question",
                )
            if isinstance(parsed.get(key), list):
                data[key] = parsed[key]
        pack = _validate_pack(data, fallback, max_items, len(research["pages"]))
        validation_keys = ("horoscope", "riddles", "wrong_games", "guest_stories")
        accepted_before_history = {key: len(pack.get(key) or []) for key in validation_keys}
        fallback_used = {
            key: bool(pack.get(key) == fallback.get(key))
            for key in validation_keys
        }
        today = time.strftime("%Y-%m-%d")
        pack["horoscope"] = filter_unused(self.cfg, "horoscope", pack.get("horoscope") or [], today)
        pack["riddles"] = filter_unused(self.cfg, "riddle", pack.get("riddles") or [])
        pack["wrong_games"] = filter_unused(self.cfg, "wrong_game", pack.get("wrong_games") or [])
        pack["guest_stories"] = filter_unused(self.cfg, "guest_story", pack.get("guest_stories") or [])
        research_summary = {
            "model": model,
            "queries": research["queries"],
            "sources": [{"title": p["title"], "url": p["url"]} for p in research["pages"]],
            "created_ts": int(time.time()),
        }
        raw_counts = {key: len(data.get(key) or []) for key in validation_keys}
        final_counts = {key: len(pack.get(key) or []) for key in validation_keys}
        validation = {
            "raw_counts": raw_counts,
            "accepted_before_history": accepted_before_history,
            "rejected_by_validation": {
                key: max(0, raw_counts[key] - accepted_before_history[key])
                for key in validation_keys
            },
            "final_counts": final_counts,
            "fallback_used": fallback_used,
            "fallback_reason": {
                key: ("валидный результат агента не заменил встроенный пакет" if fallback_used[key] else "")
                for key in validation_keys
            },
            "removed_by_history": {
                key: max(0, accepted_before_history[key] - final_counts[key])
                for key in validation_keys
            },
        }
        pack["_research"] = research_summary
        pack["_validation"] = validation
        pack["_daily_cache"] = str(self._save_daily_cache(pack, research, validation))
        return pack
