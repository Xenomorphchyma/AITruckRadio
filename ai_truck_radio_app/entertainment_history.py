# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ai_truck_radio_app.config import BASE_DIR, log


_LOCK = threading.Lock()


def _path(cfg: Dict[str, Any]) -> Path:
    value = str(cfg.get("entertainment_history_file") or "cache/entertainment_history.json")
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


def fingerprint(kind: str, item: Dict[str, Any], date: str = "") -> str:
    if kind == "horoscope":
        source = f"{date}|{item.get('sign', '')}"
    elif kind == "riddle":
        source = str(item.get("question") or "")
    elif kind == "wrong_game":
        source = str(item.get("question") or "")
    else:
        source = json.dumps(item, ensure_ascii=False, sort_keys=True)
    normalized = re.sub(r"[^a-zа-яё0-9]+", " ", source.casefold()).strip()
    return f"{kind}:{normalized}"


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", " ", str(value or "").casefold()).strip()


def _similar_question(left: str, right: str) -> bool:
    if SequenceMatcher(None, left, right).ratio() >= 0.86:
        return True
    left_words, right_words = set(left.split()), set(right.split())
    if not left_words or not right_words:
        return False
    return len(left_words & right_words) / len(left_words | right_words) >= 0.78


def load_items(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = _path(cfg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict) and item.get("key")]
    except FileNotFoundError:
        return []
    except Exception as exc:
        log(f"Не удалось прочитать журнал рубрик {path}: {exc}")
        return []


def used_keys(cfg: Dict[str, Any]) -> set[str]:
    return {str(item.get("key")) for item in load_items(cfg)}


def filter_unused(cfg: Dict[str, Any], kind: str, items: Iterable[Dict[str, Any]], date: str = "") -> List[Dict[str, Any]]:
    history = load_items(cfg)
    used = {str(item.get("key")) for item in history}
    previous_texts = [
        _normalized_text(item.get("text"))
        for item in history
        if item.get("kind") == kind and item.get("text")
    ]
    out = []
    for item in items:
        if fingerprint(kind, item, date) in used:
            continue
        if kind in {"riddle", "wrong_game"}:
            current = _normalized_text(item.get("question"))
            if current and any(_similar_question(current, old) for old in previous_texts):
                continue
        out.append(item)
    return out


def mark_used(cfg: Dict[str, Any], kind: str, item: Dict[str, Any], *, date: str = "", mode: str = "live") -> None:
    path = _path(cfg)
    key = fingerprint(kind, item, date)
    limit = max(100, int(cfg.get("entertainment_history_max_items", 1000) or 1000))
    with _LOCK:
        items = load_items(cfg)
        if any(str(entry.get("key")) == key for entry in items):
            return
        text = str(item.get("question") or item.get("sign") or item.get("title") or "")[:300]
        items.append({
            "kind": kind,
            "key": key,
            "text": text,
            "date": date,
            "mode": mode,
            "selected_ts": int(time.time()),
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"version": 1, "items": items[-limit:]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def prompt_exclusions(cfg: Dict[str, Any], limit: int = 120) -> List[str]:
    items = load_items(cfg)
    out = []
    for item in reversed(items):
        if item.get("kind") not in {"riddle", "wrong_game"}:
            continue
        text = str(item.get("text") or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def clear_history(cfg: Dict[str, Any]) -> int:
    path = _path(cfg)
    with _LOCK:
        count = len(load_items(cfg))
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return count
