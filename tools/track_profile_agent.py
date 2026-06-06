# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AITruckRadio/0.7"
SEARCH_URL = "https://search.yahoo.com/search?p="
SKIP_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "pinterest.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "yahoo.com",
    "search.yahoo.com",
    "mail.yahoo.com",
    "finance.yahoo.com",
    "azlyrics.com",
    "genius.com",
    "lyricszoo.com",
    "songlyrics.com",
}


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: List[Dict[str, str]] = []
        self._href = ""
        self._text: List[str] = []
        self._in_result = False

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = str(values.get("class") or "")
        href = str(values.get("href") or "")
        is_duck_result = tag == "a" and "result__a" in classes
        is_yahoo_result = tag == "a" and "r.search.yahoo.com/" in href and "/RU=" in href
        if is_duck_result or is_yahoo_result:
            self._href = href
            self._text = []
            self._in_result = True

    def handle_data(self, data: str) -> None:
        if self._in_result:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._in_result:
            return
        title = re.sub(r"\s+", " ", "".join(self._text)).strip()
        url = _unwrap_search_url(self._href)
        if title and url:
            self.results.append({"title": title, "url": url})
        self._href = ""
        self._text = []
        self._in_result = False


class _ReadablePageParser(HTMLParser):
    BLOCKED = {"script", "style", "noscript", "svg", "canvas", "nav", "footer", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._blocked_depth = 0
        self._chunks: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        if tag in self.BLOCKED:
            self._blocked_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCKED and self._blocked_depth:
            self._blocked_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "article", "section", "main", "li", "h1", "h2", "h3", "br"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()
        self._chunks.append(text)

    def readable_text(self) -> str:
        text = " ".join(self._chunks)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        return text.strip()


def _unwrap_search_url(url: str) -> str:
    url = html.unescape(str(url or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    parsed = urllib.parse.urlparse(url)
    if "duckduckgo.com" in parsed.netloc:
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            url = urllib.parse.unquote(target)
    if "r.search.yahoo.com" in parsed.netloc:
        match = re.search(r"/RU=([^/]+)/RK=", parsed.path)
        if match:
            url = urllib.parse.unquote(match.group(1))
    return url if url.startswith(("http://", "https://")) else ""


def _public_web_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.lower().strip(".")
        if host == "localhost" or host.endswith(".local"):
            return False
        for info in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM):
            addr = ipaddress.ip_address(info[4][0])
            if not addr.is_global:
                return False
        return True
    except Exception:
        return False


def _domain(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def _canonical_url(url: str) -> str:
    parsed = urllib.parse.urlparse(urllib.parse.urldefrag(url)[0])
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query if host not in {"en.wikipedia.org", "ru.wikipedia.org"} else ""
    return urllib.parse.urlunparse(("https", host, path, "", query, ""))


def _fetch(url: str, timeout: int, max_bytes: int) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            "Accept-Language": "ru,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if not any(kind in content_type for kind in ("text/html", "application/xhtml+xml", "text/plain")):
            raise ValueError(f"unsupported content type: {content_type}")
        return response.read(max_bytes + 1)[:max_bytes], content_type


def search_web(query: str, *, timeout: int = 15, limit: int = 8) -> List[Dict[str, str]]:
    raw, _ = _fetch(SEARCH_URL + urllib.parse.quote_plus(query), timeout, 900_000)
    parser = _SearchParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    out: List[Dict[str, str]] = []
    seen = set()
    for item in parser.results:
        url = item["url"]
        domain = _domain(url)
        if not domain or domain in SKIP_DOMAINS or any(domain.endswith("." + x) for x in SKIP_DOMAINS):
            continue
        clean_url = _canonical_url(url)
        if clean_url in seen or not _public_web_url(clean_url):
            continue
        seen.add(clean_url)
        out.append({"title": item["title"], "url": clean_url, "domain": domain})
        if len(out) >= limit:
            break
    return out


def read_web_page(
    url: str,
    *,
    timeout: int = 15,
    max_bytes: int = 1_500_000,
    max_chars: int = 9_000,
) -> Dict[str, str]:
    if not _public_web_url(url):
        raise ValueError("URL is not a public web page")
    raw, content_type = _fetch(url, timeout, max_bytes)
    charset_match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        decoded = raw.decode(charset, errors="replace")
    except LookupError:
        decoded = raw.decode("utf-8", errors="replace")
    if "text/plain" in content_type:
        title = ""
        text = decoded
    else:
        parser = _ReadablePageParser()
        parser.feed(decoded)
        title = parser.title
        text = parser.readable_text()
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return {"url": url, "title": title[:300], "text": text[:max_chars], "domain": _domain(url)}


def _json_from_model(text: str) -> Dict[str, Any]:
    text = str(text or "").replace("```json", "").replace("```", "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    obj = json.loads(text)
    return obj if isinstance(obj, dict) else {}


def plan_queries(
    artist: str,
    title: str,
    ask_model: Callable[[List[Dict[str, str]], int, float], str],
    *,
    max_queries: int = 4,
) -> List[str]:
    fallback = [
        f'"{artist}" "{title}" song',
        f'"{artist}" "{title}" album',
        f'"{artist}" official biography',
    ]
    if not artist:
        fallback = [f'"{title}" song music', f'"{title}" track']
    messages = [
        {
            "role": "system",
            "content": (
                "Ты планировщик веб-исследования музыкального трека. "
                "Верни только JSON. Не отвечай фактами из памяти."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Артист из файла: {artist or 'неизвестен'}\nНазвание: {title}\n"
                "Составь до четырёх точных поисковых запросов. Нужны страницы об исполнителе, "
                "песне, альбоме или релизе. Избегай текстов песен, видео, соцсетей и одноимённых "
                "фильмов/игр. Формат: {\"queries\":[\"...\"]}"
            ),
        },
    ]
    try:
        obj = _json_from_model(ask_model(messages, 300, 0.1))
        queries = [str(x).strip() for x in obj.get("queries", []) if str(x).strip()]
    except Exception:
        queries = []
    # Exact filename-derived queries must win over a weak model that may
    # misspell the artist or title and consume the whole query budget.
    queries = fallback + queries
    out: List[str] = []
    seen = set()
    for query in queries:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            out.append(query)
        if len(out) >= max_queries:
            break
    return out


def _relevance_score(item: Dict[str, str], artist: str, title: str) -> int:
    hay = f"{item.get('title', '')} {item.get('url', '')}".casefold()
    artist_words = [x for x in re.findall(r"[\w']+", artist.casefold()) if len(x) > 2]
    title_words = [x for x in re.findall(r"[\w']+", title.casefold()) if len(x) > 2]
    score = sum(4 for word in artist_words if word in hay)
    score += sum(3 for word in title_words if word in hay)
    domain = item.get("domain", "")
    if any(x in domain for x in ("wikipedia.org", "bandcamp.com", "musicbrainz.org", "discogs.com")):
        score += 3
    if any(x in hay for x in ("lyrics", "текст песни", "movie", "film", "game", "игра")):
        score -= 5
    if any(x in hay for x in ("rugby", "football", "soccer", "politician", "actor", "athlete")):
        score -= 12
    return score


def _page_match_flags(page: Dict[str, str], artist: str, title: str) -> Dict[str, bool]:
    hay = f"{page.get('title', '')} {page.get('text', '')}".casefold()
    non_music = any(
        marker in hay
        for marker in (
            "rugby",
            "football",
            "soccer",
            "referee",
            "basketball",
            "politician",
            "actor biography",
            "athlete",
        )
    )
    music_signal = any(
        marker in hay
        for marker in (
            "music",
            "song",
            "track",
            "album",
            "single",
            "remix",
            "band",
            "dj",
            "producer",
            "recording",
            "музык",
            "песн",
            "трек",
            "альбом",
        )
    )
    artist_words = [x for x in re.findall(r"[\w']+", artist.casefold()) if len(x) > 2]
    title_words = [x for x in re.findall(r"[\w']+", title.casefold()) if len(x) > 2]
    artist_match = bool(artist_words) and all(word in hay for word in artist_words[:3])
    if non_music and not music_signal:
        artist_match = False
    title_match = bool(title_words) and all(word in hay for word in title_words)
    return {"artist_match": artist_match, "track_match": artist_match and title_match}


def research_track(
    artist: str,
    title: str,
    ask_model: Callable[[List[Dict[str, str]], int, float], str],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    timeout = int(cfg.get("track_profiles_agent_page_timeout_sec", 15) or 15)
    max_queries = max(1, int(cfg.get("track_profiles_agent_max_queries", 4) or 4))
    results_per_query = max(2, int(cfg.get("track_profiles_agent_search_results_per_query", 8) or 8))
    max_pages = max(1, int(cfg.get("track_profiles_agent_max_pages", 4) or 4))
    min_page_chars = max(100, int(cfg.get("track_profiles_agent_min_page_chars", 250) or 250))
    max_chars = max(1500, int(cfg.get("track_profiles_agent_page_chars", 9000) or 9000))
    queries = plan_queries(artist, title, ask_model, max_queries=max_queries)
    candidates: List[Dict[str, str]] = []
    seen = set()
    for query in queries:
        try:
            for item in search_web(query, timeout=timeout, limit=results_per_query):
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                item["query"] = query
                candidates.append(item)
        except Exception as exc:
            print(f"[TrackProfiles] web search failed for {query!r}: {exc!r}", flush=True)
    candidates.sort(key=lambda item: _relevance_score(item, artist, title), reverse=True)
    pages: List[Dict[str, str]] = []
    for item in candidates:
        if len(pages) >= max_pages:
            break
        try:
            page = read_web_page(item["url"], timeout=timeout, max_chars=max_chars)
            if len(page["text"]) < min_page_chars:
                continue
            page["query"] = item.get("query", "")
            page["search_title"] = item.get("title", "")
            page.update(_page_match_flags(page, artist, title))
            if not page["artist_match"]:
                continue
            pages.append(page)
            print(f"[TrackProfiles] read page: {page['url']}", flush=True)
        except Exception as exc:
            print(f"[TrackProfiles] page skipped {item['url']}: {exc!r}", flush=True)
    return {"queries": queries, "pages": pages}
