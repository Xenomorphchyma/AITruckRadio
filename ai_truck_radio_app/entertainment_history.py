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


def _safe_cache_path(value: Any) -> Path:
    """History is application-owned data; never follow a config path outside cache."""
    cache_root = (BASE_DIR / "cache").resolve()
    candidate = Path(str(value or "entertainment_history.json"))
    if candidate.is_absolute():
        path = candidate.resolve()
    else:
        # Accept the historical `cache/foo.json` spelling as well as `foo.json`.
        raw = candidate.as_posix()
        path = (BASE_DIR / candidate if raw.startswith("cache/") else cache_root / candidate).resolve()
    try:
        path.relative_to(cache_root)
    except ValueError:
        log(f"Небезопасный путь журнала рубрик отклонён: {candidate}")
        return cache_root / "entertainment_history.json"
    return path


def _path(cfg: Dict[str, Any]) -> Path:
    value = str(cfg.get("entertainment_history_file") or "cache/entertainment_history.json")
    # Programmatic callers historically supplied an absolute temporary path.
    # The HTTP API rejects that input; keep this compatibility for local tests
    # and integrations while `clear_history` verifies ownership before unlinking.
    path = Path(value)
    return path if path.is_absolute() else _safe_cache_path(value)


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


def _write_items(path: Path, items: List[Dict[str, Any]], limit: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"version": 2, "items": items[-limit:]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def mark_used(cfg: Dict[str, Any], kind: str, item: Dict[str, Any], *, date: str = "", mode: str = "live") -> str:
    """Reserve planned content or record content that was selected in Live.

    Historical callers keep using ``mark_used``.  Planned selection is now a
    reversible reservation; it becomes permanently used only after the speech
    block is actually aired via :func:`mark_aired`.
    """
    path = _path(cfg)
    key = fingerprint(kind, item, date)
    limit = max(100, int(cfg.get("entertainment_history_max_items", 1000) or 1000))
    state = "scheduled" if mode in {"planned", "live_pending"} else "aired"
    with _LOCK:
        items = load_items(cfg)
        for entry in items:
            if str(entry.get("key")) != key:
                continue
            # A Live selection is considered consumed immediately for backward
            # compatibility.  It may promote a previously scheduled entry.
            if state == "aired" and str(entry.get("state") or "aired") != "aired":
                entry["state"] = "aired"
                entry["mode"] = mode
                entry["aired_ts"] = int(time.time())
                _write_items(path, items, limit)
            return key
        text = str(item.get("question") or item.get("sign") or item.get("title") or "")[:300]
        entry = {
            "kind": kind,
            "key": key,
            "text": text,
            "date": date,
            "mode": mode,
            "state": state,
            "selected_ts": int(time.time()),
        }
        entry["scheduled_ts" if state == "scheduled" else "aired_ts"] = int(time.time())
        items.append(entry)
        _write_items(path, items, limit)
    return key


def mark_aired(cfg: Dict[str, Any], keys: Iterable[str]) -> int:
    wanted = {str(key) for key in keys if str(key)}
    if not wanted:
        return 0
    path = _path(cfg)
    limit = max(100, int(cfg.get("entertainment_history_max_items", 1000) or 1000))
    changed = 0
    with _LOCK:
        items = load_items(cfg)
        for entry in items:
            if str(entry.get("key")) in wanted and str(entry.get("state") or "aired") != "aired":
                entry["state"] = "aired"
                entry["aired_ts"] = int(time.time())
                changed += 1
        if changed:
            _write_items(path, items, limit)
    return changed


def release_scheduled(cfg: Dict[str, Any], keys: Iterable[str] | None = None) -> int:
    """Release reservations from a discarded plan without touching aired data."""
    wanted = None if keys is None else {str(key) for key in keys if str(key)}
    path = _path(cfg)
    limit = max(100, int(cfg.get("entertainment_history_max_items", 1000) or 1000))
    with _LOCK:
        items = load_items(cfg)
        kept = [
            entry
            for entry in items
            if not (
                str(entry.get("state") or "aired") == "scheduled"
                and (wanted is None or str(entry.get("key")) in wanted)
            )
        ]
        removed = len(items) - len(kept)
        if removed:
            _write_items(path, kept, limit)
    return removed


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
        if path != _safe_cache_path(cfg.get("entertainment_history_file")):
            # Do not turn a hand-edited config into an arbitrary delete.  An
            # out-of-cache path is only removable when it is demonstrably our
            # history document, preserving the legacy local integration use.
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or raw.get("version") not in {1, 2} or not isinstance(raw.get("items"), list):
                    log(f"Удаление небезопасного журнала отклонено: {path}")
                    return 0
            except FileNotFoundError:
                return 0
            except Exception:
                log(f"Удаление небезопасного журнала отклонено: {path}")
                return 0
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return count
