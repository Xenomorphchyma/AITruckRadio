# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from ai_truck_radio_app.config import BASE_DIR, log, save_json
from ai_truck_radio_app.news_history import content_text, is_similar, transition_item, used_content
from ai_truck_radio_app.web_research import read_page, search_pages


SearchFn = Callable[[str, int, int], List[Dict[str, Any]]]
ReadFn = Callable[[str, int, int], Dict[str, Any]]
NowFn = Callable[[], float]

NEWS_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["title", "summary", "source_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

NEWS_FACTCHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["verified", "review", "rejected"]},
                    "source_ids": {"type": "array", "items": {"type": "integer"}},
                    "notes": {"type": "string"},
                },
                "required": ["draft_id", "decision", "source_ids", "notes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

_MULTIPART_SUFFIXES = {"co.uk", "com.au", "com.br", "com.cn", "com.tr", "gov.uk", "org.uk"}


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _domain(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").casefold().removeprefix("www.")


def _independent_domain(url: str) -> str:
    host = _domain(url)
    labels = [part for part in host.split(".") if part]
    if len(labels) <= 2:
        return host
    suffix = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix in _MULTIPART_SUFFIXES else suffix


def _canonical_url(url: str) -> str:
    parsed = urllib.parse.urlparse(urllib.parse.urldefrag(str(url or ""))[0])
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.casefold().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunparse(("https", host, path, "", parsed.query, ""))


def _values(value: Any) -> List[str]:
    if isinstance(value, str):
        raw = re.split(r"[,;\n]", value)
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = []
    out = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _valid_source_ids(value: Any, source_ids: set[int]) -> List[int]:
    out = []
    for raw in value or []:
        try:
            source_id = int(raw)
        except (TypeError, ValueError):
            continue
        if source_id in source_ids and source_id not in out:
            out.append(source_id)
    return out


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("NewsAgent ожидал JSON object")
    return parsed


def load_fallback_items(cfg: Dict[str, Any], *, now: int, ttl_sec: int) -> List[Dict[str, Any]]:
    path = Path(str(cfg.get("news_file") or "data/news.txt"))
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        lines = [
            _clean(line, 1200)
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except FileNotFoundError:
        return []
    except Exception as exc:
        log(f"Не удалось прочитать fallback новостей {path}: {exc}")
        return []

    count = max(1, int(cfg.get("news_lines_per_insert", 1) or 1))
    items = []
    for index, line in enumerate(lines[: max(count, int(cfg.get("news_agent_max_items", 8) or 8))], 1):
        title = _clean(re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0], 180)
        item = {
            "draft_id": f"fallback-{index}",
            "title": title or f"Локальная новость {index}",
            "summary": line,
            "source_ids": [],
            "source_domains": [],
            "official_source_ids": [],
            "published_at": "",
            "fetched_at": now,
            "expires_at": now + ttl_sec,
            "origin": "fallback_file",
            "fallback_file": str(path),
            "status": "draft",
            "status_history": [{"status": "draft", "at": now}],
        }
        items.append(transition_item(cfg, item, "review", reason="manual_fallback", at=now))
    return items


class NewsAgent:
    """Builds an auditable news pack; network and LM dependencies are injectable."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        lm: Any = None,
        *,
        search_fn: SearchFn = search_pages,
        read_fn: ReadFn = read_page,
        now_fn: NowFn = time.time,
    ) -> None:
        self.cfg = cfg
        self.lm = lm
        self.search_fn = search_fn
        self.read_fn = read_fn
        self.now_fn = now_fn

    def _official_domains(self) -> List[str]:
        out = []
        for value in _values(self.cfg.get("news_agent_official_domains")):
            domain = _domain(value if "://" in value else f"https://{value}")
            if domain and domain not in out:
                out.append(domain)
        return out

    def _queries(self, queries: Optional[Iterable[str]] = None) -> List[str]:
        if queries is not None:
            out = _values(queries)
        else:
            out = _values(self.cfg.get("news_agent_queries"))
        return out or ["главные новости сегодня"]

    def _cache_path(self) -> Path:
        value = Path(str(self.cfg.get("news_agent_cache_file") or "cache/news_agent/latest.json"))
        return value if value.is_absolute() else BASE_DIR / value

    def _cache_signature(self, queries: Iterable[str]) -> Dict[str, Any]:
        keys = (
            "news_agent_results_per_query",
            "news_agent_max_pages",
            "news_agent_min_page_chars",
            "news_agent_page_chars",
            "news_agent_total_evidence_chars",
            "news_agent_source_ttl_sec",
            "news_agent_cache_ttl_sec",
            "news_agent_max_items",
            "news_agent_structured_output",
            "news_agent_no_think",
            "news_file",
            "news_lines_per_insert",
        )
        signature = {key: self.cfg.get(key) for key in keys}
        signature.update({
            "queries": list(queries),
            "official_domains": self._official_domains(),
            "min_independent_domains": int(self.cfg.get("news_agent_min_independent_domains", 2) or 2),
            "model": str(self.cfg.get("news_agent_model") or self.cfg.get("lm_model") or "local-model"),
            "factcheck": bool(self.cfg.get("news_agent_factcheck_enabled", True)),
        })
        return signature

    def load_cache(self, queries: Optional[Iterable[str]] = None) -> Optional[Dict[str, Any]]:
        expected_queries = self._queries(queries)
        try:
            pack = json.loads(self._cache_path().read_text(encoding="utf-8"))
            if (
                not isinstance(pack, dict)
                or int(pack.get("schema_version") or 0) != 1
                or int(pack.get("expires_at") or 0) <= int(self.now_fn())
                or pack.get("config") != self._cache_signature(expected_queries)
            ):
                return None
            return pack
        except FileNotFoundError:
            return None
        except Exception as exc:
            log(f"Не удалось прочитать кэш NewsAgent: {exc}")
            return None

    def collect_sources(self, queries: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        query_list = self._queries(queries)
        official_domains = self._official_domains()
        timeout = max(1, int(self.cfg.get("news_agent_page_timeout_sec", 15) or 15))
        per_query = max(1, int(self.cfg.get("news_agent_results_per_query", 6) or 6))
        max_pages = max(1, int(self.cfg.get("news_agent_max_pages", 8) or 8))
        page_chars = max(500, int(self.cfg.get("news_agent_page_chars", 7000) or 7000))
        min_chars = max(20, int(self.cfg.get("news_agent_min_page_chars", 200) or 200))
        ttl_sec = max(60, int(self.cfg.get("news_agent_source_ttl_sec", 21600) or 21600))
        now = int(self.now_fn())

        search_jobs: List[tuple[str, bool]] = []
        for query in query_list:
            search_jobs.extend((f"site:{domain} {query}", True) for domain in official_domains)
            search_jobs.append((query, False))

        results: List[Dict[str, Any]] = []
        seen_urls = set()
        for query, official_path in search_jobs:
            try:
                found = self.search_fn(query, timeout, per_query)
            except Exception as exc:
                log(f"NewsAgent: поиск пропущен для {query!r}: {exc}")
                continue
            for raw in found or []:
                if not isinstance(raw, dict):
                    continue
                url = _canonical_url(str(raw.get("url") or ""))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                result = dict(raw)
                result["url"] = url
                result["query"] = query
                result["official_path"] = official_path
                results.append(result)

        sources: List[Dict[str, Any]] = []
        for result in results:
            if len(sources) >= max_pages:
                break
            try:
                page = self.read_fn(str(result["url"]), timeout, page_chars)
            except Exception as exc:
                log(f"NewsAgent: источник пропущен {result['url']}: {exc}")
                continue
            if not isinstance(page, dict):
                continue
            text = _clean(page.get("text"), page_chars)
            if len(text) < min_chars:
                continue
            url = _canonical_url(str(page.get("url") or result["url"])) or str(result["url"])
            domain = _domain(url)
            is_configured_official = any(domain == official or domain.endswith("." + official) for official in official_domains)
            source = {
                "source_id": len(sources) + 1,
                "url": url,
                "domain": domain,
                "independent_domain": _independent_domain(url),
                "title": _clean(page.get("title") or result.get("title"), 300),
                "text": text,
                "query": str(result.get("query") or ""),
                "official": bool(page.get("official") or result.get("official") or is_configured_official),
                "official_path": bool(result.get("official_path")),
                "published_at": _clean(page.get("published_at") or result.get("published_at"), 80),
                "fetched_at": now,
                "expires_at": now + ttl_sec,
            }
            sources.append(source)
        return {"queries": query_list, "sources": sources, "fetched_at": now, "expires_at": now + ttl_sec}

    def _evidence(self, sources: List[Dict[str, Any]]) -> str:
        if not sources:
            return "Источники не прочитаны."
        total_chars = max(2000, int(self.cfg.get("news_agent_total_evidence_chars", 20000) or 20000))
        per_source = max(600, total_chars // len(sources))
        blocks = []
        for source in sources:
            blocks.append(
                f"[SOURCE {source['source_id']}]\n"
                f"URL: {source['url']}\nDOMAIN: {source['independent_domain']}\nOFFICIAL: {source['official']}\n"
                f"PUBLISHED_AT: {source['published_at']}\nFETCHED_AT: {source['fetched_at']}\nEXPIRES_AT: {source['expires_at']}\n"
                f"TITLE: {source['title']}\nTEXT: {source['text'][:per_source]}"
            )
        return "\n\n".join(blocks)[:total_chars]

    def _selected_model(self) -> str:
        configured = str(self.cfg.get("news_agent_model") or self.cfg.get("lm_model") or "local-model")
        if configured != "local-model" or self.lm is None or not hasattr(self.lm, "list_models"):
            return configured
        models = self.lm.list_models()
        return str(models[0]) if models else configured

    def _generate(self, prompt: str, *, factcheck: bool) -> Dict[str, Any]:
        if self.lm is None:
            raise RuntimeError("LM client не подключён")
        response = self.lm.generate_plain_text(
            prompt,
            system=("Ты строгий фактчекер новостей." if factcheck else "Ты редактор проверяемой новостной ленты радио."),
            temperature=(0.05 if factcheck else float(self.cfg.get("news_agent_temperature", 0.15) or 0.15)),
            max_tokens=int(self.cfg.get("news_agent_max_tokens", 1800) or 1800),
            timeout=int(self.cfg.get("news_agent_timeout_sec", 150) or 150),
            model=self._selected_model(),
            structured_output=bool(self.cfg.get("news_agent_structured_output", True)),
            response_schema=(NEWS_FACTCHECK_SCHEMA if factcheck else NEWS_DRAFT_SCHEMA),
            no_think=bool(self.cfg.get("news_agent_no_think", True)),
        )
        return _json_object(response)

    def _draft_items(self, data: Dict[str, Any], sources: List[Dict[str, Any]], now: int) -> List[Dict[str, Any]]:
        source_by_id = {int(source["source_id"]): source for source in sources}
        valid_ids = set(source_by_id)
        max_items = max(1, int(self.cfg.get("news_agent_max_items", 8) or 8))
        out = []
        for index, raw in enumerate(data.get("items") or [], 1):
            if not isinstance(raw, dict):
                continue
            title = _clean(raw.get("title"), 220)
            summary = _clean(raw.get("summary"), 1000)
            source_ids = _valid_source_ids(raw.get("source_ids"), valid_ids)
            cited = [source_by_id[source_id] for source_id in source_ids]
            published = sorted(str(source.get("published_at") or "") for source in cited if source.get("published_at"))
            item = {
                "draft_id": f"news-{index}",
                "title": title,
                "summary": summary,
                "source_ids": source_ids,
                "source_domains": sorted({str(source["independent_domain"]) for source in cited}),
                "official_source_ids": [int(source["source_id"]) for source in cited if source.get("official")],
                "published_at": published[-1] if published else "",
                "fetched_at": now,
                "expires_at": min((int(source["expires_at"]) for source in cited), default=now),
                "origin": "news_agent",
                "status": "draft",
                "status_history": [{"status": "draft", "at": now}],
            }
            if len(title) < 8 or len(summary) < 30 or not source_ids:
                item = transition_item(self.cfg, item, "rejected", reason="invalid_draft", at=now)
            out.append(item)
            if len(out) >= max_items:
                break
        return out

    def _factcheck_items(self, items: List[Dict[str, Any]], checked: Dict[str, Any], sources: List[Dict[str, Any]], now: int) -> None:
        source_by_id = {int(source["source_id"]): source for source in sources}
        valid_ids = set(source_by_id)
        min_domains = max(2, int(self.cfg.get("news_agent_min_independent_domains", 2) or 2))
        decisions = {
            str(raw.get("draft_id") or ""): raw
            for raw in (checked.get("items") or [])
            if isinstance(raw, dict)
        }
        for index, item in enumerate(items):
            if item.get("status") == "rejected":
                continue
            decision = decisions.get(str(item.get("draft_id") or ""))
            if not decision:
                items[index] = transition_item(self.cfg, item, "rejected", reason="factcheck_missing", at=now)
                continue
            source_ids = _valid_source_ids(decision.get("source_ids"), valid_ids)
            cited = [source_by_id[source_id] for source_id in source_ids]
            official_ids = [int(source["source_id"]) for source in cited if source.get("official")]
            domains = sorted({str(source["independent_domain"]) for source in cited})
            item = dict(item)
            item["source_ids"] = source_ids
            item["source_domains"] = domains
            item["official_source_ids"] = official_ids
            item["factcheck_notes"] = _clean(decision.get("notes"), 500)
            item["expires_at"] = min((int(source["expires_at"]) for source in cited), default=now)
            result = str(decision.get("decision") or "rejected").casefold()
            if not source_ids or item["expires_at"] <= now:
                status, reason = "rejected", "factcheck_sources_invalid_or_expired"
            elif result == "rejected":
                status, reason = "rejected", "factcheck_rejected"
            elif result == "review":
                status, reason = "review", "factcheck_requested_review"
            elif official_ids:
                status, reason = "verified", "official_source"
            elif len(domains) >= min_domains:
                status, reason = "verified", "independent_domains"
            else:
                status, reason = "review", "insufficient_independent_domains"
            items[index] = transition_item(self.cfg, item, status, reason=reason, at=now)

    def _deduplicate(self, items: List[Dict[str, Any]], now: int) -> List[Dict[str, Any]]:
        previous = used_content(self.cfg)
        accepted: List[str] = []
        out = []
        for item in items:
            if item.get("status") == "rejected":
                out.append(item)
                continue
            text = content_text(item)
            if any(is_similar(text, old) for old in [*previous, *accepted]):
                out.append(transition_item(self.cfg, item, "rejected", reason="duplicate", at=now))
            else:
                accepted.append(text)
                out.append(item)
        return out

    def _fallback_pack(
        self,
        queries: List[str],
        sources: List[Dict[str, Any]],
        generated: List[Dict[str, Any]],
        *,
        now: int,
        reason: str,
    ) -> Dict[str, Any]:
        ttl = max(60, int(self.cfg.get("news_agent_cache_ttl_sec", 21600) or 21600))
        fallback = load_fallback_items(self.cfg, now=now, ttl_sec=ttl)
        return {
            "schema_version": 1,
            "created_at": now,
            "expires_at": now + ttl,
            "config": self._cache_signature(queries),
            "queries": queries,
            "sources": sources,
            "items": [*generated, *fallback],
            "fallback_used": True,
            "fallback_reason": reason,
        }

    def build(self, queries: Optional[Iterable[str]] = None, *, force: bool = False) -> Dict[str, Any]:
        query_list = self._queries(queries)
        if not force:
            cached = self.load_cache(query_list)
            if cached is not None:
                return cached

        research = self.collect_sources(query_list)
        sources = research["sources"]
        now = int(self.now_fn())
        if not sources or self.lm is None:
            pack = self._fallback_pack(query_list, sources, [], now=now, reason="sources_or_lm_unavailable")
            save_json(self._cache_path(), pack)
            return pack

        evidence = self._evidence(sources)
        try:
            draft_data = self._generate(
                "Собери короткие актуальные новости для радио только из SOURCE. Не объединяй несвязанные события. "
                "Каждый source_id обязан подтверждать заголовок и summary. Верни только JSON.\n\n" + evidence,
                factcheck=False,
            )
            items = self._draft_items(draft_data, sources, now)
            if bool(self.cfg.get("news_agent_factcheck_enabled", True)):
                factcheck_payload = [
                    {
                        "draft_id": item["draft_id"],
                        "title": item["title"],
                        "summary": item["summary"],
                        "source_ids": item["source_ids"],
                    }
                    for item in items
                    if item.get("status") == "draft"
                ]
                checked = self._generate(
                    "Вторым независимым проходом проверь каждый DRAFT по SOURCE. Не переписывай новость. "
                    "verified ставь только при полном подтверждении, review — при сомнении, rejected — при ошибке. "
                    "Верни draft_id, decision, подтверждающие source_ids и notes.\n\nDRAFTS:\n"
                    + json.dumps(factcheck_payload, ensure_ascii=False)
                    + "\n\nSOURCE:\n"
                    + evidence,
                    factcheck=True,
                )
                self._factcheck_items(items, checked, sources, now)
            else:
                items = [
                    transition_item(self.cfg, item, "review", reason="factcheck_disabled", at=now)
                    if item.get("status") == "draft"
                    else item
                    for item in items
                ]
            items = self._deduplicate(items, now)
        except Exception as exc:
            log(f"NewsAgent: генерация или фактчек не сработали: {exc}")
            pack = self._fallback_pack(query_list, sources, [], now=now, reason="generation_or_factcheck_failed")
            save_json(self._cache_path(), pack)
            return pack

        verified = [item for item in items if item.get("status") == "verified"]
        ttl = max(60, int(self.cfg.get("news_agent_cache_ttl_sec", 21600) or 21600))
        if not verified:
            pack = self._fallback_pack(query_list, sources, items, now=now, reason="no_verified_items")
        else:
            pack = {
                "schema_version": 1,
                "created_at": now,
                "expires_at": min(now + ttl, min(int(item["expires_at"]) for item in verified)),
                "config": self._cache_signature(query_list),
                "queries": query_list,
                "sources": sources,
                "items": items,
                "fallback_used": False,
                "fallback_reason": "",
            }
        save_json(self._cache_path(), pack)
        return pack

    def schedule(self, item: Dict[str, Any], *, mode: str = "live", at: int | None = None) -> Dict[str, Any]:
        scheduled = dict(item)
        scheduled["scheduled_from"] = str(item.get("status") or "verified")
        return transition_item(self.cfg, scheduled, "scheduled", mode=mode, at=at, persist=True)

    def mark_aired(self, item: Dict[str, Any], *, mode: str = "live", at: int | None = None) -> Dict[str, Any]:
        return transition_item(self.cfg, item, "aired", mode=mode, at=at, persist=True)

    def release(self, item: Dict[str, Any], *, mode: str = "cancelled", at: int | None = None) -> Dict[str, Any]:
        """Release a scheduled item when TTS/plan playback never reached air."""
        target = str(item.get("scheduled_from") or "verified")
        if target not in {"verified", "review"}:
            target = "verified"
        return transition_item(
            self.cfg,
            item,
            target,
            reason="schedule_released",
            mode=mode,
            at=at,
            persist=True,
        )

    def select_next(self, pack: Dict[str, Any], *, mode: str = "live", at: int | None = None) -> Optional[Dict[str, Any]]:
        already_used = used_content(self.cfg)
        candidates = [item for item in (pack.get("items") or []) if isinstance(item, dict) and item.get("status") == "verified"]
        candidates += [
            item
            for item in (pack.get("items") or [])
            if isinstance(item, dict) and item.get("status") == "review" and item.get("origin") == "fallback_file"
        ]
        for item in candidates:
            if not any(is_similar(content_text(item), previous) for previous in already_used):
                return self.schedule(item, mode=mode, at=at)
        return None
