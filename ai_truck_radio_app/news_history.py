# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ai_truck_radio_app.config import BASE_DIR, log, save_json


NEWS_STATUSES = ("draft", "verified", "review", "rejected", "scheduled", "aired")
_TRANSITIONS = {
    "draft": {"verified", "review", "rejected"},
    "verified": {"scheduled", "review", "rejected"},
    "review": {"verified", "scheduled", "rejected"},
    "scheduled": {"aired", "verified", "review", "rejected"},
    "aired": set(),
    "rejected": set(),
}
_LOCK = threading.RLock()


def _path(cfg: Dict[str, Any]) -> Path:
    value = Path(str(cfg.get("news_agent_history_file") or "cache/news_agent/history.json"))
    return value if value.is_absolute() else BASE_DIR / value


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", " ", str(value or "").casefold()).strip()


def content_text(item: Dict[str, Any]) -> str:
    return _normalized(f"{item.get('title', '')} {item.get('summary', '')}")


def fingerprint(item: Dict[str, Any]) -> str:
    value = content_text(item)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24] if value else ""


def is_similar(left: str, right: str) -> bool:
    left, right = _normalized(left), _normalized(right)
    if not left or not right:
        return False
    if SequenceMatcher(None, left, right).ratio() >= 0.86:
        return True
    left_words, right_words = set(left.split()), set(right.split())
    return bool(left_words and right_words and len(left_words & right_words) / len(left_words | right_words) >= 0.78)


def load_events(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = _path(cfg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        events = (data.get("events") or []) if isinstance(data, dict) else []
        if not isinstance(events, list):
            return []
        return [event for event in events if isinstance(event, dict) and event.get("status") in NEWS_STATUSES]
    except FileNotFoundError:
        return []
    except Exception as exc:
        log(f"Не удалось прочитать журнал новостей {path}: {exc}")
        return []


def used_content(cfg: Dict[str, Any], statuses: Iterable[str] = ("scheduled", "aired")) -> List[str]:
    wanted = set(statuses)
    # Status is event-sourced.  Only the latest event per fingerprint decides
    # whether content is still reserved; an earlier `scheduled` event must not
    # keep a cancelled plan blocked forever.
    latest: Dict[str, Dict[str, Any]] = {}
    for event in load_events(cfg):
        key = str(event.get("fingerprint") or event.get("content") or "")
        if key:
            latest[key] = event
    return [str(event.get("content") or "") for event in latest.values() if event.get("status") in wanted]


def _append_event(cfg: Dict[str, Any], item: Dict[str, Any], status: str, *, mode: str, at: int) -> None:
    path = _path(cfg)
    with _LOCK:
        events = load_events(cfg)
        events.append(
            {
                "fingerprint": fingerprint(item),
                "content": content_text(item),
                "title": str(item.get("title") or "")[:300],
                "status": status,
                "mode": mode,
                "at": at,
            }
        )
        limit = max(100, int(cfg.get("news_agent_history_max_items", 2000) or 2000))
        save_json(path, {"schema_version": 1, "events": events[-limit:]})


def transition_item(
    cfg: Dict[str, Any],
    item: Dict[str, Any],
    status: str,
    *,
    reason: str = "",
    mode: str = "",
    at: int | None = None,
    persist: bool = False,
) -> Dict[str, Any]:
    if status not in NEWS_STATUSES:
        raise ValueError(f"Неизвестный статус новости: {status}")
    current = str(item.get("status") or "draft")
    if current not in NEWS_STATUSES:
        raise ValueError(f"Некорректный текущий статус новости: {current}")
    if status != current and status not in _TRANSITIONS[current]:
        raise ValueError(f"Недопустимый переход новости: {current} -> {status}")

    changed_at = int(time.time() if at is None else at)
    out = dict(item)
    history = [dict(entry) for entry in (item.get("status_history") or []) if isinstance(entry, dict)]
    if not history:
        history.append({"status": current, "at": int(item.get("fetched_at") or changed_at)})
    if status != current:
        event = {"status": status, "at": changed_at}
        if reason:
            event["reason"] = reason
        history.append(event)
    out["status"] = status
    out["status_history"] = history
    out["status_updated_at"] = changed_at
    if reason:
        out["status_reason"] = reason
    if status == "scheduled":
        out["scheduled_at"] = changed_at
    elif status == "aired":
        out["aired_at"] = changed_at
    if persist and status != current:
        _append_event(cfg, out, status, mode=mode, at=changed_at)
    return out


def clear_history(cfg: Dict[str, Any]) -> int:
    path = _path(cfg)
    with _LOCK:
        count = len(load_events(cfg))
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return count
