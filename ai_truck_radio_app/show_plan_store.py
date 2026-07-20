# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from ai_truck_radio_app.tracks import PlannedItem


@dataclass
class RestoredShowPlan:
    items: List[PlannedItem] = field(default_factory=list)
    next_index: int = 0
    stale_audio_indices: set[int] = field(default_factory=set)
    created_ts: int = 0
    reason: str = ""


class ShowPlanStore:
    """Persist and restore an application-owned show plan safely.

    The JSON file is metadata only.  Restoring arbitrary paths from a hand
    edited file would otherwise turn the player into a local-file reader, so
    every item must stay under the configured music or cache root.
    """

    VERSION = 2

    def __init__(
        self,
        output_path: Path,
        *,
        music_root: Path,
        cache_root: Path,
        max_items: int = 1000,
        max_age_hours: float = 168.0,
    ) -> None:
        self.output_path = output_path.resolve()
        self.music_root = music_root.resolve()
        self.cache_root = cache_root.resolve()
        self.max_items = max(1, min(int(max_items), 5000))
        self.max_age_sec = max(0.0, float(max_age_hours)) * 3600.0

    @staticmethod
    def _under(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _allowed_path(self, kind: str, raw: Any) -> Path | None:
        try:
            path = Path(str(raw or ""))
            if not path.is_absolute():
                root = self.music_root if kind == "music" else self.cache_root
                path = root / path
            path = path.resolve()
        except Exception:
            return None
        expected_root = self.music_root if kind == "music" else self.cache_root
        if not self._under(path, expected_root) or not path.is_file():
            return None
        return path

    @staticmethod
    def _history_keys(raw: Any) -> List[str]:
        keys: List[str] = []
        for value in raw if isinstance(raw, list) else []:
            key = str(value or "").strip()[:500]
            if key and key not in keys:
                keys.append(key)
        return keys[:32]

    @staticmethod
    def _news_items(raw: Any) -> List[Dict[str, Any]]:
        allowed = {
            "draft_id", "title", "summary", "status", "status_reason",
            "status_history", "scheduled_from", "source_ids", "source_domains",
            "official_source_ids", "published_at", "fetched_at", "expires_at",
            "origin", "scheduled_at",
        }
        out: List[Dict[str, Any]] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            clean = {key: value for key, value in item.items() if key in allowed}
            clean["title"] = str(clean.get("title") or "")[:300]
            clean["summary"] = str(clean.get("summary") or "")[:1500]
            if clean.get("draft_id") and clean.get("status") == "scheduled":
                out.append(clean)
        return out[:4]

    def save(
        self,
        items: Sequence[PlannedItem],
        *,
        next_index: int = 0,
        stale_audio_indices: Iterable[int] = (),
        metadata: Dict[str, Any] | None = None,
    ) -> Path:
        stale = {int(index) for index in stale_audio_indices}
        payload: Dict[str, Any] = {
            "version": self.VERSION,
            "created_ts": int(time.time()),
            "next_index": max(0, min(int(next_index), len(items))),
            "items": [
                {
                    "kind": item.kind,
                    "path": str(item.path),
                    "title": str(item.title)[:1000],
                    "text": str(item.text)[:20000],
                    "duration_sec": max(0.0, float(item.duration_sec or 0.0)),
                    "audio_ready": index not in stale,
                    "history_keys": self._history_keys(item.history_keys),
                    "news_items": self._news_items(item.news_items),
                }
                for index, item in enumerate(items)
            ],
        }
        if metadata:
            for key, value in metadata.items():
                if key not in payload:
                    payload[key] = value
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.output_path)
        return self.output_path

    def load(self) -> RestoredShowPlan:
        try:
            raw = json.loads(self.output_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return RestoredShowPlan(reason="saved plan not found")
        except Exception as exc:
            return RestoredShowPlan(reason=f"invalid saved plan: {exc}")
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            return RestoredShowPlan(reason="invalid saved plan structure")
        entries = raw["items"]
        if not entries or len(entries) > self.max_items:
            return RestoredShowPlan(reason="saved plan is empty or too large")
        created_ts = int(raw.get("created_ts") or 0)
        if self.max_age_sec and created_ts and time.time() - created_ts > self.max_age_sec:
            return RestoredShowPlan(created_ts=created_ts, reason="saved plan expired")

        items: List[PlannedItem] = []
        stale: set[int] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                return RestoredShowPlan(created_ts=created_ts, reason="invalid saved plan item")
            kind = str(entry.get("kind") or "").strip().lower()
            if kind not in {"music", "speech", "jingle"}:
                return RestoredShowPlan(created_ts=created_ts, reason="unsupported saved plan item")
            path = self._allowed_path(kind, entry.get("path"))
            if path is None:
                return RestoredShowPlan(created_ts=created_ts, reason="saved plan references a missing or unsafe file")
            item = PlannedItem(
                kind=kind,
                path=path,
                title=str(entry.get("title") or "")[:1000],
                text=str(entry.get("text") or "")[:20000],
                duration_sec=max(0.0, float(entry.get("duration_sec") or 0.0)),
                history_keys=self._history_keys(entry.get("history_keys")),
                news_items=self._news_items(entry.get("news_items")),
            )
            items.append(item)
            if kind == "speech" and not bool(entry.get("audio_ready", True)):
                stale.add(len(items) - 1)
        next_index = max(0, min(int(raw.get("next_index") or 0), len(items)))
        return RestoredShowPlan(
            items=items,
            next_index=next_index,
            stale_audio_indices=stale,
            created_ts=created_ts,
            reason="restored",
        )
