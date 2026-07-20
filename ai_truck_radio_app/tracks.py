# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_truck_radio_app.config import (
    BASE_DIR,
    MUSIC_EXTS,
    executable_exists,
    find_ffprobe,
    log,
    run_subprocess,
)


@dataclass(frozen=True)
class Track:
    path: Path
    title: str
    artist: str

    @property
    def display_name(self) -> str:
        if self.artist:
            return f"{self.artist} — {self.title}"
        return self.title


@dataclass
class PreparedDJ:
    mp3: Path
    text: str
    previous_key: str
    next_key: str
    created_ts: float
    history_keys: List[str] = field(default_factory=list)
    news_items: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PlannedItem:
    kind: str  # music | speech | jingle
    path: Path
    title: str
    text: str = ""
    duration_sec: float = 0.0
    # Content (news/rubric/guest) reservations attached to this speech block.
    # They are promoted from ``scheduled`` to ``aired`` only after the audio
    # was actually streamed, so deleting a plan cannot consume unused content.
    history_keys: List[str] = field(default_factory=list)
    news_items: List[Dict[str, Any]] = field(default_factory=list)


def track_key(track: Optional[Track]) -> str:
    return str(track.path.resolve()).lower() if track else ""


def _clean_track_title_piece(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("_", " ")
    text = re.sub(r"[★☆]+", " ", text)
    text = re.sub(r"(?i)\b(the\s+original\s+song|original\s+song|eng\s+subs?|english\s+subs?|rus\s+subs?|lyrics?|lyric\s+video|official\s+video|official\s+audio|audio|video|clip|remaster(?:ed)?|extended|final|full|hd|hq)\b", " ", text)
    text = re.sub(r"[\[\(].{0,80}?(?:official|lyrics?|subs?|audio|video|clip|hd|hq).{0,80}?[\]\)]", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -—–|•·.,")
    return text.strip()


def _humanize_compact_title(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return raw
    raw = raw.replace("-", " ").replace("_", " ")
    raw = re.sub(r"(?<=[a-zа-яё])(?=[A-ZА-ЯЁ])", " ", raw)
    raw = re.sub(r"(?i)\b(final|extended|full|version|ver|remix-final-extended)\b", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" -—–_|.,")
    return raw or text


def _pretty_artist_name(text: str) -> str:
    raw = str(text or "").strip()
    # Generic cleanup only. Do not hard-code particular artists here.
    if not raw:
        return raw
    return re.sub(r"\s+", " ", raw).strip()


def has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", str(text or "")))


def _looks_like_upload_noise(text: str) -> bool:
    return bool(re.search(r"(?i)\b(original\s+song|eng\s+subs?|rus\s+subs?|subtitles?|official|lyrics?|audio|video|clip|hd|hq)\b|[★☆_]", str(text or "")))


def _artist_candidate_from_noisy_right(right: str) -> str:
    # Generic upload pattern: "Title - Artist ★ original song _ title eng subs".
    # Take the leading part before separators/noise words as the probable artist.
    raw = str(right or "").strip()
    raw = re.split(r"[★☆_|]", raw, maxsplit=1)[0]
    raw = re.split(r"(?i)\b(the\s+original\s+song|original\s+song|official|lyrics?|audio|video|clip|eng\s+subs?|rus\s+subs?)\b", raw, maxsplit=1)[0]
    raw = _clean_track_title_piece(raw)
    words = raw.split()
    if 1 <= len(words) <= 4:
        return raw
    return ""


def parse_track_name(path: Path) -> Tuple[str, str]:
    name = path.stem.strip()
    normalized = name.replace("_", " ")
    for sep in [" - ", " — ", " – "]:
        if sep in normalized:
            left, right = normalized.split(sep, 1)
            left_clean = _clean_track_title_piece(left)
            right_clean = _clean_track_title_piece(right)
            # Most music files are "Artist - Title".
            # But many YouTube uploads are "Title - Artist ★ original song ...".
            # Use a generic rule, not artist-specific hacks: if the right side contains
            # upload noise and begins with a short artist-like token, treat left as title.
            right_artist = _artist_candidate_from_noisy_right(right) if _looks_like_upload_noise(right) else ""
            if right_artist and left_clean and len(left_clean.split()) <= 6:
                return left_clean, _pretty_artist_name(right_artist)
            return right_clean or name, _pretty_artist_name(left_clean)
    return _humanize_compact_title(_clean_track_title_piece(name) or name), ""

def scan_music(music_dir: Path) -> List[Track]:
    music_dir.mkdir(parents=True, exist_ok=True)
    tracks: List[Track] = []
    for p in music_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in MUSIC_EXTS:
            title, artist = parse_track_name(p)
            tracks.append(Track(path=p, title=title, artist=artist))
    tracks.sort(key=lambda t: str(t.path).lower())
    return tracks




def track_profile_key_for_path(path: Path, base_dir: Optional[Path] = None) -> str:
    """Stable key for track profile cache."""
    try:
        if base_dir:
            rel = path.resolve().relative_to(base_dir.resolve())
            return str(rel).replace('\\', '/').lower()
    except Exception:
        pass
    try:
        return str(path.resolve()).replace('\\', '/').lower()
    except Exception:
        return str(path).replace('\\', '/').lower()


def _profile_key_from_item(item: Dict[str, Any]) -> str:
    for key in ("file", "path", "file_name", "filename", "track_key", "source_file"):
        val = str(item.get(key) or "").strip()
        if val:
            return val.replace("\\", "/").lower()
    artist = str(item.get("artist") or "").strip()
    title = str(item.get("title") or item.get("display_title") or "").strip()
    if artist and title:
        return f"{artist} - {title}".lower()
    return title.lower()


def _coerce_track_profiles(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        nested = data.get("tracks")
        if isinstance(nested, (list, dict)):
            return _coerce_track_profiles(nested)
        return data
    if isinstance(data, list):
        out: Dict[str, Any] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            key = _profile_key_from_item(item)
            if key:
                out[key] = item
        return out
    return {}


def load_track_profiles(cfg: Dict[str, Any]) -> Dict[str, Any]:
    raw_path = str(cfg.get('track_profiles_file', 'cache/track_profiles.json') or 'cache/track_profiles.json')
    path = Path(raw_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        return _coerce_track_profiles(data)
    except Exception as e:
        log(f'Не удалось прочитать профили треков {path}: {e}')
    return {}


def _sanitize_profile_text(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    replacements = [
        (r"(?i)\bдорожн(?:ый|ая|ое|ые|ого|ому|ым|ом|ой|ую)\s+эфир\b", "музыкальный эфир"),
        (r"(?i)\bдорожн(?:ый|ая|ое|ые|ого|ому|ым|ом|ой|ую)\s+радио\b", "музыкальное радио"),
        (r"(?i)\bв\s+дороге\b", "на фоне дня"),
        (r"(?i)\bдля\s+дороги\b", "для эфира"),
        (r"(?i)\bбез\s+кабин[а-яё]*\b", "без ролевых образов"),
        (r"(?i)\bкабин[аеуы]?\b", "эфир"),
        (r"(?i)\bгрузовик[ае]?\b", "эфир"),
        (r"(?i)\bрейс[а-яё]*\b", "эфир"),
        (r"(?i)\bтрасс[а-яё]*\b", "эфир"),
        (r"(?i)\bEuro\s+Truck\s+Simulator\s*2?\b", "музыкальный эфир"),
        (r"(?i)\bVR\b", "эфир"),
    ]
    for pat, repl in replacements:
        text = re.sub(pat, repl, text)
    return re.sub(r"\s+", " ", text).strip()


def short_track_profile(track: Optional[Track], profiles: Dict[str, Any], music_dir: Path) -> str:
    if not track or not profiles:
        return ''
    keys = [
        track_profile_key_for_path(track.path, music_dir),
        track_profile_key_for_path(track.path, None),
        track.path.name.lower(),
        track.path.stem.lower(),
        track.display_name.lower(),
    ]
    item = None
    for k in keys:
        if k in profiles:
            item = profiles[k]
            break
    if item is None:
        display_l = track.display_name.lower()
        stem_l = track.path.stem.lower()
        for candidate in profiles.values():
            if not isinstance(candidate, dict):
                continue
            names = [
                str(candidate.get("display_title") or "").lower(),
                str(candidate.get("source_display_name") or "").lower(),
                str(candidate.get("title") or "").lower(),
                str(candidate.get("short_title_for_tts") or "").lower(),
            ]
            if display_l in names or stem_l in names:
                item = candidate
                break
    if not isinstance(item, dict):
        return ''
    parts = []
    # Всегда первым передаём каноническое название из файла/тегов.
    # Это защищает от MusicBrainz/Wikipedia-романизации вроде Aluminiovyye Ogurtsy,
    # когда сам файл и эфирное название русские: Кино — Алюминиевые огурцы.
    display = track.display_name
    parts.append(f'название для эфира: {display}')
    if has_cyrillic(display):
        parts.append('правило названия: в эфире используй русское написание из поля «название для эфира», не латинизацию из внешних баз')
    for label, key in [
        ('описание', 'description'),
        ('описание', 'summary'),
        ('описание', 'short_description'),
        ('исполнитель/контекст', 'artist_context'),
        ('исполнитель/контекст', 'creator_fact'),
        ('контекст трека', 'song_context'),
        ('контекст трека', 'song_fact'),
        ('факт из интернета', 'web_fact'),
        ('интересный факт', 'interesting_fact'),
        ('настроение', 'mood'),
        ('темп/энергия', 'energy'),
        ('жанр/вайб', 'genre'),
        ('как подводить', 'radio_angle'),
        ('чего избегать', 'avoid'),
    ]:
        val = _sanitize_profile_text(str(item.get(key) or '').strip())
        if val:
            parts.append(f'{label}: {val}')
    facts = item.get("facts")
    if isinstance(facts, list):
        fact_text = "; ".join(_sanitize_profile_text(str(x)) for x in facts[:3] if str(x).strip())
        if fact_text:
            parts.append(f"факты: {fact_text}")
    sources = item.get('sources')
    if isinstance(sources, list) and sources:
        src_text = ', '.join(str(x).strip() for x in sources[:3] if str(x).strip())
        if src_text:
            parts.append(f'источники: {src_text}')
    return '; '.join(parts)[:1200]


def ffprobe_duration(cfg: Dict[str, Any], path: Path) -> Optional[float]:
    probe = find_ffprobe(cfg)
    if not executable_exists(probe):
        return None
    try:
        res = run_subprocess([
            probe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ], timeout=20)
        if res.returncode != 0:
            return None
        val = float((res.stdout or "").strip())
        if val > 0:
            return val
    except Exception:
        return None
    return None


