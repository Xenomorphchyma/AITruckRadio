# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Dict, List


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AITruckRadio/0.8"
SEARCH_URL = "https://search.yahoo.com/search?p="
SKIP_DOMAINS = {
    "facebook.com",
    "finance.yahoo.com",
    "instagram.com",
    "mail.yahoo.com",
    "pinterest.com",
    "search.yahoo.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "yahoo.com",
    "youtube.com",
}


class SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: List[Dict[str, str]] = []
        self.href = ""
        self.text: List[str] = []
        self.active = False

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        href = str(dict(attrs).get("href") or "")
        if tag == "a" and "r.search.yahoo.com/" in href and "/RU=" in href:
            self.href = href
            self.text = []
            self.active = True

    def handle_data(self, data: str) -> None:
        if self.active:
            self.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self.active:
            return
        match = re.search(r"/RU=([^/]+)/RK=", urllib.parse.urlparse(self.href).path)
        url = urllib.parse.unquote(match.group(1)) if match else ""
        title = re.sub(r"\s+", " ", "".join(self.text)).strip()
        if url.startswith(("http://", "https://")) and title:
            self.results.append({"url": url, "title": title})
        self.active = False


class PageParser(HTMLParser):
    blocked = {"script", "style", "noscript", "svg", "canvas", "nav", "footer", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.title = ""
        self.in_title = False
        self.chunks: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        if tag in self.blocked:
            self.depth += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self.blocked and self.depth:
            self.depth -= 1
        if tag == "title":
            self.in_title = False
        if tag in {"p", "div", "article", "section", "li", "h1", "h2", "h3", "br"}:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self.depth:
            return
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            if self.in_title:
                self.title = (self.title + " " + value).strip()
            self.chunks.append(value)


def _public_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False
        return True
    except Exception:
        return False


def _canonical_url(url: str) -> str:
    parsed = urllib.parse.urlparse(urllib.parse.urldefrag(url)[0])
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return urllib.parse.urlunparse(("https", host, parsed.path.rstrip("/") or "/", "", parsed.query, ""))


def _domain(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def _fetch(url: str, timeout: int, max_bytes: int) -> tuple[bytes, str]:
    if not _public_url(url):
        raise ValueError("non-public or unsupported URL")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:  # nosec B310
        if not _public_url(response.geturl()):
            raise ValueError("redirected to a non-public URL")
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if not any(x in content_type for x in ("text/html", "text/plain", "application/xhtml+xml")):
            raise ValueError(f"unsupported content type: {content_type}")
        return response.read(max_bytes + 1)[:max_bytes], content_type


def search_pages(query: str, timeout: int, limit: int) -> List[Dict[str, str]]:
    raw, _ = _fetch(SEARCH_URL + urllib.parse.quote_plus(query), timeout, 900_000)
    parser = SearchParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    out: List[Dict[str, str]] = []
    seen = set()
    for item in parser.results:
        url = _canonical_url(item["url"])
        domain = _domain(url)
        if not domain or domain in SKIP_DOMAINS or any(domain.endswith("." + item) for item in SKIP_DOMAINS):
            continue
        if url in seen or not _public_url(url):
            continue
        seen.add(url)
        out.append({"url": url, "title": item["title"]})
        if len(out) >= limit:
            break
    return out


def read_page(url: str, timeout: int, max_chars: int) -> Dict[str, str]:
    if not _public_url(url):
        raise ValueError("not a public URL")
    raw, content_type = _fetch(url, timeout, 1_500_000)
    charset_match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        decoded = raw.decode(charset, errors="replace")
    except LookupError:
        decoded = raw.decode("utf-8", errors="replace")
    if "text/plain" in content_type:
        title, text = "", decoded
    else:
        parser = PageParser()
        parser.feed(decoded)
        title = parser.title
        text = " ".join(parser.chunks)
    return {
        "url": url,
        "title": title[:300],
        "text": re.sub(r"\s+", " ", html.unescape(text)).strip()[:max_chars],
    }
