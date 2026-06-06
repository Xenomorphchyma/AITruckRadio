# -*- coding: utf-8 -*-
from __future__ import annotations
import json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Tuple

from track_profile_agent import research_track

ROOT = Path(__file__).resolve().parents[1]
MUSICBRAINZ_DISABLED_UNTIL = 0.0
MUSICBRAINZ_ERROR_COUNT = 0
WIKIPEDIA_DISABLED_UNTIL = 0.0
WIKIPEDIA_CACHE = {}
WIKIDATA_CACHE = {}
MUSICBRAINZ_CACHE = {}
MUSIC_EXTS = {'.mp3','.flac','.wav','.ogg','.oga','.m4a','.aac','.opus','.wma'}
GENERIC_TITLE_WORDS = {
    'carousel', 'song', 'песня', 'music', 'музыка', 'track', 'трек', 'original', 'version', 'remix',
}
NOISE_WORDS = {
    'official', 'video', 'audio', 'lyrics', 'lyric', 'subs', 'sub', 'eng', 'rus', 'ru', 'en', 'original', 'song',
    'перевод', 'субтитры', 'клип', 'текст', 'music', 'hd', 'hq', 'full', 'version', 'версия'
}


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        pass
    return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def rel_key(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace('\\','/').lower()
    except Exception:
        return str(path.resolve()).replace('\\','/').lower()


def _clean_noise(text: str) -> str:
    text = text.replace('_', ' ').replace('★', ' ').replace('☆', ' ')
    text = re.sub(r'\[[^\]]*(official|audio|video|lyrics?|subs?|subtitles?|перевод|субтитры|hd|hq)[^\]]*\]', ' ', text, flags=re.I)
    text = re.sub(r'\([^)]*(official|audio|video|lyrics?|subs?|subtitles?|перевод|субтитры|hd|hq)[^)]*\)', ' ', text, flags=re.I)
    text = re.sub(r'\b(the\s+)?original\s+song\b', ' ', text, flags=re.I)
    text = re.sub(r'\b(eng|rus|ru|en)\s*(subs?|subtitles?)\b', ' ', text, flags=re.I)
    text = re.sub(r'\b(official|audio|video|lyrics?|subs?|subtitles?|hd|hq|full|final|extended)\b', ' ', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip(' -—–_|')
    return text.strip()


def _humanize_compact_title(text: str) -> str:
    raw = str(text or '').strip()
    if not raw:
        return raw
    raw = raw.replace('-', ' ').replace('_', ' ')
    raw = re.sub(r'(?<=[a-zа-яё])(?=[A-ZА-ЯЁ])', ' ', raw)
    raw = re.sub(r'(?i)\b(final|extended|full|version|ver)\b', ' ', raw)
    raw = re.sub(r'\s+', ' ', raw).strip(' -—–_|.,')
    return raw or text


def _words(text: str) -> List[str]:
    return [w.lower() for w in re.findall(r'[A-Za-zА-Яа-яЁё0-9]+', text or '') if len(w) > 1]


def has_cyrillic(text: str) -> bool:
    return bool(re.search(r'[А-Яа-яЁё]', str(text or '')))


def _looks_like_generic_title(text: str) -> bool:
    ws = set(_words(text))
    return bool(ws) and len(ws) <= 2 and bool(ws & GENERIC_TITLE_WORDS)


def _looks_like_upload_noise(text: str) -> bool:
    return bool(re.search(r'(?i)\b(original\s+song|eng\s+subs?|rus\s+subs?|subtitles?|official|lyrics?|audio|video|clip|hd|hq)\b|[★☆_]', str(text or '')))


def _artist_candidate_from_noisy_right(right: str) -> str:
    # Generic upload pattern: "Title - Artist ★ original song _ title eng subs".
    # Take the leading part before separators/noise words as the probable artist.
    raw = str(right or '').strip()
    raw = re.split(r'[★☆_|]', raw, maxsplit=1)[0]
    raw = re.split(r'(?i)\b(the\s+original\s+song|original\s+song|official|lyrics?|audio|video|clip|eng\s+subs?|rus\s+subs?)\b', raw, maxsplit=1)[0]
    raw = _clean_noise(raw)
    words = raw.split()
    if 1 <= len(words) <= 4:
        return raw
    return ''


def parse_name(path: Path) -> Tuple[str, str]:
    """Best-effort filename parser based on rules, not per-artist hacks.

    Common forms:
    - Artist - Title.mp3
    - Title - Artist ★ original song _ title eng subs.mp3
    """
    original = path.stem.strip()
    clean = _clean_noise(original)
    for sep in [' - ', ' — ', ' – ']:
        if sep in original.replace('_', ' '):
            left, right = [x.strip() for x in original.replace('_', ' ').split(sep, 1)]
            left_clean = _clean_noise(left)
            right_clean = _clean_noise(right)
            right_artist = _artist_candidate_from_noisy_right(right) if _looks_like_upload_noise(right) else ''
            if right_artist and left_clean and len(_words(left_clean)) <= 6:
                return right_artist.strip(), left_clean.strip()
            return left_clean.strip(), right_clean.strip()
    return '', _humanize_compact_title(clean or original)


def http_json(url: str, *, headers: Dict[str,str] | None = None, timeout: int = 12) -> Dict[str,Any]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', errors='replace'))


def request_json(method: str, url: str, payload: Dict[str,Any], timeout: int=90) -> Dict[str,Any]:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def model_text(
    base_url: str,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> str:
    payload = {
        'model': model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
        'stream': False,
    }
    data = request_json('POST', base_url.rstrip('/') + '/chat/completions', payload, timeout=timeout)
    return str(((data.get('choices') or [{}])[0].get('message') or {}).get('content') or '').strip()


def json_from_model_text(text: str) -> Dict[str, Any]:
    text = str(text or '').replace('```json', '').replace('```', '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start >= 0 and end > start:
        text = text[start:end + 1]
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError('LM Studio returned JSON of the wrong type')
    return obj


def pick_model(base_url: str, wanted: str) -> str:
    if wanted and wanted != 'local-model':
        return wanted
    try:
        data = http_json(base_url.rstrip('/') + '/models', timeout=10)
        arr = data.get('data') or []
        if arr:
            return str(arr[0].get('id') or 'local-model')
    except Exception:
        pass
    return wanted or 'local-model'


def _mb_record_matches(record: Dict[str,Any], artist: str, title: str) -> bool:
    title_l = (title or '').lower().strip()
    artist_l = (artist or '').lower().strip()
    rec_title = str(record.get('title') or '').lower()
    if title_l and title_l not in rec_title and rec_title not in title_l:
        return False
    if artist_l:
        artist_names = []
        for ac in record.get('artist-credit') or []:
            if isinstance(ac, dict) and isinstance(ac.get('artist'), dict):
                artist_names.append(str(ac['artist'].get('name') or '').lower())
        if artist_names and not any(artist_l in a or a in artist_l for a in artist_names):
            return False
    return True


def lookup_musicbrainz(cfg: Dict[str,Any], artist: str, title: str) -> Dict[str,Any]:
    global MUSICBRAINZ_DISABLED_UNTIL, MUSICBRAINZ_ERROR_COUNT
    if not cfg.get('track_profiles_web_lookup_enabled', True):
        return {}
    now = time.time()
    if MUSICBRAINZ_DISABLED_UNTIL > now:
        return {}
    cache_key = (artist or '', title or '')
    if cache_key in MUSICBRAINZ_CACHE:
        return MUSICBRAINZ_CACHE[cache_key]
    q_parts = []
    if title:
        q_parts.append(f'recording:"{title}"')
    if artist:
        q_parts.append(f'artist:"{artist}"')
    if not q_parts:
        return {}
    query = ' AND '.join(q_parts)
    url = 'https://musicbrainz.org/ws/2/recording/?fmt=json&limit=8&query=' + urllib.parse.quote(query)
    try:
        delay = float(cfg.get('track_profiles_web_delay_sec', 1.2) or 0)
        if delay > 0:
            time.sleep(min(5.0, delay))
        data = http_json(url, headers={
            'User-Agent': 'AITruckRadio/0.6.7 (local personal radio; contact: none)',
            'Accept': 'application/json',
        }, timeout=int(cfg.get('track_profiles_web_timeout_sec', 12) or 12))
        MUSICBRAINZ_ERROR_COUNT = 0
        recs = [r for r in (data.get('recordings') or []) if isinstance(r, dict)]
        recs = [r for r in recs if _mb_record_matches(r, artist, title)] or recs[:1]
        if not recs:
            MUSICBRAINZ_CACHE[cache_key] = {}
            return {}
        r0 = recs[0]
        artists = []
        for ac in r0.get('artist-credit') or []:
            if isinstance(ac, dict) and isinstance(ac.get('artist'), dict):
                nm = ac['artist'].get('name')
                if nm: artists.append(str(nm))
        releases = []
        first_date = ''
        for rel in r0.get('releases') or []:
            if isinstance(rel, dict):
                if rel.get('title'): releases.append(str(rel.get('title')))
                if not first_date and rel.get('date'): first_date = str(rel.get('date'))
        out = {
            'musicbrainz_title': str(r0.get('title') or ''),
            'musicbrainz_artists': ', '.join(artists[:3]),
            'musicbrainz_releases': ', '.join(dict.fromkeys(releases[:5])),
            'musicbrainz_first_date': first_date,
            'musicbrainz_score': str(r0.get('score') or ''),
            'source': 'MusicBrainz',
        }
        MUSICBRAINZ_CACHE[cache_key] = out
        return out
    except Exception as e:
        MUSICBRAINZ_ERROR_COUNT += 1
        print('[TrackProfiles] MusicBrainz lookup failed:', repr(e), flush=True)
        msg = repr(e).lower()
        if MUSICBRAINZ_ERROR_COUNT >= 2 or 'timeout' in msg or 'handshake' in msg:
            cooldown = int(cfg.get('track_profiles_musicbrainz_cooldown_sec', 60) or 60)
            MUSICBRAINZ_DISABLED_UNTIL = time.time() + cooldown
            print(f'[TrackProfiles] MusicBrainz temporarily paused for {cooldown}s after network timeout/errors', flush=True)
        MUSICBRAINZ_CACHE[cache_key] = {}
        return {}


def wiki_search_summary(lang: str, query: str, timeout: int) -> Dict[str,Any]:
    api = f'https://{lang}.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=3&srsearch=' + urllib.parse.quote(query)
    data = http_json(api, headers={'User-Agent':'AITruckRadio/0.6.7 local'}, timeout=timeout)
    hits = (data.get('query') or {}).get('search') or []
    for hit in hits:
        title = str(hit.get('title') or '')
        if not title:
            continue
        rest = f'https://{lang}.wikipedia.org/api/rest_v1/page/summary/' + urllib.parse.quote(title.replace(' ', '_'))
        sm = http_json(rest, headers={'User-Agent':'AITruckRadio/0.6.7 local'}, timeout=timeout)
        extract = str(sm.get('extract') or '').strip()
        page_url = ((sm.get('content_urls') or {}).get('desktop') or {}).get('page') or ''
        if extract:
            return {'title': title, 'extract': extract[:900], 'url': page_url, 'source': f'Wikipedia {lang}', '_query': query}
    return {}


def _valid_wiki_result(res: Dict[str,Any], artist: str, title: str) -> bool:
    if not res:
        return False
    hay = (str(res.get('title') or '') + ' ' + str(res.get('extract') or '')).lower()
    artist_l = (artist or '').lower().strip()
    title_l = (title or '').lower().strip()
    # Strong false positives: TV channel / generic media pages when the artist is absent.
    if any(bad in hay for bad in ['телеканал', 'tv channel', 'children\'s channel', 'детский канал']):
        if not artist_l or artist_l not in hay:
            return False
    if artist_l:
        # For artist+title tracks, Wikipedia page must at least mention the artist.
        if artist_l not in hay:
            return False
        return True
    # If no artist was parsed, avoid generic one-word title pages.
    if _looks_like_generic_title(title_l):
        return False
    return bool(title_l and title_l in hay)


def lookup_wikipedia(cfg: Dict[str,Any], artist: str, title: str) -> Dict[str,Any]:
    global WIKIPEDIA_DISABLED_UNTIL
    if not (cfg.get('track_profiles_web_lookup_enabled', True) and cfg.get('track_profiles_wikipedia_enabled', True)):
        return {}
    now = time.time()
    if WIKIPEDIA_DISABLED_UNTIL > now:
        return {}
    cache_key = (artist or '', title or '')
    if cache_key in WIKIPEDIA_CACHE:
        return WIKIPEDIA_CACHE[cache_key]
    timeout = int(cfg.get('track_profiles_web_timeout_sec', 12) or 12)
    queries: List[str] = []
    if artist and title:
        queries += [f'"{artist}" "{title}" song', f'"{artist}" "{title}"', f'{artist} {title} песня']
        # Do NOT fall back to title-only when artist exists: this caused "Carousel" -> TV channel.
        queries += [artist]
    elif artist:
        queries += [artist]
    elif title and not _looks_like_generic_title(title):
        queries += [f'{title} song', f'{title} песня']
    seen = set()
    for q in queries:
        if WIKIPEDIA_DISABLED_UNTIL > time.time():
            WIKIPEDIA_CACHE[cache_key] = {}
            return {}
        qn = q.strip().lower()
        if not qn or qn in seen:
            continue
        seen.add(qn)
        for lang in [x.strip() for x in str(cfg.get('track_profiles_wikipedia_languages', 'ru,en,uk,de')).split(',') if x.strip()]:
            try:
                delay = float(cfg.get('track_profiles_web_delay_sec', 1.2) or 0)
                if delay > 0:
                    time.sleep(min(5.0, delay))
                res = wiki_search_summary(lang, q, timeout)
                if _valid_wiki_result(res, artist, title):
                    WIKIPEDIA_CACHE[cache_key] = res
                    return res
            except urllib.error.HTTPError as e:
                if getattr(e, 'code', None) == 429:
                    cooldown = int(cfg.get('track_profiles_wikipedia_cooldown_sec', 90) or 90)
                    WIKIPEDIA_DISABLED_UNTIL = time.time() + cooldown
                    print(f'[TrackProfiles] Wikipedia rate-limited (429); paused for {cooldown}s, continuing without Wikipedia facts', flush=True)
                    WIKIPEDIA_CACHE[cache_key] = {}
                    return {}
                print('[TrackProfiles] Wikipedia lookup failed:', repr(e), flush=True)
            except Exception as e:
                print('[TrackProfiles] Wikipedia lookup failed:', repr(e), flush=True)
    WIKIPEDIA_CACHE[cache_key] = {}
    return {}


def lookup_wikidata(cfg: Dict[str,Any], artist: str, title: str) -> Dict[str,Any]:
    """Small fallback when Wikipedia/MusicBrainz are unavailable/rate-limited.
    Wikidata often has short labels/descriptions even when page summaries fail.
    """
    if not (cfg.get('track_profiles_web_lookup_enabled', True) and cfg.get('track_profiles_wikidata_enabled', True)):
        return {}
    cache_key = (artist or '', title or '')
    if cache_key in WIKIDATA_CACHE:
        return WIKIDATA_CACHE[cache_key]
    timeout = int(cfg.get('track_profiles_web_timeout_sec', 12) or 12)
    queries = []
    if artist and title:
        queries += [f'{artist} {title}', artist]
    elif artist:
        queries += [artist]
    elif title and not _looks_like_generic_title(title):
        queries += [title]
    seen = set()
    for q in queries:
        qn = q.lower().strip()
        if not qn or qn in seen:
            continue
        seen.add(qn)
        try:
            delay = float(cfg.get('track_profiles_web_delay_sec', 1.2) or 0)
            if delay > 0:
                time.sleep(min(5.0, delay))
            url = 'https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=ru&uselang=ru&limit=5&search=' + urllib.parse.quote(q)
            data = http_json(url, headers={'User-Agent':'AITruckRadio/0.6.7 local'}, timeout=timeout)
            for ent in data.get('search') or []:
                label = str(ent.get('label') or '')
                desc = str(ent.get('description') or '')
                hay = (label + ' ' + desc).lower()
                artist_l = (artist or '').lower().strip()
                title_l = (title or '').lower().strip()
                if artist_l and artist_l not in hay and label.lower() != artist_l:
                    continue
                if any(bad in hay for bad in ['телеканал', 'tv channel', 'игра', 'film', 'фильм']) and artist_l not in hay:
                    continue
                out = {
                    'label': label,
                    'description': desc[:500],
                    'id': str(ent.get('id') or ''),
                    'url': 'https://www.wikidata.org/wiki/' + str(ent.get('id') or ''),
                    'source': 'Wikidata',
                }
                WIKIDATA_CACHE[cache_key] = out
                return out
        except Exception as e:
            print('[TrackProfiles] Wikidata lookup failed:', repr(e), flush=True)
            break
    WIKIDATA_CACHE[cache_key] = {}
    return {}


def lookup_deezer(cfg: Dict[str,Any], artist: str, title: str) -> Dict[str,Any]:
    """Public Deezer search fallback. No API key. Returns compact metadata only."""
    if not (cfg.get('track_profiles_web_lookup_enabled', True) and cfg.get('track_profiles_deezer_enabled', True)):
        return {}
    if not (artist or title):
        return {}
    cache_key = (artist or '', title or '')
    if cache_key in globals().setdefault('DEEZER_CACHE', {}):
        return DEEZER_CACHE[cache_key]
    timeout = int(cfg.get('track_profiles_web_timeout_sec', 12) or 12)
    q = ' '.join(x for x in [artist, title] if x).strip()
    try:
        delay = float(cfg.get('track_profiles_web_delay_sec', 1.2) or 0)
        if delay > 0:
            time.sleep(min(5.0, delay))
        url = 'https://api.deezer.com/search/track?limit=5&q=' + urllib.parse.quote(q)
        data = http_json(url, headers={'User-Agent':'AITruckRadio/0.6.7 local'}, timeout=timeout)
        arr = data.get('data') or []
        artist_l = (artist or '').lower().strip()
        title_l = (title or '').lower().strip()
        best = None
        for item in arr:
            if not isinstance(item, dict):
                continue
            tr_title = str(item.get('title') or '')
            ar_name = str(((item.get('artist') or {}).get('name')) or '')
            hay_t = tr_title.lower(); hay_a = ar_name.lower()
            if title_l and title_l not in hay_t and hay_t not in title_l:
                continue
            if artist_l and artist_l not in hay_a and hay_a not in artist_l:
                continue
            best = item
            break
        if not best and arr:
            best = arr[0]
        if not best:
            DEEZER_CACHE[cache_key] = {}
            return {}
        out = {
            'title': str(best.get('title') or ''),
            'artist': str(((best.get('artist') or {}).get('name')) or ''),
            'album': str(((best.get('album') or {}).get('title')) or ''),
            'link': str(best.get('link') or ''),
            'source': 'Deezer',
        }
        DEEZER_CACHE[cache_key] = out
        return out
    except Exception as e:
        print('[TrackProfiles] Deezer lookup failed:', repr(e), flush=True)
        DEEZER_CACHE[cache_key] = {}
        return {}


def lookup_itunes(cfg: Dict[str,Any], artist: str, title: str) -> Dict[str,Any]:
    """Public Apple iTunes Search API fallback. No API key."""
    if not (cfg.get('track_profiles_web_lookup_enabled', True) and cfg.get('track_profiles_itunes_enabled', True)):
        return {}
    if not (artist or title):
        return {}
    cache_key = (artist or '', title or '')
    if cache_key in globals().setdefault('ITUNES_CACHE', {}):
        return ITUNES_CACHE[cache_key]
    timeout = int(cfg.get('track_profiles_web_timeout_sec', 12) or 12)
    q = ' '.join(x for x in [artist, title] if x).strip()
    try:
        delay = float(cfg.get('track_profiles_web_delay_sec', 1.2) or 0)
        if delay > 0:
            time.sleep(min(5.0, delay))
        url = 'https://itunes.apple.com/search?media=music&entity=song&limit=5&term=' + urllib.parse.quote(q)
        data = http_json(url, headers={'User-Agent':'AITruckRadio/0.6.7 local'}, timeout=timeout)
        arr = data.get('results') or []
        artist_l = (artist or '').lower().strip()
        title_l = (title or '').lower().strip()
        best = None
        for item in arr:
            if not isinstance(item, dict):
                continue
            tr_title = str(item.get('trackName') or '')
            ar_name = str(item.get('artistName') or '')
            hay_t = tr_title.lower(); hay_a = ar_name.lower()
            if title_l and title_l not in hay_t and hay_t not in title_l:
                continue
            if artist_l and artist_l not in hay_a and hay_a not in artist_l:
                continue
            best = item
            break
        if not best and arr:
            best = arr[0]
        if not best:
            ITUNES_CACHE[cache_key] = {}
            return {}
        out = {
            'title': str(best.get('trackName') or ''),
            'artist': str(best.get('artistName') or ''),
            'album': str(best.get('collectionName') or ''),
            'genre': str(best.get('primaryGenreName') or ''),
            'releaseDate': str(best.get('releaseDate') or ''),
            'url': str(best.get('trackViewUrl') or ''),
            'source': 'iTunes Search',
        }
        ITUNES_CACHE[cache_key] = out
        return out
    except Exception as e:
        print('[TrackProfiles] iTunes lookup failed:', repr(e), flush=True)
        ITUNES_CACHE[cache_key] = {}
        return {}


PROFILE_TEXT_FIELDS = [
    'display_title',
    'source_display_name',
    'artist',
    'title',
    'short_title_for_tts',
    'description',
    'artist_context',
    'song_context',
    'creator_fact',
    'song_fact',
    'web_fact',
    'interesting_fact',
    'mood',
    'energy',
    'genre',
    'radio_angle',
    'avoid',
]


def _agent_evidence_text(research: Dict[str, Any]) -> str:
    blocks = []
    for index, page in enumerate(research.get('pages') or [], 1):
        if not isinstance(page, dict):
            continue
        blocks.append(
            f'[SOURCE {index}]\n'
            f'URL: {page.get("url", "")}\n'
            f'TITLE: {page.get("title") or page.get("search_title") or ""}\n'
            f'TEXT:\n{page.get("text", "")}'
        )
    return '\n\n'.join(blocks)


def _agent_profile_prompt(artist: str, title: str, file_name: str, evidence: str) -> str:
    return f'''
Создай профиль музыкального трека для ведущих радиостанции. Работай только по материалам SOURCE ниже.
Не используй знания из памяти. Если факт не подтверждён текстом источника, оставь соответствующее поле пустым.
Не путай песню с одноимённым фильмом, игрой, телеканалом, мемом или другим произведением.

Верни строго один JSON без markdown. Схема:
{{
  "display_title": "Исполнитель — Название",
  "source_display_name": "каноническое эфирное название",
  "artist": "уточнённый исполнитель",
  "title": "уточнённое название/версия",
  "short_title_for_tts": "короткое произносимое название без служебного мусора",
  "description": "1–2 предложения о звучании и сильных сторонах трека",
  "artist_context": "краткий подтверждённый контекст исполнителя",
  "song_context": "краткий подтверждённый контекст песни/альбома/релиза",
  "creator_fact": "один подтверждённый факт об исполнителе",
  "song_fact": "один подтверждённый факт о треке",
  "web_fact": "Об исполнителе: ... О треке: ...",
  "interesting_fact": "лучший безопасный факт для эфира",
  "mood": "краткое настроение",
  "energy": "краткая динамика/энергия",
  "genre": "жанр или осторожно определённый музыкальный вайб",
  "radio_angle": "как естественно подвести трек в эфире",
  "avoid": "какие неподтверждённые утверждения и подмены нельзя допускать",
  "used_source_ids": [1, 2]
}}

Правила:
- `display_title`, `artist` и `title` можно уточнять по источникам, но не заменяй кириллицу файла латиницей без необходимости.
- Не копируй предложения со страниц. Перескажи и ужми материал простым русским языком для радиоведущего.
- artist_context, song_context, creator_fact, song_fact и interesting_fact — максимум одно короткое предложение каждое.
- description — максимум два коротких предложения; web_fact — максимум два коротких предложения.
- Убирай справочные подробности, которые неудобно или неинтересно произносить в эфире.
- Описание звучания, mood, energy и genre формулируй осторожно. Если страницы не описывают звук, не выдавай догадку за факт.
- Не привязывай подводку к утру, вечеру, дороге, машине, игре или конкретному состоянию слушателя.
- Не унижай музыку и не пиши рекламными штампами.
- `used_source_ids` содержит только номера реально использованных SOURCE.
- Пустое подтверждёнными данными поле лучше выдуманного.

Данные файла:
artist: {artist or 'не указан'}
title: {title or 'не указано'}
file_name: {file_name}

Материалы:
{evidence or 'Надёжные страницы не прочитаны.'}
'''.strip()


def _normalize_agent_profile(
    obj: Dict[str, Any],
    *,
    artist: str,
    title: str,
    file_name: str,
    model: str,
    research: Dict[str, Any],
) -> Dict[str, Any]:
    pages = [x for x in (research.get('pages') or []) if isinstance(x, dict)]
    used_ids = []
    for value in obj.get('used_source_ids') or []:
        try:
            source_id = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= source_id <= len(pages) and source_id not in used_ids:
            used_ids.append(source_id)
    source_display = (f'{artist} — {title}' if artist else title).strip(' —') or file_name
    out: Dict[str, Any] = {}
    for key in PROFILE_TEXT_FIELDS:
        out[key] = str(obj.get(key) or '').strip()[:1200]
    out['artist'] = out['artist'] or artist
    out['title'] = out['title'] or title or Path(file_name).stem
    out['source_display_name'] = out['source_display_name'] or source_display
    out['display_title'] = out['display_title'] or out['source_display_name']
    out['short_title_for_tts'] = out['short_title_for_tts'] or out['title']
    out['description'] = out['description'] or (
        f'{out["display_title"]}: профиль построен по имени файла; подтверждённого описания звучания пока нет.'
    )
    out['avoid'] = (
        out['avoid']
        + ' Не придумывать историю создания и не подменять музыку одноимённым фильмом, игрой, каналом или мемом.'
    ).strip()[:1200]
    out['sources'] = [str(pages[index - 1].get('url') or '') for index in used_ids]
    out['research_status'] = 'verified' if len(used_ids) >= 2 else ('partial' if used_ids else 'unverified')
    out['_cleanup_meta'] = {
        'schema_version': 'radio_track_profile_v2',
        'removed_time_mood_refs': True,
        'tts_title_goal': 'короткое, легко читаемое название для ведущего',
    }
    out['_original_web_meta'] = {
        'agent_queries': list(research.get('queries') or []),
        'agent_pages': [
            {
                'title': page.get('title') or page.get('search_title') or '',
                'url': page.get('url') or '',
                'excerpt': str(page.get('text') or '')[:1200],
            }
            for page in pages
        ],
        'used_source_ids': used_ids,
        'parsed_from_filename': {'artist': artist, 'title': title, 'file_name': file_name},
    }
    out['_model'] = model
    out['_created_ts'] = int(time.time())
    return out


def analyze_track_with_agent(cfg: Dict[str, Any], artist: str, title: str, file_name: str) -> Dict[str, Any]:
    base = str(cfg.get('lm_base_url', 'http://127.0.0.1:1234/v1')).rstrip('/')
    model = pick_model(base, str(cfg.get('track_analyzer_model') or cfg.get('lm_model') or 'local-model'))
    timeout = int(cfg.get('lm_timeout_sec', 90) or 90)

    def ask_model(messages: List[Dict[str, str]], max_tokens: int, temperature: float) -> str:
        return model_text(base, model, messages, max_tokens, temperature, timeout)

    research = research_track(artist, title, ask_model, cfg)
    evidence = _agent_evidence_text(research)
    draft_text = ask_model(
        [
            {
                'role': 'system',
                'content': (
                    'Ты исследователь музыкальной редакции. Извлекай сведения только из переданных страниц. '
                    'Любое фактическое утверждение должно иметь источник.'
                ),
            },
            {'role': 'user', 'content': _agent_profile_prompt(artist, title, file_name, evidence)},
        ],
        int(cfg.get('track_profiles_agent_max_tokens', 1800) or 1800),
        0.15,
    )
    draft = json_from_model_text(draft_text)
    verification_prompt = f'''
Проверь черновик профиля по исходным SOURCE. Удали или смягчи каждый факт, которого нет в материалах.
Сделай поля короткими и удобными для радиоведущего. Не копируй SOURCE дословно: перескажи и сожми.
Исправь подмену одноимённых объектов. Сохрани ровно ту же JSON-схему, включая used_source_ids.
Не добавляй знания из памяти. Верни только исправленный JSON.

ЧЕРНОВИК:
{json.dumps(draft, ensure_ascii=False, indent=2)}

SOURCE:
{evidence or 'Надёжные страницы не прочитаны.'}
'''.strip()
    try:
        checked = json_from_model_text(
            ask_model(
                [
                    {
                        'role': 'system',
                        'content': 'Ты строгий фактчекер. Оставляй только утверждения, подтверждённые SOURCE.',
                    },
                    {'role': 'user', 'content': verification_prompt},
                ],
                int(cfg.get('track_profiles_agent_max_tokens', 1800) or 1800),
                0.05,
            )
        )
    except Exception as exc:
        print('[TrackProfiles] fact-check pass failed, using grounded draft:', repr(exc), flush=True)
        checked = draft
    return _normalize_agent_profile(
        checked,
        artist=artist,
        title=title,
        file_name=file_name,
        model=model,
        research=research,
    )


def analyze_track(cfg: Dict[str,Any], artist: str, title: str, file_name: str) -> Dict[str,Any]:
    research_mode = str(cfg.get('track_profiles_research_mode', 'web_agent') or 'web_agent').strip().lower()
    if research_mode == 'web_agent' and cfg.get('track_profiles_web_lookup_enabled', True):
        return analyze_track_with_agent(cfg, artist, title, file_name)
    base = str(cfg.get('lm_base_url','http://127.0.0.1:1234/v1')).rstrip('/')
    model = pick_model(base, str(cfg.get('track_analyzer_model') or cfg.get('lm_model') or 'local-model'))
    mb = lookup_musicbrainz(cfg, artist, title)
    wiki = lookup_wikipedia(cfg, artist, title)
    wd = lookup_wikidata(cfg, artist, title) if not wiki else {}
    deezer = lookup_deezer(cfg, artist, title) if not (mb or wiki) else {}
    itunes = lookup_itunes(cfg, artist, title) if not (mb or wiki or deezer) else {}
    web_meta = {'musicbrainz': mb, 'wikipedia': wiki, 'wikidata': wd, 'deezer': deezer, 'itunes': itunes, 'parsed_from_filename': {'artist': artist, 'title': title, 'file_name': file_name}}
    web_text = json.dumps(web_meta, ensure_ascii=False, indent=2)
    safe_mode = str(cfg.get('track_profiles_fact_mode','web_then_lm')) == 'safe_lm_only'
    fact_rule = (
        'НЕ добавляй факты из памяти. Если веб-метаданных мало, напиши web_fact пустым или "нет надёжного факта". Не подменяй трек одноимённым телеканалом, фильмом, игрой или другим объектом.'
        if not safe_mode else
        'Не используй биографические/исторические факты; опиши только вероятный вайб по названию файла.'
    )
    prompt = f'''
Ты помощник локальной музыкальной радиостанции. Нужно сделать профиль трека, чтобы ведущие понимали музыку, знали следующий/предыдущий трек и говорили о музыке уважительно, с теплом и интересом.
Используй интернет-метаданные ниже. {fact_rule}
Если web_meta пустые или сомнительные, используй только parsed_from_filename: артист = {artist or 'не указан'}, название = {title or 'не указано'}. Не выдумывай автора, телеканал, студию или историю.
Если название/артист из файла написаны кириллицей, сохраняй кириллицу в описании и radio_angle. Не заменяй русское название латиницей из MusicBrainz/Wikipedia. Например: «Алюминиевые огурцы», а не «Aluminiovyye Ogurtsy».
Очень важно: профиль должен подталкивать ведущих хвалить трек и находить его сильные стороны. Не называй музыку "абсурдной", "странной", "слабой", "унылой", "сомнительной" или унизительной. Даже если трек шуточный/мемный/тяжёлый/меланхоличный — формулируй позитивно: "с характером", "атмосферный", "ироничный", "энергичный", "цепляющий", "для вечернего эфира".
Верни строго JSON без markdown с ключами:
{{
  "description":"НЕ ПУСТОЕ доброжелательное описание что это за музыка и чем она может быть хороша для эфира, 1-2 предложения",
  "artist_context":"кто автор/исполнитель; если знаем только из файла — так и напиши 'по имени файла: ...'",
  "web_fact":"короткий факт, который можно безопасно сказать в эфире; только если он есть в web_meta; иначе 'нет надёжного факта'",
  "mood":"настроение в позитивной формулировке",
  "energy":"темп/энергия без унижения трека",
  "genre":"жанр или вайб",
  "radio_angle":"как ведущему красиво и уважительно похвалить/подвести этот трек",
  "avoid":"чего не говорить/не выдумывать; обязательно запрети подменять песню одноимённым телеканалом/фильмом/другим объектом"
}}

Артист из файла: {artist or 'не указан'}
Название из файла: {title}
Файл: {file_name}
web_meta: {web_text}
'''.strip()
    payload = {
        'model': model,
        'messages': [
            {'role':'system','content':'Ты создаёшь русские доброжелательные профили треков для радиоведущего. Цель — помочь ведущим уважительно и интересно хвалить музыку. Не подменяй песню одноимёнными объектами. Только валидный JSON.'},
            {'role':'user','content':prompt},
        ],
        'temperature': 0.20,
        'max_tokens': 620,
        'stream': False,
    }
    data = request_json('POST', base + '/chat/completions', payload, timeout=int(cfg.get('lm_timeout_sec',90)))
    txt = str(((data.get('choices') or [{}])[0].get('message') or {}).get('content') or '').strip()
    if '```' in txt:
        txt = txt.replace('```json','').replace('```','').strip()
    start, end = txt.find('{'), txt.rfind('}')
    if start >= 0 and end > start:
        txt = txt[start:end+1]
    obj = json.loads(txt)
    out: Dict[str,Any] = {}
    for k in ['description','artist_context','web_fact','mood','energy','genre','radio_angle','avoid']:
        out[k] = str(obj.get(k,'')).strip()[:600]
    if not out.get('description'):
        who = artist or 'исполнитель из имени файла'
        name = title or file_name
        out['description'] = f'Трек {who} — {name}: доброжелательная музыкальная подводка с акцентом на настроение и характер композиции.'[:600]
    if artist and (not out.get('artist_context') or 'телеканал' in out.get('artist_context','').lower()):
        out['artist_context'] = f'По имени файла исполнитель/автор определяется как {artist}. Надёжных дополнительных фактов из интернета может не быть.'
    if has_cyrillic(title) or has_cyrillic(artist):
        out['source_display_name'] = (f'{artist} — {title}' if artist else title).strip(' —')
        out['avoid'] = (out.get('avoid','') + f' В эфире использовать кириллическое название из файла: {out["source_display_name"]}; не заменять его латиницей из внешних баз.').strip()[:600]
    if not out.get('web_fact'):
        out['web_fact'] = 'нет надёжного факта'
    negative_words = ['абсурд', 'уныл', 'сомнительн', 'слаб', 'плох', 'странненьк', 'нелеп']
    for k in ['description', 'mood', 'energy', 'radio_angle']:
        low = out.get(k, '').lower()
        if any(w in low for w in negative_words):
            out[k] = (out.get(k, '') + ' Формулировать в эфире только тепло и уважительно, подчёркивая характер и энергию трека.').strip()[:600]
    avoid = out.get('avoid','')
    if 'телеканал' not in avoid.lower():
        out['avoid'] = (avoid + ' Не подменять песню одноимённым телеканалом, фильмом, игрой или другим объектом.').strip()[:600]
    sources = []
    if mb:
        sources.append('MusicBrainz')
    if wiki:
        sources.append(str(wiki.get('url') or wiki.get('source') or 'Wikipedia'))
    if wd:
        sources.append(str(wd.get('url') or wd.get('source') or 'Wikidata'))
    if deezer:
        sources.append(str(deezer.get('link') or deezer.get('source') or 'Deezer'))
    if itunes:
        sources.append(str(itunes.get('url') or itunes.get('source') or 'iTunes Search'))
    source_display = (f'{artist} — {title}' if artist else title).strip(' —') or file_name
    out['display_title'] = source_display
    out['source_display_name'] = source_display
    out['artist'] = artist
    out['title'] = title or Path(file_name).stem
    out['short_title_for_tts'] = out['title']
    out['song_context'] = out.get('web_fact', '')
    out['creator_fact'] = out.get('artist_context', '')
    out['song_fact'] = out.get('web_fact', '')
    out['interesting_fact'] = out.get('web_fact', '')
    out['research_status'] = 'partial' if sources else 'unverified'
    out['sources'] = sources
    out['_cleanup_meta'] = {
        'schema_version': 'radio_track_profile_v2',
        'removed_time_mood_refs': True,
        'tts_title_goal': 'короткое, легко читаемое название для ведущего',
    }
    out['_original_web_meta'] = web_meta
    out['_model'] = model
    out['_created_ts'] = int(time.time())
    return out


def main() -> int:
    cfg = load_json(ROOT/'config.json', load_json(ROOT/'config.example.json', {}))
    music_dir = Path(str(cfg.get('music_dir','music')))
    if not music_dir.is_absolute():
        music_dir = ROOT / music_dir
    out_path = Path(str(cfg.get('track_profiles_file','cache/track_profiles.json')))
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    progress_path = Path(str(cfg.get('track_profiles_progress_file','cache/track_profiles_progress.json')))
    if not progress_path.is_absolute():
        progress_path = ROOT / progress_path
    profiles = load_json(out_path, {})
    if not isinstance(profiles, dict):
        profiles = {}
    tracks = [p for p in music_dir.rglob('*') if p.is_file() and p.suffix.lower() in MUSIC_EXTS]
    tracks.sort(key=lambda p: str(p).lower())
    limit = int(os.environ.get('AI_TRUCK_RADIO_TRACK_PROFILE_LIMIT','0') or '0')
    force = os.environ.get('AI_TRUCK_RADIO_TRACK_PROFILE_FORCE','0').lower() in {'1','true','yes'}
    enrich_missing = bool(cfg.get('track_profiles_enrich_missing_web_only', False))
    enrich_only_if_no_sources = bool(cfg.get('track_profiles_enrich_only_if_no_sources', True))
    pending = []
    for p in tracks:
        key = rel_key(p, music_dir)
        existing = profiles.get(key)
        if not force and isinstance(existing, dict) and (existing.get('description') or existing.get('radio_angle')):
            sources = existing.get('sources') if isinstance(existing.get('sources'), list) else []
            web_meta = existing.get('_original_web_meta') if isinstance(existing.get('_original_web_meta'), dict) else {}
            if not web_meta and isinstance(existing.get('_web_meta'), dict):
                web_meta = existing.get('_web_meta')
            has_wiki = bool((web_meta.get('wikipedia') or {}).get('url')) if isinstance(web_meta.get('wikipedia'), dict) else False
            has_wd = bool((web_meta.get('wikidata') or {}).get('url')) if isinstance(web_meta.get('wikidata'), dict) else False
            has_deezer = bool((web_meta.get('deezer') or {}).get('link')) if isinstance(web_meta.get('deezer'), dict) else False
            has_itunes = bool((web_meta.get('itunes') or {}).get('url')) if isinstance(web_meta.get('itunes'), dict) else False
            has_any_source = bool(sources or has_wiki or has_wd or has_deezer or has_itunes)
            # Важный режим: если профиль уже имеет sources/_original_web_meta, не трогаем его только из-за
            # web_fact='нет надёжного факта'. Иначе оно повторно лезло в сеть на уже описанные треки.
            if enrich_missing:
                if enrich_only_if_no_sources:
                    if not has_any_source:
                        pending.append(p)
                else:
                    web_fact = str(existing.get('web_fact') or '').strip().lower()
                    missing_web = (not has_any_source) and (not web_fact or 'нет над' in web_fact or web_fact in {'нет', 'none', 'n/a'})
                    if missing_web:
                        pending.append(p)
            continue
        pending.append(p)
    if limit:
        pending = pending[:limit]
    total = len(pending)
    done = 0
    print('[TrackProfiles] music_dir:', music_dir, flush=True)
    print('[TrackProfiles] output:', out_path, flush=True)
    print('[TrackProfiles] found:', len(tracks), 'pending:', total, 'force:', force, 'enrich_missing:', enrich_missing, 'enrich_only_if_no_sources:', enrich_only_if_no_sources, flush=True)
    for idx, p in enumerate(pending, 1):
        key = rel_key(p, music_dir)
        artist, title = parse_name(p)
        print(f'[TrackProfiles] PROGRESS {idx}/{total} {key}', flush=True)
        save_json(progress_path, {'current': idx, 'total': total, 'percent': int(idx*100/max(1,total)), 'detail': key, 'ts': int(time.time())})
        print('[TrackProfiles] analyzing:', key, 'artist=', artist, 'title=', title, flush=True)
        try:
            profiles[key] = analyze_track(cfg, artist, title, p.name)
            save_json(out_path, profiles)
            done += 1
        except Exception as e:
            print('[TrackProfiles] failed:', key, repr(e), flush=True)
            source_display = (f'{artist} — {title}' if artist else title).strip(' —') or p.name
            profiles[key] = {
                'display_title': source_display,
                'source_display_name': source_display,
                'artist': artist,
                'title': title or p.stem,
                'short_title_for_tts': title or p.stem,
                'description': f'Локальный трек: {artist + " — " if artist else ""}{title}. Надёжное интернет-описание не удалось получить, поэтому в эфире лучше говорить о настроении и энергии без фактов.',
                'artist_context': artist and f'По имени файла исполнитель/автор: {artist}.' or '',
                'song_context': '',
                'creator_fact': '',
                'song_fact': '',
                'web_fact': 'нет надёжного факта',
                'interesting_fact': '',
                'mood': 'позитивно подать по настроению композиции',
                'energy': 'оценивать мягко, без унижения трека',
                'genre': 'не определено',
                'radio_angle': 'подвести уважительно: отметить атмосферу, ритм или характер трека',
                'avoid': 'не выдумывать историю и биографию; не подменять песню одноимённым телеканалом/фильмом/другим объектом',
                'research_status': 'unverified',
                'sources': [],
                '_cleanup_meta': {
                    'schema_version': 'radio_track_profile_v2',
                    'removed_time_mood_refs': True,
                    'tts_title_goal': 'короткое, легко читаемое название для ведущего',
                },
                '_original_web_meta': {
                    'parsed_from_filename': {'artist': artist, 'title': title, 'file_name': p.name},
                },
                '_error': repr(e),
                '_created_ts': int(time.time()),
            }
            save_json(out_path, profiles)
    save_json(progress_path, {'current': total, 'total': total, 'percent': 100 if total else 0, 'detail': 'готово', 'ts': int(time.time())})
    print('[TrackProfiles] new/updated:', done, flush=True)
    print('[TrackProfiles] ready:', out_path, flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
